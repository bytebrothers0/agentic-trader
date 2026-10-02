"""
test_engine.py — Smoke tests for the walk-forward backtesting engine.
Uses synthetic past-only windows (no MT5 needed).
"""

import pandas as pd
import numpy as np

from backtest.engine import Backtester


def _mk(periods, freq, trend, amp, wick):
    idx = pd.date_range(start="2025-01-01", periods=periods, freq=freq)
    base = 2000 + np.linspace(0, trend, periods)
    osc = np.sin(np.linspace(0, 12, periods)) * amp
    o = base
    c = base + osc
    h = np.maximum(o, c) + np.abs(np.cos(np.linspace(0, 12, periods))) * wick + 1.0
    l = np.minimum(o, c) - np.abs(np.cos(np.linspace(0, 12, periods))) * wick - 1.0
    return pd.DataFrame(
        {"open": o, "high": h, "low": l, "close": c, "volume": [1000] * periods},
        index=idx,
    )


def _data():
    return {
        "MN1": _mk(24, "ME", 60, 25, 8),
        "W1": _mk(60, "W", 80, 18, 6),
        "D1": _mk(120, "D", 100, 15, 6),
        "H4": _mk(200, "4h", 60, 8, 3),
        "H1": _mk(300, "h", 40, 4, 2),
    }


def test_backtest_runs_and_math_consistent():
    data = _data()
    bt = Backtester(data, symbol="XAUUSD", initial_balance=10_000.0, step_bars=24)
    res = bt.run()

    assert "final_equity" in res.stats
    assert "win_rate_pct" in res.stats
    assert "max_drawdown_usd" in res.stats
    total_pnl = sum(t.partial_pnl_usd + t.pnl_usd for t in res.trades)
    assert abs(res.stats["final_equity"] - (10_000.0 + total_pnl)) < 0.05
    assert res.stats["final_equity"] > 0
    # Equity curve starts at initial balance.
    assert res.equity_curve[0]["equity"] == 10_000.0
    # No-lookahead spot check: every trade opened within the step-TF range.
    lo, hi = data["H1"].index[0], data["H1"].index[-1]
    for t in res.trades:
        assert lo <= t.open_time <= hi
        assert t.lots >= 0.01


def test_backtest_handles_quiet_market():
    # Flat market: engine must finish gracefully even with zero fills.
    idx = pd.date_range(start="2025-01-01", periods=100, freq="h")
    flat = pd.DataFrame(
        {"open": [2000.0] * 100, "high": [2000.5] * 100, "low": [1999.5] * 100,
         "close": [2000.0] * 100, "volume": [100] * 100},
        index=idx,
    )
    data = {"D1": flat.iloc[::24].copy(), "H4": flat.iloc[::4].copy(), "H1": flat.copy()}
    bt = Backtester(data, symbol="XAUUSD", step_bars=24)
    res = bt.run()
    assert res.stats["total_trades"] >= 0
    assert res.stats["final_equity"] > 0
