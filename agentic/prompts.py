"""agentic/prompts.py — the agent's system prompt and the per-turn briefing.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "The Agent Loop"
(System prompt contract, Output contract) and "Memory, persistence, restart".
The strategy itself is external: one markdown playbook per strategy
(``agentic/strategy.py`` loads it), injected by the caller via
``build_system_prompt(playbook=...)``.

Two halves, both pure
---------------------
The **system prompt** is policy: it tells the model what kind of thing it is (an
analyst, propose-only), the perception / truth / discipline /
honesty rules the design locks in, the condition vocabulary it may watch, and
the output contract. It is assembled once into
:data:`SYSTEM_PROMPT` and exposed by :func:`build_system_prompt` so a caller can
append the loaded strategy or extra context without editing the contract.

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
from agentic.models import ProposalStatus, Serde, Subscription
from agentic.store import ContextStore

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps prompts free of a runtime dep
    from agentic.subscriptions import FireResult

#: How many notes from the turn log are read back into a briefing.
NOTES_IN_BRIEFING = 10
#: How many live proposals (with their real-execution outcome) are read back.
ORDERS_IN_BRIEFING = 6

# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #

_CONDITION_VOCABULARY = (
    "Condition vocabulary you may watch — only these are expressible, so \"watch for a good "
    "long setup\" is not a thing you can arm:\n" + describe_conditions()
)

_INDICATOR_GUIDE = (
    "Project-specific indicator guide (use these local definitions, which take "
    "precedence over generic trading terminology):\n"
    "- `sr` (S/R): body-close levels from a bearish→bullish pair (support) or "
    "bullish→bearish pair (resistance). A body close through support creates SBR; "
    "through resistance creates RBS. Wick touch is mitigation/use, not a body break.\n"
    "- `crt` (Candle Range Theory): an anchor candle defines a high/low range; a "
    "later wick sweeps one edge and closes back inside. The opposite edge is the "
    "target. A close beyond the swept edge invalidates; reaching the far edge distributes.\n"
    "- `ts` (Turtle Soup): a range boundary is swept and the sweep candle body closes "
    "back inside, within the configured window (normally five bars). It is a reversal "
    "event, not an entry by itself. Variants describe the bars between anchor and sweep.\n"
    "- `bos`: market structure level broken by candle close. BOS is continuation; "
    "CHoCH is a break against the tracked structure direction; `I-` means internal.\n"
    "- `fvg`: three-candle imbalance (bullish when current low > high two bars back; "
    "bearish mirror). First wick into the zone mitigates it. `ifvg`: a recent FVG "
    "closed through by the full body and confirmed by an overlapping opposite FVG.\n"
    "- `ob`: order-block zone from the last opposite-colour candle before a swing "
    "break/displacement; it must be associated with a sweep or displacement. A body "
    "close through its far edge can flip it into a breaker. Wick contact alone mitigates.\n"
    "- `liquidity`: clustered, approximately equal swing highs/lows (buy-side above "
    "highs; sell-side below lows); a wick through marks the pool taken. A single swing "
    "is not an equal-level pool.\n"
    "- `qm`: Quasimodo, a failed SBR/RBS: price body-closes through an S/R level, then "
    "body-closes back across it. Direction and subtype are in the level description.\n"
    "- `idm`: inducement/pullback levels from BOS-anchored, two-candle, or "
    "reference-candle rules. Wick through and reclaim is swept; body close through is broken.\n"
    "- `trendline`: sloped line through two or three close-price swing apexes. A body "
    "close through breaks it; far-side wick touch is a retest. Role-flip/channel/sweep "
    "metadata may be included in its description.\n"
    "- `ocl`: open-close level on the selected chart timeframe, normally the first candle's close in "
    "a same-colour two-candle pair; subtypes include support/resistance and levels "
    "broken twice.\n"
    "- `apex`: validated close-price swing on the selected chart timeframe that led to a structural "
    "breakout. External apex is major; IAB is an internal swing.\n"
    "Lifecycle words are family-specific: live/fresh means currently active; mitigated "
    "or filled usually means touched/used; swept/taken means liquidity was raided; "
    "broken/invalidated means the rule's close-through occurred. Read the level's "
    "family, type, description, state, and end_kind together. A detected feature is "
    "evidence, not a trade instruction or proof of confluence. Ask for exact prices "
    "with `level_lookup`; never infer them from labels or pixels.\n"
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
    "image for you; the first image is a plain 180-candle chart without indicator overlays. "
    "Request indicator families with set_view when you need them. After the initial plain "
    "chart, your first response must use set_view to request the indicator families and/or "
    "timeframe needed for analysis; do not end the turn without examining indicator evidence. "
    "You reason over the image "
    "and express everything as explicit, durable state. "
    "You are PROPOSE-ONLY: you emit plans, never orders.\n"
    "\n"
    "Strategy playbook:\n"
    "The caller supplies your strategy playbook — a markdown the operator owns "
    "(build_system_prompt(playbook=...) injects it directly after these rules). Follow it; "
    "it is your default instinct, not a straitjacket. If no strategy was loaded, run with "
    "your own reading and say so in your notes.\n"
    "\n"
    "Perception rules\n"
    "- You own your perception. Ask for what you need: change the view with set_view "
    "(symbol, timeframe, chart type, families, bars, offset, layout/panes, tags, "
    "annotations).\n"
    "- Limit every image to at most three distinct indicator families. If more evidence "
    "is needed, inspect the current image, then request the next focused family group "
    "with a later set_view/render sequence; use `families_deferred` in the set_view "
    "result to choose what to inspect next.\n"
    "- `status_filter` chooses which life-cycle states you see. The default is "
    "'all', including broken levels and filled zones. Set it to 'live' when you "
    "want strictly fresh levels for every family. The explicit 'default' option "
    "keeps the older family-aware policy: hide dead TS/CRT/QM, show every state "
    "for other families.\n"
    "- A pinned level stays visible even if the status filter would hide it (and "
    "a pin is exempt from the per-family ray budget).\n"
    "- Do not assume the default view is the right view. If you need another timeframe, "
    "ask for it.\n"
    "- `offset` re-renders a *past* window: it skips back that many bars from the newest "
    "one, so the detectors are computed within that window. The manifest's window.from/to "
    "tells you exactly which bars you are looking at.\n"
    "- In an offset (past) window the lookup's `current_price`/`atr` are that window's own "
    "last bar (`price_basis=\"window_end\"`), NOT the live market — every `distance_points` "
    "is measured inside the past window.\n"
    "- `layout=\"split\"` with exactly two `panes` shows two timeframes stacked (HTF on top, "
    "LTF below), each with its own price scale. `level_lookup` searches *every* pane, and "
    "the header `current_price`/`atr` is the basis of the pane the resolved level belongs "
    "to — so a `P2:` tag's distance is measured against pane 2's price.\n"
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
    + _INDICATOR_GUIDE + "\n"
    "\n"
    + _OUTPUT_CONTRACT
)


def build_system_prompt(*, playbook: str = "", extra: str = "") -> str:
    """The system prompt, extended with the loaded strategy or extra context.

    A single testable string: :data:`SYSTEM_PROMPT` always contains the role,
    the perception/truth/discipline/honesty rules, the condition vocabulary and
    the output contract; the strategy (loaded from the operator's .md by
    :func:`agentic.strategy.load_strategy`) and any extra context are appended,
    never substituted.
    """
    parts: List[str] = [SYSTEM_PROMPT]
    addendum = (playbook or "").strip()
    if "mnsr" in addendum[:300].lower():
        parts.append(
            "Required MNSR workflow:\n"
            "1. Start with a split view of two distinct timeframes (context first, setup second), "
            "at most three overlay families, and include liquidity. Every image is limited to "
            "three distinct indicator families.\n"
            "2. Render that selected view and look up the context liquidity family. If useful "
            "liquidity exists, pin the exact returned level_key and timeframe.\n"
            "3. Complete the playbook's setup checks. Before ending, either make a valid "
            "trade proposal or arm a strategy-relevant watch for the missing setup phase.\n"
            "Do not render every indicator family together. Inspect each image, then use later "
            "set_view/render calls sequentially for another focused group when more evidence is "
            "needed; set_view reports any families_deferred."
        )
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


def _order_digest(store: ContextStore, limit: int = ORDERS_IN_BRIEFING) -> List[Dict[str, Any]]:
    """The live proposals with their **real-execution outcome**, oldest first.

    ``propose_trade`` does not place an order itself — the executor syncs after
    the turn — so the model's feedback has to come *here*. Each row tells it
    honestly what became of its idea: placed (with the terminal ticket), refused
    (with the broker's reason — "invalid stops", a duplicate plan, the cap), or
    not yet executed. A refused order is retried next turn, so this digest is
    what lets the model *adapt* — tighten a stop distance the broker rejected,
    or drop a plan that keeps failing — instead of blindly re-proposing it.
    """
    rows: List[Dict[str, Any]] = []
    for proposal in list(store.data.proposals)[-limit:]:
        if proposal.status is not ProposalStatus.PROPOSED:
            continue
        if proposal.executed:
            state = f"order placed (ticket {proposal.order_ticket})"
        elif proposal.execution_error:
            state = f"NOT placed — refused: {proposal.execution_error}"
        else:
            state = "not yet executed"
        rows.append({
            "id": proposal.id,
            "bias": proposal.bias,
            "setup": proposal.setup,
            "entry": proposal.entry,
            "sl": proposal.sl,
            "tp": proposal.tp,
            "execution": state,
        })
    return rows


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
    - ``orders`` — the live proposals with what really happened to them at the
      terminal (placed ticket, refusal reason, not yet executed).

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
        "orders": _order_digest(store),
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
