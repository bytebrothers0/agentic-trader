"""Parse the MT5 optimization SpreadsheetML report (respecting ss:Index),
rank passes by the custom criterion and print the parameter surface."""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
XML = os.path.join(os.environ["APPDATA"], "MetaQuotes", "Terminal",
                   "D0E8209F77C8CF37AD8BF550E51FF075", "MSNR_opt_report.xml")

SS = "{urn:schemas-microsoft-com:office:spreadsheet}"

import xml.etree.ElementTree as ET

root = ET.parse(XML).getroot()

rows = []
for row in root.iter(SS + "Row"):
    vals = {}
    col = 1
    for cell in row.iter(SS + "Cell"):
        idx = cell.get(SS + "Index")
        if idx is not None:
            col = int(idx)
        data = cell.find(SS + "Data")
        vals[col] = data.text if data is not None else ""
        col += 1
    rows.append([vals.get(i, "") for i in range(1, max(vals) + 1)])

header = rows[0]
df = pd.DataFrame(rows[1:], columns=header)
print(f"passes: {len(df)}  columns: {header}")

num_cols = ["Result", "Profit", "Expected Payoff", "Profit Factor",
            "Recovery Factor", "Sharpe Ratio", "Custom", "Equity DD %", "Trades"]
for c in num_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
for c in df.columns:
    if c.startswith("Inp"):
        cn = c + "_n"
        df[cn] = pd.to_numeric(df[c], errors="coerce")

# top 15 by custom criterion (with a minimum trade count for sanity)
top = df[df["Trades"] >= 10].sort_values("Custom", ascending=False).head(15)
cols = ["Pass", "Custom", "Profit", "Profit Factor", "Trades", "Equity DD %"] + \
       [c for c in df.columns if c.startswith("Inp") and not c.endswith("_n")]
print("\n=== TOP 15 by Custom (WR x PF x sqrt(trades)) ===")
print(top[cols].to_string(index=False))

# parameter response: median custom criterion by each param's value
print("\n=== parameter response (median Custom by value, passes>=10 trades) ===")
for c in [c for c in df.columns if c.startswith("Inp") and not c.endswith("_n")]:
    g = df[df["Trades"] >= 10].groupby(df[c].astype(str))["Custom"].agg(["count", "median", "max"])
    g = g[g["count"] >= 20]
    if len(g) > 1:
        print(f"\n{c}:")
        print(g.to_string())

df.to_csv(os.path.join(HERE, "opt_passes.csv"), index=False)
print("\nsaved -> research/opt_passes.csv")
