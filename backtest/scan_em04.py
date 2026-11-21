"""
backtest/scan_em04.py — Find EM04 Fresh S/R Level Rejection setups from M15 history.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd

from backtest.historical import load_or_fetch
from indicators.candle_analyzer import CandleAnalyzer


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out = "backtest/out_strategy_probe/em04_manual_setups.json"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=180)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    analyzer = CandleAnalyzer(df)
    levels = analyzer.detect_all()

    # Filter: SUPPORT or RESISTANCE, FRESH state only (use .value)
    fresh_sr = [l for l in levels if l.level_type.value in ("support", "resistance")
                and l.state.value == "fresh"]

    print(f"Found {len(fresh_sr)} fresh S/R levels:\n")

    records: List[Dict[str, Any]] = []
    for i, lvl in enumerate(fresh_sr, 1):
        j = int(lvl.candle_index)
        direction = lvl.level_type.value  # "support" or "resistance"
        price = float(lvl.price)
        entry = price

        # Simple ATR buffer
        atr_series = _atr_series(df, 14)
        atr_val = atr_series[j] if j < len(atr_series) else 0.0
        buffer = 0.25 * (atr_val or 0.0)

        if direction == "support":
            stop = price - buffer
            target = price + (price - stop) * 2.0
            trade_dir = "bullish"
        else:
            stop = price + buffer
            target = price - (stop - price) * 2.0
            trade_dir = "bearish"

        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 3) if risk > 0 else 0.0

        rec = {
            "rank": i,
            "entry_model": "EM04",
            "model_name": "Fresh MSNR level rejection",
            "timeframe": timeframe,
            "direction": trade_dir,
            "level_type": lvl.level_type.value,
            "price": round(price, 3),
            "state": lvl.state.value,
            "touch_count": lvl.touch_count,
            "time": pd.Timestamp(lvl.candle_time).isoformat(),
            "decision_time": pd.Timestamp(df.index[j] + pd.Timedelta(seconds=900)).isoformat(),
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "risk": round(risk, 3),
            "reward": round(reward, 3),
            "rr": rr,
            "outcome": "OPEN",
            "observation_notes": (
                f"EM04: Fresh {direction} {lvl.level_type.value} @ {price:.3f} "
                f"at {pd.Timestamp(lvl.candle_time)}, touches={lvl.touch_count}"
            ),
        }
        records.append(rec)

        print(f"  {i}. [{timeframe}] {trade_dir.upper()} EM04 Fresh {lvl.level_type.value}")
        print(f"      Price:    {price:.3f} at {pd.Timestamp(lvl.candle_time)}")
        print(f"      Touches:  {lvl.touch_count}, State: {lvl.state.value}")
        print(f"      Trade:    entry={entry:.3f}  SL={stop:.3f}  TP={target:.3f}  R:R={rr:.2f}")
        print()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM04",
        "count": len(records),
        "setups": records,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Saved {len(records)} setups to {out}")
    return 0


def _atr_series(df: pd.DataFrame, period: int = 14) -> List[float]:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    p = max(1, int(period))
    return tr.ewm(alpha=1.0 / p, min_periods=1, adjust=False).mean().tolist()


if __name__ == "__main__":
    raise SystemExit(main())
