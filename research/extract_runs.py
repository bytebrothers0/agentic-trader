"""Split the MT5 tester agent log into runs and extract the verbose run's
entries + deal results (profit lines) for EA-vs-scout comparison."""
import os
import re

import pandas as pd

HERE = os.path.dirname(__file__)

log_dir = os.path.join(os.environ["APPDATA"], "MetaQuotes", "Tester")
logs = []
for root, _, files in os.walk(log_dir):
    for f in files:
        if f.endswith(".log"):
            logs.append(os.path.join(root, f))
log = max(logs, key=os.path.getmtime)
raw = open(log, "rb").read()
for enc in ("utf-16", "utf-8-sig", "utf-8", "cp1252"):
    try:
        text = raw.decode(enc)
        break
    except (UnicodeDecodeError, UnicodeError):
        continue
lines = text.splitlines()

runs = []
cur = None
for ln in lines:
    m = re.search(r"(\d\d:\d\d:\d\d)\.\d+\tTester\tXAUUSDm,M30.*testing of", ln)
    if m:
        cur = {"start": m.group(1), "entries": [], "deals": []}
        runs.append(cur)
        continue
    if cur is None:
        continue
    if "MSNR ENTRY" in ln:
        d = re.search(r"(\d{4}\.\d\d\.\d\d \d\d:\d\d:\d\d)", ln)
        e = re.search(r"ENTRY (BUY|SELL) @ ([\d.]+) SL ([\d.]+) TP ([\d.]+) RR ([\d.]+)", ln)
        cur["entries"].append((d.group(1) if d else "?", e.groups() if e else ln))
    if "deal #" in ln and ("done" in ln):
        p = re.search(r"at ([\d.]+) done", ln)
        cur["deals"].append(ln.split("\t")[-1][:120])

print(f"log: {log}")
runs = [r for r in runs if r["entries"]]
last = runs[-1]
print(f"LAST run {last['start']}: {len(last['entries'])} entries")
out = pd.DataFrame([dict(time=e[0], dir=e[1][0], entry=float(e[1][1]),
                         sl=float(e[1][2]), tp=float(e[1][3]), rr=float(e[1][4]))
                    for e in last["entries"]])
out.to_csv(os.path.join(HERE, "ea_last_run_entries.csv"), index=False)
print("saved -> research/ea_last_run_entries.csv")
