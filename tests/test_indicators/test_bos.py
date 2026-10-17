"""Tests for the BOS/CHoCH indicator (Mxwll-style port).

Logic: Donchian-zigzag swings (bar L ago exceeding all L bars after it) +
CLOSE through the last swing. Wick-only crosses never fire; one shot per
level; breaks against trend state are CHoCH. The range high/low since the
range last expanded is armed as well, so a shallow pullback pivot cannot
demote the boundary a continuation BOS still has to clear.
"""
import pandas as pd

from indicators.bos_detector import BOSDetector, BOSDirection, BOSLevel
from indicators.idm_detector import _structure_direction


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _bos(df, L=2):
    return [x for x in BOSDetector(df, swing_length=L, show_internal=False).detect_all() if not x.is_choch]


def _choch(df, L=2):
    return [x for x in BOSDetector(df, swing_length=L, show_internal=False).detect_all() if x.is_choch]


UPTREND = [
    {"open": 100, "high": 102, "low": 99, "close": 101},
    {"open": 101, "high": 105, "low": 100, "close": 104},
    {"open": 104, "high": 103, "low": 101, "close": 102},
    {"open": 102, "high": 104, "low": 101, "close": 103},
    {"open": 103, "high": 106, "low": 102, "close": 105.5},
]


def test_bullish_bos_on_close():
    lv = _bos(_df(UPTREND))
    assert len(lv) == 1
    assert lv[0].direction == BOSDirection.BULLISH
    assert lv[0].price == 105
    assert lv[0].extreme_index == 1
    assert lv[0].break_index == 4


def test_bearish_bos_first_structure():
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 101},
        {"open": 101, "high": 105, "low": 100, "close": 104},
        {"open": 104, "high": 106, "low": 103, "close": 105},
        {"open": 105, "high": 105.5, "low": 102, "close": 102.5},
        {"open": 102.5, "high": 103, "low": 99, "close": 99.5},
        {"open": 99.5, "high": 100, "low": 97, "close": 97.5},
    ])
    lv = _bos(df)
    assert len(lv) == 1
    assert lv[0].direction == BOSDirection.BEARISH
    assert lv[0].price == 99 and lv[0].break_index == 5


def test_wick_cross_without_close_is_nothing():
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 101},
        {"open": 101, "high": 105, "low": 100, "close": 104},
        {"open": 104, "high": 103, "low": 101, "close": 102},
        {"open": 102, "high": 107, "low": 101, "close": 103.5},
        {"open": 103.5, "high": 104, "low": 102, "close": 103},
    ])
    assert BOSDetector(df, swing_length=2).detect_all() == []


def test_one_shot_per_level():
    df = _df(UPTREND + [
        {"open": 105.5, "high": 107, "low": 105, "close": 106.5},
    ])
    lv = _bos(df)
    assert len(lv) == 1 and lv[0].break_index == 4


def test_choch_against_trend():
    df = _df(UPTREND + [
        {"open": 105.5, "high": 106, "low": 103, "close": 104},
        {"open": 104, "high": 104.5, "low": 100, "close": 101},
        {"open": 101, "high": 102, "low": 98, "close": 98.5},
    ])
    bos = _bos(df)
    choch = _choch(df)
    assert len(bos) == 1 and bos[0].price == 105
    assert len(choch) == 1
    assert choch[0].direction == BOSDirection.BEARISH
    assert choch[0].price == 101 and choch[0].break_index == 7


def test_triple_tapped_equal_level_breaks():
    # 105 wicked three times, then a body close above: still a BOS.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 103, "high": 105, "low": 102, "close": 104},
        {"open": 104, "high": 105, "low": 103, "close": 103.5},
        {"open": 103.5, "high": 104, "low": 102, "close": 103},
        {"open": 103, "high": 107, "low": 102, "close": 106},
    ])
    lv = _bos(df)
    assert len(lv) == 1
    assert lv[0].price == 105 and lv[0].break_index == 4


def test_near_taps_within_tolerance_break():
    # Taps at 105.2 / 105.3 / 104 (cents apart), then a close above 105.2.
    df = _df([
        {"open": 100, "high": 104, "low": 99, "close": 103},
        {"open": 103, "high": 105.2, "low": 102, "close": 104},
        {"open": 104, "high": 105.3, "low": 103, "close": 103.5},
        {"open": 103.5, "high": 104, "low": 102, "close": 103},
        {"open": 103, "high": 106, "low": 102, "close": 105.5},
    ])
    lv = _bos(df)
    assert len(lv) == 1
    assert lv[0].price == 105.2 and lv[0].break_index == 4


def test_internal_layer_fires_where_external_does_not():
    # Tiny swing: external length never confirms, internal length 2 does.
    df = _df([
        {"open": 100, "high": 101, "low": 99.5, "close": 100.5},
        {"open": 100.5, "high": 102, "low": 100, "close": 101.5},
        {"open": 101.5, "high": 101.8, "low": 100.5, "close": 101},
        {"open": 101, "high": 101.6, "low": 100.4, "close": 101.2},
        {"open": 101.2, "high": 103, "low": 101, "close": 102.5},
    ])
    ext = BOSDetector(df, swing_length=10, show_internal=False).detect_all()
    assert ext == []
    both = BOSDetector(df, swing_length=10, internal_length=2).detect_all()
    ibos = [x for x in both if x.internal and not x.is_choch]
    assert len(ibos) == 1
    assert ibos[0].kind == "I-BOS"
    assert ibos[0].direction == BOSDirection.BULLISH


def test_internal_hidden_by_flag():
    df = _df([
        {"open": 100, "high": 101, "low": 99.5, "close": 100.5},
        {"open": 100.5, "high": 102, "low": 100, "close": 101.5},
        {"open": 101.5, "high": 101.8, "low": 100.5, "close": 101},
        {"open": 101, "high": 101.6, "low": 100.4, "close": 101.2},
        {"open": 101.2, "high": 103, "low": 101, "close": 102.5},
    ])
    out = BOSDetector(df, swing_length=10, internal_length=2,
                      show_internal=False).detect_all()
    assert out == []


def test_range_high_survives_a_lower_pullback_high():
    """A shallow pullback high must not demote the range high.

    Bar 0 leaves 102 behind, the leg flushes to 96 and recovers, and only
    pivots a *lower* high 101.2 (bar 6). The nearer swing reports first when
    its close comes; the range high (102 @ bar 0) still reports afterwards,
    flagged as a range break.
    """
    df = _df([
        {"open": 100.0, "high": 102.0, "low": 100.5, "close": 101.0},
        {"open": 101.0, "high": 101.5, "low": 100.2, "close": 100.5},
        {"open": 100.5, "high": 100.8, "low": 100.0, "close": 100.2},
        {"open": 100.2, "high": 100.4, "low": 96.0, "close": 96.5},
        {"open": 96.5, "high": 100.8, "low": 96.2, "close": 100.5},
        {"open": 100.5, "high": 101.0, "low": 96.5, "close": 100.8},
        {"open": 100.8, "high": 101.2, "low": 100.0, "close": 100.2},
        {"open": 100.2, "high": 100.9, "low": 99.8, "close": 100.4},
        {"open": 100.4, "high": 101.0, "low": 100.1, "close": 100.7},
        {"open": 100.7, "high": 101.6, "low": 100.5, "close": 101.4},
        {"open": 101.4, "high": 101.5, "low": 100.8, "close": 101.2},
        {"open": 101.2, "high": 101.9, "low": 101.0, "close": 101.5},
        {"open": 101.5, "high": 102.4, "low": 101.3, "close": 102.2},
    ])
    lv = _bos(df)
    assert [(x.price, x.extreme_index, x.break_index, x.from_range)
            for x in lv] == [(101.2, 6, 9, False), (102.0, 0, 12, True)]


def test_range_low_survives_a_higher_pullback_low():
    """Mirror of the range-high case: the range low is not demoted upward.

    Bar 0 leaves 98 behind, the leg spikes to 102, and the pullback pivots a
    *higher* low 98.8 (bar 9). The closer swing reports first; the range low
    (98 @ bar 0) still reports at bar 13, flagged as a range break.
    """
    df = _df([
        {"open": 99.0, "high": 99.6, "low": 98.0, "close": 99.2},
        {"open": 99.2, "high": 100.2, "low": 99.0, "close": 100.0},
        {"open": 100.0, "high": 100.6, "low": 99.8, "close": 100.4},
        {"open": 100.4, "high": 101.0, "low": 100.2, "close": 100.8},
        {"open": 100.8, "high": 101.6, "low": 100.6, "close": 101.2},
        {"open": 101.2, "high": 102.0, "low": 101.0, "close": 101.6},
        {"open": 101.6, "high": 101.8, "low": 100.4, "close": 100.6},
        {"open": 100.6, "high": 100.8, "low": 99.4, "close": 99.8},
        {"open": 99.8, "high": 100.4, "low": 99.0, "close": 99.4},
        {"open": 99.4, "high": 99.8, "low": 98.8, "close": 99.2},
        {"open": 99.2, "high": 100.4, "low": 99.0, "close": 100.0},
        {"open": 100.0, "high": 100.2, "low": 99.6, "close": 99.8},
        {"open": 99.8, "high": 100.0, "low": 98.5, "close": 98.6},
        {"open": 98.6, "high": 98.8, "low": 97.6, "close": 97.9},
    ])
    lv = _bos(df)
    assert [(x.price, x.extreme_index, x.break_index, x.from_range)
            for x in lv] == [(98.8, 9, 12, False), (98.0, 0, 13, True)]


def test_range_breaks_are_excluded_from_the_idm_gate():
    """The IDM structure gate reads pivot breaks only."""
    lv = [
        BOSLevel(BOSDirection.BEARISH, 100.0, 0, 3, pd.Timestamp("2024-01-04")),
        BOSLevel(BOSDirection.BULLISH, 110.0, 1, 5, pd.Timestamp("2024-01-06"),
                 from_range=True),
    ]
    dirs = _structure_direction(8, lv)
    assert dirs == [None, None, None] + [BOSDirection.BEARISH] * 5
