"""Tests for the BOS/CHoCH indicator (Mxwll-style port).

Logic: Donchian-zigzag swings (bar L ago exceeding all L bars after it) +
CLOSE through the last swing. Wick-only crosses never fire; one shot per
level; breaks against trend state are CHoCH.
"""
import pandas as pd

from indicators.bos_detector import BOSDetector, BOSDirection


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
