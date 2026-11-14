# MSNR Strategy Notes Codification (68 md files)

> Date: 2026-11-14 · Method: strict full read, one file at a time. No inference
> beyond the text; contradictions logged, never silently resolved.
> Companion machine-readable inventory: `research/strategy_rules.csv`.

## Clusters

1. **part01–11** — full MSNR course (foundations → psychology)
2. **MSNR_Part1–10** — compact MSNR series incl. trade-management psychology
3. **EMS** — Engulfing MSNR SMC series (~20 files)
4. **SMC 15-part** — pullback/inducement/OB/IDM course
5. **APA** — Advanced Price Action liquidity course (5 files)
6. **video_1–12 + reference.md** — video notes + long reference

---

## Cluster 1: part01–11

### part01_foundations_snr.md — READ ✔
**Identity:** "ALCHEMIST 02" e-book Part 01 (pages 0–11) by @abayforex. Foundations: SNR zones, liquidity sweep logic, OB/50%, HTF/LTF structure, session behavior. Chart pair: XAUUSD (TradingView).

**Rules (verbatim-anchored):**
- Zone = `SNR line + OB + OB50` — never trigger on SNR line touch alone (Mistake #1).
- Sweep test: `High[i] > PrevHigh AND Close[i] < PrevHigh` (+ wick% threshold); body close beyond `PrevHigh + ATR*0.2` ⇒ breakout, NOT sweep.
- OB = last opposite candle body before impulse; `OB50 = (OB_high+OB_low)/2`; OB reusable if context supports.
- HTF trend (H4 HH/HL vs LH/LL) hard filter; trade with HTF direction; LTF for timing.
- **ConfluenceScore 0–4** (HTF bias / sweep at zone / SNR+OB+50% alignment / confirmation candle); require ≥3, sweep mandatory.
- Sequence enforced: Sweep → Zone touch → Confirmation. Other order = no trade.
- Entry triggers: (1) engulfing / strong rejection wick, (2) close-back-in-range after sweep, (3) touch 50% OB + confirmation.
- Min RR 1:1.5; SL beyond sweep extreme + buffer; TP = next liquidity pool/structure.
- **Tolerance rule:** >3 wick touches without rejection ⇒ zone WEAK ⇒ reduce position size or require stronger confirmation (author: "reduce position size"). ⇒ mechanizable A/B/C anchor.
- Session doctrine: London = manipulation/liquidity-taking; NY = expansion. Avoid mid-consolidation entries without sweep.
- Premium/discount: buys only in discount, sells only in premium of the dealing range; equilibrium (50%) = magnet.
- Zone invalid if: many touches w/o rejection, no sweep, HTF contradicts, body break with momentum.
- Trendline break = EarlyWarning only; entry needs higher-low + break of prior lower high (MSS).
- Sweep line vs resistance line are two levels: wick over sweep line, close under body-close line.

**Management/psych content:** position-size reduction on weak zones; profit-taking (no new entries) in premium for buys; "not every touch creates reversal — sweep raises probability".

**Not covered (deferred):** QM taxonomy (appears p7–8, defined in Part 03), FVG/Fair/IF distinctions, exact session hours, fib-time circles (ignore for entries).

### part02_xauusd_phases_snrbasics.md — READ ✔
**Identity:** pages 12–23: XAUUSD 1H full-cycle eye-training, 7-step bullish playbook, SNR basics, Classic V/A, 4 SNR types, sweep theory (two scopes), fresh/unfresh + storyline + 50-method.

**Rules:**
- SNR drawn at **Close of pivot candle** (not high/low) — resolves line-inside-wick ambiguity.
- Fresh/unfresh v1 (strict): wick touch ⇒ unfresh, UseCount++; body break ⇒ fresh again, UseCount=0, role flip; max 2 uses; **DailyGapException** (gap + strong prior reaction ⇒ reuse without limit).
- **ZoneStrength** = sweep(+1) + retest-hold(+1); ≥2 ⇒ HIGH_RELIABILITY, re-entry allowed on second touch (only if first held).
- Two sweep scopes: **MicroSweep** (previous candle's high/low, LTF confirmation) vs **SwingSweep** (prior swing/equal highs, HTF liquidity). Require ≥1; both ⇒ strongest.
- ClassicV buy: `Close[i-1] < S AND Open[i] >= S-tol AND Close[i] > Open[i]`; ClassicA sell mirrored. Tolerance ATR*0.05; pierce depth < ATR*0.3 else classify as sweep.
- ClassicA no-retest subtype: TouchCount==1 + immediate displacement away + no return within N bars.
- BuyType1: ≥2 rejections at same zone with intervening rally to key level; BuyType2: 0 rejections BUT sweep-before (liquidity-backed); both ⇒ strongest.
- **Premium/discount management:** inhibit new longs above RangeEQ+buffer even if sweep occurs (switch to profit-taking-only mode).
- Target subsystem = opposite liquidity pool (equal highs, prior high, "DRAW"/Profit Point), not fixed RR.
- Storyline multi-TF gate: daily bearish blocks weekly bullish (roadblock doctrine); lower-TF storyline may block higher-TF.
- 50 Method (HIGH_RISK tag): HTF zone touch → LTF (H1/M15) OB50 + sweep → SL ~10 pips; only with HTF bias alignment.
- Accumulation definition (mechanized): range width < ATR×thresh for N bars AND ≥2 sweeps of extremes.
- Label namespaces: BOS_LTF vs BOS_INTERNAL vs BOS_HTF (only HTF BOS flips bias); SWE/Ts/SSL/BSL = liquidity subsystem; MSS/BS!/BMS = structure; CE/C/L/KEY/SNR/MSNR = zone.

### part03_fresh_storyline_50method.md — READ ✔
**Identity:** pages 24–35: fresh/unfresh reconciliation, LL/UL validity band, RBS/SBR flipzone + close-rule, QM/QMR/QMM/QMC module.

**Rules:**
- **Fresh reconciliation (two flags, not one):** `TouchState ∈ {FRESH, WICK_TOUCHED, BODY_TOUCHED}`; tradable iff not BODY_TOUCHED AND UseCount<2 AND sweep done AND in reaction zone. First touch = full size; second wick touch = half size + sweep required; body touch = invalidate unless BreakAndFlip (fresh opposite-side RBS/SBR).
- **LL/UL validity band:** zone = `[LL, UL]` (UL = SNR close line, LL = sweep low/OB low). Buy valid iff `Close > LL` (wick below LL allowed); sell mirrored with UH.
- **FAKE vs BRAKE:** wick pierce + close back inside = FAKE (no flip, trade the reversal); body close beyond + displacement (~range > 1.2×ATR) = BRAKE (flip to RBS/SBR, old line becomes new opposite zone).
- **RBS/SBR close-rule:** flip requires close beyond, not wick break (p29 overrides p28 loose wording). Retest + rejection = entry. XAU worked example: break $2400 → retest RBS → longs with SL just beyond zone (~200–300 points buffer, not fixed $).
- **RBS_Strength** = TF weight (M15=1, H1=2, H4=3, D1=4) + sweep(+1) + OB-align(+1) + FVG-align(+1); require ≥3 for full size.
- QM family: base 4-step (extreme → pullback → weak second extreme → break pullback extreme → retest entry); **QMR** = full reversal playbook, enter only on BOS + retest + rejection, never on the fake leg; **QMM** = single fake break of QML (wick beyond + close back) → fade or enter continuation after trap; if no retest + strong continuation ⇒ momentum note, chase only on retest; **QMC** = fake continuation extreme (liquidity-grab wick) + break of pullback extreme → break-retest entry.
- QM targets: QM level → opposite fresh HTF; SL beyond fake extreme + buffer.

**Management/psych:** "Most enter too early — wait break, then retest. No rushing/chasing" (QMR discipline); "market moves strongly only after most have given up" (QMC mindset); momentum-no-retest handling (QMM).

### part04_quasimodo_qmr_qmm_qmc.md
(pending read)

### part05_ocl_hiddenbase.md
(pending read)

### part06_trendlines_confluence_direction.md
(pending read)

### part07_ce_equilibrium.md
(pending read)

### part08_smt_quarterly.md
(pending read)

### part09_daily_bias_profile.md
(pending read)

### part10_fibo_synthesis.md
(pending read)

### part11_entry_tp_sl_psychology.md
(pending read)

## Cluster 2: MSNR_Part1–10

### MSNR_Part1_Top_Down_Analysis.md
(pending read)

### MSNR_Part2_Market_Structure_BOS.md
(pending read)

### MSNR_Part3_Liquidity_and_Target_Sweeps.md
(pending read)

### MSNR_Part4_Market_Structure_Shift_MSS.md
(pending read)

### MSNR_Part5_Retracements_and_Triggers.md
(pending read)

### MSNR_Part6_Trendlines_and_Confluence.md
(pending read)

### MSNR_Part7_Advanced_Entry_Patterns.md
(pending read)

### MSNR_Part8_Wick_Analysis_and_50_Percent.md
(pending read)

### MSNR_Part9_Refining_Entries_M1_M5.md
(pending read)

### MSNR_Part10_Trade_Management_Psychology.md
(pending read)

## Cluster 3: EMS (Engulfing MSNR SMC)

### correction rule for all.md
(pending read)

### EMS.md
(pending read)

### EMS_ENGULFING_MSNR_SMC_#2.md
(pending read)

### EMS_ENGULFING_MSNR_SMC_#3.md
(pending read)

### EMS_ENGULFING_MSNR_SMC_#4.md
(pending read)

### EMS#ENGULFING #MSNR#SMC#.mp4.md
(pending read)

### _EMS#ENGULFING #MSNR#SMC.mp4.md
(pending read)

### Part_1 EMS#Engulfing #MSNR#SMC.mp4.md
(pending read)

### =EMS#ENGULFING #MSNR#SMC#_8.mp4.md
(pending read)

### _EMS#ENGULFING #MSNR#SMC_10.mp4.md
(pending read)

### EMS#ENGULFING #MSNR#SMC#7.mp4.md
(pending read)

### EMS#ENGULFING #MSNR#SMC#_6.mp4.md
(pending read)

### full strategy for EMS with breakdown of how to use EG and EF for bias part 1#Engulfing #smctrading.md
(pending read)

### full strategy for EMS with breakdown of how to use EG and EF for bias part 2#Engulfing_smctrading.mp4.md
(pending read)

## Cluster 4: SMC 15-part course

### Part_1_Valid_Pullback_Identification.md
(pending read)

### Part_2_Market_Structure_Mapping.md
(pending read)

### Part_3_All_about_Inducement.md
(pending read)

### Part_4_OrderFlows.md
(pending read)

### Part_5_OrderBlocks.md
(pending read)

### Part_6_Valid_Orderblock_Identification.md
(pending read)

### Part_7_Engineering_Liquidity.md
(pending read)

### Part_8_IDM_Sweep_Entry_Module.md
(pending read)

### Part_9_Decisional_POI_Mitigation.md
(pending read)

### Part_10_Eng_LQD_Sweep_Entry_Module.md
(pending read)

### Part_11_Extreme_POI_Mitigation.md
(pending read)

### Part_12_Major_vs_Minor_IDM.md
(pending read)

### Part_13_SMC_Secrets_and_Tips.md
(pending read)

### Part_14_Top_Down_Analysis_Workflow.md
(pending read)

### Part_15_Real_Chart_Case_Study.md
(pending read)

## Cluster 5: APA

### 01_apa_market_overview_and_liquidity.md
(pending read)

### 02_apa_liquidity_engineering_and_levels.md
(pending read)

### 03_apa_areas_of_liquidity_and_types.md
(pending read)

### 04_apa_directional_bias_and_market_shift.md
(pending read)

### 05_apa_entry_modules_and_consumption.md
(pending read)

## Cluster 6: video notes + reference

### video_1.md … video_12.md
(pending read, one section per file)

### reference.md
(pending read)

---

## Overlap map
(pending — completed at Task 11)

## Conflict register
(pending — completed at Task 11)
