"""Tests for the Turtle Soup (TS) indicator."""
import pandas as pd

from indicators.ts_detector import TSDetector, TSType, TSDirection


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def test_upper_ts_bearish_sweep():
    # bull -> bear, sweeps the high, body closes back below it
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].direction == TSDirection.BEARISH
    assert uppers[0].price == 105
    assert uppers[0].candle_index == 1


def test_lower_ts_bullish_sweep():
    # bear -> bull, sweeps the low, body closes back above it
    df = _df([
        {"open": 103, "high": 105, "low": 98, "close": 100},
        {"open": 99, "high": 102, "low": 96, "close": 101},
    ])
    lv = TSDetector(df).detect_all()
    lowers = [x for x in lv if x.ts_type == TSType.TS_LOW]
    assert len(lowers) == 1
    assert lowers[0].direction == TSDirection.BULLISH
    assert lowers[0].price == 98


def test_no_ts_same_colour():
    # NOTE: same-colour pairs now COUNT (user rule change) — a bull -> bull
    # sweep with close back inside is a valid TS.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 102, "high": 107, "low": 101, "close": 106},
    ])
    lv = TSDetector(df).detect_all()
    # candle2 body (102-106) does NOT close back below 105 -> no TS
    assert [x for x in lv if x.ts_type == TSType.TS_HIGH] == []


def test_no_ts_body_closes_through():
    # sweep but body closes ABOVE the swept high -> not ts, that's a break
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 104, "high": 107, "low": 103, "close": 106},
    ])
    lv = TSDetector(df).detect_all()
    assert [x for x in lv if x.ts_type == TSType.TS_HIGH] == []


def test_no_ts_no_sweep():
    # opposite colours but no sweep of either wick
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 102, "high": 104, "low": 100, "close": 101},
    ])
    assert TSDetector(df).detect_all() == []


def test_same_colour_sweep_counts():
    # red -> red: sweeps the low, body closes back above -> valid TS_LOW
    df = _df([
        {"open": 103, "high": 105, "low": 98, "close": 100},
        {"open": 101, "high": 102, "low": 96, "close": 99},
    ])
    lv = TSDetector(df).detect_all()
    lowers = [x for x in lv if x.ts_type == TSType.TS_LOW]
    assert len(lowers) == 1
    assert lowers[0].price == 98


def test_dojis_never_qualify():
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 100},
        {"open": 100, "high": 107, "low": 97, "close": 100},
    ])
    assert TSDetector(df).detect_all() == []


def test_sweep_gate_filters_micro_sweeps():
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    # Unfiltered: upper TS (sweep 2.0) fires.
    assert len(TSDetector(df).detect_all()) == 1
    # Gated far above local volatility: nothing fires.
    assert TSDetector(df, min_sweep_atr=5.0).detect_all() == []
    # Gated at zero: fires (default behavior preserved).
    assert len(TSDetector(df, min_sweep_atr=0.0).detect_all()) == 1
