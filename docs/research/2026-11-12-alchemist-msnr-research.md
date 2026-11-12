# Alchemist MSNR — Research Notes & Codification (2026-11-12)

Deep-research deliverable backing the mechanical MQL5 EA (`mql5/Experts/MSNR_Alchemist.mq5`)
and the Python validator (`research/alchemist_backtest.py`).

## Bottom line

The Alchemist MSNR strategy (Malaysian SnR × SMC × ICT × CRT, taught by the
"THE ALCHEMIST MSNR TRADING STRATEGY" channel, @alchemist_malaysiasnr) is
**fully codifiable without the AI layer**. The community has already produced
three independent mechanical implementations (OrderBlock.net, KeenBase's
printed playbook, the open-source Wonra Alchemist SNR Engine) whose rules
agree with the Alchemist's own course transcripts. The distilled mechanical
rulebook below is what the EA implements. Confidence: **High** for the level
engine and trigger definitions (3+ independent sources agree), **Medium** for
the exact risk parameters (RR floor, session window — sources vary 1.5–3.0).

## Key findings

### F1 — QM is redundant (confirms the operator's instinct) — HIGH
Alchemist's own course (Part 1, 08:07–08:27): *"The QM is simply an SBR or an
RBS that got broken one more time."* The S/R level engine with flip tracking
already represents every QM. The dedicated QM detector family should be
**dropped from the agent's default families** (kept available, off by
default). Sources: readray.io Alchemist SNR Part 1 transcript; Wonra engine
description ("the QM level is only a setup when it agrees with the
storyline"); trader_core.md §QM.

### F2 — The exact level engine — HIGH
- **A/V levels**: bullish-then-bearish candle pair = **A** (resistance);
  bearish-then-bullish = **V** (support). Level price = **the close of the
  first candle** of the pair. (Alchemist EP1; KeenBase; Wonra.)
- **GAP levels**: green+green = support (untraded band above the prior
  close); red+red = resistance. Band floor ≈ 0.1×ATR (community tuning).
- **OCL (Open-Close Levels)**: in a run of same-colour candles, the close of
  the **first** candle of the run is a level.
- **SBR/RBS**: a **body close** through a level flips its role (support
  broken → resistance = SBR; resistance broken → support = RBS) and the
  level becomes fresh again. A **wick touch consumes freshness only**
  (fresh → unfresh); a body close breaks it.

### F3 — Freshness & use budgets — HIGH
- Fresh = untouched since formation. First reaction is the professional
  trade; each reaction consumes strength.
- **Two-times rule** (H1/H4 levels): usable up to 2 touches.
- **Four-times rule** (D1/W1 levels): usable up to 4 touches.
- Broken levels revive only via the flip (SBR/RBS) within a bounded window;
  after repeated failures the level is dead.
- Conservative EA default: require never-touched levels for entry
  (`InpRequireFresh=true`); budgets become relevant when the flag is off.

### F4 — Storyline (direction) — HIGH
Direction from **HTF levels read on bodies** (MN/W1/D1), beginning with a
**rejection** (close back below resistance / above support) and confirmed by
a **lower-TF breakout** in the same direction. D1 must align with W1 or HALT.
Mechanical encoding used here: last confirmed **close-price pivot break** on
D1 defines external bias; the same break on H1 must agree, else no trade.

### F5 — The trigger sequence — HIGH
1. Price **reaches** a fresh right-side level (wick into the zone).
2. The level **reacts**: no body close through it (a body close-through
   would have flipped/broken the level — the setup is gone).
3. **LTF structure shift**: M30 body-close through the last minor swing in
   the level's direction (BOS/CHoCH). Enter at that close.
   Execution TFs per the Alchemist gold breakdowns: **30M–1H never below
   30m, never above 1H** for execution; analysis on W1/D1/H4.

### F6 — Stop / target / filters — MEDIUM (parameter ranges vary by source)
- **Stop**: beyond the reaction extreme (lowest M30 low from first touch to
  entry for buys) + 0.1×ATR(M30) buffer. Gold needs the sweep extreme, not
  the zone edge.
- **Target**: the nearest opposing fresh level / liquidity pool — *"we
  always target closest exit point"* (gold breakdown video). Fallback: fixed
  RR. Minimum RR gate 1.5 (KeenBase printed rule; the Scribd course deck
  advertises 1:3 targets at ~70% win rate — treat as marketing until the
  backtest says otherwise).
- **Sessions**: London/NY only. *"Usually we don't trade the Asian session"*
  (Forgotten Alchemist video). Encoded 07:00–20:00 UTC.
- **Time limit**: ~200 M30 bars (~4 days) — the reaction has run out of time
  (KeenBase's codification of the method).

### F7 — Published trade record — LOW (no verifiable dated ledger found)
No public, dated, verifiable Alchemist trade ledger (Myfxbook/FTX-style) was
found for the @alchemist_malaysiasnr educator; published material is
video breakdowns with stated R:R ("3 to 25 R:R") and the one-week replay
entries in "The Forgotten Alchemist Trading Strategy" (EURUSD + gold, 1:5
partial shown). The `myfxbook` "Alchemist" systems found are unrelated
grid/hedge robots sharing the name. **Implication:** the ≥70% accuracy
target must be validated against the *codified rules replayed on real
XAUUSD history* (the Python backtester + the MT5 Strategy Tester), not
against a copied trade ledger. This is what was built.

### F8 — Indicator families for the agent (bloat reduction)
Recommended default family set for the chart agent (settings
`strategy/families_registry.py`), ranked by marginal value:

| Family | Verdict | Reason |
|---|---|---|
| `sr` | **KEEP (core)** | The A/V/gap/OCL level engine + SBR/RBS + freshness — the strategy's spine. |
| `bos` | **KEEP (core)** | The trigger is a structure shift; BOS/CHoCH is how the agent times it. |
| `crt` | **KEEP (core)** | The sweep + close-back trigger on HTF ranges; CRT framing is central. |
| `liq` | **KEEP** | Pools = targets (draw on liquidity). Cheap, high value. |
| `fvg` | **KEEP** | Entry refinement (FVG retrace inside OTE). Moderate. |
| `qm` | **DROP (default off)** | Redundant with `sr` broken-twice (F1). |
| `ts` | **DROP (default off)** | TS is the CRT family's variant taxonomy — CRT already covers the read. |
| `idm` | optional | Inducement matters conceptually, but the mechanical value is already carried by structure; enable for LTF refinement only. |
| `tl`, `apex`, `ocl` | DROP | Trendlines/apex are not part of the Alchemist core loop; OCL is already inside `sr`. |

Rendering hygiene (per operator note): the S/R detector's noise reduction
(2026-10-20, `server.sr_render_levels`: gap levels never rendered, 2-use
retirement, cluster dedupe → 20 representatives) already answers the "too
messy" complaint; combined with `status_filter="default"` the agent sees
fresh-only TS/CRT/QM by family choice — with QM/TS dropped the default dial
stays clean.

## Implementation delivered

1. `research/cache_history.py` — deep XAUUSDm history cache (M5…W1, 2018→now).
2. `research/alchemist_backtest.py` — the Python validator implementing
   exactly the rules above; intrabar stop/target resolution on M5.
3. `mql5/Experts/MSNR_Alchemist.mq5` — the standalone mechanical EA:
   same rulebook, H4 book rebuild per closed H4 bar, storyline per H1 bar,
   trigger + execution per closed M30 bar; server-side SL/TP; risk% or fixed
   lot; time exit; session filter; spread guard.
4. `tools/mql5_build.ps1` — compile + deploy + Strategy-Tester launcher
   (Model=4 real ticks, ExecutionMode=100 ms delay), ASCII/no-BOM config.

## Limitations & open questions
- The backtest win rate is a property of the codified rules + parameter
  choices, not of the human Alchemist's discretionary skill. Discretion
  (news handling, bend doctrine) is not mechanical; the EA encodes only
  the objective triggers.
- Exness XAUUSDm feed (digits=3, spread ~240 points): results are
  broker-specific; repeat on the live broker before going live.
- Real-tick download for a year of M30 testing is heavy on first run;
  subsequent runs reuse the cached ticks.
- The Scribd "70% win rate" claim is unverified marketing; our own replay
  decides.

## Sources (graded)
- [S1] THE ALCHEMIST MSNR TRADING STRATEGY channel (@alchemist_malaysiasnr) — YouTube. Course EP1 "MNSR 01: Introduction", gold breakdowns. **B** (primary: the educator's own teaching).
- [S2] "Alchemist snr part 1" transcript (readray.io / videohighlight.com) — full EP1 transcription with A/V/SBR/RBS/QM definitions, fresh/unfresh, 2×/4× rules. **B**.
- [S3] "The Forgotten Alchemist Trading Strategy | Malaysian SnR & SMC Secrets" (YouTube Qlq_pW8QPMY) — weekly-replay trade walkthrough, session doctrine. **B**.
- [S4] "MSNR STRATEGY: GOLD (XAUUSD) NEXT MOVE" (YouTube kcgGzd6Au58) — execution TFs (30M–1H), key-level-inside-FVG entry, SL-covering-candle, nearest-exit targeting, 4RR. **B**.
- [S5] OrderBlock.net — MSNR fresh-level lifecycle (CREATED→FRESH→TESTED→BROKEN→FLIPPED/INVALIDATED, 0.1 ATR buffers, 60-bar flip window), OCL definition. **B**.
- [S6] KeenBase Trading — "MSNR Trading Strategy: Exact Malaysian SnR Entry Rules, With a Printable Playbook" — the D1→H1 direction / H4 level / M30 entry routine, SL/target/1.5-RR/200-bar rules, gold example trade. **B**.
- [S7] Wonra "Alchemist SNR Engine" (TradingView, open source) — independent implementation; storyline/roadblock/miss concepts; confirms QM-from-flip. **B**.
- [S8] Scribd — MSNR XAUUSD Strategy Presentation + MSNR Mastery Guide v1 (community decks; 1H zones/15M entry, 1:3 RR, 70%+ claim). **C** (marketing-grade; used for parameter ranges only).
- [S9] MQL5 forum + MQL5 article 2552 + pipsgrowth CLI guide — tester INI keys (Model=4 = real ticks; ExecutionMode=100 = fixed 100 ms delay; ASCII/no-BOM config; ShutdownTerminal). **B**.
