"""agentic/agent_loop.py — one turn: briefing -> render -> LLM -> tools -> persist.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "The Agent Loop",
"Memory, persistence, restart" and "Economics and the leash".

This is the only LLM-facing component in ``agentic``, and it is built so the LLM
is the *last* thing you need in order to test it. :class:`AgentLoop` is handed an
:class:`AgentClient`; :class:`ScriptedAgent` is a deterministic client that reads
from a list of replies and spends nothing. Every acceptance test for the loop runs
on ``ScriptedAgent``, an injected clock and a fake feed — no network, no model, no
money.

The turn algorithm (spec's six steps)
-------------------------------------
1. **Leash first.** ``store.check_leash(now)``. If the leash refuses, the turn never
   happened: return a refused outcome and record nothing.
2. **Gating.** A ``fire`` / ``boot`` / ``schedule`` trigger when ``agent.enabled``
   is false is refused (``reason="disabled"``). A ``request`` is *always* allowed —
   the human asked. Then ``store.expire_due(now)`` retires what timed out.
3. **Briefing + model-led perception.** ``prompts.build_briefing`` rebuilds the
   context fresh from the store, and the turn opens **text-only**: the system
   prompt + strategy, the briefing and the tool schemas — the model sees no
   image until it chooses the view and asks for its own render (which then
   counts toward :class:`~agentic.tools.ToolRegistry`'s render budget). A feed
   failure surfaces in-band, as a refused render call, never as a hard degrade.
4. **LLM + tool phase.** :meth:`AgentLoop._tool_phase` calls the client, executes its
   tool calls (bounded by ``MAX_TOOL_CALLS_PER_TURN``) and re-renders (bounded by
   ``MAX_RENDERS_PER_TURN``); it feeds the results back and calls again, up to a
   small round cap. Truncation is surfaced both to the model (a refused
   ``ToolResult``) and to the caller (``output["truncated"]``), never silent. A
   transport exception is caught: the turn is refused with
   ``client_error: ...`` (or ``bad_response: ...`` for a malformed reply), and if
   earlier rounds already cost money the spend is billed as a partial turn.
5. **Output.** :func:`_apply_output` applies the structured result — thesis,
   proposals — on top of the turn's notes. Applying it must never raise out of
   :meth:`run_turn`; a rejected mutation is captured in the turn's output.
6. **Persist + log.** ``store.record_turn`` then ``store.save``.

Steps 1 and 2 are shared with :meth:`AgentLoop.wake`/``boot`` through
:meth:`AgentLoop._gate`, so a refused wake can never consume the watchdog buffers.

Triggers on top of the algorithm:

* :meth:`AgentLoop.wake` — gate, then flush the Watchdog, then run a ``fire`` turn
  carrying its fires and expiries.
* :meth:`AgentLoop.boot` — gate, backfill the downtime so missed fires appear in
  the briefing (clearly marked retroactive), then run the mandatory ``boot`` turn.
"""
from __future__ import annotations

import json
import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from agentic import prompts
from agentic._time import as_aware, new_id
from agentic.feed import Feed
from agentic.models import Serde, Trigger
from agentic.renderer import RenderResult, Renderer
from agentic._dialect import coerce_bias as _coerce_bias
from agentic._dialect import coerce_proposal as _coerce_proposal
from agentic.store import (
    MAX_BARS,
    MAX_RENDERS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    MAX_SPEND_PER_DAY_USD,
    ContextStore,
    LeashExceeded,
    StoreError,
)
from agentic.strategy import is_mnsr_strategy
from agentic.tools import ToolCall, ToolRegistry, ToolResult
from agentic.watchdog import Watchdog

#: How many times the model may be asked again after a round of tool calls. Small
#: on purpose: a loop is a leash in itself.
MAX_TOOL_ROUNDS = 7

# --------------------------------------------------------------------------- #
# Chat-turn leash (AgentLoop.chat_turn)
# --------------------------------------------------------------------------- #
# A chat question must answer in seconds. The autonomous watcher's settings
# (config.settings AGENT_MAX_TOOL_ROUNDS, shipped at 400 for the staged MNSR
# workflow) would let a chatty model grind through minutes of tool rounds per
# message; the chat turn caps its own leash below, regardless of those settings.
CHAT_MAX_TOOL_ROUNDS = 4       # model round-trips per chat turn
CHAT_MAX_TOOL_CALLS = 10       # executed tool calls per chat turn
CHAT_MAX_RENDERS = 2           # chart renders per chat turn


def default_leash() -> Dict[str, int]:
    """How ``AgentLoop`` bounds a turn when nobody injected a leash: the shipped
    constants above. A live retune lives **outside** this module — the loop is a
    pure module and may not import ``config`` — so the (non-pure) service builds
    its loop with a leash callable that reads the ``AGENT_MAX_TOOL_CALLS`` /
    ``AGENT_MAX_TOOL_ROUNDS`` ``AGENT_MAX_RENDERS_PER_TURN`` settings, re-read
    per turn."""
    return {
        "tool_calls": MAX_TOOL_CALLS_PER_TURN,
        "rounds": MAX_TOOL_ROUNDS,
        "renders": MAX_RENDERS_PER_TURN,
    }

#: The instruction for the *closing call* — the one last, tool-less ask made when
#: the tool rounds ended without a structured object. Tool-calling loops and
#: reasoning runaways are a model behaviour, not a wiring fault: rather than let a
#: turn bill tokens and record nothing, we make exactly one more call with no
#: tools and no chart image, which is the shape these models reliably answer. It
#: fires only when there is nothing to lose (see ``_tool_phase``).
CLOSING_INSTRUCTION = (
    "Your previous response omitted the required thesis. End the turn now; you have "
    "no more tool calls to make. Reply with ONLY the "
    "strict JSON object defined in the output contract — no prose, no markdown "
    "fence, nothing before or after it. This closing call does not re-attach the "
    "chart image even when one rendered earlier in the turn: the chart's levels "
    "ride along as text in the briefing's `chart` block, so reason from those "
    "numbers rather than claiming no chart was available. Include a `thesis` object "
    "with a bias, a non-empty storyline, an explicit invalidation, and confidence. "
    "Bias describes observed market direction independently of entry readiness. Use "
    "neutral only when direction itself is genuinely unclear; no valid entry means "
    "no proposal, not neutral bias. Check invalidation against the latest completed "
    "candle and timestamp before describing it as pending."
)

CLOSING_SYSTEM_PROMPT = (
    "Close the existing analysis from the supplied chart summary and tool evidence. "
    "Do not call tools. Return only one JSON object with `thesis` containing `bias`, "
    "`storyline`, `levels_of_interest`, `invalidation`, and `confidence`; also include "
    "`proposals` (an empty array when no valid setup passed), `notes`, and `reasoning`. "
    "Never invent prices. Market bias describes current direction independently from "
    "entry readiness. Use neutral only when direction is genuinely unclear. If no valid "
    "setup passed, return no trade proposal and state which gate is missing. Check "
    "invalidation against the latest completed candle and timestamp; do not describe "
    "an already-broken level as pending. Follow the active strategy included below. "
    "For an Alchemist MSNR proposal, name the qualifying EM01–EM10 model and preserve "
    "its trigger and invalidation rules; if none triggered, return no proposal and name "
    "the next required event."
)

#: The single key the closing instruction is carried under in the briefing. It
#: holds a dict: the instruction plus a truthful ``image_seen_this_turn`` flag —
#: a turn whose tool rounds degenerated must not let the closing call honestly
#: believe no chart ever existed (replayed turns did exactly that and refused
#: to read).
CLOSING_KEY = "closing"

#: Whether the closing call is made at all. A knob so an operator can turn it off
#: (and so tests can pin either branch) without editing the loop.
CLOSING_CALL = True

_THESIS_KEYS = ("bias", "storyline", "levels_of_interest", "invalidation", "confidence")
_PROPOSAL_KEYS = (
    "bias",
    "setup",
    "entry",
    "sl",
    "tp",
    "invalidation",
    "confidence",
    "reason",
    "provenance",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pick(data: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    """Only the keys a store method accepts, dropping ``None`` placeholders."""
    return {k: v for k, v in data.items() if k in keys and v is not None}


def _normalise_note(note: Any, now: datetime) -> Dict[str, Any]:
    at = now.isoformat()
    if isinstance(note, dict):
        return {"at": str(note.get("at") or at), "text": str(note.get("text", ""))}
    return {"at": at, "text": str(note)}


def _one_line(text: Any, limit: int = 0) -> str:
    """Collapse whitespace (and optionally truncate) for a digest line."""
    flat = " ".join(str(text if text is not None else "").split())
    if limit and len(flat) > limit:
        return flat[: limit - 1].rstrip() + "…"
    return flat


def _has_thesis(output: Any) -> bool:
    """Whether model output satisfies the minimum durable-read contract."""
    thesis = output.get("thesis") if isinstance(output, dict) else None
    return bool(
        isinstance(thesis, dict)
        and str(thesis.get("storyline") or "").strip()
        and str(thesis.get("invalidation") or "").strip()
    )


def _has_thesis_tool_call(log: Sequence[Dict[str, Any]]) -> bool:
    """A successful set_thesis tool can fulfill the durable-read contract."""
    for entry in log or ():
        call = (entry or {}).get("call") or {}
        result = (entry or {}).get("result") or {}
        value = result.get("result") or {}
        if (
            call.get("name") == "set_thesis"
            and result.get("ok", True)
            and str(value.get("storyline") or "").strip()
            and str(value.get("invalidation") or "").strip()
        ):
            return True
    return False


def _workflow_state(log: Sequence[Dict[str, Any]], output: Any = None) -> Dict[str, bool]:
    """Return the concrete perception/action milestones completed this turn."""
    entries = list(log or ())
    view_at: Dict[str, int] = {}
    entry_tf: str = ""
    for index, entry in enumerate(entries):
        call = (entry or {}).get("call") or {}
        result = (entry or {}).get("result") or {}
        view = result.get("result") or {}
        if call.get("name") == "set_view" and result.get("ok", True):
            timeframe = str(view.get("timeframe") or "").upper()
            if view.get("layout", "single") == "single" and len(view.get("families") or []) <= 3:
                if timeframe not in view_at:
                    entry_tf = timeframe  # first timeframe viewed is the entry timeframe
                view_at[timeframe] = index

    rendered_at: Dict[str, int] = {}
    for index, entry in enumerate(entries):
        call = (entry or {}).get("call") or {}
        result = (entry or {}).get("result") or {}
        if call.get("name") != "render" or not result.get("ok", True):
            continue
        manifest = ((result.get("result") or {}).get("manifest") or {})
        timeframe = str(manifest.get("timeframe") or "").upper()
        if timeframe in view_at and index > view_at[timeframe]:
            rendered_at[timeframe] = index
    confirm_tf = next((tf for tf in ("H4", "H1") if tf in rendered_at), "")
    last_required_render = max(
        [rendered_at[tf] for tf in ("W1", "D1", confirm_tf) if tf in rendered_at],
        default=None,
    )
    context_complete = all(tf in rendered_at for tf in ("W1", "D1")) and bool(confirm_tf)
    liquidity_lookup_at = next((
        index for index, entry in enumerate(entries)
        if last_required_render is not None
        and index > last_required_render
        and ((entry or {}).get("call") or {}).get("name") == "level_lookup"
        and (((entry or {}).get("call") or {}).get("arguments") or {}).get("family") == "liquidity"
        and ((entry or {}).get("result") or {}).get("ok", True)
    ), None)

    lookup_matches: List[Dict[str, Any]] = []
    if liquidity_lookup_at is not None:
        value = ((entries[liquidity_lookup_at].get("result") or {}).get("result") or {})
        lookup_matches = [item for item in (value.get("matches") or []) if isinstance(item, dict)]
    liquidity_matches = [
        item for item in lookup_matches if item.get("status") in {"live", "swept"}
    ]
    pinned_keys = {
        str((((entry or {}).get("call") or {}).get("arguments") or {}).get("level_key") or "")
        for index, entry in enumerate(entries)
        if liquidity_lookup_at is not None and index > liquidity_lookup_at
        and ((entry or {}).get("call") or {}).get("name") == "add_pin"
        and ((entry or {}).get("result") or {}).get("ok", True)
    }
    pinned_timeframes = {
        str((((entry or {}).get("call") or {}).get("arguments") or {}).get("timeframe") or "").upper()
        for index, entry in enumerate(entries)
        if liquidity_lookup_at is not None and index > liquidity_lookup_at
        and ((entry or {}).get("call") or {}).get("name") == "add_pin"
        and ((entry or {}).get("result") or {}).get("ok", True)
    }
    lookup_timeframes = {str(item.get("timeframe") or "").upper() for item in liquidity_matches}
    pin_done = (
        not liquidity_matches
        or any(str(item.get("level_key") or "") in pinned_keys for item in liquidity_matches)
        or bool(pinned_timeframes & lookup_timeframes)
        or bool(pinned_keys)  # any pin added after lookup satisfies the pin step
    )
    proposals = output.get("proposals") if isinstance(output, dict) else None
    proposal_done = bool(proposals) or any(
        ((entry or {}).get("call") or {}).get("name") == "propose_trade"
        and ((entry or {}).get("result") or {}).get("ok", True)
        for entry in entries
    )
    watch_done = any(
        ((entry or {}).get("call") or {}).get("name") == "add_watch"
        and ((entry or {}).get("result") or {}).get("ok", True)
        for entry in entries
    )
    entry_view = bool(entry_tf)
    entry_render = bool(entry_tf) and entry_tf in rendered_at
    return {
        "context_view": context_complete,
        "render": context_complete,
        "w1_view": "W1" in view_at,
        "w1_render": "W1" in rendered_at,
        "d1_view": "D1" in view_at,
        "d1_render": "D1" in rendered_at,
        # Selecting the confirmation timeframe and rendering it are separate
        # workflow milestones. If both depend on ``rendered_at``, the required
        # tool remains set_view_confirm after a successful set_view and the
        # model loops on the same timeframe forever.
        "confirm_view": any(tf in view_at for tf in ("H4", "H1")),
        "confirm_render": bool(confirm_tf),
        "liquidity_lookup": liquidity_lookup_at is not None,
        "pin": pin_done,
        "entry_view": entry_view,
        "entry_render": entry_render,
        "entry_tf": entry_tf,
        "action": proposal_done or watch_done,
        "liquidity_found": bool(liquidity_matches),
        "confirm_tf": confirm_tf,
    }


def _workflow_pin_candidate(log: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Nearest actionable liquidity from the turn's required survey lookup."""
    for entry in reversed(list(log or ())):
        call = (entry or {}).get("call") or {}
        result = (entry or {}).get("result") or {}
        if (
            call.get("name") != "level_lookup"
            or ((call.get("arguments") or {}).get("family") != "liquidity")
            or not result.get("ok", True)
        ):
            continue
        body = result.get("result") or {}
        matches = [
            dict(item) for item in (body.get("matches") or [])
            if isinstance(item, dict) and item.get("status") in {"live", "swept"}
            and item.get("level_key") and item.get("timeframe")
        ]
        if not matches:
            return None
        primary_tf = ""
        for earlier in reversed(list(log or ())):
            earlier_call = (earlier or {}).get("call") or {}
            earlier_result = (earlier or {}).get("result") or {}
            if earlier_call.get("name") == "set_view" and earlier_result.get("ok", True):
                view = earlier_result.get("result") or {}
                primary_tf = str(view.get("timeframe") or "")
                break
        matches.sort(key=lambda item: (
            0 if str(item.get("timeframe")) == primary_tf else 1,
            abs(float(item.get("distance_points") or 0.0)),
            str(item.get("level_key") or ""),
        ))
        return matches[0]
    return None


def _required_workflow_tool(
    log: Sequence[Dict[str, Any]], output: Any = None, *, require_watch: bool = True
) -> str:
    """The turn cannot finish until the strategy's minimum inspection is done."""
    state = _workflow_state(log, output)

    # Count how many renders have succeeded at all. Once any render succeeded,
    # consider required renders done — the model has seen the chart. Forcing
    # more renders just loops and burns tokens.
    total_renders = sum(
        1 for entry in list(log or ())
        if ((entry or {}).get("call") or {}).get("name") == "render"
        and ((entry or {}).get("result") or {}).get("ok", True)
    )

    if not state["w1_view"]:
        return "set_view_w1"
    if not state["w1_render"] and total_renders == 0:
        return "render"
    if total_renders > 0:
        state["w1_render"] = True
    if not state["d1_view"]:
        return "set_view_d1"
    if not state["d1_render"] and total_renders == 0:
        return "render"
    if total_renders > 0:
        state["d1_render"] = True
    if not state["confirm_view"]:
        return "set_view_confirm"
    if not state["confirm_render"] and total_renders == 0:
        return "render"
    if total_renders > 0:
        state["confirm_render"] = True
    if not state["liquidity_lookup"]:
        return "level_lookup"
    if state["liquidity_found"] and not state["pin"]:
        # If at least one pin already succeeded, the pin step is satisfied —
        # don't loop forever pinning HTF levels that won't match the M15
        # lookup timeframe. Move on to the entry timeframe.
        pins_succeeded = any(
            ((entry or {}).get("call") or {}).get("name") == "add_pin"
            and ((entry or {}).get("result") or {}).get("ok", True)
            for entry in list(log or ())
        )
        if pins_succeeded:
            pass  # fall through to entry_render check
        else:
            return "add_pin"
    # After HTF context + liquidity, return to the entry timeframe to evaluate
    # the entry trigger (e.g. M15 CRT sweep/close-back) before concluding.
    entry_tf = str(state.get("entry_tf") or "")
    if entry_tf and not state.get("entry_render"):
        # If set_view_entry was already called but not rendered, render now —
        # don't loop on set_view_entry forever.
        entry_viewed = False
        for entry in list(log or ()):
            call = (entry or {}).get("call") or {}
            result = (entry or {}).get("result") or {}
            view_result = result.get("result") or {}
            if (
                call.get("name") == "set_view"
                and str(view_result.get("timeframe", "")).upper() == entry_tf
                and result.get("ok", True)
            ):
                entry_viewed = True
                break
        if entry_viewed:
            return "render"
        return f"set_view_entry:{entry_tf}"
    if require_watch and not state["action"]:
        return "add_watch"
    return ""


def _workflow_tools(registry: ToolRegistry, required: str) -> List[Dict[str, Any]]:
    """Copy the tool surface, tightening the currently required workflow step."""
    tools = copy.deepcopy(registry.schemas())
    by_name = {tool["name"]: tool for tool in tools}
    if required.startswith("set_view"):
        schema = by_name["set_view"]["parameters"]
        if required == "set_view_confirm":
            schema["properties"]["timeframe"]["enum"] = ["H4", "H1"]
            schema["required"] = ["timeframe", "families"]
        elif required.startswith("set_view_entry:"):
            # Dynamic entry timeframe (e.g. M15) with CRT+liquidity families
            entry_tf = required.split(":", 1)[1]
            schema["properties"]["timeframe"]["enum"] = [entry_tf]
            schema["properties"]["families"]["enum"] = [["crt", "bos", "liquidity"]]
            schema["required"] = ["timeframe", "families"]
        else:
            timeframe = {"set_view_w1": "W1", "set_view_d1": "D1"}.get(required)
            if timeframe:
                schema["properties"]["timeframe"]["enum"] = [timeframe]
                schema["required"] = ["timeframe", "families"]
    elif required == "level_lookup":
        schema = by_name["level_lookup"]["parameters"]
        schema["properties"]["family"]["enum"] = ["liquidity"]
        schema["required"] = ["family"]
    elif required == "add_pin":
        schema = by_name["add_pin"]["parameters"]
        schema["required"] = ["level_key", "timeframe", "reason"]
    return tools


def _tool_choice(name: str) -> Dict[str, Dict[str, str]]:
    if name.startswith("set_view_"):
        name = "set_view"
    elif name.startswith("set_view_entry:"):
        name = "set_view"
    return {"type": "function", "function": {"name": name}}


def _evidence_digest(log: Sequence[Dict[str, Any]], *, per_result: int = 600) -> str:
    """The turn's tool activity as a compact **text** block.

    Used only by the closing call: the assistant/tool message pair cannot be
    replayed without a ``tools`` array, and the raw ``render`` manifest is exactly
    the bulk that provokes a reasoning runaway — so each result is flattened to a
    single truncated line. Returns ``""`` for a turn that called no tools.
    """
    lines: List[str] = []
    for entry in log or ():
        call = (entry or {}).get("call") or {}
        result = (entry or {}).get("result") or {}
        name = _one_line(call.get("name") or "?", 60) or "?"
        args = _one_line(json.dumps(call.get("arguments") or {}, ensure_ascii=False, default=str), 200)
        if result.get("ok", True) is False:
            outcome = "ERROR: " + _one_line(result.get("error") or "failed", per_result)
        else:
            body = result.get("result")
            outcome = _one_line(
                json.dumps(body, ensure_ascii=False, default=str) if body is not None else "(ok)",
                per_result,
            )
        lines.append(f"- {name}({args}) -> {outcome}")
    return "\n".join(lines)


def _manifest_digest(manifest: Optional[Dict[str, Any]], *, max_lines: int = 160) -> str:
    """The last render's manifest as the compact **text** a closing call reads.

    The closing call is image-less by design, and the tool log it digest is often
    just a ``set_view`` — so a turn whose rounds degenerated used to close with
    the model honestly holding no numbers at all. This is the image's numbers:
    one line per drawn tag (live levels first — they are the actionable ones),
    capped with a ``+N more`` tail so a huge manifest cannot balloon the rescue
    call that exists to *prevent* ballooning. Returns ``""`` when nothing rendered.
    """
    manifest = manifest or {}
    tags = manifest.get("tags") or {}
    entries = [entry for entry in tags.values() if isinstance(entry, dict)] if isinstance(tags, dict) else []

    def _order(entry: Dict[str, Any]) -> tuple:
        return (0 if entry.get("status") == "live" else 1, str(entry.get("tag") or ""))

    lines: List[str] = []

    def add_candle_context(context: Any, timeframe: str) -> None:
        if not isinstance(context, dict):
            return
        completed = context.get("latest_completed_bar")
        latest = context.get("latest_bar")
        if isinstance(completed, dict):
            lines.append(
                f"- Latest completed {timeframe} candle: "
                f"time={completed.get('time')} O={completed.get('open')} "
                f"H={completed.get('high')} L={completed.get('low')} "
                f"C={completed.get('close')}"
            )
        if isinstance(latest, dict) and context.get("latest_bar_may_be_open"):
            lines.append(
                f"- Current possibly-forming {timeframe} candle: "
                f"time={latest.get('time')} O={latest.get('open')} "
                f"H={latest.get('high')} L={latest.get('low')} "
                f"C={latest.get('close')} (do not use its close to confirm invalidation)"
            )

    panes = manifest.get("panes") or []
    if panes:
        for pane in panes:
            if isinstance(pane, dict):
                add_candle_context(pane.get("bars_context"), str(pane.get("timeframe") or "?"))
    else:
        add_candle_context(
            manifest.get("bars_context"), str(manifest.get("timeframe") or "?")
        )
    for entry in sorted(entries, key=_order):
        band = ""
        low, high = entry.get("price_low"), entry.get("price_high")
        if low is not None and high is not None:
            band = f" band {low}-{high}"
        distance = entry.get("distance_points")
        distance_s = f" ({distance:+g} pts)" if isinstance(distance, (int, float)) else ""
        label = str(entry.get("label") or "")
        if label:
            # The image's word may repeat across levels (three ``CRT`` lines on
            # one pane); the unique manifest tag in parentheses is the bridge.
            name = f"{label} ({entry.get('tag')})"
            lines.append(
                f"- {name} {entry.get('timeframe')} "
                f"{entry.get('direction')} {entry.get('price')}{band} "
                f"{entry.get('status')}{distance_s}"
            )
        else:
            lines.append(
                f"- {entry.get('tag')} {entry.get('family')} {entry.get('timeframe')} "
                f"{entry.get('direction')} {entry.get('price')}{band} "
                f"{entry.get('status')}{distance_s}"
            )
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [
            f"- (+{len(lines) - max_lines} more candle/level evidence lines; render for the full manifest)"
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The wire shapes
# --------------------------------------------------------------------------- #

@dataclass
class AgentRequest(Serde):
    """Everything one model call receives. Rebuilt fresh each turn."""

    turn_id: str = ""
    trigger: str = ""
    trigger_detail: str = ""
    system_prompt: str = ""
    briefing: Dict[str, Any] = field(default_factory=dict)
    image_path: str = ""
    manifest: Dict[str, Any] = field(default_factory=dict)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    #: Strategy turns use a required staged tool sequence before they can finish;
    #: turns without a Phoenix playbook keep the ordinary set_view-first contract.
    tool_choice: Any = "auto"
    tool_results: List[ToolResult] = field(default_factory=list)  # fed back on the next round
    #: The calls whose results are in ``tool_results``, in the same order. A real
    #: client (``agentic.llm``) uses this to rebuild the assistant ``tool_calls``
    #: message that precedes the ``tool`` results on the wire.
    tool_calls_made: List[ToolCall] = field(default_factory=list)


@dataclass
class AgentReply(Serde):
    """What one model call returns: tool calls and/or a structured output."""

    tool_calls: List[ToolCall] = field(default_factory=list)
    output: Dict[str, Any] = field(default_factory=dict)
    text: str = ""
    tokens: Dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    #: The provider's ``finish_reason`` (e.g. ``tool_calls``/``stop``), recorded for
    #: debugging. The loop ignores it; it is not a control input.
    finish_reason: str = ""


class AgentClient(Protocol):
    """The one method the loop needs from a model (or a mock)."""

    def complete(self, request: AgentRequest) -> AgentReply: ...


class ScriptedAgent:
    """A deterministic mock agent: a list of replies, or a request -> reply callable.

    Zero API spend. Every request it saw is recorded on ``requests``, so a test can
    inspect exactly what briefing and tools the loop assembled. When the script is
    exhausted (or the callable is not given a script) it *falls silent*: it returns
    an empty :class:`AgentReply` — no tool calls, no output — which the loop reads
    as "the model has nothing more to say" and stops. That is the documented
    default; a test can rely on it.
    """

    def __init__(self, script: Any):
        if callable(script):
            self._script: List[AgentReply] = []
            self._callable: Optional[Callable[[AgentRequest], AgentReply]] = script
        else:
            self._script = list(script)
            self._callable = None
        self._index = 0
        self.requests: List[AgentRequest] = []

    def complete(self, request: AgentRequest) -> AgentReply:
        self.requests.append(request)
        if self._callable is not None:
            return self._callable(request)
        if self._index < len(self._script):
            reply = self._script[self._index]
            self._index += 1
            return reply
        return AgentReply()  # script exhausted: the model fell silent


@dataclass
class TurnOutcome(Serde):
    """The result of one turn — the debugging surface of the loop.

    ``tool_calls`` counts every call the model emitted this turn, executed *or*
    refused by the cap (the log records both, so the two agree). ``image_path`` and
    ``manifest`` are the **final** render of the turn, not the initial one.
    """

    turn_id: str = ""
    trigger: str = ""
    ok: bool = True
    reason: str = ""
    renders: int = 0
    tool_calls: int = 0
    output: Dict[str, Any] = field(default_factory=dict)
    image_path: str = ""
    manifest: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatTurnResult(Serde):
    """The result of one free-form chat turn.

    Unlike :class:`TurnOutcome`, this carries the assistant's *raw text* so a
    chat UI can show a straight conversation. Tool calls, renders and the final
    image are included so the UI can surface evidence alongside the reply.
    """

    turn_id: str = ""
    ok: bool = True
    reason: str = ""
    response: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    renders: int = 0
    image_path: str = ""
    manifest: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _ToolPhase:
    """The outcome of step 4 (the LLM + tool phase), before output is applied."""

    reply: AgentReply = field(default_factory=AgentReply)
    log: List[Dict[str, Any]] = field(default_factory=list)
    truncations: List[str] = field(default_factory=list)
    tokens: int = 0
    cost: float = 0.0
    renders: int = 0
    #: Set when the model call itself failed (a transport exception). A failed
    #: phase is never logged: the turn did not happen.
    error: str = ""
    recoverable: bool = False


# --------------------------------------------------------------------------- #
# Applying the structured output
# --------------------------------------------------------------------------- #

def _apply_output(
    store: ContextStore,
    output: Dict[str, Any],
    now: datetime,
) -> Tuple[Dict[str, Any], List[str]]:
    """Apply the model's thesis and proposals to the store. **Never raises.**

    Returns ``(output, apply_errors)``. A rejected mutation is recorded in
    ``apply_errors`` instead of propagating, so one bad field cannot lose the whole
    turn — the model sees what it got wrong and can fix it next turn.
    """
    apply_errors: List[str] = []
    thesis = output.get("thesis")
    if isinstance(thesis, dict):
        picked = _pick(thesis, _THESIS_KEYS)
        if "bias" in picked:
            picked["bias"] = _coerce_bias(picked["bias"])
            # Record the read-back dialect so the turn log shows what was applied,
            # not just what arrived.
            if picked["bias"] != thesis.get("bias"):
                output.setdefault("dialect", {})["thesis_bias"] = picked["bias"]
        try:
            store.set_thesis(**picked, now=now)
        except (StoreError, TypeError, ValueError) as exc:
            apply_errors.append(f"thesis: {exc}")
    for proposal in output.get("proposals") or []:
        if not isinstance(proposal, dict):
            apply_errors.append(f"proposal: not an object: {proposal!r}")
            continue
        try:
            store.add_proposal(**_coerce_proposal(proposal, _PROPOSAL_KEYS), now=now)
        except (StoreError, TypeError, ValueError) as exc:
            apply_errors.append(f"proposal: {exc}")
    return output, apply_errors


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #

def _truncate(text: Any, limit: int = 200) -> str:
    """One-line, length-capped text for a refusal reason (never leak a payload)."""
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _failure_reason(exc: BaseException) -> str:
    """``bad_response:`` for a :class:`~agentic.llm.ResponseError`, else ``client_error:``.

    The type name and a truncated message only — an exception's text can carry a
    request body or a key, so it is capped and never stored verbatim.
    """
    # Imported locally: ``agentic.llm`` imports this module, so a module-level
    # import would be circular; by the time a turn runs, both modules are loaded.
    from agentic.llm import ResponseError

    label = "bad_response" if isinstance(exc, ResponseError) else "client_error"
    return f"{label}: {type(exc).__name__}: {_truncate(exc)}"


def _execute_tool_call(
    registry: ToolRegistry,
    call: ToolCall,
    executed: int,
    truncations: List[str],
    log: List[Dict[str, Any]],
    tool_cap: int,
) -> Tuple[ToolResult, int]:
    """Run one tool call, or refuse it at the per-turn cap.

    Returns ``(result, executed_count)`` so the caller can keep the running count.
    A call beyond ``tool_cap`` becomes an ``ok=False`` result in the
    log and in what the model sees next — visible on both sides, never dropped.
    """
    if executed >= tool_cap:
        truncations.append("tool_calls")
        result = ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=False,
            error=f"tool_cap: {tool_cap} tool calls per turn",
        )
    else:
        result = registry.execute(call)
        executed += 1
        if call.name == "render" and not result.ok:
            truncations.append("renders")
    log.append({"call": call.to_dict(), "result": result.to_dict()})
    return result, executed


class AgentLoop:
    """Drives one turn at a time over a store, a feed, a renderer and a client."""

    def __init__(
        self,
        store: ContextStore,
        feed: Feed,
        renderer: Renderer,
        client: AgentClient,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        watchdog: Optional[Watchdog] = None,
        playbook: str = "",
        activity: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        leash: Optional[Callable[[], Dict[str, int]]] = None,
        families: Optional[Callable[[], Sequence[str]]] = None,
        checkpoint: Optional[Callable[[Optional[Dict[str, Any]]], None]] = None,
    ):
        self.store = store
        self.feed = feed
        self.renderer = renderer
        self.client = client
        self._clock = clock or getattr(store, "_clock", None) or _utcnow
        self._watchdog = watchdog
        self._activity = activity
        # The leash is injected so a non-pure layer can retune the caps live
        # (config.settings); the loop itself stays free of any config import.
        self._leash_of = leash or default_leash
        # The operator's enabled indicator families (settings tab), injected the
        # same way: read fresh at each turn start, so a settings toggle applies
        # on the next turn without a restart. ``None`` (no callable) = all
        # families — the shipped default and the degraded fallback.
        self._families_of = families
        self._checkpoint = checkpoint
        # The operator's strategy (strategies/*.md via agentic.strategy), fixed
        # for this loop's lifetime: a turn never mixes strategies.
        self._playbook = str(playbook or "")
        # Chat turns run with this False→True swap (scoped, under the turn
        # lock): a chat turn must never trigger the MNSR staged-workflow
        # forcing in _tool_phase — the agent reads the operator's intent and
        # picks its own tools (or none), instead of being handed a required
        # set_view/render/lookup/pin/watch sequence.
        self._chat_mode = False

    # ------------------------------------------------------------------ families

    def _enabled_families(self) -> Optional[List[str]]:
        """The operator's enabled indicator families for this turn.

        Read fresh from the injected callable (settings tab state), so a toggle
        applies on the next turn with no restart. A broken callable degrades to
        ``None`` — every family — exactly like a broken leash degrades to the
        shipped caps.
        """
        if self._families_of is None:
            return None
        try:
            return list(self._families_of())
        except Exception:  # noqa: BLE001 — a broken knob must not brick a turn
            return None

    # ------------------------------------------------------------------ gate

    def _gate(
        self, trigger: str, now: datetime, *, continuation: bool = False
    ) -> Optional[TurnOutcome]:
        """Steps 1-2: validate the trigger, check the leash, apply the kill switch.

        Returns the refusal :class:`TurnOutcome`, or ``None`` when the turn may run.
        Extracted so :meth:`wake` can refuse a turn *before* flushing the Watchdog:
        a flush empties the coalescing buffers, so an ungated flush would lose the
        fire permanently (the spec's "do not lose events" invariant).
        """
        try:
            trigger_enum = Trigger(trigger)
        except ValueError:
            return TurnOutcome(trigger=str(trigger), ok=False, reason="bad_trigger")

        # 1. Leash first: a refused turn never happened.
        try:
            self.store.check_leash(now)
        except LeashExceeded as exc:
            if continuation and self.store.data.budget.spend_usd_today >= MAX_SPEND_PER_DAY_USD:
                return TurnOutcome(
                    trigger=trigger_enum.value,
                    ok=False,
                    reason="leash:max_spend_per_day",
                    output={"resumable": True, "resume_blocked": "daily_spend_cap"},
                )
            if not continuation:
                return TurnOutcome(trigger=trigger_enum.value, ok=False, reason=f"leash:{exc.reason}")
            # A saved run is the same logical turn: do not strand it behind
            # interval/hour/day turn-count gates. The daily spend cap still wins.

        # 2. Gating: fire/boot/schedule need an armed agent; request never does.
        if trigger_enum is not Trigger.REQUEST and not self.store.data.agent.enabled:
            return TurnOutcome(trigger=trigger_enum.value, ok=False, reason="disabled")
        return None

    # ------------------------------------------------------------------ triggers

    def wake(self) -> Optional[TurnOutcome]:
        """Gate first, then flush the Watchdog; run a ``fire`` turn if it emitted."""
        if self._watchdog is None:
            return None
        now = as_aware(self._clock())
        refusal = self._gate(Trigger.FIRE.value, now)
        if refusal is not None:
            return refusal  # buffers are intact: the flush never ran
        request = self._watchdog.flush(trigger=Trigger.FIRE.value, now=now)
        if request is None:
            return None
        return self.run_turn(
            trigger=Trigger.FIRE.value,
            detail=request.reason,
            fires=request.fires,
            expired=request.expired,
        )

    def boot(self) -> TurnOutcome:
        """Gate first, backfill the downtime, then run the mandatory boot turn."""
        now = as_aware(self._clock())
        refusal = self._gate(Trigger.BOOT.value, now)
        if refusal is not None:
            return refusal
        retroactive: Sequence[Any] = ()
        if self._watchdog is not None:
            retroactive = self._watchdog.backfill(self.store, now=now).fires
        return self.run_turn(
            trigger=Trigger.BOOT.value,
            detail="server start",
            retroactive=retroactive,
        )

    # ------------------------------------------------------------------ step 4

    def _emit_activity(self, event: str, **payload: Any) -> None:
        if self._activity is None:
            return
        try:
            self._activity(event, payload)
        except Exception:
            # UI telemetry must never interrupt an agent turn.
            pass

    def _tool_phase(
        self,
        registry: ToolRegistry,
        request: AgentRequest,
        *,
        resume_state: Optional[Dict[str, Any]] = None,
    ) -> _ToolPhase:
        """Step 4: call the model, execute its tools, feed results back, repeat.

        Bounded twice over: ``MAX_TOOL_CALLS_PER_TURN`` executed calls per turn and
        ``MAX_TOOL_ROUNDS`` model calls. A call beyond the cap is **not dropped
        silently** — it becomes an ``ok=False`` :class:`ToolResult` in the log and in
        the results the model sees next, so the truncation is visible on both sides.

        The model call is hardened: an exception becomes ``_ToolPhase.error``
        (``client_error: ...`` / ``bad_response: ...``) rather than propagating. On
        that path the spend and log of the rounds that already succeeded are kept
        on the returned phase, so :meth:`run_turn` can bill a partial turn. The
        calls whose results were fed back are recorded on
        ``request.tool_calls_made``, in order, for the wire layer.
        """
        resume_state = dict(resume_state or {})
        log: List[Dict[str, Any]] = list(resume_state.get("log") or [])
        truncations: List[str] = list(resume_state.get("truncations") or [])
        tokens = int(resume_state.get("tokens") or 0)
        cost = float(resume_state.get("cost") or 0.0)
        executed = len(log)
        reply = AgentReply()
        deferred_output: Dict[str, Any] = dict(resume_state.get("deferred_output") or {})
        start_round = max(0, int(resume_state.get("next_round") or 0))
        # The staged MNSR workflow is a watcher-turn contract. A chat turn
        # (_chat_mode) answers the operator's actual question: the model reads
        # the intent and may call tools or not — the harness never forces one,
        # and never fabricates workflow fallback calls on its behalf.
        require_watch = (not self._chat_mode) and is_mnsr_strategy(self._playbook)
        # The model round budget is a settings knob (AGENT_MAX_TOOL_ROUNDS),
        # re-read per turn so the user's edits apply without a restart.
        # leash read encompassing the turn's caps: {tool_calls, rounds, renders},
        # injected (config lives outside the pure core) and validated here so a
        # bad setting can never unbound the loop. (The render bound is consumed
        # by the registry constructed in run_turn — same leash, same rule.)
        bounds = self._leash_of()
        try:
            tool_cap = max(1, int(bounds.get("tool_calls", MAX_TOOL_CALLS_PER_TURN)))
        except (TypeError, ValueError):
            tool_cap = MAX_TOOL_CALLS_PER_TURN
        try:
            rounds = max(1, int(bounds.get("rounds", MAX_TOOL_ROUNDS)))
        except (TypeError, ValueError):
            rounds = MAX_TOOL_ROUNDS
        # A resumed analysis receives one fresh bounded segment. The absolute
        # round index remains in telemetry/checkpoints so repeated resumes never
        # replay earlier calls, while each invocation still obeys the 400 cap.
        for round_index in range(start_round, start_round + rounds):
            if self._checkpoint is not None:
                self._checkpoint({
                    "turn_id": request.turn_id,
                    "trigger": request.trigger,
                    "detail": request.trigger_detail,
                    "request": request.to_dict(),
                    "log": log,
                    "truncations": truncations,
                    "tokens": tokens,
                    "cost": cost,
                    "next_round": round_index,
                    "deferred_output": deferred_output,
                    "renders": registry.renders_used(),
                    "last_result": registry.last_result.to_dict() if registry.last_result else None,
                    "notes": registry.notes(),
                })
            if self.store.data.budget.spend_usd_today >= MAX_SPEND_PER_DAY_USD:
                self._emit_activity(
                    "analysis_paused",
                    turn_id=request.turn_id,
                    reason="daily_spend_cap",
                    round=round_index + 1,
                )
                return _ToolPhase(
                    reply=reply,
                    log=log,
                    truncations=list(dict.fromkeys(truncations + ["spend_cap"])),
                    tokens=tokens,
                    cost=cost,
                    renders=registry.renders_used(),
                    error="leash:max_spend_per_day",
                    recoverable=self._checkpoint is not None,
                )
            required_before_call = _required_workflow_tool(
                log, deferred_output, require_watch=require_watch
            ) if require_watch else ""
            if required_before_call:
                request.tools = _workflow_tools(registry, required_before_call)
                request.tool_choice = _tool_choice(required_before_call)
                request.briefing["workflow_required"] = required_before_call
            self._emit_activity(
                "model_call_started",
                turn_id=request.turn_id,
                round=round_index + 1,
            )
            try:
                # A per-call snapshot: the request object is updated between
                # rounds (tools, image, briefing), so the client records what
                # THIS call actually saw — the model-led turn's history is
                # honest instead of every record showing the last round.
                call_request = replace(
                    request,
                    manifest=dict(request.manifest or {}),
                    briefing=dict(request.briefing or {}),
                    tool_results=list(request.tool_results or []),
                    tool_calls_made=list(request.tool_calls_made or []),
                )
                reply = self.client.complete(call_request)
            except Exception as exc:  # noqa: BLE001 — a failed model call must not crash the loop
                return _ToolPhase(
                    reply=reply,
                    log=log,
                    truncations=list(dict.fromkeys(truncations)),
                    tokens=tokens,
                    cost=cost,
                    renders=registry.renders_used(),
                    error=_failure_reason(exc),
                    recoverable=self._checkpoint is not None,
                )
            self._emit_activity(
                "model_response",
                turn_id=request.turn_id,
                round=round_index + 1,
                tool_calls=len(reply.tool_calls),
                finish_reason=str(reply.finish_reason or ""),
                output_fields=sorted((reply.output or {}).keys()),
            )
            tokens += sum(int(v or 0) for v in (reply.tokens or {}).values())
            cost += float(reply.cost_usd or 0.0)
            if reply.output and str(reply.finish_reason or "").lower() != "length":
                deferred_output.update(dict(reply.output))
            if not reply.tool_calls:
                if str(reply.finish_reason or "").lower() == "length":
                    continuation = str(reply.text or "")[-6000:]
                    request.briefing["resume_notice"] = (
                        "The previous model completion reached its per-call generation limit and "
                        "was cut off before producing a complete analysis. Continue the existing "
                        "analysis from the saved evidence, avoid repeating completed tools, and "
                        "return a concise complete structured thesis."
                    )
                    if continuation:
                        request.briefing["cutoff_response"] = continuation
                    truncations.append("generation_length")
                    if self._checkpoint is not None:
                        self._checkpoint({
                            "turn_id": request.turn_id,
                            "trigger": request.trigger,
                            "detail": request.trigger_detail,
                            "request": request.to_dict(),
                            "log": log,
                            "truncations": truncations,
                            "tokens": tokens,
                            "cost": cost,
                            "next_round": round_index + 1,
                            "deferred_output": deferred_output,
                            "renders": registry.renders_used(),
                            "last_result": registry.last_result.to_dict() if registry.last_result else None,
                            "notes": registry.notes(),
                        })
                    reply.output = dict(deferred_output)
                    # Don't return early: fall through to the closing call so the
                    # model still gets one tool-less, image-less ask for the
                    # structured thesis it was cut off before producing.
                    break
                required = _required_workflow_tool(
                    log, deferred_output, require_watch=require_watch
                ) if require_watch else ""
                if required in {"level_lookup", "add_pin", "add_watch"} and round_index + 1 < start_round + rounds:
                    fallback_call: Optional[ToolCall] = None
                    if required == "level_lookup":
                        view = self.store.data.view
                        context_tf = str(view.timeframe)
                        fallback_call = ToolCall(
                            call_id=new_id("workflow_lookup"),
                            name="level_lookup",
                            arguments={"family": "liquidity", "timeframe": context_tf},
                        )
                    elif required == "add_pin":
                        candidate = _workflow_pin_candidate(log)
                        if candidate:
                            fallback_call = ToolCall(
                                call_id=new_id("workflow_pin"),
                                name="add_pin",
                                arguments={
                                    "level_key": candidate["level_key"],
                                    "timeframe": candidate["timeframe"],
                                    "reason": "MSNR context liquidity: preserve the live/swept pool across timeframe views",
                                },
                            )
                    else:
                        view = self.store.data.view
                        setup_tf = str(view.timeframe)
                        fallback_call = ToolCall(
                            call_id=new_id("workflow_watch"),
                            name="add_watch",
                            arguments={
                                "condition": "bos_forms",
                                "params": {"timeframe": setup_tf},
                                "ttl_hours": 12.0,
                                "reason": "MSNR fallback: wait for a setup-frame BOS before the next trade assessment",
                            },
                        )
                    if fallback_call is not None:
                        self._emit_activity(
                            "tool_call", turn_id=request.turn_id,
                            call_id=fallback_call.call_id, name=fallback_call.name,
                            arguments=dict(fallback_call.arguments), source="workflow_fallback",
                        )
                        result, executed = _execute_tool_call(
                            registry, fallback_call, executed, truncations, log, tool_cap
                        )
                        log[-1]["source"] = "workflow_fallback"
                        self._emit_activity(
                            "tool_result", turn_id=request.turn_id,
                            call_id=fallback_call.call_id, name=fallback_call.name,
                            ok=result.ok, preview=(result.error or repr(result.result))[:1200],
                            source="workflow_fallback",
                        )
                        request.tool_calls_made.append(fallback_call)
                        request.tool_results.append(result)
                        request.tools = registry.schemas()
                        request.tool_choice = "auto"
                        workflow_action = {
                            "level_lookup": "The system looked up the required context liquidity family.",
                            "add_pin": "The system pinned the nearest live/swept higher-timeframe liquidity level.",
                            "add_watch": "The system added a conservative watch because no trade proposal or watch was returned before the required workflow step ended.",
                        }
                        request.briefing["workflow_action"] = workflow_action[fallback_call.name]
                        if self._checkpoint is not None:
                            self._checkpoint({
                                "turn_id": request.turn_id, "trigger": request.trigger,
                                "detail": request.trigger_detail, "request": request.to_dict(),
                                "log": log, "truncations": truncations, "tokens": tokens,
                                "cost": cost, "next_round": round_index + 1,
                                "deferred_output": deferred_output,
                                "renders": registry.renders_used(),
                                "last_result": registry.last_result.to_dict() if registry.last_result else None,
                                "notes": registry.notes(),
                            })
                        continue
                if required and round_index + 1 < start_round + rounds:
                    request.tools = _workflow_tools(registry, required)
                    request.tool_choice = _tool_choice(required)
                    request.briefing["workflow_required"] = required
                    request.briefing["workflow_instruction"] = (
                        f"Complete the required {required} step before ending this strategy analysis."
                    )
                    if self._checkpoint is not None:
                        self._checkpoint({
                            "turn_id": request.turn_id, "trigger": request.trigger,
                            "detail": request.trigger_detail, "request": request.to_dict(),
                            "log": log, "truncations": truncations, "tokens": tokens,
                            "cost": cost, "next_round": round_index + 1,
                            "deferred_output": deferred_output,
                            "renders": registry.renders_used(),
                            "last_result": registry.last_result.to_dict() if registry.last_result else None,
                            "notes": registry.notes(),
                        })
                    continue
                if deferred_output:
                    reply.output = dict(deferred_output)
                break
            results: List[ToolResult] = []
            made: List[ToolCall] = []
            for call in reply.tool_calls:
                made.append(call)
                self._emit_activity(
                    "tool_call",
                    turn_id=request.turn_id,
                    call_id=call.call_id,
                    name=call.name,
                    arguments=dict(call.arguments or {}),
                )
                result, executed = _execute_tool_call(
                    registry, call, executed, truncations, log, tool_cap
                )
                preview = result.error or repr(result.result)
                self._emit_activity(
                    "tool_result",
                    turn_id=request.turn_id,
                    call_id=call.call_id,
                    name=call.name,
                    ok=result.ok,
                    preview=preview[:1200],
                )
                results.append(result)
            request.tool_results = list(request.tool_results) + results
            # The calls that produced those results, in the same order: what a
            # real client needs to rebuild the assistant -> tool message pair.
            request.tool_calls_made = list(request.tool_calls_made) + made
            required = _required_workflow_tool(
                log, deferred_output, require_watch=require_watch
            ) if require_watch else ""
            if required:
                request.tools = _workflow_tools(registry, required)
                request.tool_choice = _tool_choice(required)
                request.briefing["workflow_required"] = required
                request.briefing["workflow_instruction"] = (
                    f"Complete the required {required} step before ending this strategy analysis."
                )
            else:
                request.tools = registry.schemas()
                request.tool_choice = "auto"
            if registry.last_result is not None:
                request.image_path = registry.last_result.image_path
                request.manifest = registry.last_result.manifest
            if self._checkpoint is not None:
                self._checkpoint({
                    "turn_id": request.turn_id, "trigger": request.trigger,
                    "detail": request.trigger_detail, "request": request.to_dict(),
                    "log": log, "truncations": truncations, "tokens": tokens,
                    "cost": cost, "next_round": round_index + 1,
                    "deferred_output": deferred_output,
                    "renders": registry.renders_used(),
                    "last_result": registry.last_result.to_dict() if registry.last_result else None,
                    "notes": registry.notes(),
                })
        else:
            truncations.append("rounds")
        if deferred_output:
            merged = dict(reply.output or {})
            merged.update(deferred_output)
            reply.output = merged
        # The closing call. The tool rounds are over; if they ended with no
        # structured object, ask exactly once more, tool-less and image-less (a
        # shape these models reliably answer — the chart image and a tool-calling
        # history are what push a vision model into a reasoning runaway). The
        # evidence the tools produced rides along as *text* in the briefing rather
        # than as assistant/tool messages, so the request stays valid without a
        # ``tools`` array. A failure here is swallowed: the turn then simply ends
        # as it would have, so the closing call can only ever add an output.
        #
        # Chat turns skip it: their contract IS plain conversational text, and
        # forcing a "reply with ONLY the strict JSON thesis" ask over a perfectly
        # good chat answer is what turned every greeting into an analysis dump.
        if CLOSING_CALL and (not self._chat_mode) and not _has_thesis(reply.output):
            closed = self._closing_call(request, log)
            if closed is not None:
                tokens += sum(int(v or 0) for v in (closed.tokens or {}).values())
                cost += float(closed.cost_usd or 0.0)
                if closed.output:
                    merged_output = dict(reply.output or {})
                    merged_output.update(closed.output)
                    closed.output = merged_output
                    reply = closed
        return _ToolPhase(
            reply=reply,
            log=log,
            truncations=list(dict.fromkeys(truncations)),
            tokens=tokens,
            cost=cost,
            renders=registry.renders_used(),
            recoverable=("rounds" in truncations and not _has_thesis(reply.output)),
        )

    def _closing_call(
        self, request: AgentRequest, log: Sequence[Dict[str, Any]]
    ) -> Optional[AgentReply]:
        """One last, tool-less ask for the structured object (see the constants).

        Returns the reply, or ``None`` if the call itself failed. The chart image is
        deliberately dropped (it is what sends a vision model into a reasoning
        runaway) and the tool evidence is folded into the briefing as a compact text
        digest, so the model still answers from what it actually saw.
        """
        briefing = dict(request.briefing or {})
        briefing[CLOSING_KEY] = {
            "instruction": CLOSING_INSTRUCTION,
            # The closing call drops the image, but it must not mislead the model
            # about the turn it is closing: say truthfully whether a chart render
            # existed earlier, so "no chart was available" stays a fact, not a
            # guess from this call's own shape.
            "image_seen_this_turn": bool(request.image_path),
        }
        chart = _manifest_digest(request.manifest)
        if chart:
            # The image's numbers, as text: without this, a turn whose tool
            # rounds were spent on set_view closes with the model honestly
            # holding no prices at all.
            briefing["chart"] = chart
        digest = _evidence_digest(log)
        if digest:
            briefing["evidence"] = digest
        closing = AgentRequest(
            turn_id=request.turn_id,
            trigger=request.trigger,
            trigger_detail=request.trigger_detail,
            system_prompt=(
                CLOSING_SYSTEM_PROMPT
                + ("\n\nActive strategy playbook:\n" + self._playbook if self._playbook else "")
            ),
            briefing=briefing,
            image_path="",
            manifest={},
            tools=[],
        )
        try:
            return self.client.complete(closing)
        except Exception:  # noqa: BLE001 — a failed closing call must not lose the turn
            return None

    # ------------------------------------------------------------------ turn

    def run_turn(
        self,
        *,
        trigger: str = Trigger.REQUEST.value,
        detail: str = "",
        fires: Sequence[Any] = (),
        expired: Sequence[Any] = (),
        retroactive: Sequence[Any] = (),
        resume_state: Optional[Dict[str, Any]] = None,
    ) -> TurnOutcome:
        # One instant for the whole turn: every stamp (subscriptions, thesis,
        # notes, the turn record) comes from it, so a subscription can never
        # post-date the turn that created it.
        now = as_aware(self._clock())
        resume_state = dict(resume_state or {})

        # 1. Leash + 2. gating (shape-validated and gated by _gate). A refused
        # turn never happened: nothing is recorded.
        refusal = self._gate(trigger, now, continuation=bool(resume_state.get("request")))
        if refusal is not None:
            return refusal
        if resume_state.get("request"):
            current_day = (
                self.store.data.budget.day_started_at.date().isoformat()
                if self.store.data.budget.day_started_at else ""
            )
            if resume_state.get("accounting_day") != current_day:
                resume_state["accounting_base_cost_usd"] = float(resume_state.get("cost") or 0.0)
                resume_state["accounted_cost_usd"] = 0.0
                resume_state["accounting_day"] = current_day
        trigger = Trigger(trigger).value
        self._emit_activity("turn_started", trigger=trigger, detail=detail)
        expired = list(expired) + list(self.store.expire_due(now))

        # 3. Briefing + the first render (render #1).
        briefing = prompts.build_briefing(
            self.store,
            trigger=trigger,
            detail=detail,
            now=now,
            fires=fires,
            expired=expired,
            retroactive=retroactive,
        )
        require_workflow = is_mnsr_strategy(self._playbook)
        # The leash is read once per turn here too: its (optional) ``renders``
        # bound becomes this registry's render budget. A leash without a
        # ``renders`` key (older injected callables, the shipped default path)
        # falls back to the shipped constant, exactly as before.
        try:
            render_bound = int(self._leash_of().get("renders", MAX_RENDERS_PER_TURN))
        except (TypeError, ValueError):
            render_bound = MAX_RENDERS_PER_TURN
        enabled_families = self._enabled_families()
        saved_render = resume_state.get("last_result")
        if isinstance(saved_render, dict):
            saved_render = RenderResult.from_dict(saved_render)
        registry = ToolRegistry(
            self.store, self.feed, self.renderer, clock=self._clock, now=now,
            require_context_view=require_workflow, max_renders=render_bound,
            enabled_families=enabled_families,
            renders_used=resume_state.get("renders", 0),
            last_result=saved_render,
            notes=resume_state.get("notes") or [],
        )

        # The first image is a plain, live-edge 180-candle chart. It gives the
        # model unmarked price action before it selects indicator evidence.
        # Strategy-required indicator views are then requested and rendered
        # one timeframe at a time through the normal tool loop.
        first_required = (
            _required_workflow_tool([], {}, require_watch=require_workflow)
            if require_workflow else ""
        )
        request = AgentRequest.from_dict(resume_state["request"]) if resume_state.get("request") else None
        if request is None:
            initial_render: Optional[RenderResult] = None
            try:
                self.store.set_view(bars=MAX_BARS, offset=0, families=[])
                registry.reset_snapshots()
                initial_render = registry.initial_render()
            except Exception as exc:  # noqa: BLE001 — indicator view can retry after the plain-view failure
                briefing["initial_render_error"] = f"{type(exc).__name__}: {exc}"
            request = AgentRequest(
                turn_id=new_id("turn"),
                trigger=trigger,
                trigger_detail=detail,
                system_prompt=prompts.build_system_prompt(
                    playbook=self._playbook, enabled_families=enabled_families,
                ),
                briefing=briefing,
                image_path=initial_render.image_path if initial_render else "",
                manifest=initial_render.manifest if initial_render else {},
                tools=_workflow_tools(registry, first_required) if require_workflow else registry.schemas(),
                tool_choice=_tool_choice(first_required) if require_workflow else "auto",
                tool_results=[],
            )

        # 4. LLM + tool phase.
        phase = self._tool_phase(registry, request, resume_state=resume_state)
        if phase.recoverable and (
            phase.error or "generation_length" in phase.truncations or "rounds" in phase.truncations
        ):
            final = registry.last_result
            output = {
                "analysis_status": "incomplete",
                "resumable": True,
                "analysis_error": (
                    "The daily model spend cap was reached. The analysis is saved and can resume after the budget rolls over."
                    if phase.error == "leash:max_spend_per_day"
                    else phase.error or (
                        "The model response reached its per-call generation limit before the analysis was complete."
                        if "generation_length" in phase.truncations
                        else "The 400-round segment ended before the analysis was complete."
                    )
                ),
            }
            return TurnOutcome(
                turn_id=request.turn_id,
                trigger=trigger,
                ok=False,
                reason=phase.error or (
                    "generation_length" if "generation_length" in phase.truncations
                    else "rounds_exhausted"
                ),
                renders=registry.renders_used(),
                tool_calls=len(phase.log),
                output=output,
                image_path=final.image_path if final else "",
                manifest=final.manifest if final else {},
            )
        if phase.error:
            # A failed model call. Side effects that are *not* the turn record have
            # already happened: ``expire_due`` retired deadlines in memory and any
            # render the model itself asked for wrote a PNG to disk. "Not recorded"
            # below means no turn record and no save.
            #
            # If earlier rounds succeeded they cost real money, so bill them as a
            # partial turn rather than dropping the spend and under-counting the
            # leash. If the very first call failed there is nothing to bill: the
            # turn is refused and nothing is written.
            if not (phase.tokens or phase.cost):
                return TurnOutcome(trigger=trigger, ok=False, reason=phase.error)
            output = {"error": phase.error, "partial": True}
            final = registry.last_result
            record = self.store.record_turn(
                trigger,
                trigger_detail=detail,
                renders=registry.renders_used(),
                tool_calls=phase.log,
                tokens=phase.tokens,
                cost_usd=phase.cost,
                output=output,
                now=now,
            )
            self.store.save()
            return TurnOutcome(
                turn_id=record.id,
                trigger=trigger,
                ok=False,
                reason=phase.error,
                renders=registry.renders_used(),
                tool_calls=len(phase.log),
                output=output,
                image_path=final.image_path if final else "",
                manifest=final.manifest if final else {},
            )

        # 5. Output — applying it must never raise out of run_turn. The registry's
        # turn notes come first, then any the model wrote in its output.
        output = dict(phase.reply.output or {})
        output["notes"] = registry.notes() + [
            _normalise_note(note, now) for note in (output.get("notes") or [])
        ]
        workflow_missing: List[str] = []
        if require_workflow:
            state = _workflow_state(phase.log, output)
            workflow_missing = [
                label for key, label in (
                    ("w1_render", "w1_context_render"),
                    ("d1_render", "d1_context_render"),
                    ("confirm_render", "h4_or_h1_confirmation_render"),
                    ("liquidity_lookup", "liquidity_level_lookup"),
                    ("pin", "pin_relevant_liquidity"),
                    ("entry_render", "entry_timeframe_render"),
                    ("action", "watch_or_trade_proposal"),
                ) if not state[key]
            ]
        incomplete = "generation_length" in phase.truncations or not (
            _has_thesis(output) or _has_thesis_tool_call(phase.log)
        ) or bool(workflow_missing)
        if incomplete:
            output["analysis_status"] = "incomplete"
            problems = []
            if not (_has_thesis(output) or _has_thesis_tool_call(phase.log)):
                problems.append("missing thesis with storyline and explicit invalidation")
            if "generation_length" in phase.truncations:
                problems.append("model completion hit its per-call generation limit")
            if workflow_missing:
                problems.append("workflow steps not completed: " + ", ".join(workflow_missing))
            output["analysis_error"] = "; ".join(problems)
            if workflow_missing:
                output["workflow_missing"] = workflow_missing
        output, apply_errors = _apply_output(self.store, output, now)
        if apply_errors:
            output["apply_errors"] = apply_errors
        if phase.truncations:
            output["truncated"] = phase.truncations

        # 6. Persist + log. ``record_turn`` re-checks the leash internally — that is
        # deliberate defence in depth: the store refuses to bill a turn the leash
        # would not allow, even if the loop's gate were ever bypassed.
        accounted_cost = float(resume_state.get("accounted_cost_usd") or 0.0)
        accounting_base = float(resume_state.get("accounting_base_cost_usd") or 0.0)
        if accounted_cost:
            # Interrupted spend was provisionally included in the durable budget;
            # replace it with the final whole-turn amount on successful resume.
            self.store.data.budget.spend_usd_today = max(
                0.0, self.store.data.budget.spend_usd_today - accounted_cost
            )
        record = self.store.record_turn(
            trigger,
            trigger_detail=detail,
            renders=registry.renders_used(),
            tool_calls=phase.log,
            tokens=phase.tokens,
            cost_usd=phase.cost,
            output=output,
            now=now,
            enforce_leash=not bool(resume_state.get("request")),
            record_id=request.turn_id,
            budget_cost_usd=max(0.0, phase.cost - accounting_base),
        )
        self.store.save()
        if self._checkpoint is not None:
            self._checkpoint(None)

        final = registry.last_result
        reason_parts = []
        if incomplete:
            reason_parts.append("incomplete_analysis")
        if workflow_missing:
            reason_parts.append("workflow_missing: " + ", ".join(workflow_missing))
        if phase.truncations:
            reason_parts.append("truncated: " + ", ".join(phase.truncations))
        return TurnOutcome(
            turn_id=record.id,
            trigger=trigger,
            ok=not incomplete,
            reason="; ".join(reason_parts),
            renders=registry.renders_used(),
            tool_calls=len(phase.log),
            output=output,
            image_path=final.image_path if final else "",
            manifest=final.manifest if final else {},
        )

    # ------------------------------------------------------------------ chat

    def chat_turn(
        self,
        message: str,
        *,
        now: Optional[datetime] = None,
        activity: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> ChatTurnResult:
        """A free-form chat turn: the human asks, the agent answers using tools.

        Unlike :meth:`run_turn`, **no workflow is forced** — the model chooses
        which tools (if any) to call, and may answer text-only. The assistant's
        raw text is returned alongside any tool calls and renders, so a chat UI
        can show a straight conversation.

        A ``request`` turn always passes the gate (the human asked), even when
        the agent runtime is disabled or paused.

        Pacing: the store's ``min_turn_interval_s`` is relaxed to 0 for a chat
        turn — a human deliberately asking is not the same as the watchdog
        hammering — while ``max_turns_per_hour``/``max_turns_per_day`` and the
        spend cap stay enforced. The original injection is restored afterwards.

        ``activity`` (optional) receives the loop's live progress events
        (``turn_started``/``model_call_started``/``model_response``/
        ``tool_call``/``tool_result``, plus a ``chat_render`` when a chart is
        drawn) alongside the panel feed, so a chat UI can stream them.
        """
        instant = as_aware(now or self._clock())

        # Scoped swaps — leash relax, chat-mode flag, event hook — all restored
        # in finally so the autonomous watcher keeps its own personality. A
        # chat turn never runs concurrently with one (the service turn lock).
        original_limits = getattr(self.store, "_leash_limits", None)
        limits_swapped = False
        if callable(original_limits):
            def chat_limits() -> Dict[str, Any]:
                limits = dict(original_limits() or {})
                limits["min_turn_interval_s"] = 0.0
                return limits
            self.store.set_leash_limits(chat_limits)
            limits_swapped = True

        original_activity = self._activity
        original_checkpoint = self._checkpoint
        # Chat turns are conversational and must not create an analysis-resume
        # checkpoint on the shared service loop.
        self._checkpoint = None
        if activity is not None:
            def chat_emit(event: str, payload: Dict[str, Any]) -> None:
                try:
                    activity(event, dict(payload or {}))
                except Exception:  # noqa: BLE001 — a chat hook must never break the turn
                    pass
                if original_activity is not None:
                    try:
                        original_activity(event, dict(payload or {}))
                    except Exception:  # noqa: BLE001 — UI telemetry
                        pass
            self._activity = chat_emit

        self._chat_mode = True
        try:
            return self._chat_turn_body(message, instant=instant)
        finally:
            self._chat_mode = False
            self._activity = original_activity
            self._checkpoint = original_checkpoint
            if limits_swapped:
                self.store.set_leash_limits(original_limits)

    def _chat_turn_body(self, message: str, *, instant: datetime) -> ChatTurnResult:
        # Gate: request turns are always allowed.
        refusal = self._gate(Trigger.REQUEST.value, instant)
        if refusal is not None:
            return ChatTurnResult(
                ok=False, reason=refusal.reason, response="",
            )

        expired = list(self.store.expire_due(instant))
        briefing = prompts.build_briefing(
            self.store,
            trigger=Trigger.REQUEST.value,
            detail=message,
            now=instant,
            expired=expired,
        )

        try:
            render_bound = int(self._leash_of().get("renders", MAX_RENDERS_PER_TURN))
        except (TypeError, ValueError):
            render_bound = MAX_RENDERS_PER_TURN

        # The chat turn carries its own tight leash. The autonomous watcher's
        # settings (AGENT_MAX_TOOL_ROUNDS, shipped at 400) exist so a staged
        # MNSR workflow can retry long-running perception work; a chat question
        # must answer in seconds, not grind through hundreds of tool rounds at
        # the model's pace. Bounded below the autonomous leash, but the same
        # tools stay available.
        try:
            autonomous_leash = dict(self._leash_of())
        except Exception:  # noqa: BLE001 — a broken injected leash degrades to shipped caps
            autonomous_leash = dict(default_leash())

        def _cap(key: str, shipped: int, limit: int) -> int:
            try:
                value = int(autonomous_leash.get(key, shipped))
            except (TypeError, ValueError):
                value = shipped
            return max(1, min(value, limit))

        chat_leash = {
            "tool_calls": _cap("tool_calls", MAX_TOOL_CALLS_PER_TURN, CHAT_MAX_TOOL_CALLS),
            "rounds": _cap("rounds", MAX_TOOL_ROUNDS, CHAT_MAX_TOOL_ROUNDS),
            "renders": _cap("renders", MAX_RENDERS_PER_TURN, CHAT_MAX_RENDERS),
        }

        registry = ToolRegistry(
            self.store, self.feed, self.renderer, clock=self._clock, now=instant,
            require_context_view=False, max_renders=chat_leash["renders"],
            enabled_families=self._enabled_families(),
        )

        # Conversation memory: the last few chat exchanges ride in the briefing
        # so the agent answers QA about *this* conversation, not the same
        # analysis from scratch (that is why "hello"/"hi" used to repeat).
        briefing["chat_history"] = prompts.chat_history_rows(self.store)

        request = AgentRequest(
            turn_id=new_id("chat"),
            trigger=Trigger.REQUEST.value,
            trigger_detail=message,
            # The chat persona — NOT the watcher's analysis contract: persona +
            # abilities + the trader-knowledge layer + "the strategy we are
            # trading" + condition vocabulary. The knob filters the knowledge
            # layer here too: no usage instructions for tools the chat agent
            # cannot call.
            system_prompt=prompts.build_chat_system_prompt(
                playbook=self._playbook, enabled_families=self._enabled_families(),
            ),
            briefing=briefing,
            image_path="",
            manifest={},
            tools=registry.schemas(),
            tool_choice="auto",
            tool_results=[],
        )

        # Step 4: LLM + tool phase — no workflow forcing, tool_choice="auto",
        # and the chat leash swapped in for the duration (restored after: the
        # autonomous watcher keeps its own settings untouched).
        original_leash = self._leash_of
        self._leash_of = lambda: chat_leash  # noqa: E731 — scoped swap, under the turn lock
        try:
            phase = self._tool_phase(registry, request)
        finally:
            self._leash_of = original_leash

        # Stream the render as soon as it exists (the SSE hook forwards it).
        final = registry.last_result
        if final and (final.render_id or final.image_path):
            self._emit_activity(
                "chat_render",
                turn_id=request.turn_id,
                render_id=str(final.render_id or ""),
                timeframe=str(getattr(final.manifest or {}, "timeframe", "") or ""),
                bars=len((final.manifest or {}).get("tags") or {}),
            )

        if phase.error:
            # A failed model call. If earlier rounds succeeded they cost real
            # money; bill them as a partial turn rather than dropping the spend.
            if not (phase.tokens or phase.cost):
                return ChatTurnResult(
                    ok=False, reason=phase.error, response="",
                )
            output: Dict[str, Any] = {"error": phase.error, "partial": True}
        else:
            output = dict(phase.reply.output or {})
            output["notes"] = registry.notes() + [
                _normalise_note(note, instant) for note in (output.get("notes") or [])
            ]
            output, apply_errors = _apply_output(self.store, output, instant)
            if apply_errors:
                output["apply_errors"] = apply_errors

        final = registry.last_result
        response_text = phase.reply.text or ""

        # A chat-mode model may still emit the playbook's structured JSON
        # despite the chat persona. If the reply is a JSON blob, unwrap the
        # human-readable fields so the panel shows a sentence, not raw JSON.
        if response_text.strip().startswith("{"):
            try:
                blob = json.loads(response_text)
            except ValueError:
                blob = None
            if isinstance(blob, dict):
                jt = blob.get("thesis") if isinstance(blob.get("thesis"), dict) else {}
                bits = [str(v) for v in (
                    jt.get("storyline"),
                    jt.get("invalidation") and f"Invalidation: {jt['invalidation']}",
                    jt.get("confidence") is not None and f"Confidence: {jt['confidence']}",
                    blob.get("reasoning"),
                ) if v]
                if bits:
                    response_text = " ".join(bits)

        # If the model gave no raw text but structured output exists, render a
        # readable summary so the chat still shows something useful.
        if not response_text and output:
            parts: List[str] = []
            thesis = output.get("thesis")
            if isinstance(thesis, dict):
                if thesis.get("storyline"):
                    parts.append(str(thesis["storyline"]))
                if thesis.get("invalidation"):
                    parts.append(f"Invalidation: {thesis['invalidation']}")
                if thesis.get("confidence"):
                    parts.append(f"Confidence: {thesis['confidence']}")
            if output.get("reasoning"):
                parts.append(str(output["reasoning"]))
            if output.get("proposals"):
                parts.append(f"{len(output['proposals'])} proposal(s).")
            response_text = " ".join(parts) or "(no response)"

        # Persist the agent's chat wording BEFORE the turn is recorded, so the
        # next briefing's chat_history replay carries this side of the exchange.
        output["chat_response"] = response_text
        if final and final.render_id:
            # Durable pointer to the turn's chart render: the PNG lives on disk
            # in the render dir and /api/agent/render serves it by id, so the
            # chat history shows the image across server restarts.
            output["render_id"] = final.render_id

        record = self.store.record_turn(
            Trigger.REQUEST.value,
            trigger_detail=message,
            renders=registry.renders_used(),
            tool_calls=phase.log,
            tokens=phase.tokens,
            cost_usd=phase.cost,
            output=output,
            now=instant,
        )
        self.store.save()

        return ChatTurnResult(
            ok=not phase.error,
            reason=phase.error or "",
            response=response_text,
            turn_id=record.id,
            tool_calls=[call.to_dict() if hasattr(call, "to_dict") else dict(call) for call in phase.log],
            renders=registry.renders_used(),
            image_path=final.image_path if final else "",
            manifest=final.manifest if final else {},
            output=output,
        )
