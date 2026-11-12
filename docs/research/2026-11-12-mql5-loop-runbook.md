# MSNR Alchemist MQL5 — Build / Compile / Backtest Loop (runbook)

The research-loop for the mechanical Alchemist MSNR EA. The **MT5 Strategy
Tester is the authoritative backtest engine** (Model=4 "every tick based on
real ticks", ExecutionMode=100 ms simulated order delay — per operator
requirement). The Python validator (`research/alchemist_backtest.py`) is a
fast offline scout of the same rulebook for quick probes only.

## Paths (this machine)

| Thing | Path |
|---|---|
| Terminal | `C:\Program Files\MetaTrader 5\terminal64.exe` (build 6230) |
| MetaEditor | `C:\Program Files\MetaTrader 5\metaeditor64.exe` |
| MetaTester | `C:\Program Files\MetaTrader 5\metatester64.exe` |
| Data folder | `%APPDATA%\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075` |
| Deployed EA | `<data>\MQL5\Experts\MSNR_Alchemist.mq5` (+ `.ex5`) |
| Set files | `<data>\MQL5\Profiles\Tester\MSNR_Alchemist*.set` (deployed from `mql5\tester\`) |
| Tester config | `<data>\MQL5\Files\tester_msnr.ini` (ASCII, **no BOM** — a BOM silently breaks parsing) |
| Reports | `<data>\MSNR_Alchemist_report.htm` + PNGs; parsed by `research/parse_mt5_report.py` |
| Account | Exness-MT5Trial9 demo #477365890, symbol `XAUUSDm` (3 digits) |

## The loop (research → build → compile → backtest → compare)

1. **Edit** the strategy in `mql5\Experts\MSNR_Alchemist.mq5` (repo copy).
2. **Compile + deploy + (single) backtest**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\mql5_build.ps1 -RunTest
   ```
   Closes the running terminal first (the data folder must be free), redeploys,
   compiles, writes the tester INI, launches headless, shuts down when done.
3. **Parse the report**:
   ```powershell
   python research\parse_mt5_report.py
   ```
4. **Parameter sweep** (genetic optimization, custom criterion = win rate ×
   profit factor × √trades, min 10 trades):
   - swept params flagged `Y` in `mql5\tester\MSNR_Alchemist_opt.set`
   - INI template: `Optimization=2`, `OptimizationCriterion=6`
   - see `tools/mql5_build.ps1` paths; launch exactly like step 2 but with
     `tester_msnr_opt.ini`
5. **Validate the winner** with a single Model=4 run (the report above), then
   hold-out: rerun on a date range the sweep never saw before going live.
6. Mirror any logic change into `research/alchemist_backtest.py` and re-run it
   on the same window (`python research\alchemist_backtest.py 2025-11-01 2026-11-10`)
   — Python and EA numbers should stay within M5-vs-real-tick tolerance.

## Tester INI (the operator-mandated execution settings)

```ini
[Tester]
Expert=MSNR_Alchemist
Symbol=XAUUSDm
Period=M30
Model=4              ; 0 Every tick | 1 1-min OHLC | 2 Open prices | 3 Math | 4 REAL TICKS
ExecutionMode=100    ; fixed 100 ms order-execution delay (0 none, -1 random)
Optimization=0       ; 0 single | 2 genetic
OptimizationCriterion=6   ; custom max -> EA OnTester()
FromDate=2025.11.01
ToDate=2026.11.10
Deposit=10000
Leverage=1:100
Report=MSNR_Alchemist_report
ReplaceReport=1
ShutdownTerminal=1
```

## Results so far

| Run | Config | Trades | Win rate | Net | PF | Max DD |
|---|---|---|---|---|---|---|
| v1.00 baseline (2025.11.01→2026.11.10) | defaults, TP=nearest level | 26 | 23.1% | −359.44 (−3.6%) | 0.64 | 4.33% |
| v1.01 sequencing sweep | genetic, custom criterion | running | — | — | — | — |

Baseline diagnosis: the asymmetry is right (avg win ≈ 2.1× avg loss) but the
trigger fired on any minor-swing break near price. v1.01 adds the Alchemist
sequence constraints: **trigger within N bars after the level touch**, the
**broken swing must sit at the level** (≤ X ATR), optional **sweep
requirement** (wick through + close back), and a wider touch-lookback window.
