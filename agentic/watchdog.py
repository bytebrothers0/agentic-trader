"""The Watchdog — the LLM-free, render-free evaluator loop (spec phase 2, part B).

The Watchdog is what makes the agent *self-starting*. It owns no intelligence and
no state beyond the turn it is currently assembling: it drives
:mod:`agentic.subscriptions` over the store's open subscriptions, retires what
fired, and turns a burst of events into **one** turn.

The model
---------
* **Cadence.** The caller schedules ``scan`` on the close of any bar whose
  timeframe an open subscription references (:meth:`Watchdog.due_timeframes`
  answers that question), plus a throttled price check (:meth:`Watchdog.price_check_due`
  at the ``PRICE_CHECK_S`` cadence) for price-based conditions. Each scan advances
  every subscription's evaluation window, fired or not, so an unfired watch's
  window can never grow unbounded.
* **Coalescing.** A burst of fires is usually one regime event. Fires (and
  wake-on-expiry deadlines) accumulate in a pending buffer; the buffer is emitted
  as a :class:`TurnRequest` only once ``COALESCE_WINDOW_S`` has passed since the
  first thing landed in it, so multiple events merge into one turn.
* **Expiry is not a fire.** A plain expiry is never a wake — it is buffered and
  reported in the next turn's ``expired`` briefing ("3 watches expired since your
  last turn"). A subscription may opt in with ``wake_on_expiry`` to make the
  deadline itself a reason to wake.
* **Backfill on boot.** The Watchdog is not running while the process is down. On
  startup, :meth:`Watchdog.backfill` re-evaluates every open subscription over
  ``(last_evaluated_at, now]`` and marks the missed fires ``retroactive`` so they
  are never re-reported as live. It emits no turn — the mandatory boot turn
  carries them in its briefing.

Triggers and causes
-------------------
A :class:`TurnRequest` carries two separate ideas. ``trigger`` is always a
:class:`agentic.models.Trigger` value (``fire`` / ``request`` / ``boot``), so it
can be fed straight to :meth:`agentic.store.ContextStore.record_turn`; a
scan-emitted turn is always ``fire``. ``cause`` is the fine-grained composition
(``fire`` / ``expiry`` / ``fire+expiry``) that explains *what* happened.

Purity
------
This module reads no clock and touches nothing outside ``agentic.*`` and the
standard library. The clock is injected (``clock=``); there is deliberately no
``datetime.now`` fallback, so a missing clock fails loudly rather than silently
making evaluation non-deterministic. The ``feed`` is injected too; the Watchdog
never imports the server.

Cooldown on backfill
--------------------
The ``SUB_COOLDOWN_S`` gate exists to stop a *repeating* watch machine-gunning
live fires; it is applied in :meth:`Watchdog.scan`. It is deliberately **not**
applied in :meth:`Watchdog.backfill`, whose whole purpose is to not lose events —
a suppressed retroactive fire would vanish, because backfill also advances the
window. Both loops share :meth:`Watchdog._evaluate_open`, which is the single home
of that invariant. In practice the two agree, since downtime is normally longer
than the cooldown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import floor
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentic import subscriptions
from agentic.feed import Feed
from agentic.models import Serde, Subscription, Trigger, validate_timeframe
from agentic.store import SUB_COOLDOWN_S, ContextStore
from agentic.subscriptions import FireResult

#: Fires inside this window merge into one turn (spec: proposal 45s).
COALESCE_WINDOW_S = 45.0
#: Throttled cadence for price-based conditions (spec: proposal 15s).
PRICE_CHECK_S = 15.0

#: MT5 has no fixed month length; the convention here matches the indicator suite.
MONTH_S = 2592000.0  # 30 days

_UNITS = {"M": 60.0, "H": 3600.0, "D": 86400.0, "W": 604800.0}


def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _missing_clock() -> datetime:
    raise RuntimeError(
        "Watchdog has no clock: pass clock=<callable>()= — the pure core never "
        "reads the wall clock (inject one, or pass now= to scan/backfill/flush)"
    )


def bar_seconds(timeframe: str) -> float:
    """Length of one bar in seconds, for the timeframe grammar of the models.

    Derives directly from :func:`agentic.models.validate_timeframe`: ``M`` minutes,
    ``H`` hours, ``D`` days, ``W`` weeks, and ``MN``/``MNn`` months. A month is
    ``MONTH_S`` (30 days) — MT5's convention, since a month has no fixed length.
    A zero count (``M0``, ``MN0``) is rejected like any other non-positive bar.
    """
    tf = validate_timeframe(str(timeframe))
    if tf.startswith("MN"):
        count, unit = int(tf[2:] or "1"), MONTH_S
    else:
        count, unit = int(tf[1:]), _UNITS[tf[0]]
    value = unit * count
    if value <= 0:
        raise ValueError(f"timeframe {timeframe!r} has a non-positive bar length")
    return value


# --------------------------------------------------------------------------- #
# Turn shapes
# --------------------------------------------------------------------------- #

@dataclass
class TurnRequest(Serde):
    """One turn the agent loop should run, with everything that caused it.

    ``trigger`` is always a :class:`agentic.models.Trigger` value, so it can be
    handed straight to :meth:`agentic.store.ContextStore.record_turn`. ``cause``
    carries the fine-grained composition (``fire`` / ``expiry`` / ``fire+expiry``)
    for the briefing. ``fires`` and ``expired`` are the whole buffered batch, so a
    burst of events is reported as one turn.
    """

    trigger: str = Trigger.FIRE.value
    cause: str = "fire"
    fires: List[FireResult] = field(default_factory=list)
    expired: List[Subscription] = field(default_factory=list)
    created_at: Optional[datetime] = None
    reason: str = ""


@dataclass
class ScanResult(Serde):
    """What one :meth:`Watchdog.scan` did.

    ``new_fires`` fired in *this* scan; ``expired`` are the subscriptions that
    newly expired in it. ``turn`` is set only when the coalescing window had
    elapsed and the buffers were emitted. ``pending_*`` is what is still buffered.
    """

    evaluated_at: datetime
    new_fires: List[FireResult] = field(default_factory=list)
    expired: List[Subscription] = field(default_factory=list)
    turn: Optional[TurnRequest] = None
    pending_fires: int = 0
    pending_expired: int = 0


@dataclass
class BackfillResult(Serde):
    """Missed events recovered on boot. Every fire is ``retroactive=True``."""

    evaluated_at: datetime
    fires: List[FireResult] = field(default_factory=list)


def _cause(fires: List[FireResult], woke: bool) -> str:
    """The fine-grained composition of a turn: what actually happened."""
    if fires and woke:
        return "fire+expiry"
    if woke:
        return "expiry"
    return "fire"


def _reason(fires: List[FireResult], expired: List[Subscription]) -> str:
    bits = []
    if fires:
        bits.append(f"{len(fires)} fire(s)")
    if expired:
        bits.append(f"{len(expired)} expiry(ies)")
    return ", ".join(bits) or "nothing pending"


# --------------------------------------------------------------------------- #
# The Watchdog
# --------------------------------------------------------------------------- #

class Watchdog:
    """Drives the condition evaluator over a store, and coalesces the fires.

    ``feed`` is an :class:`agentic.feed.Feed` (or any object with the same
    ``snapshot``/``bars`` methods). ``clock`` is a zero-argument callable returning
    an aware UTC datetime. The cooldown defaults to
    :data:`agentic.store.SUB_COOLDOWN_S`.
    """

    def __init__(
        self,
        feed: Feed,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        coalesce_window_s: float = COALESCE_WINDOW_S,
        sub_cooldown_s: Optional[float] = None,
        price_check_s: float = PRICE_CHECK_S,
    ):
        self._feed = feed
        self._clock = clock or _missing_clock
        self.coalesce_window_s = float(coalesce_window_s)
        self.sub_cooldown_s = SUB_COOLDOWN_S if sub_cooldown_s is None else float(sub_cooldown_s)
        self.price_check_s = float(price_check_s)

        self._pending_fires: List[FireResult] = []
        self._pending_expired: List[Subscription] = []
        self._pending_wake: List[Subscription] = []
        self._window_start: Optional[datetime] = None

    # ------------------------------------------------------------------ buffers

    def pending(self) -> List[FireResult]:
        """The buffered *fires* not yet emitted as a turn (a copy)."""
        return list(self._pending_fires)

    def pending_expiries(self) -> List[Subscription]:
        """The buffered expiries awaiting the next turn's briefing (a copy)."""
        return list(self._pending_expired)

    def _has_pending_event(self) -> bool:
        """Whether the buffer holds anything that can *cause* a turn.

        Non-wake expiries ride along with the next turn but never create one.
        """
        return bool(self._pending_fires or self._pending_wake)

    def _emit(self, now: datetime, trigger: Trigger) -> TurnRequest:
        fires = list(self._pending_fires)
        expired = list(self._pending_expired)
        woke = bool(self._pending_wake)
        self._pending_fires = []
        self._pending_expired = []
        self._pending_wake = []
        self._window_start = None
        return TurnRequest(
            trigger=trigger.value,
            cause=_cause(fires, woke),
            fires=fires,
            expired=expired,
            created_at=now,
            reason=_reason(fires, expired),
        )

    # ------------------------------------------------------------------ cadence

    def _timeframe_for(self, sub: Subscription, store: ContextStore) -> str:
        return str(sub.params.get("timeframe") or store.data.view.timeframe)

    def price_check_due(self, last_check_at: Optional[datetime], now: datetime) -> bool:
        """Whether the throttled price check is due.

        The caller tracks its last price check and, for price-based conditions,
        wakes the loop when this is true. No prior check (``None``) is always due;
        the exact ``price_check_s`` boundary counts as due.
        """
        if last_check_at is None:
            return True
        elapsed = (_as_aware(now) - _as_aware(last_check_at)).total_seconds()
        return elapsed >= self.price_check_s

    def referenced_timeframes(self, store: ContextStore) -> List[Tuple[str, str]]:
        """Sorted, de-duplicated ``(symbol, timeframe)`` the open subs need."""
        symbol = store.data.view.symbol
        timeframes = {self._timeframe_for(sub, store) for sub in store.open_subscriptions()}
        return sorted((symbol, tf) for tf in timeframes)

    def due_timeframes(
        self,
        store: ContextStore,
        since: datetime,
        now: datetime,
    ) -> List[Tuple[str, str]]:
        """Referenced timeframes with a bar close in ``(since, now]``.

        Boundaries are epoch-aligned (``bar_seconds``), which is how MT5 stamps
        bars. Naive datetimes are read as UTC.
        """
        since = _as_aware(since)
        now = _as_aware(now)
        since_ts, now_ts = since.timestamp(), now.timestamp()
        due: List[Tuple[str, str]] = []
        for symbol, tf in self.referenced_timeframes(store):
            step = bar_seconds(tf)
            first_boundary = (floor(since_ts / step) + 1) * step
            if first_boundary <= now_ts:
                due.append((symbol, tf))
        return due

    # ------------------------------------------------------------------ feeding

    def _snapshot_and_bars(
        self,
        symbol: str,
        timeframe: str,
        store: ContextStore,
        cache: Dict[Any, Any],
    ) -> Tuple[Any, Any]:
        """Fetch each ``(symbol, timeframe)`` at most once per scan."""
        key = (symbol, str(timeframe))
        if key not in cache:
            snapshot = self._feed.snapshot(symbol, timeframe)
            bars = self._feed.bars(symbol, timeframe, bars=int(store.data.view.bars))
            cache[key] = (snapshot, bars)
        return cache[key]

    def _in_cooldown(self, sub: Subscription, now: datetime) -> bool:
        if sub.one_shot or sub.last_fired_at is None:
            return False
        return (now - _as_aware(sub.last_fired_at)).total_seconds() < self.sub_cooldown_s

    def _evaluate_open(
        self,
        store: ContextStore,
        now: datetime,
        cache: Dict[Any, Any],
    ) -> List[Tuple[Subscription, Optional[FireResult]]]:
        """Evaluate every open subscription once, sharing the per-scan feed cache.

        Returns ``(sub, fire-or-None)`` per subscription. The cooldown gate and the
        ``retroactive`` marking are deliberately the *callers'* business, so the
        invariant lives in exactly one place: :meth:`scan` applies
        :meth:`_in_cooldown` (the live cadence), :meth:`backfill` does not (its
        whole point is to not lose missed events), and only :meth:`backfill` marks
        a fire ``retroactive``.
        """
        symbol = store.data.view.symbol
        evaluated: List[Tuple[Subscription, Optional[FireResult]]] = []
        for sub in store.open_subscriptions():
            timeframe = self._timeframe_for(sub, store)
            snapshot, bars = self._snapshot_and_bars(symbol, timeframe, store, cache)
            fired = subscriptions.evaluate(
                sub,
                snapshot,
                bars,
                now=now,
                last_evaluated_at=sub.last_evaluated_at,
            )
            evaluated.append((sub, fired))
        return evaluated

    # ------------------------------------------------------------------ scanning

    def scan(self, store: ContextStore, *, now: Optional[datetime] = None) -> ScanResult:
        """One evaluation pass: retire expiries, evaluate, and maybe emit a turn."""
        now = _as_aware(now or self._clock())
        has_event_before = self._has_pending_event()  # before this scan's events land

        expired = list(store.expire_due(now))
        if expired:
            self._pending_expired.extend(expired)
            self._pending_wake.extend(sub for sub in expired if sub.wake_on_expiry)

        new_fires: List[FireResult] = []
        evaluated: List[str] = []
        for sub, fired in self._evaluate_open(store, now, {}):
            evaluated.append(sub.id)
            if fired is None or self._in_cooldown(sub, now):
                continue
            store.mark_fired(sub.id, now)
            new_fires.append(fired)

        # Advance the window for every subscription we looked at, fired or not.
        if evaluated:
            store.mark_evaluated(evaluated, now)

        if new_fires:
            self._pending_fires.extend(new_fires)
        if not has_event_before and self._has_pending_event():
            self._window_start = now  # the coalescing window opens on the first event

        turn: Optional[TurnRequest] = None
        if self._has_pending_event() and self._window_start is not None:
            if (now - self._window_start).total_seconds() >= self.coalesce_window_s:
                turn = self._emit(now, Trigger.FIRE)

        return ScanResult(
            evaluated_at=now,
            new_fires=new_fires,
            expired=expired,
            turn=turn,
            pending_fires=len(self._pending_fires),
            pending_expired=len(self._pending_expired),
        )

    def backfill(self, store: ContextStore, *, now: Optional[datetime] = None) -> BackfillResult:
        """Recover fires missed while the process was down. Emits no turn."""
        now = _as_aware(now or self._clock())
        fires: List[FireResult] = []
        evaluated: List[str] = []
        for sub, fired in self._evaluate_open(store, now, {}):
            evaluated.append(sub.id)
            if fired is None:
                continue
            fired.retroactive = True  # only backfill reports missed fires
            store.mark_fired(sub.id, now)
            fires.append(fired)

        if evaluated:
            store.mark_evaluated(evaluated, now)
        return BackfillResult(evaluated_at=now, fires=fires)

    def flush(
        self,
        *,
        now: Optional[datetime] = None,
        trigger: str = Trigger.REQUEST.value,
    ) -> Optional[TurnRequest]:
        """Force-emit the pending buffers, bypassing the coalescing window.

        Used for ``request``/``boot`` turns: the caller supplies the trigger
        (constrained to :class:`agentic.models.Trigger`), since the turn happened
        because a human or the boot asked, not because the coalescing window
        elapsed. Returns ``None`` when nothing is pending.
        """
        trigger = Trigger(trigger)  # constrained to the store's vocabulary
        now = _as_aware(now or self._clock())
        if not (self._pending_fires or self._pending_wake or self._pending_expired):
            return None
        return self._emit(now, trigger)
