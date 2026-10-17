# ALCHEMIST 02 — Part 04: QM Accuracy, OCL/OC Hidden Base, Trendlines + Confluence (Pages 36-47)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-36.jpg` through `-47.jpg`
> Covers: why QM works + hesitation mindset, OC/OCL divider, OCL definition/identification/TF/session/examples, OC hidden-base BUYING + SELLING with HTF→LTF drill-down, MSNR TRENDLINES divider + theory + zone-strength + Fib + CE50 + distance, equal-touch rules, 4 trendline chart types, confluence BUY/SELL + Direction multi-TF rule.

## 1. Page 36 — Why QM Is So Accurate + Hesitation Mindset

### Why accurate (EN+ID)
- `Because it comes from real shift in market control. When price breaks structure (BOS), opposite side begins taking control. When pulls back to retest same area (QM Zone), major players — smart money — add more. / Karena berasal dari perubahan nyata kendali market. Saat BOS, sisi berlawanan mulai mengambil alih. Ketika retest zona QM, pemain besar menambah posisi.`
- `Most don't understand, end up trapped wrong side. / Banyak tidak memahami sehingga terjebak sisi salah.`

### Key Points / Poin Penting
1. `True QM must be formed by real BOS — not random fluctuations. / Harus memiliki BOS jelas, bukan gerakan acak.`
2. `If returns too quickly or without strong confirmation (engulfing/pin), be cautious. / Jika kembali terlalu cepat atau tanpa konfirmasi kuat (engulfing/pin), hati-hati.`
3. `Always check HTF context to understand main trend before trade. / Selalu cek konteks TF lebih tinggi untuk arah utama.`
- **Bot:** implement `QM_Quality`: `BOS_ATR_ratio >= 0.8`, `RetestDelay >= 3 bars`, `Confirm in {Engulfing, Pin, OB50+reject}` else tag `LOW_QUALITY_QM` and halve size or skip.

### My Perspective / Mindset Saya (most important nuance)
- `QM is not always reversal signal — it's moment market begins to hesitate. Many see BOS and think "This is QM!" But real QM forms when market uncertain — unsure continue or reverse. / QM bukan selalu titik reversal — melainkan momen market mulai ragu dan kehilangan momentum. Banyak melihat BOS langsung berpikir "Ini QM!" Padahal sebenarnya muncul saat fase ketidakpastian — tidak yakin lanjut atau berbalik.`
- `Job is wait proper confirmation instead of rushing without analyzing candle strength and broader structure. / Tugas menunggu konfirmasi, bukan terburu-buru tanpa melihat kekuatan candle dan struktur besar.`
- `Impatient often fail because QM can make them believe "definitely reversing" while market just pausing before continuing. / Tidak sabar sering melewatkan karena QM bisa menipu berpikir "pasti reversal" padahal hanya mengambil napas sebelum lanjut.`
- **Coding:** do NOT auto-enter on BOS that looks like QM. Require `HesitationEvidence`: slowdown (range contraction), wick increase, or equal-touch before BOS. Pure impulsive BOS without hesitation = trend continuation, not QM.

## 2. Page 37 — Divider: WHAT IS OC/OCL
- Marks shift from QM to Open-Close system. All pages 38-41 belong here.

## 3. Page 38 — What Is OCL and How to Use It (HTF + LTF)

### Definition (ID+EN)
- `OCL, or Open-Close Level, is price zone created from open and close of a candle. / Zona harga yang diambil dari open dan close sebuah candlestick.`
- `Most look for SNR by focusing on wicks. But open/close reveal where market actually accepted price. / Banyak hanya fokus shadow/wick. Padahal open/close menunjukkan di mana market benar-benar menerima harga.`
- `Close tells where market finally agreed during session, next open shows where new pressure begins. That's why OCL often more reliable than wick lines. / Close memberi tahu di mana akhirnya menyepakati harga sesi itu, dan open berikutnya menunjukkan dari mana tekanan baru terbentuk. Alasan zona OCL sering lebih akurat daripada garis pada wicks.`

### How to Identify / Cara Menemukan
- `Look for key candles: breakout candle, strong reversal. / Cari candle penting: Breakout, Reversal kuat.`
- `Mark close, sometimes also next open. Area becomes OCL. / Tandai close-nya, terkadang sertakan juga open berikutnya. Area menjadi zona OCL.`
- `If price breaks through OCL and closes beyond, signals enough strength to shift structure. / Jika menembus dan close di atas/bawah zona, tanda kekuatan menggeser struktur.`
- `When retests OCL, often cleaner/safer entry. / Saat kembali retest, biasanya titik entry lebih aman dan bersih.`
- HTF diagram (right): 4 candles with blue box `OCL (OPEN CLOSE LEVELS)` spanning opens/closes, labelled `HTF`. Wick highs/lows extend beyond box — box ignores wicks by design.

### Which Timeframes / Timeframe yang Bisa Dipakai
- `You can use any, but H4/Daily give stronger/clearer. / Bisa semua, namun besar seperti H4/Daily cenderung lebih kuat dan jelas.`
- `Try combining with: Trendlines, Fibonacci, Market Structure. You'll notice accuracy/confidence improve. / Cobalah gabungkan dengan Trendline, Fibonacci, Market Structure. Akurasi dan kepercayaan diri meningkat drastis.`

### Additional LTF Example (critical confluence)
- `In LTF see combination: FVG, Resistance, Retest, Key timezones (NY/London). / Pada LTF kombinasi: FVG, Resistance, Retest, Timezones (New York/London).`
- `When S/R overlaps FVG, zone becomes much stronger. / Ketika support/resistance bertumpuk dengan FVG, zona jauh lebih kuat.`
- LTF diagram (bottom-left): `RBS` base, `FAIR`, `FVG` upper, `OCL`, `+TS`, `RESIS`, `KZ [key zone]` green box, pink FVG box, `Follow The Tren` arrow looping from FVG to OCL retest then expansion.
- **Ambiguity:** `FAIR` vs `FVG` vs `OCL` stacked vertically — they are NOT same: `FAIR` = equilibrium/CE line, `FVG` = imbalance box above, `OCL` = open-close line below. Entry is at `OCL+KZ`, target is `FVG` fill. Do not enter at FVG when plan says OCL.

## 4. Page 39 — OCL Sessions + 4 Worked Examples (IMPORTANT)

### Session filter (top, bilingual)
- `OCL can help take entries during NY/London, which usually give stronger zones and bigger momentum vs Asia. If formed during London/NY, more valid and less likely fake-break. / Dapat membantu entry selama New York/London, biasanya zona lebih kuat dan momentum lebih besar dibanding Asia. Jika terbentuk saat London/New York, cenderung lebih valid dan kemungkinan kecil fake breakout.`
- **Bot:** `SessionWeight: Asia=0.5, London=1.0, NY=1.0, Overlap=1.5`. Require higher confluence if `Session==Asia`.

### Examples 1&2 (top OCL = potential sell)
- `OCL at top creates potential sell zone once returns to retest. Usually forms from: strong rejection during active session, BOS, clean retest before drops. / Zona potensial mencari sell setelah menyentuh kembali. Biasanya terbentuk dari: Rejection kuat sesi aktif, Break of Structure, Retest kembali sebelum jatuh.`
- `You can also use Fibonacci to refine entry, but not strict — additional tool. / Bisa gunakan Fibonacci mengukur level presisi, meski bukan wajib — hanya alat pendukung.`
- Diagrams 1 (peach box) and 2 (blue box) show small consolidation `OCL` line at highs, then sharp displacement down after retest. Both are ClassicA + OCL overlap.

### Example 4 (bottom-left, bullish continuation buy)
- `Here OCL overlaps S/R, creating strong rejection. When revisits with clear confirmation, safer entry before continues trend. / Bertumpuk dengan zona SNR menghasilkan rejection kuat. Ketika kembali menyentuh secara clean dan terkonfirmasi, peluang entry lebih aman sebelum melanjutkan tren.`
- Diagram 4 shows uptrend with mid `OCL` beige box holding as support, then continuation up.

### Example 3 (bottom-right, broken support becomes sell)
- `In this example OCL acts as support that later gets broken. When comes back to retest, becomes ideal sell zone, especially if aligns with SNR/key. / Berperan sebagai support yang ditembus. Saat kembali retest, menjadi titik ideal mencari sell, terlebih jika bertepatan dengan SNR/key lain.`
- Diagram 3 shows low `OCL` + `KZ` box broken then retested from below with rejection.
- **Pattern:** Examples 1-2 = fresh short, 3 = SBR short, 4 = RBS long. OCL is the *measurement* (open-close line), RBS/SBR is the *role* after break. Combine both tags per zone.

## 5. Pages 40-41 — OC / Open-Close: Hidden Base Theory (BUYING + SELLING)

Same theory mirrored for both directions; diagrams differ.

### Core concept (EN+ID, both pages)
- `OC, or Open-Close, is simple but powerful. When HTF chart shows two identical candles in a row — same color, same shape — it's not coincidence. If zoom into LTF, often find area hiding a zone, typically supply/demand. For SMC, known as hidden base — base inside LTF. / Konsep sederhana tetapi sangat kuat. Ketika HTF menemukan dua candle hampir identik — warna sama, bentuk sama — itu bukan kebetulan. Jika perbesar ke LTF, biasanya terlihat menyimpan zona, umumnya supply/demand. Bagi SMC sering disebut hidden base — base tersembunyi dalam struktur LTF.`
- **Visual cue for bot:** `OC Signal = Close[i]≈Close[i-1] AND Open[i]≈Open[i-1] AND Color[i]==Color[i-1] AND BodySize similar (within 20%)`. On HTF this looks like flat pause; on LTF it unfolds into range/base with OBs, V-shapes, accumulation.

### Why OC Matters / Kenapa Penting + Power / Kekuatan
- `Strength is it tells market pausing, gathering momentum, deciding continue/reverse. If understand, like knowing where orders placed. Major advantage vs just staring at HTF assuming nothing happening. / Kekuatan memberi tahu market berhenti sejenak, mengumpulkan momentum, memutuskan lanjut/berbalik. Seperti mengetahui di mana order tersembunyi. Keunggulan saat entry dibanding hanya melihat HTF dan menganggap kosong.`
- Analogy: `HTF like looking at building far away — plain empty. Walk closer, see windows, doors, shops, activity inside. OC point signal: "This area isn't empty. Activity hidden inside." / HTF seperti gedung dari kejauhan — kosong polos. Tapi ketika mendekat, mulai melihat jendela, pintu, toko, aktivitas. Titik OC sinyal: "Area ini tidak kosong. Ada sesuatu tersembunyi di dalamnya."`

### Chart Explanation / Penjelasan Chart
- `HTF shows clean formation. LTF reveals real structure: internal ranges, bases, levels where orders accumulate. Hidden details explain why price reacts strongly to OC zones. / HTF hanya menunjukkan formasi bersih. LTF mengungkap struktur sebenarnya: internal range, base, level tempat order terakumulasi. Detail tersembunyi inilah yang membuat harga sering bereaksi kuat pada zona OC.`
- Page 40 BUYING diagrams: `1` HTF two tall candles with pink `SPL` base + `EQ` + `CNTL` + `EN`? Actually labels `SPL`, `EQ`, small `—` markers; `2` LTF expansion to `KEY LEVELS` with pink `INTERNAL` box, `S` support. Arrow `=>` shows HTF pause maps to LTF base.
- Page 41 SELLING diagrams: `3 H4 TIMEFRAME oc (open close)` teal box at highs mapping to breakdown; `4 M15 TIMEFRAME Key levels Turtle soup` teal box mapping to `S` then cascade to lows. Circular arrow indicates fractal loop H4↔M15.

### Important Note / Catatan Penting (both pages)
- `Don't rely only on demand/supply zone. On LTF many other valuable elements — OB, Volume, V-shapes, Accumulation (A), and more. None are right/wrong; they offer different perspectives supporting same behavior. / Jangan hanya fokus pada demand/supply zone. Di LTF ada banyak elemen penting: OB, Volume, V-shape, Accumulation (A). Tidak ada yang benar/salah; semuanya perspektif berbeda yang menjelaskan perilaku sama.`
- **Bot architecture:** OC detector should trigger LTF drill-down, not direct entry. On `OC_HTF` → fetch LTF candles same time window → run `OB`, `VShape`, `Accumulation`, `VolumeShift` sub-detectors → score zone by count of sub-elements. Enter only if `SubScore>=2`.

## 6. Pages 42-47 — MSNR Trendlines Module

### Page 42 divider: `MSNR TRENDLINES` — no logic.

### Page 43 — What They Are and Why They Matter + Zone-Strength Formula
- `Market doesn't move randomly. Every move has direction, structure, reason. Trendline helps understand structure and trade harmony vs guessing. / Tidak pernah bergerak acak. Setiap pergerakan selalu memiliki arah, struktur, alasan. Salah satu alat utama melihat struktur dan trading searah tren, bukan menebak.`
- `Aren't just decorations — reveal true behavior. Know correctly, instantly recognize whether: Moving with strength, Losing momentum, Preparing reversal. / Bukan hanya garis agar rapi — mencerminkan perilaku sebenarnya. Jika benar, langsung menunjukkan apakah: Bergerak dengan kekuatan, Kehilangan momentum, Bersiap reversal.`
- Helps: `Identify direction clearly, Find entries aligning current trend, Spot reversals earlier. / Melihat arah lebih jelas, Menemukan entry searah tren lebih mudah, Menangkap reversal tahap awal.`
- Build: `Start observing which points consistently respected. Then connect — that is valid. / Amati titik yang sering dihormati market. Kemudian hubungkan — itulah yang valid.`
- Overlap bonus: `If overlaps other structures: Liquidity zones, Trendline confluence, CE → zone even more powerful because multiple confirmations. / Jika bertemu struktur lain: Zona likuiditas, Confluence trendline, CE → jauh lebih kuat karena beberapa konfirmasi.`
- How to know truly strong (numbered):
  1. `Check liquidity before zone. If clear buildup leading into zone, often signals strong reaction. / Periksa likuiditas sebelum zona. Jika akumulasi sebelum memasuki zona, biasanya reaksi kuat saat disentuh.`
  2. `Check trendlines. Zone supported by multiple intersecting trendlines much stronger, because aligns structural, directional, liquidity factors. / Periksa trendline. Semakin banyak berpotongan/mengonfirmasi zona sama, semakin kuat — karena struktur, arah, likuiditas saling mendukung.`
  - `When combine, not random — high-probability backed multiple confirmations.`
- Good trendline: `Isn't perfect — it's respected one. Strong is not neat/artistic. It's one price reacts to, because reflects smart money intentions. / Bukan yang sempurna. Tapi yang dihormati harga. Kuat bukanlah garis sempurna, lurus, estetis. Kuat adalah garis yang menunjukkan reaksi harga, karena menggambarkan niat pelaku besar.`
- `Understanding deeply like rhythm. Instead of guesswork, begin to read with own eyes. / Memahami dengan baik mulai memahami irama pergerakan. Dari menebak-nebak berubah bisa membaca dengan mata sendiri.`
- Bottom `LINE EXAMPLE 1/2/3`: (1) ascending `1-2-3` support line with W-bottoms then breakout up; (2) descending + ascending intersecting (wedge) with `2-3-4` then drop-and-reclaim? Actually shows two lines forming triangle then expansion up; (3) descending `1-2-3` resistance with lower highs then break attempt.
- **Ambiguity:** line examples use closing-price line, not candle highs/lows. Bot trendline fitter should offer `CloseMode` (default per p23 close-rule) plus `WickMode` for validation; respected = multiple touches within tolerance in CloseMode.

### Page 44 — Candle vs Line, Strong-Zone Composition, Fib, CE50, Distance Intro
- Top-left: `CANDLE` vs `15 MINE LINE CHART` vs `15 MINE` vs `30 MINE` with `SS`, `TRENDLINE`, `KEY RESIS`, `KZ` blue box at top. Shows same sell zone on 4 views — teaching that M30 trendline + M15 candles + line all converge at `KZ`. Bot should validate trendline on multiple TFs; strongest when M15/M30/H1 lines intersect same KZ.
- Composition: `In example zone strong because: Clear buildup, Main + minor trendlines confirming, CE/SNR, Fibonacci time zone alignment. When align, high-probability. / Ada likuiditas jelas sebelum masuk, Ada trendline utama dan kecil saling mengonfirmasi, Ada CE/SNR, Ada zona Fibonacci Time. Elemen bersatu membentuk berkekuatan tinggi.`
- Fib as Additional: `Use as supporting not primary. Helps confirm balance, strengthen confluence, add secondary validation. Not main but refining. / Gunakan bukan faktor utama, tetapi pendukung: melihat keseimbangan, memperkuat confluence, menambah validasi. Faktor sekunder namun bermanfaat memperjelas struktur/keseimbangan.`
- Continuing upper: `After liquidity and trendlines, next key: Consequent Encroachment (CE). CE represents 50% level of: candle wick, FVG, OB, or any key area. When respects 50%, often smart money participation. / Setelah likuiditas dan trendline, masuk elemen kunci: CE adalah level 50% dari: sumbu candle, FVG, OB, atau area kunci lainnya. Jika menghormati 50%, sering tanda smart money berpartisipasi.`
- How to Use Trendline Distance: `Used to: measure strength, identify weakening, detect early reversal. Examples illustrate different spacing between points forming trendline and how distance helps evaluate strength. / Untuk: mengukur kekuatan tren, mengetahui melemah, mendeteksi potensi reversal lebih awal. Diagram menunjukkan beberapa contoh jarak antar titik membentuk trendline dan mengukur kekuatan struktur.`

### Page 45 — Trendline Distance Rules (CARA MENGGUNAKAN TRENDLINE DISTANCE)
- Top diagrams `1)-4)` show dot spacing patterns: (1) wide-equal, (2) wide-then-tight, (3) clustered-then-wide, (4) equal-mid. Equal spacing = strongest (see below).
- Key Principles / Prinsip Utama:
  - `Touches must be equally spaced → strong. / Sentuhan harus memiliki jarak seimbang → kuat.`
  - `Never force a line (let market show you). / Jangan pernah memaksakan garis (biarkan market menunjukkannya).`
  - `Only works with 4 main MSNR zones. / Hanya bekerja dengan 4 zona MSNR utama.`
  - `Trendlines don't always need to be fresh. / Tidak harus selalu baru/fresh.`
- Conditions / Syarat:
  - `Touches must occur above/below SNR. / Harus terjadi di atas/bawah SNR.`
  - `If above SNR → strong (bullish bias). / Jika di atas → kuat (bias bullish).`
  - `If below SNR → weak (bearish bias). / Jika di bawah → lemah (bias bearish).`
  - `Market often leaves wick/shadow near SNR → use to confirm. / Sering meninggalkan wick/shadow dekat SNR → gunakan mengonfirmasi.`
- Bottom charts `1)` and `2)` show `1-2-3` ascending trendlines with equal-ish spacing leading to rally. `1)` has three touches from deep low; `2)` shallower.
- Easy Summary / Ringkasan: `1. Equal touches = strong. 2. SNR+trendline = special zone. 3. Above → buys / Below → sells. 4. Don't force.`
- Helps: `Identify up/down, Find entries aligning main trend, Spot reversals early before most notice.`
- **Coding distance:**
  ```
  Gaps = [bars between Touch1-Touch2, Touch2-Touch3]
  EqualSpaced = max(Gaps)/min(Gaps) < 1.5  // tune 1.3-1.8
  ClusteredEarly (gaps increasing) = weakening? Actually p45 diagram 3 clustered early then wide = momentum building? Treat Equal as strongest, Increasing gap as still valid (expansion), Decreasing gap as weakening (exhaustion).
  NeverForce = require at least 3 touches with R² > 0.85 on log-price; else no line.
  Only4Zones = only draw trendlines anchored to 4 main MSNR (HTF key levels), not every micro swing — prevents overfitting.
  ```

### Page 46 — MSNR: Trendlines Bilingual Recap + 4 Chart Archetypes
- Repeats touch rules + quick summary in EN+ID (same as p45). No new logic except visual archetypes:
  - `1.` descending support line with `1-2-3` then break up + retest continuation up.
  - `2.` ascending support `1-2-3 TRENDLINE` with higher lows then expansion up.
  - `3.` ascending resistance `1-2-3 TRENDLINE` with lower highs? Actually rising wedge then sharp breakdown.
  - `4.` descending resistance `1-2-3 TRENDLINE` then breakdown cascade.
- **Bot:** classify trendline by slope + position vs SNR: `SupportTrendline (below price, bullish bias)` vs `ResistanceTrendline (above price, bearish bias)`. Break of support trendline with body close = early short warning (needs MSS confirm per Part 01); break of resistance = early long warning.

### Page 47 — Confluence in Action + Direction (Multi-TF Break Rule)
- Example: `Imagine price moves up taps downtrend line, right same level as previous resistance, then reversal candle. This point represents three combined forces, high reversal prob. Many use as entry because confirm direction greater confidence — not random. / Bayangkan bergerak naik menyentuh downtrend line, tepat level sama dengan resistance sebelumnya, lalu membentuk reversal. Titik ini menunjukkan tiga faktor bertemu, peluang reversal sangat tinggi. Banyak menggunakan sebagai zona entry karena konfirmasi arah lebih kuat — bukan tebakan acak.`
- BUY confluence (reversal): `Currently downtrend, preparing upside. Draw trendline Close1→Close2. When pulls back touches + aligns previous support → confluence point. Two confirmations: structure reversal sell→buy, taps multiple Trendline+Liquidity+AMD+Support. No need extra confirmation candle — plan already tells entry. / Sedang downtrend menunggu reversal atas. Buat garis Close1→Close2. Ketika pullback kembali menyentuh dan sejajar support sebelumnya → titik confluence. Dua konfirmasi kuat: pola reversal sell ke buy, menyentuh beberapa faktor Trendline+Liquidity+AMD+Support. Tidak perlu menunggu candle tambahan karena rencana sudah mengarahkan entry di titik ini.`
  - Diagram 1: `A` left high, `M` low trendline touch with pink accumulation + green expansion, `D` top.
- SELL confluence mirror: `Currently uptrend preparing downside. Draw Close1→Close2. Pullback touches + aligns previous resistance + AMD+Liquidity → sell confluence zone. Place sell limit per plan. Because institutions/smart money often already positioning sell.`
  - Diagram 2: `QS`, `SS`, `CE` at top with pink distribution + blue displacement down.
- Concept: `Confluence point enter with confidence — because every element (trend, trendline, SNR, liquidity, price action) aligns same direction. Isn't guessing planning ahead before chart speaks. Don't need perfect candle, when everything aligns plan itself tells act. Trading based confirmation through plan, not emotion. Difference between trader waits chart speak vs listens plan before market reacts. / Titik confluence area bisa entry keyakinan tinggi — karena setiap elemen tren, trendline, SNR, price action selaras arah sama. Bukan menebak — merencanakan sebelum chart berbicara. Tidak perlu konfirmasi sempurna, karena ketika selaras rencana cukup bertindak. Trading dengan konfirmasi melalui rencana, bukan emosi. Perbedaan trader menunggu chart memberi jawaban vs mengikuti rencana sebelum market memberi sinyal.`
- DIRECTION (Market Direction) / Apa itu Direction?
  - `Direction is what gives price ability to break S/R. / Faktor yang membuat harga mampu menembus support/resistance.`
  - Key Concepts (small print): `DIRECTION IS MULTI-TIMEFRAME CONCEPT. Doesn't come from single TF, but connection between multiple. A TF cannot break another TF unless: Higher can break lower, Lower cannot break higher. / Arah adalah permainan multi-timeframe. Tidak berasal dari satu TF, tetapi hubungan antara beberapa TF. TF tidak dapat menembus TF lain kecuali: Tinggi dapat menembus rendah, tetapi rendah tidak bisa menembus tinggi.`
  - **Bot critical:** gate BOS signals by TF hierarchy. `M15 BOS valid only if H1/H4 trend agrees or H1 at fresh zone boundary. H4 BOS can override M15 structure; M15 BOS cannot override H4 S/R — treat as internal sweep, not reversal.` Implement `DirectionBias = HTF_Trend; LTF_Entry only if aligns or HTF at extreme (premium/discount boundary with sweep).`
  - Note `AMD` in confluence = Accumulation-Manipulation-Distribution (Wyckoff) phase tag; `Q`/`KZ`/`SS` markers confirm phase. Require `Phase==Manipulation→Distribution` for sell confluence, `Accumulation→Manipulation` completed for buy confluence.

## 7. Consolidated Bot Rules from Part 04

```text
QM Quality Gate:
  BOS_ATR>=0.8 AND RetestDelay>=3 AND Confirm in {Engulfing,Pin,OB50} AND HTF agrees
  Hesitation required: range contraction or wick expansion before BOS else continuation not QM
OCL:
  Zone = [min(Open[i],Close[i]), max(Open[i],Close[i])] of key candle (breakout/strong reversal) [+ next Open optional]
  Break = CloseBeyond OCL + displacement; RetestHold -> entry
  Weight by session: Asia 0.5, London/NY 1.0, Overlap 1.5; combine with Trendline/Fib/MS; FVG overlap bonus +1
  Examples: top OCL->sell retest; broken support OCL->SBR sell; overlapped OCL+SNR->strong buy/sell
OC Hidden Base:
  HTF Signal = two same-color/shape candles with Open/Close clustered (20% tolerance)
  -> Drill to LTF window: detect OB/VShape/Accumulation/VolumeShift; need >=2 sub-elements to trade
  Do not enter on HTF OC alone; LTF reveals true supply/demand
Trendlines:
  Fit on Close series (Wick confirm); need >=3 touches, R²>0.85, anchored to 4 main MSNR zones, never force
  Equal spacing strongest (maxGap/minGap<1.5); decreasing gaps = exhaustion warning
  Above SNR = bullish bias (buys), Below = bearish (sells); wick at SNR confirms
  Strong zone = LiquidityBuildup + Main/Minor trendlines intersect + CE/SNR + FibTime align
  CE = 50% of wick/FVG/OB/key area; respect implies smart money
Confluence Entry (no extra candle needed if plan aligns):
  Buy = Downtrend + Close1-Close2 trendline + pullback touches trendline AT prior support + Liquidity+AMD+Support
  Sell = Uptrend + Close1-Close2 trendline + pullback touches AT prior resistance + AMD+Liquidity
  Direction = multi-TF: Higher can break Lower, Lower cannot break Higher; LTF BOS against HTF = internal only
```

---
*End of Part 04 — next: Part 05 pages 48-59.*
