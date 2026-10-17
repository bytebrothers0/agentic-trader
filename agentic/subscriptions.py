"""The deterministic condition evaluator (spec phase 2, part A).

This is the Watchdog's brain, minus the clock. It answers exactly one question,
with no randomness and no model:

    did this subscription's condition *newly* occur in ``(last_evaluated_at, now]``?

The window is the whole trick. Every condition is **edge-triggered**: it fires on
the rising edge ``false -> true``, never on every evaluation while it stays true.
Two consecutive windows ``(t0, t1]`` and ``(t1, t2]`` share no event time, so an
event at ``t1`` fires once, in the first window. The evaluator never mutates the
subscription (the store owns state) and never mutates the snapshot.

What "the event" means, per condition
-------------------------------------
* level conditions fire at :func:`event_time` — ``changed_at`` if the level's
  freshness tracker moved it, else ``formed_at``.
* price conditions fire at the bar that crossed / entered (never at ``now``).
* session conditions fire at the UTC boundary that fell inside the window.
* a pin (``level_alive``) fires either when the event time of its non-``live``
  status is in the window, or when the level is no longer produced at all; the
  latter has no event time of its own, so it fires at ``now`` — but only when the
  window is non-empty (a zero-width window cannot have observed a disappearance).

Sessions (UTC, documented, fixed)
---------------------------------
``asia`` 00:00–08:00 · ``london`` 07:00–16:00 · ``ny`` 12:00–21:00. A
``session_opens`` fires at the open boundary, a ``session_closes`` at the close.
When more than one boundary of the same kind falls in a (backfill) window, the
**earliest** is reported — the first missed fire is the one that matters. With
``last_evaluated_at=None`` the search is bounded to the **24 hours** preceding
``now`` (it does not scan the whole history), so at most one occurrence of a given
boundary is ever considered.

``price_crosses`` (documented edge)
-----------------------------------
A bar crosses ``price`` only when the previous close and the current close lie on
**strictly opposite** sides: ``prev < price < cur`` or ``prev > price > cur``. A
close landing exactly on the level is not itself a cross; the cross fires on the
bar that closes through it. This keeps one crossing from firing twice across
consecutive windows.

``range_expands`` (documented definition)
-----------------------------------------
The "session window" is the **UTC calendar day of the latest bar**. Its range is
``max(high) - min(low)`` over the bars of that day. A ``range_expands`` fires at
the first bar of that day whose inclusion pushed the day's running range above
``multiple × reference`` — provided that bar's time is in the evaluation window,
so a range that was already wide before the window does not fire. ``reference``:

* ``ATR`` — the snapshot's ``atr`` (the current ATR of the timeframe). A
  non-positive reference cannot fire.
* ``ADR`` — the mean of the **prior** days' ranges present in the bars (the
  current day is excluded). With no prior complete day there is no reference and
  nothing can fire.

Responsibility split
--------------------
The evaluator owns **no** timeframe routing. If a condition names a ``timeframe``,
it is matched against the level's own ``timeframe`` and evaluated against whatever
the caller passed; the caller is expected to fetch the right ``(symbol, timeframe)``
snapshot and bars. ``now`` and ``last_evaluated_at`` are timezone-aware (assumed
UTC); a naive datetime is read as UTC. ``last_evaluated_at=None`` means the lower
bound is open — everything up to ``now`` counts.

Malformed parameters are not this module's problem: the store validates params at
creation (:func:`agentic.conditions.validate`), so the evaluator assumes valid
input and raises only for an unknown *condition* name, which would be a bug.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as _time, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from agentic.conditions import Condition
from agentic.feed import BOS, IDM, Bars, FeedSnapshot, LevelRecord
from agentic.models import LevelStatus, Serde, Subscription, SubscriptionState

UTC = timezone.utc

#: (open, close) UTC boundaries per session, as documented in the module docstring.
SESSION_BOUNDARIES: Dict[str, Tuple[_time, _time]] = {
    "asia": (_time(0, 0), _time(8, 0)),
    "london": (_time(7, 0), _time(16, 0)),
    "ny": (_time(12, 0), _time(21, 0)),
}


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #

@dataclass
class FireResult(Serde):
    """What the Watchdog hands the agent loop: proof that a subscription fired.

    ``fired_at`` is the **event** time, not the evaluation time. ``retroactive``
    is always ``False`` here — only the Watchdog, which knows whether the process
    was running, can mark a backfilled fire as retroactive. ``state_after`` is the
    projection of what the store will do (``fired`` for a one-shot, ``armed`` for
    a repeating watch); the evaluator never performs that transition itself.
    """

    subscription_id: str = ""
    kind: str = ""
    condition: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    fired_at: Optional[datetime] = None
    retroactive: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)
    state_before: str = "armed"
    state_after: str = "armed"
    reason: str = ""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _bar_time(bars: Bars, index: int) -> datetime:
    return datetime.fromtimestamp(int(bars.times[index]), tz=UTC)


def _in_window(event: Optional[datetime], last: Optional[datetime], now: datetime) -> bool:
    """``last < event <= now``; with ``last=None`` the lower bound is open."""
    event = _as_aware(event)
    if event is None:
        return False
    if last is None:
        return event <= now
    return last < event <= now


def event_time(level: LevelRecord) -> Optional[datetime]:
    """The moment a level's event happened: ``changed_at`` if set, else ``formed_at``."""
    return level.changed_at or level.formed_at


def _condition_name(condition: Any) -> str:
    return condition.value if isinstance(condition, Enum) else str(condition)


def _bar_evidence(bars: Bars, index: int) -> Dict[str, Any]:
    return {
        "time": int(bars.times[index]),
        "open": bars.open[index],
        "high": bars.high[index],
        "low": bars.low[index],
        "close": bars.close[index],
    }


def _parse_iso(raw: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #

@dataclass
class _Ctx:
    sub: Subscription
    snapshot: FeedSnapshot
    bars: Optional[Bars]
    now: datetime
    last: Optional[datetime]
    params: Dict[str, Any]

    def window_indices(self) -> List[int]:
        """Indices of bars whose time lies in the window, ascending.

        ``Bars.times`` is ascending (``parse_candles`` sorts it), so the window is
        a contiguous slice: its upper bound is :meth:`Bars.index_at_or_before` of
        ``now`` and its lower bound is one past the index at or before ``last``.
        """
        if self.bars is None or len(self.bars) == 0:
            return []
        upper = self.bars.index_at_or_before(self.now)
        if upper < 0:
            return []
        lower = 0 if self.last is None else self.bars.index_at_or_before(self.last) + 1
        if lower > upper:
            return []
        return list(range(lower, upper + 1))

    def resolve_level(self) -> Optional[LevelRecord]:
        """The level a ``level_key`` or ``family``+``price`` reference points at."""
        key = self.params.get("level_key")
        if key:
            return self.snapshot.by_key(str(key))

        family = self.params.get("family")
        price = self.params.get("price")
        if family is None or price is None:
            return None

        candidates = [
            lvl
            for lvl in self.snapshot.family(str(family))
            if self.timeframe_ok(lvl) and self.direction_ok(lvl)
        ]
        tolerance = self.params.get("tolerance")
        if tolerance is not None:
            candidates = [lvl for lvl in candidates if abs(lvl.price - float(price)) <= float(tolerance)]
        if not candidates:
            return None
        return min(candidates, key=lambda lvl: abs(lvl.price - float(price)))

    def timeframe_ok(self, level: LevelRecord) -> bool:
        want = self.params.get("timeframe")
        return not want or level.timeframe == str(want)

    def direction_ok(self, level: LevelRecord) -> bool:
        want = self.params.get("direction")
        return not want or level.direction == str(want)


# --------------------------------------------------------------------------- #
# Level formation
# --------------------------------------------------------------------------- #

def _h_level_forms(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    family = str(ctx.params.get("family"))
    min_size = ctx.params.get("min_size_atr")
    variant = ctx.params.get("variant")
    min_inside = ctx.params.get("min_inside_bars")

    matches: List[LevelRecord] = []
    for level in ctx.snapshot.levels:
        if level.family != family:
            continue
        if not ctx.timeframe_ok(level) or not ctx.direction_ok(level):
            continue
        if variant is not None and level.variant != str(variant):
            continue
        if min_inside is not None and level.inside_bars < int(min_inside):
            continue
        if min_size is not None:
            atr = float(ctx.snapshot.atr or 0.0)
            if atr <= 0:
                continue  # cannot judge size without a reference
            band = level.band()
            size = (band[1] - band[0]) if band else 0.0
            if size < atr * float(min_size):
                continue
        if _in_window(level.formed_at, ctx.last, ctx.now):
            matches.append(level)

    if not matches:
        return None
    level = min(matches, key=lambda lvl: _as_aware(lvl.formed_at))
    return level.formed_at, level.to_dict(), f"{family} level formed"


def _status_handler(required: LevelStatus):
    def handler(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
        level = ctx.resolve_level()
        if level is None or level.status is not required:
            return None
        when = event_time(level)
        if not _in_window(when, ctx.last, ctx.now):
            return None
        return when, level.to_dict(), f"level {required.value}"

    return handler


def _h_level_touched(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    if ctx.bars is None:
        return None
    level = ctx.resolve_level()
    if level is None:
        return None
    band = level.band()
    if band:
        target_low, target_high = min(band), max(band)
    else:
        target_low = target_high = level.price

    for index in ctx.window_indices():
        if ctx.bars.low[index] <= target_high and ctx.bars.high[index] >= target_low:
            at = _bar_time(ctx.bars, index)
            evidence = {"level": level.to_dict(), "bar": _bar_evidence(ctx.bars, index)}
            return at, evidence, f"price touched {level.price}"
    return None


def _h_level_alive(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    level = ctx.resolve_level()
    if level is None:
        # The level is not being produced any more. There is no level event time,
        # so it is noticed at `now` — but only if the window is non-empty.
        if not _in_window(ctx.now, ctx.last, ctx.now):
            return None
        key = ctx.sub.level_key or ctx.params.get("level_key") or ""
        evidence = {"level_key": str(key), "status": LevelStatus.NOT_FOUND.value}
        return ctx.now, evidence, "level no longer produced"
    if level.status is LevelStatus.LIVE:
        return None
    when = event_time(level)
    if not _in_window(when, ctx.last, ctx.now):
        return None
    return when, level.to_dict(), f"level {level.status.value}"


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #

def _internal_ok(level: LevelRecord, internal: bool) -> bool:
    """Internal/external filter for BOS/CHoCH levels.

    ``parse_level`` tags ``bos`` records with ``attrs["internal"]`` from the
    ``I-`` prefix of the payload token (``I-BOS``/``I-CHOCH`` are internal).
    """
    return bool(level.attrs.get("internal")) == bool(internal)


def _bos_handler(kind: str):
    def handler(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
        internal = ctx.params.get("internal")
        matches: List[Tuple[datetime, LevelRecord]] = []
        for level in ctx.snapshot.levels:
            if level.family != BOS:
                continue
            if level.attrs.get("kind") != kind:
                continue
            if not ctx.timeframe_ok(level) or not ctx.direction_ok(level):
                continue
            if internal is not None and not _internal_ok(level, bool(internal)):
                continue
            when = event_time(level)
            if _in_window(when, ctx.last, ctx.now):
                matches.append((_as_aware(when), level))
        if not matches:
            return None
        when, level = min(matches, key=lambda pair: pair[0])
        return when, level.to_dict(), f"{kind} printed"

    return handler


def _h_idm_swept(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    rule = ctx.params.get("rule")
    matches: List[Tuple[datetime, LevelRecord]] = []
    for level in ctx.snapshot.levels:
        if level.family != IDM or level.status is not LevelStatus.SWEPT:
            continue
        if not ctx.timeframe_ok(level):
            continue
        if rule is not None and str(level.attrs.get("rule", "")) != str(rule):
            continue
        when = event_time(level)
        if _in_window(when, ctx.last, ctx.now):
            matches.append((_as_aware(when), level))
    if not matches:
        return None
    when, level = min(matches, key=lambda pair: pair[0])
    return when, level.to_dict(), "IDM swept"


# --------------------------------------------------------------------------- #
# Price
# --------------------------------------------------------------------------- #

def _crosses(previous: float, current: float, price: float) -> bool:
    """Did the close move *strictly* across ``price`` between two bars?

    A close landing exactly on ``price`` is not itself a cross: the crossing bar
    is the one that closes through the level, so ``prev < price < cur`` (or the
    mirror) is the only thing that counts.
    """
    return (previous < price < current) or (previous > price > current)


def _h_price_crosses(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    if ctx.bars is None or len(ctx.bars) == 0:
        return None
    price = float(ctx.params["price"])
    for index in ctx.window_indices():
        if index == 0:
            continue
        if _crosses(ctx.bars.close[index - 1], ctx.bars.close[index], price):
            at = _bar_time(ctx.bars, index)
            evidence = {"price": price, "bar": _bar_evidence(ctx.bars, index)}
            return at, evidence, f"close crossed {price}"
    return None


def _overlaps(bars: Bars, index: int, low: float, high: float) -> bool:
    return bars.low[index] <= high and bars.high[index] >= low


def _h_price_enters_zone(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    if ctx.bars is None or len(ctx.bars) == 0:
        return None
    low = float(ctx.params["low"])
    high = float(ctx.params["high"])
    for index in ctx.window_indices():
        if index == 0:
            continue
        if _overlaps(ctx.bars, index, low, high) and not _overlaps(ctx.bars, index - 1, low, high):
            at = _bar_time(ctx.bars, index)
            evidence = {"low": low, "high": high, "bar": _bar_evidence(ctx.bars, index)}
            return at, evidence, f"price entered [{low}, {high}]"
    return None


def _daily_ranges(bars: Bars) -> Dict[Any, float]:
    days: Dict[Any, List[float]] = {}
    for index in range(len(bars)):
        day = _bar_time(bars, index).date()
        span = days.setdefault(day, [float("inf"), float("-inf")])
        span[0] = min(span[0], bars.low[index])
        span[1] = max(span[1], bars.high[index])
    return {day: span[1] - span[0] for day, span in days.items()}


def _h_range_expands(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    if ctx.bars is None or len(ctx.bars) == 0:
        return None
    multiple = float(ctx.params["multiple"])
    reference = str(ctx.params.get("reference", "ATR")).upper()

    last_date = _bar_time(ctx.bars, len(ctx.bars) - 1).date()
    if reference == "ATR":
        reference_name = "atr"
        reference_value = float(ctx.snapshot.atr or 0.0)
    else:  # ADR
        ranges = _daily_ranges(ctx.bars)
        prior = [value for day, value in ranges.items() if day != last_date]
        reference_name = "adr"
        reference_value = sum(prior) / len(prior) if prior else 0.0

    if reference_value <= 0:
        return None
    threshold = multiple * reference_value

    session_high, session_low, crossing = float("-inf"), float("inf"), None
    for index in range(len(ctx.bars)):
        if _bar_time(ctx.bars, index).date() != last_date:
            continue
        session_high = max(session_high, ctx.bars.high[index])
        session_low = min(session_low, ctx.bars.low[index])
        if session_high - session_low > threshold:
            crossing = index
            break

    if crossing is None:
        return None
    at = _bar_time(ctx.bars, crossing)
    if not _in_window(at, ctx.last, ctx.now):
        return None
    evidence = {
        "bar": _bar_evidence(ctx.bars, crossing),
        "session_range": session_high - session_low,
        "multiple": multiple,
        "reference": reference_name,
        "reference_value": reference_value,
        "threshold": threshold,
    }
    return at, evidence, f"session range exceeded {multiple} x {reference_name}"


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #

def _boundary_in_window(ctx: _Ctx, boundary: _time) -> Optional[datetime]:
    start = (ctx.last - timedelta(days=1)) if ctx.last is not None else (ctx.now - timedelta(days=1))
    day = start.date()
    end = ctx.now.date()
    hits: List[datetime] = []
    while day <= end:
        candidate = datetime.combine(day, boundary, tzinfo=UTC)
        if _in_window(candidate, ctx.last, ctx.now):
            hits.append(candidate)
        day += timedelta(days=1)
    return min(hits) if hits else None


def _session_handler(which: str):
    def handler(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
        session = str(ctx.params["session"]).lower()
        spec = SESSION_BOUNDARIES.get(session)
        if spec is None:
            return None
        boundary = spec[0] if which == "open" else spec[1]
        at = _boundary_in_window(ctx, boundary)
        if at is None:
            return None
        label = boundary.strftime("%H:%M")
        evidence = {"session": session, "boundary": label, "at": at.isoformat()}
        return at, evidence, f"{session} {which} at {label} UTC"

    return handler


def _h_time_reached(ctx: _Ctx) -> Optional[Tuple[datetime, Dict[str, Any], str]]:
    raw = ctx.params.get("at")
    at = _parse_iso(raw)
    if at is None or not _in_window(at, ctx.last, ctx.now):
        return None
    return at, {"at": raw}, f"time reached {raw}"


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

_HANDLERS = {
    Condition.LEVEL_FORMS.value: _h_level_forms,
    Condition.LEVEL_TOUCHED.value: _h_level_touched,
    Condition.LEVEL_SWEPT.value: _status_handler(LevelStatus.SWEPT),
    Condition.LEVEL_BROKEN.value: _status_handler(LevelStatus.BROKEN),
    Condition.LEVEL_FILLED.value: _status_handler(LevelStatus.FILLED),
    Condition.LEVEL_ALIVE.value: _h_level_alive,
    Condition.BOS_FORMS.value: _bos_handler("BOS"),
    Condition.CHOCH_FORMS.value: _bos_handler("CHoCH"),
    Condition.IDM_SWEPT.value: _h_idm_swept,
    Condition.PRICE_CROSSES.value: _h_price_crosses,
    Condition.PRICE_ENTERS_ZONE.value: _h_price_enters_zone,
    Condition.RANGE_EXPANDS.value: _h_range_expands,
    Condition.SESSION_OPENS.value: _session_handler("open"),
    Condition.SESSION_CLOSES.value: _session_handler("close"),
    Condition.TIME_REACHED.value: _h_time_reached,
}


def _result(
    sub: Subscription,
    fired_at: datetime,
    evidence: Dict[str, Any],
    reason: str,
) -> FireResult:
    state_before = sub.state.value if isinstance(sub.state, Enum) else str(sub.state or SubscriptionState.ARMED.value)
    return FireResult(
        subscription_id=sub.id,
        kind=sub.kind.value if isinstance(sub.kind, Enum) else str(sub.kind),
        condition=_condition_name(sub.condition),
        params=dict(sub.params),
        fired_at=_as_aware(fired_at),
        retroactive=False,
        evidence=evidence,
        state_before=state_before,
        state_after=SubscriptionState.FIRED.value if sub.one_shot else SubscriptionState.ARMED.value,
        reason=reason,
    )


def evaluate(
    sub: Subscription,
    snapshot: FeedSnapshot,
    bars: Optional[Bars] = None,
    *,
    now: datetime,
    last_evaluated_at: Optional[datetime] = None,
) -> Optional[FireResult]:
    """Evaluate one subscription against one instant.

    Returns ``None`` when the condition did not newly occur in
    ``(last_evaluated_at, now]``, else a :class:`FireResult` whose ``fired_at`` is
    the event time. Never mutates ``sub`` or ``snapshot``. ``bars`` is required
    only for price/range conditions; it may be ``None`` for the rest.
    """
    name = _condition_name(sub.condition)
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"unknown condition: {name!r}")

    now = _as_aware(now)
    last = _as_aware(last_evaluated_at)
    ctx = _Ctx(
        sub=sub,
        snapshot=snapshot,
        bars=bars,
        now=now,
        last=last,
        params=dict(sub.params or {}),
    )
    outcome = handler(ctx)
    if outcome is None:
        return None
    fired_at, evidence, reason = outcome
    return _result(sub, fired_at, evidence, reason)
