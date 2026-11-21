"""
backtest/scan_em01.py — Find EM01 Classic CRT setups from M15 history.

Simple, clear scan: run the production CRT detector on frozen M15 bars,
print every valid classic CRT with full metadata. No agent involved yet.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from typing import Any, Dict, List

import pandas as pd

from backtest.historical import load_or_fetch, tf_seconds
from backtest.crt_scan import scan_classic_crts, CrtCandidate


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out = "backtest/out_strategy_probe/em01_manual_setups.json"

    print(f"Loading {symbol} {timeframe} history from {cache}…")
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=180)

    if timeframe not in frames:
        print(f"ERROR: no {timeframe} data (have: {sorted(frames)})")
        return 1

    df = frames[timeframe]
    print(f"Loaded {len(df)} {timeframe} bars: {df.index[0]} -> {df.index[-1]}")

    # Scan for classic CRTs that reached target (DISTRIBUTED state)
    candidates = scan_classic_crts(df, timeframe, since=None, min_rr=1.0,
                                   only_distributed=True, top=20)

    print(f"\nFound {len(candidates)} EM01 Classic CRT setups (target reached):\n")

    records: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates, 1):
        rec = {
            "rank": i,
            "entry_model": "EM01",
            "model_name": "Classic CRT sweep and delivery",
            "timeframe": c.timeframe,
            "direction": c.direction,
            "variant": c.variant,
            "state": c.state,
            "anchor_time": c.anchor_time,
            "manipulation_time": c.manipulation_time,
            "distribution_time": c.distribution_time,
            "decision_time": c.decision_time,
            "crh": c.crh,
            "crl": c.crl,
            "swept_level": c.swept_level,
            "target_level": c.target_level,
            "entry": c.entry,
            "stop": c.stop,
            "target": c.target,
            "risk": c.risk,
            "reward": c.reward,
            "rr": c.rr,
            "bars_to_target": c.bars_to_target,
            "inside_bars": c.inside_bars,
            "sweep_amount": c.sweep_amount,
            "range_atr": c.range_atr,
            "outcome": "TP",
        }
        records.append(rec)

        print(f"  {i}. [{c.timeframe}] {c.direction.upper()} CRT")
        print(f"      Anchor:   {c.anchor_time}")
        print(f"      Manip:    {c.manipulation_time}  (decision instant)")
        print(f"      Distrib:  {c.distribution_time}  ({c.bars_to_target} bars to target)")
        print(f"      Range:    {c.crl:.3f} – {c.crh:.3f}  (swept {c.swept_level:.3f})")
        print(f"      Trade:    entry={c.entry:.3f}  SL={c.stop:.3f}  TP={c.target:.3f}  R:R={c.rr:.2f}")
        print()

    # Save
    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM01",
        "count": len(records),
        "setups": records,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Saved {len(records)} setups to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
