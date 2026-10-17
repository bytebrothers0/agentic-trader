"""Tests for the top-down CRT playbook (spec phase 1 + the CRT wiring).

Bias selection across D1/W1/MN1, LTF confirmation priority, and the plan maths.
A fake :class:`Feed` built from plain payload dicts stands in for the live MT5
path, so the playbook is exercised with nothing else present.
"""
import pytest

from agentic.crt_strategy import (
    HTF_BIAS_TIMEFRAMES,
    LTF_EXECUTION_TIMEFRAMES,
    OPTIONAL_FAMILIES,
    REQUIRED_FAMILIES,
    Confirmation,
    HtfBias,
    _confidence,
    analyze,
    build_plan,
    derive_htf_bias,
    find_confirmation,
)
from agentic.feed import Feed, parse_payload
from agentic.models import LevelStatus

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _crt(direction, price, high, low, *, state="MANIPULATED", end_kind="active",
         variant="classic", inside=0, time=1000):
    return {
        "category": "crt",
        "type": f"{direction.upper()} ({variant.upper()})",
        "variant": variant,
        "price": price,
        "state": state,
        "time": time,
        "start_time": time + 60,
        "end_time": None if end_kind == "active" else time + 120,
        "end_kind": end_kind,
        "range_high": high,
        "range_low": low,
        "target": high if direction == "bullish" else low,
        "inside_bars": inside,
        "sweep_amount": 1.0,
        "desc": "crt",
    }


def _bos(direction, price, time=1000):
    return {"category": "bos", "type": f"BOS ({direction.upper()})", "price": price,
            "state": "FRESH", "time": time, "end_time": time + 50, "end_kind": "active",
            "desc": "bos"}


def _fvg(direction, price, low, high, *, state="FRESH", time=1000):
    end_kind = "active" if state == "FRESH" else "broken"
    return {"category": "fvg", "type": f"FVG ({direction.upper()})", "price": price,
            "state": state, "time": time, "end_kind": end_kind,
            "box_bottom": low, "box_top": high, "desc": "fvg"}


def _snap(timeframe, levels, *, price=100.0, atr=None):
    payload = {"symbol": "XAUUSDm", "timeframe": timeframe, "current_price": price,
               "total_levels": len(levels), "levels": levels}
    if atr is not None:
        payload["atr"] = atr
    return parse_payload(payload)


# --------------------------------------------------------------------------- #
# Bias
# --------------------------------------------------------------------------- #

def test_bias_prefers_the_highest_live_timeframe():
    snaps = {
        "MN1": _snap("MN1", [_crt("bearish", 100.0, 110.0, 90.0)]),
        "W1": _snap("W1", [_crt("bullish", 80.0, 120.0, 70.0)]),
        "D1": _snap("D1", [_crt("bullish", 60.0, 130.0, 50.0)]),
    }
    bias = derive_htf_bias(snaps)
    assert bias.timeframe == "MN1"
    assert bias.direction == "bearish"
    assert bias.target == 90.0
    assert bias.is_live


def test_bias_skips_a_resolved_htf_for_a_live_lower_one():
    snaps = {
        "MN1": _snap("MN1", [_crt("bearish", 100.0, 110.0, 90.0, state="DISTRIBUTED", end_kind="distributed")]),
        "W1": _snap("W1", [_crt("bullish", 80.0, 120.0, 70.0)]),
    }
    bias = derive_htf_bias(snaps)
    assert bias.timeframe == "W1"
    assert bias.direction == "bullish"


def test_bias_falls_back_to_newest_when_none_are_live():
    snaps = {
        "D1": _snap("D1", [
            _crt("bullish", 50.0, 100.0, 40.0, state="DISTRIBUTED", end_kind="distributed", time=1000),
            _crt("bullish", 60.0, 100.0, 40.0, state="INVALIDATED", end_kind="invalidated", time=2000),
        ]),
    }
    bias = derive_htf_bias(snaps)
    assert bias is not None
    assert bias.status is LevelStatus.BROKEN
    assert not bias.is_live


def test_bias_is_none_without_a_crt():
    snaps = {"MN1": _snap("MN1", [_bos("bullish", 1.0)]), "D1": _snap("D1", [])}
    assert derive_htf_bias(snaps) is None


def test_bias_equilibrium_is_the_range_midpoint():
    snaps = {"D1": _snap("D1", [_crt("bullish", 90.0, 110.0, 90.0)])}
    assert derive_htf_bias(snaps).equilibrium == 100.0


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #

def test_confirmation_prefers_a_structure_shift_over_a_zone():
    ltf = _snap("H1", [_fvg("bullish", 101.0, 100.0, 102.0), _bos("bullish", 99.0)])
    bias = HtfBias(direction="bullish", timeframe="D1", level_key="k", target=110.0)
    conf = find_confirmation(ltf, bias)
    assert conf.kind == "bos"
    assert conf.direction == "bullish"


def test_confirmation_direction_must_match_the_bias():
    ltf = _snap("H1", [_bos("bearish", 99.0), _fvg("bearish", 101.0, 100.0, 102.0)])
    bias = HtfBias(direction="bullish", timeframe="D1", level_key="k", target=110.0)
    assert find_confirmation(ltf, bias) is None


def test_confirmation_falls_back_to_a_live_zone():
    ltf = _snap("H1", [_fvg("bullish", 101.0, 100.0, 102.0)])
    bias = HtfBias(direction="bullish", timeframe="D1", level_key="k", target=110.0)
    conf = find_confirmation(ltf, bias)
    assert conf.kind == "fvg"
    assert conf.band_low == 100.0 and conf.band_high == 102.0


def test_confirmation_ignores_a_dead_zone():
    ltf = _snap("H1", [_fvg("bullish", 101.0, 100.0, 102.0, state="BROKEN")])
    bias = HtfBias(direction="bullish", timeframe="D1", level_key="k", target=110.0)
    assert find_confirmation(ltf, bias) is None


def test_confirmation_rejects_a_neutral_bias():
    ltf = _snap("H1", [_bos("bullish", 99.0)])
    assert find_confirmation(ltf, HtfBias(direction="neutral")) is None


# --------------------------------------------------------------------------- #
# Plan maths
# --------------------------------------------------------------------------- #

def _bias(direction="bullish", key="crt:D1:bullish:90.00", target=110.0, eq=100.0):
    return HtfBias(timeframe="D1", direction=direction, level_key=key,
                   range_high=110.0, range_low=90.0, target=target,
                   equilibrium=eq, status=LevelStatus.LIVE)


def _conf(direction="bullish", kind="fvg", price=102.0, low=101.0, high=103.0, key="fvg:H1:bullish:102.00"):
    return Confirmation(timeframe="H1", kind=kind, direction=direction, level_key=key,
                        price=price, band_low=low, band_high=high, status=LevelStatus.LIVE)


def test_plan_long_maths():
    # No LTF entry zone, so the confirmation band is the risk unit; the stop is
    # padded by 5% of the HTF range (20 points) because ATR is absent.
    plan = build_plan(_bias(), _conf(), _snap("H1", []))
    assert plan.direction == "bullish"
    assert plan.entry == 102.0
    assert plan.stop == pytest.approx(100.0)      # band low 101 minus 5% of the 20-point range
    assert plan.target == 110.0
    assert plan.partial == 100.0
    assert plan.risk == pytest.approx(2.0)
    assert plan.reward == pytest.approx(8.0)
    assert plan.rr == pytest.approx(4.0)
    assert "crt:D1:bullish:90.00" in plan.invalidation
    assert plan.provenance == ["crt:D1:bullish:90.00", "fvg:H1:bullish:102.00"]


def test_plan_short_maths():
    plan = build_plan(
        _bias("bearish", key="crt:D1:bearish:110.00", target=90.0),
        _conf("bearish", price=98.0, low=97.0, high=99.0, key="fvg:H1:bearish:98.00"),
        _snap("H1", []),
    )
    assert plan.direction == "bearish"
    assert plan.stop == pytest.approx(100.0)      # band high 99 plus 5% of the 20-point range
    assert plan.target == 90.0
    assert plan.rr == pytest.approx(4.0)


def test_plan_pads_the_stop_by_atr_when_available():
    plan = build_plan(_bias(), _conf(), _snap("H1", []), atr=10.0)
    assert plan.stop == pytest.approx(98.5)       # band low 101 minus 0.25 * ATR(10)


def test_plan_is_well_defined_without_a_band():
    # A BOS confirmation carries no band; the stop is still padded (to 101), so
    # the plan is never degenerate and rr is always meaningful.
    plan = build_plan(_bias(), _conf(kind="bos", price=102.0, low=None, high=None), _snap("H1", []))
    assert plan.risk == pytest.approx(1.0)
    assert plan.rr == pytest.approx(8.0)


def test_plan_prefers_the_aligned_entry_zone_for_risk():
    # A live bullish FVG on the LTF is the location: entry at the zone, stop
    # below its low, and the zone is cited in the provenance.
    ltf = _snap("H1", [_fvg("bullish", 103.0, 102.0, 104.0)])
    plan = build_plan(_bias(), _conf(kind="bos", price=99.0, low=None, high=None), ltf)
    assert plan.entry == 103.0
    assert plan.stop == pytest.approx(101.0)      # zone low 102 minus 5% of the range
    assert plan.provenance[-1].startswith("fvg:H1:bullish:103.00")
    assert "zone" in plan.reasoning


def test_plan_targets_the_nearest_htf_boundary():
    # bias target is 110, but a nearer HTF boundary sits at 106: that is the TP,
    # and the bias CRT's own far boundary is still recorded as htf_target.
    plan = build_plan(_bias(), _conf(), _snap("H1", []), target_candidates=[106.0, 110.0, 130.0])
    assert plan.target == 106.0
    assert plan.htf_target == 110.0


def test_plan_target_ignores_candidates_behind_entry():
    plan = build_plan(
        _bias("bearish", key="crt:D1:bearish:110.00", target=90.0),
        _conf("bearish", price=98.0, low=97.0, high=99.0),
        _snap("H1", []),
        target_candidates=[95.0, 120.0],  # 120 is above entry -> not a short target
    )
    assert plan.target == 95.0


def test_plan_falls_back_to_the_bias_target_when_no_ladder_rung():
    plan = build_plan(_bias(), _conf(), _snap("H1", []), target_candidates=[50.0])
    assert plan.target == 110.0


def test_confidence_rewards_inside_bars_and_a_live_bias():
    live_rich = _bias()
    live_rich.inside_bars = 2
    live_rich.variant = "inside_bar"
    resolved = _bias()
    resolved.status = LevelStatus.FILLED
    conf = _conf()
    assert _confidence(live_rich, conf) > _confidence(resolved, conf)
    assert 0.10 <= _confidence(live_rich, conf) <= 0.90


def test_plan_round_trips_through_serde():
    from agentic.crt_strategy import CrtPlan
    plan = build_plan(_bias(), _conf(), _snap("H1", []))
    assert CrtPlan.from_dict(plan.to_dict()).target == plan.target


# --------------------------------------------------------------------------- #
# Whole read
# --------------------------------------------------------------------------- #

def _feed(by_timeframe, *, atr=None):
    def provider(*, symbol, timeframe, families, bars, **_):
        payload = {"symbol": symbol, "timeframe": timeframe, "current_price": 100.0,
                   "levels": by_timeframe.get(timeframe, [])}
        if atr is not None:
            payload["atr"] = atr
        return payload

    return Feed(provider=provider)


def test_analyze_produces_a_plan_end_to_end():
    feed = _feed({
        "MN1": [],
        "W1": [],
        "D1": [_crt("bullish", 90.0, 110.0, 85.0, variant="inside_bar", inside=2)],
        "H1": [_fvg("bullish", 92.0, 91.0, 93.0)],
    }, atr=4.0)
    result = analyze(feed, "XAUUSDm", ltf_timeframe="H1")
    assert result.reason == "plan ready"
    assert result.bias.timeframe == "D1"
    assert result.plan.direction == "bullish"
    assert result.plan.target == 110.0
    assert result.plan.ltf_timeframe == "H1"


def test_analyze_reports_when_there_is_no_htf_bias():
    feed = _feed({"MN1": [], "W1": [], "D1": [], "H1": [_fvg("bullish", 92.0, 91.0, 93.0)]})
    result = analyze(feed, "XAUUSDm", ltf_timeframe="H1")
    assert result.plan is None
    assert "no CRT" in result.reason


def test_analyze_reports_when_the_ltf_has_not_confirmed():
    feed = _feed({
        "MN1": [], "W1": [],
        "D1": [_crt("bullish", 90.0, 110.0, 85.0)],
        "H1": [_bos("bearish", 99.0)],  # wrong direction
    })
    result = analyze(feed, "XAUUSDm", ltf_timeframe="H1")
    assert result.plan is None
    assert result.bias.direction == "bullish"
    assert "awaiting LTF confirmation" in result.reason


# --------------------------------------------------------------------------- #
# The strategy's ladder and family set
# --------------------------------------------------------------------------- #

def test_the_ladder_and_family_set():
    assert HTF_BIAS_TIMEFRAMES == ("MN1", "W1", "D1")
    assert LTF_EXECUTION_TIMEFRAMES[0] == "H4"
    assert "crt" in REQUIRED_FAMILIES
    assert set(REQUIRED_FAMILIES).isdisjoint(OPTIONAL_FAMILIES)
