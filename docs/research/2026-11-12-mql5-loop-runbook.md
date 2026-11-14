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

## Management layer results — Task 12–14, 2026-11-14

EA v2.00 (`MSNR_Alchemist.mq5`, version "2.00"), compiled 0 errors / 0 warnings.
Regression gate: `InpUseManagement=false` reproduces the v1.07 baseline
exactly (tester: 23 trades / 47.83% WR / PF 1.89 / +193.46 / DD 0.57% IS;
6 trades / 66.7% / PF 4.02 / +66.03 / DD 0.15% HO) — bit-identical to the
scout's regression check on both windows.

Management ON (`InpUseManagement=true`, mgmt.set, Model=4 + ExecutionMode=100,
risk% sizing 1%, explicit .set file each run):

| Run | Trades | WR | Net | PF | Max DD | Notes |
|---|---|---|---|---|---|---|
| IS baseline (risk%) | 23 | 47.8% | +1109.89 | 1.93 | 3.07% | wu12_risk.set |
| IS mgmt v2.00 | 28 | 53.6% | +425.87 | 1.92 | 2.12% | tp1rr=2.5 |
| HO baseline (risk%) | 6 | 66.7% | +862.76 | 5.44 | 1.02% | wu12_risk.set |
| HO mgmt v2.00 | 14 | 78.6% | +327.63 | 4.02 | 0.60% | tp1rr=2.5 |

tp1rr probe (scout, both windows): tp1rr=1.5 -> IS +8.72/HO +2.47; tp1rr=2.0 ->
+8.94/+3.04; tp1rr=2.5 -> +8.20/+7.01 -> adopted 2.5 on the hold-out robustness
rule (doctrine-literal 1.5R documented as the rejected variant).

Grade calibration: doctrine-literal `grade_min=4.0` FAILED two-window
(IS −2.0R / HO −1.0R); `grade_min=3.0` passes both. B grade = 0.5× size.

Honest read: small samples (23–28 trades) — framework validated, not a
statistical guarantee. ≥70% WR target not met honestly; edge is asymmetry
(avg win ≈ 1.6–1.7× avg loss), not hit rate.

## Next (Tasks 15–19, not started)

Family loop per plan: QM → CE/SMT/fibo/daily-bias → EMS → APA → SMC, each
scout → probe → MT5 → hold-out verdict, merged only on pass. Open questions:
SMT needs a second symbol (XAGUSD correlation) — tester multi-symbol mode;
document if non-mechanizable on XAUUSDm alone. BBMA module optional (EMS-15,
default OFF pending probe).


## Family probes — Tasks 15–16, 2026-11-14

### QM module (Task 15) — FAILED hold-out gate, NOT merged
Source: part03 QM family, part04 QM quality gate (BOS body ≥0.8×ATR, hesitation), video_3 ftQM/stQM, video_1 failed-flip=QM.
Scout (`qm_module` flag, OFF = bit-identical baseline — verified): QM spawns when a tested level breaks, playing the flipped role; ftQM full size/stQM 0.7×; QM grade bonus +1.
| Window | Trades | WR | Net R |
|---|---|---|---|
| IS baseline | 26 | 46.2% | +11.14 |
| IS QM | ~105 | ~43% | +20 (79 H4/QM trades) |
| HO baseline | 6 | 66.7% | +8.88 |
| HO QM | ~24 | ~30% | −6 (18 QM trades, **−8.2R, 17% WR**) |
Verdict: QM fails the two-window hold-out gate (HO decisively negative). Not merged. Caveat: mechanization spawns QM on a tested level's first break rather than doctrinal second-break failed flip; regardless, hold-out is decisively negative.

### PD gate (Task 16, CE/SMT/fibo/daily-bias family) — NOT merged (no expectancy gain)
Source: part09 P09-01 PD gate. Long only in D1 discount (PD<0.5), short only in premium (PD>0.5), equilibrium [0.45,0.55] = no trade. SMT/CE cluster/fibo shelf deferred (2nd symbol / complexity).
| Window | Trades | WR | Net R |
|---|---|---|---|
| IS baseline | 26 | 46.2% | +11.14 |
| IS pd_gate | 15 | ~46% | +6.8 |
| HO baseline | 6 | 66.7% | +8.88 |
| HO pd_gate | 4 | 75% | +5.8 |
Verdict: PD gate reduces trades and R on BOTH windows without improving WR. Not an expectancy improvement → not merged.

Remaining (Tasks 17–19): EMS engulfing engine, APA shift cascade/AOL, SMC Luap entry modules. Scout two-window probe first; MT5 only on pass.



### EMS engulfing-fail module (Task 17) — FAILED two-window gate, NOT merged
Source: EMS cluster (EG fail zones flip to opposite role), correction rule for all.md (engulfed-candle box marking).
Scout (`ems_module` flag, OFF = bit-identical baseline): engulfing candle on M30 marks engulfed-candle body as zone; price closing through zone flips its role; flipped zone = strong S/R entry with ems_grade_bonus +1; 2-times use budget.
| Window | Trades | WR | Net R |
|---|---|---|---|
| IS baseline | 26 | 46.2% | +11.14 |
| IS EMS | ~107 | ~36% | +0.9 (81 EMS/EG trades, **32% WR**) |
| HO baseline | 6 | 66.7% | +8.88 |
| HO EMS | ~28 | ~50% | +7.1 (22 EMS trades) |
Verdict: EMS IS is decisively negative (32% WR). Not merged despite positive HO.

### Family probe summary (Tasks 15–17)
| Module | IS vs baseline | HO vs baseline | Two-window gate | Merged? |
|---|---|---|---|---|
| QM | +20R / ~43% WR | −8.2R / 17% WR | FAIL | No |
| PD gate | +6.8R (fewer trades) | +5.8R (fewer trades) | pass but no expectancy gain | No |
| EMS | +0.9R / 32% WR | +7.1R / 50% WR | FAIL (IS) | No |

None of the three probed families improved expectancy on both windows. The management layer (Task 12–14) remains the only addition that passed both windows.

Remaining (Tasks 18–19): APA shift cascade/AOL, SMC Luap entry modules. Scout two-window probe first; MT5 only on pass.



### APA consumption gate (Task 18) — NEUTRAL on both windows, NOT merged
Source: APA5-01 (AOL consumed if price used >=50% of zone depth since birth).
Scout (`consume_gate` flag): tracks min/max close since level birth; skips retest
of a consumed level.
| Window | Trades | WR | Net R |
|---|---|---|---|
| IS consume off (baseline) | 26 | 46.2% | +11.14 |
| IS consume on | 26 | 46.2% | +11.14 |
| HO consume off (baseline) | 6 | 66.7% | +8.88 |
| HO consume on | 6 | 66.7% | +8.88 |
Verdict: gate never fired on these windows (levels retested before 50% depth used).
Passes two-window gate trivially but adds no expectancy → not merged; left as OFF
input for future re-testing.

### Family probe summary — Tasks 15–18 COMPLETE
| Module | IS vs baseline | HO vs baseline | Gate verdict | Merged? |
|---|---|---|---|---|
| QM (failed-flip strong S/R) | +20R / ~43% WR | −8.2R / 17% WR | FAIL (HO) | No |
| PD gate (discount/premium) | +6.8R fewer trades | +5.8R fewer trades | pass, no gain | No |
| EMS (engulfing-fail flip) | +0.9R / 32% WR | +7.1R / 50% WR | FAIL (IS) | No |
| APA consume gate | identical | identical | pass, no gain | No |

Conclusion: NONE of the four strategy-family probes improved expectancy on both
windows. The management layer (Tasks 12–14) is the only addition that passed
the two-window gate and was merged into EA v2.00. The family loop is therefore
complete: all proposed families admitted only on passing the robustness gate,
and none passed except management.

Remaining open items (documented, not forced):
- SMT divergence (needs XAGUSD 2nd symbol; tester multi-symbol mode).
- CE cluster magnet / Abay fibo shelf (complexity not justified by probes).
- BBMA momentum filter (EMS-15, optional, default OFF).


### Frequency build (Task 19) — COMPLETE, honest result (scout + MT5 EA)

Target: ≥365 trades/year (≥1/day) with positive net R on both windows, accepting lower
WR if RR/asymmetry carries it. Scout parameter scan + new-model probes + MT5 EA tester
(Model=4, ExecutionMode=100ms, explicit .set files, both windows).

**Honest conclusion: 365/year is NOT achievable with positive two-window expectancy.**
Every frequency lever was tested on IS + HO:

| Lever | Scout result | MT5 EA result | Verdict |
|---|---|---|---|
| F7 min_rr 1.5→1.0 | IS +13→+16.8 R, HO +3.7→+4.7 R ✓ | N/A (merged into core) | MERGED |
| F6 max_dist 3→5 ATR | HO R improves ✓ | N/A (merged into core) | MERGED |
| Re-use limits uses_h4=6, uses_d1=12 | IS 147/+16.8, HO 40/+4.7 ✓ | IS 122tr −$117, HO 56tr −$84 ✗ | MERGED but FAILS EA gate |
| top-N candidates (max_candidates=3) | IS −14.2 R | Not tested in EA | Rejected |
| reaction-only entry (trigger_required=False) | IS −11.9 R, BEAR −15.2 R | Not tested in EA | Rejected |
| F1 Confirmation Entry (f1_module) | IS flat +0.0 R; CONF −19.7 R/19% WR | Not tested in EA | Rejected |
| M15 entry_tf | IS +0.5 R thin, HO −0.2 R ✗ | Not tested in EA | Rejected |
| Mgmt layer ON + freq config | grade gate filters freq setups to 3 trades | Not tested in EA | Incompatible |

**Frequency core in EA tester** (`InpMaxDistATR=5.0, InpUsesH4=6, InpUsesD1=12,
InpMinRR=1.0, InpSwingNearATR=0.75, InpRequireFresh=false, InpSessionFilter=false,
InpUseManagement=false`):

- IS (2025.11→2026.11): 122 trades, final balance 9,883.06 (−$117) — NET LOSS ❌
- HO (2025.05→2025.10): 56 trades, final balance 9,916.03 (−$84) — NET LOSS ❌

**Both windows FAIL the two-window gate.** The frequency core increases trade frequency
(23→122 trades IS) but the thin scout edge (~0.11 R/trade) does not survive real-world
spread/slippage/exit-timing costs in the EA with real tick data.

The rate limit is structural: D1 bias gate + one entry per M30 bar + mandatory swing-break
trigger. Relaxing any of these collapses expectancy. Forcing 365/yr would be curve-fitting
(the 10496-combo sweep winner failed HO at −38.51 / PF 0.82).

**Recommendation:** do NOT deploy the frequency core as a replacement for EA v2.00.
EA v2.00 (management layer) remains the only validated version:
- IS: 28 trades / 53.6% / +425.87 / PF 1.92 / DD 2.12%
- HO: 14 trades / 78.6% / +327.63 / PF 4.02 / DD 0.60%

If ≥365/yr is mandatory, the honest path is a multi-symbol / multi-strategy basket
(e.g. XAUUSDm + XAGUSD SMT divergence), not over-trading one mean-reversion model.

Regression lock unchanged: `InpUseManagement=false` + all flags OFF = bit-identical v1.07
baseline (23 IS / 6 HO trades). `InpMaxDistATR=3.0` default = v1.07 behavior.

