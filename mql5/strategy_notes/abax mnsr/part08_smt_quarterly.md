# ALCHEMIST 02 — Part 08: SMT Divergence + Quarterly Theory / AMDX Cycle (Pages 78–92)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-78.jpg` through `-92.jpg` — `Penjelasan SMT Divergence (Simplified & Mudah Dipahami)`, 4-case XAU/XAG table, `Kenapa Bisa Terjadi SMT`, `Pair yang Cocok`, `Cara Menggunakan SMT untuk Entry`, `Quarterly Theory – Teori Siklus Pergerakan Harga di Setiap Sesi Trading`, `Struktur Siklus Harga`, Buying/Selling + Variations (1–4 diagrams), `Cara Menggunakan Quarterly Theory`.
> Thesis: **SMT = lie detector (which leg is fake); Quarterly/AMDX = timer (when fake happens)**. Combine: SMT tells direction truth, AMDX tells session window. Neither is entry alone.
> Repo: SMT filter (new, XAU/XAG + EUR/GBP, USD/CAD/CHF, AUD/NZD), session AMDX state machine, E3 liquidity, E2 sweep.

## 1. APA ITU SMT DIVERGENCE? (page 78–80)

- `SMT (SMART MONEY TECHNIQUE) DIVERGENCE ADALAH KONDISI KETIKA DUA PAIR YANG BIASANYA BERGERAK MIRIP TIBA-TIBA MENUNJUKKAN PERGERAKAN YANG BERBEDA. PERBEDAAN INI MEMBERI PETUNJUK BAHWA SALAH SATU PAIR SEDANG MELAKUKAN FAKE MOVE, SEDANGKAN PAIR YANG LAIN MENUNJUKKAN ARAH PASAR YANG SEBENARNYA.`
- `INTINYA: LIHAT PAIR MANA YANG "TIDAK IKUT" MELAKUKAN GERAKAN EKSTREM — ITU BIASANYA ARAH ASLI PASAR. / Follow the pair that refuses the extreme — that's truth.`
- Diagrams: two line charts with `SMT` gap label + `Q3` box (Quarterly Q3 timing context). One leg makes lower low, other holds higher low → divergence wedge.
- **Bot principle:** SMT is not buy/sell signal, it's `FakeLeg vs TrueLeg` classifier. `SMT = ALAT UNTUK MENGHINDARI JEBAKAN PASAR, BUKAN SINYAL BUY/SELL LANGSUNG.`
  ```
  SMT_State = NONE | BULLISH_DIVERGENCE (one makes LL, other holds) | BEARISH_DIVERGENCE (one makes HH, other holds)
  TrueDirection = opposite of FakeLeg extreme (fade the faker, follow the holder)
  ```

## 2. Four cases — XAU vs XAG (pages 80–83, must code all)

- **Kasus 1 — XAU TURUN, XAG TIDAK TURUN:** `GOLD (XAU) JATUH, TAPI SILVER (XAG) TIDAK IKUT JATUH. ARTINYA PENURUNAN XAU ADALAH FAKE, DAN KEMUNGKINAN BESAR HARGA AKAN BALIK NAIK. MAKA: IKUTI XAG → EXPECT REVERSAL NAIK.`
- **Kasus 2 — XAG TURUN, XAU TIDAK TURUN:** `SILVER TURUN TAJAM, GOLD TETAP STABIL. MAKA PENURUNAN SILVER ADALAH FAKE → HARGA KEMUNGKINAN AKAN NAIK.`
- **Kasus 3 — XAU NAIK, XAG TIDAK IKUT:** `GOLD RALLY KUAT, TETAPI SILVER DIAM SAJA. RALLY GOLD KEMUNGKINAN FAKE → HARGA BISA TURUN.`
- **Kasus 4 — XAG NAIK, XAU TIDAK IKUT:** `SILVER NAIK, GOLD TIDAK IKUT. KENAIKAN SILVER ADALAH FAKE → HARGA BISA TURUN.`
- Summary rule (bold in book): `SELALU IKUTI PAIR YANG TIDAK MELAKUKAN GERAKAN EKSTREM. ITU ADALAH SISI YANG BENAR.`
- **Visual ambiguity:** both charts falling looks like correlated sell. Difference is 5–15 points extreme depth. Human misses; bot must compare swing points quantitatively.
- **Coding (XAUUSD vs XAGUSD, same TF, synced bars):**
  ```
  // Compare last two swing lows/highs within lookback 50 bars, tolerance 0.3 ATR
  Low_XAU_1, Low_XAU_2 vs Low_XAG_1, Low_XAG_2 (aligned by time ±2 bars)
  if Low_XAU_2 < Low_XAU_1 - Tol && Low_XAG_2 >= Low_XAG_1 - Tol*0.3 -> BEAR_TRAP (fake breakdown) -> bias LONG XAU
  if High_XAU_2 > High_XAU_1 + Tol && High_XAG_2 <= High_XAG_1 + Tol*0.3 -> BULL_TRAP -> bias SHORT XAU
  // Mirror for XAG faker cases
  // Require correlation check first (see §4)
  ```

## 3. Why SMT happens + correlated pairs (pages 84–85)

- `KARENA SMART MONEY (INSTITUSI) TIDAK SELALU MENDORONG KEDUA PAIR SECARA BERSAMAAN. MEREKA SERING "MEMANCING" TRADER DENGAN: MENAIKKAN SALAH SATU PAIR TERLALU TINGGI ATAU MENJATUHKANNYA TERLALU DALAM ... SEMENTARA PAIR SATUNYA TETAP BERGERAK NORMAL. PAIR YANG BERGERAK NORMAL ITULAH YANG MENUNJUKKAN ARAH YANG SEBENARNYA.`
- Suitable pairs (book list, must whitelist):
  - `EURUSD ⇄ GBPUSD`
  - `USDCAD ⇄ USDCHF`
  - `AUDUSD ⇄ NZDUSD`
  - Plus `XAUUSD ⇄ XAGUSD` (primary for gold trader).
- Warning: `HINDARI SMT JIKA DUA PAIR TIDAK BERGERAK MIRIP DALAM KONDISI NORMAL, KARENA HASILNYA AKAN MENYESATKAN.`
- **Bot correlation gate:**
  ```
  Corr = Pearson(returns_XAU[60], returns_XAG[60])
  AllowSMT only if Corr > 0.70 in normal regime (prior 60 bars excluding last 5)
  Else SMT_State = NONE (avoid false divergence in decoupled regime / news single-asset)
  ```

## 4. Cara Menggunakan SMT untuk Entry (pages 86–87)

1. `IDENTIFIKASI SIAPA YANG MELAKUKAN FAKE MOVE. CONTOH: GOLD BREAK LOW TERLALU DALAM, SILVER TIDAK IKUT BREAK.`
2. `TUNGGU HARGA KEMBALI MASUK KE RANGE. JANGAN LANGSUNG ENTRY SAAT FAKE TERJADI.` (critical — wait for close-back-inside, same as sweep rule).
3. `ENTRY KE ARAH YANG BENAR. JIKA GOLD FAKE BREAK BAWAH → ENTRY BUY SETELAH HARGA KEMBALI NAIK KE ATAS LOW.`
4. `STOP LOSS AMAN. LETAKKAN STOP LOSS DI BAWAH LEVEL FAKE-OUT.` (beyond fake extreme + buffer, not beyond true leg).
- `SMT tidak wajib, tapi: sangat membantu meningkatkan confidence entry, terutama saat market tidak jelas arahnya.`
- Inti: `PASAR YANG FAKE = SISI YANG SALAH / TERJEBAK. PASAR YANG STABIL DAN TIDAK IKUT FAKE = ARAH SEBENARNYA. JIKA KAMU BELAJAR MEMBACA SMT DENGAN BENAR, KAMU AKAN TAHU KAPAN CHART: "BERACTING" UNTUK MENJEBAK TRADER ATAU "JUJUR" MENUNJUKKAN ARAH MARKET.`
- **Bot sequence:**
  ```
  On SMT_Divergence(bias):
    WaitFor CloseBackInside(range) on traded symbol (XAU)
    + LTF MSS in bias direction
    + Touch OCL/SNR/CE confluence (Parts 05–07)
    Then Entry with SL beyond FakeExtreme + 0.3 ATR, TP next liquidity
    Score +1.5 if SMT agrees, -1.5 if SMT contradicts planned direction (skip or halve size)
  ```

## 5. Quarterly Theory — Teori Siklus Pergerakan Harga di Setiap Sesi (pages 88–90)

- `QUARTERLY THEORY (QT) ADALAH SEBUAH KONSEP YANG DIGUNAKAN UNTUK MENGANALISIS PERILAKU HARGA DI DALAM BERBAGAI SESI MARKET, SEPERTI FOREX ATAU GOLD. TEORI INI MENJELASKAN BAHWA SETIAP HARI TRADING MENGIKUTI SIKLUS YANG BERULANG MELALUI TIGA SESI UTAMA: ASIA / LONDON / NEW YORK.`
- `SETIAP SESI MEMILIKI PERAN YANG BERBEDA DALAM MEMBENTUK STRUKTUR MARKET SECARA KESELURUHAN.`
- Prinsip Utama:
  - `Market tidak bergerak secara acak. Pergerakan harga mengikuti ritme yang konsisten, yang bertujuan untuk: Menciptakan likuiditas / Menarik trader retail masuk ke market / Memberi ruang bagi smart money untuk mengeksekusi buy atau sell dengan ukuran besar.`
  - `DENGAN KATA LAIN, PERGERAKAN HARGA MEMANG "DIRANCANG" UNTUK MEMINDAHKAN LIKUIDITAS SEBELUM ARAH SEBENARNYA BERJALAN.`
- Struktur Siklus Harga (Contoh Visual, page 89):
  - `1. BUYING CYCLE (SIKLUS NAIK): A (Accumulation): harga bergerak range, market mengumpulkan posisi buy / M (Manipulation): harga diturunkan sebentar untuk ambil likuiditas / D (Distribution): harga naik kuat (impuls utama) / X (Continuation/Reset): konsolidasi atau persiapan siklus berikutnya.`
  - `2. BUYING VARIATION: harga bisa turun lebih dalam saat manipulasi, setelah akumulasi selesai market naik agresif, sering membuat trader ragu sebelum move besar.`
  - `3. SELLING CYCLE (SIKLUS TURUN): A: range di atas (persiapan sell) / M: harga dinaikkan untuk ambil stop loss / D: harga turun kuat / X: konsolidasi sebelum siklus baru.`
  - `4. SELLING VARIATION: manipulasi bisa terjadi di high, setelah distribusi selesai market jatuh dengan impuls tajam, banyak trader masuk terlambat di akhir pergerakan.`
- Diagrams 1–4:
  - 1 Buying: `A` sideways box → `M` dip below range (pink box) → `D` vertical impulse (green box) → `X` zigzag top.
  - 2 Buying Variation: `X` start dump → `A` long base → `M` deeper dip → `D` explosive up.
  - 3 Selling: `A` top range → `M` spike above (pink) → `D` vertical drop (green) → `X` bottom chop.
  - 4 Selling Variation: `X` start rally → `A` rising base → `M` spike high → `D` collapse.
- **Bot AMDX state machine:**
  ```
  enum AMDX { A_ACCUM, M_MANIP, D_DISTR, X_RESET };
  // Session mapping default: Asia=A, London=M (+sweep), NY=D, LateNY/Close=X
  // But detect by price, not clock alone:
  // A = range (ADX<20, range<0.5 ATR), M = sweep of A extreme + quick return, D = displacement (body>1.5 ATR + BOS), X = consolidation after D
  ```

## 6. How to use QT in trading (page 91–92)

- `AMATI STRUKTUR MARKET DI SETIAP SESI (ASIA, LONDON, NEW YORK)`
- `GUNAKAN MANIPULATION POINT (M) SEBAGAI PETUNJUK ADANYA PERGERAKAN SMART MONEY`
- `TUNGGU HARGA MASUK KE FASE DISTRIBUTION (D) ATAU ACCUMULATION (A) UNTUK KONFIRMASI ARAH`
- `HINDARI MENGEJAR HARGA DI AKHIR FASE — TRADINGLAH BERSAMA SIKLUS BARU`
- `JIKA SUDAH MEMAHAMI SIKLUS INI, KAMU AKAN MULAI MELIHAT PERGERAKAN MARKET YANG SERING TERLEWAT OLEH KEBANYAKAN TRADER`
- Kesimpulan: `QUARTERLY THEORY MEMBANTU TRADER MEMAHAMI BAHWA: MARKET BERGERAK DALAM POLA BERULANG / SETIAP SESI PUNYA FUNGSI BERBEDA / LIKUIDITAS SELALU DIAMBIL SEBELUM MOVE BESAR TERJADI. JIKA DIGABUNGKAN DENGAN LIQUIDITY SWEEP, MARKET STRUCTURE, DAN ALCHEMIST MODEL, QT MENJADI ALAT TIMING YANG SANGAT KUAT.`
- Offer footer: `RINGKAS JADI CHEAT SHEET 1 HALAMAN / BUAT CONTOH ENTRY REAL BUY & SELL / GABUNGKAN DENGAN SNR + LIQUIDITY SWEEP` — confirms QT is timing layer, not standalone.
- **Visual ambiguities:**
  - A vs X both look like sideways chop. Distinguish: A before M (pre-sweep, Smart Money building), X after D (post-impulse, profit-taking / reset). Same shape, opposite meaning. Bot must track sequence, not shape alone.
  - M dip vs real breakdown both break range. Distinguish: M returns quickly inside + SMT holds on correlated pair + sweep wick; real breakdown closes outside + displacement + SMT confirms (both break).
  - Buying Variation deep M looks like sell signal. Filter: if Asia/London M depth >1.0 ATR but reclaims within 3–5 M15 bars + NY session approaching → variation buy, not sell.

## 7. Combined SMT + QT bot logic

```
DailyBias = QT_Cycle(Asia=A ? London=M ? NY=D)
If London M sweeps Asia low AND XAG holds (SMT bullish divergence):
  Bias = LONG for NY D
  Wait D displacement up + pullback to OCL/CE/SNR confluence
  Entry long, SL below M extreme, TP buy-side liquidity / HTF premium
Else if London M sweeps Asia high AND XAG holds high (bearish div):
  Bias = SHORT
Else No SMT + No clear M -> NO_TRADE or scalp X range only (derate size 0.5)
```

## 8. Repo mapping

- SMT divergence → new `MSNR_SMT.mq5` or EA filter: inputs `InpUseSMT=true, InpSMT_Symbol2=XAGUSD, InpSMT_CorrMin=0.70, InpSMT_Lookback=60, InpSMT_TolATR=0.3`. Buffers `SMT_State, SMT_Bias`.
- Correlated pairs whitelist → `InpSMT_Pairs="XAUUSD|XAGUSD;EURUSD|GBPUSD;USDCAD|USDCHF;AUDUSD|NZDUSD"`.
- AMDX cycle → session state machine in EA + `MSNR_Storyline` extension: `A/M/D/X` enum per day, `M_Point` buffer (manipulation extreme), `D_Impulse` flag.
- M sweep → E2 sweep detector scoped to Asia range high/low.
- D impulse → E2 BOS/displacement + E1 engulfing.
- Timing gate → `InpTradeLondonM=false, InpTradeNYD=true` (trade D, not M). M is signal, D is entry.

---
*Next: Part 09 (pages 92–106) — Daily Bias internal & external range liquidity + Daily Profile (London reversal / NY continuation / NY reversal / NY manipulation / Judas / Seek and Destroy #5).*
