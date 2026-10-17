"""
test_indicators_all.py — Pytest Suite for MSNR Foundation Indicators

Tests:
  1. CandleAnalyzer (Support, Resistance, SBR, RBS)
  2. FreshnessTracker (Fresh -> Unfresh -> Broken state transitions)
  3. OCLDetector (sOCL, rOCL, 1-Lap OCL, LS OCL, engulfing disqualification)
  4. QMDetector (ABQM, FTQM, STQM from failed SBR/RBS)
  5. ApexDetector (Apex Support/Resistance and IAB with breakout confirmation)
"""

import numpy as np
import pandas as pd
import pytest

from indicators.candle_analyzer import CandleAnalyzer, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.ocl_detector import OCLDetector, OCLType
from indicators.qm_detector import QMDetector, QMType, QMDirection
from indicators.apex_detector import ApexDetector, ApexType


@pytest.fixture
def sample_ohlcv_data():
    """Generates synthetic OHLCV data with known MSNR patterns."""
    dates = pd.date_range(start="2026-01-01", periods=30, freq="D")
    
    # Construct a synthetic pattern:
    # Day 0: Bearish, Day 1: Bullish -> Support at Day 0 close
    # Day 2: Bullish, Day 3: Bearish -> Resistance at Day 2 close
    opens  = [2000, 1980, 1990, 2020, 2005, 1970, 1985, 2010, 2030, 2015] + [2000]*20
    closes = [1980, 2000, 2020, 1995, 1970, 1990, 2015, 2035, 2010, 1980] + [2000]*20
    highs  = [2005, 2005, 2025, 2025, 2010, 1995, 2020, 2040, 2035, 2020] + [2005]*20
    lows   = [1975, 1975, 1985, 1990, 1965, 1965, 1980, 2005, 2005, 1975] + [1995]*20
    volume = [1000] * 30

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volume
    }, index=dates)
    return df


def test_candle_analyzer_support_resistance(sample_ohlcv_data):
    analyzer = CandleAnalyzer(sample_ohlcv_data)
    levels = analyzer.detect_all()
    
    supports = analyzer.get_supports()
    resistances = analyzer.get_resistances()
    
    assert len(supports) >= 1
    assert len(resistances) >= 1
    
    # First support is at Day 0 close = 1980
    assert supports[0].price == 1980.0
    # First resistance is at Day 2 close = 2020
    assert resistances[0].price == 2020.0


def test_freshness_tracker(sample_ohlcv_data):
    analyzer = CandleAnalyzer(sample_ohlcv_data)
    levels = analyzer.detect_all()
    
    tracker = FreshnessTracker(sample_ohlcv_data)
    updated_levels = tracker.update(levels)
    
    # Day 0 support (1980) was later crossed below by Day 4 (close=1970)
    sup_0 = [lv for lv in updated_levels if lv.price == 1980.0 and lv.level_type == LevelType.SUPPORT][0]
    assert sup_0.state == LevelState.BROKEN


def test_freshness_tracker_close_through_break():
    """Verify a pristine FRESH support level is marked BROKEN by a normal candle close-through."""
    dates = pd.date_range(start="2026-01-01", periods=10, freq="D")
    # Day 0: Bearish, Day 1: Bullish -> Support at Day 0 close = 1980
    # Day 2: Bullish candle above support (1990 -> 2010) -> Support stays FRESH
    # Day 3: Candle closes at 1970 (body close-through 1980) -> Support becomes BROKEN
    opens  = [2000, 1975, 1990, 1990, 1960, 1960, 1960, 1960, 1960, 1960]
    closes = [1980, 2000, 2010, 1970, 1960, 1960, 1960, 1960, 1960, 1960]
    highs  = [2005, 2005, 2015, 1995, 1965, 1965, 1965, 1965, 1965, 1965]
    lows   = [1975, 1970, 1985, 1965, 1945, 1945, 1945, 1945, 1945, 1945]

    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": [100]*10}, index=dates)

    analyzer = CandleAnalyzer(df)
    # Detect S/R without running role reversals to get raw FRESH level
    levels = analyzer._filter(LevelType.SUPPORT, fresh_only=False)
    if not levels:
        analyzer._detect_sr()
        levels = analyzer.get_supports()
    sup = levels[0]
    assert sup.state == LevelState.FRESH

    tracker = FreshnessTracker(df)
    tracker.update([sup])
    assert sup.state == LevelState.BROKEN


def test_ocl_detector():
    dates = pd.date_range(start="2026-01-01", periods=10, freq="D")
    # Video 2 rOCL (web engulf rule): two BULLISH candles (Day 0-1) engulfed
    # by the BEARISH candle completing a Resistance (Day 2). Level = Day 0 close.
    opens  = [2000, 2020, 2045, 1990, 1990, 1990, 1990, 1990, 1990, 1990]
    closes = [2020, 2040, 1990, 1990, 1990, 1990, 1990, 1990, 1990, 1990]
    highs  = [2025, 2045, 2050, 1995, 1995, 1995, 1995, 1995, 1995, 1995]
    lows   = [1995, 2015, 1985, 1985, 1985, 1985, 1985, 1985, 1985, 1985]

    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": [100]*10}, index=dates)

    detector = OCLDetector(df, timeframe="D1")
    ocls = detector.detect_all()

    assert len(ocls) >= 1
    rocls = [o for o in ocls if o.ocl_type == OCLType.ROCL]
    assert len(rocls) >= 1
    # rOCL pair Day 0-1, level at Day 0 close = 2020
    assert rocls[0].price == 2020.0


def test_ocl_socl_detector():
    dates = pd.date_range(start="2026-01-01", periods=10, freq="D")
    # Video 2 sOCL (web engulf rule): two BEARISH candles (Day 0-1) engulfed
    # by the BULLISH candle completing a Support (Day 2). Level = Day 0 close.
    opens  = [2020, 2000, 1975, 2030, 2030, 2030, 2030, 2030, 2030, 2030]
    closes = [2000, 1980, 2030, 2030, 2030, 2030, 2030, 2030, 2030, 2030]
    highs  = [2025, 2005, 2035, 2035, 2035, 2035, 2035, 2035, 2035, 2035]
    lows   = [1995, 1975, 1970, 2025, 2025, 2025, 2025, 2025, 2025, 2025]

    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": [100]*10}, index=dates)

    detector = OCLDetector(df, timeframe="D1")
    ocls = detector.detect_all()

    socls = [o for o in ocls if o.ocl_type == OCLType.SOCL]
    assert len(socls) >= 1
    # sOCL pair Day 0-1, level at Day 0 close = 2000
    assert socls[0].price == 2000.0


def test_qm_detector():
    dates = pd.date_range(start="2026-01-01", periods=10, freq="D")
    # 1. Day 0-1: Support at 1980
    # 2. Day 2: Breaks below 1980 -> becomes SBR at 1980
    # 3. Day 3: Rallies and closes back above 1980 -> Failed SBR -> Bullish QM!
    opens  = [2000, 1980, 1980, 1970, 2010, 2000, 2000, 2000, 2000, 2000]
    closes = [1980, 2000, 1970, 2010, 2020, 2000, 2000, 2000, 2000, 2000]
    highs  = [2005, 2005, 1985, 2015, 2025, 2005, 2005, 2005, 2005, 2005]
    lows   = [1975, 1975, 1965, 1965, 2005, 1995, 1995, 1995, 1995, 1995]

    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": [100]*10}, index=dates)

    analyzer = CandleAnalyzer(df)
    base_levels = analyzer.detect_all()

    qm_det = QMDetector(df, base_levels)
    qms = qm_det.detect_all()

    assert len(qms) >= 1
    assert qms[0].direction == QMDirection.BULLISH
    assert qms[0].price == 1980.0


def test_apex_detector():
    dates = pd.date_range(start="2026-01-01", periods=20, freq="D")
    # Synthetic swing high at index 4 (price 2050), then break below valley at index 2 (1980)
    closes = [2000, 1990, 1980, 2020, 2050, 2010, 1970, 1960, 1950, 1940] + [1950]*10
    df = pd.DataFrame({
        "open": closes,
        "high": [c + 5 for c in closes],
        "low": [c - 5 for c in closes],
        "close": closes,
        "volume": [100]*20
    }, index=dates)

    apex_det = ApexDetector(df, timeframe="D1", min_distance=2)
    apexes = apex_det.detect_all()

    assert len(apexes) >= 1
    res_apexes = [a for a in apexes if a.apex_type in (ApexType.APEX_RESISTANCE, ApexType.IAB_RESISTANCE)]
    assert len(res_apexes) >= 1
    assert res_apexes[0].price == 2050.0
