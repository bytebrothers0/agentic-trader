"""Tests for the IDM (inducement/liquidity) indicator (Luap True SMC).

Rule: reference candle 1 + a later break of its low (pullback) + a later
break of its high (continuation) -> swing low between the breaks is the
bullish IDM. Bearish mirrors. One-sided drift yields no IDM.
"""
import pandas as pd

from indicators.idm_detector import IDMDetector, IDMType


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _lows(df):
    return [x for x in IDMDetector(df).detect_all() if x.idm_type == IDMType.IDM_LOW]


def _highs(df):
    return [x for x in IDMDetector(df).detect_all() if x.idm_type == IDMType.IDM_HIGH]


def test_bullish_idm_swept():
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 103, "high": 110, "low": 102, "close": 108},
        {"open": 108, "high": 109, "low": 98, "close": 101},
        {"open": 101, "high": 111, "low": 100, "close": 110},
        {"open": 110, "high": 110.5, "low": 95, "close": 100},
    ])
    lv = _lows(df)
    assert len(lv) == 1
    assert lv[0].price == 98
    assert lv[0].swept is True
    assert lv[0].formation_index == 2
    assert lv[0].sweep_index == 4


def test_bearish_idm_swept():
    df = _df([
        {"open": 103, "high": 105, "low": 100, "close": 101},
        {"open": 101, "high": 102, "low": 95, "close": 97},
        {"open": 97, "high": 103, "low": 96, "close": 102},
        {"open": 102, "high": 101, "low": 94, "close": 96},
        {"open": 96, "high": 104, "low": 93, "close": 103},
    ])
    lv = _highs(df)
    swept = [x for x in lv if x.swept]
    assert len(swept) == 1
    assert swept[0].price == 103 and swept[0].sweep_index == 4


def test_no_continuation_no_bullish_idm():
    # Pullback with no continuation is a reversal, not inducement.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 103, "high": 110, "low": 102, "close": 108},
        {"open": 108, "high": 109, "low": 98, "close": 101},
        {"open": 101, "high": 104, "low": 96, "close": 99},
    ])
    assert _lows(df) == []


def test_high_first_invalidates_no_idm():
    # Shallow pullback never breaks the low, then a new high: no IDM.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 103, "high": 110, "low": 102, "close": 108},
        {"open": 105, "high": 108, "low": 104, "close": 106},
        {"open": 106, "high": 112, "low": 105, "close": 111},
    ])
    assert IDMDetector(df).detect_all() == []


def test_inside_bar_ignored_pullback_uses_mother():
    # idx2 is inside idx1; idx3 breaks the mother (idx1) low -> valid.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 103, "high": 110, "low": 102, "close": 108},
        {"open": 105, "high": 108, "low": 104, "close": 106},
        {"open": 106, "high": 107, "low": 100, "close": 102},
        {"open": 102, "high": 112, "low": 101, "close": 110},
    ])
    lv = IDMDetector(df).detect_all()
    assert len(lv) == 1
    assert lv[0].idm_type == IDMType.IDM_LOW
    assert lv[0].price == 100 and lv[0].formation_index == 3
    assert not lv[0].swept
