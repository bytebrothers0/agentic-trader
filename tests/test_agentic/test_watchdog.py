"""Tests for the Watchdog (spec phase 2, part B acceptance criteria).

Everything runs on an injected clock and a ``Feed`` built from in-memory payload
dicts, so there is no MT5, no network and no real time anywhere in here. The
scenarios mirror the spec's Watchdog section: edge fires, coalescing, expiry vs
wake, and boot backfill.
"""
from datetime import timedelta

import pytest

from _fixtures import (
    FakeClock,
    at,
    candles_payload,
    level,
    snapshot_payload,
    ts,
)
from agentic.feed import Feed
from agentic.models import SubscriptionState, Trigger
from agentic.store import SUB_COOLDOWN_S, ContextStore
from agentic.watchdog import (
    COALESCE_WINDOW_S,
    PRICE_CHECK_S,
    BackfillResult,
    ScanResult,
    TurnRequest,
    Watchdog,
    bar_seconds,
)


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #

def _store(clock, tmp_path, *, symbol="XAUUSDm", timeframe="M15", bars=20):
    store = ContextStore(symbol, state_dir=str(tmp_path), clock=clock)
    store.set_view(timeframe=timeframe, bars=bars)
    return store


class FeedStub:
    """A :class:`Feed` whose ``(symbol, timeframe)`` payloads the test rewrites.

    Records what was fetched, so a test can prove the per-scan cache fetches each
    ``(symbol, timeframe)`` once.
    """

    def __init__(self, *, symbol="XAUUSDm", price=100.0, atr=5.0):
        self.symbol = symbol
        self.price = price
        self.atr = atr
        self.levels = {}
        self.candles = {}
        self.snapshot_calls = []
        self.bars_calls = []

    def set_levels(self, levels, timeframe="M15"):
        self.levels[timeframe] = list(levels)
        return self

    def set_candles(self, rows, timeframe="M15"):
        self.candles[timeframe] = candles_payload(rows, symbol=self.symbol, timeframe=timeframe)["candles"]
        return self

    def build(self) -> Feed:
        def provider(*, symbol, timeframe, families=None, bars=300, **kwargs):
            self.snapshot_calls.append((symbol, timeframe))
            return snapshot_payload(
                self.levels.get(timeframe, []),
                symbol=symbol,
                timeframe=timeframe,
                price=self.price,
                atr=self.atr,
            )

        def candles_provider(*, symbol, timeframe, bars=300, **kwargs):
            self.bars_calls.append((symbol, timeframe))
            return candles_payload(
                self.candles.get(timeframe, []), symbol=symbol, timeframe=timeframe
            )

        return Feed(provider=provider, candles_provider=candles_provider)


def _fvg(when, price=100.0):
    return level("fvg", price=price, time=ts(when), end_kind="active",
                 box_top=price + 1.0, box_bottom=price - 1.0)


def _watchdog(stub, clock, **kwargs):
    return Watchdog(stub.build(), clock=clock, **kwargs)


# --------------------------------------------------------------------------- #
# Edge fire + retirement
# --------------------------------------------------------------------------- #

def test_one_shot_level_forms_fires_once_and_retires(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    sub, created = store.add_subscription("watch", "level_forms", {"family": "fvg"}, now=clock())
    assert created
    stub = FeedStub()
    wd = _watchdog(stub, clock)

    # nothing formed yet -> no fire, and the window still advances.
    first = wd.scan(store, now=at(9, 0))
    assert first.new_fires == []
    assert first.turn is None
    assert store.get_subscription(sub.id).last_evaluated_at == at(9, 0)

    # a new FVG appears inside the next window.
    formed = at(9, 5)
    stub.set_levels([_fvg(formed)])
    second = wd.scan(store, now=at(9, 10))
    assert len(second.new_fires) == 1
    fire = second.new_fires[0]
    assert fire.fired_at == formed
    assert fire.condition == "level_forms"
    assert fire.state_after == SubscriptionState.FIRED.value

    # one_shot retires the watch, so a later scan cannot re-fire it.
    assert store.get_subscription(sub.id).state is SubscriptionState.FIRED
    assert store.open_subscriptions() == []
    third = wd.scan(store, now=at(9, 10) + timedelta(seconds=30))
    assert third.new_fires == []
    assert third.pending_fires == 1  # still buffered, waiting out the window
    assert third.turn is None

    # once the coalescing window has elapsed, the buffered fire is emitted once.
    emitted = wd.scan(store, now=at(9, 10) + timedelta(seconds=60))
    assert emitted.new_fires == []
    assert emitted.pending_fires == 0
    assert emitted.turn is not None
    assert [f.subscription_id for f in emitted.turn.fires] == [sub.id]


# --------------------------------------------------------------------------- #
# Pins
# --------------------------------------------------------------------------- #

def test_pin_fires_when_its_level_disappears(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    stub = FeedStub().set_levels([_fvg(at(8, 30))])
    pin, _ = store.add_subscription("pin", params={"family": "fvg", "price": 100.0}, now=clock())
    wd = _watchdog(stub, clock)

    live = wd.scan(store, now=at(9, 5))
    assert live.new_fires == []  # the level is still produced and live

    stub.set_levels([])  # aged out of the lookback / genuinely gone
    gone = wd.scan(store, now=at(9, 10))
    assert len(gone.new_fires) == 1
    fire = gone.new_fires[0]
    assert fire.kind == "pin"
    assert fire.evidence["status"] == "not_found"
    assert fire.fired_at == at(9, 10)
    assert store.get_subscription(pin.id).state is SubscriptionState.FIRED


# --------------------------------------------------------------------------- #
# Cooldown
# --------------------------------------------------------------------------- #

def test_repeating_watch_respects_the_cooldown(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    sub, _ = store.add_subscription(
        "watch", "level_forms", {"family": "fvg"}, one_shot=False, now=clock()
    )
    stub = FeedStub()
    wd = _watchdog(stub, clock)
    assert wd.sub_cooldown_s == SUB_COOLDOWN_S

    stub.set_levels([_fvg(at(9, 1))])
    clock.set(at(9, 5))
    first = wd.scan(store, now=clock())
    assert len(first.new_fires) == 1
    assert store.get_subscription(sub.id).last_fired_at == at(9, 5)

    # a fresh event two minutes later is inside the 300s cooldown -> suppressed.
    stub.set_levels([_fvg(at(9, 6))])
    clock.set(at(9, 7))
    cooled = wd.scan(store, now=clock())
    assert cooled.new_fires == []
    assert store.get_subscription(sub.id).last_fired_at == at(9, 5)

    # once the cooldown has fully elapsed, a fresh event fires again.
    stub.set_levels([_fvg(at(9, 8))])
    clock.set(at(9, 5) + timedelta(seconds=SUB_COOLDOWN_S))
    thawed = wd.scan(store, now=clock())
    assert len(thawed.new_fires) == 1
    assert store.get_subscription(sub.id).last_fired_at == at(9, 5) + timedelta(seconds=SUB_COOLDOWN_S)


# --------------------------------------------------------------------------- #
# Coalescing
# --------------------------------------------------------------------------- #

def test_fires_merge_into_one_turn_inside_the_coalesce_window(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    base = at(9, 0)

    def watch(offset_s):
        sub, _ = store.add_subscription(
            "watch", "time_reached", {"at": (base + timedelta(seconds=offset_s)).isoformat()},
            now=base,
        )
        return sub

    a, b, c = watch(10), watch(20), watch(120)
    wd = _watchdog(FeedStub(), clock)

    r1 = wd.scan(store, now=base + timedelta(seconds=10))
    assert [f.subscription_id for f in r1.new_fires] == [a.id]
    assert r1.turn is None  # the window just opened

    r2 = wd.scan(store, now=base + timedelta(seconds=20))
    assert [f.subscription_id for f in r2.new_fires] == [b.id]
    assert r2.turn is None  # only 10s into the 45s window
    assert r2.pending_fires == 2

    # the window has now elapsed: both fires are emitted as ONE turn.
    r3 = wd.scan(store, now=base + timedelta(seconds=65))
    assert r3.new_fires == []
    assert r3.turn is not None
    assert r3.turn.trigger == Trigger.FIRE.value
    assert r3.turn.cause == "fire"
    assert sorted(f.subscription_id for f in r3.turn.fires) == sorted([a.id, b.id])
    assert r3.pending_fires == 0

    # a later fire starts a fresh window and produces a second turn.
    r4 = wd.scan(store, now=base + timedelta(seconds=120))
    assert [f.subscription_id for f in r4.new_fires] == [c.id]
    assert r4.turn is None
    assert r4.pending_fires == 1

    r5 = wd.scan(store, now=base + timedelta(seconds=165))
    assert r5.turn is not None
    assert [f.subscription_id for f in r5.turn.fires] == [c.id]


def test_flush_emits_immediately(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    sub, _ = store.add_subscription(
        "watch", "time_reached", {"at": at(9, 10).isoformat()}, now=clock()
    )
    wd = _watchdog(FeedStub(), clock)

    wd.scan(store, now=at(9, 10))
    assert len(wd.pending()) == 1  # buffered, no turn yet

    turn = wd.flush(now=at(9, 11))
    assert turn is not None
    assert turn.trigger == Trigger.REQUEST.value
    assert turn.cause == "fire"
    assert [f.subscription_id for f in turn.fires] == [sub.id]
    assert wd.pending() == []

    # nothing pending any more.
    assert wd.flush(now=at(9, 12)) is None

    # the trigger is constrained to the store's vocabulary.
    with pytest.raises(ValueError):
        wd.flush(now=at(9, 12), trigger="expiry")


# --------------------------------------------------------------------------- #
# Expiry vs wake
# --------------------------------------------------------------------------- #

def test_non_wake_expiry_is_buffered_not_a_wake(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    sub, _ = store.add_subscription(
        "watch", "time_reached", {"at": at(23, 0).isoformat()}, ttl_hours=1, now=clock()
    )
    wd = _watchdog(FeedStub(), clock)

    result = wd.scan(store, now=at(10, 30))  # expires_at was 10:00
    assert [s.id for s in result.expired] == [sub.id]
    assert result.turn is None
    assert result.pending_expired == 1
    assert [s.id for s in wd.pending_expiries()] == [sub.id]
    assert store.get_subscription(sub.id).state is SubscriptionState.EXPIRED

    # it rides along with the next forced turn's briefing.
    turn = wd.flush(now=at(10, 31))
    assert turn is not None
    assert [s.id for s in turn.expired] == [sub.id]
    assert wd.pending_expiries() == []


def test_wake_on_expiry_arms_an_expiry_turn(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    sub, _ = store.add_subscription(
        "watch", "time_reached", {"at": at(23, 0).isoformat()},
        ttl_hours=1, wake_on_expiry=True, now=clock(),
    )
    wd = _watchdog(FeedStub(), clock)

    first = wd.scan(store, now=at(10, 0))  # the deadline itself is the event
    assert [s.id for s in first.expired] == [sub.id]
    assert first.turn is None  # the window opens now, it does not fire instantly

    second = wd.scan(store, now=at(10, 0) + timedelta(seconds=COALESCE_WINDOW_S))
    assert second.turn is not None
    assert second.turn.trigger == Trigger.FIRE.value  # a scan-emitted turn is a fire
    assert second.turn.cause == "expiry"
    assert [s.id for s in second.turn.expired] == [sub.id]
    assert second.pending_expired == 0


def test_fire_and_wake_expiry_merge_with_a_combined_trigger(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    store.add_subscription(
        "watch", "time_reached", {"at": at(23, 0).isoformat()}, ttl_hours=1,
        wake_on_expiry=True, now=clock(),
    )
    store.add_subscription("watch", "time_reached", {"at": at(10, 0).isoformat()}, now=clock())
    wd = _watchdog(FeedStub(), clock)

    wd.scan(store, now=at(10, 0))
    result = wd.scan(store, now=at(10, 0) + timedelta(seconds=COALESCE_WINDOW_S))
    assert result.turn is not None
    assert result.turn.trigger == Trigger.FIRE.value
    assert result.turn.cause == "fire+expiry"
    assert len(result.turn.fires) == 1
    assert len(result.turn.expired) == 1


# --------------------------------------------------------------------------- #
# Backfill
# --------------------------------------------------------------------------- #

def test_backfill_reports_missed_fires_once_as_retroactive(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    sub, _ = store.add_subscription(
        "watch", "level_forms", {"family": "fvg"}, one_shot=False, now=clock()
    )
    stub = FeedStub()
    wd = _watchdog(stub, clock)

    # downtime: a level forms while nobody is watching.
    formed = at(10, 0)
    stub.set_levels([_fvg(formed)])
    clock.set(at(11, 0))

    back = wd.backfill(store, now=clock())
    assert len(back.fires) == 1
    assert back.fires[0].retroactive is True
    assert back.fires[0].fired_at == formed
    assert wd.pending() == []  # backfill emits no turn and buffers no fire
    assert store.get_subscription(sub.id).last_evaluated_at == at(11, 0)

    # the next live scan must not re-report the same event.
    clock.set(at(11, 5))
    live = wd.scan(store, now=clock())
    assert live.new_fires == []
    assert live.turn is None


def test_backfill_reports_every_missed_fire(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    store.add_subscription("watch", "level_forms", {"family": "fvg"}, now=clock())
    store.add_subscription(
        "watch", "time_reached", {"at": at(9, 30).isoformat()}, now=clock()
    )
    stub = FeedStub().set_levels([_fvg(at(9, 45))])
    wd = _watchdog(stub, clock)

    clock.set(at(11, 0))
    back = wd.backfill(store, now=clock())
    assert len(back.fires) == 2
    assert all(f.retroactive for f in back.fires)


# --------------------------------------------------------------------------- #
# Cadence helpers
# --------------------------------------------------------------------------- #

def test_bar_seconds_matches_the_timeframe_grammar():
    assert bar_seconds("M1") == 60
    assert bar_seconds("M5") == 300
    assert bar_seconds("M15") == 900
    assert bar_seconds("M30") == 1800
    assert bar_seconds("H1") == 3600
    assert bar_seconds("H2") == 7200
    assert bar_seconds("H4") == 14400
    assert bar_seconds("D1") == 86400
    assert bar_seconds("W1") == 604800
    assert bar_seconds("MN1") == 2592000
    assert bar_seconds("MN") == 2592000
    assert bar_seconds("MN2") == 2 * 2592000
    with pytest.raises(ValueError):
        bar_seconds("bogus")


def test_bar_seconds_rejects_a_zero_count_symmetrically():
    """``M0`` and ``MN0`` are both meaningless and both rejected."""
    with pytest.raises(ValueError):
        bar_seconds("M0")
    with pytest.raises(ValueError):
        bar_seconds("MN0")


def test_referenced_and_due_timeframes(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path, timeframe="M15")
    store.add_subscription("watch", "level_forms", {"family": "fvg"}, now=clock())
    store.add_subscription(
        "watch", "level_forms", {"family": "crt", "timeframe": "H1"}, now=clock()
    )
    wd = _watchdog(FeedStub(), clock)

    assert wd.referenced_timeframes(store) == [("XAUUSDm", "H1"), ("XAUUSDm", "M15")]

    # a 15m boundary falls at 09:15 (the 1h boundary at 09:00 is behind `since`).
    assert wd.due_timeframes(store, at(9, 10), at(9, 15)) == [("XAUUSDm", "M15")]
    # a boundary exactly at `since` is excluded; the next is not due yet.
    assert wd.due_timeframes(store, at(9, 15), at(9, 16)) == []
    # a boundary exactly at `now` is included.
    assert wd.due_timeframes(store, at(9, 0), at(9, 15)) == [("XAUUSDm", "M15")]
    # the 1h boundary at 10:00 is due in the next hour.
    assert wd.due_timeframes(store, at(9, 59), at(10, 0)) == [("XAUUSDm", "H1"), ("XAUUSDm", "M15")]


def test_each_timeframe_is_fetched_once_per_scan(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    store.add_subscription("watch", "level_forms", {"family": "fvg"}, now=clock())
    store.add_subscription("watch", "level_forms", {"family": "ob"}, now=clock())
    stub = FeedStub()
    wd = _watchdog(stub, clock)

    wd.scan(store, now=at(9, 5))
    assert stub.snapshot_calls == [("XAUUSDm", "M15")]
    assert stub.bars_calls == [("XAUUSDm", "M15")]


def test_coalesce_window_boundary_is_inclusive(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    store.add_subscription(
        "watch", "time_reached", {"at": at(9, 10).isoformat()}, now=clock()
    )
    wd = _watchdog(FeedStub(), clock)

    wd.scan(store, now=at(9, 10))  # the fire opens the window
    almost = wd.scan(store, now=at(9, 10) + timedelta(seconds=COALESCE_WINDOW_S - 0.5))
    assert almost.turn is None  # a hair short of the window

    exact = wd.scan(store, now=at(9, 10) + timedelta(seconds=COALESCE_WINDOW_S))
    assert exact.turn is not None  # exactly at the window is due
    assert exact.turn.cause == "fire"


def test_due_timeframes_normalises_naive_datetimes(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    store.add_subscription("watch", "level_forms", {"family": "fvg"}, now=clock())
    wd = _watchdog(FeedStub(), clock)

    naive_since = at(9, 10).replace(tzinfo=None)
    naive_now = at(9, 15).replace(tzinfo=None)
    assert wd.due_timeframes(store, naive_since, naive_now) == [("XAUUSDm", "M15")]


def test_price_check_due_boundary(tmp_path):
    clock = FakeClock(at(9, 0))
    wd = _watchdog(FeedStub(), clock)
    assert wd.price_check_s == PRICE_CHECK_S

    last = at(9, 0)
    assert wd.price_check_due(None, last) is True  # never checked -> always due
    assert wd.price_check_due(last, last + timedelta(seconds=PRICE_CHECK_S - 0.5)) is False
    assert wd.price_check_due(last, last + timedelta(seconds=PRICE_CHECK_S)) is True

    custom = _watchdog(FeedStub(), clock, price_check_s=2.0)
    assert custom.price_check_due(last, last + timedelta(seconds=1)) is False
    assert custom.price_check_due(last, last + timedelta(seconds=2)) is True


def test_scan_and_backfill_on_an_empty_store(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    wd = _watchdog(FeedStub(), clock)

    scanned = wd.scan(store, now=at(9, 5))
    assert (scanned.new_fires, scanned.expired, scanned.turn) == ([], [], None)
    assert (scanned.pending_fires, scanned.pending_expired) == (0, 0)

    backed = wd.backfill(store, now=at(9, 5))
    assert backed.fires == []
    assert wd.flush(now=at(9, 6)) is None


# --------------------------------------------------------------------------- #
# Purity + serialisation
# --------------------------------------------------------------------------- #

def test_watchdog_without_a_clock_refuses_to_guess(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    wd = Watchdog(FeedStub().build())  # no clock injected
    with pytest.raises(RuntimeError):
        wd.scan(store)


def test_results_round_trip_through_json(tmp_path):
    clock = FakeClock(at(9, 0))
    store = _store(clock, tmp_path)
    store.add_subscription(
        "watch", "time_reached", {"at": at(9, 10).isoformat()}, ttl_hours=1,
        wake_on_expiry=True, now=clock(),
    )
    wd = _watchdog(FeedStub(), clock)

    wd.scan(store, now=at(9, 10))
    result = wd.scan(store, now=at(10, 0))  # past the coalesce window -> a turn

    again = ScanResult.from_dict(result.to_dict())
    assert again.evaluated_at == result.evaluated_at
    assert again.pending_fires == result.pending_fires

    turn = result.turn
    assert turn is not None
    turn_again = TurnRequest.from_dict(turn.to_dict())
    assert turn_again.trigger == turn.trigger
    assert turn_again.cause == turn.cause
    assert len(turn_again.fires) == len(turn.fires)
    assert turn_again.fires[0].condition == turn.fires[0].condition

    back = BackfillResult(evaluated_at=at(11, 0), fires=[])
    assert BackfillResult.from_dict(back.to_dict()) == back
