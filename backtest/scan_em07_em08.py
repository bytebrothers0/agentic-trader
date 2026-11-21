"""
backtest/scan_em07_em08.py — Find EM07 OB retest + EM08 Breaker retest setups.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd

from backtest.historical import load_or_fetch
from indicators.ob_detector import OBDetector


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=500)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    ob_detector = OBDetector(df, swing_length=10, show_last=3,
                             require_fvg=False, require_sweep=True)
    ob_levels = ob_detector.detect_all()

    print(f"Found {len(ob_levels)} order blocks total")

    em07: List[Dict[str, Any]] = []  # non-breaker OB
    em08: List[Dict[str, Any]] = []  # breaker

    atr_series = _atr_series(df, 14)

    for ob in ob_levels:
        j = int(ob.formation_index)
        if j >= len(df) - 1:
            continue
        entry = (float(ob.top) + float(ob.bottom)) / 2.0
        atr_val = atr_series[j] if j < len(atr_series) else 0.0
        buffer = 0.25 * (atr_val or 0.0)

        direction = "bullish" if ob.direction.value == "bullish" else "bearish"
        if direction == "bullish":
            stop = float(ob.bottom) - buffer
            target = float(ob.top) + (float(ob.top) - float(ob.bottom)) * 2.0
        else:
            stop = float(ob.top) + buffer
            target = float(ob.bottom) - (float(ob.top) - float(ob.bottom)) * 2.0

        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 3) if risk > 0 else 0.0

        rec = {
            "entry_model": "EM08" if ob.is_breaker else "EM07",
            "model_name": "Breaker retest" if ob.is_breaker else "Displacement-backed order-block retest",
            "timeframe": timeframe,
            "direction": direction,
            "is_breaker": ob.is_breaker,
            "zone_top": round(float(ob.top), 3),
            "zone_bottom": round(float(ob.bottom), 3),
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "risk": round(risk, 3),
            "reward": round(reward, 3),
            "rr": rr,
            "mitigated": ob.mitigated,
            "time": pd.Timestamp(ob.candle_time).isoformat(),
            "decision_time": pd.Timestamp(df.index[j] + pd.Timedelta(seconds=900)).isoformat(),
            "observation_notes": (
                f"{'EM08' if ob.is_breaker else 'EM07'}: {direction} {'breaker' if ob.is_breaker else 'OB'} "
                f"zone {float(ob.bottom):.3f}-{float(ob.top):.3f} at {pd.Timestamp(ob.candle_time)}, "
                f"mitigated={ob.mitigated}"
            ),
        }

        if ob.is_breaker:
            em08.append(rec)
        else:
            em07.append(rec)

    # Sort by recency (most recent first), take top 20 each
    em07.sort(key=lambda r: r["time"], reverse=True)
    em08.sort(key=lambda r: r["time"], reverse=True)
    top_em07 = em07[:20]
    top_em08 = em08[:20]

    print(f"\nEM07 (OB retest): {len(em07)} total, showing top 20 recent")
    for i, c in enumerate(top_em07, 1):
        print(f"  {i}. [{c['direction'].upper()}] {c['zone_bottom']:.3f}-{c['zone_top']:.3f} @ {c['time']} RR={c['rr']:.2f} mitigated={c['mitigated']}")

    print(f"\nEM08 (Breaker retest): {len(em08)} total, showing top 20 recent")
    for i, c in enumerate(top_em08, 1):
        print(f"  {i}. [{c['direction'].upper()}] {c['zone_bottom']:.3f}-{c['zone_top']:.3f} @ {c['time']} RR={c['rr']:.2f} mitigated={c['mitigated']}")

    os.makedirs("backtest/out_strategy_probe", exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "em07_count": len(em07),
        "em08_count": len(em08),
        "em07_setups": top_em07,
        "em08_setups": top_em08,
    }
    with open("backtest/out_strategy_probe/em07_em08_manual_setups.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\nSaved EM07 ({len(top_em07)}) + EM08 ({len(top_em08)}) setups")
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
