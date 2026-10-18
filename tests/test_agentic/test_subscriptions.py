"""Tests for the deterministic condition evaluator (spec phase 2, part A).

Every condition in the vocabulary is exercised with a positive fire, a negative
(no event in the window), and the edge-trigger property (the same event fires in
exactly one of two consecutive windows). Snapshots and bars are built from plain
payload dicts via ``parse_payload`` / ``parse_candles`` — nothing here touches MT5.
"""
from datetime import datetime, timedelta

import pytest

from _fixtures import (
    UTC,
    at as _at,
    day as _day,
    level as _level,
    series as _series,
    snapshot as _snapshot,
    sub as _sub,
    ts as _ts,
)
from agentic import subscriptions as subs
from agentic.conditions import ALL_CONDITIONS
from agentic.feed import (
    Bars,
    Feed,
    default_candles_provider,
    parse_candles,
    parse_level,
)
from agentic.subscriptions import FireResult, evaluate, event_time


# --------------------------------------------------------------------------- #
# Bars + event_time
# --------------------------------------------------------------------------- #

def test_bars_round_trip_and_index_at_or_before():
    bars = _series([
        (1000, 1.0, 2.0, 0.5, 1.5),
        (2000, 1.5, 3.0, 1.0, 2.5),
        (3000, 2.5, 4.0, 2.0, 3.5),
    ])
    assert len(bars) == 3
    assert bars.index_at_or_before(500) == -1
    assert bars.index_at_or_before(2000) == 1
    assert bars.index_at_or_before(2500) == 1
    assert bars.index_at_or_before(99999) == 2
    assert bars.index_at_or_before(datetime.fromtimestamp(2500, tz=UTC)) == 1

    again = Bars.from_dict(bars.to_dict())
    assert again == bars
    assert again.times == [1000, 2000, 3000]
    assert again.close == [1.5, 2.5, 3.5]


def test_parse_candles_sorts_and_drops_rows_without_a_time():
    bars = parse_candles({"candles": [
        {"time": 2000, "open": 1, "high": 1, "low": 1, "close": 1},
        {"open": 9, "high": 9, "low": 9, "close": 9},
        {"time": 1000, "open": 0, "high": 0, "low": 0, "close": 0},
    ]}, symbol="XAUUSDm", timeframe="M15")
    assert bars.symbol == "XAUUSDm"
    assert bars.timeframe == "M15"
    assert bars.times == [1000, 2000]


def test_event_time_prefers_changed_at_then_falls_back_to_formed_at():
    with_change = parse_level(
        _level("fvg", time=_ts(_at(10, 0)), end_time=_ts(_at(11, 0)), end_kind="active"),
        timeframe="M15",
    )
    assert event_time(with_change) == _at(11, 0)

    without_change = parse_level(
        _level("fvg", time=_ts(_at(10, 0)), end_kind="active"), timeframe="M15"
    )
    assert event_time(without_change) == _at(10, 0)

    nothing = parse_level({"category": "fvg", "price": 1.0}, timeframe="M15")
    assert event_time(nothing) is None


# --------------------------------------------------------------------------- #
# level_forms
# --------------------------------------------------------------------------- #

def test_level_forms_fires_once_per_new_level():
    sub = _sub("level_forms", {"family": "fvg"})
    snap = _snapshot([_level(
        "fvg", price=100.0, time=_ts(_at(10, 0)), end_kind="active",
        box_top=101.0, box_bottom=100.0,
    )])

    fired = evaluate(sub, snap, now=_at(10, 30), last_evaluated_at=_at(9, 0))
    assert fired is not None
    assert fired.fired_at == _at(10, 0)
    assert fired.evidence["family"] == "fvg"
    assert fired.condition == "level_forms"

    # edge-triggered: the same formation belongs to exactly one window.
    assert evaluate(sub, snap, now=_at(11, 0), last_evaluated_at=_at(10, 30)) is None
    # negative: nothing formed inside the window.
    assert evaluate(sub, snap, now=_at(9, 0), last_evaluated_at=_at(8, 0)) is None


def test_level_forms_applies_every_filter():
    new_level = _level(
        "crt", type="BULLISH (INSIDE_BAR)", price=100.0, time=_ts(_at(10, 0)),
        end_kind="active", variant="inside_bar", inside_bars=3,
        range_high=110.0, range_low=100.0,
    )
    snap = _snapshot([new_level], atr=5.0)
    window = {"now": _at(10, 30), "last_evaluated_at": _at(9, 0)}

    assert evaluate(_sub("level_forms", {"family": "crt"}), snap, **window) is not None
    # direction
    assert evaluate(_sub("level_forms", {"family": "crt", "direction": "bullish"}), snap, **window) is not None
    assert evaluate(_sub("level_forms", {"family": "crt", "direction": "bearish"}), snap, **window) is None
    # variant / min_inside_bars
    assert evaluate(_sub("level_forms", {"family": "crt", "variant": "inside_bar"}), snap, **window) is not None
    assert evaluate(_sub("level_forms", {"family": "crt", "variant": "classic"}), snap, **window) is None
    assert evaluate(_sub("level_forms", {"family": "crt", "min_inside_bars": 3}), snap, **window) is not None
    assert evaluate(_sub("level_forms", {"family": "crt", "min_inside_bars": 4}), snap, **window) is None
    # min_size_atr: band size 10 vs atr 5 -> 10 >= 7.5 passes, 10 >= 15 fails.
    assert evaluate(_sub("level_forms", {"family": "crt", "min_size_atr": 1.5}), snap, **window) is not None
    assert evaluate(_sub("level_forms", {"family": "crt", "min_size_atr": 3.0}), snap, **window) is None
    # ...and without an ATR there is no reference, so the filter cannot pass.
    assert evaluate(_sub("level_forms", {"family": "crt", "min_size_atr": 1.0}), _snapshot([new_level]), **window) is None
    # wrong family
    assert evaluate(_sub("level_forms", {"family": "ob"}), snap, **window) is None


# --------------------------------------------------------------------------- #
# level_touched
# --------------------------------------------------------------------------- #

def test_level_touched_fires_on_a_bar_in_the_window():
    snap = _snapshot([_level(
        "fvg", price=100.0, time=_ts(_at(9, 0)), end_kind="active",
        box_top=101.0, box_bottom=99.0,
    )])
    key = snap.levels[0].level_key
    series = _series([
        (_ts(_at(9, 0)), 98, 98.5, 97.5, 98.0),      # below the band [99, 101]
        (_ts(_at(9, 15)), 99, 101, 98, 100.5),      # touches the band [99, 101]
        (_ts(_at(9, 30)), 101.5, 103, 101.5, 102.5),  # back above the band
    ])
    sub = _sub("level_touched", {"level_key": key})

    fired = evaluate(sub, snap, series, now=_at(10, 0), last_evaluated_at=_at(9, 0))
    assert fired is not None
    assert fired.fired_at == _at(9, 15)
    assert fired.evidence["bar"]["time"] == _ts(_at(9, 15))
    assert fired.evidence["level"]["level_key"] == key

    # edge-triggered: the touch bar is behind the next window.
    assert evaluate(sub, snap, series, now=_at(10, 0), last_evaluated_at=_at(9, 15)) is None
    # negative: no bar at all in the window.
    assert evaluate(sub, snap, series, now=_at(9, 0), last_evaluated_at=_at(8, 0)) is None


def test_level_touched_uses_the_band_not_just_the_midpoint():
    snap = _snapshot([_level(
        "fvg", price=100.0, time=_ts(_at(9, 0)), end_kind="active",
        box_top=101.0, box_bottom=99.0,
    )])
    key = snap.levels[0].level_key

    # the wick enters the band [99, 101] but never reaches the midpoint (100).
    wick = _series([(_ts(_at(9, 30)), 101.0, 102.0, 100.5, 101.5)])
    fired = evaluate(_sub("level_touched", {"level_key": key}), snap, wick,
                     now=_at(10, 0), last_evaluated_at=_at(9, 0))
    assert fired is not None
    assert fired.fired_at == _at(9, 30)

    # a bar entirely above the band does not touch it.
    above = _series([(_ts(_at(9, 30)), 102.5, 103.0, 101.5, 102.5)])
    assert evaluate(_sub("level_touched", {"level_key": key}), snap, above,
                    now=_at(10, 0), last_evaluated_at=_at(9, 0)) is None


def test_level_touched_resolves_family_plus_nearest_price():
    snap = _snapshot([
        _level("fvg", price=100.0, time=_ts(_at(9, 0)), end_kind="active"),
        _level("fvg", price=120.0, time=_ts(_at(9, 0)), end_kind="active"),
    ])
    series = _series([(_ts(_at(9, 30)), 119, 121, 118, 120.5)])
    sub = _sub("level_touched", {"family": "fvg", "price": 120.0})

    fired = evaluate(sub, snap, series, now=_at(10, 0), last_evaluated_at=_at(9, 0))
    assert fired is not None
    assert fired.evidence["level"]["price"] == 120.0

    # nothing near 100 gets touched when reference price is 120.
    untouched = _sub("level_touched", {"family": "fvg", "price": 100.0})
    assert evaluate(untouched, snap, series, now=_at(10, 0), last_evaluated_at=_at(9, 0)) is None


# --------------------------------------------------------------------------- #
# level_swept / level_broken / level_filled
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("condition,end_kind", [
    ("level_swept", "swept"),
    ("level_broken", "invalidated"),
    ("level_filled", "distributed"),
])
def test_level_status_conditions(condition, end_kind):
    snap = _snapshot([_level(
        "fvg", price=100.0, time=_ts(_at(9, 0)), end_time=_ts(_at(10, 0)),
        end_kind=end_kind, box_top=101.0, box_bottom=99.0,
    )])
    key = snap.levels[0].level_key
    sub = _sub(condition, {"level_key": key})

    fired = evaluate(sub, snap, now=_at(11, 0), last_evaluated_at=_at(9, 0))
    assert fired is not None
    assert fired.fired_at == _at(10, 0)  # changed_at, not formed_at

    # edge-triggered / negative window.
    assert evaluate(sub, snap, now=_at(11, 0), last_evaluated_at=_at(10, 0)) is None
    assert evaluate(sub, snap, now=_at(9, 30), last_evaluated_at=_at(9, 0)) is None


def test_level_status_conditions_reject_the_wrong_status():
    live = _snapshot([_level(
        "fvg", price=100.0, time=_ts(_at(9, 0)), end_kind="active",
        box_top=101.0, box_bottom=99.0,
    )])
    key = live.levels[0].level_key
    for condition in ("level_swept", "level_broken", "level_filled"):
        assert evaluate(_sub(condition, {"level_key": key}), live, now=_at(11, 0), last_evaluated_at=_at(9, 0)) is None


def test_level_conditions_return_none_when_the_level_is_absent():
    empty = _snapshot([])
    for condition in ("level_swept", "level_broken", "level_filled"):
        sub = _sub(condition, {"level_key": "fvg:M15:bullish:100.00:x"})
        assert evaluate(sub, empty, now=_at(11, 0), last_evaluated_at=_at(9, 0)) is None


# --------------------------------------------------------------------------- #
# level_alive (a pin)
# --------------------------------------------------------------------------- #

def test_level_alive_fires_when_the_level_stops_being_produced():
    sub = _sub("level_alive", {"level_key": "fvg:M15:bullish:100.00:x"}, kind="pin")
    fired = evaluate(sub, _snapshot([]), now=_at(12, 0), last_evaluated_at=_at(11, 0))

    assert fired is not None
    assert fired.kind == "pin"
    assert fired.evidence["status"] == "not_found"
    assert fired.fired_at == _at(12, 0)  # no level event time: noticed at `now`


def test_level_alive_fires_on_a_transition_out_of_live():
    dying = _snapshot([_level(
        "fvg", price=100.0, time=_ts(_at(9, 0)), end_time=_ts(_at(10, 0)),
        end_kind="swept", box_top=101.0, box_bottom=99.0,
    )])
    sub = _sub("level_alive", {"level_key": dying.levels[0].level_key}, kind="pin")

    fired = evaluate(sub, dying, now=_at(11, 0), last_evaluated_at=_at(9, 0))
    assert fired is not None
    assert fired.fired_at == _at(10, 0)
    assert fired.evidence["status"] == "swept"

    # a live level is not a fire; and the same transition does not repeat.
    living = _snapshot([_level(
        "fvg", price=100.0, time=_ts(_at(9, 0)), end_kind="active",
        box_top=101.0, box_bottom=99.0,
    )])
    assert evaluate(sub, living, now=_at(11, 0), last_evaluated_at=_at(9, 0)) is None
    assert evaluate(sub, dying, now=_at(11, 0), last_evaluated_at=_at(10, 0)) is None


def test_level_alive_not_found_needs_a_nonempty_window():
    sub = _sub("level_alive", {"level_key": "fvg:M15:bullish:100.00:x"}, kind="pin")
    # a zero-width window cannot have observed anything disappear.
    assert evaluate(sub, _snapshot([]), now=_at(12, 0), last_evaluated_at=_at(12, 0)) is None
    assert evaluate(sub, _snapshot([]), now=_at(12, 1), last_evaluated_at=_at(12, 0)) is not None


# --------------------------------------------------------------------------- #
# bos_forms / choch_forms
# --------------------------------------------------------------------------- #

def test_bos_and_choch_forms_are_distinguished():
    snap = _snapshot([
        _level("bos", type="BOS (BULLISH)", price=100.0, time=_ts(_at(9, 0)),
               end_time=_ts(_at(10, 0)), end_kind="active"),
        _level("bos", type="CHOCH (BEARISH)", price=110.0, time=_ts(_at(9, 0)),
               end_time=_ts(_at(10, 30)), end_kind="active"),
    ])
    assert snap.levels[0].attrs["kind"] == "BOS"
    assert snap.levels[1].attrs["kind"] == "CHoCH"
    window = {"now": _at(11, 0), "last_evaluated_at": _at(9, 0)}

    bos = evaluate(_sub("bos_forms", {}), snap, **window)
    assert bos is not None
    assert bos.fired_at == _at(10, 0)

    choch = evaluate(_sub("choch_forms", {}), snap, **window)
    assert choch is not None
    assert choch.fired_at == _at(10, 30)

    # direction filter
    assert evaluate(_sub("bos_forms", {"direction": "bullish"}), snap, **window) is not None
    assert evaluate(_sub("bos_forms", {"direction": "bearish"}), snap, **window) is None
    # kind filter
    assert evaluate(_sub("choch_forms", {"direction": "bullish"}), snap, **window) is None
    # edge-triggered
    assert evaluate(_sub("bos_forms", {}), snap, now=_at(12, 0), last_evaluated_at=_at(11, 0)) is None


def test_bos_kind_is_case_insensitive_and_strips_the_i_prefix():
    def kind(type_text):
        level = parse_level({"category": "bos", "type": type_text, "price": 1.0}, timeframe="M15")
        return level.attrs["kind"], level.attrs["internal"]

    assert kind("BOS (BULLISH)") == ("BOS", False)
    assert kind("CHOCH (BEARISH)") == ("CHoCH", False)
    assert kind("I-BOS (BULLISH)") == ("BOS", True)
    assert kind("I-CHOCH (BEARISH)") == ("CHoCH", True)
    # case-insensitive on the leading token.
    assert kind("choch (bullish)") == ("CHoCH", False)


def test_bos_internal_filter_reads_the_i_prefix():
    snap = _snapshot([
        _level("bos", type="BOS (BULLISH)", price=100.0, time=_ts(_at(9, 0)),
               end_time=_ts(_at(10, 0)), end_kind="active"),
        _level("bos", type="I-BOS (BULLISH)", price=105.0, time=_ts(_at(9, 0)),
               end_time=_ts(_at(10, 30)), end_kind="active"),
        _level("bos", type="I-CHOCH (BEARISH)", price=110.0, time=_ts(_at(9, 0)),
               end_time=_ts(_at(10, 45)), end_kind="active"),
    ])
    assert snap.levels[0].attrs["internal"] is False
    assert snap.levels[1].attrs["internal"] is True
    assert snap.levels[2].attrs["kind"] == "CHoCH"
    assert snap.levels[2].attrs["internal"] is True
    window = {"now": _at(11, 0), "last_evaluated_at": _at(9, 0)}

    external = evaluate(_sub("bos_forms", {"internal": False}), snap, **window)
    assert external is not None and external.fired_at == _at(10, 0)
    internal = evaluate(_sub("bos_forms", {"internal": True}), snap, **window)
    assert internal is not None and internal.fired_at == _at(10, 30)
    assert evaluate(_sub("choch_forms", {"internal": True}), snap, **window).fired_at == _at(10, 45)
    assert evaluate(_sub("choch_forms", {"internal": False}), snap, **window) is None


# --------------------------------------------------------------------------- #
# idm_swept
# --------------------------------------------------------------------------- #

def test_idm_swept_filters_by_rule():
    snap = _snapshot([_level(
        "idm", price=100.0, time=_ts(_at(9, 0)), end_time=_ts(_at(10, 0)),
        end_kind="swept", rule="two_candle",
    )])
    window = {"now": _at(11, 0), "last_evaluated_at": _at(9, 0)}

    fired = evaluate(_sub("idm_swept", {"rule": "two_candle"}), snap, **window)
    assert fired is not None
    assert fired.fired_at == _at(10, 0)

    assert evaluate(_sub("idm_swept", {"rule": "bos"}), snap, **window) is None
    assert evaluate(_sub("idm_swept", {}), snap, **window) is not None

    # not swept -> no fire, and the same sweep does not repeat.
    live = _snapshot([_level("idm", price=100.0, time=_ts(_at(9, 0)), end_kind="active", rule="two_candle")])
    assert evaluate(_sub("idm_swept", {}), live, **window) is None
    assert evaluate(_sub("idm_swept", {}), snap, now=_at(11, 0), last_evaluated_at=_at(10, 0)) is None


# --------------------------------------------------------------------------- #
# price_crosses
# --------------------------------------------------------------------------- #

def test_price_crosses_fires_exactly_once_across_consecutive_windows():
    series = _series([
        (_ts(_at(9, 0)), 99, 100, 98, 99.5),
        (_ts(_at(9, 15)), 99.5, 101, 99, 100.5),   # strictly crosses up through 100
        (_ts(_at(9, 30)), 100.5, 102, 100, 101.5),
    ])
    sub = _sub("price_crosses", {"price": 100.0})

    first = evaluate(sub, _snapshot([]), series, now=_at(9, 20), last_evaluated_at=_at(9, 0))
    assert first is not None
    assert first.fired_at == _at(9, 15)
    assert first.evidence["price"] == 100.0
    assert first.evidence["bar"]["time"] == _ts(_at(9, 15))

    # the two windows share only the boundary: the crossing is not re-fired.
    second = evaluate(sub, _snapshot([]), series, now=_at(10, 0), last_evaluated_at=_at(9, 20))
    assert second is None


def test_price_crosses_ignores_a_close_exactly_at_the_level():
    sub = _sub("price_crosses", {"price": 100.0})

    # a bar closing exactly on the price is not itself a cross...
    landing = _series([
        (_ts(_at(9, 0)), 98, 100, 98, 100.0),
        (_ts(_at(9, 15)), 100, 101, 99, 100.5),
    ])
    assert evaluate(sub, _snapshot([]), landing, now=_at(10, 0), last_evaluated_at=_at(9, 0)) is None

    # ...and staying on one side never crosses at all.
    flat = _series([
        (_ts(_at(9, 0)), 90, 91, 89, 90.5),
        (_ts(_at(9, 15)), 90.5, 92, 90, 91.5),
    ])
    assert evaluate(sub, _snapshot([]), flat, now=_at(10, 0), last_evaluated_at=_at(9, 0)) is None


# --------------------------------------------------------------------------- #
# price_enters_zone
# --------------------------------------------------------------------------- #

def test_price_enters_zone_requires_a_fresh_entry():
    series = _series([
        (_ts(_at(9, 0)), 95, 96, 94, 95.5),        # outside [100, 102]
        (_ts(_at(9, 15)), 96, 101, 95, 100.5),     # enters -> fire
        (_ts(_at(9, 30)), 100, 103, 99, 102.0),    # still inside
    ])
    sub = _sub("price_enters_zone", {"low": 100.0, "high": 102.0})

    fired = evaluate(sub, _snapshot([]), series, now=_at(10, 0), last_evaluated_at=_at(9, 0))
    assert fired is not None
    assert fired.fired_at == _at(9, 15)
    assert fired.evidence["low"] == 100.0 and fired.evidence["high"] == 102.0

    # edge-triggered: already inside before the window, so no new entry.
    assert evaluate(sub, _snapshot([]), series, now=_at(10, 0), last_evaluated_at=_at(9, 15)) is None

    # negative: price never reaches the zone.
    far = _series([
        (_ts(_at(9, 0)), 90, 91, 89, 90.5),
        (_ts(_at(9, 15)), 90.5, 92, 90, 91.5),
    ])
    assert evaluate(sub, _snapshot([]), far, now=_at(10, 0), last_evaluated_at=_at(9, 0)) is None


# --------------------------------------------------------------------------- #
# range_expands
# --------------------------------------------------------------------------- #

def test_range_expands_against_atr():
    day = _at(0, 0)
    series = _series([
        (_ts(day), 100, 105, 100, 104),                       # range 5
        (_ts(day + timedelta(hours=1)), 104, 110, 103, 109),  # range 10
    ])
    snap = _snapshot([], atr=5.0)
    sub = _sub("range_expands", {"multiple": 1.5})  # threshold 7.5

    fired = evaluate(sub, snap, series, now=_at(2), last_evaluated_at=day)
    assert fired is not None
    assert fired.fired_at == day + timedelta(hours=1)
    assert fired.evidence["session_range"] == 10.0
    assert fired.evidence["reference"] == "atr"

    # a threshold past the session range never fires.
    assert evaluate(_sub("range_expands", {"multiple": 3.0}), snap, series, now=_at(2), last_evaluated_at=day) is None
    # no ATR -> no reference -> cannot fire.
    assert evaluate(sub, _snapshot([]), series, now=_at(2), last_evaluated_at=day) is None
    # edge-triggered: the expansion bar is behind the window.
    assert evaluate(sub, snap, series, now=_at(5), last_evaluated_at=_at(2)) is None


def test_range_expands_against_adr_uses_prior_days_only():
    d1, d2, d3 = _day(13), _day(14), _day(15)
    series = _series([
        (_ts(d1), 100, 108, 100, 107),   # prior day range 8
        (_ts(d2), 107, 113, 105, 112),   # prior day range 8
        (_ts(d3), 112, 118, 112, 117),   # current day range 6
    ])
    snap = _snapshot([])  # ATR is absent; ADR alone drives this
    sub = _sub("range_expands", {"multiple": 0.5, "reference": "ADR"})  # 0.5 * 8 = 4
    window = {"now": _day(15, 12), "last_evaluated_at": _day(14, 23)}

    fired = evaluate(sub, snap, series, **window)
    assert fired is not None
    assert fired.fired_at == d3
    assert fired.evidence["reference"] == "adr"
    assert fired.evidence["reference_value"] == 8.0

    assert evaluate(_sub("range_expands", {"multiple": 2.0, "reference": "ADR"}), snap, series, **window) is None
    # with only the current day present there is no prior ADR -> cannot fire.
    single_day = _series([(_ts(d3), 112, 118, 112, 117)])
    assert evaluate(_sub("range_expands", {"multiple": 0.1, "reference": "ADR"}), snap, single_day, **window) is None


# --------------------------------------------------------------------------- #
# session_opens / session_closes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("condition,session,hour,minute", [
    ("session_opens", "asia", 0, 0),
    ("session_closes", "asia", 8, 0),
    ("session_opens", "london", 7, 0),
    ("session_closes", "london", 16, 0),
    ("session_opens", "ny", 12, 0),
    ("session_closes", "ny", 21, 0),
])
def test_session_boundaries(condition, session, hour, minute):
    boundary = _at(hour, minute)
    sub = _sub(condition, {"session": session})

    fired = evaluate(sub, _snapshot([]), now=boundary + timedelta(minutes=1),
                     last_evaluated_at=boundary - timedelta(minutes=1))
    assert fired is not None
    assert fired.fired_at == boundary
    assert fired.evidence["session"] == session

    # edge-triggered: the boundary is behind the next window.
    assert evaluate(sub, _snapshot([]), now=boundary + timedelta(hours=1),
                    last_evaluated_at=boundary + timedelta(minutes=1)) is None
    # negative: a window that does not contain the boundary.
    assert evaluate(sub, _snapshot([]), now=boundary - timedelta(hours=2),
                    last_evaluated_at=boundary - timedelta(hours=3)) is None


# --------------------------------------------------------------------------- #
# time_reached
# --------------------------------------------------------------------------- #

def test_time_reached():
    at = _at(12, 0)
    sub = _sub("time_reached", {"at": at.isoformat()})

    fired = evaluate(sub, _snapshot([]), now=at + timedelta(minutes=1),
                     last_evaluated_at=at - timedelta(minutes=1))
    assert fired is not None
    assert fired.fired_at == at
    assert fired.evidence["at"] == at.isoformat()

    # negative: the timestamp is still in the future.
    assert evaluate(sub, _snapshot([]), now=at - timedelta(minutes=2),
                    last_evaluated_at=at - timedelta(hours=1)) is None
    # edge-triggered: the same instant does not fire twice.
    assert evaluate(sub, _snapshot([]), now=at + timedelta(hours=1),
                    last_evaluated_at=at + timedelta(minutes=1)) is None


def test_time_reached_accepts_a_zulu_suffix():
    sub = _sub("time_reached", {"at": "2026-10-15T12:00:00Z"})
    fired = evaluate(sub, _snapshot([]), now=_at(12, 0, 1), last_evaluated_at=_at(11, 59))
    assert fired is not None
    assert fired.fired_at == _at(12, 0)


# --------------------------------------------------------------------------- #
# Cross-cutting
# --------------------------------------------------------------------------- #

def test_every_condition_has_a_handler():
    assert set(subs._HANDLERS) == set(ALL_CONDITIONS)


def test_window_excludes_the_lower_bound_and_includes_now():
    sub = _sub("time_reached", {"at": _at(12, 0).isoformat()})
    snap = _snapshot([])

    # the lower bound is open: an event exactly at last_evaluated_at is excluded.
    assert evaluate(sub, snap, now=_at(12, 30), last_evaluated_at=_at(12, 0)) is None
    # the upper bound is closed: an event exactly at now is included.
    assert evaluate(sub, snap, now=_at(12, 0), last_evaluated_at=_at(11, 30)) is not None


def test_session_boundary_exactly_at_now_is_included():
    london = _sub("session_opens", {"session": "london"})
    snap = _snapshot([])

    fired = evaluate(london, snap, now=_at(7, 0), last_evaluated_at=_at(6, 0))
    assert fired is not None
    assert fired.fired_at == _at(7, 0)
    # ...and exactly at last_evaluated_at is excluded.
    assert evaluate(london, snap, now=_at(8, 0), last_evaluated_at=_at(7, 0)) is None


def test_price_and_range_conditions_return_none_without_bars():
    snap = _snapshot([])
    window = {"now": _at(10, 0), "last_evaluated_at": _at(9, 0)}

    assert evaluate(_sub("price_crosses", {"price": 100.0}), snap, None, **window) is None
    assert evaluate(_sub("price_enters_zone", {"low": 100.0, "high": 102.0}), snap, None, **window) is None
    assert evaluate(_sub("range_expands", {"multiple": 1.5}), snap, None, **window) is None


def test_open_lower_bound_accepts_any_event_up_to_now():
    sub = _sub("time_reached", {"at": _at(12, 0).isoformat()})
    assert evaluate(sub, _snapshot([]), now=_at(13, 0), last_evaluated_at=None) is not None
    assert evaluate(sub, _snapshot([]), now=_at(11, 0), last_evaluated_at=None) is None


def test_non_one_shot_projects_an_armed_state_after_firing():
    sub = _sub("time_reached", {"at": _at(12, 0).isoformat()}, one_shot=False)
    fired = evaluate(sub, _snapshot([]), now=_at(13), last_evaluated_at=_at(11))
    assert fired.state_before == "armed"
    assert fired.state_after == "armed"

    one_shot = _sub("time_reached", {"at": _at(12, 0).isoformat()})
    assert evaluate(one_shot, _snapshot([]), now=_at(13), last_evaluated_at=_at(11)).state_after == "fired"


def test_evaluate_never_mutates_and_the_result_round_trips():
    sub = _sub("level_forms", {"family": "fvg"})
    snap = _snapshot([_level("fvg", price=100.0, time=_ts(_at(10, 0)), end_kind="active")])
    sub_before, snap_before = sub.to_dict(), snap.to_dict()

    fired = evaluate(sub, snap, now=_at(11), last_evaluated_at=_at(9))
    assert sub.to_dict() == sub_before
    assert snap.to_dict() == snap_before

    again = FireResult.from_dict(fired.to_dict())
    assert again == fired
    assert again.fired_at == fired.fired_at
    assert again.retroactive is False


def test_unknown_condition_raises():
    with pytest.raises(ValueError):
        evaluate(_sub("not_a_condition", {}), _snapshot([]), now=_at(11), last_evaluated_at=_at(9))


# --------------------------------------------------------------------------- #
# Feed: the candles seam
# --------------------------------------------------------------------------- #

def test_feed_bars_uses_its_own_provider_and_leaves_snapshot_alone():
    calls = []

    def levels_provider(**kwargs):
        return {"symbol": kwargs["symbol"], "timeframe": kwargs["timeframe"], "levels": []}

    def candles_provider(**kwargs):
        calls.append(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "timeframe": kwargs["timeframe"],
            "candles": [{"time": 1000, "open": 1, "high": 2, "low": 0.5, "close": 1.5}],
        }

    feed = Feed(provider=levels_provider, candles_provider=candles_provider)
    bars = feed.bars("XAUUSDm", "M15", bars=120)
    assert calls == [{"symbol": "XAUUSDm", "timeframe": "M15", "bars": 120, "offset": 0}]
    assert len(bars) == 1
    assert feed.snapshot("XAUUSDm", "M15").levels == []


def test_default_candles_provider_is_lazy_until_called():
    # Building it must not import ``server``; calling the closure is what would.
    provider = default_candles_provider()
    assert callable(provider)
