"""Robustness scan: candidate configs must show positive expectancy on BOTH
the sweep window (in-sample) and the hold-out window (unseen)."""
import sys

import pandas as pd

sys.path.insert(0, r"C:\Users\Hp\Documents\codes\work\trading bot\research")
import alchemist_backtest as ab

INS = (pd.Timestamp("2025-11-01"), pd.Timestamp("2026-11-10"))
HOS = (pd.Timestamp("2025-05-01"), pd.Timestamp("2025-10-31"))

BASE = dict(bias_mode="d1", max_dist_atr=3.0, tp_mode="level",
            require_fresh=False, session_filter=True, session_start=7,
            session_end=20, entry_style="trigger", reach_bars=12)

CANDS = {
    "v105":                    dict(uses_h4=1, uses_d1=2, swing_pivot=3, swing_near_atr=1.5, require_sweep=True,  sl_buf_atr=0.10, min_rr=1.0,  trig_after_touch=8),
    "sweep_winner":            dict(uses_h4=3, uses_d1=4, swing_pivot=4, swing_near_atr=0.5, require_sweep=False, sl_buf_atr=0.20, min_rr=1.25, trig_after_touch=12),
    "mid_2_3":                 dict(uses_h4=2, uses_d1=3, swing_pivot=3, swing_near_atr=1.0, require_sweep=True,  sl_buf_atr=0.15, min_rr=1.25, trig_after_touch=10),
    "winner_plus_sweep":       dict(uses_h4=3, uses_d1=4, swing_pivot=4, swing_near_atr=0.5, require_sweep=True,  sl_buf_atr=0.20, min_rr=1.25, trig_after_touch=12),
    "v105_near05":             dict(uses_h4=1, uses_d1=2, swing_pivot=3, swing_near_atr=0.5, require_sweep=True,  sl_buf_atr=0.10, min_rr=1.0,  trig_after_touch=8),
    "deep_sweep_true":         dict(uses_h4=2, uses_d1=3, swing_pivot=4, swing_near_atr=0.75, require_sweep=True, sl_buf_atr=0.15, min_rr=1.0,  trig_after_touch=12),
    "v105_sess21":             dict(uses_h4=1, uses_d1=2, swing_pivot=3, swing_near_atr=1.5, require_sweep=True,  sl_buf_atr=0.10, min_rr=1.0,  trig_after_touch=8, session_end=21),
    "winner_sess16":           dict(uses_h4=3, uses_d1=4, swing_pivot=4, swing_near_atr=0.5, require_sweep=False, sl_buf_atr=0.20, min_rr=1.25, trig_after_touch=12, session_end=16),
    "v105_uses24":             dict(uses_h4=2, uses_d1=4, swing_pivot=3, swing_near_atr=1.5, require_sweep=True,  sl_buf_atr=0.10, min_rr=1.0,  trig_after_touch=8),
    "winner_uses12":           dict(uses_h4=1, uses_d1=2, swing_pivot=4, swing_near_atr=0.5, require_sweep=False, sl_buf_atr=0.20, min_rr=1.25, trig_after_touch=12),
    "v105_slbuf20":            dict(uses_h4=1, uses_d1=2, swing_pivot=3, swing_near_atr=1.5, require_sweep=True,  sl_buf_atr=0.20, min_rr=1.0,  trig_after_touch=8),
    "mid_deep":                dict(uses_h4=2, uses_d1=4, swing_pivot=4, swing_near_atr=0.75, require_sweep=True,  sl_buf_atr=0.15, min_rr=1.25, trig_after_touch=12),
    "mid_nosweep":             dict(uses_h4=2, uses_d1=2, swing_pivot=3, swing_near_atr=1.0, require_sweep=False, sl_buf_atr=0.15, min_rr=1.0,  trig_after_touch=10),
    "winner_reach9":           dict(uses_h4=3, uses_d1=4, swing_pivot=4, swing_near_atr=0.5, require_sweep=False, sl_buf_atr=0.20, min_rr=1.25, trig_after_touch=12, reach_bars=9),
    "mid_3_3":                 dict(uses_h4=3, uses_d1=3, swing_pivot=4, swing_near_atr=0.75, require_sweep=False, sl_buf_atr=0.20, min_rr=1.25, trig_after_touch=12),
}

results = []
for name, over in CANDS.items():
    params = dict(BASE)
    params.update(over)
    row = {"name": name}
    for tag, (s, e) in (("in", INS), ("ho", HOS)):
        tr = ab.run(s, e, dict(params))
        n = len(tr)
        wins = sum(1 for t in tr if t["reason"] == "WIN")
        tot_r = sum(t["r"] for t in tr)
        row[f"{tag}_n"] = n
        row[f"{tag}_wr"] = (wins / n * 100) if n else 0.0
        row[f"{tag}_R"] = tot_r
    results.append(row)
    print(f"{name:20s} in: n={row['in_n']:3d} wr={row['in_wr']:4.0f}% R={row['in_R']:+6.1f}   "
          f"hold-out: n={row['ho_n']:3d} wr={row['ho_wr']:4.0f}% R={row['ho_R']:+6.1f}", flush=True)

print("\n=== ranked by min(in R, hold-out R) — robustness ===")
for r in sorted(results, key=lambda r: min(r["in_R"], r["ho_R"]), reverse=True):
    print(f"{r['name']:20s} min_R={min(r['in_R'], r['ho_R']):+6.1f}  "
          f"(in {r['in_R']:+6.1f} / ho {r['ho_R']:+6.1f}, trades {r['in_n']}+{r['ho_n']})")
