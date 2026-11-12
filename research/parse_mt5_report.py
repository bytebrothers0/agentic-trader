"""
parse_mt5_report.py — extract the headline stats + trade table from an MT5
Strategy Tester HTML report into a clean summary + CSV.

Usage: python research/parse_mt5_report.py [path-to-report.htm]
"""
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(__file__)
DEFAULT = os.path.join(
    os.environ["APPDATA"], "MetaQuotes", "Terminal",
    "D0E8209F77C8CF37AD8BF550E51FF075", "MSNR_Alchemist_report.htm")


def text_of(el_html: str) -> str:
    return re.sub(r"<[^>]+>", "", el_html).replace("&nbsp;", " ").strip()


def _read_html(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-16", "utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="ignore")


def parse(path=DEFAULT):
    html = _read_html(path)

    # MT5 report layout: <tr align="right"><td ...>key:</td><td ...><b>value</b></td></tr>
    stats = {}
    for m in re.finditer(
            r"<td[^>]*>([A-Za-z][^<>]{2,60}?):</td>\s*<td[^>]*>\s*(?:<b>)?(.*?)(?:</b>)?\s*</td>",
            html, re.S):
        k, v = text_of(m.group(1)), text_of(m.group(2))
        if k and k not in stats and v:
            stats[k] = v

    # trade rows: <tr class=...><td>...</td></tr> after "Deals"/"Orders" tables
    rows = []
    for trm in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [text_of(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", trm.group(1), re.S)]
        if len(cells) >= 8 and re.match(r"^\d+$", cells[0] or ""):
            rows.append(cells)

    print(f"report: {path}")
    print("-" * 60)
    interesting = [
        "Initial Deposit", "Total Net Profit", "Gross Profit", "Gross Loss",
        "Profit Factor", "Expected Payoff", "Recovery Factor", "Sharpe Ratio",
        "Balance Drawdown Absolute", "Balance Drawdown Maximal",
        "Balance Drawdown Relative", "Total Trades", "Total Deals",
        "Win Trades", "Loss Trades", "Short Trades (won %)",
        "Long Trades (won %)", "Profit Trades (% of total)",
        "Loss Trades (% of total)", "Largest profit trade",
        "Largest loss trade", "Average profit trade", "Average loss trade",
        "Maximum consecutive wins ($)", "Maximum consecutive losses ($)",
    ]
    for k in interesting:
        if k in stats:
            print(f"{k:38s} {stats[k]}")
    if rows:
        cols = ["deal", "time", "symbol", "type", "dir", "volume", "price", "order",
                "commission", "swap", "profit", "balance", "comment"][: len(rows[0])]
        # MT5 deals table layout varies; keep raw strings and salvage numerics
        df = pd.DataFrame(rows)
        out = os.path.join(HERE, "mt5_deals.csv")
        df.to_csv(out, index=False)
        print("-" * 60)
        print(f"deals parsed: {len(df)} rows -> {out}")
    return stats


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    parse(path)
