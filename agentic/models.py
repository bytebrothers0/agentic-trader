"""Schemas for the agentic chart agent (spec phase 0).

Everything here round-trips through JSON via :class:`Serde`. Datetimes are
timezone-aware; enums serialise to their string values.

Payloads the agent owns wholesale — a pin's level query, a watch's parameters, a
turn's tool calls, a proposal's provenance — stay as plain ``dict``/``list`` on
purpose. This module is not a schema for those: the detector layer and the
condition vocabulary are.
"""
from __future__ import annotations

import re
import typing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

SPEC_VERSION = "0.1.0"

#: Timeframes are validated by shape rather than against a frozen list, so a
#: derived timeframe such as H2 is expressible without touching the schema.
#: ``MN1``/``MN`` is MT5 monthly — note ``M1`` is 1-minute, not monthly, so the
#: monthly form is spelled out rather than folded into ``M\d{1,2}``.
_TIMEFRAME_RE = re.compile(r"^(M\d{1,2}|MN\d{0,2}|H\d{1,2}|D\d{1,2}|W\d{1,2})$")

#: Start every agent turn from candles alone. The agent can request any subset
#: of indicator families with set_view once it has read the unmarked price action.
DEFAULT_FAMILIES: List[str] = []
DEFAULT_VIEW_FAMILIES: List[str] = []

#: The life-cycle dial for perception ``("default", "all", "live")``.
#: New views default to ``"all"``. Explicit ``"default"`` retains the older
#: family-aware policy (hide dead TS/CRT/QM, keep all other families); ``"live"``
#: keeps only fresh / unmitigated / unbroken levels everywhere.
STATUS_FILTERS: List[str] = ["default", "all", "live"]

#: The families whose dead history the explicit legacy ``"default"`` dial hides
#: — exactly ``"live"`` for them, and pass-through for everyone else. TS and CRT per the
#: 2026-10-20 spec amendment; QM added later the same day per the operator:
#: the three setups whose history piles the ray budget with gravedust.
FRESH_ONLY_FAMILIES: List[str] = ["ts", "crt", "qm"]

VALID_BIAS = {"bullish", "bearish", "neutral", "none"}

#: A level is identified by family + timeframe + direction + price + birth bar.
#: Deterministic, recomputable, and stable across renders — which is what lets a
#: pin survive a timeframe change and still resolve.
LEVEL_KEY_SEP = ":"


def validate_timeframe(tf: str) -> str:
    if not isinstance(tf, str) or not _TIMEFRAME_RE.match(tf):
        raise ValueError(f"invalid timeframe: {tf!r} (expected M/H/D/W + digits, e.g. M15, H2, D1)")
    return tf


def make_level_key(
    family: str,
    timeframe: str,
    direction: str,
    price: float,
    born_at: Optional[str] = None,
) -> str:
    """Build the stable identity of a level.

    ``born_at`` is the birth bar's timestamp (ISO). When unknown, the price alone
    still identifies the level within its family/timeframe/direction bucket.
    """
    parts = [str(family), str(timeframe), str(direction), f"{float(price):.2f}"]
    if born_at:
        parts.append(str(born_at))
    return LEVEL_KEY_SEP.join(parts)


# --------------------------------------------------------------------------- #
# JSON round-tripping
# --------------------------------------------------------------------------- #

_TYPE_HINT_CACHE: Dict[Any, Dict[str, Any]] = {}


def _dump(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _dump(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(v) for v in value]
    return value


def _hints(tp: Any) -> Dict[str, Any]:
    if tp not in _TYPE_HINT_CACHE:
        _TYPE_HINT_CACHE[tp] = typing.get_type_hints(tp)
    return _TYPE_HINT_CACHE[tp]


def _load(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    if tp is Any or tp is None:
        return value

    origin = typing.get_origin(tp)
    if origin is typing.Union:  # Optional[X]
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _load(args[0], value) if args else value
    if origin in (list, set, tuple, frozenset):
        args = typing.get_args(tp)
        inner = args[0] if args else Any
        loaded = [_load(inner, v) for v in value]
        if origin in (set, frozenset):
            return origin(loaded)
        if origin is tuple:
            return tuple(loaded)
        return loaded
    if origin is dict:
        return dict(value)

    if isinstance(tp, type):
        if issubclass(tp, Enum):
            return tp(value)
        if tp is datetime:
            return value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if is_dataclass(tp):
            hints = _hints(tp)
            known = {f.name for f in fields(tp)}
            kwargs = {
                k: _load(hints.get(k, Any), v)
                for k, v in value.items()
                if k in known
            }
            return tp(**kwargs)
    return value


class Serde:
    """Mixin: ``to_dict()`` / ``from_dict()`` for dataclasses."""

    def to_dict(self) -> Dict[str, Any]:
        return _dump(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return _load(cls, dict(data or {}))


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #

class Trigger(str, Enum):
    """Why a turn happened."""

    BOOT = "boot"
    FIRE = "fire"
    REQUEST = "request"
    SCHEDULE = "schedule"


class SubscriptionKind(str, Enum):
    PIN = "pin"
    WATCH = "watch"


class SubscriptionState(str, Enum):
    ARMED = "armed"
    FIRED = "fired"
    EXPIRED = "expired"
    RELEASED = "released"


class LevelStatus(str, Enum):
    """Status of a pinned level, re-resolved against fresh feed output."""

    LIVE = "live"
    SWEPT = "swept"
    BROKEN = "broken"
    FILLED = "filled"
    NOT_FOUND = "not_found"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class AgentMode(str, Enum):
    PROPOSE = "propose"


class ChartType(str, Enum):
    CANDLES = "candles"
    LINE = "line"


class Layout(str, Enum):
    SINGLE = "single"
    SPLIT = "split"


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

@dataclass
class View(Serde):
    """The agent's current perception settings — dials, not UI state."""

    symbol: str = ""
    timeframe: str = "M15"
    chart_type: ChartType = ChartType.CANDLES
    families: List[str] = field(default_factory=lambda: list(DEFAULT_VIEW_FAMILIES))
    #: Which life-cycle states the agent perceives: ``"all"`` (the new-view
    #: default), ``"default"`` (fresh-only for TS/CRT/QM, everything for the rest),
    #: ``"live"`` (strictly fresh/unmitigated/unbroken everywhere) or ``"all"``.
    #: Validated by ``Store.set_view``.
    status_filter: str = "all"
    bars: int = 180
    #: How many bars to skip back from the newest one, **per timeframe**. The
    #: rendered window is ``[now-(offset+bars)*tf, now-offset*tf]``; ``0`` (the
    #: default) is the live/latest window, so ``offset`` alone re-renders a *past*
    #: window. The endpoint computes indicators on the fetched window, so an
    #: offset render shows the detectors *within that past window*.
    offset: int = 0
    layout: Layout = Layout.SINGLE
    panes: List[str] = field(default_factory=list)
    show_tags: bool = True
    annotations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Subscription(Serde):
    """One primitive, two faces.

    ``kind='pin'``  → condition ``level_alive``, ``params`` is the level query,
                      ``level_key``/``status`` hold the last resolved identity.
    ``kind='watch'``→ condition from :mod:`agentic.conditions`, ``params`` are its
                      parameters.
    """

    id: str = ""
    kind: SubscriptionKind = SubscriptionKind.WATCH
    condition: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    one_shot: bool = True
    wake_on_expiry: bool = False
    state: SubscriptionState = SubscriptionState.ARMED
    fire_count: int = 0
    last_evaluated_at: Optional[datetime] = None
    last_fired_at: Optional[datetime] = None
    level_key: Optional[str] = None
    status: Optional[LevelStatus] = None
    reason: str = ""
    note: str = ""


@dataclass
class Thesis(Serde):
    """The agent's durable read of the market — its memory."""

    updated_at: Optional[datetime] = None
    bias: str = "none"
    storyline: str = ""
    levels_of_interest: List[str] = field(default_factory=list)
    invalidation: str = ""
    confidence: float = 0.0


@dataclass
class Proposal(Serde):
    """A plan. Mirrors ``ai_agent/schemas.py:AIProposal`` for continuity."""

    id: str = ""
    created_at: Optional[datetime] = None
    bias: str = "none"
    setup: str = ""
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    invalidation: str = ""
    confidence: float = 0.0
    reason: str = ""
    provenance: List[str] = field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PROPOSED
    #: Real-execution bookkeeping (execution/agent_orders.py). ``executed`` is
    #: True when the proposal became a pending order; failures keep ``executed``
    #: False and carry ``execution_error`` so the panel shows why no order exists.
    executed: bool = False
    order_ticket: int = 0
    execution_error: str = ""


@dataclass
class TurnRecord(Serde):
    """One turn in the append-only log — the debugging surface."""

    id: str = ""
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    trigger: Trigger = Trigger.REQUEST
    trigger_detail: str = ""
    view: Dict[str, Any] = field(default_factory=dict)
    subscriptions: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    output: Dict[str, Any] = field(default_factory=dict)
    renders: int = 0
    tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Budget(Serde):
    """Counters the leash reads from."""

    turns_today: int = 0
    turns_this_hour: int = 0
    renders_today: int = 0
    spend_usd_today: float = 0.0
    day_started_at: Optional[datetime] = None
    hour_started_at: Optional[datetime] = None
    last_turn_at: Optional[datetime] = None


@dataclass
class AgentMeta(Serde):
    enabled: bool = False
    mode: AgentMode = AgentMode.PROPOSE
    model: str = ""
    spec_version: str = SPEC_VERSION
    last_evaluated_at: Optional[datetime] = None
    #: When the operator last cleared the chat conversation ("clear context" in
    #: the chat panel). The turn log is append-only audit — never deleted — so
    #: both the chat history endpoint and the briefing's chat-memory replay
    #: (``prompts.chat_history_rows``) read only turns *after* this instant.
    #: ``None`` (the default, and what older state files load as) means the
    #: whole log is still the conversation.
    chat_cleared_at: Optional[datetime] = None


@dataclass
class StoreState(Serde):
    """The serialisable root of the context store."""

    version: str = SPEC_VERSION
    symbol: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    view: View = field(default_factory=View)
    subscriptions: List[Subscription] = field(default_factory=list)
    thesis: Thesis = field(default_factory=Thesis)
    turns: List[TurnRecord] = field(default_factory=list)
    proposals: List[Proposal] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    agent: AgentMeta = field(default_factory=AgentMeta)
