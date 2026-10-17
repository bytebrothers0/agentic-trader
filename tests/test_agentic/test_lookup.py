"""Tests for the numeric lookup tool (spec phase 3, "The numeric lookup tool").

Ground truth for anything the agent saw: resolve by tag / level_key / family /
near_price, and always answer the market header. Snapshots are built from plain
payload dicts via ``_fixtures`` — nothing here touches MT5.
"""
import pytest

from _fixtures import level as _level, snapshot as _snapshot, ts as _ts
from agentic.feed import FeedSnapshot, parse_level
from agentic.lookup import LookupRecord, LookupResult, level_lookup


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

def _scene():
    """A snapshot with a zone, a single line, and a duplicate-price pair."""
    return _snapshot(
        [
            _level("fvg", type="FVG (BULLISH)", price=110.0, time=1000, end_kind="active",
                   box_top=112.0, box_bottom=108.0, desc="FVG 108-112"),
            _level("crt", type="BULLISH (CLASSIC)", price=200.0, time=2000,
                   end_kind="active", range_high=205.0, range_low=195.0),
            _level("crt", type="BEARISH (CLASSIC)", price=100.0, time=3000, end_kind="active"),
        ],
        symbol="XAUUSDm", timeframe="M15", price=150.0, atr=10.0,
    )


def _by_price(snap, price):
    return next(l for l in snap.levels if l.price == price)


# --------------------------------------------------------------------------- #
# Header-only query
# --------------------------------------------------------------------------- #

def test_empty_query_answers_price_and_atr_with_no_matches():
    result = level_lookup(_scene())
    assert isinstance(result, LookupResult)
    assert result.current_price == 150.0
    assert result.atr == 10.0
    assert result.matches == []


def test_price_and_atr_overrides_win_over_the_snapshot():
    result = level_lookup(_scene(), {}, price=155.0, atr=5.0)
    assert result.current_price == 155.0
    assert result.atr == 5.0


def test_query_is_echoed_back():
    result = level_lookup(_scene(), {"family": "crt"})
    assert result.query == {"family": "crt"}


# --------------------------------------------------------------------------- #
# Resolution precedence
# --------------------------------------------------------------------------- #

def test_resolves_by_tag_and_reports_the_manifest_origin():
    snap = _scene()
    level = _by_price(snap, 110.0)
    tags = {"F1": {"level_key": level.level_key, "origin": "pinned"}}
    result = level_lookup(snap, {"tag": "F1"}, tags=tags)
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.tag == "F1"
    assert match.level_key == level.level_key
    assert match.origin == "pinned"
    assert match.price == 110.0


def test_resolves_by_level_key():
    snap = _scene()
    level = _by_price(snap, 200.0)
    match = level_lookup(snap, {"level_key": level.level_key}).matches[0]
    assert match.level_key == level.level_key
    assert match.price == 200.0
    assert match.tag == ""
    assert match.origin == "live"


def test_family_query_lists_the_whole_family():
    matches = level_lookup(_scene(), {"family": "crt"}).matches
    assert [m.price for m in matches] == [200.0, 100.0]


def test_family_query_is_filtered_by_timeframe():
    h1 = parse_level(_level("crt", price=100.0, time=1000), timeframe="H1")
    h4 = parse_level(_level("crt", price=200.0, time=2000), timeframe="H4")
    snap = FeedSnapshot(
        symbol="XAUUSDm", timeframe="M15", current_price=150.0, atr=10.0,
        levels=[h1, h4],
    )
    all_crt = level_lookup(snap, {"family": "crt"}).matches
    assert [m.price for m in all_crt] == [200.0, 100.0]
    only_h1 = level_lookup(snap, {"family": "crt", "timeframe": "H1"}).matches
    assert [m.timeframe for m in only_h1] == ["H1"]
    assert [m.price for m in only_h1] == [100.0]


def test_near_price_returns_nearest_first_within_radius():
    snap = _scene()
    near = level_lookup(snap, {"near_price": 106.0, "radius": 10.0}).matches
    # 110 is four away, 100 is six: nearest first.
    assert [m.price for m in near] == [110.0, 100.0]
    # A radius of zero matches only the exact price.
    exact = level_lookup(snap, {"near_price": 110.0, "radius": 0}).matches
    assert [m.price for m in exact] == [110.0]
    assert level_lookup(snap, {"near_price": 150.0, "radius": 5}).matches == []


def test_tag_takes_precedence_over_other_keys():
    snap = _scene()
    fvg = _by_price(snap, 110.0)
    crt = _by_price(snap, 200.0)
    tags = {"F1": {"level_key": fvg.level_key, "origin": "live"}}
    result = level_lookup(
        snap, {"tag": "F1", "level_key": crt.level_key, "family": "crt"}, tags=tags
    )
    assert [m.level_key for m in result.matches] == [fvg.level_key]


# --------------------------------------------------------------------------- #
# What a match answers
# --------------------------------------------------------------------------- #

def test_band_fields_come_from_the_zone():
    snap = _scene()
    fvg = _by_price(snap, 110.0)
    match = level_lookup(snap, {"level_key": fvg.level_key}).matches[0]
    assert match.price == 110.0
    assert match.price_low == 108.0
    assert match.price_high == 112.0
    assert match.family == "fvg"
    assert match.direction == "bullish"

    crt = _by_price(snap, 200.0)
    crt_match = level_lookup(snap, {"level_key": crt.level_key}).matches[0]
    assert (crt_match.price_low, crt_match.price_high) == (195.0, 205.0)


def test_distance_is_signed_in_points_and_atr():
    snap = _scene()
    above = level_lookup(snap, {"level_key": _by_price(snap, 200.0).level_key}).matches[0]
    assert above.distance_points == 50.0
    assert above.distance_atr == 5.0
    below = level_lookup(snap, {"level_key": _by_price(snap, 100.0).level_key}).matches[0]
    assert below.distance_points == -50.0
    assert below.distance_atr == -5.0


def test_distance_atr_is_none_without_an_atr():
    snap = _scene()
    key = _by_price(snap, 100.0).level_key
    match = level_lookup(snap, {"level_key": key}, atr=0.0).matches[0]
    assert match.distance_points == -50.0
    assert match.distance_atr is None


def test_created_at_is_the_formation_time():
    snap = _scene()
    fvg = _by_price(snap, 110.0)
    match = level_lookup(snap, {"level_key": fvg.level_key}).matches[0]
    assert match.created_at == fvg.formed_at


def test_note_is_the_human_description_not_the_origin():
    snap = _scene()
    fvg = _by_price(snap, 110.0)
    match = level_lookup(snap, {"level_key": fvg.level_key}).matches[0]
    assert match.note == "FVG 108-112"
    assert match.origin == "live"


def test_is_thesis_level_marks_the_stated_level():
    snap = _scene()
    key = _by_price(snap, 110.0).level_key
    result = level_lookup(snap, {"family": "fvg"}, thesis_level_keys=[key])
    assert [m.is_thesis_level for m in result.matches] == [True]
    assert level_lookup(snap, {"family": "fvg"}).matches[0].is_thesis_level is False


def test_status_is_carried_through():
    snap = _snapshot([
        _level("crt", price=100.0, time=1000, end_kind="swept"),
    ])
    match = level_lookup(snap, {"level_key": snap.levels[0].level_key}).matches[0]
    assert match.status == "swept"


# --------------------------------------------------------------------------- #
# Not-found and stale tags
# --------------------------------------------------------------------------- #

def test_unknown_level_key_is_not_found():
    match = level_lookup(_scene(), {"level_key": "nope"}).matches[0]
    assert match.status == "not_found"
    assert match.level_key == "nope"


def test_unknown_tag_is_not_found():
    match = level_lookup(_scene(), {"tag": "Z9"}, tags={}).matches[0]
    assert match.status == "not_found"
    assert match.tag == "Z9"


def test_stale_tag_falls_back_to_the_manifest_entry():
    # A level drawn under a tag that the fresh feed no longer produces: the
    # lookup answers from the manifest rather than pretending the tag is gone.
    tags = {
        "F9": {
            "level_key": "fvg:H2:bearish:130.00:2026-10-16T12:00:00+00:00",
            "family": "fvg", "timeframe": "H2", "direction": "bearish",
            "price": 130.0, "price_low": 128.0, "price_high": 132.0,
            "status": "live", "origin": "pinned", "note": "H2 FVG",
        }
    }
    match = level_lookup(_scene(), {"tag": "F9"}, tags=tags).matches[0]
    assert match.tag == "F9"
    assert match.origin == "pinned"
    assert match.price == 130.0
    assert match.price_low == 128.0
    assert match.distance_points == -20.0


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #

def test_family_ordering_is_deterministic():
    # Same price, different keys: the level_key is the tie-break, and a second
    # identical call returns the identical order.
    snap = _snapshot([
        _level("crt", type="BULLISH (CLASSIC)", price=150.0, time=1000, end_kind="active"),
        _level("crt", type="BEARISH (CLASSIC)", price=150.0, time=2000, end_kind="active"),
        _level("crt", type="BULLISH (CLASSIC)", price=200.0, time=3000, end_kind="active"),
    ])
    first = level_lookup(snap, {"family": "crt"}).matches
    second = level_lookup(snap, {"family": "crt"}).matches
    assert [m.level_key for m in first] == [m.level_key for m in second]
    assert [m.price for m in first] == [200.0, 150.0, 150.0]
    tied = [m.level_key for m in first if m.price == 150.0]
    assert tied == sorted(tied)


def test_result_round_trips_through_json():
    snap = _scene()
    result = level_lookup(snap, {"family": "crt"})
    again = LookupResult.from_dict(result.to_dict())
    assert isinstance(again, LookupResult)
    assert isinstance(again.matches[0], LookupRecord)
    assert again.current_price == 150.0
    assert [m.price for m in again.matches] == [200.0, 100.0]
