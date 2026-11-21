"""
backtest/scan_em05.py — Find EM05 SBR/RBS Role-Flip Retest setups from M15 history.
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
    out = "backtest/out_strategy_probe/em05_manual_setups.json"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=500)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    analyzer = CandleAnalyzer(df)
    levels = analyzer.detect_all()

    # Filter: SBR or RBS, FRESH state only (use .value)
    flip_levels = [l for l in levels if l.level_type.value in ("sbr", "rbs")
                   and l.state.value == "fresh"]

    # Sort by index descending (most recent first), take top 20
    flip_levels.sort(key=lambda l: l.candle_index, reverse=True)
    flip_levels = flip_levels[:20]

    print(f"Found {len(flip_levels)} recent fresh SBR/RBS levels:\n")

    records: List[Dict[str, Any]] = []
    for i, lvl in enumerate(flip_levels, 1):
        j = int(lvl.candle_index)
        direction = lvl.level_type.value  # "sbr" or "rbs"
        price = float(lvl.price)
        entry = price

        atr_series = _atr_series(df, 14)
        atr_val = atr_series[j] if j < len(atr_series) else 0.0
        buffer = 0.25 * (atr_val or 0.0)

        if direction == "rbs":
            # Resistance became support -> bullish retest
            stop = price - buffer
            target = price + (price - stop) * 2.0
            trade_dir = "bullish"
        else:
            # Support became resistance -> bearish retest
            stop = price + buffer
            target = price - (stop - price) * 2.0
            trade_dir = "bearish"

        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 3) if risk > 0 else 0.0

        rec = {
            "rank": i,
            "entry_model": "EM05",
            "model_name": "SBR/RBS role-flip retest",
            "timeframe": timeframe,
            "direction": trade_dir,
            "level_type": direction,
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
                f"EM05: {direction} role-flip @ {price:.3f} at {pd.Timestamp(lvl.candle_time)}, "
                f"touches={lvl.touch_count}"
            ),
        }
        records.append(rec)

        print(f"  {i}. [{timeframe}] {trade_dir.upper()} EM05 {direction} Role-Flip")
        print(f"      Price:    {price:.3f} at {pd.Timestamp(lvl.candle_time)}")
        print(f"      Touches:  {lvl.touch_count}, State: {lvl.state.value}")
        print(f"      Trade:    entry={entry:.3f}  SL={stop:.3f}  TP={target:.3f}  R:R={rr:.2f}")
        print()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM05",
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
