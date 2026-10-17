# ALCHEMIST 02 — Part 02: XAUUSD Full-Cycle, SNR Basics, Sweep + Fresh Logic (Pages 12-23)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-12.jpg` through `-23.jpg`
> Covers: H1 XAUUSD 4245→3886 annotated cycle (line + candle + zoom), ID/EN bullish-phase playbook, SNR basics divider, classic V/A buying/selling, 4-type taxonomy intro, SNR+liquidity-sweep theory, sweep-of-previous-candle note, SNR marking + fresh/unfresh + storyline + 50-method entries.

## 1. Pages 12-14 — XAUUSD 1H Annotated Master Cycle (Same Move, 3 Views)

All three are the same XAUUSD 1H down-then-up-then-down structure from ~4245,033 top to ~3886,050 bottom. Author shows it three times to teach eye-training:

### Page 12 — Line view (07:51, 4096,744)
- Top: `CE/.H`, `C/A` (Classic/A?), `OC/L` (Open-Close level?) in red diagonal, `-Ts` (minus Turtle Soup = sweep short?).
- Mid-left: `BS!` (Break Structure!), `MSS` (Market Structure Shift).
- Center: `rispeck fvg [respect FVG]` with dot — price respects a bullish FVG before dropping. `BMS` (Break Market Structure?), `SEL SIDE LIQ` long horizontal, `-Ts` pink box (turtle-soup short zone).
- Center-bottom: `+Ts` (turtle-soup long), `BS!`, `IFS` (Inducement Fake Sweep?), `IS`, `CE/L`, `SSL/CV` (Sell-Side Liquidity / Consequent Violation?).
- Right: `MSNR SS`, `BUY SIDE LIQ`, `R`, `C/L`, `VERSION`, `+Ts`, `KEY/LEVELS`, `MSNR RVRSL [reversal]`, `CE/`, `SWE`, `3.983,217 / 3.964,912 / 3.955,352 / 3.944,594 / 3.928,207 / 3.915,237`.
- Faint background arcs: `-5 / -4 / -2,5 / -2 / -1` — Fib-time/circle projection, ignore for entries.
- **Bot reading:** line view is used to see `MSS`, `BS!`, `CE` without wick noise. Code MSS on close-price series as well as candle series; if they disagree, prefer candle close but log both. Line view `rispeck fvg` still refers to candle FVG zone (pink boxes) — FVG must be detected on candles even when displaying line.

### Page 13 — Candle view (07:04, same prices)
- Same labels but now candles visible. Confirms:
  - `MSS` = small consolidation break left side.
  - `rispeck fvg` = doji-like pause atop a displacement leg — must hold; if later closed through with body, FVG invalid.
  - Pink vertical boxes = FVG / turtle-soup zones (`-Ts` at sell-side, `+Ts` at lows, large pink on right at `BUY SIDE LIQ` sweep high and far-right breakdown).
  - Grey vertical bands = session/accumulation? Actually `KEY/LEVELS` bands.
- **Visual ambiguity:** `BS!` appears 3 times at different heights. They are not equal: first is LTF BOS, second is internal BOS, third near `MSNR SS` is HTF BOS. Bot must namespace `BOS_LTF`, `BOS_INTERNAL`, `BOS_HTF`; do not treat all `BS!` as same strength. Only HTF BOS flips bias.

### Page 14 — Zoomed bottom-right (06:33)
- New labels: `MSNR PVRSL [MSNR reversal]`, `CE/.H`, `SWE`, `CRSG` (Crossing? Actually `CRSG` = Confirmation Signal?), `CE/.H` second, `SWE`, `LTT`, `MSNR WE`, `SNR LV`, `KEY`, `TRAMLN [trendline]`, `LIT`, `IFR` (Inducement Fake Reversal?), `INFR` (Inducement Fake Reversal? internal fractal?), `ID` (Inducement?), `S`, `SNR`, `KEY/.S`, `SF`.
- Dotted diagonal `SNR LV` trendline from lows to highs — shows SNR levels themselves can be diagonal (trendline SNR). Bot trendline module must feed into SNR validator, not run isolated.
- Red dots on highs = sweep points (`SWE`). `=` marks = equilibrium / CE midlines.
- **Coding rule:** any label containing `SWE`, `Ts`, `SSL`, `BSL`, `BUY SIDE LIQ`, `SEL SIDE LIQ` belongs to liquidity subsystem. Any containing `MSS`, `BS!`, `BMS`, `M SHIFF` belongs to structure subsystem. Any containing `CE`, `C/A`, `C/L`, `KEY`, `SNR`, `MSNR` belongs to zone subsystem. Author mixes them on one line; bot must split by prefix.

## 2. Pages 15 (ID) + 16 (EN) — Bullish Structured Market Playbook

Identical content, ID + EN. This is the canonical 7-step bullish template. Must be coded as phased state machine:

### Overall Context / Gambaran Umum
`Chart shows well-structured bullish market where price: 1. Clears liquidity (sweep), 2. Confirms structure, 3. Re-accumulates, 4. Expands toward higher targets.`

### 2.1 Accumulation & Liquidity Phase (left-bottom)
- `Price trades in range/consolidation, Multiple sell-side sweeps (equal lows), Stops from both buyers+sellers taken / Banyak stop loss buyer & seller diambil`
- Purpose: `To clear market before real move / Mengosongkan market sebelum move besar dimulai.`
- **Bot:** accumulation = `RangeWidth < ATR*threshold for N bars AND >=2 sweeps of range extremes`. Do not mark every sideways as accumulation; require sweeps.

### 2.2 MSS – Bullish Confirmation
- `After sell-side taken: Price forms Higher Low, Internal structure broken upside, Strong bullish impulse appears. / Setelah sell-side diambil: Higher Low, break struktur internal, impuls naik jelas.`
- This confirms bullish bias, not yet entry.

### 2.3 Impulse & Dealing Range
- `Bullish impulse creates dealing range: Impulse low -> impulse high, Equilibrium (50%) acts as key reaction. / Impuls naik membentuk dealing range: Low impuls - High impuls, Midpoint/Equilibrium 50% menjadi area reaksi penting.`
- `Instead of immediate continuation: controlled retrace, structure remains intact above key levels.`
- **Visual:** impulse legs drawn as near-vertical displacements; dealing range box from wick-low to wick-high. Equilibrium dashed midline with `=` marks.
- **Coding:** `DealingRange = [ImpulseLow, ImpulseHigh]`, `EQ = (High+Low)/2`. Premium = above EQ, Discount = below EQ. BUY only in discount per section 2.6.

### 2.4 Re-Accumulation (Continuation Phase)
- `Boxed middle area: Bullish consolidation, Minor stop hunts / fake breakdowns, Respect Key SNR / CE (Consequent Encroachment) / Konsolidasi bullish, fake breakdown (stop hunt kecil), respect Key SNR/CE.`
- Indicates `Smart money still building longs.`
- **Ambiguity:** re-accumulation looks like reversal (red candles down). Distinguish by: holds above `KEY/LEVELS` + `CE/F` (Consequent Encroachment Flip?) and sweeps are small (`-Ts` wicks, not body closes below). Code: `ReAccumulation = pullback < 50% of impulse AND closes back above CE AND LTF MSS bullish`.

### 2.5 Draw on Liquidity (Price Objective)
- Labels: `DRAW`, `Profit Point`, `Key SNR / MSNR` show price being `Pulled toward buy-side / Targeting previous highs or equal highs / Ditarik menuju buy-side, Target di high sebelumnya / equal high.`
- **Bot:** target subsystem = opposite liquidity pool, not fixed RR. `LongTarget = nearest BuySide pool (equal highs, prior high, `B/ES`, `PROFIT POINT`)`. `DRAW` and `CUTTING` lines on chart are target rails — implement as rays to next HTF level.

### 2.6 Entry Logic (How to Trade This Structure) / Cara Membaca Setup
- `Ideal BUY entries: In discount, After: Minor liquidity sweep, Internal MSS/BOS, Reaction from Key Level or SNR zone. / BUY di discount setelah: Liquidity sweep kecil, MSS/BOS internal, Reaksi di Key Level/SNR.`
- `Stop: Below most recent swing low / structure. / Di bawah swing low / struktur terakhir.`
- `Targets: Range high, Profit Point, Upper liquidity pools.`
- **Filters:** `DOJI`, `FTL`, `B!`, `C`, `RR`, `S`, `CE/L`, `KEY/SNR` appear as micro-confirmations. `DOJI` at equilibrium = pause, not reversal. Require sweep+MSS, not doji alone.

### 2.7 Final Expansion
- `On right: Price breaks range, Bullish structure intact, Expands toward HTF liquidity objectives. However: Price now in premium -> Better for profit-taking, not new entries. / Harga break range, struktur tetap bullish, menuju HTF liquidity objective. Namun area atas sudah premium -> cocok ambil profit, bukan entry baru.`
- **Bot rule:** inhibit new longs when `Price > RangeEQ + premium buffer` even if sweep occurs. Switch to `TakeProfitOnly` mode.

### Key Takeaways box
`Liquidity always taken first, Structure confirms direction, Consolidation is preparation not weakness, Price moves discount -> premium, Liquidity defines target.`

## 3. Page 17 — Divider: BASICS OF SUPPORT AND RESISTANCE (SNR)
- No logic, marks start of SNR子module. All pages 18-23 belong here.

## 4. Page 18 — Dasar-Dasar / Basics of SNR + Classic V/A Candle Schematics

### Definitions (ID+EN identical)
- SUPPORT: `A price level where market expects enough buying pressure to stop fall. Causes price to stumble and may bounce. Often occurs where price dropped multiple times but cannot break below.`
- RESISTANCE: `A price level where market expects enough selling pressure to stop rise. Causes price to hit ceiling and may downturn. Often where price rose multiple times but cannot break above.`
- Labels: `(1) BUYING - CLASSIC V (Gambar menunjukkan pola candle pada level support)` and `(2) SELLING - CLASSIC A (pola candle pada level resistance)`.

### Diagrams — Critical for bot
- **BUYING (left):** two candles over `SUPPORT` line: first dark candle closes below line (wick pierces), second white candle opens at line and closes up. Lower inset `CLASSIC/V` shows V-shape: dip below then reclaim. Text: `RESISTACE [sic]`.
- **SELLING (right):** mirror: dark + white candles under `RESISTACE` line at highs, inset `CLASSIC/A` shows A-shape (spike above then reject).
- **Visual ambiguity resolved:**
  - Support/resistance line is drawn at `close` level, not wick extreme. Wick piercing below/above is EXPECTED, not break. Break = second candle body closing beyond, not wick.
  - `CLASSIC/V` vs `CLASSIC/A` naming: V = bullish reclaim shape, A = bearish rejection shape. Later pages abbreviate to `C/V`, `C/A`, `CE/W`, `Ce`. Normalize: `ClassicV = BuySetup`, `ClassicA = SellSetup`.
  - Small inset lines (`+` crosses) are entry/stop markers, not structure. Ignore for zone detection.

### Important Note / Catatan Penting
- `The first candle closes below support. The next candle opens at support level. / Candle pertama menutup di bawah support, candle berikutnya membuka di level support.`
- Analytical meaning: `Price dipped below but buying pressure entered, causing next open back at level. Signal buying strength returning, bounce may occur. Helps identify reversals more accurately.`
- **Coding:**
  ```
  ClassicV_Buy = Close[i-1] < Support AND Open[i] >= Support - tolerance AND Close[i] > Open[i]
  ClassicA_Sell = Close[i-1] > Resistance AND Open[i] <= Resistance + tolerance AND Close[i] < Open[i]
  // Tolerance = ATR*0.05 or 2-3 pips on XAUUSD M15; wick pierce depth < ATR*0.3 else treat as sweep, not classic.
  ```

## 5. Page 19 — Types of SNR: SELLING Classic A (No-Retest Drop)

Philosophy block (ID+EN):
- `Support and resistance are not just lines to look nice. They are footprints of market behavior and reflection of trader psychology. / Bukan sekadar garis agar terlihat rapi. Itu adalah jejak perilaku pasar dan cerminan psikologi trader.`
- `Many types, each with characteristics and strength. Some for reversals, some for continuation, some reveal buyer vs seller control.`
- `Today I show four main types I personally use... Once you understand, you'll never see market same way.`

### Classic A rules (Selling)
1. `Wait for price to reach SNR level (support or resistance). / Tunggu harga mencapai area SNR.`
2. `Price touches level and drops — no retest. / Harga menyentuh lalu jatuh — tanpa retest kembali.`
- Diagrams: bottom shows two candle variants (grey+dark) under `CE/H CLASSIC/` with `Selling` arrow down; line diagram on right shows `1-2-3 RESISTANCE` with magnifier on first touch-drop (no second touch). `CLASSIC/A` line diagram shows sharp A-peak, immediate fall.
- **Bot distinction:** ClassicA = `TouchCount==1 AND immediate displacement away (body range > ATR) AND no return within N bars`. If price returns and retests, it is NOT ClassicA — reclassify as ClassicV/A-retest or sweep type (next pages). This prevents mislabeling every touch as ClassicA.

## 6. Page 20 — Types 1.1 BUYING (Rejection vs Liquidity Variants)

Same philosophy header, now BUYING side. Two candle schematics labeled `3` (left) and `4` (right) over `SUPPORT`:

- **Type 1 (left diagram 3):** `You can see there was already one rejection. Then price moved up to seek key level before dropping again with another rejection, and only then continued. / Sudah ada satu penolakan (rejection). Kemudian harga naik mencari level penting, sebelum turun lagi dengan penolakan lainnya, dan setelah itu barulah melanjutkan.`
  - Visual: two tall bullish candles at left (first rejection wicks), then gap, then small bearish candle at `2` marked `Buying` bracket — second rejection at same support. Points `1` and `2` both dots on support line.
  - **Code:** `BuyType1 = RejectionCount>=2 at same zone + intervening rally to key level (e.g. prior high / CE) + second hold`. Stronger than single touch; allow entry on second rejection close.

- **Type 2 (right diagram 4):** `Similar to Type 1, but no rejection. Instead, there is liquidity. Presence of liquidity before reaching zone indicates strength. / Mirip tipe 1, tetapi tidak ada penolakan. Sebaliknya, terdapat likuiditas. Adanya likuiditas sebelum menyentuh zona menunjukkan kekuatan.`
  - Visual: two tall bullish candles, then small `—` marker (liquidity) mid-air, then dark square candle dropping to support dot, `S` + `Buying` bracket.
  - **Ambiguity:** Type 2 has NO wick rejection at support yet — support holds via body? Actually dot is at open? Means liquidity grab above (stop hunt) fuels drop that holds at support without prior wick. Bot must not require wick touch for Type 2; require `LiquiditySweepAbove within lookback + body hold at support`.
  - **Decision table:**
    ```
    if Rejections>=1 and LiquiditySweepBefore==false -> Type1
    if Rejections==0 and LiquiditySweepBefore==true -> Type2 (liquidity-backed, still valid)
    if both true -> strongest (Type1+2 confluence)
    ```

## 7. Page 21 — What Is SNR + Liquidity Sweep? (Bilingual Theory)

### Liquidity Sweep definition
- `A sweep occurs when price pushes above previous high or below previous low to trigger pending/stop orders. Many mistake as breakout, but in reality smart money tactic to collect liquidity before moving true direction. / Artinya ketika harga naik menyentuh/menembus high sebelumnya atau turun menembus low untuk memicu pending/stop order. Trader sering salah paham breakout, padahal strategi smart money ambil likuiditas sebelum gerak arah sebenarnya.`

### Using Sweep with SNR
- `When price approaches SNR, many orders resting there. If sweep occurs around zone, market may be testing level by collecting stops before reversing. / Ketika harga mencapai area SNR, biasanya banyak order menunggu. Jika sweep di area ini, market sedang mengetes zona dengan menyapu stop loss terlebih dahulu sebelum berbalik.`
- Examples:
  - `At Resistance: Breaks above to collect buy-stops, then drops sharply -> Sell (short). / Di Resistance: Menembus ke atas ambil stop buy, lalu turun tajam -> sinyal sell.`
  - `At Support: Breaks below to collect sell-stops, then bounces strongly -> Buy (long). / Di Support: Turun menembus ambil stop sell, lalu memantul kuat -> sinyal buy.`

### Importance in Confirming SNR
- `Increases accuracy — not every touch creates reversal, but when sweep confirms, probability significantly higher. / Meningkatkan akurasi — tidak semua sentuhan berarti reversal, tetapi jika ada sweep, keberhasilan lebih tinggi.`
- `Reveals smart money — shows real buying/selling from large players, not noise. / Menunjukkan tekanan beli/jual nyata dari big players, bukan noise.`
- `Reduces false breakouts — helps identify genuine vs liquidity grab. / Membantu bedakan break benar atau hanya grab.`

### Summary / Ringkasan
`Liquidity Sweep + SNR is not just identifying levels. It is about understanding intention, who collects liquidity, and using that to determine whether next move is likely reversal or continuation. / Bukan hanya melihat support/resistance. Ini tentang memahami apa yang dilakukan market di balik layar — siapa yang mengumpulkan likuiditas — dan menggunakannya untuk menentukan tren selanjutnya berbalik atau berlanjut.`
- **Bot implication:** sweep is mandatory filter for high-probability trades. Implement `SweepConfirmed` boolean; allow `NoSweep` trades only as low-risk / half-size with explicit flag.

## 8. Page 22 — Note: Sweep of Previous Candle + Retest Reliability

### Core note (ID+EN)
- `Liquidity Sweep + SNR refers to sweeping high or low of previous candle. / Adalah penyapuan terhadap high atau low candle sebelumnya.`
- `Confirming SNR with sweep means we want to see liquidity taken from previous high/low when price taps SNR. This indicates: zone tested, high probability zone will hold and reverse. / Mengonfirmasi SNR dengan sweep berarti ingin melihat likuiditas diambil pada high/low sebelumnya ketika harga menyentuh SNR, yang menunjukkan zona sudah diuji, kemungkinan besar bertahan dan reversal valid.`
- **Narrow definition alert:** here sweep = previous *candle* high/low, not just prior swing/equal highs. Bot must implement TWO sweep scopes:
  1. `MicroSweep = High[i] > High[i-1] and Close[i] < High[i-1]` (or low equivalent) — for LTF confirmation.
  2. `SwingSweep = High[i] > PriorSwingHigh and Close[i] < PriorSwingHigh` — for HTF liquidity.
  - Page 22 refers to (1); pages 12-16 pools refer to (2). Require at least one, score higher if both align.

### Diagrams
- Top-left SELLING (Resistance -> SWE -> CLASSIC/A): tall grey candle, small dark candle sweeping its high? Actually `RESISTANCE` top line, `SWE` mid-line, `CLASSIC/A` lower. Shows sweep of prior candle high then rejection down.
- Top-right BUYING (Support -> SWE -> CLASSIC/V): small dark, light, tall dark candles rising off `SWE`/`SUPPORT` lines, labelled `CLASSIC/V`.
- Bottom-left SELLING detail: `SWE` wick box left, `Price - Rejection` arrow at `CLASSIC/A` line, dark displacement candle down.
- Bottom-right BUYING detail: mirror, `Price - Rejection` arrow up off `CLASSIC/V`.
- Labels `A` (peak) and `V` (valley) line icons on far left confirm shape naming.

### Another Note / Catatan Tambahan
- `If SNR occurs with sweep and later price returns to touch same zone, we can consider that level highly reliable — strong and valid zone. / Jika SNR terjadi bersamaan sweep dan kemudian ada candle menyentuh kembali level tersebut, maka zona sangat kuat / valid dan kuat.`
- **Bot:** implement `ZoneStrength`: `+1 for sweep, +1 for retest-hold`. `Strength>=2 => HIGH_RELIABILITY`. Allow re-entry on second touch only if first touch held (no body close through). This contradicts naive fresh-only logic; handled next page via fresh/unfresh max-2 rule.

## 9. Page 23 — SNR Marking: Close Price, Fresh/Unfresh, Storyline, 50-Method

Most codable rules page in Part 02. Bilingual (EN left, ID right).

### 9.1 Marking SNR — Use Closing Price
- `USE THE CLOSING PRICE OF THE CANDLE. / GUNAKAN HARGA PENUTUPAN (CLOSING) DARI CANDLE.`
- **Bot:** draw SNR at `Close[i]` of pivot candle, not High/Low. Wick extremes belong to sweep subsystem. This single rule resolves many visual mismatches where line sits inside wicks on pages 12-14.

### 9.2 Fresh vs Unfresh (1.1)
- `A zone is fresh if never touched. / Zone dianggap fresh jika belum pernah disentuh.`
- `If touched by wick -> becomes unfresh. / Jika tersentuh wick -> menjadi unfresh.`
- `If broken through by full candle body -> zone turns fresh again. / Jika ditembus full body -> menjadi fresh kembali.`
- `A zone can be used no more than 2 times. / Hanya bisa digunakan maksimal 2 kali.`
- `Exception: If daily gap caused strong reaction before, zone may be reused without 2-time limit. / Jika pernah terjadi daily gap yang menghasilkan reaksi kuat, dapat digunakan kembali tanpa batas 2 kali.`
- Summary: `FRESH = Never touched / Belum pernah disentuh; UNFRESH = Touched by wick / Tersentuh wick; FULL BODY BREAK = Becomes fresh again / Menjadi fresh lagi; MAXIMUM 2 USES / MAKSIMAL 2X.`
- **Visual ambiguity + coding:**
  ```
  TouchTest = WickOverlapsZone AND BodyClosesInsideOrBeforeZone -> Unfresh, UseCount++
  BreakTest = BodyClosesBeyondZone + displacement (e.g. body > ATR*0.5) -> Refresh, UseCount=0, flip role (S->R or R->S)
  Invalidate if UseCount>=2 AND NOT HasDailyGapException
  DailyGapException = GapSize > ATR AND PriorReaction > ATR*1.0 (tune)
  ```
  - Human eye often calls a deep wick pierce a "break" — bot must NOT; only body close counts.

### 9.3 Storyline (Price Action Structure)
- `Price tends to touch fresh zone then get rejected with wick. Lower TF (one level below) must show clear breakout (external). After that, price moves from one fresh zone to another (e.g. daily to daily, weekly to weekly). Breakout does not always have to happen at fresh zones. / Harga cenderung menyentuh zone fresh dan kemudian rejected oleh wick. TF lebih rendah (satu level di bawah) harus menunjukkan breakout jelas (external breakout). Setelah itu, harga bergerak dari satu fresh zone ke fresh zone lain (daily ke daily, weekly ke weekly). Breakout tidak harus selalu terjadi di fresh zone.`
- `For weekly storylines: watch roadblocks from lower TF (e.g. daily can block weekly). Example: If weekly bullish but daily bearish, weekly cannot continue until daily reverses. / Untuk storyline weekly: perhatikan hambatan dari TF lebih rendah (daily bisa menghalangi weekly). Contoh: jika weekly bullish tetapi daily bearish, weekly tidak bisa lanjut naik sampai daily berubah bullish.`
- Summary: `Clear storyline -> Reject from zone -> Breakout -> Move to next zone. Always watch lower TF storylines — they may conflict.`
- **Bot:** implement multi-TF gate:
  ```
  AllowWeeklyLong only if DailyStoryline != bearish_displacement_down
  AllowDailyLong only if H1Storyline != bearish_displacement_down
  StorylineState per TF = {AtFreshZone, Rejected, BrokenExternal, InTransit}
  ```

### 9.4 Entries — 3.1 High Risk, 3.1.1 The "50 Method" / Metode "50"
- `Example: Price touches daily zone -> then use multi-timeframe (e.g. H1/M15) -> set stop loss around 10 pips. / Contoh: Harga menyentuh daily zone -> lalu gunakan multi-timeframe (H1/M15) -> set stop loss sekitar 10 pips.`
- `Correct way: Direction must align with higher storyline (e.g. weekly). If weekly bullish -> look for buys at daily zones supporting weekly. / Cara benar: Arah entry harus sesuai storyline TF lebih tinggi (weekly). Jika weekly bullish -> cari buy di daily zone searah weekly.`
- **Ambiguity:** "50 Method" name vs "10 pips SL" — 50 refers to 50% / 50-pip? Context + later pages suggest 50% OB entry with tight 10-pip SL on LTF confirmation (M15/H1) when HTF zone touched. Code as: `HTF Zone touch -> drop to LTF -> wait LTF sweep+reject at OB50 -> enter with SL 10 pips (XAUUSD: 100 points? tune per symbol) + HTF-structure SL fallback`. Flag as `HIGH_RISK` because counter-trend LTF scalps against HTF wick; require HTF bias alignment to lower risk.

## 10. Consolidated Bot Rules from Part 02

```text
SNR_Line = Close[pivot] (not high/low)
ClassicV = Close[i-1]<S AND Open[i]>=S-tol AND Close[i]>Open[i] -> Buy bias
ClassicA = Close[i-1]>R AND Open[i]<=R+tol AND Close[i]<Open[i] -> Sell bias
ClassicA_noRetest = TouchCount==1 AND displacement away within 3 bars AND no return in N bars
BuyType1 = Rejections>=2 with mid-rally to key level between
BuyType2 = No rejection BUT SweepBefore==true (liquidity-backed)
MicroSweep = sweep of High[i-1]/Low[i-1]; SwingSweep = sweep of swing/equal highs/lows; need >=1, both = strongest
Fresh = never touched; WickTouch -> Unfresh UseCount++; BodyBreak -> Fresh again UseCount=0 + role flip
MaxUses = 2 unless DailyGapException (gap + strong prior reaction)
ZoneStrength = Sweep?1:0 + RetestHold?1:0; >=2 => HIGH_RELIABILITY, allow re-entry
StorylineGate: HTF direction must agree with LTF; daily bearish blocks weekly bullish
50Method: HTF touch -> LTF (H1/M15) OB50 + sweep -> SL ~10 pips, HIGH_RISK tag, only with HTF bias
Target = opposite liquidity (DRAW/Profit Point/buy-side), not fixed RR; inhibit new entries in premium (for buys) / discount (for sells)
```

---
*End of Part 02 — next: Part 03 pages 24-35.*
