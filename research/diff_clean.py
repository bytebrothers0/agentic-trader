"""Clean diff: scout trades vs the LAST tester run's entries only."""
import os
from datetime import timedelta

import pandas as pd

HERE = os.path.dirname(__file__)
scout = pd.read_csv(os.path.join(HERE, "alchemist_trades_best.csv"),
                    parse_dates=["entry_time"])
ea = pd.read_csv(os.path.join(HERE, "ea_last_run_entries.csv"),
                 parse_dates=["time"])
print(f"scout: {len(scout)}  EA: {len(ea)}")

matched_s = 0
for _, s in scout.iterrows():
    d = 1 if s["dir"] > 0 else -1
    near = ea[(ea["dir"] == ("BUY" if d > 0 else "SELL")) &
              ((ea["time"] - s["entry_time"]).abs() <= timedelta(minutes=35))]
    if near.empty:
        print(f"SCOUT ONLY {s['entry_time']} {'BUY' if d>0 else 'SELL'} @{s['entry']:.2f} "
              f"{s['level']} rr={s['rr']:.2f} {s['reason']} R={s['r']:+.2f}")
    else:
        matched_s += 1
print(f"scout matched: {matched_s}/{len(scout)}")
print("---")
matched_e = 0
for _, e in ea.iterrows():
    d = 1 if e["dir"] == "BUY" else -1
    near = scout[(scout["dir"] == d) &
                 ((scout["entry_time"] - e["time"]).abs() <= timedelta(minutes=35))]
    if near.empty:
        print(f"EA ONLY {e['time']} {e['dir']} @{e['entry']:.2f} rr={e['rr']:.2f}")
    else:
        matched_e += 1
print(f"EA matched: {matched_e}/{len(ea)}")
