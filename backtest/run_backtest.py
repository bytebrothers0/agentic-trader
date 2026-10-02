"""
run_backtest.py — CLI for the MSNR walk-forward backtester.

Live MT5 history:
    python backtest/run_backtest.py --symbol XAUUSD --bars 800

Synthetic fallback (no MT5 terminal needed, for smoke-testing the engine):
    python backtest/run_backtest.py --synthetic

Outputs: printed stats + backtest/trades_<symbol>.csv + backtest/equity_<symbol>.csv
"""

import argparse
import os
import sys

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BOT_DIR)
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import pandas as pd  # noqa: E402

from backtest.engine import Backtester  # noqa: E402


def synthetic_data() -> dict:
    """
    Oscillating multi-TF data with real S/R formation (no MT5 needed).
    All timeframes are END-ALIGNED to the same week so HTF storylines have
    depth at every H1 step (staggered starts would starve early steps of
    Weekly/Monthly bars and the engine would correctly — but boringly —
    sit out; live MT5 data is always end-aligned like this).
    """
    import numpy as np

    END = pd.Timestamp("2025-06-01")

    def _mk(periods, freq, trend, amp, wick):
        idx = pd.date_range(end=END, periods=periods, freq=freq)
        base = 2000 + np.linspace(0, trend, periods)
        osc = np.sin(np.linspace(0, 30, periods)) * amp
        o = base
        c = base + osc
        h = np.maximum(o, c) + np.abs(np.cos(np.linspace(0, 30, periods))) * wick + 1.0
        l = np.minimum(o, c) - np.abs(np.cos(np.linspace(0, 30, periods))) * wick - 1.0
        return pd.DataFrame(
            {"open": o, "high": h, "low": l, "close": c, "volume": [1000] * periods},
            index=idx,
        )

    return {
        "MN1": _mk(24, "ME", 60, 30, 10),
        "W1": _mk(60, "W", 60, 22, 8),
        "D1": _mk(150, "D", 40, 16, 6),
        "H4": _mk(500, "4h", 25, 9, 4),
        "H1": _mk(800, "h", 10, 5, 2),
    }


def live_data(symbol: str, bars: int, engine: str = "msnr") -> dict:
    from data.mt5_loader import MT5DataLoader

    loader = MT5DataLoader(symbol=symbol)
    if engine == "ts_m15":
        return {"M15": loader.fetch_timeframe("M15", count=bars)}
    out = {}
    for tf in ["MN1", "W1", "D1", "H4", "H1"]:
        out[tf] = loader.fetch_timeframe(tf, count=bars)
    return out


def main():
    ap = argparse.ArgumentParser(description="MSNR walk-forward backtest")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=800, help="Bars per TF from MT5")
    ap.add_argument("--balance", type=float, default=10_000.0)
    ap.add_argument("--risk", type=float, default=1.0, help="Base risk % per trade")
    ap.add_argument("--step-bars", type=int, default=24, help="Recompute signals every N step bars")
    ap.add_argument("--step-tf", default=None, help="Clock TF (default H1, M15 for ts_m15)")
    ap.add_argument("--engine", default="msnr", choices=["msnr", "ts_m15"],
                    help="Strategy engine to backtest")
    ap.add_argument("--since", default=None, help="Only use bars at/after YYYY-MM-DD")
    ap.add_argument("--synthetic", action="store_true", help="Use generated data (no MT5)")
    args = ap.parse_args()

    if args.synthetic:
        print("Using synthetic data (no MT5).")
        data = synthetic_data()
    else:
        try:
            data = live_data(args.symbol, args.bars, args.engine)
            print(f"Fetched live MT5 history for {args.symbol}.")
        except Exception as e:
            print(f"MT5 fetch failed ({e}); falling back to synthetic data.")
            data = synthetic_data()

    if args.since:
        cutoff = pd.Timestamp(args.since)
        first_idx = next(iter(data.values())).index
        if getattr(first_idx, "tz", None) is not None and cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize(first_idx.tz)
        data = {tf: df[df.index >= cutoff] for tf, df in data.items()}
        print(f"Sliced history from {args.since}: " +
              ", ".join(f"{tf}={len(df)}" for tf, df in data.items()))

    step_tf = args.step_tf or ("M15" if args.engine == "ts_m15" else "H1")
    bt = Backtester(
        data, symbol=args.symbol, initial_balance=args.balance,
        risk_percent=args.risk, step_tf=step_tf, step_bars=args.step_bars,
        engine=args.engine,
    )
    res = bt.run()

    print(f"\n=== {args.engine.upper()} Backtest [{args.symbol}] ===")
    for k, v in res.stats.items():
        print(f"  {k:18s}: {v}")

    if res.trades:
        tdf = pd.DataFrame([{
            "ticket": t.ticket, "model": t.model, "direction": t.direction,
            "lots": t.lots, "entry": round(t.entry, 2), "sl": round(t.sl, 2),
            "tp": round(t.tp, 2), "obstacle": t.obstacle,
            "open_time": t.open_time, "close_time": t.close_time,
            "exit": round(t.exit_price, 2), "pnl": round(t.partial_pnl_usd + t.pnl_usd, 2),
            "reason": t.close_reason,
        } for t in res.trades])
        tpath = os.path.join(BOT_DIR, "backtest", f"trades_{args.symbol}_{args.engine}.csv")
        tdf.to_csv(tpath, index=False)
        print(f"\nTrades ({len(tdf)}):")
        print(tdf.tail(10).to_string(index=False))
        print(f"\nFull log -> {tpath}")
        edf = pd.DataFrame(res.equity_curve)
        epath = os.path.join(BOT_DIR, "backtest", f"equity_{args.symbol}_{args.engine}.csv")
        edf.to_csv(epath, index=False)
        print(f"Equity curve -> {epath}")
    else:
        print("\nNo trades filled in this window (zones never touched or no storylines).")


if __name__ == "__main__":
    main()
