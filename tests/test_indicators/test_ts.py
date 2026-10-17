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


def test_dojis_can_sweep():
    # Web-exact: TS is colour-independent — dojis sweep too.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 100},
        {"open": 100, "high": 107, "low": 97, "close": 100},
    ])
    lv = TSDetector(df).detect_all()
    assert {x.ts_type for x in lv} == {TSType.TS_HIGH, TSType.TS_LOW}


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


def test_no_ts_body_edge_high():
    # ❌ case from the chart: candle1 closes AT its high (no upper wick —
    # the "extreme" is a body edge, nothing was swept).
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 105},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    assert [x for x in TSDetector(df).detect_all()
            if x.ts_type == TSType.TS_HIGH] == []


def test_no_ts_body_edge_low():
    # Mirror: candle1 closes AT its low (no lower wick).
    df = _df([
        {"open": 100, "high": 101, "low": 95, "close": 95},
        {"open": 96, "high": 100, "low": 93, "close": 98},
    ])
    assert [x for x in TSDetector(df).detect_all()
            if x.ts_type == TSType.TS_LOW] == []


def test_dust_wick_counts_by_default_gate_opts_in():
    # Web-exact: any wick > 0 counts by default; the fraction gates are
    # opt-in display filters (live chart passes its tuned values).
    df = _df([
        {"open": 100, "high": 105.1, "low": 99, "close": 105},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    assert len([x for x in TSDetector(df).detect_all()
                if x.ts_type == TSType.TS_HIGH]) == 1
    gated = [x for x in TSDetector(df, min_wick_body_frac=0.10).detect_all()
             if x.ts_type == TSType.TS_HIGH]
    assert gated == []


def test_visible_wick_counts():
    # ✅ case from the chart: long upper wick protruding past the body.
    df = _df([
        {"open": 100, "high": 108, "low": 97, "close": 103},
        {"open": 104, "high": 110, "low": 100, "close": 102},
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].price == 108


def test_small_wick_on_big_body_counts():
    # Oct02 10:00 shape (scaled): 1.76 lower wick on a 12.42 body (14%).
    # Small but visible — the range leg (11% of range) agrees.
    df = _df([
        {"open": 184.13, "high": 186.01, "low": 169.95, "close": 171.71},
        {"open": 171.90, "high": 174.38, "low": 165.81, "close": 173.85},
    ])
    lv = TSDetector(df).detect_all()
    lowers = [x for x in lv if x.ts_type == TSType.TS_LOW]
    assert len(lowers) == 1
    assert lowers[0].price == 169.95


def test_wick_near_body_edge_fails_range():
    # Oct02 06:30 shape (scaled): 0.98 wick on 9.13 body passes the body
    # leg (10.8%) but at 8.8% of range it needs range_frac <= 0.05.
    # Guard: with the default 0.05 it fires; tightened to 0.10 it must not.
    df = _df([
        {"open": 189.54, "high": 190.59, "low": 179.43, "close": 180.41},
        {"open": 180.21, "high": 183.01, "low": 177.38, "close": 181.02},
    ])
    got = [x for x in TSDetector(df).detect_all()
           if x.ts_type == TSType.TS_LOW]
    assert len(got) == 1 and got[0].price == 179.43
    tight = [x for x in TSDetector(df, min_wick_range_frac=0.10).detect_all()
             if x.ts_type == TSType.TS_LOW]
    assert tight == []
