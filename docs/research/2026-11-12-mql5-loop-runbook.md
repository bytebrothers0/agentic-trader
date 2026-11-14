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

## Tick-data availability probe (Task 1, 2026-11-14)

**Finding: Exness serves real ticks for XAUUSDm only from 2026-01-01.** Probe
(2-day mid-July windows, per year, Model=4) logged `real ticks begin from
2026.01.01 00:00:00` for every year 2018–2023 — the tester silently falls back
to `every tick generation used` (ticks generated from M1 bars) for older data.

Consequences:
1. **Retroactive label correction:** the earlier "real ticks" runs over
   2025.11→2026.11 were *hybrid* — 2025 portion M1-generated, 2026 portion
   real ticks. The 2025.05→2025.10 hold-out was M1-generated ticks entirely.
   Numbers stand as recorded; the generation mode is now labeled honestly.
2. **2018–2023 training windows** run on M1-generated ticks. M1 bar
   availability (Python API check, Jul 15–17 window): 2022/2024/2025/2026
   full locally; 2018–2021/2023 require on-demand download (tester fetches
   M1 automatically per tested window — first run per year is slow, then
   cached). 2018 needs a warm-up run before trusting a backtest.
3. Validation protocol update: Model=4 + ExecutionMode=100 remains the
   tester config (MT5 auto-falls-back); every result table gains a
   `tick source` column (real vs M1-generated per window).

| Year | Real ticks? | M1 bars | Notes |
|---|---|---|---|
| 2018 | no | on-demand | warm-up run needed |
| 2019 | no | on-demand | |
| 2020 | no | on-demand | |
| 2021 | no | partial local | |
| 2022 | no | yes | |
| 2023 | no | on-demand (partial) | |
| 2024 | no | yes | |
| 2025 | no | yes | earlier hold-out used this |
| 2026 | **yes** | yes | true Model=4 possible |

## Results so far

| Run | Config | Trades | Win rate | Net | PF | Max DD |
|---|---|---|---|---|---|---|
| v1.00 baseline (2025.11.01→2026.11.10) | defaults, TP=nearest level | 26 | 23.1% | −359.44 (−3.6%) | 0.64 | 4.33% |
| v1.01 sequencing sweep | genetic, custom criterion | **aborted** — swept a buggy EA | — | — | — | — |
| v1.02 freshness fix (fresh-only) | replay scans bars AFTER birth | **0** | — | 0.00 | — | 0.00% |
| v1.03 operating point (real ticks) | d1+sweep, 2×/4× budgets, RR≥1.0 | 31 | 38.7% | +13.39 | 1.03 | 2.72% |
| v1.04 closed-bar trigger (real ticks) | forming-bar fix | 58 | 32.8% | −246.93 | 0.69 | 4.90% |
| scout (fixed look-ahead) | same operating point | 70 | 35.7% | +5.36 R | — | — |
| v1.05 trigger+operating point (real ticks) | d1 bias, sweep-gate, uses 1/2, sw=3, RR≥1.0 | 24 | **45.8%** | **+55.16 (+0.55%)** | **1.20** | 1.02% |
| v1.05 hold-out (scout, 2025.05→2025.10) | window untouched by any probe | 4 | 50.0% | +2.58 R | — | — |
| v1.05 genetic refinement (full enumeration) | 10496 combos, Model=4+100 ms | done: 3694 passes | — | — | — | — |
| v1.06 sweep-winner confirmation | uses 3/4, sw=4, near=0.5, no sweep, RR≥1.25 | 63 | 44.4% | +482.41 (+4.8%) | 1.94 | 0.85% |
| v1.06 hold-out (real ticks) | **FAILED to generalize** | 29 | 31.0% | −38.51 | 0.82 | 1.63% |
| v1.05 hold-out (real ticks) | generalizes | 4 | 75.0% | +60.77 | 12.94 | 0.05% |
| dst (deep_sweep_true) confirmation | uses 2/3, sw=4, near=0.75, sweep ON | 66 | 42.4% | +101.02 | 1.10 | 3.02% |
| dst hold-out (real ticks) | **FAILED to generalize** | 21 | 38.1% | −49.20 | 0.75 | 1.35% |
| **wu12 (winner_uses12) FINAL** | uses 1/2, sw=4, near=0.5, slbuf 0.2, RR≥1.25 | **23** | **47.8%** | **+193.46 (+1.9%)** | **1.89** | **0.57%** |
| **wu12 hold-out (real ticks) FINAL** | **positive on unseen data** | **6** | **66.7%** | **+66.03 (+0.66%)** | **4.02** | **0.15%** |

## Final configuration (v1.07 = winner_uses12)

| Input | Value | Rationale (response surface + robustness scan) |
|---|---|---|
| InpBiasMode | 0 (D1-only storyline) | H1 alignment halves volume with no quality gain |
| InpUsesH4 / InpUsesD1 | 1 / 2 | shallow budgets = strictest use of fresh levels; robust on both windows |
| InpStoryPivot | 3 | unchanged baseline |
| InpSwingPivot | 4 | deeper M30 minor swing — the surface's strongest quality lever |
| InpSwingNearATR | 0.50 | the broken swing must sit AT the level (≤0.5 ATR) |
| InpRequireSweep | false | the swing-at-level + pivot-4 constraints subsume it |
| InpReachBars / TrigAfterTouch | 12 / 12 | touch window; weak sequencing cap |
| InpSlBufATR | 0.20 | wider stop buffer beyond the reaction extreme |
| InpMinRR | 1.25 | surface optimum |
| InpTPMode | 0 (nearest opposing level) | fixed RR inferior |
| InpEntryStyle | 0 (trigger confirm) | sweep-sniper entries need unfillable stale prices |
| Session | 07–20 UTC | London/NY |

Real-tick validation (Model=4, ExecutionMode=100 ms): in-sample
2025.11→2026.11: 23 trades, 47.8% WR, +193.46, PF 1.89, DD 0.57%;
hold-out 2025.05→2025.10 (never touched by any sweep): 6 trades, 66.7% WR,
+66.03, PF 4.02, DD 0.15%. **Caveat: 29 total trades is a small sample —
treat the numbers as a validated framework, not a statistical guarantee.
The ≥70% win-rate target is not met honestly; the strategy's edge comes
from the ~1.9–2.2× asymmetry (avg win ≈ 2× avg loss), not hit rate.**

**The hold-out verdict:** the exhaustive sweep's best parameter pocket (63
trades, PF 1.94, +4.8%) is regime-fit — on the unseen May–Oct 2025 window it
loses money (PF 0.82). The v1.05 operating point — which was *not* tuned to
the sweep — is positive on both windows. The lesson stands: parameters tuned
hard to one regime buy in-sample beauty and out-of-sample pain. Final config
selection is decided by `research/robust_scan.py`: candidates must be
positive on BOTH windows.

**Bug log (the loop working as intended):**
1. **v1.00/v1.01 freshness direction bug** — `ReplayLife` mixed chronological
   and series indexing and scanned bars *before* a level's birth, so levels
   stayed wrongly fresh and the trigger fired far too often (26 trades, 23%
   win rate). Found by cross-checking against the Python scout, whose strict
   replay found ~0 valid entries over the same window. v1.02 converts the
   iBarShift series shift to a chronological position and replays forward.
2. **v1.02 teaches the selectivity lesson**: fresh-only (never-touched) is
   so rare that the EA trades zero times in a year. The Alchemist doctrine's
   **2-times (H4) / 4-times (D1) rules** exist for exactly this — a level
   remains usable after wick touches as long as no body close breaks it.
   `InpRequireFresh=false` activates the use budgets.
3. **The tester reuses the last-used inputs** when no `ExpertParameters` is
   given in the INI — the v1.03 year run silently ran OLD defaults (0 trades).
   Always pass an explicit `.set` file.
4. **v1.03/v1.04 forming-bar bugs** — the EA treated the forming M30/H4/D1
   bar as closed: tick-level "swing break" fired entries on wicks. v1.04
   slices the forming bar off every CopyRates use.
5. **The scout had a look-ahead** — it included the forming H4/D1 bar
   (open < decision time) in the book using its FINAL OHLC, i.e. prices up to
   4 h after the decision. After the fix the scout's 59% WR collapsed to
   ~36% and matched the EA — the honest baseline is **~33-36% win rate with
   a small positive edge**. Round-3 probing (grid_probe3.py) hunts filters
   (uses budgets, reach window, session window, RR gate, bias mode) that
   raise the win rate legitimately, before the MT5 genetic refinement.
6. **Scout sweep entries used unfillable stale prices** — the 52% WR sweep
   variant entered at the sweep candle's close whenever one appeared inside
   the 12-bar window. Restricting to the JUST-CLOSED sweep bar (EA parity)
   gives 18 trades / 33% WR / +6.7R (avg RR 4.25). The honest best is the
   **trigger-confirm style: 29 trades, 48.3% WR, +12.1R (+0.42R/trade)** —
   v1.05 implements both styles (`InpEntryStyle` 0=trigger 1=sweep).

## v1.05 validated on real ticks (Model=4 + ExecutionMode=100)

24 trades, **45.8% win rate**, PF 1.20, net +55.16 (+0.55%), max DD 1.02%,
Sharpe 3.08, avg win $30.52 / avg loss $21.58. Parity with the scout holds
(scout: 29 trades / 48.3% — M5-vs-real-tick tolerance). This is the honest
operating point; the genetic refinement (custom criterion WR×PF×√trades,
min 10 trades) is sweeping the gate parameters around it in the MT5 tester.
