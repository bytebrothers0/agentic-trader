# MSNR Strategy Codification & Layered EA — Design Spec

> Date: 2026-11-14 · Status: **DRAFT for user review** · Approach A (doctrine-first, layered merge) approved verbally.

## 1. Goal

Extend the validated mechanical Alchemist MSNR EA (`mql5/Experts/MSNR_Alchemist.mq5`)
with (a) the missing trading-psychology / trade-management layer — A+ setups,
partials, breakeven, obstacles, entry models, confluences, rule-tolerance —
and (b) additional strategy families from `strategy_notes/` (EMS, APA, SMC
course modules, QM, CE, SMT, fibo, …), each admitted **only if it survives the
same research → validate → backtest → refine loop** the Alchemist core went
through. Everything ships as **one EA with switchable layers**.

## 2. Decisions locked (user, 2026-11-14)

| Decision | Choice |
|---|---|
| Architecture | One EA, layered (management layer + optional strategy modules) |
| Source scope | **68 md files in `strategy_notes/` only** (no transcript txt) |
| Validation windows | Train/select 2018–2023 (multi-regime) · hold-out **2024 untouched** · 2025–26 = regime stress test, reported separately |
| Rule tolerance | **A+/A/B/C grading + risk scaling** (grade gates are EA inputs) |
| Admission rule | No layer/strategy is added because the user asked — only on surviving the two-window robustness gate |

## 3. Non-goals

- No transcript `.txt` deep-read (user decision; md files may cite them).
- No multi-strategy mega-EA internals: one strategy module is *active* at a
  time via input selection; modules do not signal simultaneously in v1.
- No live-trading changes: EA remains propose/execute on the demo account;
  magic number 999777 unchanged.

## 4. Current baseline (evidence in hand)

- Final Alchemist config (winner_uses12), real ticks Model=4 + ExecutionMode=100:
  in-sample 2025.11→2026.11: 23 trades / 47.8% WR / PF 1.89 / +1.9% / DD 0.57%;
  hold-out 2025.05→2025.10: 6 trades / 66.7% WR / PF 4.02 / +0.66% / DD 0.15%.
- Known gaps the EA does **not** implement: partials, breakeven, A+ grading,
  confluence scoring, obstacles, rule-tolerance, entry-model variants.
- Tools ready: Python scout (`research/alchemist_backtest.py`, look-ahead-free),
  report parser (`research/parse_mt5_report.py`, UTF-16 aware), optimization
  XML miner (`research/parse_opt_xml.py`), robustness scan
  (`research/robust_scan.py`), history cache 2018→2026 (`research/data/*.csv`).

## 5. Phase 1 — Deep read (strict, no prediction)

Read **every** md file in `strategy_notes/` fully, one by one (68 files,
~520 KB). No skimming, no inferring missing steps, no merging while reading.

Per file, record into `docs/research/2026-11-14-strategy-notes-codification.md`:

1. **File identity**: name, cluster (part01–11 / MSNR_Part1–10 / video / EMS /
   SMC 15-part / APA / reference / correction rule), length.
2. **Rules verbatim-ish**: every stated rule with its exact conditions
   (definitions, thresholds, timeframes, entry/exit, SL/TP, management).
3. **Management & psychology**: partials (where/when/%), breakeven triggers,
   A+ setup criteria, obstacles (what invalidates/weakens a setup), entry
   models (all variants), confluence checklists, discretionary tolerance
   ("rules can bend" clauses) — the user's named gap list.
4. **Conflicts**: where two files contradict (e.g., different 50-method
   readings) — logged, not silently resolved.
5. **Overlap map**: which concepts repeat across clusters (MSNR core is
   re-taught inside EMS/APA/SMC material) — reused once, not re-implemented.

Deliverable: the codification doc + a machine-readable rule inventory
(`research/strategy_rules.csv`: rule id, file, cluster, concept, parameters,
mechanizable yes/no).

## 6. Phase 2 — Management layer on the Alchemist core (first build)

Implement as switchable EA inputs, each individually validated on
2018–2023 + confirmed on the 2024 hold-out:

- **Grading engine**: A+/A/B/C from the doctrine's confluence checklist
  (grade inputs: grade thresholds, checklist items from Phase 1).
- **Risk scaling**: A+ = full risk; A = normal; B = reduced (`InpGradeBRiskPct`,
  default 0.5×) or skip; C = never traded (`InpMinGrade` gate).
- **Partials**: `InpPartialEnable`, partial level & % from doctrine
  (default from `part11` / `MSNR_Part10` — read first, not invented).
- **Breakeven**: `InpBEEnable` + trigger rule from doctrine (e.g., after
  partial / after X R / beyond a structure level).
- Each layer: scout implementation → 2018–2023 backtest vs baseline (no-layer)
  → 2024 hold-out → only kept if it improves or preserves expectancy with
  lower DD; otherwise documented and defaulted OFF.

## 7. Phase 3 — Strategy families (each its own loop)

Order (from cluster independence and user emphasis): MSNR core variants
(QM, CE, SMT, fibo, daily-bias) → EMS → APA → SMC-course modules.

Per family, the same loop as the Alchemist port:

1. Codify rulebook from Phase 1 notes ( scout `research/<family>_backtest.py`,
   look-ahead-free: forming bars excluded everywhere).
2. Baseline backtest 2018–2023 (Python, fast) + probe grid.
3. MT5 real-ticks confirmation of the operating point (Model=4 + 100 ms).
4. Parameter sweep only around the operating point; **selection criterion =
   two-window robustness** (positive expectancy in-sample AND 2024 hold-out).
5. Merge into the EA as a selectable module only on pass; else document fail
   in the codification doc.

## 8. Lifecycle matrix (integrity checklist)

- **Setup**: EA defaults = final validated config; all new layers default to
  the settings that passed validation; sane fallbacks if ATR/history missing
  (skip bar, log reason).
- **Conflict**: `InpOneTrade` already guards concurrent entries; grading and
  management must compose deterministically (defined order: grade gate →
  entry → partial → BE → TP/SL/time-exit). Module selector prevents two
  strategy logics firing on the same bar.
- **Cleanup**: partial closes leave position remnants — verify position
  volume bookkeeping with `InpUseFixedLot=0.01`; no ghost orders; tester
  INI hygiene (ASCII, explicit `.set` always passed).
- **Paradox/edge**: zero levels near price → no trade (existing); grade
  checklist with missing data → grade degrades (never upgrades); M5 gap in
  scout → handled (UnboundLocalError fixed); sweep/optimization pass limits
  on the weak CPU → focused spaces only, full enumeration only where cheap.
- **Interruption**: tester self-shutdown on completion; watchers re-armable;
  all research state committed to git after each milestone (existing practice).
- **Observability**: verbose journal lines for grade, partial, BE events
  (`InpVerbose`); scout CSVs per run; runbook results table appended per run.
- **Testing**: per-layer scout tests (baseline vs baseline+layer), real-tick
  confirmation, hold-out gate, regression check that the untouched Alchemist
  core (layers OFF) reproduces the 2026-11-14 validated numbers.

## 9. Risks (upfront)

- **Small-sample honesty**: 2024 hold-out may again yield few trades for
  selective configs; min-trade floors in criteria, and we report the number.
- **The 70% WR target may remain unmet** — the edge is asymmetry; every
  report states real numbers, never marketing claims.
- **Doctrine contradictions** (e.g., between MSNR core re-taught in EMS vs
  part01–11): resolved by the "core wins, variant documented" rule unless
  backtests say otherwise.
- **Compute**: 2018–2023 is ~6× the previous window; full enumeration sweeps
  are capped; focused genetic sweeps + Python probes carry the load.
- **Broker specificity**: results are Exness-XAUUSDm-specific; revalidation
  required on any live broker before real money.

## 10. Success criteria

1. Codification doc covers 68/68 md files with zero skipped.
2. Management layer validated with per-layer evidence (kept or rejected).
3. Each strategy family has a documented pass/fail verdict with numbers.
4. Final EA: layers switchable, defaults = validated settings, compiles clean,
   core regression reproduced, full ledger committed.

## 11. Deliverables

- `docs/research/2026-11-14-strategy-notes-codification.md` (Phase 1)
- `research/strategy_rules.csv` (rule inventory)
- Scout scripts + results CSVs per family/layer
- Updated `MSNR_Alchemist.mq5` (layered) + `.set` files + runbook entries
- Updated `architecture_index.md` + research doc addenda
