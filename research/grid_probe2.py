"""Grid probe round 2: sweep-required setups (the confirmed quality gate),
exploring bias mode, reach width and RR."""
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
    max_dist_atr=[3.0, 5.0, 8.0],
    min_rr=[1.0, 1.5],
    swing_near_atr=[0.75, 1.5],
)
FIXED = dict(require_fresh=False, require_sweep=True, reach_bars=12,
             trig_after_touch=8, tp_mode="level")

keys = list(grid)
results = []
t0 = time.time()
for combo in itertools.product(*(grid[k] for k in keys)):
    params = dict(zip(keys, combo))
    params.update(FIXED)
    tr = ab.run(START, END, params)
    if not tr:
        print(f"{params} -> n=0", flush=True)
        continue
    wins = sum(1 for t in tr if t["reason"] == "WIN")
    tot_r = sum(t["r"] for t in tr)
    results.append((params, len(tr), wins, wins / len(tr), tot_r))
    print(f"bias={params['bias_mode']:5s} dist={params['max_dist_atr']:.0f} rr={params['min_rr']:.1f} "
          f"swing={params['swing_near_atr']:.2f} -> n={len(tr)} wins={wins} "
          f"wr={wins/len(tr)*100:.0f}% R={tot_r:+.1f}", flush=True)

print(f"\n=== {len(results)} configs with trades, {time.time()-t0:.0f}s total ===")
results.sort(key=lambda r: (r[3], r[4]), reverse=True)
for params, n, w, wr, r in results[:12]:
    print(f"WR {wr*100:5.1f}%  n={n:3d}  R={r:+6.1f}  {params}")
