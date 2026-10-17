"""Tests for the read-only indicator feed (spec phase 1 acceptance criteria).

The feed must normalise the ``/api/indicators`` payload into agent records with
stable keys, map the life-cycle to :class:`LevelStatus`, and never mutate the
source. A fake provider of plain dicts stands in for the live MT5 path, so these
tests run with nothing else present.
"""
import pytest

from agentic.feed import (
    FAMILY_QUERY,
    KNOWN_FAMILIES,
    Feed,
    FeedSnapshot,
    LevelRecord,
    _show_flags,
    family_of,
    parse_level,
    parse_payload,
    status_of,
)
from agentic.models import LevelStatus, validate_timeframe

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

CRT_LEVEL = {
    "category": "crt",
    "type": "BEARISH (INSIDE_BAR)",
    "variant": "inside_bar",
    "price": 4191.315,
    "state": "DISTRIBUTED",
    "time": 1792141200,
    "start_time": 1792142100,
    "end_time": 1792143000,
    "end_kind": "distributed",
    "range_high": 4191.315,
    "range_low": 4185.858,
    "target": 4185.858,
    "inside_bars": 3,
    "sweep_amount": 0.828,
    "desc": "CRT BEARISH: swept 4191.31, target 4185.86",
}


def _payload(levels, *, symbol="XAUUSDm", timeframe="M15", price=4190.0, atr=None):
    out = {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": price,
        "total_levels": len(levels),
        "levels": levels,
    }
    if atr is not None:
        out["atr"] = atr
    return out


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

def test_normalises_a_crt_level():
    lvl = parse_level(CRT_LEVEL, symbol="XAUUSDm", timeframe="M15")
    assert lvl.family == "crt"
    assert lvl.direction == "bearish"
    assert lvl.price == 4191.315
    assert lvl.status is LevelStatus.FILLED  # distributed == target reached
    assert lvl.target == 4185.858
    assert lvl.band() == (4185.858, 4191.315)
    assert lvl.variant == "inside_bar"
    assert lvl.inside_bars == 3
    assert lvl.timeframe == "M15"
    assert lvl.formed_at.isoformat() == "2026-10-16T09:00:00+00:00"
    assert lvl.origin.startswith("CRT BEARISH")


def test_level_key_is_stable_across_recomputation():
    a = parse_level(CRT_LEVEL, timeframe="M15")
    b = parse_level(dict(CRT_LEVEL), timeframe="M15")
    assert a.level_key == b.level_key
    assert a.level_key.startswith("crt:M15:bearish:4191.31:")


def test_family_aliases_are_rewritten():
    assert family_of({"category": "liq"}) == "liquidity"
    assert family_of({"category": "tl"}) == "trendline"
    assert family_of({"category": "crt"}) == "crt"


def test_direction_reads_the_type_field():
    assert parse_level({"category": "bos", "type": "CHoCH (BULLISH)", "price": 1.0}).direction == "bullish"
    assert parse_level({"category": "bos", "type": "BOS (BEARISH)", "price": 1.0}).direction == "bearish"
    assert parse_level({"category": "sr", "type": "SUPPORT", "price": 1.0}).direction == "neutral"


def test_status_prefers_end_kind_over_state():
    # end_kind is the authoritative life-cycle marker.
    assert status_of({"end_kind": "distributed", "state": "MANIPULATED"}) is LevelStatus.FILLED
    assert status_of({"end_kind": "invalidated", "state": "DISTRIBUTED"}) is LevelStatus.BROKEN
    assert status_of({"end_kind": "swept", "state": "FRESH"}) is LevelStatus.SWEPT
    assert status_of({"end_kind": "active", "state": "BROKEN"}) is LevelStatus.LIVE
    # state is the fallback when end_kind is absent.
    assert status_of({"state": "TAKEN"}) is LevelStatus.FILLED
    assert status_of({}) is LevelStatus.LIVE


def test_band_reads_every_zone_shape():
    assert parse_level({"category": "fvg", "price": 1.0, "box_top": 2.0, "box_bottom": 0.5}).band() == (0.5, 2.0)
    assert parse_level({"category": "qm", "price": 1.0, "box_high": 3.0, "box_low": 0.1}).band() == (0.1, 3.0)
    assert parse_level({"category": "sr", "price": 1.0}).band() is None


def test_parse_payload_reads_header_and_levels():
    snap = parse_payload(_payload([CRT_LEVEL, {"category": "liq", "type": "EQH (BUY-SIDE)", "price": 4191.0, "state": "FRESH"}], atr=12.5))
    assert snap.symbol == "XAUUSDm"
    assert snap.timeframe == "M15"
    assert snap.atr == 12.5
    assert snap.current_price == 4190.0
    assert len(snap.levels) == 2
    assert len(snap.family("crt")) == 1
    assert len(snap.family("liquidity")) == 1


def test_snapshot_round_trips_through_json():
    snap = parse_payload(_payload([CRT_LEVEL]))
    again = FeedSnapshot.from_dict(snap.to_dict())
    assert isinstance(again, FeedSnapshot)
    assert len(again.levels) == 1
    level = again.levels[0]
    assert isinstance(level, LevelRecord)
    assert level.status is LevelStatus.FILLED
    assert level.variant == "inside_bar"
    assert level.band() == (4185.858, 4191.315)


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #

def _snapshot():
    return parse_payload(_payload([
        {"category": "crt", "type": "BULLISH (CLASSIC)", "price": 100.0, "state": "MANIPULATED",
         "time": 1000, "end_kind": "active", "range_high": 110.0, "range_low": 95.0, "target": 110.0},
        {"category": "crt", "type": "BULLISH (CLASSIC)", "price": 200.0, "state": "DISTRIBUTED",
         "time": 2000, "end_kind": "distributed", "range_high": 210.0, "range_low": 195.0, "target": 210.0},
        {"category": "fvg", "type": "FVG (BULLISH)", "price": 105.0, "state": "FRESH",
         "time": 1500, "end_kind": "active", "box_top": 106.0, "box_bottom": 104.0},
    ]))


def test_snapshot_queries():
    snap = _snapshot()
    assert [l.price for l in snap.live("crt")] == [100.0]
    assert [l.price for l in snap.family("crt")] == [100.0, 200.0]
    assert snap.newest(snap.family("crt")).price == 200.0
    assert snap.by_key(snap.levels[0].level_key) is snap.levels[0]
    assert snap.by_key("nope") is None
    assert [l.price for l in snap.near_price(104.0, 2.0)] == [105.0]
    assert [l.price for l in snap.of_direction("bullish")] == [100.0, 200.0, 105.0]


# --------------------------------------------------------------------------- #
# Feed / provider seam
# --------------------------------------------------------------------------- #

def test_feed_calls_the_provider_with_the_wanted_arguments():
    calls = []

    def provider(**kwargs):
        calls.append(kwargs)
        return _payload([])

    feed = Feed(provider=provider)
    feed.snapshot("XAUUSDm", "H1", families=["crt", "bos"], bars=200)
    assert calls == [{"symbol": "XAUUSDm", "timeframe": "H1", "families": ["crt", "bos"], "bars": 200}]


def test_feed_snapshots_returns_one_per_timeframe():
    def provider(**kwargs):
        return _payload([CRT_LEVEL], timeframe=kwargs["timeframe"])

    feed = Feed(provider=provider)
    snaps = feed.snapshots("XAUUSDm", ["D1", "W1", "MN1"])
    assert set(snaps) == {"D1", "W1", "MN1"}
    assert snaps["W1"].timeframe == "W1"


def test_feed_rejects_a_non_mapping_provider_result():
    feed = Feed(provider=lambda **_: ["not", "a", "mapping"])
    with pytest.raises(TypeError):
        feed.snapshot("XAUUSDm", "H1")


def test_feed_validates_the_timeframe():
    feed = Feed(provider=lambda **_: _payload([]))
    with pytest.raises(ValueError):
        feed.snapshot("XAUUSDm", "bogus")


def test_show_flags_map_families_to_query_keys():
    flags = _show_flags(["crt", "bos"])
    assert flags["show_crt"] is True
    assert flags["show_bos"] is True
    assert flags["show_fvg"] is False
    assert all(v is True for v in _show_flags(None).values())


def test_family_vocabulary_is_complete():
    assert "crt" in KNOWN_FAMILIES
    assert set(KNOWN_FAMILIES) == set(FAMILY_QUERY)


# --------------------------------------------------------------------------- #
# Schema reach
# --------------------------------------------------------------------------- #

def test_monthly_timeframe_is_now_expressible():
    # The repo labels monthly MN1/MN; M1 is 1-minute, so the monthly form is
    # spelled out rather than folded into the M\d{1,2} branch.
    assert validate_timeframe("MN1") == "MN1"
    assert validate_timeframe("MN") == "MN"
    assert validate_timeframe("W1") == "W1"
    assert validate_timeframe("M1") == "M1"
    with pytest.raises(ValueError):
        validate_timeframe("X1")
