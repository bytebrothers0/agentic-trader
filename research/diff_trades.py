"""Diff the scout's trades against the EA's tester entries (agent log)."""
import os
import re

import pandas as pd

HERE = os.path.dirname(__file__)

# scout trades
scout = pd.read_csv(os.path.join(HERE, "alchemist_trades_best.csv"),
                    parse_dates=["entry_time"])
# EA entries from the newest agent log
log_dir = os.path.join(os.environ["APPDATA"], "MetaQuotes", "Tester")
logs = []
for root, _, files in os.walk(log_dir):
    for f in files:
        if f.endswith(".log"):
            logs.append(os.path.join(root, f))
log = max(logs, key=os.path.getmtime)
raw = open(log, "rb").read()
for enc in ("utf-16", "utf-8", "cp1252"):
    try:
        text = raw.decode(enc)
        break
    except (UnicodeDecodeError, UnicodeError):
        continue

entries = []
for ln in text.splitlines():
    if "MSNR ENTRY" not in ln:
        continue
    d = re.search(r"(\d{4}\.\d\d\.\d\d \d\d:\d\d:\d\d)", ln)
    e = re.search(r"ENTRY (BUY|SELL) @ ([\d.]+) SL ([\d.]+) TP ([\d.]+) RR ([\d.]+) \| (\w+)/(\w+) lvl ([\d.]+)", ln)
    if d and e:
        entries.append(dict(
            time=pd.to_datetime(d.group(1).replace(".", "-")),
            dir=e.group(1), entry=float(e.group(2)), sl=float(e.group(3)),
            tp=float(e.group(4)), rr=float(e.group(5)),
            tf=e.group(6), kind=e.group(7), lvl=float(e.group(8))))
ea = pd.DataFrame(entries)
print(f"EA entries: {len(ea)}  scout trades: {len(scout)}")

# match by nearest entry_time within 30 minutes and same direction
matched = 0
for _, s in scout.iterrows():
    cand = ea[ea["dir"] == ("BUY" if s["dir"] > 0 else "SELL")]
    if cand.empty:
        continue
    near = cand[(cand["time"] - s["entry_time"]).abs() <= pd.Timedelta(minutes=30)]
    if not near.empty:
        matched += 1
print(f"matched (same dir, <=30min): {matched}")

# list scout trades with NO EA match and vice versa (first 25 each)
ea_times = set()
for _, s in scout.iterrows():
    cand = ea[ea["dir"] == ("BUY" if s["dir"] > 0 else "SELL")]
    near = cand[(cand["time"] - s["entry_time"]).abs() <= pd.Timedelta(minutes=30)]
    if near.empty:
        print(f"SCOUT ONLY: {s['entry_time']} {'BUY' if s['dir']>0 else 'SELL'} "
              f"@{s['entry']:.2f} {s['level']} rr={s['rr']:.2f} {s['reason']}")
print("---")
for _, e in ea.iterrows():
    cand = scout[scout["dir"] == (1 if e["dir"] == "BUY" else -1)]
    near = cand[(cand["entry_time"] - e["time"]).abs() <= pd.Timedelta(minutes=30)]
    if near.empty:
        print(f"EA ONLY: {e['time']} {e['dir']} @{e['entry']:.2f} {e['tf']}/{e['kind']} rr={e['rr']:.2f}")
