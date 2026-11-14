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

### part04_quasimodo_qmr_qmm_qmc.md — READ ✔
**Identity:** pages 36–47: QM accuracy + hesitation mindset, OC/OCL system, hidden base, MSNR trendlines + zone strength + CE50 + distance, confluence, multi-TF Direction.

**Rules:**
- **QM Quality Gate:** real BOS required (BOS_ATR_ratio ≥0.8); retest delay ≥3 bars; confirmation ∈ {engulfing, pin, OB50+reject}; HTF context check. Otherwise LOW_QUALITY_QM → halve size or skip.
- **Hesitation Mindset (key nuance):** QM ≠ every BOS — real QM forms in *uncertainty* (range contraction, wick increase, equal-touch before BOS). Pure impulsive BOS = trend continuation, not QM. Do not auto-enter.
- OCL = open-close zone `[min(close, nextOpen), max(...)]` of key candles (breakout/strong reversal); break = close beyond + displacement; retest = cleaner entry; S/R+FVG overlap bonus.
- **SessionWeight: Asia=0.5, London=1.0, NY=1.0, Overlap=1.5** — Asia OCL needs extra confirmation (LTF MSS + sweep).
- OC hidden base: two same-color/shape HTF candles (Open/Close clustered within 20-30%) → drill to LTF window → detect OB/V-shape/Accumulation/VolumeShift; trade only if ≥2 sub-elements. Never enter on HTF OC alone.
- Trendlines: build on CLOSES (wick-confirm); ≥3 touches, R²>0.85; equal spacing strongest (`maxGap/minGap < 1.5`); decreasing gaps = exhaustion; anchored only to the 4 main MSNR zones; never force.
- Trendline vs SNR side rule: touches above SNR = strong bullish (buys); below = weak bearish (sells); wicks near SNR confirm.
- Strong zone = liquidity buildup + main+minor trendlines intersecting + CE/SNR + Fib-time align.
- **Confluence definition:** 2–3 factors at the SAME point, SAME direction (side-agreement mandatory — a counter-trend cross is conflict, not confluence). Third vote from {Fibo, OB, Liquidity, QML}.
- **Direction multi-TF law:** "Higher can break lower, lower cannot break higher" — LTF BOS against HTF = internal sweep, not reversal. Formal basis for the storyline gate.
- AMD = Accumulation-Manipulation-Distribution phase tag; sell confluence wants Manipulation→Distribution complete.

### part05_ocl_hiddenbase.md — READ ✔
**Identity:** pages 38–52 re-cover (overlaps part04 §3–5) with harder parameters + repo mapping to existing indicators (`MSNR_OCL` I3, `MSNR_Freshness` I4, `MSNR_EMS_BOS_Sweep` E2, `MSNR_EMS_FVG` E6).

**Rules (adds beyond part04):**
- OCL qualifier: `body_k > 1.5*ATR AND range_k > median(range,50)*1.2` — doji/small bodies rejected (anti-spam).
- OC pair tolerance: `abs(Close[h]-Close[h+1]) < 0.3*ATR` and same color; else not OC.
- **Zone scoring ladder:** entry at wick-level only = grade C (extra sweep required); OCL-only = B (session + MSS); OCL+SNR overlap = A+ (+2). Tradeable if Score ≥4; **A+ if ≥5**.
- Wick poke = still fresh; body close-through + retest = broken/flipped (consistent with part03 BRAKE).
- Keep separate buffers: `Buf_Wick`, `Buf_OCL_Top/Bot/Mid` — never merge wick and OCL layers.
- Hidden-base LTF probe returns flags `hasOB, hasFVG, hasSweep, hasAccum`; score = count; plain micro-range = weak (1), OB+FVG+sweep = strong (3).
- Fib optional (+0.5 score), never required.
- Alerts/log taxonomy: `OCL_Birth/Retest`, `OC_HiddenBaseFound(strength)`.

### part06_trendlines_confluence_direction.md — READ ✔
**Identity:** pages 48–64: [X] Factor confluence, QML SNR+TL triple stack, QMX (QM+TL geometric crossing), trendline distance, confluence builds, Direction hierarchy. Repo: `MSNR_QM_Taxonomy` (abQM/iabQM/ftQM/stQM), E1 engulfing, E9 planner.

**Rules:**
- "A good trendline isn't the perfect one — it's the respected one."
- **QML SNR+TL:** QML + nearest key level (±40pts) + nearest trendline (≥2 touches, ±40pts), sides agree → one of the strongest reversal zones. Entry = rejection candle at confluence.
- **QMX (stricter, +1 score):** trendline geometrically CROSSES the QM/SNR level at point 3 AND engulfing present before point 3 (`EGULF` marks). Both detectors coded separately: `IsQML_TL()` (proximity) vs `IsQMX()` (intersection + engulf).
- Trendline spacing strength: `spacingStd < 0.3*mean(spacing)`; compression into apex + above SNR = strong continuation; expanding/uneven = weakening.
- Confluence builds allow **limit entry without confirmation candle** when the stack is complete (`RequireConfirmationCandle=false` — parameterized; deviation from part01's mandatory candle — log as documented choice).
- Direction hierarchy gate `CanBreak(requestorTF, targetTF)` = requestor ≥ target or HTF flipped.
- Fibo/CE secondary: score boost only, never a gate.
- **Overlap logged:** part04 §6 (pages 42–47) and part06 §1, §6 (pages 53–60) cover the same trendline pages with identical rules — canonical version = this file (adds R²/spacing formulas).

### part07_ce_equilibrium.md — READ ✔
**Identity:** pages 64–78: Candle Equilibrium (CE)/Consequent Encroachment — the 50% core. Repo: extends E5 `MSNR_EMS_PremiumDiscount`.

**Rules:**
- **CE = (High+Low)/2 INCLUDING wicks** (book explicit; body-mid is the OB-mid, a different object).
- Control rules: price above CE of strong bullish candle = buyers in control; body close below = sellers gain; wick poke + close back = hold + entry signal.
- 45–50% zone: price often returns to 45–50% of the range to "check previous strength" before continuing/reversing.
- **Magnet rule:** CE + OB-mid + FVG-mid clustering within 0.2 ATR = price magnet; trade the cluster zone `[min(mids)..max(mids)]` with entry at cluster edge + confirmation; SL beyond cluster + FVG extreme.
- Strong CE filter: `Range > 0.8*ATR AND Body > 0.6*Range AND Body > 0.6*ATR`, born from displacement/engulf/BOS, session ≠ Asia; **chopped CE invalid after 3 crosses in 20 bars** (becomes fair value, not S/R).
- Weak CE: doji/inside-bar/Asia-birth, no confluence, isolated mid → skip or derate.
- Retest pattern: displacement → slow pullback (3–5 small candles) to CE ± 0.15 ATR → rejection wick + close back → entry; impulsive close-through CE = loss of control → flip bias.
- KESIMPULAN: CE = strength measurement + direction confirmation + dynamic S/R + smart-money retest zone + pre-move magnet.

### part08_smt_quarterly.md — READ ✔
**Identity:** pages 78–92: SMT divergence (lie detector) + Quarterly Theory/AMDX (session timer). Neither is entry alone.

**Rules:**
- **SMT = FakeLeg vs TrueLeg classifier, not a signal.** "Always follow the pair that refuses the extreme."
- Four XAU/XAG cases coded: XAU makes LL while XAG holds → bear trap → long XAU; XAU makes HH while XAG holds → bull trap → short; mirrored for XAG-fakes. Compare last two swings within 50-bar lookback, tolerance 0.3 ATR, bars time-aligned ±2.
- **Correlation gate:** allow SMT only if Pearson(returns, 60 bars excluding last 5) > 0.70; else SMT_STATE=NONE.
- Pair whitelist: XAUUSD⇄XAGUSD (primary), EURUSD⇄GBPUSD, USDCAD⇄USDCHF, AUDUSD⇄NZDUSD. Avoid SMT if pairs don't normally correlate.
- SMT entry sequence: identify fake → **wait for close-back-inside (never enter during the fake)** → LTF MSS + OCL/SNR/CE confluence → entry; SL beyond FAKE extreme + 0.3 ATR (not the true leg). Score +1.5 if SMT agrees; **−1.5 (skip or halve) if contradicts**.
- **Quarterly Theory AMDX:** A=accumulation (range, ADX<20), M=manipulation (sweep of A extreme + quick return), D=distribution (displacement body>1.5ATR + BOS), X=reset. Default session map: Asia=A, London=M, NY=D, late-NY=X — but **detect by price, not clock alone**.
- A vs X same shape, opposite meaning — track sequence (A before M, X after D).
- M dip vs real breakdown: M returns quickly + SMT holds + sweep wick; breakdown closes outside + displacement + SMT confirms both.
- Buying Variation filter: deep M (>1.0 ATR) reclaiming within 3–5 M15 bars with NY approaching = variation buy, not sell.
- Timing gates: trade D (NY), signal on M (London); `InpTradeLondonM=false, InpTradeNYD=true`.

### part09_daily_bias_profile.md — READ ✔
**Identity:** pages 92–108: Daily Bias (IRL/ERL selection) + Daily Profiles (London reversal/NY continuation, NY reversal, NY Judas, Seek & Destroy #5). "No bias = no trade, even if pattern looks perfect."

**Rules:**
- ERL = external pools (prior day/week high-low); IRL = internal stepping stones (Asia high/low, FVG mids, OCLs, CE clusters).
- **PD gate:** `PD = (Price−RangeLow)/(RangeHigh−RangeLow)` on D1/H4 dealing range; Premium >0.5, Discount <0.5, Equilibrium 0.45–0.55. Long only in Discount (or Premium + ERL swept + SMT + MSS flip); short mirrored. **Equilibrium = no bias, wait for M.**
- Same BOS means opposite things by PD position: discount BOS = continuation (trade); premium BOS = trap (fade) unless ERL swept.
- **London 02:00–08:30** (times broker-dependent, parameterize): sweep of Asia high/low without displacement = manipulation signal (not entry); London displacement + BOS = trend-day signal → expect NY continuation (Profile 1); both sides swept, no displacement = Seek&Destroy warning → derate size.
- **NY CME 09:30** execution window; M15 = execution lens; NY determines daily close shape.
- **1st vs 2nd Opportunity:** 1st liquidity take is often fake (fade only if SMT diverges + PD extreme); 2nd after retest + MSS = trade.
- **Judas:** spike beyond Asia/London extreme at/after 09:30, wick ratio >0.6, close back inside ≤3 M15 bars, SMT holds → fade opposite on retest of spike CE/OCL; SL beyond Judas extreme +0.3 ATR; TP equilibrium then opposite ERL.
- **Seek & Destroy #5:** `DayRange < 0.7×ATR_D1 AND both sides swept AND no displacement close`; scalp extremes to equilibrium only, **half size**, require SMT + CE/OCL extreme + LTF MSS; SafeTP=EQ, aggressive TP=opposite extreme; disable trend-continuation entries.
- Session inputs: `InpAsiaStart/End (20:00–00:00 Asia range), InpLondonStart=02:00, InpLondonEnd=08:30, InpNYOpen=09:30`.

### part10_fibo_synthesis.md — READ ✔
**Identity:** pages 108–118: custom Abayfx Fibonacci, HTF 6-way confluence shelf, full-system synthesis, EA wiring checklist, THE END (psychology).

**Rules:**
- **Fibo is the ruler, not the reason** — never a gate; +0.5 score if entry within 0.15 ATR of a level.
- Custom levels replace classic 0.5/0.618: entry shelf `1.0–1.55` (with precision `1.47/1.55`), invalidation `−0.72/−0.75/−0.78` (Judas dip shelf; **SL beyond −0.78, not beyond 0**; beyond −0.78 = invalidation), extension TPs `2.235 / 2.6 / 2.82–2.88 / 3.27 / 4–4.733`.
- Anchor rule: Fibo low anchors to **HTF 6-way confluence shelf** (HTF key + OB + RBS + FVG + QMM + classicV), not fractal extreme; skip Fibo if no overlap. `HTF_Score ≥3` to anchor; ≥4 for A+.
- Full-system `CanTrade` checklist: (1) HTF bias + PD + DailyBias agree; (2) sweep done + SMT holds; (3) confluence zone score ≥4 (≥5 full size); (4) session: London=signal, NY=execution, Asia skip/derate, S&D half-size to EQ; (5) confirmation: rejection wick + close-back + LTF MSS (or plan-limit at score ≥5); (6) SL beyond fake/−0.78, TP IRL→ERL→Fibo extension, RR ≥1.5, spread + news filter.
- 12-row master ambiguity table (sweep vs breakout, fresh vs used, Judas vs D, A vs X, premium vs discount BOS, Fibo anchor, session blindness, SMT depth…).
- Closing psychology (author): book is a thinking guide, not absolute rules — "adapt to your own psychology and risk management"; code probabilities + filters + risk, journal profile/score/session/SMT.

### part11_entry_tp_sl_psychology.md — READ ✔ (KEY MANAGEMENT FILE)
**Identity:** synthesis of Parts 01–10 into the codable entry/TP/SL/psychology playbook.

**Entry models A–H catalogue (all of them):**
- A: Bullish/bearish reversal playbook (default; sweep→zone+reject→close-back/LTF-BOS entry, RR ≥1.5)
- B: OCL retest/flip (virgin watch → retest+reject entry; broken+retest = role-flip entry; only displacement candles birth OCL)
- C: QML SNR+TL triple stack (SL beyond QML extreme)
- D: QMX cross (TL × QM intersection + engulf; +1 over C)
- E: CE cluster magnet (cluster edge limit + rejection + LTF MSS; chopped ≥3 crosses = dead)
- F: SMT fade + NY 2nd opportunity (skip 1st, trade 2nd)
- G: Judas/London sweep fade (SL beyond Judas extreme +0.3 ATR)
- H: Trend continuation / Fibo breakout-retest (1.0–1.55 shelf; SL beyond −0.78)

**Confirmation ladder:** virgin touch = watch; 1 confirmation (engulf / close-back / OB50-CE touch+confirm / LTF MSS) = standard entry (score ≥4); 2 confirmations = A+ full size (score ≥5); no confirmation + score ≥5 stack = plan-limit allowed (`PlanEntry=true`).

**SL rules:** beyond fake extreme `±(0.3×ATR + spread×1.5)` — where retail does NOT have stops. Per model: A/B/E sweep extreme +0.2–0.3 ATR; C/D QML/QMX extreme; F/G fake/Judas extreme; H −0.78 shelf. Invalidation exits (no averaging): too many touches, no sweep, HTF contradiction, momentum break. Chopped CE → exit breakeven. LTF 50-method scalp ~10 pips = HIGH_RISK exception with HTF-structure fallback.

**TP ladder:** IRL → ERL → Fibo extensions → HTF key. Trend day holds through EQ; S&D takes EQ only.

**PARTIALS LADDER (the core management layer):**
- TP1 = IRL / 1:1.5 RR → close **50%**, move SL to **breakeven** (`InpMoveToBreakeven=true`)
- TP2 = ERL / Fibo 2.6–2.88 → close **30%**, trail by structure (LTF BOS)
- TP3 = Fibo 3.27-buyside / HTF key → **runner 20%**

**Psychology filters (code what humans cannot):**
- HTF gate, sweep gate (no sweep = no trade), touch-count derate, session gate, SMT veto, spread/news blackout (S&D + high-impact news = no new entries).
- **Daily loss cap: max 2 losses/day or −X% → stop (anti-revenge). Max 1 re-entry per zone (anti-chasing).**
- Score→size: ≥5 = A+ full; 4 = 0.7×; <4 = no trade; S&D caps 0.5×.
- Risk inputs: `InpRiskPercent 0.5–1.0`, `InpMinRR 1.5`, magic 888999 (book's set; our EA keeps 999777).

## Cluster 2: MSNR_Part1–10 (phoenix_mnsr) — READ ✔ (10/10)

**Cluster identity:** "PHOENIX FX" course — MSNR as a precision tight-stop (10 pip) reversal system: top-down H1→M15→M5/M1, state machine (POI → BOS trend → Target Sweep → MSS → premium pullback → trigger). Overlaps the abax cluster's core (sweep/MSS/OCL/RBS/CE concepts) — distinct contributions are the **precision execution layer**, **tolerance buffers**, and **management specifics** below.

### MSNR_Part1_Top_Down_Analysis.md — READ ✔
- H1 = bias/POI layer (swing highs/lows, BSL/SSL pools, OB/FVG); M15 = setup layer; M5/M1 = execution.
- **Core setup sequence on LTF:** continuous BOS (trend) → Target Sweep (BSL pierced + rejected) → MSS (break of the swing low preceding the TS). State machine: State 0 waiting for H1 POI → State 1 monitor LTF.
- Bot: two parallel structure mappers (H1 macro, M15 micro); hierarchical filter — only MSS at high-probability H1 locations.

### MSNR_Part2_Market_Structure_BOS.md — READ ✔
- Swing detection options: fractal (2-candle), N-candle extremum (5/5), ATR-based. **BOS = body close beyond prior swing high** (wick = sweep, not BOS). Momentum filter: breakout body size threshold.
- Trend tracking states: reversal BOS (Change of Character) vs continuation BOS.
- **"Continuous" rule: require ≥2–3 consecutive directional BOS before hunting reversal setups** (prevents trading unstable early structure).
- Psychology: continuous BOS builds retail breakout-buying + stop pools below swing lows = the liquidity the strategy harvests.

### MSNR_Part3_Liquidity_and_Target_Sweeps.md — READ ✔
- Pool taxonomy: single swing highs/lows; **EQH/EQL** (≥2 swing points within 2–3 pips = massive pool); time-based (prev day/week high-low, Asia high/low) mapped at day start.
- **Target Sweep = pierce + rejection:** wick above level + close back below; OR 2–3-candle window rapid reversal (small body close above, engulfed back below). Volume spike optional-confirm.
- IDM (inducement): minor swing below the main POI; setup stronger if IDM swept before POI tap.
- Monitoring phase: pierced level → classify breakout (close beyond + hold) vs sweep (rejection) before priming MSS detection.

### MSNR_Part4_Market_Structure_Shift_MSS.md — READ ✔
- BOS = continuation (with trend); MSS = reversal (against trend, immediately after a TS) = CHoCH.
- **MSS trigger level = the most recent valid swing low before the TS high** (locked at TS confirmation); break requires strong bearish **body close** (wick = just another sweep); impulsive break preferred (measure candle size/time during break).
- 6-state workflow: trend confirm → liquidity map → TS detect → lock MSS level → monitor → confirm.
- False-MSS mitigation: HTF alignment mandatory (M15 MSS at H1/H4 zone, else discount/ignore); displacement required — weak overlapping candles = reduce size or skip.
- Psychology: selling at the TS = catching a falling knife; MSS proves sellers overwhelmed buyers + trapped breakout longs fuel the move.

### MSNR_Part5_Retracements_and_Triggers.md — READ ✔
- After MSS: define range (TS high → post-MSS low); entries only **above 50% (premium for shorts)**; signals below EQ ignored.
- POI = OB (last bullish candle before bearish MSS move) or FVG in the premium zone.
- **Doji trigger:** body < 15% of total range; valid only in premium + at resistance zone (TS level or pre-MSS structural highs).
- **Pre-zone liquidity:** minor swing highs below the main POI; optimal entry = price sweeps them, then immediately taps the main POI.
- **10-pip SL discipline:** SL strictly above TS high or entry-Doji wick + spread buffer; **skip trade if required SL distance > ~15 pips** — the whole RR model depends on tight stops.

### MSNR_Part6_Trendlines_and_Confluence.md — READ ✔
- Trendlines = secondary confluence only (never create the setup; structure + liquidity do).
- Standardized construction: point-to-point across the last 2 valid swing fractals (not regression); project forward; confluence = |TrendlinePrice − ResistanceZone| ≤ tolerance (~3 pips).
- Master trigger upgrade: premium + resistance zone + Doji + trendline intersecting = highest confidence.
- **Trendline liquidity (advanced):** expect smart money to sweep a perfect retail trendline before the true move — look for TS occurring *with* a trendline break = double-trap scenario.

### MSNR_Part7_Advanced_Entry_Patterns.md — READ ✔
- **OCL = Max(Open, Close) of the swing-peak candle** (body, not wick); bodies = accepted value, wicks = sweeps; institutional pullbacks respect OCL lines.
- RBS/SBR lifecycle: breakout above Res1 → potential support; MSS back below → flips to SBR; pullback to SBR = POI.
- **"OCL DOJI RBS" perfect storm:** price at historical flipped level (zone tolerance) + specific OCL (precise tolerance) + Doji on tap = entry. Restrictive by design — quality over quantity.
- Precision rationale: 10-pip stops cannot survive "roughly in the zone" entries.

### MSNR_Part8_Wick_Analysis_and_50_Percent.md — READ ✔
- **Wick tip** = the sweep candle's extreme; primary use = SL a fraction beyond it (violation = thesis invalid); secondary = aggressive POI (100% retrace + Doji at tip = risky valid entry).
- **50% wick rule:** qualifying institutional wick (≥3× body AND during sweep/BOS) midpoint = Wick_50_Level: bullish rejection `Low + (Min(Open,Close)−Low)/2`; bearish `High − (High−Max(Open,Close))/2`.
- Treated exactly like horizontal S/R/OCL; confluence "OCL + 50% wick + TL" = premium entry zone; Doji/rejection at that exact midpoint = trigger.

### MSNR_Part9_Refining_Entries_M1_M5.md — READ ✔
- M1 hunting rule: first clear **M5 IDM**, then find M1 FVG/OB.
- OB definition: last opposite-color candle before displacement that caused structural damage (OBs must be associated with sweeps/BOS — not all OBs valid).
- FVG 3-candle math: bullish `Candle3.Low > Candle1.High`; bearish mirrored.
- M1 sequence: context (M15 TS+MSS+premium) → M5 IDM cleared → nearest M1 FVG/OB → **limit at FVG bottom / OCL of M1 OB** or M1 Doji market entry.
- **Squeeze filter:** ATR of last 5 M1 candles shrinking into the POI = probability up; blasting in with large M1 candles = cancel the order.
- Architecture: EA attached to M1 chart; polls H1/M15/M5 data; handles missing ticks.

### MSNR_Part10_Trade_Management_Psychology.md — READ ✔ (second key management source)
- **"Too accurate" tolerance layer:** zone-based entries (EntryZone = OCL ± 2 pips; trigger inside the band suffices) — prevents missing moves on 0.1-pip misses.
- **Fractional scale-in:** 1/3 at FVG front edge + 1/3 at 50% midpoint + 1/3 at the OCL extreme (catches shallow retracements).
- **TP management:** primary TP = most recent prominent SSL pool (place slightly ABOVE the pool for a short, ensuring fill before bounce).
- **Runner management:** close 50% at first major SSL pool → move SL to **breakeven** → trail remainder behind M15 lower highs (fractal-based structural trail).
- **Reliability threshold:** structure narrative (BOS/TS/MSS) from M15/M5 only; M1 = trigger arm after green light; M1-only signal with bullish M15 = false signal, overruled.
- SMC-confirmed structure integrates best on 5–15 min; below that = more false signals.

## Cluster 3: EMS (ems mnsr) — READ ✔ (14/14)

**Cluster identity:** Engulfing-MSNR-SMC video series. Core engine: HTF engulfing zones (EG) / engulfing-fail zones (EF) as POIs, refined 2 TFs down, executed with LTF sweep+BOS+engulfing trigger. BBMA (Bollinger 20/2 + EMA50 + LWMA5/10 high-low channels) as optional momentum filter.

### correction rule for all.md — READ ✔ (corrections override the video notes)
- **EG-zone correction (overrides EMS#7/_8 "shadow to shadow" marking):** mark the **ENGULFED candle (candle1)**, not the engulfing candle. Box covers candle1 + 3 steps right (candle1, candle2, and the pullback space of the 3rd step) for the entry.
- Timeframes for bot internals: **M15, H1, H4, D1, W1**. Zone marked on W1/D1/H4 → drop **two** TFs (W1→H4, D1→H1, H4→M15) for the SMC setup.
- LTF leg liquidity = low of pullback in the bias leg; must sit **inside the marked box** (else look above/below per bias).
- After liquidity marked → **one TF higher**: nearest key level (OCL/QMR/SNR/RBS/SBR) **below** liquidity for buys / **above** for sells; the key level **must lie inside the marked box** — outside levels never used; when packed, take the one **closest to the liquidity**.
- **Wick-exception rule:** if candle1's bias-side wick (upper for buys reversed logic per text: buys → lower wick side, sells → upper wick side) is longer than candle2's (wick or body close), clamp zone to candle1 BODY + bias-side wick only; box height = the larger of candle1/candle2 wick heights on the bias side; else full candle1 wicks. Prevents outlier-wick inflation.
- **Strict:** valid EG zones form from candles of **opposite colors**.

### EMS.md — READ ✔
- EMS = MSNR + SMC + CRT hybrid. A-shape (swing-high resistance) / V-shape (swing-low support) via fractal detection.
- Bullish engulf: `Close[1] > Open[2] AND Open[1] < Close[2]`; bearish mirrored (body engulf).
- **CRT:** range = reference candle's wick high/low; sweep = `High[i] > RangeHigh AND Close[i] < RangeHigh`; confirm = break AND **close** beyond opposite side of the range.
- SMC 4-event entry: sweep → BOS → internal-liquidity trap → QMR/OB mitigation limit entry.
- Workflow: W1/D1 engulfing rejecting A/V level = bias → H4/D1 OCL/RBS/SBR refine → H1/M15 tap + sweep-BOS-QMR pullback → TP next HTF pool.

### EMS_ENGULFING_MSNR_SMC_#2.md — READ ✔
- After LTF BOS/CHoCH from HTF POI tap, find the **engulfing candle that caused the break**; limit at its **50%** (`Low + (High-Low)*0.5`); SL strictly beyond engulfing-zone extreme.
- 4-state machine: POI tap → LTF BOS → engulf zone → limit at 50%.

### EMS_ENGULFING_MSNR_SMC_#3.md — READ ✔
- Valid range bounded by **strong low** (origin of BOS move) / strong high; violated strong low invalidates range → wait for new setup.
- BOS = body close beyond prior swing's wick; wick-only = sweep (grab) → opposite direction cue.
- Strongest setup: sweep of low then immediate BOS up.
- Sniper entries: HTF zone → LTF unmitigated zone inside it; on HTF tap wait for LTF internal sweep + BOS or fresh engulfing; never blind-enter.
- Chop rule: use the **most recent** valid BOS that occurred **after** a liquidity sweep; if structure messy → go one TF up for cleaner view.

### EMS_ENGULFING_MSNR_SMC_#4.md — READ ✔
- Storyline SBI sequence: **Sweep → BOS → IND** (inducement created and targeted later).
- Entry triggers ranked: engulfing candle, double candles (2 strong same-direction), "stubborn engulfing" (wick-heavy).
- POI = open/close of the engulfing candle or head of wick; enter on retracement tap; SL beyond QMR level; TP = opposing A/V key level (RR up to 1:8–1:13 claimed).
- Invalid engulfing types: engulfing wick ≫ body, or prior candle wick too long → skip or seek double-candle entry.
- Ideal HTF engulf contains its **own internal BOS + sweep** when viewed on LTF — internal structure = strength confirmation.

### EMS#ENGULFING #MSNR#SMC#.mp4.md (part 1) — READ ✔
- Swing structure = the leg that caused a BOS; entry = retrace **back into** the swing-structure zone (not right after BOS); prior structural points = transactional liquidity swept first.
- Ranging vs trending discrimination needed (equal highs/lows count or ADX).

### _EMS#ENGULFING #MSNR#SMC.mp4.md — READ ✔
- POI always 1–2 TFs above execution; **pick the key level nearest to liquidity** (min pip-distance to unmitigated swing).
- **CRT 3-candle:** touch candle → indecision candle (body ≤30% of range, defines Range High/Low) → third candle sweeps range side and closes back → entry toward range low/high.
- Engulfing: candle2 body engulfs candle1 body; limit at engulfed-candle open or engulfing 50% (never market-on-close).

### Part_1 EMS#Engulfing #MSNR#SMC.mp4.md — READ ✔
- HTF rejection valid = tap + **body close beyond** the level (wick tap insufficient).
- **50% retrace mandatory** before entry (Fib 0/0.5/1 on break leg); shorts only above 50% (premium), longs below (discount).
- FVG confluence inside 50%+ zone (gap between wick1 and wick3); not relied on alone.
- EG Fail: engulfing zone broken by close → opposite side pulls into failed zone; zone = engulfed candle body.
- Hack: at 50% with no engulf/FVG → minor A/V key level near EQ → drop to M15 for fresh engulfing sniper entry.

### =EMS#ENGULFING #MSNR#SMC#_8.mp4.md — READ ✔
- HTF engulfing must come from a fresh POI/SNR ("where is price coming from"); drop 2–3 TFs.
- **Zone = full wick range of the ENGULFED candle** (superseded by correction file).
- **BBMA settings (verbatim):** BB(20, 2.0, shift 0, close), EMA50 close, LWMA5 High/Low, LWMA10 High/Low; "directional candlestick" crossing the MA 5/10 channel = momentum confirmation for re-entries.
- POI freshness = zero wick penetrations historically (trace bars).

### -EMS#ENGULFING #MSNR#SMC_10.mp4.md — READ ✔
- Multiple OBs/POIs: choose **closest to liquidity**; if LTF noisy → go HTF for a single Daily OCL.
- Standard model: sweep → BOS → swing range valid **only after BOS** (not fractal-only) → 50% PD filter (sell POI premium / buy POI discount) → internal liquidity (V/A shape) → OCL/Breaker just beyond internal liquidity → 2-TF drop refinement → LTF sweep+BOS confirm.
- **Failed-POI rule:** next deeper level allowed ONLY if still reasonably near the original sweep; too far = abort storyline, wait for fresh sweep+BOS.

### EMS#ENGULFING #MSNR#SMC#7.mp4.md — READ ✔
- BOS: `Close[1] < Low[Swing]` / `Close[1] > High[Swing]`; sweep: wick pierce + body close inside ("Type 2 liquidity").
- POI zone = High-to-Low wick range of reference candle (superseded by correction file).
- **Failed-engulfing zone as future POI:** zones that hit SL become strong S/R for later taps (mechanizable: track EG zones + outcome).
- IRL/ERL: range = most recent major swing H/L; IRL = minor swings inside; TP at exact ERL price.
- Tap definition: `High[0] >= POI_Low` for bearish POI → monitoring state for engulfing close.

### EMS#ENGULFING #MSNR#SMC#_6.mp4.md — READ ✔
- Bias TFs: Weekly/Daily/Monthly; setups: H4/H1/M15.
- **Re-baptizing:** full candle break+close past an unfresh zone = fresh flipped SNR (matches abax BRAKE).
- EG Fail execution: on full-candle break of engulfing zone, wait for pullback INTO the failed zone and trade in the BREAKOUT direction (part2 note: flips to opposite POI — logged as a conflict, resolution below).
- Open-Close SNR when no visible peaks; line-chart V-shape detection = close-only swing detection.
- Gann box 50% = PD split; discount for buys, premium for sells.
- BBMA re-entry + momentum candle crossing MAs = confirmation.

### full strategy for EMS with breakdown of how to use EG and EF for bias part 1 — READ ✔
- EG mechanic: after valid EG, price pulls back into **engulfed-candle zone** then continues with the engulf direction.
- EF mechanic: zone broken → pullback into failed zone acts as reversal POI (RBS/SBR flip).
- Key levels: A-shape, V-shape, OCL, QMR; rejection confirmed only by body close beyond level after tap.
- Bias protocol: Weekly rejection first; if none → Daily.
- Entry flow: HTF bias → 4H engulfing in bias direction → 15m/30m pullback into 4H engulf zone → LTF sweep + BOS (or 1H engulfing as final trigger) → limit/market into unmitigated LTF OB/OCL/engulf zone → SL beyond structural swing with breathing room.
- **Liquidity-vs-depth rule:** if clear liquidity sits before the entry zone, no need to wait for deep premium/discount; if no obvious liquidity, expect deeper pullback to PD/extreme.

### full strategy for EMS ... part 2 — READ ✔
- Marking rule (pre-correction): cover full engulfing candle; if engulfed wick longer, cover the longer wick; instructor prefers tighter POI within valid BOS zone.
- **EF flip:** failed bullish engulfing = bearish POI; failed bearish = bullish POI (track zone state machine: ACTIVE→FAILED→FLIPPED).
- MTF: HTF POI tap → LTF confirmation = sweep + BOS/CHoCH + new LTF engulfing trigger → limit at LTF engulfing open/50%; SL beyond sweep/engulfing wick.
- **Sweep-before-POI requirement:** POI reached without prior liquidity sweep = lower probability (gate).
- **Third-candle exception:** entry may come at candle 4, 5+; never invalidate an engulfing zone just because candle 3 didn't retest (valid while BOS/liquidity intact).

**EMS conflicts registered:**
1. Zone marking: video notes "engulfing candle high-to-low" (part 8, 7, part2-part1) vs correction file "engulfed candle + 3-step box + wick-clamp" — **correction file wins** (it is explicitly labeled as corrections).
2. EG-fail direction: `_6` says trade breakout direction at pullback; part2 says failed zone flips to opposite-direction POI — both describe the same RBS/SBR flip; canonical = zone flips role; trade on retest respecting new role (i.e., breakout-direction continuation = same thing from the other side). Documented, no code conflict.
3. BBMA present in _8/_6, absent elsewhere → optional module, default OFF until probe says otherwise.

## Cluster 4: SMC 15-part / "True SMC (Luap)" (luap smc) — READ ✔ (15/15)

**Cluster identity:** Fully mechanical SMC framework, candle-range-based (no indicators). Chain: Valid Pullback → IDM → sweep → confirmed swing → BOS/CHoCH → POI hierarchy (Extreme OF/OB/Wick > Decisional > Eng LQD = trap) → Entry Modules 1/2/3. This is the most mechanizable course in the whole set.

### Part_1_Valid_Pullback_Identification.md — READ ✔
- **Valid Pullback (bullish):** target candle = candle making current Highest High; pullback confirmed when a later candle's **wick OR body breaks the target candle's LOW**; if instead its high is broken, target shifts to the new HH (reset check). Bearish mirrored.
- **Inside-bar rule:** inside candle = non-event; the Mother candle's extreme is the reference.
- Trap: many small "down" candles that never break the HH candle's low = single leg, NOT a pullback.
- Confirmed pullback = the next step's IDM.

### Part_2_Market_Structure_Mapping.md — READ ✔
- **Swing confirmation requires IDM sweep:** new high is TEMPORARY until the first valid pullback low (IDM) is swept; only then = Confirmed HH.
- **BOS = body close beyond a confirmed swing point** (wick above = liquidity sweep, not BOS).
- **CHoCH = body close through the LAST PROTECTED higher low (bull→bear)** — the low that caused the last BOS.
- Trading Range = confirmed HH ↔ protected HL.

### Part_3_All_about_Inducement.md — READ ✔
- IDM = extreme of the **first/most-recent valid pullback** below the temporary high (bullish).
- IDM sweep (wick or body) ⇒ confirm prior extreme + establish range.
- **IDM shifting:** new extreme without sweeping IDM ⇒ IDM moves to the newest valid pullback.
- Reaction before IDM sweep = likely SMT → do not enter, wait for IDM.

### Part_4_OrderFlows.md — READ ✔
- **OrderFlow = container:** after bullish BOS, the last bearish sequence before the break — box from High of first red candle to Low of last red candle; bearish mirrored.
- Mitigation filter: any return into the OF (wick tap counts) = mitigated → next unmitigated OF or refine to Extreme.
- OBs only work inside a valid unmitigated OrderFlow.

### Part_5_OrderBlocks.md — READ ✔
- Valid OB checklist: (1) **FVG** between OB candle and 3rd candle of the move; (2) **unmitigated**; (3) bonus: OB candle itself swept prior high/low.
- Extreme OB = at start of move; Decisional OB = near IDM.
- No FVG above/below ⇒ "Engineered OB"/SMT → ignore.

### Part_6_Valid_Orderblock_Identification.md — READ ✔
- Liquidity-grab filter: OB candidate must sweep previous candle's extreme; no sweep = Weak OB, avoid.
- FVG filter: gap in the next 2 candles required; slow all-touching move = efficiency, invalid.
- Mitigation refinement: body mitigated but wick unmitigated → **refine entry to 50% of the wick**.
- Hidden OB: tiny opposite candle whose wick pokes beyond the big impulse candle = valid OB.

### Part_7_Engineering_Liquidity.md — READ ✔
- **Eng LQD = valid pullback formed between IDM and the Extreme POI** (fake OB/SNR retail loves).
- Price approaching Extreme **must sweep Eng LQD first**; sweep of Eng LQD + tap of Extreme = highest-probability setup.
- Respect of Eng LQD without reaching Extreme = lower-probability Decisional move.
- Trendline liquidity = engineered liquidity; wait for its sweep into unmitigated OF.
- Never enter at Eng LQD itself.

### Part_8_IDM_Sweep_Entry_Module.md — READ ✔ (Module No.1)
- Trigger: candle wicks through IDM and **closes back inside** previous range.
- Entry trigger: subsequent candle breaks the sweeping candle's High/Low (displacement); patterns = engulfing or long-wick pin bar.
- **Body close through IDM = NOT a sweep** → potential trend change; cancel Module 1, wait for deeper mitigation.
- SL 2–3 pips beyond sweep wick extreme; TP = external liquidity (leg target).

### Part_9_Decisional_POI_Mitigation.md — READ ✔
- Decisional POI = first unmitigated OB/OF where the most recent BOS push started.
- **IDM filter:** no inducement before the Decisional = invalid/SMT; clear IDM sweep into it = valid.
- Tapped + reversal = mitigated; reaction fails and breaks through → market heading for Extreme.
- **Risk ladder: 0.5% at Decisional, 1% at Extreme.**

### Part_10_Eng_LQD_Sweep_Entry_Module.md — READ ✔ (Module No.3, highest probability)
- Setup: Eng LQD (last pullback) between Decisional and Extreme; price wicks through Eng LQD and **immediately taps the Extreme OF/OB**.
- Trigger: rejection/displacement back above the Eng LQD level; limit at the Extreme acceptable on strong sweep (no LTF CHoCH needed).
- SL exactly beyond the Extreme POI (absolute range extreme); TP = external liquidity; target 1:5+ RR.
- Extreme reached **without** sweeping Eng LQD = caution (possible deeper mitigation).

### Part_11_Extreme_POI_Mitigation.md — READ ✔
- Extreme refinement hierarchy: **unmitigated Extreme OF → unmitigated Extreme OB (with FVG) → unmitigated OB wick → last extreme candle (the wick)**.
- All mitigated = leg fully mitigated = high risk, skip.

### Part_12_Major_vs_Minor_IDM.md — READ ✔
- **Minor IDM = pullback before BOS; Major IDM = pullback after BOS** (in the new leg).
- Major IDM sweep ⇒ ~70–80% reversal; Minor IDM sweep ⇒ ~50%, often goes deeper.
- In complex ranges: the highest/lowest Major IDM = ultimate liquidity target before the Extreme.
- Risk scaling: Major sweep = full risk (1%); Minor = light risk/scalp only.

### Part_13_SMC_Secrets_and_Tips.md — READ ✔
- **Protected high/low** = swing that caused a BOS; break = CHoCH. **Weak/targeted high/low** = failed to take IDM or BOS; expect sweep, never place stops there.
- **Single-leg trap:** many small candles one direction without breaking a prior candle extreme = one unit, no internal structure.

### Part_14_Top_Down_Analysis_Workflow.md — READ ✔
- Workflow: H1 map (BOS/CHoCH/IDM → range) → mark unmitigated Decisional+Extreme OFs → halt execution until tap → LTF (M1/M5): find LTF Major IDM → **LTF CHoCH = body-close break of LTF Major IDM** → enter.
- TP = HTF external liquidity (case shows 1:12).

### Part_15_Real_Chart_Case_Study.md — READ ✔
- Pre-flight: HTF bullish + price in discount + HTF Eng LQD swept → buy prep.
- Execution: HTF Extreme OF tap + LTF CHoCH (Major IDM body break) + new LTF inducement → limit at LTF unmitigated OB.
- **TP ladder: TP1 = first LTF structural high/low (→ move to breakeven), TP2 = HTF inducement, TP Final = HTF external liquidity.**
- "Don't get greedy": LTF CHoCH against the position near target = exit early (mechanizable early-exit rule).
- Risk 1% per trade.

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
