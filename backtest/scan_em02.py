"""
backtest/scan_em02.py — Find EM02 Inside-bar CRT setups from M15 history.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Dict, List

import pandas as pd

from backtest.historical import load_or_fetch
from indicators.crt_detector import CRTDetector, CRTVariant


def crt_settings() -> Dict[str, Any]:
    from config import settings as S
    return {
        "min_range_atr": S.CRT_MIN_RANGE_ATR,
        "min_sweep_atr": S.CRT_MIN_SWEEP_ATR,
        "min_close_back_atr": S.CRT_MIN_CLOSE_BACK_ATR,
        "max_inside_bars": S.CRT_MAX_INSIDE_BARS,
        "require_directional_anchor": S.CRT_REQUIRE_DIRECTIONAL_ANCHOR,
        "max_per_side": S.CRT_MAX_PER_SIDE,
        "max_live_per_side": S.CRT_MAX_LIVE_PER_SIDE,
        "atr_period": S.CRT_ATR_PERIOD,
    }


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out = "backtest/out_strategy_probe/em02_manual_setups.json"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=500)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    detector = CRTDetector(df, **crt_settings())
    levels = detector.detect_all()

    # Filter to INSIDE_BAR variant only, any state
    inside_crts = [l for l in levels if l.variant is CRTVariant.INSIDE_BAR]

    print(f"\nFound {len(inside_crts)} EM02 Inside-bar CRT setups:\n")

    records: List[Dict[str, Any]] = []
    for i, lvl in enumerate(inside_crts, 1):
        j = int(lvl.manipulation_index)
        direction = lvl.direction.value
        entry = float(df["close"].iloc[j])
        stop = float(df["low"].iloc[j]) - 0.25 * (lvl.range_atr or 0.0) if direction == "bullish" else float(df["high"].iloc[j]) + 0.25 * (lvl.range_atr or 0.0)
        target = float(lvl.crh) if direction == "bullish" else float(lvl.crl)
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 3) if risk > 0 else 0.0

        rec = {
            "rank": i,
            "entry_model": "EM02",
            "model_name": "Inside-bar CRT expansion",
            "timeframe": timeframe,
            "direction": direction,
            "variant": "inside_bar",
            "state": lvl.state.value,
            "anchor_time": pd.Timestamp(lvl.anchor_time).isoformat(),
            "manipulation_time": pd.Timestamp(lvl.manipulation_time).isoformat(),
            "distribution_time": pd.Timestamp(lvl.distribution_time).isoformat() if lvl.distribution_time else None,
            "decision_time": pd.Timestamp(df.index[j] + pd.Timedelta(seconds=900)).isoformat(),
            "crh": round(float(lvl.crh), 3),
            "crl": round(float(lvl.crl), 3),
            "swept_level": round(float(lvl.swept_level), 3),
            "target_level": round(float(lvl.target_level), 3),
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "risk": round(risk, 3),
            "reward": round(reward, 3),
            "rr": rr,
            "bars_to_target": int(lvl.distribution_index - lvl.manipulation_index) if lvl.distribution_index else None,
            "inside_bars": int(lvl.inside_count),
            "sweep_amount": round(float(lvl.sweep_amount), 3),
            "range_atr": round(float(lvl.range_atr), 3),
            "outcome": "TP" if lvl.state.value == "distributed" else "SL" if lvl.state.value == "invalidated" else "OPEN",
        }
        records.append(rec)

        print(f"  {i}. [{timeframe}] {direction.upper()} Inside-bar CRT")
        print(f"      Anchor:   {pd.Timestamp(lvl.anchor_time)}")
        print(f"      Manip:    {pd.Timestamp(lvl.manipulation_time)}  (decision instant)")
        print(f"      Distrib:  {pd.Timestamp(lvl.distribution_time) if lvl.distribution_time else 'n/a'}")
        print(f"      Range:    {float(lvl.crl):.3f} – {float(lvl.crh):.3f}  (swept {float(lvl.swept_level):.3f})")
        print(f"      Inside:   {int(lvl.inside_count)} bars, sweep={float(lvl.sweep_amount):.3f} pts")
        print(f"      Trade:    entry={entry:.3f}  SL={stop:.3f}  TP={target:.3f}  R:R={rr:.2f}")
        print(f"      State:    {lvl.state.value}")
        print()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM02",
        "count": len(records),
        "setups": records,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Saved {len(records)} setups to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
