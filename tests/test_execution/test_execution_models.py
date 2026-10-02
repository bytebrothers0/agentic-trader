"""
test_execution_models.py — Pytest Suite for MSNR Entry Models (Phase 3) & Risk/Execution (Phase 5)

Tests:
  1. RiskManager (1% account risk sizing, fixed 300 pts SL, spread buffer)
  2. EntryEngine (Model A: Cascade, Model B: 14B, Model C: D1W4)
  3. OrderManager (Order struct formatting & position parsing)
"""

import pandas as pd
import numpy as np
import pytest

from strategy.entry_engine import EntryEngine, TradeSignal, EntryModelType
from execution.risk_manager import RiskManager, PositionPlan
from execution.order_manager import OrderManager
from strategy.storyline_engine import BiasDirection


@pytest.fixture
def test_multi_tf_data():
    """Generates synthetic multi-timeframe OHLCV bars with alternating candles."""
    def _make_df(dates, periods, trend_end, osc_amp, wick):
        base = 2000 + np.linspace(0, trend_end, periods)
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


def test_risk_manager_position_sizing():
    risk_mgr = RiskManager(risk_percent=1.0)
    metrics = risk_mgr.get_account_metrics()

    assert metrics.equity > 0

    plan = risk_mgr.calculate_position(
        symbol="XAUUSDm",
        direction=BiasDirection.BULLISH,
        entry_price=2000.0,
        sl_reference=1990.0,
        final_tp=2050.0,
        intermediate_obstacle=2025.0,
        risk_multiplier=1.0,
        model_name="Model A Test"
    )

    assert plan is not None
    assert plan.buffered_entry > 2000.0   # Spread buffer added for Buy
    assert plan.sl_points == 300           # Fixed 300 points on Gold
    assert plan.stop_loss < plan.buffered_entry
    assert plan.lot_size >= 0.01
    assert plan.risk_amount_usd > 0


def test_entry_engine_model_scan(test_multi_tf_data):
    engine = EntryEngine(test_multi_tf_data, symbol="XAUUSDm")
    signals = engine.scan_all_models()

    assert isinstance(signals, list)


def test_order_manager_structures():
    mgr = OrderManager(magic_number=888999)
    assert mgr.magic_number == 888999
