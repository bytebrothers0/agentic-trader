"""
backtest/scan_em06.py — Find EM06 Displacement BOS + FVG setups from M15 history.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd

from backtest.historical import load_or_fetch
from indicators.bos_detector import BOSDetector, BOSDirection
from indicators.fvg_detector import FVGDetector


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out = "backtest/out_strategy_probe/em06_manual_setups.json"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=500)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    bos_detector = BOSDetector(df, swing_length=25, internal_length=3)
    bos_levels = bos_detector.detect_all()

    fvg_detector = FVGDetector(df)
    fvg_levels = fvg_detector.detect_all()

    # External BOS only, with a fresh FVG from same impulse
    candidates: List[Dict[str, Any]] = []
    for bos in bos_levels:
        if bos.internal:
            continue
        j = int(bos.break_index)
        entry = float(bos.price)

        # Find FVG from same impulse
        fvg_found = None
        for fvg in fvg_levels:
            if fvg.direction.value == bos.direction.value and \
               fvg.formation_index >= bos.extreme_index and \
               fvg.formation_index <= j:
                fvg_found = fvg
                break

        direction = "bullish" if bos.direction is BOSDirection.BULLISH else "bearish"
        atr_series = _atr_series(df, 14)
        atr_val = atr_series[j] if j < len(atr_series) else 0.0
        buffer = 0.25 * (atr_val or 0.0)

        if direction == "bullish":
            stop = entry - buffer
            target = fvg_found.top if fvg_found else entry + (entry - stop) * 2.0
        else:
            stop = entry + buffer
            target = fvg_found.bottom if fvg_found else entry - (stop - entry) * 2.0

        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 3) if risk > 0 else 0.0

        candidates.append({
            "entry_model": "EM06",
            "model_name": "Displacement BOS and FVG retracement",
            "timeframe": timeframe,
            "direction": direction,
            "bos_kind": bos.kind,
            "bos_price": round(float(bos.price), 3),
            "fvg_found": bool(fvg_found),
            "fvg_price": round(float(fvg_found.top), 3) if fvg_found and direction == "bullish" else
                         (round(float(fvg_found.bottom), 3) if fvg_found else None),
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "risk": round(risk, 3),
            "reward": round(reward, 3),
            "rr": rr,
            "time": pd.Timestamp(bos.candle_time).isoformat(),
            "decision_time": pd.Timestamp(df.index[j] + pd.Timedelta(seconds=900)).isoformat(),
            "observation_notes": (
                f"EM06: {bos.kind} {direction} BOS @ {float(bos.price):.3f} "
                f"at {pd.Timestamp(bos.candle_time)}, FVG={'found' if fvg_found else 'none'}"
            ),
        })

    candidates.sort(key=lambda c: c["rr"], reverse=True)
    top20 = candidates[:20]

    print(f"\nFound {len(candidates)} EM06 candidates, showing top 20:\n")
    for i, c in enumerate(top20, 1):
        print(f"  {i}. [{c['timeframe']}] {c['direction'].upper()} EM06 {c['bos_kind']}")
        print(f"      BOS:      @ {c['bos_price']:.3f} at {c['time']}")
        print(f"      FVG:      {'found @ %.3f' % c['fvg_price'] if c['fvg_price'] else 'none'}")
        print(f"      Trade:    entry={c['entry']:.3f}  SL={c['stop']:.3f}  TP={c['target']:.3f}  R:R={c['rr']:.2f}")
        print()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM06",
        "count": len(candidates),
        "setups": top20,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Saved {len(top20)} setups to {out}")
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
