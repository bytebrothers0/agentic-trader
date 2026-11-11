"""tools/smc_library_compare.py — empirical head-to-head: our detectors vs the
``smartmoneyconcepts`` pip library (joshyattridge, v0.0.27) on the SAME candles.

Not a replacement study — a cross-validation study: where the two agree, both
definitions are likely right; where they disagree, the disagreement usually has
a definitional reason (states, internal/external, body-close rules) worth
naming. Research phase only; nothing here is wired into the agent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SMC_CREDIT", "0")

import pandas as pd

from data.mt5_loader import MT5DataLoader
from smartmoneyconcepts import smc


def _ohlc(loader, tf: str, count: int) -> pd.DataFrame:
    df = loader.fetch_timeframe(tf, count=count, start=0)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    return df[["open", "high", "low", "close", "volume"]], df


def compare(tf: str, count: int = 180) -> None:
    loader = MT5DataLoader(symbol="XAUUSDm")
    loader.connect()
    ohlc, df = _ohlc(loader, tf, count)
    loader.disconnect()

    print(f"=== {tf} | {count} bars | last close {ohlc['close'].iloc[-1]:.3f} ===")

    # --- swings ------------------------------------------------------------
    shl = smc.swing_highs_lows(ohlc, swing_length=50)
    n_swings = int(shl["HighLow"].notna().sum())
    # recency: how many bars back is the most recent confirmed swing?
    swing_idx = shl["HighLow"].dropna()
    last_swing_bars_ago = len(ohlc) - 1 - int(swing_idx.index[-1]) if len(swing_idx) else None
    print(f"[swings] smc-lib: {n_swings} swings (length=50 => 100-bar window), "
          f"most recent confirmed {last_swing_bars_ago} bars ago")

    # --- FVG ---------------------------------------------------------------
    fvg = smc.fvg(ohlc)
    lib_bull = fvg[(fvg["FVG"] == 1) & (fvg["MitigatedIndex"].isna() | (fvg["MitigatedIndex"] == 0))]
    # count all + unmitigated
    n_all = int(fvg["FVG"].notna().sum())
    n_unmit = int((fvg["FVG"].notna() & (fvg["MitigatedIndex"] == 0)).sum())
    print(f"[fvg] smc-lib: {n_all} gaps total, {n_unmit} unmitigated")

    from server import get_indicators
    payload = get_indicators(symbol="XAUUSDm", timeframe=tf.upper(), bars=count, offset=0, show_fvg=True)
    ours = [l for l in payload["levels"] if "FVG" in str(l.get("type", "")).upper()]
    ours_fresh = [l for l in ours if str(l.get("state", "")).upper() in ("FRESH", "UNFRESH")]
    print(f"[fvg] ours:    {len(ours)} gaps total, {len(ours_fresh)} active")

    # overlap check: lib unmitigated tops/bottoms vs our active gap prices
    lib_ranges = [(min(r.Top, r.Bottom), max(r.Top, r.Bottom))
                  for r in fvg[fvg["FVG"].notna() & (fvg["MitigatedIndex"] == 0)].itertuples()]
    matched = 0
    for lo, hi in lib_ranges:
        if any(lo - 0.6 <= l["price"] <= hi + 0.6 for l in ours_fresh):
            matched += 1
    if lib_ranges:
        print(f"[fvg] overlap: {matched}/{len(lib_ranges)} lib-unmitigated gaps fall inside one of our active gaps")

    # --- BOS / CHoCH ---------------------------------------------------------
    bc = smc.bos_choch(ohlc, shl, close_break=True)
    n_bos = int(bc["BOS"].notna().sum())
    n_choch = int(bc["CHOCH"].notna().sum())
    print(f"[bos] smc-lib: {n_bos} BOS + {n_choch} CHoCH (all historical breaks; unbroken levels REMOVED)")

    payload = get_indicators(symbol="XAUUSDm", timeframe=tf.upper(), bars=count, offset=0, show_bos=True)
    ours_b = [l for l in payload["levels"] if l.get("category") == "bos"]
    n_ext = len([l for l in ours_b if not str(l.get("type", "")).startswith("I-")])
    n_int = len([l for l in ours_b if str(l.get("type", "")).startswith("I-")])
    print(f"[bos] ours:    {len(ours_b)} levels ({n_ext} external / {n_int} internal), FRESH ones kept")

    # --- liquidity -------------------------------------------------------------
    liq = smc.liquidity(ohlc, shl, range_percent=0.01)
    n_liq = int(liq["Liquidity"].notna().sum())
    n_swept = int((liq["Swept"] != 0).sum()) if n_liq else 0
    print(f"[liq] smc-lib: {n_liq} equal-level pools ({n_swept} swept by wick/pierce; no body-close rule)")

    payload = get_indicators(symbol="XAUUSDm", timeframe=tf.upper(), bars=count, offset=0, show_liq=True)
    ours_l = [l for l in payload["levels"] if l.get("category") == "liquidity"]
    states = {}
    for l in ours_l:
        states[str(l.get("state", "?")).upper()] = states.get(str(l.get("state", "?")).upper(), 0) + 1
    print(f"[liq] ours:    {len(ours_l)} pools with states {states}")

    # --- what the lib has that we may not -------------------------------------
    phl = smc.previous_high_low(ohlc, time_frame="1D")
    print(f"[pdh/pdl] smc-lib previous D1 high/low: {phl['PreviousHigh'].iloc[-1]:.2f} / {phl['PreviousLow'].iloc[-1]:.2f}")
    retr = smc.retracements(ohlc, shl)
    print(f"[retracement] smc-lib current: {retr['CurrentRetracement%'].iloc[-1]:.1f}% "
          f"deepest: {retr['DeepestRetracement%'].iloc[-1]:.1f}%")


if __name__ == "__main__":
    compare("M15", 180)
    print()
    compare("H4", 180)
