"""
backtest/scan_em09.py — Find EM09 Trendline Break + Retest setups from M15 history.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd

from backtest.historical import load_or_fetch
from indicators.trendline_detector import TLDetector


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out = "backtest/out_strategy_probe/em09_manual_setups.json"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=500)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    tl_detector = TLDetector(df)
    lines = tl_detector.detect_all()

    # Filter: broken + retested
    broken_retested = [l for l in lines if l.broken and l.retested]
    print(f"Found {len(lines)} trendlines, {len(broken_retested)} broken+retested\n")

    records: List[Dict[str, Any]] = []
    for i, line in enumerate(broken_retested[:20], 1):
        j = int(line.break_index) if line.break_index is not None else int(line.end_index)
        if j >= len(df) - 1:
            continue

        side = str(line.side)  # "upper" or "lower"
        price = float(line.pivot_price)
        entry = price

        atr_series = _atr_series(df, 14)
        atr_val = atr_series[j] if j < len(atr_series) else 0.0
        buffer = 0.25 * (atr_val or 0.0)

        # After break, trade in break direction. Upper=resistance broken -> bullish.
        # Lower=support broken -> bearish.
        trade_dir = "bullish" if side == "upper" else "bearish"

        if trade_dir == "bullish":
            stop = price - buffer
            target = price + (price - stop) * 2.0
        else:
            stop = price + buffer
            target = price - (stop - price) * 2.0

        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 3) if risk > 0 else 0.0

        rec = {
            "rank": i,
            "entry_model": "EM09",
            "model_name": "Trendline break and retest",
            "timeframe": timeframe,
            "direction": trade_dir,
            "tl_side": side,
            "price": round(price, 3),
            "state": "broken_retested",
            "touches": line.touches,
            "retested": line.retested,
            "break_time": pd.Timestamp(df.index[j]).isoformat() if j < len(df) else "",
            "decision_time": pd.Timestamp(df.index[j] + pd.Timedelta(seconds=900)).isoformat(),
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "risk": round(risk, 3),
            "reward": round(reward, 3),
            "rr": rr,
            "outcome": "OPEN",
            "observation_notes": (
                f"EM09: {trade_dir} trendline break @ {price:.3f} at {pd.Timestamp(df.index[j])}, "
                f"touches={line.touches}, retested={line.retested}"
            ),
        }
        records.append(rec)

        print(f"  {i}. [{timeframe}] {trade_dir.upper()} EM09 Trendline Break/Retest")
        print(f"      Side:     {side}")
        print(f"      Price:    {price:.3f} at {pd.Timestamp(df.index[j])}")
        print(f"      Touches:  {line.touches}, Retested: {line.retested}")
        print(f"      Trade:    entry={entry:.3f}  SL={stop:.3f}  TP={target:.3f}  R:R={rr:.2f}")
        print()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM09",
        "count": len(records),
        "total_lines": len(lines),
        "broken_retested": len(broken_retested),
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
