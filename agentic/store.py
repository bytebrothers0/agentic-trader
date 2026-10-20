"""The durable context store (spec phase 0).

The store is the state of record and the only thing that persists. It holds
*intent* and *agent metadata* — never detector output. Caps and expiries are
enforced here, not by the agent, because a chatty agent that can pin without limit
degrades the very image it reasons over.

Every rejection raises a :class:`StoreError` carrying a machine-readable
``reason``; the agent sees that reason in the tool result and can fix its own
request. Nothing fails silently, which is the whole point.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import fields as dc_fields
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from agentic import conditions as cond
from agentic.models import (
    AgentMeta,
    AgentMode,
    Budget,
    ChartType,
    Layout,
    LevelStatus,
    Proposal,
    ProposalStatus,
    STATUS_FILTERS,
    StoreState,
    Subscription,
    SubscriptionKind,
    SubscriptionState,
    Thesis,
    Trigger,
    TurnRecord,
    VALID_BIAS,
    View,
    validate_timeframe,
)

# --------------------------------------------------------------------------- #
# The leash. Every one of these exists because an autonomous, self-starting
# agent without limits is a subscription you did not sign up for.
# --------------------------------------------------------------------------- #

MAX_PINS = 8
MAX_OPEN_SUBSCRIPTIONS = 20
WATCH_TTL_DEFAULT_HOURS = 24.0
WATCH_TTL_MAX_HOURS = 24.0 * 7
PIN_TTL_DEFAULT_HOURS = 72.0
PIN_TTL_MAX_HOURS = 24.0 * 14
SUB_COOLDOWN_S = 300
MAX_RENDERS_PER_TURN = 3
MAX_TOOL_CALLS_PER_TURN = 8
MIN_TURN_INTERVAL_S = 60
MAX_TURNS_PER_HOUR = 6
MAX_TURNS_PER_DAY = 60
MAX_SPEND_PER_DAY_USD = 5.0

MIN_BARS = 20
#: Maximum bars in one agent screenshot. Past price action is reached with
#: ``offset`` — pan the window back — rather than widening without a bound.
MAX_BARS = 180
#: How far back (in bars, per timeframe) the agent may shift its window. A cap
#: exists for the same reason the bar cap does: an unbounded lookback asks the
#: provider for history it may not hold and renders a window nobody asked for.
#: 5000 bars matches the widest window the pre-50 era could ask for — you can
#: move a full window behind the newest bar, but not forever.
MAX_OFFSET = 5000

DEFAULT_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")


class StoreError(Exception):
    """A rejected mutation, with a machine-readable ``reason``."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


class CapExceeded(StoreError):
    """A cap or an expiry bound was breached."""


class LeashExceeded(StoreError):
    """The turn leash refused to start a turn."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class ContextStore:
    """Load, mutate and persist one symbol's context.

    ``clock`` is injectable so expiry and leash behaviour are testable without
    waiting for real time.
    """

    def __init__(
        self,
        symbol: str,
        state_dir: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        if not symbol or not str(symbol).strip():
            raise StoreError("missing_symbol", "a context store needs a symbol")
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self._clock = clock or _utcnow
        now = self._clock()
        self.data = StoreState(symbol=str(symbol), created_at=now, updated_at=now)
        self.data.view.symbol = str(symbol)
        self._roll_windows(now)

    # ------------------------------------------------------------------ paths

    @staticmethod
    def path_for(symbol: str, state_dir: Optional[str] = None) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(symbol))
        return os.path.join(state_dir or DEFAULT_STATE_DIR, f"{safe}.json")

    @property
    def path(self) -> str:
        return self.path_for(self.data.symbol, self.state_dir)

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    # --------------------------------------------------------------------- io

    def to_dict(self) -> Dict[str, Any]:
        return self.data.to_dict()

    def save(self) -> str:
        """Write atomically (temp file + replace) so a crash cannot truncate state.

        The temp name is unique per process **and** per thread. ``save`` is called
        from more than one thread (the agent's watchdog thread and a request thread
        can both persist the same store), and a *shared* ``path + ".tmp"`` let two
        concurrent writers interleave into one file — the ``os.replace`` then
        published a corrupt JSON document. A per-thread temp file makes each write
        private, so the last replace wins with a complete document.
        """
        self.data.updated_at = self._clock()
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.path + f".{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data.to_dict(), f, indent=2, ensure_ascii=False)
            self._replace(tmp)
        finally:
            # A failed (or already-replaced) write must not leave a temp behind.
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return self.path

    def _replace(self, tmp: str) -> None:
        """``os.replace`` with a brief retry for the Windows transient lock.

        Replacing a path that another thread is *also* replacing can fail with
        ``PermissionError`` ("access is denied") on Windows even though the temp
        files are distinct. A few short retries turn that momentary lock into a
        clean last-writer-wins; elsewhere the first attempt succeeds.
        """
        last: Optional[OSError] = None
        for attempt in range(8):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError as exc:
                last = exc
                time.sleep(0.002 * (attempt + 1))
        assert last is not None  # only reachable if every attempt raised
        raise last  # all retries exhausted: surface the real error

    @classmethod
    def load(
        cls,
        symbol: str,
        state_dir: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> "ContextStore":
        path = cls.path_for(symbol, state_dir)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        store = cls(symbol=symbol, state_dir=state_dir, clock=clock)
        store.data = StoreState.from_dict(raw)
        if not store.data.symbol:
            store.data.symbol = str(symbol)
        return store

    @classmethod
    def load_or_new(
        cls,
        symbol: str,
        state_dir: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> "ContextStore":
        try:
            return cls.load(symbol, state_dir=state_dir, clock=clock)
        except FileNotFoundError:
            return cls(symbol, state_dir=state_dir, clock=clock)

    # ------------------------------------------------------------------ housekeeping

    def _touch(self) -> None:
        self.data.updated_at = self._clock()

    def _roll_windows(self, now: datetime) -> None:
        """Reset the day/hour counters when their window has passed."""
        b = self.data.budget
        if b.day_started_at is None or _as_aware(now).date() != _as_aware(b.day_started_at).date():
            b.turns_today = 0
            b.renders_today = 0
            b.spend_usd_today = 0.0
            b.day_started_at = now
        if b.hour_started_at is None or (_as_aware(now) - _as_aware(b.hour_started_at)) >= timedelta(hours=1):
            b.turns_this_hour = 0
            b.hour_started_at = now

    # ------------------------------------------------------------------ view

    def set_view(self, **changes: Any) -> View:
        """Change the agent's perception settings. Unknown dials are rejected."""
        known = {f.name for f in dc_fields(View)}
        unknown = sorted(set(changes) - known)
        if unknown:
            raise StoreError("unknown_view_field", f"view has no field(s): {', '.join(unknown)}")

        if "symbol" in changes and str(changes["symbol"]) != self.data.symbol:
            raise StoreError(
                "symbol_mismatch",
                f"this store belongs to {self.data.symbol!r}; a symbol gets its own store",
            )

        try:
            if "timeframe" in changes:
                changes["timeframe"] = validate_timeframe(str(changes["timeframe"]))
            if "panes" in changes:
                changes["panes"] = [validate_timeframe(str(p)) for p in (changes["panes"] or [])]
        except ValueError as exc:
            raise StoreError("invalid_timeframe", str(exc))

        if "chart_type" in changes:
            try:
                changes["chart_type"] = ChartType(changes["chart_type"])
            except ValueError:
                raise StoreError("invalid_chart_type", f"chart_type must be one of {[c.value for c in ChartType]}")
        if "layout" in changes:
            try:
                changes["layout"] = Layout(changes["layout"])
            except ValueError:
                raise StoreError("invalid_layout", f"layout must be one of {[l.value for l in Layout]}")
        if "families" in changes:
            changes["families"] = [str(f) for f in (changes["families"] or [])]
        if "bars" in changes:
            try:
                bars = int(changes["bars"])
            except (TypeError, ValueError):
                raise StoreError("invalid_bars", f"bars must be an integer, got {changes['bars']!r}")
            if not MIN_BARS <= bars <= MAX_BARS:
                raise StoreError("invalid_bars", f"bars must be between {MIN_BARS} and {MAX_BARS}")
            changes["bars"] = bars
        if "show_tags" in changes:
            changes["show_tags"] = bool(changes["show_tags"])
        if "status_filter" in changes:
            value = str(changes["status_filter"] or "").strip().lower()
            if value not in STATUS_FILTERS:
                raise StoreError(
                    "invalid_status_filter",
                    f"status_filter must be one of {STATUS_FILTERS}",
                )
            changes["status_filter"] = value
        if "offset" in changes:
            try:
                offset = int(changes["offset"])
            except (TypeError, ValueError):
                raise StoreError("invalid_offset", f"offset must be an integer, got {changes['offset']!r}")
            if not 0 <= offset <= MAX_OFFSET:
                raise StoreError("invalid_offset", f"offset must be between 0 and {MAX_OFFSET}")
            changes["offset"] = offset

        # A split render is capped at exactly two **distinct** timeframes in v1, and
        # the primary pane (``panes[0]``) is what ``level_lookup``, pins and
        # subscriptions treat as *the* timeframe. So ``view.timeframe`` is kept in
        # sync to it when panes are supplied, and re-asserted on *every* split
        # mutation — a bare ``set_view(timeframe=...)`` while split must not desync
        # the view from ``panes[0]``.
        panes_value = changes.get("panes") if "panes" in changes else None
        if panes_value:
            if "timeframe" in changes and changes["timeframe"] != panes_value[0]:
                raise StoreError(
                    "invalid_split",
                    "timeframe and panes disagree; panes[0] is the primary timeframe",
                )
            changes["timeframe"] = panes_value[0]
        effective_panes = changes.get("panes", self.data.view.panes)
        effective_layout = changes.get("layout", self.data.view.layout)
        if effective_layout is Layout.SPLIT:
            if len(effective_panes) != 2:
                raise StoreError("invalid_split", "split needs exactly 2 panes")
            if effective_panes[0] == effective_panes[1]:
                raise StoreError("invalid_split", "split needs two distinct timeframes")
            changes["timeframe"] = effective_panes[0]

        for key, value in changes.items():
            setattr(self.data.view, key, value)
        self._touch()
        return self.data.view

    # ------------------------------------------------------------------ subscriptions

    def open_subscriptions(self, kind: Optional[SubscriptionKind] = None) -> List[Subscription]:
        """Armed subscriptions, optionally filtered to pins or watches.

        ``kind`` accepts either the enum or its string form — a bare string that
        quietly matched nothing was a footgun worth closing.
        """
        if kind is not None and not isinstance(kind, SubscriptionKind):
            try:
                kind = SubscriptionKind(kind)
            except ValueError:
                raise StoreError("invalid_kind", f"kind must be one of {[k.value for k in SubscriptionKind]}")
        return [
            s
            for s in self.data.subscriptions
            if s.state is SubscriptionState.ARMED and (kind is None or s.kind is kind)
        ]

    def get_subscription(self, sub_id: str) -> Subscription:
        for s in self.data.subscriptions:
            if s.id == sub_id:
                return s
        raise StoreError("unknown_subscription", f"no subscription {sub_id!r}")

    def add_subscription(
        self,
        kind: str,
        condition: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        *,
        ttl_hours: Optional[float] = None,
        one_shot: bool = True,
        wake_on_expiry: bool = False,
        reason: str = "",
        note: str = "",
        starts_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> Tuple[Subscription, bool]:
        """Create a pin or a watch. Returns ``(subscription, created)``.

        Already-open duplicates return the existing subscription with
        ``created=False`` rather than piling up. Every subscription gets a hard
        expiry; there is no such thing as an eternal subscription.
        """
        now = now or self._clock()
        self._roll_windows(now)

        try:
            kind_enum = SubscriptionKind(kind)
        except ValueError:
            raise StoreError("invalid_kind", f"kind must be one of {[k.value for k in SubscriptionKind]}")

        try:
            if kind_enum is SubscriptionKind.PIN:
                params = cond.validate_pin_query(params)
                condition = cond.Condition.LEVEL_ALIVE.value
            else:
                if not condition:
                    raise cond.ConditionError("missing_params", "a watch needs a condition")
                condition = condition.value if hasattr(condition, "value") else str(condition)
                params = cond.validate(condition, params)
        except cond.ConditionError as exc:
            raise StoreError(exc.reason, str(exc))

        open_subs = self.open_subscriptions()
        if len(open_subs) >= MAX_OPEN_SUBSCRIPTIONS:
            raise CapExceeded(
                "max_open_subscriptions",
                f"{MAX_OPEN_SUBSCRIPTIONS} subscriptions are already open; release something first",
            )
        if kind_enum is SubscriptionKind.PIN:
            open_pins = [s for s in open_subs if s.kind is SubscriptionKind.PIN]
            if len(open_pins) >= MAX_PINS:
                raise CapExceeded(
                    "max_pins",
                    f"{MAX_PINS} levels are already pinned; release one to pin another",
                )

        for existing in open_subs:
            if existing.kind is kind_enum and existing.condition == condition and existing.params == params:
                return existing, False

        default_hours, max_hours = (
            (PIN_TTL_DEFAULT_HOURS, PIN_TTL_MAX_HOURS)
            if kind_enum is SubscriptionKind.PIN
            else (WATCH_TTL_DEFAULT_HOURS, WATCH_TTL_MAX_HOURS)
        )
        ttl = default_hours if ttl_hours is None else float(ttl_hours)
        if ttl <= 0:
            raise StoreError("invalid_ttl", "ttl_hours must be > 0")
        if ttl > max_hours:
            raise StoreError(
                "ttl_beyond_max",
                f"ttl_hours {ttl:g} exceeds the {max_hours:g}h cap for a {kind_enum.value}",
            )

        starts = _as_aware(starts_at) if starts_at else now
        sub = Subscription(
            id=_new_id(kind_enum.value),
            kind=kind_enum,
            condition=condition,
            params=params,
            starts_at=starts,
            expires_at=starts + timedelta(hours=ttl),
            one_shot=bool(one_shot),
            wake_on_expiry=bool(wake_on_expiry),
            state=SubscriptionState.ARMED,
            fire_count=0,
            last_evaluated_at=now,
            level_key=params.get("level_key"),
            status=LevelStatus.LIVE if kind_enum is SubscriptionKind.PIN else None,
            reason=reason,
            note=note,
        )
        self.data.subscriptions.append(sub)
        self._touch()
        return sub, True

    def release_subscription(self, sub_id: str) -> Subscription:
        sub = self.get_subscription(sub_id)
        if sub.state in (SubscriptionState.EXPIRED, SubscriptionState.RELEASED):
            raise StoreError("not_releasable", f"{sub_id!r} is already {sub.state.value}")
        sub.state = SubscriptionState.RELEASED
        self._touch()
        return sub

    def mark_fired(self, sub_id: str, now: Optional[datetime] = None) -> Subscription:
        now = now or self._clock()
        sub = self.get_subscription(sub_id)
        if sub.state is not SubscriptionState.ARMED:
            raise StoreError("not_armed", f"{sub_id!r} is {sub.state.value}, not armed")
        sub.fire_count += 1
        sub.last_fired_at = now
        sub.last_evaluated_at = now
        if sub.one_shot:
            sub.state = SubscriptionState.FIRED
        self._touch()
        return sub

    def mark_evaluated(
        self,
        sub_ids: Union[str, Iterable[str]],
        now: Optional[datetime] = None,
    ) -> None:
        """Advance ``last_evaluated_at`` for armed subscriptions that did not fire.

        A subscription's evaluation window must keep moving even when nothing
        happened, or it would grow without bound and re-report old events. Only
        armed subscriptions are advanced (a fired/expired/released one is done).
        Accepts a single id or an iterable of ids.
        """
        ids = {sub_ids} if isinstance(sub_ids, str) else set(sub_ids)
        now = now or self._clock()
        changed = False
        for sub in self.data.subscriptions:
            if sub.id in ids and sub.state is SubscriptionState.ARMED:
                sub.last_evaluated_at = now
                changed = True
        if changed:
            self._touch()

    def expire_due(self, now: Optional[datetime] = None) -> List[Subscription]:
        """Retire armed subscriptions whose deadline has passed. Returns them."""
        now = now or self._clock()
        expired: List[Subscription] = []
        for sub in self.data.subscriptions:
            if sub.state is SubscriptionState.ARMED and sub.expires_at and _as_aware(sub.expires_at) <= now:
                sub.state = SubscriptionState.EXPIRED
                expired.append(sub)
        if expired:
            self._touch()
        return expired

    # ------------------------------------------------------------------ thesis / proposals

    def set_thesis(
        self,
        *,
        bias: Optional[str] = None,
        storyline: Optional[str] = None,
        levels_of_interest: Optional[List[str]] = None,
        invalidation: Optional[str] = None,
        confidence: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> Thesis:
        thesis = self.data.thesis
        if bias is not None:
            if bias not in VALID_BIAS:
                raise StoreError("invalid_bias", f"bias must be one of {sorted(VALID_BIAS)}")
            thesis.bias = bias
        if storyline is not None:
            thesis.storyline = str(storyline)
        if levels_of_interest is not None:
            thesis.levels_of_interest = [str(k) for k in levels_of_interest]
        if invalidation is not None:
            thesis.invalidation = str(invalidation)
        if confidence is not None:
            thesis.confidence = float(confidence)
        thesis.updated_at = now or self._clock()
        self._touch()
        return thesis

    def add_proposal(
        self,
        *,
        bias: str = "none",
        setup: str = "",
        entry: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        invalidation: str = "",
        confidence: float = 0.0,
        reason: str = "",
        provenance: Optional[List[str]] = None,
        now: Optional[datetime] = None,
    ) -> Proposal:
        if bias not in VALID_BIAS:
            raise StoreError("invalid_bias", f"bias must be one of {sorted(VALID_BIAS)}")
        proposal = Proposal(
            id=_new_id("prop"),
            created_at=now or self._clock(),
            bias=bias,
            setup=setup,
            entry=entry,
            sl=sl,
            tp=tp,
            invalidation=invalidation,
            confidence=float(confidence),
            reason=reason,
            provenance=[str(k) for k in (provenance or [])],
            status=ProposalStatus.PROPOSED,
        )
        self.data.proposals.append(proposal)
        self._touch()
        return proposal

    def set_proposal_status(self, proposal_id: str, status: str) -> Proposal:
        for proposal in self.data.proposals:
            if proposal.id == proposal_id:
                try:
                    proposal.status = ProposalStatus(status)
                except ValueError:
                    raise StoreError("invalid_status", f"status must be one of {[s.value for s in ProposalStatus]}")
                self._touch()
                return proposal
        raise StoreError("unknown_proposal", f"no proposal {proposal_id!r}")

    # ------------------------------------------------------------------ leash / turns

    def check_leash(self, now: Optional[datetime] = None) -> None:
        """Refuse to start a turn if the leash says no. Raises :class:`LeashExceeded`."""
        now = now or self._clock()
        now = _as_aware(now)
        self._roll_windows(now)
        b = self.data.budget

        if b.last_turn_at is not None:
            since = (now - _as_aware(b.last_turn_at)).total_seconds()
            if since < MIN_TURN_INTERVAL_S:
                raise LeashExceeded(
                    "min_turn_interval",
                    f"only {since:.0f}s since the last turn; minimum is {MIN_TURN_INTERVAL_S}s",
                )
        if b.turns_this_hour >= MAX_TURNS_PER_HOUR:
            raise LeashExceeded("max_turns_per_hour", f"{MAX_TURNS_PER_HOUR} turns already this hour")
        if b.turns_today >= MAX_TURNS_PER_DAY:
            raise LeashExceeded("max_turns_per_day", f"{MAX_TURNS_PER_DAY} turns already today")
        if b.spend_usd_today >= MAX_SPEND_PER_DAY_USD:
            raise LeashExceeded(
                "max_spend_per_day",
                f"${b.spend_usd_today:.2f} spent today, cap is ${MAX_SPEND_PER_DAY_USD:.2f}",
            )

    def record_turn(
        self,
        trigger: str,
        *,
        trigger_detail: str = "",
        renders: int = 0,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tokens: int = 0,
        cost_usd: float = 0.0,
        output: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> TurnRecord:
        """Check the leash, then append a turn and bill it."""
        now = now or self._clock()
        now = _as_aware(now)
        self.check_leash(now)

        try:
            trigger_enum = Trigger(trigger)
        except ValueError:
            raise StoreError("invalid_trigger", f"trigger must be one of {[t.value for t in Trigger]}")

        record = TurnRecord(
            id=_new_id("turn"),
            started_at=now,
            ended_at=now,
            trigger=trigger_enum,
            trigger_detail=trigger_detail,
            view=self.data.view.to_dict(),
            subscriptions=[
                {
                    "id": s.id,
                    "kind": s.kind.value,
                    "condition": s.condition,
                    "params": s.params,
                    "state": s.state.value,
                    "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                }
                for s in self.open_subscriptions()
            ],
            tool_calls=list(tool_calls or []),
            output=dict(output or {}),
            renders=int(renders),
            tokens=int(tokens),
            cost_usd=float(cost_usd),
        )
        self.data.turns.append(record)

        b = self.data.budget
        b.turns_today += 1
        b.turns_this_hour += 1
        b.renders_today += int(renders)
        b.spend_usd_today += float(cost_usd)
        b.last_turn_at = now
        self.data.agent.last_evaluated_at = now
        self._touch()
        return record

    def set_enabled(self, enabled: bool, now: Optional[datetime] = None) -> AgentMeta:
        self.data.agent.enabled = bool(enabled)
        self.data.agent.mode = AgentMode.PROPOSE
        self._touch()
        return self.data.agent
