"""Tests for the CRT (Candle Range Theory) indicator.

CRT detects ranges that liquidate each other: an anchor candle defines the range
(CRH/CRL), a later candle sweeps one boundary and closes back inside, and the
projection is toward the opposite boundary.

Covered here:
  - the strict 3-candle (CLASSIC) setup, bullish and bearish
  - the INSIDE_BAR variant (accumulation nests inside bars inside the anchor)
  - dedupe: one setup per manipulation candle, widest range wins
  - a bar that sweeps both boundaries yields exactly one setup
  - life cycle: MANIPULATED / DISTRIBUTED / INVALIDATED
  - gates: min_range_atr, min_sweep_atr, max_inside_bars, directional anchor
  - per-side caps, ordering, validation
"""
import pandas as pd
import pytest

from indicators.crt_detector import (
    CRTDetector,
    CRTDirection,
    CRTLevel,
    CRTState,
    CRTVariant,
)


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(
        [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in rows],
        index=dates,
    )


def _detect(rows, **kwargs):
    return CRTDetector(_df(rows), **kwargs).detect_all()


# Bar shorthand: (open, high, low, close)
CLASSIC_BULL = [
    (100, 110, 95, 108),   # anchor: range 95..110
    (100, 104, 92, 103),   # manipulation: sweeps 95 -> 92, closes 103 back inside
    (103, 111, 100, 110),  # distribution: reaches CRH 110
]

CLASSIC_BEAR = [
    (110, 115, 105, 107),  # anchor: range 105..115
    (108, 118, 106, 107),  # manipulation: sweeps 115 -> 118, closes 107 back inside
    (107, 110, 104, 105),  # distribution: reaches CRL 105
]

INSIDE_BAR = [
    (100, 110, 95, 108),   # anchor: range 95..110
    (102, 106, 99, 104),   # inside bar (also inside the anchor)
    (103, 105, 100, 105),  # inside bar (inside both the anchor and the first)
    (100, 104, 92, 103),   # manipulation: sweeps 95 -> 92, closes 103
    (103, 111, 100, 110),  # distribution
]

BLOCK = [
    (100, 110, 95, 108),
    (100, 104, 92, 103),
    (103, 111, 100, 110),
]


# --------------------------------------------------------------------------- #
# the classic setup
# --------------------------------------------------------------------------- #

def test_classic_bullish_crt():
    levels = _detect(CLASSIC_BULL)
    assert len(levels) == 1
    lvl = levels[0]
    assert lvl.direction is CRTDirection.BULLISH
    assert lvl.variant is CRTVariant.CLASSIC
    assert (lvl.crh, lvl.crl) == (110.0, 95.0)
    assert lvl.swept_level == 95.0
    assert lvl.target_level == 110.0
    assert lvl.price == lvl.swept_level
    assert (lvl.anchor_index, lvl.manipulation_index) == (0, 1)
    assert lvl.inside_count == 0
    assert lvl.sweep_amount == pytest.approx(3.0)
    assert lvl.close_back_distance == pytest.approx(8.0)
    assert lvl.state is CRTState.DISTRIBUTED
    assert lvl.distribution_index == 2
    assert lvl.end_index == 2
    assert lvl.end_kind == "distributed"


def test_classic_bearish_crt():
    levels = _detect(CLASSIC_BEAR)
    assert len(levels) == 1
    lvl = levels[0]
    assert lvl.direction is CRTDirection.BEARISH
    assert lvl.variant is CRTVariant.CLASSIC
    assert (lvl.crh, lvl.crl) == (115.0, 105.0)
    assert lvl.swept_level == 115.0
    assert lvl.target_level == 105.0
    assert lvl.sweep_amount == pytest.approx(3.0)
    assert lvl.close_back_distance == pytest.approx(8.0)
    assert lvl.state is CRTState.DISTRIBUTED
    assert lvl.distribution_index == 2
    assert lvl.end_kind == "distributed"


def test_levels_property_mirrors_detect_all():
    det = CRTDetector(_df(CLASSIC_BULL))
    assert det.levels == []
    assert det.detect_all() == det.levels


# --------------------------------------------------------------------------- #
# the inside-bar variant and dedupe
# --------------------------------------------------------------------------- #

def test_inside_bar_variant_is_detected():
    levels = _detect(INSIDE_BAR)
    assert len(levels) == 1
    lvl = levels[0]
    assert lvl.variant is CRTVariant.INSIDE_BAR
    assert lvl.direction is CRTDirection.BULLISH
    assert lvl.anchor_index == 0
    assert lvl.manipulation_index == 3
    assert lvl.inside_bar_indices == [1, 2]
    assert lvl.inside_count == 2
    assert lvl.state is CRTState.DISTRIBUTED


def test_one_setup_per_manipulation_candle_widest_range_wins():
    """The anchor, both inside bars and the anchor's own interior all describe
    the same sweep. Only the outermost accumulation container is reported."""
    levels = _detect(INSIDE_BAR)
    manips = [lvl.manipulation_index for lvl in levels]
    assert len(manips) == len(set(manips)) == 1

    # The three competing anchors were 95..110 (15), 99..106 (7) and 100..105 (5).
    lvl = levels[0]
    assert lvl.range_size == pytest.approx(15.0)
    assert lvl.variant is CRTVariant.INSIDE_BAR


def test_max_inside_bars_creates_a_longer_accumulation_gate():
    """A run longer than the cap is a range, not a compression: that anchor is
    skipped and only the narrower competing anchor survives."""
    capped = _detect(INSIDE_BAR, max_inside_bars=1)
    assert [lvl.anchor_index for lvl in capped] == [1]
    assert capped[0].inside_count == 1

    uncapped = _detect(INSIDE_BAR)
    assert uncapped[0].anchor_index == 0
    assert uncapped[0].inside_count == 2


def test_one_setup_when_a_bar_sweeps_both_boundaries():
    """One bar is one manipulation. The deeper raid decides the side."""
    bearish = _detect([
        (100, 110, 95, 108),
        (100, 118, 88, 104),   # sweeps both: low by 7, high by 8
    ])
    assert len(bearish) == 1
    assert bearish[0].direction is CRTDirection.BEARISH
    assert bearish[0].swept_level == 110.0
    assert bearish[0].target_level == 95.0

    bullish = _detect([
        (100, 110, 95, 108),
        (100, 118, 86, 104),   # sweeps both: low by 9, high by 8
    ])
    assert len(bullish) == 1
    assert bullish[0].direction is CRTDirection.BULLISH
    assert bullish[0].swept_level == 95.0
    assert bullish[0].target_level == 110.0


# --------------------------------------------------------------------------- #
# life cycle
# --------------------------------------------------------------------------- #

def test_unresolved_setup_stays_manipulated():
    levels = _detect([
        (100, 110, 95, 108),
        (100, 104, 92, 103),
        (103, 106, 99, 104),   # neither the target nor a close through 95
    ])
    assert len(levels) == 1
    lvl = levels[0]
    assert lvl.state is CRTState.MANIPULATED
    assert lvl.end_index is None
    assert lvl.end_kind == "active"
    assert lvl.distribution_index is None
    assert lvl.invalidated_index is None


def test_body_close_through_the_swept_boundary_invalidates():
    levels = _detect([
        (100, 110, 95, 108),
        (100, 104, 92, 103),
        (103, 104, 88, 90),    # closes 90, back below the swept low 95
    ])
    assert len(levels) == 1
    lvl = levels[0]
    assert lvl.state is CRTState.INVALIDATED
    assert lvl.invalidated_index == 2
    assert lvl.end_index == 2
    assert lvl.end_kind == "invalidated"
    assert lvl.distribution_index is None


def test_invalidation_beats_distribution_on_the_same_bar():
    """A bar that both closes through the low and taps the high is reported as
    void, not as a win."""
    levels = _detect([
        (100, 110, 95, 108),
        (100, 104, 92, 103),
        (103, 112, 88, 90),    # closes 90 (< 95) and wicks 112 (>= 110)
    ])
    assert levels[0].state is CRTState.INVALIDATED
    assert levels[0].end_kind == "invalidated"


def test_distribution_is_not_credited_to_the_manipulation_candle():
    """A-M-D: the distribution comes after the manipulation."""
    levels = _detect([
        (95, 112, 92, 111),    # anchor 92..112
        (98, 111, 88, 111),    # manipulation: sweeps 92 -> 88, closes 111 (near CRH)
    ])
    bullish = [lvl for lvl in levels if lvl.direction is CRTDirection.BULLISH]
    assert len(bullish) == 1
    assert bullish[0].state is CRTState.MANIPULATED
    assert bullish[0].distribution_index is None


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #

def test_min_range_atr_gates_micro_ranges():
    assert len(_detect(CLASSIC_BULL)) == 1
    assert _detect(CLASSIC_BULL, min_range_atr=1.5) == []


def test_min_sweep_atr_gates_micro_sweeps():
    assert len(_detect(CLASSIC_BULL, min_sweep_atr=0.1)) == 1
    assert _detect(CLASSIC_BULL, min_sweep_atr=0.5) == []


def test_sweep_min_is_an_absolute_penetration_floor():
    assert len(_detect(CLASSIC_BULL, sweep_min=2.0)) == 1
    assert _detect(CLASSIC_BULL, sweep_min=4.0) == []


def test_min_close_back_atr_gates_body_edge_closes():
    assert len(_detect(CLASSIC_BULL, min_close_back_atr=0.1)) == 1
    assert _detect(CLASSIC_BULL, min_close_back_atr=1.0) == []


def test_directional_anchor_filter_is_opt_in():
    """The bullish anchor in this fixture hosts a bullish CRT. Off by default;
    on, that setup is refused."""
    assert len(_detect(CLASSIC_BULL)) == 1
    assert _detect(CLASSIC_BULL, require_directional_anchor=True) == []


# --------------------------------------------------------------------------- #
# caps and ordering
# --------------------------------------------------------------------------- #

def test_resolved_history_is_capped_per_side():
    df = _df(BLOCK * 3)
    many = CRTDetector(df).detect_all()
    assert len(many) > 1
    assert all(lvl.direction is CRTDirection.BULLISH for lvl in many)
    assert all(lvl.state is CRTState.DISTRIBUTED for lvl in many)

    kept = CRTDetector(df, max_per_side=1).detect_all()
    assert len(kept) == 1
    assert kept[0].manipulation_index == max(lvl.manipulation_index for lvl in many)


def test_live_setups_survive_the_resolved_cap():
    df = _df(BLOCK * 2 + [(100, 110, 95, 108), (100, 104, 92, 103)])
    levels = CRTDetector(df, max_per_side=0).detect_all()
    assert levels
    assert all(lvl.state is CRTState.MANIPULATED for lvl in levels)
    assert all(lvl.end_kind == "active" for lvl in levels)


def test_levels_are_ordered_by_manipulation():
    levels = _detect(BLOCK * 3)
    manips = [lvl.manipulation_index for lvl in levels]
    assert manips == sorted(manips)
    assert len(manips) == len(set(manips))


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #

def test_validation_rejects_bad_input():
    with pytest.raises(ValueError):
        CRTDetector(pd.DataFrame({"open": [1], "high": [1], "low": [1]}))

    with pytest.raises(ValueError):
        CRTDetector(pd.DataFrame(
            [{"open": 1, "high": 1, "low": 1, "close": 1}],
            index=pd.Index([1]),
        ))

    empty = pd.DataFrame(
        [], columns=["open", "high", "low", "close"],
        index=pd.DatetimeIndex([]),
    )
    with pytest.raises(ValueError):
        CRTDetector(empty)
