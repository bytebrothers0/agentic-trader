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
   ``ToolResult``) and to the caller (``output["truncated"]``), never silent.
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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from agentic import prompts
from agentic._time import as_aware, new_id
from agentic.feed import Feed
from agentic.models import Serde, Trigger
from agentic.renderer import Renderer
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


@dataclass
class AgentReply(Serde):
    """What one model call returns: tool calls and/or a structured output."""

    tool_calls: List[ToolCall] = field(default_factory=list)
    output: Dict[str, Any] = field(default_factory=dict)
    text: str = ""
    tokens: Dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0


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

    # ------------------------------------------------------------------ step 4

    def _tool_phase(self, registry: ToolRegistry, request: AgentRequest) -> _ToolPhase:
        """Step 4: call the model, execute its tools, feed results back, repeat.

        Bounded twice over: ``MAX_TOOL_CALLS_PER_TURN`` executed calls per turn and
        ``MAX_TOOL_ROUNDS`` model calls. A call beyond the cap is **not dropped
        silently** — it becomes an ``ok=False`` :class:`ToolResult` in the log and in
        the results the model sees next, so the truncation is visible on both sides.
        """
        log: List[Dict[str, Any]] = []
        truncations: List[str] = []
        tokens = 0
        cost = 0.0
        executed = 0
        reply = AgentReply()
        for _ in range(MAX_TOOL_ROUNDS):
            reply = self.client.complete(request)
            tokens += sum(int(v or 0) for v in (reply.tokens or {}).values())
            cost += float(reply.cost_usd or 0.0)
            if not reply.tool_calls:
                break
            results: List[ToolResult] = []
            for call in reply.tool_calls:
                if executed >= MAX_TOOL_CALLS_PER_TURN:
                    truncations.append("tool_calls")
                    dropped = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        ok=False,
                        error=f"tool_cap: {MAX_TOOL_CALLS_PER_TURN} tool calls per turn",
                    )
                    results.append(dropped)
                    log.append({"call": call.to_dict(), "result": dropped.to_dict()})
                    continue
                executed += 1
                result = registry.execute(call)
                if call.name == "render" and not result.ok:
                    truncations.append("renders")
                results.append(result)
                log.append({"call": call.to_dict(), "result": result.to_dict()})
            request.tool_results = list(request.tool_results) + results
            if registry.last_result is not None:
                request.image_path = registry.last_result.image_path
                request.manifest = registry.last_result.manifest
        else:
            truncations.append("rounds")
        return _ToolPhase(
            reply=reply,
            log=log,
            truncations=list(dict.fromkeys(truncations)),
            tokens=tokens,
            cost=cost,
            renders=registry.renders_used(),
        )

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
        initial = registry.initial_render()

        request = AgentRequest(
            turn_id=new_id("turn"),
            trigger=trigger,
            trigger_detail=detail,
            system_prompt=prompts.build_system_prompt(),
            briefing=briefing,
            image_path=initial.image_path,
            manifest=initial.manifest,
            tools=registry.schemas(),
            tool_results=[],
        )

        # 4. LLM + tool phase.
        phase = self._tool_phase(registry, request)

        # 5. Output — applying it must never raise out of run_turn. The registry's
        # turn notes come first, then any the model wrote in its output.
        output = dict(phase.reply.output or {})
        output["notes"] = registry.notes() + [
            _normalise_note(note, now) for note in (output.get("notes") or [])
        ]
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
            image_path=final.image_path,
            manifest=final.manifest,
        )
