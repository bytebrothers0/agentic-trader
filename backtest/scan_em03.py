"""
backtest/scan_em03.py — Find EM03 Liquidity Raid setups from M15 history.

Detects liquidity pools (equal highs/lows) that were taken, then checks for
a structure shift (BOS/CHoCH) after the raid. EM03 = liquidity raid +
reclaim + structure shift.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pandas as pd

from backtest.historical import load_or_fetch
from indicators.liquidity_detector import LiquidityDetector
from indicators.bos_detector import BOSDetector


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out = "backtest/out_strategy_probe/em03_manual_setups.json"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=500)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    # Detect liquidity pools
    liq_detector = LiquidityDetector(df, swing_length=5, eq_tol_atr=0.15,
                                     eq_max_bars=60, min_touches=2,
                                     max_per_side=3, atr_period=14)
    pools = liq_detector.detect_all()
    print(f"Found {len(pools)} liquidity pools total")

    # Detect BOS/CHoCH for structure shift
    bos_detector = BOSDetector(df, swing_length=25, internal_length=3)
    bos_levels = bos_detector.detect_all()

    # Build BOS lookup by break index
    bos_by_break: Dict[int, Any] = {}
    for b in bos_levels:
        bos_by_break[b.break_index] = b

    # Filter: pools that were taken (raid happened)
    taken_pools = [p for p in pools if p.taken]
    print(f"Of which {len(taken_pools)} were taken (raided)")

    records: List[Dict[str, Any]] = []
    for i, pool in enumerate(taken_pools, 1):
        taken_idx = pool.taken_index
        if taken_idx is None or taken_idx >= len(df) - 1:
            continue

        # Look for structure shift after the raid (within 20 bars)
        shift_bos = None
        for bi in range(taken_idx + 1, min(taken_idx + 20, len(df))):
            if bi in bos_by_break:
                shift_bos = bos_by_break[bi]
                break

        j = taken_idx  # decision instant = raid candle close
        entry = float(pool.price)
        atr_val = None

        # Compute simple ATR buffer
        atr_series = _atr_series(df, 14)
        atr_val = atr_series[j] if j < len(atr_series) else 0.0

        if pool.side.value == "buyside":
            # BSL above price was raided -> expect downside move
            stop = float(df["high"].iloc[taken_idx]) + 0.25 * (atr_val or 0.0)
            target = entry - (stop - entry) * 1.5
            direction = "bearish"
        else:
            # SSL below price was raided -> expect upside move
            stop = float(df["low"].iloc[taken_idx]) - 0.25 * (atr_val or 0.0)
            target = entry + (entry - stop) * 1.5
            direction = "bullish"

        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 3) if risk > 0 else 0.0

        rec = {
            "rank": i,
            "entry_model": "EM03",
            "model_name": "Liquidity raid, reclaim and structure shift",
            "timeframe": timeframe,
            "direction": direction,
            "pool_type": pool.liq_type.value,
            "pool_side": pool.side.value,
            "pool_price": round(float(pool.price), 3),
            "pool_size": pool.pool_size,
            "pool_taken": pool.taken,
            "pool_first_index": pool.first_index,
            "pool_last_index": pool.last_index,
            "pool_time": pd.Timestamp(pool.candle_time).isoformat(),
            "taken_index": taken_idx,
            "taken_time": pd.Timestamp(df.index[taken_idx]).isoformat(),
            "decision_time": pd.Timestamp(df.index[j] + pd.Timedelta(seconds=900)).isoformat(),
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "risk": round(risk, 3),
            "reward": round(reward, 3),
            "rr": rr,
            "structure_shift": shift_bos.kind if shift_bos else None,
            "shift_price": round(float(shift_bos.price), 3) if shift_bos else None,
            "shift_time": pd.Timestamp(shift_bos.candle_time).isoformat() if shift_bos else None,
            "state": "DISTRIBUTED" if shift_bos else "LIVE",
            "outcome": "TP" if shift_bos else "OPEN",
            "observation_notes": (
                f"EM03: {pool.side.value} liquidity pool @ {float(pool.price):.3f} "
                f"(size={pool.pool_size}) raided at {pd.Timestamp(df.index[taken_idx])}; "
                f"structure shift: {shift_bos.kind if shift_bos else 'none yet'}"
            ),
        }
        records.append(rec)

        print(f"  {i}. [{timeframe}] {direction.upper()} EM03 Liquidity Raid")
        print(f"      Pool:     {pool.liq_type.value} {pool.side.value} @ {float(pool.price):.3f} (size={pool.pool_size})")
        print(f"      Raided:   {pd.Timestamp(df.index[taken_idx])}")
        print(f"      Shift:    {shift_bos.kind if shift_bos else 'none'} @ {float(shift_bos.price):.3f if shift_bos else 0:.3f}")
        print(f"      Trade:    entry={entry:.3f}  SL={stop:.3f}  TP={target:.3f}  R:R={rr:.2f}")
        print(f"      State:    {'DISTRIBUTED' if shift_bos else 'LIVE'}")
        print()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM03",
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
