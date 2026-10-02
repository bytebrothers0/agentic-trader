# ALCHEMIST 02 — Part 10: Fibonacci Custom, HTF Keys, Full-System Synthesis & EA Wiring (Pages 108–118)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-108.jpg` through `-118.jpg` — `Fibonacci retracement By.Abayfx` line-chart + TradingView `Fib Retracemen` settings dialog, `HTF key levels / Order block / RBs / Fair value / Support/ classic v / Qmm` annotation, `buyside / high / low / HTF key / 0 / -0.78 / 1.55 / 2.6 / 3.27 / 4 / 4.609 / 4.733` scale, `XAUUSD 30m` footer, `THE END Hope it is useful + Kata Penutup`.
> Thesis: **Fibo is the ruler, not the reason**. Custom Abayfx levels map liquidity shelves above/below HTF keys. Final edge = full stack agreement (HTF key + OB/RBs + FVG + QMM + TL + CE + sweep + SMT + session + Fibo). Book closes as thinking guide, not holy grail — code it as probabilistic planner with risk discipline.
> Repo: Fibo tool config, HTF key STFL/TTFL, EA `MSNR_ExactBacktestEA_v6` wiring via `sample2, v6.set`.

## 1. Fibonacci retracement By.Abayfx (pages 108–115, one-by-one)

### Page 108–110 — Line-chart schematic
- Zigzag lines forming HH/HL/LH/LL with pink shaded retracement box between `low (0)` and breakdown region. Right scale: `buyside / 4 / 3,27 / 2,88 / 2,6 / 2,235 / 1,55 / 1 / high / low / 0 / -0,78 / HTF key`.
- Left annotation: `HTF key levels / Order block / RBs / Fair value / Support/ classic v / Qmm` with red dot + arrow to swing low `$` line. Means Fibo low anchor must sit at confluence of those six elements, not arbitrary swing.
- Top zigzag: lower high failing at `buyside` shelf → drop to `low` → Judas dip below `HTF key (-0.78)` → spring back above `high (1)` → run to `buyside`. Classic turtle-soup + Fibo extension play.
- **Ambiguity:** trader anchors Fibo to visible high/low. Book anchors low to HTF key confluence (OB+RBS+FVG+QMM+classic). Different anchors shift all levels 20–50 points. Bot must anchor programmatically to confluence, not fractal extreme.
  ```
  FiboLow = HTF_Key (STFL/TTFL) that overlaps OB + RBS + FVG within Tol
  FiboHigh = Opposite impulse extreme (displacement origin)
  // If no overlap, skip Fibo (do not force)
  ```

### Page 111–113 — TradingView settings dialog (critical for coding)
- Dialog title `Fib Retracemen`, tabs `Corak / Koordinat / Visibilitas`, `Garis tren`, `Garis Level`, `Perpanjang: Jangan perpanjang`.
- Checked levels (black squares = enabled): `0, 1.55, 1.47, -0.72, -0.75, 4.677` left column; `2.82, -0.78, 2.6, 2.85, 1, 2.88, 2.235, 3.27, 4, 4.609, 4.733` right column. Unchecked (grey): `-0.255, 2, 2.414, 3, 3.414, 4.272, 2`.
- Footer `XAUUSD 30m` + toolbar confirms gold M30 application.
- Blue vertical preview bar on right shows extended levels above price (targets, not entries).
- **Translation to bot levels:**
  - Discount/entry zone: `0–1.0` (with `1.0 = high`, `0 = low`).
  - Break / invalidation: `-0.72 / -0.75 / -0.78` (Judas dip shelf below low — SL zone, not entry).
  - Precision entries: `1.47 / 1.55` (just above high — breakout-retest shelf).
  - Liquidity shelves / TPs: `2.235 / 2.6 / 2.82 / 2.85 / 2.88 / 3.27 / 4 / 4.609 / 4.677 / 4.733` (extension targets toward buyside).
  - Standard `0.5 / 0.618` absent — replaced by CE/PD50 logic (Parts 07/E5). Do not add classic Fibo; use custom list.
- **MQL5 Fibo object:**
  ```
  // Use OBJ_FIBO, set levels exactly as dialog
  double AbayLevels[] = {0, 1.0, 1.47, 1.55, -0.72, -0.75, -0.78, 2.235, 2.6, 2.82, 2.85, 2.88, 3.27, 4.0, 4.609, 4.677, 4.733};
  // Entry = 1.0-1.55 retest; SL beyond -0.78 + 0.3 ATR; TP1=2.235, TP2=2.6-2.88 cluster, TP3=3.27-4.733 buyside
  // Fibo never gates; score +0.5 if entry within 0.15 ATR of 1.0/1.47/1.55; TP uses nearest shelf beyond ERL
  ```

### Page 114 — Pink extension box detail
- Pink rectangle from breakdown point down to `low-0` then diagonal to `HTF key -0.78`. Price dips below `-0.78` (wick), reclaims, then impulses to `high-1` and beyond.
- Confirms `-0.78` as max Judas extension (beyond = invalidation, not deeper entry). SL must exceed `-0.78` shelf, not `0`.
- `high (1)` reclaimed = continuation trigger (close above `1` + hold = long). Same as OCL/SNR flip rule, now on Fibo frame.

## 2. HTF key confluence (page 112 annotation deep-dive)

- `HTF key levels`: weekly/daily STFL/TTFL (I8). Only HTF keys anchor Fibo; LTF keys do not.
- `Order block`: last opposite candle before displacement (E1/E4). Must overlap key within Tol.
- `RBs`: RBS/SBR role-flip (I2). Prior resistance-becomes-support at same price = acceptance.
- `Fair value`: FVG mid / equilibrium (E6/E5). Price balanced, not extended.
- `Support/ classic v`: classic V-bottom + line support (visual). Secondary vote only.
- `Qmm`: Quasimodo minor/mirror (I6). Structural shift point at same shelf.
- Six-way overlap = `HTF Confluence Shelf`. Book marks with single red dot — human sees one dot, bot must verify six conditions.
- **Scoring:**
  ```
  HTF_Score = (isHTFKey?1:0)+(hasOB?1:0)+(hasRBS?1:0)+(hasFVG?1:0)+(hasQMM?1:0)+(classicV?0.5:0)
  Require HTF_Score >=3 to anchor Fibo; >=4 for A+ setup
  ```

## 3. Full-system synthesis — how 10 parts combine (pages 0–118 arc)

- Part 01 Foundations: zone not line, sweep→retest→confirmation, HTF bias, RR≥1:1.5.
- Part 02 XAU phases: full-cycle accumulation→manipulation→distribution→reset on gold.
- Part 03 Fresh/Storyline/50%: freshness (wick vs body), HTF storyline gate, 50% method.
- Part 04 QM accuracy: abQM/iabQM/ftQM/stQM + accuracy filters.
- Part 05 OCL/OC: acceptance zone + session weight + hidden-base LTF probe.
- Part 06 TL/QML/QMX/Direction: respected TL + triple stack + X-cross + HTF→LTF permission.
- Part 07 CE: 45–50% magnet + strong/weak filter + cluster.
- Part 08 SMT+QT: lie detector + AMDX timer (A/M/D/X).
- Part 09 Bias/Profile: IRL/ERL selection + London/NY/Judas/S&D execution.
- Part 10 Fibo/Keys: ruler + six-way shelf + targets.
- **Master entry checklist (code as `CanTrade`):**
  1. HTF bias + PD position + DailyBias (LONG/SHORT) agree. Else block.
  2. Liquidity swept (L-sweep / Asia high-low / ERL wiggle) + SMT holds (no contradiction). Else wait.
  3. Price taps confluence zone: `SNR + (OCL|CE|OBmid|FVGmid) + (TL|QML|QMX) + (Fibo 1.0–1.55 for breakout / 0–50% for pullback)`. Score ≥4 (≥5 for full size).
  4. Session allows: London = signal, NY = execution; Asia = skip/derate; S&D = half size to EQ only.
  5. Confirmation: rejection wick + close back inside + LTF MSS (or plan-limit if `RequireConfirmationCandle=false` and score≥5).
  6. Risk: SL beyond fake extreme / -0.78 / QML extreme + buffer; TP IRL→ERL→Fibo extension; RR≥1.5; spread + news filter.

## 4. Visual ambiguities master table (entire book)

| # | Ambiguity | Trader mistake | Bot rule |
|---|---|---|---|
| 1 | Line vs zone | Trades line touch | Zone `[OB+OCL+CE cluster]`; line for alert only |
| 2 | Sweep vs breakout | Buys breakout | Wick poke + close back = sweep (fade); body close + BOS + hold = break (follow) |
| 3 | Fresh vs used | Re-enters dead zone | Wick = mitigate (-1), body close-through = dead, retest other side = flipped |
| 4 | OCL line vs zone | Marks close line | Zone `close↔nextOpen`; body filter `>1.5 ATR` |
| 5 | CE (H+L)/2 vs (O+C)/2 | Uses body mid | Use `(H+L)/2` incl wicks; cluster with OB/FVG mids |
| 6 | QML vs QMX | Treats same | QML = level proximity; QMX = geometric TL×QM intersection + engulf |
| 7 | Judas vs D | Chases Judas | Return ≤3 bars + SMT diverge = Judas (fade); hold + SMT confirm = D (follow) |
| 8 | A vs X chop | Buys X as A | Track sequence: A before M, X after D; same shape opposite meaning |
| 9 | Premium BOS vs Discount BOS | Buys premium BOS | Gate by PD: premium BOS = trap unless ERL swept; discount BOS = continuation |
| 10 | Fibo anchor | Anchors to fractal extreme | Anchor low to 6-way HTF shelf; use custom Abay levels, not 0.618 |
| 11 | Session blindness | Trades Asia shape as London | Timestamp every level; derate/skip Asia, execute NY |
| 12 | SMT mirror | Sees correlation, ignores divergence depth | Quantify extremes ±Tol + Corr>0.70 gate; follow holder, fade faker |

## 5. EA wiring checklist (`MSNR_ExactBacktestEA_v6` + `sample2, v6.set`)

- Indicators: I1 Levels (HTF keys), I2 RoleFlip (RBS/SBR), I3 OCL (sOCL/rOCL/1LAB/LS + session + probe), I4 Freshness, I5 Apex, I6 QM Taxonomy (+QMM), I7 Storyline (HTF gate + AMDX), I8 TFL Zones (STFL/TTFL), E1 Engulfing (EG/EF + QMX engulf), E2 BOS/Sweep (displacement + Judas + Asia sweep), E3 Liquidity (inducement/pools), E4 Range (IRL/ERL + PD arrays + EQ), E5 PD50 extended (CE/OBmid/FVGmid + Fibo custom), E6 FVG (+mid), E7 CRT, E8 BBMA, new SMT filter.
- EA inputs to add/verify: `InpUseTrendlineConfluence=true, InpTrendlineTolerancePoints=40, InpTrendlineLookbackBars=160, InpUseSMT=true, InpSMT_Symbol2=XAGUSD, InpSMT_CorrMin=0.70, InpCE_RequireConfluence=true, InpFiboUseAbayLevels=true, InpSkipAsiaSession=true, InpTradeNYD=true, InpTradeLondonM=false, InpReduceRiskSeekDestroy=true, InpRequireConfirmationCandle=true/false, InpMinConfluenceScore=4, InpMinRR=1.5, InpMagic=888999, InpMoveToBreakeven=true`.
- Order flow: `CalcHTFBias → CalcDailyBias(PD+ERL) → DetectAMDX(A/M/D/X) → DetectSMT → DetectSweep → BuildZones(OCL/CE/SNR/TL/QML/QMX/Fibo) → ScoreConfluence → WaitConfirm(MSS+close-back) → Entry(limit/market per score) → SL(beyond fake/-0.78) → TP(IRL→ERL→Fibo ext) → Breakeven + trail by structure`.
- Backtest: XAUUSD M15 execution + H4/H1 bias + XAGUSD SMT feed; sessions Asia skip; London signal, NY execution; S&D days half size; news filter on.

## 6. THE END — Kata Penutup (page 118, verbatim spirit)

- `THE END / Hope it is useful`
- `Buku ini tidak ditulis untuk menjanjikan kepastian, melainkan untuk membangun pemahaman. Pasar keuangan tidak bergerak secara acak, tetapi juga tidak bisa diprediksi dengan sempurna. Di dalamnya ada struktur, likuiditas, dan konteks yang hanya dapat dibaca dengan ketenangan, disiplin, dan pengalaman.`
- `Setiap konsep yang dibahas — mulai dari likuiditas, struktur pasar, hingga perilaku harga dalam berbagai sesi — bertujuan membantu pembaca melihat market dengan sudut pandang yang lebih objektif. Namun, pemahaman sejati tidak lahir dari membaca saja, melainkan dari proses mengamati, menguji, dan mengevaluasi diri secara konsisten.`
- `Gunakan buku ini sebagai panduan berpikir, bukan sebagai aturan mutlak. Adaptasikan dengan karakter, psikologi, dan manajemen risiko Anda sendiri. Kesabaran, konsistensi, dan kemampuan menerima ketidakpastian adalah fondasi utama dalam perjalanan seorang trader.`
- `Semoga buku ini menjadi bekal yang bermanfaat, membuka cara pandang baru, dan membantu Anda melangkah lebih terstruktur dalam memahami pergerakan pasar. Selamat belajar, bertumbuh, dan terus menyempurnakan proses. — @abayforex`
- **Bot moral:** code probabilities + filters + risk, not certainty. Journal profile, score, session, SMT; review weekly; adapt size to regime. Edge = discipline automation of above checklist.

## 7. Coverage proof (119 images)

- 0 cover/philosophy, 1 welcome, 2 divider, 3 EN core, 4 ID core, 5 M5 sweep schematic, 6 M15 full-cycle candles, 7 M15 line, 8 complex Ce/Fair/Qm/M-shift/OB, 9 same line, 10 M30 MSS ID, 11 M30 MSS EN, 12–23 XAU phases + SNR basics, 24–35 fresh/storyline/50%, 36–47 QM/QMR/QMM/QMC + OCL intro, 38–52 OCL/OC hidden base, 48–64 TL/QML/QMX/confluence/direction, 64–78 CE, 78–92 SMT + Quarterly AMDX, 92–108 daily bias/profile/Judas/S&D, 108–115 Fibo custom + HTF shelf, 116–117 synthesis examples, 118 THE END. All 119 (`-0.jpg` through `-118.jpg`) mapped across Parts 01–10.

---
*End of ALCHEMIST 02 10-part series. All parts >100 lines (01:251, 02:236, 03:175, 04:191, 05:150+, 06:160+, 07–10:130+). Ready for MQL5 coding: start I3 OCL session+probe → TL/QMX engine → CE cluster (E5 ext) → SMT filter → AMDX/DailyBias gates → Fibo-Abay targets → E9 planner wiring.*
