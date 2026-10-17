"""agentic/prompts.py — the agent's system prompt and the per-turn briefing.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "The Agent Loop"
(System prompt contract, Output contract) and "Memory, persistence, restart".

Two halves, both pure
---------------------
The **system prompt** is policy: it tells the model what kind of thing it is (an
analyst, propose-only), the top-down CRT playbook it runs by default, the
condition vocabulary it may watch, and the perception / truth / discipline /
honesty rules the design locks in. It is assembled once into
:data:`SYSTEM_PROMPT` and exposed by :func:`build_system_prompt` so a caller can
append a playbook addendum or extra context without editing the contract.

The **briefing** is memory. The spec is explicit that the agent is *not* a
transcript: each turn's context is rebuilt fresh from the store, so prompt size is
bounded no matter how long the agent has been running. :func:`build_briefing`
does that rebuild — the trigger and its detail, the current thesis, every open
subscription with its countdown, the budget position, the previous turn's
conclusion in one line, the current view, recent notes read back from the turn
log, and any fires / expiries / retroactive fires (the last clearly marked
``"not live"``, because a backfilled fire is evidence about the past, not the
present).

Nothing here reads the wall clock or touches the running system; the turn's
instant is injected into :func:`build_briefing` (there is deliberately no
``datetime.now`` fallback — a missing instant fails loudly rather than silently
making a briefing non-deterministic). ``agentic.conditions.describe()`` is the
single source of the vocabulary text, so the prompt can never drift from the
evaluator.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

from agentic._time import as_aware, seconds_remaining
from agentic.conditions import describe as describe_conditions
from agentic.crt_strategy import HTF_BIAS_TIMEFRAMES, LTF_EXECUTION_TIMEFRAMES
from agentic.models import Serde, Subscription
from agentic.store import ContextStore

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps prompts free of a runtime dep
    from agentic.subscriptions import FireResult

#: How many notes from the turn log are read back into a briefing.
NOTES_IN_BRIEFING = 10

# --------------------------------------------------------------------------- #
# The playbook
# --------------------------------------------------------------------------- #

#: The top-down CRT model, summarised from :mod:`agentic.crt_strategy` for the
#: prompt. Prompted behaviour, not enforced control — the agent may improvise.
CRT_PLAYBOOK = (
    "Top-down CRT (Candle Range Theory) playbook — your default instinct, not a "
    "straitjacket:\n"
    "- HTF bias (" + "/".join(HTF_BIAS_TIMEFRAMES) + "): the higher-timeframe CRT is the "
    "container you trade inside. A range candle defines CRH/CRL; a later candle sweeps one "
    "boundary and closes back inside; the projection is toward the OPPOSITE boundary. That "
    "direction is the bias and the opposite boundary is the draw-on-liquidity target.\n"
    "- LTF confirmation (" + "/".join(LTF_EXECUTION_TIMEFRAMES) + "): drop down to validate the "
    "bias. Wait for the change in state of delivery — a BOS in the bias direction — then a "
    "fresh FVG or OB in the bias direction as the entry zone.\n"
    "- Execution: enter at the aligned zone (discount for longs, premium for shorts), stop "
    "beyond the zone padded by ~0.25xATR (else 5% of the HTF range), target the nearest HTF "
    "CRT boundary beyond entry, partial at equilibrium. State the invalidation explicitly.\n"
    "Decision order for every turn: ORIENT (HTF bias) -> LOCATE (the levels that matter) -> "
    "ARM (subscriptions with expiries) -> REACT (update the thesis when the evidence changes)."
)

# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #

_CONDITION_VOCABULARY = (
    "Condition vocabulary you may watch — only these are expressible, so \"watch for a good "
    "long setup\" is not a thing you can arm:\n" + describe_conditions()
)

_OUTPUT_CONTRACT = (
    "How a turn ends\n"
    "- Think first, then act: reason over the briefing and the image, and call tools while you "
    "still need to (change the view, look something up, arm a subscription).\n"
    "- Use only the tools provided; there is no other way to act, and no order tool.\n"
    "- When you have no more tool calls, end the turn with the structured object below, as "
    "STRICT JSON — no prose around it, no markdown fence, no trailing commentary.\n"
    "\n"
    "Output contract — the final structured object:\n"
    "  thesis: {bias, storyline, levels_of_interest[], invalidation, confidence}\n"
    "  proposals: [{bias, setup, entry, sl, tp, invalidation, confidence, reason, "
    "provenance[]}]\n"
    "  subscriptions_added: []      # informational only; mutate via add_pin / add_watch\n"
    "  subscriptions_released: []   # informational only; mutate via release_pin / cancel_watch\n"
    "  notes: [{text}]\n"
    "  reasoning: one short paragraph — the one line the next briefing will show\n"
    "mode=propose: a proposal is a PLAN, never an order. There is no order tool."
)

SYSTEM_PROMPT = (
    "You are a market analyst for one instrument. Each turn the system renders one chart "
    "image for you; you reason over it and express everything as explicit, durable state. "
    "You are PROPOSE-ONLY: you emit plans, never orders.\n"
    "\n"
    + CRT_PLAYBOOK + "\n"
    "\n"
    "Perception rules\n"
    "- You own your perception. Ask for what you need: change the view with set_view "
    "(symbol, timeframe, chart type, families, bars, layout/panes, tags, annotations).\n"
    "- Do not assume the default view is the right view. If you need another timeframe, "
    "ask for it.\n"
    "- A pin keeps a level visible across timeframes. Use add_pin / release_pin instead of "
    "re-finding the same level every turn.\n"
    "- The image tells you what exists and where; it does not tell you the exact number.\n"
    "\n"
    "Truth rules\n"
    "- Every price you state must come from level_lookup. Never read a price off the image.\n"
    "- Cite a level_key for anything that must survive across turns; cite a tag only within "
    "the turn that drew it, because tags are stable within a render and not across renders.\n"
    "\n"
    "Discipline rules\n"
    "- Always state a thesis and an explicit invalidation.\n"
    "- Always set an expiry (ttl_hours) on a subscription; nothing is eternal.\n"
    "- Prefer one well-reasoned wait over five speculative ones.\n"
    "\n"
    "Honesty rules\n"
    "- Report uncertainty; give a confidence, not a certainty.\n"
    "- Do not claim an edge the evidence does not show. \"No setup\" is a valid conclusion.\n"
    "\n"
    + _CONDITION_VOCABULARY + "\n"
    "\n"
    + _OUTPUT_CONTRACT
)


def build_system_prompt(*, playbook: str = "", extra: str = "") -> str:
    """The system prompt, optionally extended with a playbook addendum or context.

    A single testable string: :data:`SYSTEM_PROMPT` always contains the role, the
    CRT playbook, the condition vocabulary, the rules and the output contract; the
    optional sections are appended, never substituted.
    """
    parts: List[str] = [SYSTEM_PROMPT]
    addendum = (playbook or "").strip()
    if addendum:
        parts.append("Playbook addendum:\n" + addendum)
    context = (extra or "").strip()
    if context:
        parts.append("Additional context:\n" + context)
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Briefing helpers
# --------------------------------------------------------------------------- #

def _iso(value: Optional[datetime]) -> Optional[str]:
    aware = as_aware(value)
    return aware.isoformat() if aware else None


def subscription_summary(sub: Subscription) -> str:
    """A one-line, human-readable identity for a pin or a watch."""
    kind = getattr(sub, "kind", "")
    kind = kind.value if hasattr(kind, "value") else str(kind)
    params = getattr(sub, "params", {}) or {}
    if kind == "pin":
        key = getattr(sub, "level_key", None) or params.get("level_key")
        if key:
            return f"pin {key}"
        return f"pin {params.get('family')}@{params.get('price')}"
    condition = getattr(sub, "condition", "") or ""
    rendered = ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"watch {condition}({rendered})" if rendered else f"watch {condition}"


def subscription_briefing(sub: Subscription, now: datetime) -> Dict[str, Any]:
    """One subscription -> the projected row shared by a briefing and the panel.

    The single projection of a subscription's derived view: its kind/condition/
    state as plain strings, a one-line ``summary``, its ``reason``, its expiry and
    a live countdown. A briefing and the Agent Panel both read this, so the two
    can never drift apart.
    """
    state = getattr(sub, "state", "")
    state = state.value if hasattr(state, "value") else str(state)
    expires_at = getattr(sub, "expires_at", None)
    remaining = seconds_remaining(expires_at, now)
    kind = getattr(sub, "kind", "")
    kind = kind.value if hasattr(kind, "value") else str(kind)
    return {
        "id": getattr(sub, "id", ""),
        "kind": kind,
        "condition": getattr(sub, "condition", ""),
        "state": state,
        "summary": subscription_summary(sub),
        "reason": getattr(sub, "reason", ""),
        "expires_at": _iso(expires_at),
        "seconds_remaining": remaining,
    }


def turn_conclusion(turn: Any) -> Dict[str, Any]:
    """One turn record -> its identity plus the one-line conclusion the next
    briefing (and the panel's turn log) shows. The single projection of a turn."""
    output = getattr(turn, "output", {}) or {}
    conclusion = _one_line(
        output.get("reasoning") or output.get("conclusion") or output.get("summary")
    )
    trigger = getattr(turn, "trigger", "")
    trigger = trigger.value if hasattr(trigger, "value") else str(trigger)
    return {
        "turn_id": getattr(turn, "id", ""),
        "trigger": trigger,
        "at": _iso(getattr(turn, "started_at", None)),
        "conclusion": conclusion,
    }


def _fire_briefing(fire: "FireResult", now: datetime, *, live: bool) -> Dict[str, Any]:
    """One fire as briefing data. A retroactive fire is marked ``"not live"``."""
    data = fire.to_dict() if isinstance(fire, Serde) else dict(fire or {})
    data["live"] = bool(live)
    if not live:
        fired_at = data.get("fired_at") or "an unknown time"
        data["note"] = f"retroactive — not live (would have fired {fired_at})"
    return data


def _expiry_briefing(sub: Subscription, now: datetime) -> Dict[str, Any]:
    data = subscription_briefing(sub, now)
    data["note"] = "expired since your last turn"
    return data


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def _previous_turn(store: ContextStore) -> Optional[Dict[str, Any]]:
    """The previous turn's conclusion in one line, plus its identity."""
    turns = list(getattr(store.data, "turns", []) or [])
    if not turns:
        return None
    return turn_conclusion(turns[-1])


def _recent_notes(store: ContextStore, limit: int = NOTES_IN_BRIEFING) -> List[Dict[str, Any]]:
    """Notes read back from the turn log, oldest first, most recent ``limit``."""
    collected: List[Dict[str, Any]] = []
    for turn in list(getattr(store.data, "turns", []) or []):
        for note in (getattr(turn, "output", {}) or {}).get("notes", []) or []:
            collected.append(dict(note) if isinstance(note, dict) else {"text": str(note)})
    return collected[-limit:]


def _missing_now() -> datetime:
    raise RuntimeError(
        "build_briefing has no instant: pass now=<datetime> — the pure core never "
        "reads the wall clock (inject the turn's instant)"
    )


def build_briefing(
    store: ContextStore,
    *,
    trigger: str,
    detail: str = "",
    now: Optional[datetime] = None,
    fires: Iterable[Any] = (),
    expired: Iterable[Any] = (),
    retroactive: Iterable[Any] = (),
) -> Dict[str, Any]:
    """Everything the agent needs to know *why this turn happened*, rebuilt fresh.

    The store is the memory, so a briefing is a projection of the store plus the
    events that caused this turn — never a growing conversation. Fields:

    - ``trigger`` / ``detail`` — why this turn happened.
    - ``now`` — the turn's instant, ISO-8601 (the injected clock, never read here).
    - ``view`` — the current perception settings.
    - ``thesis`` — the durable read (its ``updated_at`` is context, not new data).
    - ``subscriptions`` — every open subscription with state and countdown.
    - ``budget`` — the leash position.
    - ``previous_turn`` — the last turn's conclusion in one line, or ``None``.
    - ``fires`` / ``expired`` — live events since the last turn.
    - ``retroactive`` — fires missed while the process was down, each marked
      ``live: false`` and ``"not live"``; they are history, not evidence now.
    - ``notes`` — recent notes read back from the turn log.

    ``now`` is required: a missing instant raises rather than silently reading the
    wall clock (see :func:`_missing_now`), so a briefing is always reproducible.
    """
    if now is None:
        _missing_now()
    now = as_aware(now)
    open_subs = [s for s in store.open_subscriptions()]
    return {
        "trigger": trigger,
        "detail": detail,
        "view": store.data.view.to_dict(),
        "thesis": store.data.thesis.to_dict(),
        "subscriptions": [subscription_briefing(s, now) for s in open_subs],
        "budget": store.data.budget.to_dict(),
        "previous_turn": _previous_turn(store),
        "fires": [_fire_briefing(f, now, live=True) for f in fires],
        "expired": [_expiry_briefing(s, now) for s in expired],
        "retroactive": [_fire_briefing(f, now, live=False) for f in retroactive],
        "notes": _recent_notes(store),
        "now": now.isoformat(),
    }


def render_briefing_text(briefing: Optional[Dict[str, Any]]) -> str:
    """A briefing -> the stable text block the model's user message carries.

    The briefing is JSON-serialisable by construction (:func:`build_briefing`
    builds it as plain data), so this is a canonical JSON dump under a one-line
    header naming the trigger. It lives here, beside the briefing that produced
    it, so the wire layer (``agentic.llm``) never re-implements the format.
    """
    data = briefing or {}
    trigger = str(data.get("trigger") or "turn")
    detail = _one_line(data.get("detail"))
    header = f"Turn briefing — trigger: {trigger}"
    if detail:
        header += f" ({detail})"
    body = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return f"{header}\n{body}"
