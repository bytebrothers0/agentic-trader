"""Tests for the liquidity-pool indicator (equal highs / equal lows).

Rule: two or more swings at (almost) the same price form a pool. Single stray
swings are excluded. A pool spans its first -> last touch; a later wick through
the level marks it taken.
"""
import pandas as pd
import pytest

from indicators.liquidity_detector import LiquidityDetector, LIQType


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _mirror(rows, base=200.0):
    return [
        {"open": base - r["close"], "high": base - r["low"],
         "low": base - r["high"], "close": base - r["open"]}
        for r in rows
    ]


# Equal highs at 110.0 on idx 3 and idx 8.
EQH_ROWS = [
    {"open": 100, "high": 101, "low": 99, "close": 100},
    {"open": 100, "high": 102, "low": 99.5, "close": 101},
    {"open": 101, "high": 104, "low": 100.5, "close": 103},
    {"open": 103, "high": 110, "low": 102.8, "close": 109.5},
    {"open": 109.5, "high": 109.6, "low": 107, "close": 108},
    {"open": 108, "high": 108.5, "low": 106, "close": 107},
    {"open": 107, "high": 108, "low": 105, "close": 106},
    {"open": 106, "high": 108.5, "low": 105.5, "close": 108},
    {"open": 108, "high": 110, "low": 107.5, "close": 109.5},
    {"open": 109.5, "high": 109.6, "low": 107, "close": 108},
    {"open": 108, "high": 108.5, "low": 106, "close": 107},
]

SINGLE_SWING_ROWS = [
    {"open": 100, "high": 101, "low": 99, "close": 100},
    {"open": 101, "high": 102, "low": 100, "close": 101},
    {"open": 101, "high": 105, "low": 100.5, "close": 104},
    {"open": 104, "high": 110, "low": 103, "close": 109},
    {"open": 109, "high": 109.5, "low": 107, "close": 108},
    {"open": 108, "high": 108.5, "low": 106, "close": 107},
    {"open": 107, "high": 108, "low": 105, "close": 106},
    {"open": 106, "high": 107, "low": 104, "close": 105},
    {"open": 105, "high": 106, "low": 103, "close": 104},
]


def test_equal_highs_untaken():
    lv = LiquidityDetector(_df(EQH_ROWS), swing_length=2).detect_all()
    assert len(lv) == 1
    pool = lv[0]
    assert pool.liq_type == LIQType.EQH
    assert pool.side.value == "buyside"
    assert pool.price == 110
    assert pool.pool_size == 2
    assert pool.first_index == 3 and pool.last_index == 8
    assert pool.taken is False


def test_equal_highs_taken():
    rows = EQH_ROWS + [{"open": 109, "high": 111, "low": 107, "close": 109}]
    lv = LiquidityDetector(_df(rows), swing_length=2).detect_all()
    eqh = [x for x in lv if x.liq_type == LIQType.EQH]
    assert len(eqh) == 1
    assert eqh[0].taken is True
    assert eqh[0].taken_index == 11


def test_equal_lows_pool_is_mirror():
    lv = LiquidityDetector(_df(_mirror(EQH_ROWS)), swing_length=2).detect_all()
    eql = [x for x in lv if x.liq_type == LIQType.EQL]
    assert len(eql) == 1
    assert eql[0].price == 90.0            # 200 - 110
    assert eql[0].pool_size == 2
    assert eql[0].side.value == "sellside"
    assert eql[0].taken is False


def test_single_swing_is_not_a_pool():
    assert LiquidityDetector(_df(SINGLE_SWING_ROWS),
                             swing_length=2).detect_all() == []


def test_short_frame_returns_empty():
    df = _df([{"open": 1, "high": 2, "low": 0.5, "close": 1}])
    assert LiquidityDetector(df, swing_length=2).detect_all() == []


def test_validation_requires_ohlcv():
    with pytest.raises(ValueError):
        LiquidityDetector(pd.DataFrame(
            {"high": [1], "low": [1], "open": [1]},   # no "close"
            index=pd.date_range("2024-01-01", periods=1, freq="D"),
        ))
