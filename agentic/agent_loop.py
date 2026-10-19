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
3. **Briefing + render.** ``prompts.build_briefing`` rebuilds the context fresh from
   the store, and the first render of the turn is performed. That render counts as
   render #1 toward ``MAX_RENDERS_PER_TURN``; the :class:`~agentic.tools.ToolRegistry`
   owns that budget so it cannot double-count.
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from agentic import prompts
from agentic._time import as_aware, new_id
from agentic.feed import Feed
from agentic.models import Serde, Trigger
from agentic.renderer import RenderResult, Renderer
from agentic.store import (
    MAX_TOOL_CALLS_PER_TURN,
    ContextStore,
    LeashExceeded,
    StoreError,
)
from agentic.tools import ToolCall, ToolRegistry, ToolResult
from agentic.watchdog import Watchdog

#: How many times the model may be asked again after a round of tool calls. Small
#: on purpose: a loop is a leash in itself.
MAX_TOOL_ROUNDS = 4

#: The instruction for the *closing call* — the one last, tool-less ask made when
#: the tool rounds ended without a structured object. Tool-calling loops and
#: reasoning runaways are a model behaviour, not a wiring fault: rather than let a
#: turn bill tokens and record nothing, we make exactly one more call with no
#: tools and no chart image, which is the shape these models reliably answer. It
#: fires only when there is nothing to lose (see ``_tool_phase``).
CLOSING_INSTRUCTION = (
    "End the turn now. You have no more tool calls to make. Reply with ONLY the "
    "strict JSON object defined in the output contract — no prose, no markdown "
    "fence, nothing before or after it."
)

#: The single key the closing instruction is carried under in the briefing.
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
        try:
            store.set_thesis(**_pick(thesis, _THESIS_KEYS), now=now)
        except (StoreError, TypeError, ValueError) as exc:
            apply_errors.append(f"thesis: {exc}")
    for proposal in output.get("proposals") or []:
        if not isinstance(proposal, dict):
            apply_errors.append(f"proposal: not an object: {proposal!r}")
            continue
        try:
            store.add_proposal(**_pick(proposal, _PROPOSAL_KEYS), now=now)
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
) -> Tuple[ToolResult, int]:
    """Run one tool call, or refuse it at the per-turn cap.

    Returns ``(result, executed_count)`` so the caller can keep the running count.
    A call beyond ``MAX_TOOL_CALLS_PER_TURN`` becomes an ``ok=False`` result in the
    log and in what the model sees next — visible on both sides, never dropped.
    """
    if executed >= MAX_TOOL_CALLS_PER_TURN:
        truncations.append("tool_calls")
        result = ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=False,
            error=f"tool_cap: {MAX_TOOL_CALLS_PER_TURN} tool calls per turn",
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
    ):
        self.store = store
        self.feed = feed
        self.renderer = renderer
        self.client = client
        self._clock = clock or getattr(store, "_clock", None) or _utcnow
        self._watchdog = watchdog

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

    # ------------------------------------------------------------------ step 3

    def _initial_render(
        self, registry: ToolRegistry
    ) -> Tuple[Optional[RenderResult], str]:
        """Step 3's first render, hardened so a persisted bad view cannot brick the loop.

        A view whose ``offset`` exceeds the feed's history makes every render
        raise. Because ``set_view`` has already persisted that offset, leaving it
        in place would refuse *every* future turn and the model would never get a
        chance to ``set_view(offset=0)``. So a feed failure **degrades instead of
        propagating**: retry once at the live edge (``offset=0``, same
        timeframe/families), then — if that also fails — return ``(None, reason)``
        so the turn still completes with the refusal recorded on it.
        """
        try:
            return registry.initial_render(), ""
        except Exception as exc:  # noqa: BLE001 — a feed failure must never escape
            reason = f"{type(exc).__name__}: {_truncate(exc)}"
        if int(self.store.data.view.offset or 0) <= 0:
            return None, reason
        try:
            self.store.set_view(offset=0)
            registry.reset_snapshots()
            return registry.initial_render(), ""
        except Exception as exc:  # noqa: BLE001 — a second failure is still a refusal, not a crash
            return None, f"{type(exc).__name__}: {_truncate(exc)}"

    # ------------------------------------------------------------------ step 4

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
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                reply = self.client.complete(request)
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
            tokens += sum(int(v or 0) for v in (reply.tokens or {}).values())
            cost += float(reply.cost_usd or 0.0)
            if not reply.tool_calls:
                break
            results: List[ToolResult] = []
            made: List[ToolCall] = []
            for call in reply.tool_calls:
                made.append(call)
                result, executed = _execute_tool_call(
                    registry, call, executed, truncations, log
                )
                results.append(result)
            request.tool_results = list(request.tool_results) + results
            # The calls that produced those results, in the same order: what a
            # real client needs to rebuild the assistant -> tool message pair.
            request.tool_calls_made = list(request.tool_calls_made) + made
            if registry.last_result is not None:
                request.image_path = registry.last_result.image_path
                request.manifest = registry.last_result.manifest
        else:
            truncations.append("rounds")
        # The closing call. The tool rounds are over; if they ended with no
        # structured object, ask exactly once more, tool-less and image-less (a
        # shape these models reliably answer — the chart image and a tool-calling
        # history are what push a vision model into a reasoning runaway). The
        # evidence the tools produced rides along as *text* in the briefing rather
        # than as assistant/tool messages, so the request stays valid without a
        # ``tools`` array. A failure here is swallowed: the turn then simply ends
        # as it would have, so the closing call can only ever add an output.
        if CLOSING_CALL and not (reply.output or {}):
            closed = self._closing_call(request, log)
            if closed is not None:
                tokens += sum(int(v or 0) for v in (closed.tokens or {}).values())
                cost += float(closed.cost_usd or 0.0)
                if closed.output:
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
        briefing[CLOSING_KEY] = CLOSING_INSTRUCTION
        digest = _evidence_digest(log)
        if digest:
            briefing["evidence"] = digest
        closing = AgentRequest(
            turn_id=request.turn_id,
            trigger=request.trigger,
            trigger_detail=request.trigger_detail,
            system_prompt=request.system_prompt,
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
        registry = ToolRegistry(
            self.store, self.feed, self.renderer, clock=self._clock, now=now
        )
        initial, render_error = self._initial_render(registry)

        request = AgentRequest(
            turn_id=new_id("turn"),
            trigger=trigger,
            trigger_detail=detail,
            system_prompt=prompts.build_system_prompt(),
            briefing=briefing,
            image_path=initial.image_path if initial else "",
            manifest=initial.manifest if initial else {},
            tools=registry.schemas(),
            tool_results=[],
        )

        # 4. LLM + tool phase.
        phase = self._tool_phase(registry, request)
        if phase.error:
            # A failed model call. Side effects that are *not* the turn record have
            # already happened: ``expire_due`` retired deadlines in memory and
            # ``initial_render`` wrote a PNG to disk. "Not recorded" below means no
            # turn record and no save.
            #
            # If earlier rounds succeeded they cost real money, so bill them as a
            # partial turn rather than dropping the spend and under-counting the
            # leash. If the very first call failed there is nothing to bill: the
            # turn is refused and nothing is written.
            if not (phase.tokens or phase.cost):
                return TurnOutcome(trigger=trigger, ok=False, reason=phase.error)
            output = {"error": phase.error, "partial": True}
            if render_error:
                output["render_error"] = render_error
            final = registry.last_result or initial
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
        if render_error:
            # The initial render degraded (e.g. a persisted offset past history):
            # record it on the turn so the model knows why there was no image.
            output["render_error"] = render_error
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

        final = registry.last_result or initial
        return TurnOutcome(
            turn_id=record.id,
            trigger=trigger,
            ok=True,
            reason=("truncated: " + ", ".join(phase.truncations)) if phase.truncations else "",
            renders=registry.renders_used(),
            tool_calls=len(phase.log),
            output=output,
            image_path=final.image_path if final else "",
            manifest=final.manifest if final else {},
        )
