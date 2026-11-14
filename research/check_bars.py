"""Check M1/OHLC bar availability per year for XAUUSDm (for generated-tick backtests)."""
import os

import MetaTrader5 as mt5

mt5.initialize()
print("connected:", mt5.terminal_info() is not None)
sym = "XAUUSDm"

for year in range(2018, 2027):
    ok = {}
    for tf, name in ((mt5.TIMEFRAME_M1, "M1"), (mt5.TIMEFRAME_M5, "M5"),
                     (mt5.TIMEFRAME_M30, "M30"), (mt5.TIMEFRAME_H4, "H4")):
        r = mt5.copy_rates_range(sym, tf,
                                 __import__("datetime").datetime(year, 7, 15),
                                 __import__("datetime").datetime(year, 7, 17))
        ok[name] = len(r) if r is not None else 0
    print(f"{year}: M1={ok['M1']:5d} M5={ok['M5']:4d} M30={ok['M30']:3d} H4={ok['H4']:2d} bars (Jul 15-17 window)")
mt5.shutdown()
