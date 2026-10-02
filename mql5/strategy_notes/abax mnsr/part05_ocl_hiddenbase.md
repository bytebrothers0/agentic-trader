# ALCHEMIST 02 — Part 05: OCL / Open-Close Levels & Hidden Base (Pages 38–52)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-38.jpg` through `-52.jpg` — `WHAT IS OC/OCL` divider + `What Is OCL and How to Use It` + `Penting/IMPORTANT` session filter + Examples 1–4 + `OC / OPEN-CLOSE` hidden-base pages (BUYING + SELLING) + QML intro bridge.
> Thesis: wicks show rejection; **open/close show acceptance**. OCL = where market agreed price. HTF identical candles hide LTF supply/demand. Bot must treat OCL as zone, not line, with session weight + LTF probe.
> Repo link: I3 `MSNR_OCL.mq5` (sOCL/rOCL/1LAB/LS), E6 FVG, E2 sweep, session gate in `sample2, v6.set`.

## 1. OCL definition (What Is OCL and How to Use It)

- `OCL (Open-Close Level) = zona dari harga open dan close sebuah candlestick.`
- Most traders mark SNR only on shadows/wicks. Book says wrong: open/close reveal where market **accepted** price. Close = final agreement of session; next open = where new pressure starts. Hence OCL often more reliable than wick-lines.
- How to find (pages 40–42):
  1. Locate key candles — **breakout candle, strong reversal / displacement candle**. Ignore doji / small bodies.
  2. Mark its `close`. Sometimes plus next candle's `open`. Band between = OCL zone.
  3. HTF sketch: prior impulsive candles, blue OCL band at stacked closes, label `OCL (OPEN CLOSE LEVELS)`.
  4. LTF sketch: `RBS / FAIR / FVG / +TS / OCL / RESIS / KZ` stack with `Follow The Tren [trend]`.
- Trigger rule from book:
  - Break through OCL + close beyond = strength to shift structure.
  - Retest of OCL = cleaner/safer entry than first break.
  - Overlap OCL + SNR = strong rejection area (Example 4).
- **Bot translation:**
  ```
  OCL_Zone = [min(close_k, open_k+1), max(close_k, open_k+1)]
  OCL_Line = close_k  // for alerts only
  Qualifier = body_k > 1.5*ATR(14) AND range_k > median(range,50)*1.2
  // doji/small body -> reject, prevents OCL spam
  ```

## 2. OCL vs wick-SNR — visual ambiguity #1

- Human eye: both look like horizontal lines. Book forces distinction:
  - Wick line = rejection edge (tail). Price wicked and left = no acceptance.
  - OCL = acceptance core (body). Price closed and held = agreement.
- Chart ambiguity: on M15 candles, OCL band sits inside prior wick high/low. On line-chart view (same page lower panel), wicks disappear, OCL becomes exact swing line. Trader flipping views mislabels.
- **Coding resolution:**
  - Keep two layers: `WickLevel (high/low)` + `OCL_Zone (open/close)`.
  - Entry at overlap = A+ (score +2). Entry at wick-only = C (require extra sweep). Entry at OCL-only = B (require session + MSS).
  - Never merge into single `Support/Resistance` buffer. Keep `Buf_Wick`, `Buf_OCL_Top`, `Buf_OCL_Bot`, `Buf_OCL_Mid`.
  - Line-chart mode in book = `close-only` rendering. Bot equivalent = `PRICE_CLOSE` sampling, not `HIGH/LOW`. Replicate by option `UseCloseForStructure=true`.

## 3. Timeframes + stack rule

- Any TF works, but **H4/Daily give stronger/clearer signals** (page 41). M15 OCL = intraday, H4 OCL = institutional.
- Always combine: **Trendlines + Fibonacci + Market Structure**. Accuracy + confidence jump. Book shows LTF combo: `FVG + Resistance + Retest + Timezones (New York/London)`.
- When S/R overlaps FVG, zone much stronger.
- **Bot scoring (do not use single flag):**
  ```
  Score = 0
  +1 if OCL virgin or retest+rejection
  +1 if SNR overlap (wick within 0.25 ATR)
  +1 if FVG overlap (E6)
  +1 if trendline touch (tolerance InpTrendlineTolerancePoints=40)
  +1 if London/NY session (see §4)
  +1 if LTF MSS in entry direction after touch
  Tradeable if Score >= 4, A+ if >=5
  ```

## 4. Session filter — Penting / IMPORTANT (page 43)

- OCL during **New York / London = stronger zones + bigger momentum than Asia**. London/NY overlap = most reliable, lowest fake-break odds.
- Visual: vertical shaded session boxes behind OCL examples. Asia box = tight range, no displacement. London box = sweep + displacement. NY box = continuation.
- **Ambiguity:** same OCL shape in Asia vs London looks identical in isolation. Bot must timestamp OCL birth.
- **Coding:**
  ```
  enum ENUM_OCL_Session { OCL_ASIA, OCL_LONDON, OCL_NY, OCL_OVERLAP };
  // Asia OCL -> require extra confirmation (LTF MSS + sweep) or skip
  // London/NY OCL -> standard plan
  ```
- Matches `sample2, v6.set` Asia-skip philosophy (`InpSkipAsiaSession=true`). Parameterize `InpDerateAsiaOCL=true`, `InpRequireExtraConfirmAsia=true`.

## 5. Four worked examples (pages 44–47) — one-by-one

### Example 1 & 2 (top sell, mirrored)
- OCL at top = potential sell after return-retest. Formed by strong rejection in active session + BOS + clean retest before drop. Fibonacci optional (precision aid, not rule).
- Candle view: bearish displacement away, then slow return to OCL mid, then bearish engulfing down. Line view: M-shape with lower high at OCL.
- Bot: `OCL virgin (no retest) -> watch; OCL retest + rejection (engulfing / wick + close back inside) -> entry`.

### Example 3 — OCL as support that breaks
- OCL initially holds (two touches), third touch closes through with body (not wick). Return-retest from below = ideal sell, especially aligning with SNR/key level.
- Ambiguity: wick poke vs body close-through. Book uses body close: wick poke = still fresh, body close-through = broken + role-flip.
- Bot: `if Close[i] < OCL_Bot - 2*Point and Close[i+1] retests OCL_Bot from below + rejection -> short`. Same as I2 RBS/SBR flip but anchored on OCL, not wick extreme.

### Example 4 — OCL overlapping SNR
- Strong rejection area. Clean confirmed revisit = safer entry before trend continues. Shows `SNR line == OCL_Top` within few points + FVG above.
- Bot: overlap tolerance = `0.25*ATR_M15` or `InpTrendlineTolerancePoints`. If distance > tolerance, treat as two separate zones (do not merge).

## 6. OC — hidden base (BUYING + SELLING pages, 48–52 bridge)

- `OC (Open-Close): two identical HTF candles side-by-side (same color/shape) is not coincidence. Zoom to LTF -> hidden supply/demand zone (SMC hidden base).`
- Why matters: HTF pause = gathering momentum, deciding continue vs reverse. Knowing hidden orders = advantage vs assuming "nothing happening."
- Analogy in book: HTF = building from far (plain wall); walk closer = windows/doors/shops/activity. OC point says: *"Area ini tidak kosong. Ada sesuatu yang tersembunyi / This area isn't empty."*
- Chart logic:
  - HTF clean formation (e.g. two bullish H4 side-by-side) -> LTF (M15) reveals internal range/base/order-accumulation -> explains strong reactions at OC zones.
  - H4 example (3): grey HTF candles -> teal OC band -> displacement down after base breaks.
  - M15 example (4): teal LTF base -> `Key levels / Turtle soup` sweep of highs then drop.
- SELLING mirror: same hidden-base logic inverted (two bearish HTF -> LTF supply base).
- Important note (page 52 footer): **don't rely only on demand zone.** LTF has OB, Volume, V-shape, Accumulation (A), etc. None right/wrong — different perspectives on same behavior.
- **Bot OC detector:**
  ```
  bool IsOC = (Close[h] > Open[h] && Close[h+1] > Open[h+1] && MathAbs(Close[h]-Close[h+1]) < 0.3*ATR)
           || (Close[h] < Open[h] && Close[h+1] < Open[h+1] && MathAbs(Close[h]-Close[h+1]) < 0.3*ATR);
  // On birth, drill to LTF:
  // window = [Time[h], Time[h+1]+Period Seconds]
  // look for base/range/OB/FVG/V-shape/accumulation inside window
  // Score OC by LTF content: plain micro-range = weak (1); OB+FVG+sweep = strong (3)
  ```
- This is exactly repo I3 `MSNR_OCL` + `1LAB/sOCL/rOCL` classification extended with LTF probe. `sOCL` = support OCL (bullish pair), `rOCL` = resistance OCL (bearish pair), `1LAB` = first leg after base, `LS` = last support in base.

## 7. Visual ambiguities table — OCL/OC for coder

| Ambiguity | What human sees | Bot decision |
|---|---|---|
| OCL = line or zone? | Thin line on chart | Zone `[min(close, nextOpen)..max]`; line for alerts, zone for entries/SL |
| Which candle qualifies? | Any big candle | Only breakout / strong-reversal displacement; `body>1.5 ATR`, reject doji |
| Wick poke vs break? | Same crossing | Wick poke (high/low poke, close back inside) = still valid/fresh; body close beyond + retest = broken/flipped |
| Asia vs London OCL? | Identical shape | Tag birth session; derate Asia, require LTF MSS + sweep or skip |
| Hidden base must be which pattern? | Looks like range | Any of OB / FVG / V / accumulation / volume shift; score composition, don't hardcode one |
| Fib required? | Fib drawn on examples | No. Optional precision overlay only, +0.5 score |
| OCL retest entry timing? | Return looks tradeable immediately | Wait for rejection: engulfing / wick + close-back-inside / LTF MSS; market-entry on touch alone = Mistake #1 |
| Two HTF candles slightly different size? | Still looks like OC | Allow `abs(close1-close2)<0.3 ATR` and same color; else not OC, treat as single OCLs |

## 8. MQL5 implementation notes

- Buffers: `OCL_Top, OCL_Bot, OCL_Mid, OCL_Session (int), OCL_Score, OCL_State (virgin/retested/broken/flipped)`.
- Freshness: reuse I4 `MSNR_Freshness` logic — wick touch = mitigate (score -1), body close-through = broken, retest from other side = flipped entry.
- LTF probe function `ProbeHiddenBase(datetime t1, datetime t2)` returns flags `hasOB, hasFVG, hasSweep, hasAccum`. Called once per HTF OC birth, cached.
- Turtle-soup sweep at OC edge -> call E2 `MSNR_EMS_BOS_Sweep` sweep detector on LTF window, not HTF.
- Session: use server time + `InpLondonStart/InpNYStart` from EA set; store `birthHour`.
- Alerts: `OCL_Birth(HTF, price, session)`, `OCL_Retest(side, score)`, `OC_HiddenBaseFound(strength)`.

## 9. Repo mapping checklist

- OCL birth/role/LS -> `MSNR_OCL` (I3) already does two-same-color + close-of-first + sOCL/rOCL/1LAB/LS. Add: `includeNextOpen` zone mode + session tag + HTF->LTF hidden-base probe (new `ProbeHiddenBase`).
- Hidden-base LTF elements -> `MSNR_EMS_FVG` (E6), OB-mid (E5 extension), `MSNR_TFL_Zones` internal ranges, E3 inducement, E2 sweep.
- Session filter -> EA session gate (London/NY boost, Asia derate/skip) + `InpSkipAsiaSession`.
- Turtle-soup at OC edge -> E2 sweep detector on LTF window.
- QML bridge (page 52): OCL + SNR + TL triple stack leads into Part 06 QML/QMX — do not code OCL in isolation.

---
*Next: Part 06 (pages 48–62) — MSNR Trendlines: respected vs perfect, touch rules, QML SNR+TL, QMX crossing, confluence build, CE/Fibo intro, trendline distance, direction multi-TF hierarchy.*
