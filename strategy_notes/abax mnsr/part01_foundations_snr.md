# ALCHEMIST 02 — Part 01: Foundations, SNR Zones, Liquidity Sweep Logic (Pages 0-11)

> Source images: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-0.jpg` through `-11.jpg`
> Scope: Cover art, philosophy, ALCHEMIST+SNR core model (EN+ID), M5 LTF sweep schematic, M15 full-cycle examples, trendline-break + MSS framework, liquidity/MSS/premium-discount/session/dealing-range master chart.

## 1. What Pages 0-2 Establish (Cover + Welcome + Title)

### Page 0 — Cover: "E-BOOK > ABAYFX / 100 PEGES / Pengertian ALCHEMIST"
- Definition (ID): `Alchemist adalah konsep atau cara berpikir dalam trading yang bertujuan mengubah area market biasa menjadi peluang trading bernilai tinggi dengan memahami struktur harga, likuiditas, dan reaksi market.`
- Simplified: `Alchemist = seni membaca niat market, bukan sekadar melihat pergerakan harga.`
- Subtitle: `Malaysia Support and resistance` + `KEY/LEVELS` + `MSNR` vertical panel + `SUPPORT AND RESISTANCE`
- Background chart shows candlesticks + zigzag/line structure with Fib levels on right: `0,109 / 0,127 / 0,145 / 0,214 / 0,232 / 0,25` and lower `0,618 / 0,636 / 0,654 / 0,786 / 0,804 / 0,822`, plus footer `support levels with engulfing zone are (V)` and `CLASSIC/V`.
- **Bot takeaway:** entire book is MSNR (Malaysia SNR) key-levels system, not classic line SNR. Fib + engulfing-zone notation matters. Do not code classic pivot S/R; code zone + liquidity context.

### Page 1 — Welcome
- Only text: `WELCOME AND HAPPY READING MY BOOK / @abayforex`. No logic. Confirms author handle for attribution.

### Page 2 — Section divider: `ALCHEMIST + SNR / @abayforex`
- Marks start of Module 1. Every later chart belongs under this module until new divider appears.

## 2. Core Components of the Alchemist Model (Pages 3 EN + 4 ID — same content)

Author lists 4 pillars. Must be coded as 4 interacting subsystems, not isolated signals:

### 2.1 SNR Zone — Key Support & Resistance Zones, NOT just lines
- ID version: `Area Support & Resistance utama, bukan garis.`
- **Visual ambiguity to resolve for bot:** human sees a horizontal line on chart, but logic says zone = `SNR + OB + 50% OB`. On pages 6-11 the zone is drawn as thin line (`S`, `R`, `KEY/LEVELS`, `snr`) but entry text says wait for `touch 50% OB + confirmation`.
- **Coding rule:**
  ```
  Zone = { snr_line, ob_high, ob_low, ob_50 = (ob_high+ob_low)/2 }
  ValidLongZone = price in [ob_low, ob_50] AND HTF bias bullish AND sweep already occurred
  ValidShortZone = price in [ob_50, ob_high] AND HTF bias bearish AND sweep already occurred
  ```
- Never trigger on `Touch(snr_line)` alone. That is listed as Mistake #1.

### 2.2 Liquidity Sweep (MISS) — Price takes liquidity by running above previous highs or below previous lows
- ID: `Price mengambil likuiditas dengan menembus high/low sebelumnya.`
- Purpose (both versions):
  1. `Price sweeps previous high/low to collect liquidity.`
  2. `Removes pending orders and retail stop losses. / Menghilangkan pending order & stop loss retail.`
  3. `After the sweep, market is prepared to move in real direction.`
- Valid sweep confirmation (both versions):
  - `Market has retested the zone / Market sudah retest zona`
  - `Ready to move in opposite direction / Siap bergerak arah berlawanan`
- **Visual ambiguity:** sweep looks identical to breakout on a single timeframe. Author distinguishes by:
  - LTF (M5) view: `Long wicks + False breakouts / Wick panjang + Fake breakout`
  - `Price slightly breaks above resistance / Harga break sedikit di atas resistance`
  - `Fails to hold or close strongly above it / Tapi tidak close kuat`
  - Conclusion label: `Liquidity has been collected / Likuiditas sudah diambil` + `Breakout is likely fake / Bukan breakout valid`
- **Coding rule for bot:**
  ```
  IsSweepHigh(i) = High[i] > PrevHigh AND Close[i] < PrevHigh AND UpperWick% > threshold
  IsSweepLow(i)  = Low[i] < PrevLow AND Close[i] > PrevLow AND LowerWick% > threshold
  // Must also check: no strong body close beyond level. If Close > PrevHigh + ATR*0.2 => NOT sweep, IS breakout.
  ```

### 2.3 Order Block (OB) — The last genuine buy/sell area (focus on 50% midpoint)
- ID: `Area terakhir buyer/seller nyata (fokus pada level 50% OB).`
- Rules block (EN):
  - `Use OB before market breaks structure.`
  - `Use the 50% midpoint of OB for optimal entry.`
  - `OB can be reused if the context still supports it.`
- ID identical: `Gunakan OB sebelum market break struktur. / Pakai level 50% OB sebagai titik entry terbaik. / OB bisa dipakai lagi jika konteks mendukung.`
- **Visual ambiguity:** on page 5 and 7, OB is a full candle body (dark bar), but label `Candle fillet 50% / 0.5 ob From upper body to lower body` and `From upper axis to lower axis what is the axis? The wick is the tail of the candle` shows author confusion between body-based vs wick-based OB.
- **Coding resolution:**
  - Default: `OB = body of last opposite candle before impulse (Open to Close)`.
  - `OB50 = (OB_high + OB_low)/2`.
  - Optional input `InpOB_UseWicks=false` to allow full high-low version for testing, since chart annotates both.
  - Log which version triggers to disambiguate later pages.

### 2.4 Market Structure (MS) — Main structure + substructure (Uptrend/Downtrend + Swing Highs/Lows)
- ID: `Struktur utama & substruktur (trend UP/DOWN + swing high/low).`
- How to use (EN):
  1. `Identify HTF trend and LTF structure.`
  2. `Trade in direction of main trend for higher win rate.`
  3. Zone valid if: sweep high/low + touch+reject + aligns with MS + candle closes near OB or 50% midpoint.
- **Coding rule:** need two structure trackers:
  - `HTF_Trend (e.g. H4): HH/HL = bullish, LH/LL = bearish`
  - `LTF_Structure (e.g. M5/M15): internal BOS/MSS for entry timing`
  - Block trades where `HTF != LTF_direction` — listed as Mistake #3: `Trading against HTF (HTF bearish but taking buys).`

## 3. Mistakes, Effective Use, Confluence, Failure (Pages 3-4 right column)

### 3.1 Common Mistakes (Avoid These) / Kesalahan Umum
1. Entering just because price touched a line — without confirmation.
2. Ignoring liquidity and order blocks.
3. Trading against HTF structure.
- **Bot translation:** all three must be hard filters, not warnings.

### 3.2 Effective Use of SNR / Cara Efektif Menggunakan SNR
- `Wait for clear reaction: rebound or rejection. / Tunggu clear reaction (rebound atau rejection).`
- `Must be located near key structure points (HH/HL/LH/LL). / Harus berada di area high/low penting.`
- `If zone is touched after a sweep, it becomes valid. / Jika zona disentuh setelah sweep, dianggap valid.`
- **Sequence enforced:** `Sweep -> Zone Touch -> Confirmation`. Any other order = no trade.

### 3.3 Confluence Checklist (Before Taking Entry)
- `HTF supports directional bias (e.g. H4 bullish)`
- `Liquidity sweep occurs at the zone`
- `Zone aligns with SNR+OB+50% OB`
- `Confirmation candle appears (engulfing / rejection / close-back-in-range)`
- **Bot:** implement as `ConfluenceScore 0-4`; require `>=3`, with sweep mandatory.

### 3.4 When SNR Fails / Jika SNR Gagal
Zone invalid if:
- Too many touches with no rejection / Banyak sentuhan tanpa rejection kuat.
- No liquidity sweep occurs / Tidak ada sweep.
- HTF contradicts entry / HTF bearish tetapi entry buy.
- Price breaks zone with strong momentum / Harga break zona dengan momentum kuat.
- **Visual ambiguity:** "too many touches" is subjective on chart (pages 6/8 show Retest 1/2/3). Code as input: `InpMaxTouches=3`; after 3 wick touches without displacement away, mark zone `WEAK` -> require stronger confirmation or halve lot (author says `reduce position size`).

### 3.5 Entry Triggers (Trigger Masuk)
Enter only when one appears:
1. Confirming candle: engulfing / strong rejection wick.
2. Close-back-in-range: after sweep, price closes back above/below zone.
3. Touch 50% OB + confirmation candle.
- Warning: `If zone has multiple touches -> weaker -> reduce size or wait stronger confirmation.`

### 3.6 Bullish Reversal Playbook (Example Setup)
1. HTF begins shifting bullish.
2. Price sweeps sell-side below previous lows.
3. Price taps zone (SNR+OB+50% OB) and shows rejection.
4. Enter once price closes back above zone or breaks substructure.
- Mirror for bearish.

### 3.7 Quick Rules (Summary)
1. Trade with HTF bias (use H4 for direction).
2. Wait sweep -> zone touch -> confirmation candle.
3. Use 50% OB for entry and stop placement.
4. Min R:R 1:1.5 and manage based on structure.

## 4. M5 LTF Sweep Schematic (Page 5) — Most Codable Diagram in Part 01

Page 5 shows two large candles (grey + dark) with annotations:

- Top text: `M5 – LTF Liquidity Sweep / On lower TF (M5): Price sweeps previous highs/lows / Stops are taken (retail)` + `Appears as: Long wicks / False breakouts` + `Liquidity Sweep (L Sweep): Price slightly breaks above resistance / Fails to hold or close strongly above it` + `Indicates: Liquidity collected / Breakout likely fake`.
- Left labels: `Key levels / Poi HTF / MSNR / RBs Resistance becomes support / Order Block / Vair value gap [sic: Fair value gap] / Resistance classic A` pointing to `Key / H` line.
- Middle: `M5-Ltf Sweep` arrow to `L,Sweept` line just above `Resistance` line. `Order block` line at lower third of dark candle.
- Center logic box (bilingual, exact):
  ```
  1. Harga mendekati HTF key level / Price approaches HTF key level
  2. Terjadi liquidity sweep (fake breakout) / Liquidity sweep occurs
  3. Harga reject di resistance / Price gets rejected at resistance
  4. Terbentuk order block / Order block forms
  5. Entry di order block / 50% candle / Entry at OB / 50% candle
  6. Target ke struktur berikutnya / Target next structure level
  ```
- Bottom: `Order Block: The last candle before strong impulsive move / Acts as high-probability entry zone / Sell after high sweep / Buy after low sweep`.
- Right panel: `HTF key levels / L, Sweept` -> two tall candles with `Candle fillet 50%` mid-line and `Order block` low line.
- Footer: `M15`.
- **Visual ambiguities resolved:**
  - `L,Sweept` vs `Resistance` are TWO separate lines ~ few pips apart. Sweep pierces first but must not close above second. Code both: `SweepLine = sweep high wick extreme`, `ResistanceLine = body-close level`. Sweep = wick over SweepLine + close under ResistanceLine.
  - `Vair value gap` typo = Fair Value Gap; but chart does NOT draw FVG here — do not require FVG for this setup.
  - `RBs Resistance becomes support` label on bearish short example is confusing; actually shows resistance-turned-entry after sweep. Treat `RBS` as role state after sweep+reject, not classic S/R flip requiring body break.
  - `Candle fillet 50%` typo = filament/fill 50% — means OB midpoint. Use `(OB_high+OB_low)/2`.

## 5. M15 Full-Cycle Examples (Pages 6-7)

### Page 6 (BTCUSD 13:22, duplicate candle + line views)
Labels to encode:
- `Displacement` (strong vertical move), `sbr` (support becomes resistance? actually sell-side resistance), `resis / idm / Sweep` cluster at top, `Sell s` / `buy s` liquidity pools, `KEY/LEVELS`, `Retest 1/2/3`, `trendline` with `1-2-3` touches, `Acumulation [sic]`, `Resistance becomes support`, `rbs`, `doji`, `snr`, `+ts`, `Manipulation`, `market structure shift`, `reversal Q`, `Support`.
- **Key teaching:** same chart shown as candles (top) and line (bottom) — author insists line helps see `sweep`, `trendline`, `accumulation` without candle noise. Bot should optionally use `close-price line` for trendline-break detection to match human.
- Retest counting: support shows `Retest 1` then `Retest 2` at `Manipulation` low; resistance shows `Retest 1/2/3` into trendline. Third touch + `ob` + `sell s` = short trigger before displacement down.
- **Ambiguity:** `X` vs `1/2/3` numbering — `X` marks failed swing (inducement), numbers mark valid trendline touches. Code trendline touches only when swing actually touches line within tolerance, ignore `X` fake touches.

### Page 7 (Complex multi-phase, 94.102,5)
Additional labels beyond page 6:
- `Ce 0.5` (Confirmation Entry at 50%?), `buy s / sell s`, `Fair`, `0,5- / 0,5+`, `Sweep`, `Qm`, `M shiff [MSS]`, `Trendline 1-2-3`, `0.5 ob From upper body to lower body`, `+ob`, `Acumulation`, `M+sshiff`, `Distribution`, `M5 support becomes resistance`, `X / reversal`, `A`, `M`, `idm`, `Resistance sweep`, `break of structure Bos / idm / Indusment [inducement] / Clsd/mss/shift`, `QML`, `ce`, `0.5 Ob`, `Retest 2 / Manipulation`.
- Inset `market structure shift` candles + `break of structure` M-pattern diagram clarifies `inducement = middle dip that traps retails before real BOS`.
- **Ambiguity — `0.5` family:** `Ce 0.5`, `0,5-`, `0,5+`, `0.5 ob`, `0.5 Ob` all refer to same fib-50% concept but applied to different ranges (OB vs dealing range vs displacement leg). Bot must namespace: `OB50`, `Range50`, `Displacement50` separately; do not conflate.
- **Ambiguity — `Fair`:** appears twice (`Fair` near `buy s` and `sell s`). Means Business? Actually `Fair` = Fair Value / Equilibrium? Later pages clarify as `Fair` = origin of displacement? Treat as `Fair Value / Breaker origin`, not standalone signal until Part 02 clarifies.

## 6. Trendline Break + MSS Framework (Page 8 EN+ID mirrored)

Two stacked identical charts (candles top, line bottom) with 6 numbered callouts:

1. **Initial Phase – Bearish Trend / Fase Awal – Downtrend & Tekanan Harga**
   - `Descending Trendline / Price forms lower highs and lower lows / Price capped below trendline / Each swing high rejected / Swing lows repeatedly broken -> bearish continuation`
   - Includes `M30 support key levels` at bottom, `Breakout trendline` diagonal, `Swing high/low` red lines.
2. **Trendline Break & MSS / Break Trendline & Market Structure Shift**
   - `A strong impulsive candle breaks descending trendline / This is early signal, not entry / Price creates higher low / Then breaks previous lower high / Confirms shift bearish->bullish`
   - ID: `Terjadi candle impulsif menembus trendline / Ini bukan entry, tapi early warning perubahan trend / Harga membentuk higher low / Lalu break lower high sebelumnya / Bias berubah menjadi bullish`
   - **Critical for bot:** trendline break ALONE never triggers entry. Must wait for `higher low + break of prior lower high`. Code as `EarlyWarning` state, not `Entry`.
3. **Impulse & Consolidation / Fase Impuls & Konsolidasi**
   - `Bullish Impulse: Strong upward displacement confirms buyer dominance / Channel/Flag: Price pulls back in controlled descending channel / Bullish structure remains intact / Support & SNR tested multiple times and holds / No bearish MSS appears`
4. **Key Zones – Support & RBS / Area Kunci – Support, SNR, dan RBS**
   - `Classic Support/RBS: Previous resistance turns into support / Price reacts cleanly / Indicates smart money accumulation / ex-BO (Previous Breakout Area): Price retests breakout zone / Acts as valid support`
5. **Liquidity Sweep at Highs / Liquidity Sweep di Atas**
   - `Resistance & Swing High: Buy-side liquidity builds above equal highs / L-Sweep: Price briefly pushes above resistance / Stops taken / This is liquidity collection, not reversal`
6. **Entry & Final Expansion / Entry & Ekspansi Akhir**
   - `CE (Confirmation/Candle Entry): Entry near support after confirmation / Lower risk, higher reward / Strong Breakout: Price exits consolidation with force / Large bullish expansion / Buy-Side Liquidity Taken: Previous highs broken / Stops above highs triggered / Trend continuation confirmed`
- Footer labels: `buy side liquidity`, `L, Sweep`, `RESISTANCE`, `Swing high/low`, `ex-bo`, `market structure shift`, `ce / snr / Ts / Support`, `end of the circles` (fibo circles), `Displacement` vertical bar on right.
- **Visual ambiguity:** blue vertical bar (`Classic v/ support`) marks impulse candle; circles are Fib-time? `end of the circles` = time-based target? For bot, ignore circles for entry; use for optional time-stop.

## 7. Seven-Pillar Master Chart (Pages 9 ID + 10 EN + 11 zoom)

Pages 9-10 are same BTC/XAU chart (prices 122.444,18 down to 103.572,86) with 7 text blocks surrounding chart; page 11 is zoomed right-half. Blocks (ID / EN):

1. **Liquidity Sweep (Pengambilan Likuiditas)**
   - `Harga berkali-kali menyapu likuiditas: Buy-side = equal high / high sebelumnya; Sell-side = equal low / low sebelumnya / Pergerakan bukan acak, bertujuan mengambil stop loss + mengisi order besar institusi.`
2. **Market Structure Shift (MSS)**
   - `Setelah likuiditas diambil: Harga gagal lanjut arah sebelumnya / Terjadi break struktur internal / Muncul candle displacement kuat / Menandakan perubahan bias jangka pendek.`
3. **Premium & Discount (Konsep Premium & Discount)**
   - `Harga bergerak di antara: Premium zone -> ideal untuk sell; Discount zone -> ideal untuk buy / Entry terbaik: Setelah sweep + saat harga bereaksi di premium/discount.`
   - **Bot:** requires dealing-range high/low to compute premium (>50%) vs discount (<50%). Do not hardcode price values from screenshot.
4. **Dealing Range & Equilibrium**
   - `Setiap impuls membentuk dealing range: Dari high ke low impuls / Equilibrium (50%) menjadi titik magnet / Pola umum: bergerak dari ekstrem -> kembali ke equilibrium -> lanjut ke sisi berlawanan.`
5. **Session-Based Behavior / Perilaku Berdasarkan Sesi**
   - `Area vertikal berwarna = sesi aktif: London = manipulasi & ambil likuiditas; New York = ekspansi ke target utama / Pergerakan paling valid setelah market ambil likuiditas lebih dulu.`
   - **Visual:** light-blue vertical bands on chart = sessions. Bot needs session filter: `London = sweep/manipulation expected, New York = expansion; avoid entries mid-consolidation without sweep.`
6. **Support & Resistance Internal**
   - `Kotak dan garis horizontal menandai: Support & resistance internal / Area reaksi setelah displacement / Ini bukan S/R klasik, melainkan area reaksi hasil orderflow.`
   - Labels on chart: `CLASSIC/A`, `Ce/FG`, `INDUSMENT`, `BO/S`, `RRB`, `IF`, `SB/R`, `OPEN CLOSE`, `KEY/LYS`, `SUPPORT`, `TP FIBO CIRCLES`, `SEL SIDE LIQUIDITY`, `BUY SIDE LIQUIDITY`, `Ce/W`, `TS`, etc.
   - **Ambiguity:** many abbreviations overlapping same horizontal level. Resolution table for coder:
     - `BO/S` = Break of Structure (internal)
     - `M/SHIFT` = MSS
     - `RRB` = Resistance Becomes ...? Actually `RBS` variant spelling
     - `SB/R` = Support Becomes Resistance (bearish flip)
     - `IF` = Inducement Fake? / `TFR`? Keep as inducement marker, not entry.
     - `TS` = Turtle Soup (sweep) — synonym for L-Sweep.
     - `Ce/W`, `Ce/FG`, `OPEN CLOSE` = confirmation-entry / open-close levels.
7. **Final Objective / Target Akhir**
   - `Chart ends with price reaching major liquidity pool or HTF level / Once met, price either consolidates or prepares next manipulation cycle. / Target sudah "ditentukan" oleh likuiditas.`
- Left summary: `Kesimpulan Utama / Key Takeaway: Harga tidak bergerak sembarangan / Likuiditas selalu menjadi tujuan awal / Struktur memberi konfirmasi arah / Sesi memberi timing / Target sudah "ditentukan" oleh likuiditas. / Price does not move randomly / Liquidity comes first / Structure confirms direction / Sessions provide timing / Targets predefined by liquidity.`

### Page 11 zoom specifics (XAUUSD 91.692,40 bottom)
- Shows `SBR/SUPPRT BECOME`, `KEY/LEVELS`, `TRANDLINE [sic]`, `INDUCEMENT`, `MSS`, `TQM`, `BO/S`, `MSNR/RS`, `SNR`, `SB/R`, `SEL SIDE LIQUIDITY`, `BUY SIDE LIQUIDITY`, `CLASSIC/A`, `KEY/C`, `TS`, price ladder right side.
- Confirms pair is XAUUSD on TradingView (`DRAW ON LIQUIDITY`, `01:36:38` timestamp) — strategy applied to gold, volatile, wide stops needed.
- **Bot note:** abbreviations `TRANDLINE`, `INDUSMENT`, `Acumulation` are typos but consistent; normalize in code enum to `TRENDLINE`, `INDUCEMENT`, `ACCUMULATION` to avoid string-mismatch bugs.

## 8. Codable State Machine Derived from Part 01

```text
STATE 0: HTF_BIAS (H4) = bullish if HH+HL, bearish if LH+LL, else NEUTRAL -> NO TRADE
STATE 1: POOL_MAP = list equal highs/lows + prior day high/low + session high/low
STATE 2: SWEEP_DETECT (M5): wick pierces pool AND body closes back inside AND displacement threshold not exceeded
STATE 3: ZONE_BUILD: SNR line + OB (last opposite candle) + OB50; tag Premium (>Range50) vs Discount (<Range50)
STATE 4: TOUCH_COUNT++ on each wick touch; if >3 without reject -> mark WEAK
STATE 5: CONFIRM: engulfing OR rejection wick (>50% range) OR close-back-in-range OR MSS break on LTF
STATE 6: ENTRY: at OB50 or after LTF BOS retest; SL beyond sweep extreme + buffer; TP next liquidity pool; min RR 1:1.5
STATE 7: INVALIDATE if: body close beyond zone with momentum, HTF flips, no sweep, over-touched
```

## 9. What Is NOT Yet Covered (Deferred to Later Parts)
- Quasimodo (Qm/QML) mentioned but not defined — appears pages 7-8 as `Qm`, `Q` — full taxonomy expected later.
- `Fair` vs `FVG` vs `IF` distinction unclear — needs later FVG pages.
- `X / reversal`, `Ce 0.5` precise fib rules — needs later CE pages.
- Session time windows (exact GMT hours for London/NY killzones) not numbered — must extract if later pages give hours.
- `TP FIBO CIRCLES / end of circles` time projection — ignore until defined.

---
*End of Part 01 — next: Part 02 pages 12-23.*
