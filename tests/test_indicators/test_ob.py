"""Tests for OB + Breaker Blocks (LuxAlgo port + Luap status)."""
import pandas as pd

from indicators.ob_detector import OBDetector, OBDirection


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _bull(df, **kw):
    return [x for x in OBDetector(df, swing_length=2, **kw).detect_all()
            if x.direction == OBDirection.BULLISH]


def _bear(df, **kw):
    return [x for x in OBDetector(df, swing_length=2, **kw).detect_all()
            if x.direction == OBDirection.BEARISH]


BULL_BASE = [
    {"open": 100, "high": 102, "low": 99, "close": 101},
    {"open": 101, "high": 105, "low": 100, "close": 104},
    {"open": 104, "high": 103, "low": 101, "close": 102},
    {"open": 102, "high": 104, "low": 101, "close": 103},
    {"open": 103, "high": 106, "low": 102, "close": 105.5},
]


def test_bullish_ob_formation():
    lv = _bull(_df(BULL_BASE))
    assert len(lv) == 1
    assert not lv[0].is_breaker
    assert lv[0].bottom == 101 and lv[0].top == 103
    assert lv[0].formation_index == 2


def test_bullish_breaker_flip():
    df = _df(BULL_BASE + [
        {"open": 105.5, "high": 106, "low": 100, "close": 100.5},
    ])
    lv = _bear(df)
    assert len(lv) == 1
    assert lv[0].is_breaker
    assert lv[0].bottom == 101 and lv[0].top == 103
    assert lv[0].break_index == 5


def test_breaker_removed_on_acceptance_back():
    df = _df(BULL_BASE + [
        {"open": 105.5, "high": 106, "low": 100, "close": 100.5},
        {"open": 100.5, "high": 112, "low": 101, "close": 111},
    ])
    assert _bear(df) == [] and _bull(df) == []


def test_bearish_ob_formation():
    df = _df([
        {"open": 103, "high": 106, "low": 102, "close": 105},
        {"open": 105, "high": 106, "low": 100, "close": 101},
        {"open": 101, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 99.5, "close": 102.5},
        {"open": 102.5, "high": 103, "low": 100, "close": 101},
        {"open": 101, "high": 101.5, "low": 96, "close": 97},
    ])
    lv = _bear(df)
    assert len(lv) == 1
    assert not lv[0].is_breaker
    assert lv[0].bottom == 99.5 and lv[0].top == 103


def test_wick_only_swing_cross_is_nothing():
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 101},
        {"open": 101, "high": 105, "low": 100, "close": 104},
        {"open": 104, "high": 103, "low": 101, "close": 102},
        {"open": 102, "high": 107, "low": 101, "close": 103.5},
        {"open": 103.5, "high": 104, "low": 102, "close": 103},
    ])
    assert OBDetector(df, swing_length=2).detect_all() == []


def test_show_last_keeps_newest_per_side():
    df = _df(BULL_BASE + [
        {"open": 105.5, "high": 107, "low": 104, "close": 106},
        {"open": 106, "high": 106.5, "low": 102, "close": 103},
        {"open": 103, "high": 109, "low": 102, "close": 107.5},
        {"open": 107.5, "high": 108, "low": 106, "close": 107},
        {"open": 107, "high": 107.5, "low": 106, "close": 106.5},
        {"open": 106.5, "high": 110, "low": 106, "close": 109.5},
    ])
    assert len(_bull(df)) == 2
    short = _bull(df, show_last=1)
    assert len(short) == 1 and short[0].formation_index == 8
