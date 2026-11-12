"""Parameter grid probe on the scout (fast) — find configs with enough
trades and a win rate toward the 70% target."""
import itertools
import sys
import time

import pandas as pd

sys.path.insert(0, r"C:\Users\Hp\Documents\codes\work\trading bot\research")
import alchemist_backtest as ab

START = pd.Timestamp("2025-11-01")
END = pd.Timestamp("2026-11-10")

grid = dict(
    require_fresh=[False, True],
    require_sweep=[False, True],
    min_rr=[1.0, 1.5, 2.0],
    reach_bars=[12, 24],
    trig_after_touch=[8],
    swing_near_atr=[0.75, 1.5],
    tp_mode=["level"],
)

keys = list(grid)
results = []
t0 = time.time()
for combo in itertools.product(*(grid[k] for k in keys)):
    params = dict(zip(keys, combo))
    tr = ab.run(START, END, params)
    if not tr:
        continue
    wins = sum(1 for t in tr if t["reason"] == "WIN")
    losses = sum(1 for t in tr if t["reason"] == "LOSS")
    tot_r = sum(t["r"] for t in tr)
    results.append((params, len(tr), wins, wins / len(tr), tot_r))
    print(f"{params} -> n={len(tr)} wins={wins} wr={wins/len(tr)*100:.0f}% R={tot_r:+.1f}", flush=True)

print(f"\n=== {len(results)} configs with trades, {time.time()-t0:.0f}s total ===")
results.sort(key=lambda r: (r[3], r[4]), reverse=True)
for params, n, w, wr, r in results[:12]:
    print(f"WR {wr*100:5.1f}%  n={n:3d}  R={r:+6.1f}  {params}")
