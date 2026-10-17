# ALCHEMIST 02 — Part 03: Fresh vs Unfresh, RBS/SBR Flipzone, QM/QMR/QMM/QMC (Pages 24-35)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-24.jpg` through `-35.jpg`
> Covers: fresh/unfresh deep-dive (2 versions), LL validity filter, RBS/SBR divider + definitions + close-rule + XAU 2400 example, Quasimodo divider + QM trap theory + QMR deceptive reversal + QMM fake-break + QMC fake-continuation + real QM line vs candle example.

## 1. Pages 24-25 — Fresh vs Unfresh: Two Definitions That Must Be Reconciled for Bot

Author gives slightly different wordings on p24 vs p25 vs p23. This is the biggest ambiguity in Part 03; code must pick one consistent implementation.

### Page 24 — WHAT IS UNFRESH / FRESH? (BUYING charts)
- EN: `Unfresh SNR = level already been touched. If broken by full candle body, becomes fresh again. Each level only up to two times. If daily gap created strong reaction previously, may be reused without two-use rule.`
- `A level is fresh until touched. If touched by wick, becomes unfresh.`
- `Fresh SNR = level not been touched yet (still fresh).`
- ID identical: `Unfresh = sudah pernah disentuh. Jika ditembus candle body jadi fresh kembali. Maksimal 2 kali. Daily gap kuat boleh dipakai kembali tanpa 2 kali.`
- Summary: `Unfresh = already used. Fresh = not used yet. Same logic sell-side.`
- Charts: two BUYING uptrend-then-drop examples with `UNFRESH SNR` vs `FRESH SNR` horizontal at lows. Unfresh chart shows multiple touches along the way (level used); Fresh chart shows clean first touch after impulse (unused).
- **Bot rule v1 (touch-based):** `Fresh=True initially; on WickTouch -> Fresh=False, UseCount++; on BodyBreak -> Fresh=True, UseCount=0, flip role.`

### Page 25 — FRESH AND UNFRESH SNR LEVELS (refined, body-based)
- EN (critical shift): `Fresh SNR = level NOT broken by candle before. Even if tapped or broken by wick, still fresh unless body breaks it.`
- `Unfresh SNR = level already touched or broken by wick or body before.`
- ID: `Fresh = belum pernah ditembus candle sebelumnya. Jika ditembus body tetap dianggap fresh [typo? should be unfresh? read EN]. Unfresh = sudah pernah disentuh/ditembus wick sebelumnya.`
- Why fresh matters: `Represents institutional orders, liquidity present — price frequently reacts/bounces strongly. / Area institusi menggunakan likuiditas, harga sering memantul.`
- Observation: `If touches wick and bounces -> still valid / hanya menyentuh wick dan memantul -> masih valid. If touches body -> not valid / menyentuh body -> tidak valid.`
- Price movement: `Generally moves from one fresh HTF level to another fresh on opposite side. Along way may break LTF swing highs/lows but eventually gravitates to next fresh HTF. / Bergerak dari fresh HTF ke fresh sisi berlawanan. Dapat mematahkan LTF swings tetapi akhirnya mencapai sisi lain fresh HTF.`
- Diagrams: `FRESH LEVEL BROKEN` (wick pierce through then body? still labelled broken?), `FRESH SNR` box, `STILL FRESH` arrow pointing to wick-only pierce, `FRESH LEVELS BROKEN -> SNR` cascade.
- Validation checklist (both languages):
  1. `Price has tapped wick/shadow / menyentuh wick/shadow`
  2. `Liquidity collected (sweep) / likuiditas sudah diambil`
  3. `Price in congestion/reaction zone / berada dalam zona konsolidasi/konsolidasi`
  - `If all three met, valid for buy/sell.`
- **Reconciliation for coder:**
  - p23-24: wick touch = unfresh (strict).
  - p25: wick touch = still fresh/valid, body touch = unfresh/invalid (loose, institutional view).
  - Resolution: implement TWO flags, not one:
    ```
    TouchState = FRESH (never touched) / WICK_TOUCHED / BODY_TOUCHED
    Tradable = (TouchState != BODY_TOUCHED) AND UseCount<2 AND SweepDone AND InReactionZone
    // p24 Unfresh = WICK_TOUCHED (weaker, second touch only with sweep+confirmation, reduced size)
    // p25 Fresh = not BODY-broken (still tradable on wick touches)
    // → First touch (FRESH): full size. Second wick touch (UNFRESH but not body): half size + require sweep. Body touch: invalidate unless full body break flips to new RBS/SBR fresh.
    ```
  - This satisfies both pages and matches real charts where second wick touch still holds (p26 example touches 2-3).

## 2. Page 26 — LL Filter, RBS Principle, Real 1-2-3-4 Example, Gap SNR

### 2.1 PENTING / IMPORTANT — Lower Limit (LL) invalidation
- `When price rejects from fresh support, buy still valid as long as candle closes above lower limit (LL). If closes below LL, setup immediately invalid. / Ketika rejection pada fresh support, entry buy masih valid selama closing di atas batas bawah (LL). Jika closing di bawah, kehilangan validitas.`
- Diagrams: left `UL / FRESH / LL` with tall bullish candle closing above red `LL` line (valid). Right `UL / UNFRESH SUP V / LL` with dark bearish candle closing below (invalid, red dot).
- **Coding:** zone is not a line but band `[LL, UL]`. `UL = SNR close line, LL = zone bottom (e.g. sweep low or OB low)`. `ValidBuy = Close > LL`. Wick below LL allowed; close below = fail. Mirror for sells with `UH`.

### 2.2 RBS Principle / Prinsip RBS
- `After price breaks resistance, it often flips into new support. This can be used as buy entry. / Setelah menembus resistance, sering berubah fungsi menjadi support baru untuk entry buy.`
- Leads to Flipzone concept below.

### 2.3 HERE IS A REAL MARKET EXAMPLE (1-2-3-4)
- Labels:
  1. `Original SNR (Resistance) / Titik asal SNR`
  2. `First rejection (weak resistance) / Rejection pertama (lemah)`
  3. `Second rejection (weak) / Rejection kedua (lemah)`
  4. `Rejection from strong support (used for direct entry) / Rejection dari support kuat (entry langsung)`
- Chart: horizontal resistance line with `UPTREND WITH A PAUSE BEFORE CONTINUATION`, sharp V-drop to trendline, rally breaking line with strong bullish candle, retest, continuation. `(FLIPZONE) Flipzone` arrow at break-retest.
- Text: `Price shows uptrend with pause before continuation, confirming strength.`
- Flipzone definition: `A strong bullish candle breaking weak resistance creates new structure, turning previous resistance into solid support (RBS) after breakout. / Candlestick bullish cukup kuat menembus resistance lemah akan membentuk struktur baru mengubah resistance lama menjadi support kuat (RBS). This zone is known as Flipzone.`
- Key note: `Gap SNR typically forms from strong momentum candle, indicating clear buying/selling pressure from institutional participants. / Biasanya berasal dari momentum kuat, menunjukkan tekanan beli/jual jelas. Example in next chart.`

## 3. Pages 27-29 — RBS/SBR Module

### Page 27 divider: `WHAT IS RBS / SBR IN TRADING / @abayforex` — no logic.

### Page 28 — RBS vs SBR with FAKE vs BRAKE diagrams
- Header: `APA ITU RBS/SBR? Aku punya contoh nyata dari trading-ku sendiri. / WHAT IS RBS/SBR? Real examples from my own trading.`
- RBS: `Previous resistance turns into support. Happens when price breaks above and pulls back, old resistance holds. Tip: wait long at RBS because often pushes back up. / Level resistance sebelumnya berubah menjadi support ketika menembus dan mencoba turun kembali namun tertahan. Tunggu buy di RBS karena sering mendorong naik.`
- Diagrams: left `FAKE` (break attempt that fails back below — do NOT mark RBS), right `X / RBS / BRAKE [break]` (body breaks above `X` line then holds on retest at `RBS` line, then `BRAKE` arrow candle confirms).
- SBR mirror: `Previous support turns into resistance. Breaks below then pulls back, old support acts as resistance. Wait short because often rejects down.`
- Diagrams: left `FAKE` (wick below but closes back above — not SBR), right `BRAKE / RBS [should be SBR, typo] / RBS` (body breaks below then retest rejects).
- **Visual ambiguity:** author labels SBR chart's line `RBS` (copy-paste error). Do not trust text label; infer from direction: break down + retest from below = SBR regardless of label. Code by price action, not label string.
- **FAKE vs BRAKE distinction for bot:**
  ```
  FAKE = Wick pierces level BUT Close returns inside (sweep) -> NO flip, keep old role, expect reversal.
  BRAKE/BREAK = Body closes beyond level + displacement (e.g. range > 1.2*ATR or next candle confirms) -> flip role to RBS/SBR, old line becomes new opposite zone.
  ```

### Page 29 — Close-rule refinement, psychology, XAU 2400 example
- RBS refined: `Occurs when previous resistance turns into support AFTER price successfully breaks above AND closes above. Zone often entry for buyers on retest as bounces. / Kondisi ketika berubah menjadi support setelah berhasil menembus dan close di atas. Biasanya tempat buyer masuk saat retest.`
- SBR refined: `Happens when previous support turns into resistance AFTER price breaks below AND closes beneath. During retest sellers step in causing reject down.`
- **Critical addition vs p28:** close required, not just wick break. This overrides loose interpretation. Bot must require `CloseBeyond`, not `HighBeyond`.
- CE Concept: `RBS/SBR driven by market psychology and shift buyer/seller control. Breakout indicates dominant side taken over. When price returns (retest), many who missed breakout enter, reinforcing new S/R. / Terjadi karena perubahan sentimen/dominasi. Berhasil melewati level penting menunjukkan salah satu pihak lebih kuat. Saat kembali menguji (retest), trader menunggu konfirmasi masuk sehingga menjadi support/resistance baru.`
- Charts: `1. SELLING SBR` (rally to line, strong dark break down, sideways retest under line, then cascade) and `2. BUYYING [sic] RBS` (decline to line, strong light break up, retest holding, rally).
- Worked example: `If XAU/USD breaks above $2,400 (previous resistance) then retests while showing bullish rejection, level now acts as RBS. Look longs around $2,400 SL slightly below. / Jika menembus $2,400 dan retest dengan rejection bullish, area berubah menjadi RBS. Buka buy sekitar $2,400 SL sedikit di bawah.`
- Line icons: green V then RBS (support flip), red A then SBR (resistance flip).
- Extra notes:
  - `Higher TF (H4/Daily) give stronger RBS/SBR. / Semakin tinggi TF semakin kuat validitas.`
  - `Waiting for clear confirmation + retest increases accuracy.`
  - `RBS/SBR works better combined with liquidity, OB, bias, FVG. / Lebih efektif jika bersama likuiditas, OB, bias, FVG.`
- **Bot:** `RBS_Strength = TF_weight (M15=1, H1=2, H4=3, Daily=4) + Sweep?1:0 + OB_align?1:0 + FVG_align?1:0`. Require `>=3` for full size.

## 4. Pages 30-35 — Quasimodo Module (QM / QMR / QMM / QMC)

### Page 30 divider: `QUASIMODO IN TRADING` — no logic.

### Page 31 — QM: The Point Where Market Traps Majority
- `When we talk QM/Quasimodo, many recognize from Smart Money. Most powerful for high-probability reversals. / Ketika membahas QM, banyak mengenal dari Smart Money. Salah satu pola paling efektif identifikasi reversal akurasi tinggi.`
- Unique: `Doesn't just signal reversal — shows where market tricks most into wrong side. / Bukan hanya tanda kapan berbalik — tetapi menunjukkan di mana mayoritas tertipu.`
- Narrative: `During uptrend most believe keeps higher. Creates HH building confidence. Suddenly drops sharply breaks prior support. Then climbs back to retest same level... rejects and reverses — retest zone becomes QM level.`
- Simple: `QM is trap zone — convinces most wrong direction. If understand, spot reversal before others. / Area di mana market sengaja menipu mayoritas agar masuk arah salah. Jika paham bisa lihat entry lebih awal.`
- Structure Made Simple:
  - Bearish QM (Sell): `1. Keeps rising -> HH, 2. Pullback -> HL, 3. Rises again weaker then breaks below HL -> shift begins, 4. Returns to retest same area -> Sell Entry Zone. / Naik HH, pullback HL, naik lagi lemah lalu turun break HL struktur berubah, retest area sama titik sell.`
  - Bullish QM (Buy): `1. Keeps falling -> LL, 2. Pullback -> LH, 3. Drops again fails new LL then pushes strongly breaks above LH -> shift, 4. Pullback retest same zone -> Buy Entry. / Turun LL, pullback LH, turun lagi gagal LL baru lalu naik kuat break LH shift, pullback entry buy.`

### Page 32 — QMR (Quasimodo Reversal): Most Deceptive Reversal
- `One of most deceptive reversals. When preparing to reverse, rarely turns immediately. Often creates fake continuation — making traders believe trend continues. Then out of nowhere sharply reverses. That moment is QMR. / Pola pembalikan paling menipu. Ketika siap berubah arah, tidak langsung berbalik. Biasanya membuat gerakan palsu terlebih dahulu — membuat percaya tren masih lanjut. Lalu tiba-tiba berbalik kuat dari arah tak terduga.`
- Formation: `Appears when major trend losing strength. Uptrend: HH -> HL -> LH -> then breaks into LL. Downtrend: LL -> LH -> HL -> then breaks into HH. / Struktur ketika tren besar mulai melemah. Uptrend HH HL LH lalu break LL. Downtrend LL LH HL lalu break HH.`
- Simple: `Pretends continue then suddenly breaks trapping wrong. Reflects smart money manipulating, causing retail wrong side before reversal.`
- How to trade: `After QM forms: 1. Structure break (BOS), 2. Price returning retest same level, 3. Clear rejection confirming reversal. Retest best entry: lower risk, clear confirmation, reversal momentum emerged. / Setelah pola selesai: Break struktur, kembali retest level sama, baru bergerak reversal. Retest entry paling aman risiko kecil konfirmasi jelas momentum muncul.`
- Mistake: `Most enter too early — see small move assume reversed, only to be stopped. Understander waits: Let break happen first — then enter on retest. No rushing/chasing. / Banyak masuk terlalu cepat — melihat fake move langsung entry akhirnya kena stop. Pahami menunggu: Biarkan break dulu — baru entry saat retest. Tidak perlu kejar harga.`
- Summary: `QM = reversal after major trend. Typical bearish HH HL LH LL. Don't enter fake move — wait break and retest. / Struktur reversal setelah tren besar. Urutan HH HL LH LL. Jangan entry fake move tunggu break entry retest.`
- Key: `Once understand QM, see fake continuation vs true reversal. Almost every major reversal uses this to trap liquidity before moving. Always: fake move first — then real move. / Jika memahami QM bisa bedakan pergerakan palsu vs pembalikan nyata. Hampir semua reversal besar pola ini untuk trap likuiditas. Fake move selalu muncul terlebih dahulu baru real terjadi.`
- Charts: top bullish-to-bearish QMR line at highs with long lower wick LL break then retest short; bottom bearish-to-bullish QMR inverse with `$` liquidity marker. US100 29:28 footer confirms indices too.

### Page 33 — QMM (Quasimodo Manipulation): Fake Break of QML
- `QMM is phase where market pretends to break key level (QML) to trap most before reversing true direction. Price behavior purposely created by smart money to trigger stops and clear opposite liquidity before continuing. / Fase di mana market pura-pura menembus level kunci (QML) untuk menjebak mayoritas sebelum kembali arah sebenarnya. Gerakan dibuat smart money membersihkan posisi berlawanan sebelum lanjut arah utama.`
- Simply: `Market takes out others' stops before real move. / Market harus mengambil stop-loss lain sebelum lanjut.`
- Recognize: `Normal QML acts clean S/R. But during QMM: 1. Fakes break above/below looking valid, 2. Returns inside range continues original. Moment chart tricks eyes believing breakout — while smart money remains control. / Normal QML sebagai support/resistance jelas. Namun dalam QMM: Menembus palsu terlihat breakout sesungguhnya. Lalu kembali masuk area sebelumnya lanjut arah asli. Momen grafik menipu mata percaya breakout terjadi padahal smart money pegang kendali.`
- Typical: `Initially QML acts resistance. Breaks above appearing bullish. Then drops sharply below — confirms bearish QMM. / Awalnya sebagai resistance. Lalu break di atasnya seolah bullish. Namun setelah itu jatuh tajam kembali — ini QMM bearish jelas.`
- Charts: line diagram with `X` fake-break high, `QMM` line, `Q` circle (quasi high), then cascade down; candle chart with `FAKE` left shoulder, `QMM` line, `X` second shoulder.
- In short: `QMM = fake breakout above/below QML to remove liquidity before real move. Helps confirm which side smart money aligned. Safer entry than guessing standard S/R.`
- Edge: `Sometimes price may not retest QML again and simply continues real direction. Signals strong momentum — smart money accelerating. Traders understanding QMM usually wait retest when occurs. Retest often high-prob low-risk because true intention revealed. / Kadang tidak kembali retest tetapi langsung jauh. Artinya tekanan tren sangat kuat — smart money mendorong lebih cepat. Tunggu kembali ke QMM jika retest. Titik low-risk high-probability karena niat sebenarnya ditunjukkan.`
- **Bot distinction QMR vs QMM:**
  - QMR = full 4-step reversal structure ending with BOS + retest entry (trade the reversal).
  - QMM = single fake-break wick beyond QML then close back inside (trade continuation after trap, or fade the fake break). QMM can occur INSIDE QMR step 3 (the fake HH/LL leg).

### Page 34 — QMC (Quasimodo Continuation): Fake Continuation + Clean Retest
- `QMC is when market acts like trend will continue, but only collecting liquidity before real direction. Shows smart money shifting, high-accuracy entry after trapped + stops. / Kondisi ketika seolah menunjukkan tren akan berlanjut... Namun kenyataannya hanya menjebak likuiditas sebelum lanjut arah sebenarnya. Struktur menunjukkan smart money menggeser posisi — bisa sebagai entry akurasi tinggi karena setelah menipu mayoritas dan mengambil likuiditas.`
- Simply: `QMC = fake move before main move + clean retest entry. / Fake continuation + clean retest. Core: smart money tactic creating fake continuation before true directional starts. Waiting break+retest far safer than chasing normal S/R.`
- Structural pattern:
  - Uptrend: `1. HH, 2. Pullback HL, 3. Pushes up again fake HH (liquidity grab/fake wick), 4. Drops breaks HL signaling shift. / Membentuk HH, retrace HL, kembali naik fake HH (grab/fake wick), setelah itu turun break HL tanda awal pembalikan.`
  - Downtrend: `1. LL, 2. Pullback LH, 3. Pushes down fake LL, 4. Rallies breaks LH confirming reversal.`
- Mindset: `Market usually moves strongly only after most given up. Must: stop wrong side, create doubt, make believe nothing will happen. Exactly when everyone thinks "probably not going anywhere... / market sudah selesai gak gerak lagi" — real move begins. / Biasanya bergerak kuat setelah mayoritas menyerah. Harus: membersihkan posisi salah, membuat kehilangan kepercayaan, menciptakan ilusi tidak akan bergerak. Ketika semua berpikir kayaknya sudah selesai — justru saat pergerakan sebenarnya dimulai.`
- Key principle: `There must always be fake move/liquidity grab before real move begins. Traps wrong side clears liquidity before smart money commits. / Selalu ada fake move/grab sebelum sebenarnya dimulai. Menjebak arah salah lalu bergerak benar setelah stop diambil.`
- Chart US100 06:10 QMC line shows HH-HL-fake HH-break-retest-short.
- Footer: `Itulah inti dari konsep QM & QMC.`

### Page 35 — Real QM Example (Line vs Candle) + End of QM
- `This is real chart where QM formed clearly. Classic sequence: Strong move up/down -> BOS -> retest QM zone -> sharp reversal opposite. Proves not textbook — real behavior smart money uses repeatedly. / Contoh chart nyata QM sangat jelas. Urutan klasik muncul depan mata: Pergerakan kuat naik/turun -> Break of Structure -> retest zona QM -> berbalik kuat. Menjelaskan QM bukan pola buku teks melainkan perilaku benar terjadi sering dimanfaatkan smart money.`
- (1) Line: `Lower low followed by higher high, then shoulder before reverses. / Lower low diikuti higher high lalu terbentuk shoulder sebelum berbalik.`
- (2) Candle: `Highlighted area shows QM zone where price retested before significant reversal. / Area hijau menandai zona QM tempat retest sebelum reversal signifikan.`
- Charts show bearish QM: rally, left shoulder, higher high head, right shoulder (QM zone blue box), then cascade down with retest wicks into blue box.
- Closing: `Understanding QM not just shape, but shift control, moment smart money steps in, how crowd trapped wrong side. Master and see market new clarity. / Memahami QM bukan hanya bentuknya, tetapi melihat perubahan kendali, momen smart money mengambil alih, dan bagaimana retail terjebak sisi salah. Kuasai dan mulai melihat market jauh lebih jelas.`

## 5. Consolidated Bot Rules from Part 03

```text
Fresh Logic:
  Fresh = never body-broken; WickTouch = still tradable but Unfresh (size 0.5, need sweep)
  BodyTouch/CloseBeyond = invalid unless BreakAndFlip (becomes fresh opposite side RBS/SBR)
  UseCount max 2; DailyGapStrongReaction exempts limit
  Zone = [LL, UL]; ValidBuy requires Close > LL; ValidSell requires Close < UH
Validation (all three for full size):
  1. Wick tap, 2. Sweep done (micro or swing), 3. In congestion/reaction (range or OB/FVG confluence)
RBS = CloseAboveResistance + RetestHold -> new Support (Flipzone), buy retest rejection
SBR = CloseBelowSupport + RetestReject -> new Resistance, sell retest rejection
  FAKE (wick + close back) = NO flip, trade reversal; BRAKE (body close + displacement) = flip
  TF weight: M15=1 H1=2 H4=3 Daily=4; need RBS/SBR score >=3 with liquidity/OB/FVG
  Example anchor: XAU 2400 flip -> SL just beyond zone (XAU: ~200-300 points buffer, not fixed $)
QM Family:
  QM base (4 steps): Trend extreme (HH/LL) -> pullback (HL/LH) -> weak second extreme -> break pullback extreme -> retest entry
  QMR = full reversal playbook; wait BOS + retest + rejection; never enter fake leg
  QMM = fake break of QML (wick beyond + close back inside) -> fade fake or enter continuation after trap; if no retest and strong continuation, mark momentum, chase only on retest
  QMC = fake continuation HH/LL (liquidity grab wick) + break HL/LH -> enter break-retest; mindset: pre-move consolidation/doubt expected
Targets: QM level to opposite fresh HTF; QMC to break extreme then fresh; SL beyond fake extreme + buffer
```

---
*End of Part 03 — next: Part 04 pages 36-47.*
