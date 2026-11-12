"""Grid probe round 3 — look-ahead-fixed scout. Exploring bias mode,
use budgets, reach window, session window and RR gate."""
import itertools
import sys
import time

import pandas as pd

sys.path.insert(0, r"C:\Users\Hp\Documents\codes\work\trading bot\research")
import alchemist_backtest as ab

START = pd.Timestamp("2025-11-01")
END = pd.Timestamp("2026-11-10")

grid = dict(
    bias_mode=["d1", "d1_h1"],
    uses_h4=[1, 2],
    reach_bars=[6, 12],
    session_end=[20, 16, 21],
    min_rr=[1.0, 1.5],
)
FIXED = dict(require_fresh=False, require_sweep=True, trig_after_touch=8,
             swing_near_atr=1.5, max_dist_atr=3.0, tp_mode="level",
             uses_d1=4, session_start=7)

keys = list(grid)
results = []
t0 = time.time()
for combo in itertools.product(*(grid[k] for k in keys)):
    params = dict(zip(keys, combo))
    params.update(FIXED)
    tr = ab.run(START, END, params)
    if not tr:
        continue
    wins = sum(1 for t in tr if t["reason"] == "WIN")
    tot_r = sum(t["r"] for t in tr)
    results.append((params, len(tr), wins, wins / len(tr), tot_r))
    print(f"bias={params['bias_mode']:5s} uh4={params['uses_h4']} reach={params['reach_bars']:2d} "
          f"sess=7-{params['session_end']:2d} rr={params['min_rr']:.1f} -> n={len(tr)} wins={wins} "
          f"wr={wins/len(tr)*100:.0f}% R={tot_r:+.1f}", flush=True)

print(f"\n=== {len(results)} configs, {time.time()-t0:.0f}s ===")
results.sort(key=lambda r: (r[3], r[4]), reverse=True)
for params, n, w, wr, r in results[:12]:
    print(f"WR {wr*100:5.1f}%  n={n:3d}  R={r:+6.1f}  {params}")
