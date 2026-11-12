"""
cache_history.py — pull deep XAUUSDm history from the connected MT5 terminal
and cache it to CSV for the offline backtest loop.

Usage: python research/cache_history.py [bars_per_tf]
"""
import os
import sys

import MetaTrader5 as mt5
import pandas as pd

SYMBOL = "XAUUSDm"
OUT_DIR = os.path.join(os.path.dirname(__file__), "data")
TIMEFRAMES = {
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
}

os.makedirs(OUT_DIR, exist_ok=True)


def fetch(tf_name, bars):
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAMES[tf_name], 0, bars)
    if rates is None:
        print(f"{tf_name}: FAILED ({mt5.last_error()})")
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    path = os.path.join(OUT_DIR, f"{SYMBOL}_{tf_name}.csv")
    df.to_csv(path, index=False)
    print(f"{tf_name}: {len(df)} bars  {df['time'].iloc[0]} -> {df['time'].iloc[-1]}  -> {path}")
    return df


def main():
    bars = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    if not mt5.initialize():
        raise SystemExit("MT5 initialize failed")
    print("MT5", mt5.version())
    for tf in TIMEFRAMES:
        n = min(bars, 5_000_000) if tf in ("M5", "M15", "M30") else bars
        fetch(tf, n)
    mt5.shutdown()


if __name__ == "__main__":
    main()
