# MSNR Layered EA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task.

**Goal:** Complete the validated Alchemist MSNR EA with the doctrine's trade-management/psychology layer (A+/A/B/C grading, partials, breakeven, confluence, rule-tolerance) and admit other strategy families (QM, CE, SMT, fibo, EMS, APA, SMC) only if each survives the two-window robustness loop.

**Architecture:** One EA (`mql5/Experts/MSNR_Alchemist.mq5`), layered: strategy module selector + grading engine + management layer (partials/BE) as switchable inputs. Python scouts carry fast research; MT5 Strategy Tester (Model=4 real ticks, ExecutionMode=100, always explicit `.set`) is authoritative. Validation: train 2018–2023, hold-out 2024 untouched, 2025–26 stress test reported separately.

**Resilience & Lifecycle Strategy:**
- *Setup*: EA defaults stay = last validated config until a layer passes; every new input defaults OFF/neutral; scout scripts fail loudly on missing data.
- *Conflict*: `InpOneTrade` guards concurrent entries; composition order fixed: grade gate → entry → partial → BE → TP/SL/time-exit; module selector ensures one strategy logic per bar.
- *Interruption*: all tester runs use `ShutdownTerminal=1`; git commit after every task; results CSVs written before analysis.
- *Cleanup*: partial-close bookkeeping verified in tester (volume math, no ghost orders); scout removes no shared state (fresh `run()` per call); INI files ASCII/no-BOM.
- *Known risk*: Exness real-tick availability for 2018–2023 is unverified — Task 2 probes this first; Model=1 (M1 OHLC) fallback documented per-year if real ticks are absent.

**Spec:** `docs/specs/2026-11-14-msnr-layered-ea-design.md`

---

## Phase 0 — tick-data availability probe

### Task 1: Probe real-tick availability 2018–2023
**Files:**
- Create: `tools/probe_ticks.ps1` (loops years, launches 1-day tester run per year, greps log for "based on real ticks" vs M1 generation)
- Append: `docs/research/2026-11-14-mql5-loop-runbook.md` (tick-availability table)

- [ ] **Step 1:** Write the probe script: for each year 2018..2023, FromDate=Jan01 ToDate=Jan03 of that year, Model=4, Symbol=XAUUSDm, ShutdownTerminal=1, distinct report names.
- [ ] **Step 2:** Run it; for each year read the Tester log line "generating based on real ticks" vs "generating based on M1 bars" (or equivalent).
- [ ] **Step 3:** Record per-year verdict in the runbook: real ticks OK / fallback Model=1 needed. This decides the validation model per window — document, never silently downgrade.
- [ ] **Step 4:** Commit.

## Phase 1 — deep read of strategy_notes (68 md files, strict)

### Task 2: Codification scaffold
**Files:**
- Create: `docs/research/2026-11-14-strategy-notes-codification.md` (per-file template: identity / rules / management-psych / conflicts / overlap)
- Create: `research/strategy_rules.csv` (header: rule_id,file,cluster,concept,definition,params,mechanizable,notes)

- [ ] **Step 1:** Write the scaffold with all 68 filenames listed under their cluster headings, each an empty section.
- [ ] **Step 2:** Commit.

### Task 3: Read part01–part03 (foundations, XAUUSD phases, fresh/storyline/50-method)
**Files:**
- Read fully: `strategy_notes/part01_foundations_snr.md`, `part02_xauusd_phases_snrbasics.md`, `part03_fresh_storyline_50method.md`

- [ ] **Step 1:** Read each file completely (no skimming).
- [ ] **Step 2:** Fill the codification sections: every rule with exact conditions; flag management/psych content (A+/partials/BE/obstacles/confluence/tolerance clauses); log contradictions with the existing EA doctrine.
- [ ] **Step 3:** Append mechanizable rules to `research/strategy_rules.csv`.
- [ ] **Step 4:** Commit.

### Task 4: Read part04–part07 (QM/QMR, OCL/hidden base, trendlines/confluence, CE equilibrium)
Same steps as Task 3 for `part04_quasimodo_qmr_qmm_qmc.md`, `part05_ocl_hiddenbase.md`, `part06_trendlines_confluence_direction.md`, `part07_ce_equilibrium.md`.

### Task 5: Read part08–part11 (SMT/quarterly, daily bias, fibo, entry/TP/SL/psychology)
Same steps for `part08_smt_quarterly.md`, `part09_daily_bias_profile.md`, `part10_fibo_synthesis.md`, `part11_entry_tp_sl_psychology.md`. **part11 is the key file for the management layer — extract partials/BE/A+/tolerance rules verbatim with parameters.**

### Task 6: Read MSNR_Part1–10 (top-down … trade-management psychology)
Same steps for the 10 `MSNR_Part*.md` files. **MSNR_Part10_Trade_Management_Psychology.md is the second key management source — same treatment as part11.**

### Task 7: Read EMS cluster (~20 files)
Same steps for all `*EMS*`/`Eng*` md files + `correction rule for all.md` (read that file FIRST — it may carry cross-cutting rules that qualify the whole EMS series).

### Task 8: Read SMC 15-part course
Same steps for `Part_1_Valid_Pullback_Identification.md` … `Part_15_Real_Chart_Case_Study.md`.

### Task 9: Read APA cluster (5 files)
Same steps for `01_apa_*.md` … `05_apa_entry_modules_and_consumption.md`.

### Task 10: Read video_1–12 + reference.md
Same steps for `video_*.md` (12 files) and `reference.md` (64 KB — read in 2–3 passes).

### Task 11: Overlap map + conflict register + rule inventory freeze
**Files:**
- Edit: `docs/research/2026-11-14-strategy-notes-codification.md` (final sections)
- Edit: `research/strategy_rules.csv` (freeze)

- [ ] **Step 1:** Write the overlap map: which concepts repeat across clusters; canonical source chosen per concept (core wins, variant documented).
- [ ] **Step 2:** Write the conflict register (unresolved contradictions listed explicitly).
- [ ] **Step 3:** Sanity-check: 68/68 sections non-empty; CSV row count matches extracted rules.
- [ ] **Step 4:** Commit.

## Phase 2 — management layer on the Alchemist core

### Task 12: Scout implementation of grading + partials + BE
**Files:**
- Edit: `research/alchemist_backtest.py` (add params: `grade_min`, `partial_enable`, `partial_level`, `partial_pct`, `be_enable`, `be_trigger` — values from part11/MSNR_Part10 doctrine, NOT invented)
- Test: baseline vs baseline+layer on a 3-month window smoke test

- [ ] **Step 1:** Extract the exact doctrine values from the codification doc; write them into the params block with file citations in comments.
- [ ] **Step 2:** Implement grading engine (confluence checklist → A+/A/B/C), risk scaling (B = `grade_b_risk` × risk, C never traded), partial close (volume split, remaining position), BE move at trigger.
- [ ] **Step 3:** Smoke test: 3-month run with layers ON produces trades and doesn't crash; layers OFF reproduces current numbers exactly (regression check).
- [ ] **Step 4:** Commit.

### Task 13: Scout validation on 2018–2023 + 2024 hold-out
**Files:**
- Create: `research/layer_scan.py` (baseline vs each layer alone vs all layers, both windows)

- [ ] **Step 1:** Run the scan (background, it's long).
- [ ] **Step 2:** Record per-layer verdicts: kept if it improves or preserves expectancy with ≤ equal max DD on BOTH windows; else defaulted OFF with the numbers logged.
- [ ] **Step 3:** Commit results + runbook table update.

### Task 14: EA implementation of the management layer
**Files:**
- Edit: `mql5/Experts/MSNR_Alchemist.mq5` (new input group "=== Grading & management ===", OnTick management path, CTrade partial close)
- Edit: `mql5/tester/MSNR_Alchemist.set` + new `MSNR_Alchemist_layered.set`

- [ ] **Step 1:** Implement grade computation, risk scaling, partials, BE mirroring scout logic rule-for-rule (EA parity discipline as before).
- [ ] **Step 2:** Compile (metaeditor64, expect 0 errors/0 warnings).
- [ ] **Step 3:** Real-tick run 2025.11→2026.11 with layers OFF must reproduce the 2026-11-14 validated numbers (regression gate). Record in runbook.
- [ ] **Step 4:** Real-tick runs 2018–2023 train window + 2024 hold-out with the winning layer set (model per Task 1 probe).
- [ ] **Step 5:** Commit.

## Phase 3 — strategy families (each: scout → probe → MT5 → hold-out verdict)

### Task 15: QM/QMR module
- [ ] **Step 1:** Scout `research/qm_backtest.py` from the codified rules (level = broken RBS/SBR flip per doctrine).
- [ ] **Step 2:** Baseline 2018–2023 + probe grid (Python).
- [ ] **Step 3:** MT5 confirmation of operating point; 2024 hold-out verdict.
- [ ] **Step 4:** Verdict + numbers in codification doc; commit.

### Task 16: CE / SMT / fibo / daily-bias batch
Same 4 steps per concept (one scout per concept; batch report in one runbook table). SMT needs a second symbol for divergence — document if data limits make it non-mechanizable on XAUUSDm alone.

### Task 17: EMS module (Engulfing/EG/EF bias)
Same 4 steps; scout `research/ems_backtest.py`.

### Task 18: APA module (liquidity engineering, entry modules)
Same 4 steps; scout `research/apa_backtest.py`.

### Task 19: SMC-course modules (IDM sweep, POI mitigation, top-down)
Same 4 steps; scout `research/smc_backtest.py`. Include Part_13 "SMC Secrets and Tips" tolerance rules in grading input.

### Task 20: Final integration
**Files:**
- Edit: `mql5/Experts/MSNR_Alchemist.mq5` (module selector + merged passing modules, defaults = validated)
- Edit: `docs/research/2026-11-12-mql5-loop-runbook.md` (final ledger), `architecture_index.md`, research doc addenda

- [ ] **Step 1:** Merge surviving modules behind the selector input; defaults = each layer's validated setting.
- [ ] **Step 2:** Full compile + final two-window confirmation runs (Model=4 where ticks allow).
- [ ] **Step 3:** Regression: Alchemist core unchanged with modules OFF.
- [ ] **Step 4:** Update docs; commit; relaunch user's terminal normally; final report with per-layer/per-family verdicts and honest sample-size caveats.

---

**Execution notes for workers:**
- Never touch a running terminal; always launch the tester with an explicit `.set` via `/config` INI (ASCII, no BOM).
- Every claim of "improvement" needs BOTH windows; single-window results are reported as such.
- No strategy/layer is merged without its documented verdict, whatever the user's enthusiasm — that rule is in the spec (§2).
