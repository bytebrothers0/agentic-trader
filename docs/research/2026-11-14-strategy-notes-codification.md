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
