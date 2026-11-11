"""Fairness probe: retuned swing_length for the smc library."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SMC_CREDIT", "0")

import pandas as pd
from data.mt5_loader import MT5DataLoader
from smartmoneyconcepts import smc


def probe(tf: str, count: int, swing_length: int) -> None:
    loader = MT5DataLoader(symbol="XAUUSDm")
    loader.connect()
    df = loader.fetch_timeframe(tf, count=count, start=0)
    loader.disconnect()
    df = df.rename(columns={c: c.lower() for c in df.columns})
    ohlc = df[["open", "high", "low", "close", "volume"]]

    shl = smc.swing_highs_lows(ohlc, swing_length=swing_length)
    n_swings = int(shl["HighLow"].notna().sum())
    bc = smc.bos_choch(ohlc, shl, close_break=True)
    n_bos = int(bc["BOS"].notna().sum())
    n_choch = int(bc["CHOCH"].notna().sum())
    liq = smc.liquidity(ohlc, shl, range_percent=0.01)
    n_liq = int(liq["Liquidity"].notna().sum())
    print(f"{tf} x{count} swing_length={swing_length}: swings={n_swings} BOS={n_bos} CHoCH={n_choch} liq_pools={n_liq}")

    if n_bos or n_choch:
        rows = []
        for r in bc[bc["BOS"].notna()].itertuples():
            rows.append(("BOS" + ("+" if r.BOS == 1 else "-"), ohlc.index[r.Index] if hasattr(r, "Index") else "?"))
        for r in bc[bc["CHOCH"].notna()].itertuples():
            rows.append(("CHoCH" + ("+" if r.CHOCH == 1 else "-"), "?"))
        print("   first few:", rows[:4])


if __name__ == "__main__":
    for length in (5, 10, 20):
        probe("M15", 180, length)
    for length in (5, 10, 20):
        probe("H4", 180, length)
