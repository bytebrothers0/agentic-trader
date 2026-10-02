"""
test_strategy_core.py — Pytest Suite for MSNR Strategy Core (Phase 2)

Tests:
  1. StorylineEngine (Multi-TF rejection + breakout detection)
  2. FTFLLocator (FTFL selection & box calculation)
  3. STFLLocator (STFL refinement inside FTFL box)
  4. TTFLLocator (TTFL key level & 50% Equilibrium fallback)
  5. ObstacleScanner (Obstacle barriers & final Draw on Liquidity)
"""

import pandas as pd
import numpy as np
import pytest

from strategy.storyline_engine import StorylineEngine, StorylineEvent, BiasDirection
from strategy.ftfl_locator import FTFLLocator, FTFLZone, FTFLPriority
from strategy.stfl_locator import STFLLocator, STFLZone
from strategy.ttfl_locator import TTFLLocator, TTFLRefinement, TTFLEntryType
from strategy.obstacle_scanner import ObstacleScanner, ObstacleTarget


@pytest.fixture
def multi_tf_data():
    """Generates synthetic multi-timeframe OHLCV dataset with alternating candles (forms real S/R)."""
    def _make_df(dates, periods, trend_end, osc_amp, wick):
        base = 2000 + np.linspace(0, trend_end, periods)
        # Oscillating close creates alternating bullish/bearish candles so S/R can form.
        osc = np.sin(np.linspace(0, 10, periods)) * osc_amp
        opens = base
        closes = base + osc
        highs = np.maximum(opens, closes) + np.abs(np.cos(np.linspace(0, 10, periods))) * wick + 1.0
        lows = np.minimum(opens, closes) - np.abs(np.cos(np.linspace(0, 10, periods))) * wick - 1.0
        return pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000] * periods
        }, index=dates)

    dates_d1 = pd.date_range(start="2026-01-01", periods=60, freq="D")
    dates_h4 = pd.date_range(start="2026-01-01", periods=120, freq="4h")
    dates_h1 = pd.date_range(start="2026-01-01", periods=240, freq="1h")

    df_d1 = _make_df(dates_d1, 60, 100, 15, 6)
    df_h4 = _make_df(dates_h4, 120, 100, 8, 3)
    df_h1 = _make_df(dates_h1, 240, 100, 4, 2)

    return {"D1": df_d1, "H4": df_h4, "H1": df_h1}


def test_ftfl_locator():
    # Deterministic frame ending in a genuinely FRESH bullish support:
    # Day 7 bearish -> Day 8 bullish forms SUPPORT @ 2000, Day 9 never touches
    # it (low 2012). Storyline breakout at bar 8 = immediate mode (<=3 bars).
    dates = pd.date_range(start="2026-01-01", periods=10, freq="D")
    opens  = [2000, 1990, 2005, 1998, 2010, 2005, 2005, 2012, 2000, 2015]
    closes = [1990, 2005, 1998, 2010, 2005, 2012, 2012, 2000, 2015, 2020]
    highs  = [2005, 2010, 2010, 2015, 2015, 2017, 2017, 2017, 2020, 2025]
    lows   = [1985, 1985, 1993, 1993, 2000, 2000, 2000, 1995, 1995, 2012]
    df_d1 = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1000] * 10},
        index=dates,
    )

    storyline = StorylineEvent(
        htf="W1",
        ltf="D1",
        bias=BiasDirection.BULLISH,
        rejection_price=2000.0,
        rejection_time=df_d1.index[8],
        rejection_candle_idx=8,
        breakout_time=df_d1.index[8],
        breakout_candle_idx=8,
        rejection_level_desc="Weekly Fresh Support"
    )

    locator = FTFLLocator(df_d1, timeframe="D1")
    ftfl_zone = locator.find_ftfl(storyline)

    assert ftfl_zone is not None
    assert ftfl_zone.direction == BiasDirection.BULLISH
    assert ftfl_zone.price == 2000.0
    assert ftfl_zone.box_top >= ftfl_zone.box_bottom
    assert ftfl_zone.equilibrium == (ftfl_zone.box_top + ftfl_zone.box_bottom) / 2.0


def test_stfl_and_ttfl_cascade(multi_tf_data):
    df_h4 = multi_tf_data["H4"]
    df_h1 = multi_tf_data["H1"]

    # 1. Build an FTFL zone from a REAL detected support so the cascade has
    # genuine confirmation (Bug 9: no more guaranteed direct-zone fallback).
    from indicators.candle_analyzer import CandleAnalyzer
    from indicators.freshness_tracker import FreshnessTracker
    analyzer = CandleAnalyzer(df_h4)
    levels = analyzer.detect_all()
    levels = FreshnessTracker(df_h4).update(levels)
    supports = [lv for lv in levels if lv.level_type.value == "support"]
    assert len(supports) >= 1, "fixture must produce at least one support level"
    src = supports[len(supports) // 2]
    idx = src.candle_index
    highs = df_h4["high"].values
    lows = df_h4["low"].values
    ftfl = FTFLZone(
        timeframe="D1",
        direction=BiasDirection.BULLISH,
        price=src.price,
        box_top=float(max(highs[idx], highs[min(idx + 1, len(df_h4) - 1)])),
        box_bottom=float(min(lows[idx], lows[min(idx + 1, len(df_h4) - 1)])),
        time_formed=src.candle_time,
        candle_index=idx,
        level_type_desc="Daily Fresh Support",
        priority=FTFLPriority.A_PLUS
    )

    # 2. Refine down to STFL (4H) — must find confirmation inside/near the box.
    stfl_locator = STFLLocator(df_h4, stfl_timeframe="H4")
    stfl_zone = stfl_locator.find_stfl(ftfl)

    assert stfl_zone is not None
    assert stfl_zone.direction == BiasDirection.BULLISH
    assert stfl_zone.box_top >= stfl_zone.box_bottom

    # 3. Refine down to TTFL (1H) with Equilibrium fallback
    ttfl_locator = TTFLLocator(df_h1, ttfl_timeframe="H1")
    ttfl_refinement = ttfl_locator.refine(stfl_zone)

    assert ttfl_refinement is not None
    assert ttfl_refinement.direction == BiasDirection.BULLISH
    assert ttfl_refinement.entry_price > 0
    assert ttfl_refinement.sl_reference > 0


def test_obstacle_scanner(multi_tf_data):
    df_d1 = multi_tf_data["D1"]
    scanner = ObstacleScanner(df_d1, timeframe="D1")

    targets = scanner.scan_targets(entry_price=2020.0, direction=BiasDirection.BULLISH)

    assert len(targets) >= 1
    # Check that final Draw on Liquidity is included
    final_tp = [t for t in targets if t.is_final_tp]
    assert len(final_tp) == 1
    assert final_tp[0].price > 2020.0
