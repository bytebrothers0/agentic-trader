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
from agentic.renderer import Renderer
from agentic._dialect import coerce_bias as _coerce_bias
from agentic._dialect import coerce_proposal as _coerce_proposal
from agentic.store import (
    MAX_RENDERS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    ContextStore,
    LeashExceeded,
    StoreError,
)
from agentic.tools import ToolCall, ToolRegistry, ToolResult
from agentic.watchdog import Watchdog

#: How many times the model may be asked again after a round of tool calls. Small
#: on purpose: a loop is a leash in itself.
MAX_TOOL_ROUNDS = 7


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
    "If evidence is insufficient, say so and use neutral bias."
)

CLOSING_SYSTEM_PROMPT = (
    "Close the existing analysis from the supplied chart summary and tool evidence. "
    "Do not call tools. Return only one JSON object with `thesis` containing `bias`, "
    "`storyline`, `levels_of_interest`, `invalidation`, and `confidence`; also include "
    "`proposals` (an empty array when no valid setup passed), `notes`, and `reasoning`. "
    "Never invent prices. If the analysis did not establish a valid setup, use neutral "
    "bias, explain which evidence or strategy phase is missing, and say no trade proposal."
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
    valid_view_at = None
    for index, entry in enumerate(entries):
        call = (entry or {}).get("call") or {}
        result = (entry or {}).get("result") or {}
        view = result.get("result") or {}
        is_context_view = (
            call.get("name") == "set_view"
            and result.get("ok", True)
            and isinstance(view, dict)
            and view.get("layout") == "split"
            and len(view.get("panes") or []) == 2
            and len(set(view.get("panes") or [])) == 2
            and 1 <= len(view.get("families") or []) <= 3
            and "liquidity" in (view.get("families") or [])
        )
        if call.get("name") == "set_view" and result.get("ok", True):
            # A later view change supersedes an earlier valid one.
            valid_view_at = index if is_context_view else None

    render_at = next((
        index for index, entry in enumerate(entries)
        if valid_view_at is not None
        and index > valid_view_at
        and ((entry or {}).get("call") or {}).get("name") == "render"
        and ((entry or {}).get("result") or {}).get("ok", True)
    ), None)
    liquidity_lookup_at = next((
        index for index, entry in enumerate(entries)
        if render_at is not None
        and index > render_at
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
    pin_done = not liquidity_matches or any(
        str(item.get("level_key") or "") in pinned_keys for item in liquidity_matches
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
    return {
        "context_view": valid_view_at is not None,
        "render": render_at is not None,
        "liquidity_lookup": liquidity_lookup_at is not None,
        "pin": pin_done,
        "action": proposal_done or watch_done,
        "liquidity_found": bool(liquidity_matches),
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
                panes = view.get("panes") or []
                primary_tf = str(panes[0]) if panes else ""
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
    if not state["context_view"]:
        return "set_view"
    if not state["render"]:
        return "render"
    if not state["liquidity_lookup"]:
        return "level_lookup"
    if state["liquidity_found"] and not state["pin"]:
        return "add_pin"
    if require_watch and not state["action"]:
        return "add_watch"
    return ""


def _workflow_tools(registry: ToolRegistry, required: str) -> List[Dict[str, Any]]:
    """Copy the tool surface, tightening the currently required workflow step."""
    tools = copy.deepcopy(registry.schemas())
    by_name = {tool["name"]: tool for tool in tools}
    if required == "set_view":
        schema = by_name["set_view"]["parameters"]
        schema["properties"]["layout"]["enum"] = ["split"]
        schema["required"] = ["layout", "panes", "families"]
    elif required == "level_lookup":
        schema = by_name["level_lookup"]["parameters"]
        schema["properties"]["family"]["enum"] = ["liquidity"]
        schema["required"] = ["family"]
    elif required == "add_pin":
        schema = by_name["add_pin"]["parameters"]
        schema["required"] = ["level_key", "timeframe", "reason"]
    return tools


def _tool_choice(name: str) -> Dict[str, Dict[str, str]]:
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
    tags = (manifest or {}).get("tags") or {}
    if not isinstance(tags, dict) or not tags:
        return ""
    entries = [entry for entry in tags.values() if isinstance(entry, dict)]

    def _order(entry: Dict[str, Any]) -> tuple:
        return (0 if entry.get("status") == "live" else 1, str(entry.get("tag") or ""))

    lines: List[str] = []
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
            f"- (+{len(entries) - max_lines} more levels; render for the full manifest)"
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
        # The operator's strategy (strategies/*.md via agentic.strategy), fixed
        # for this loop's lifetime: a turn never mixes strategies.
        self._playbook = str(playbook or "")

    # ------------------------------------------------------------------ gate

    def _gate(self, trigger: str, now: datetime) -> Optional[TurnOutcome]:
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
            return TurnOutcome(trigger=trigger_enum.value, ok=False, reason=f"leash:{exc.reason}")

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

    def _tool_phase(self, registry: ToolRegistry, request: AgentRequest) -> _ToolPhase:
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
        log: List[Dict[str, Any]] = []
        truncations: List[str] = []
        tokens = 0
        cost = 0.0
        executed = 0
        reply = AgentReply()
        deferred_output: Dict[str, Any] = {}
        require_watch = "mnsr" in self._playbook[:300].lower()
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
        for round_index in range(rounds):
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
            if reply.output:
                deferred_output.update(dict(reply.output))
            if not reply.tool_calls:
                required = _required_workflow_tool(
                    log, deferred_output, require_watch=require_watch
                ) if require_watch else ""
                if required in {"level_lookup", "add_pin", "add_watch"} and round_index + 1 < rounds:
                    fallback_call: Optional[ToolCall] = None
                    if required == "level_lookup":
                        view = self.store.data.view
                        context_tf = str(view.panes[0]) if view.panes else str(view.timeframe)
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
                                    "reason": "Phoenix context liquidity: preserve the live/swept pool across timeframe views",
                                },
                            )
                    else:
                        view = self.store.data.view
                        setup_tf = (
                            str(view.panes[1])
                            if view.layout.value == "split" and len(view.panes) == 2
                            else str(view.timeframe)
                        )
                        fallback_call = ToolCall(
                            call_id=new_id("workflow_watch"),
                            name="add_watch",
                            arguments={
                                "condition": "bos_forms",
                                "params": {"timeframe": setup_tf},
                                "ttl_hours": 12.0,
                                "reason": "Phoenix fallback: wait for a setup-frame BOS before the next trade assessment",
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
                        continue
                if required and round_index + 1 < rounds:
                    request.tools = _workflow_tools(registry, required)
                    request.tool_choice = _tool_choice(required)
                    request.briefing["workflow_required"] = required
                    request.briefing["workflow_instruction"] = (
                        f"Complete the required {required} step before ending this strategy analysis."
                    )
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
        if CLOSING_CALL and not _has_thesis(reply.output):
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
            system_prompt=CLOSING_SYSTEM_PROMPT,
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
    ) -> TurnOutcome:
        # One instant for the whole turn: every stamp (subscriptions, thesis,
        # notes, the turn record) comes from it, so a subscription can never
        # post-date the turn that created it.
        now = as_aware(self._clock())

        # 1. Leash + 2. gating (shape-validated and gated by _gate). A refused
        # turn never happened: nothing is recorded.
        refusal = self._gate(trigger, now)
        if refusal is not None:
            return refusal
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
        require_workflow = "mnsr" in self._playbook[:300].lower()
        # The leash is read once per turn here too: its (optional) ``renders``
        # bound becomes this registry's render budget. A leash without a
        # ``renders`` key (older injected callables, the shipped default path)
        # falls back to the shipped constant, exactly as before.
        try:
            render_bound = int(self._leash_of().get("renders", MAX_RENDERS_PER_TURN))
        except (TypeError, ValueError):
            render_bound = MAX_RENDERS_PER_TURN
        registry = ToolRegistry(
            self.store, self.feed, self.renderer, clock=self._clock, now=now,
            require_context_view=require_workflow, max_renders=render_bound,
        )

        # Step 3 is now model-led perception: the turn opens with the system
        # prompt + strategy, the briefing and the tool schemas — **no image**.
        # The model decides what to look at (set_view) and explicitly asks for
        # its own renders; each successful render then becomes that round's
        # image + manifest. A feed failure therefore surfaces in-band, as a
        # refused render tool call the model can react to (reduce the offset),
        # instead of a pre-turn degrade path the model never saw.
        request = AgentRequest(
            turn_id=new_id("turn"),
            trigger=trigger,
            trigger_detail=detail,
            system_prompt=prompts.build_system_prompt(playbook=self._playbook),
            briefing=briefing,
            image_path="",
            manifest={},
            tools=_workflow_tools(registry, "set_view") if require_workflow else registry.schemas(),
            tool_choice={"type": "function", "function": {"name": "set_view"}},
            tool_results=[],
        )

        # 4. LLM + tool phase.
        phase = self._tool_phase(registry, request)
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
                    ("context_view", "two_timeframe_context_view"),
                    ("render", "indicator_render"),
                    ("liquidity_lookup", "liquidity_level_lookup"),
                    ("pin", "pin_relevant_liquidity"),
                    ("action", "watch_or_trade_proposal"),
                ) if not state[key]
            ]
        incomplete = not (
            _has_thesis(output) or _has_thesis_tool_call(phase.log)
        ) or bool(workflow_missing)
        if incomplete:
            output["analysis_status"] = "incomplete"
            problems = []
            if not (_has_thesis(output) or _has_thesis_tool_call(phase.log)):
                problems.append("missing thesis with storyline and explicit invalidation")
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
