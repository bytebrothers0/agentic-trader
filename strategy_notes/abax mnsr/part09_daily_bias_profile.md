# ALCHEMIST 02 — Part 09: Daily Bias + Daily Profile — Internal/External Liquidity & London/NY Playbook (Pages 92–108)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-92.jpg` through `-108.jpg` — `DAILY BIAS internal & external range liquidity` divider, IRL/ERL theory, `DAILY PROFILE London reversal, ny continuation` divider (`>ny reversal >ny manipulation & Explanation >new York judas >seek and destroy`), London Session (02.00–08.30) rules, New York Session (CME Open 09.30) rules, `HTF Premium & Discount Array`, `Asian Range`, Daily Candle OHLC, M15 execution lens, 1st/2nd Opportunity, `DAILY PROFILE #5: SEEK AND DESTROY` full page, SMT-in-profile note.
> Thesis: **daily bias = choose which liquidity to target (internal vs external); daily profile = choose when/how to enter (London fake vs NY real)**. No bias = no trade, even if pattern looks perfect.
> Repo: E4 `MSNR_EMS_Range` (IRL/ERL), E5 PD arrays, session boxes, EA daily-bias gate.

## 1. DAILY BIAS — internal & external range liquidity (pages 92–96)

- Divider establishes module: bias is not direction prediction, it's liquidity selection.
- Core (reconstructed from charts + E4 alignment):
  - **External Range Liquidity (ERL):** buy-side above prior day/week high, sell-side below low. Resting stops + breakout orders. Final objective.
  - **Internal Range Liquidity (IRL):** intraday pools inside range — Asia high/low, London sweep point, FVG mids, OCLs, CE cluster. Stepping stones.
- Bias logic:
  - If price in **Premium** (upper half of HTF dealing range) → bias short toward internal low → external sell-side, unless ERL above already swept (then reversal long allowed).
  - If price in **Discount** → bias long toward internal high → external buy-side.
  - If price at **Equilibrium** → no bias, wait for M (manipulation) to show hand.
- HTF Premium & Discount Array (page 99 box):
  - `HTF Premium Array: Area mahal (potensi sell)` / `HTF Discount Array: Area murah (potensi buy)`.
  - `Dalam profil S&D, harga sering menyentuh kedua area ini tanpa langsung trending.` — premium/discount touch alone is not entry, needs profile confirmation.
- **Ambiguity:** same M15 bullish BOS in premium vs discount means opposite things. In discount = continuation toward ERL (trade). In premium = trap into ERL sweep then reversal (fade). Bot must gate every entry by `PremiumDiscountPosition`.
  ```
  PD = (Price - RangeLow)/(RangeHigh-RangeLow) // HTF D1/H4 dealing range
  Premium if PD>0.5, Discount if PD<0.5, Equilibrium if 0.45-0.55
  BiasLong only if Discount OR (Premium + ERL swept + SMT + MSS down->up)
  BiasShort only if Premium OR (Discount + ERL swept + SMT + MSS up->down)
  ```

## 2. DAILY PROFILE master divider (page 95)

- `DAILY PROFILE / London reversal, ny continuation / >ny reversal / >ny manipulation & Explanation / >new York judas / >seek and destroy`
- This is table of contents for intraday playbook. Four profiles implied (standard ICT + book naming):
  1. London Reversal → NY Continuation (trend day).
  2. NY Reversal (London consolidation, NY fake then real opposite).
  3. NY Manipulation / Judas (spike one side at NY open then run other side).
  4. Seek and Destroy #5 (choppy, both sides swept, low probability — page 105 detail).
- **Bot:** implement `DailyProfile` classifier after the fact for journaling + before the fact as `ExpectedProfile` from HTF context (range position + prior day type + news). Do not force one profile; detect.

## 3. London Session — 02.00–08.30 (pages 97–100)

- `Terjadi sekitar 02.00 – 08.30. Harga sering mengambil high dan low Asian Range. Namun gagal melanjutkan arah (tidak displacement kuat). Ini menandakan: Market belum punya arah jelas. Perlu konfluensi tambahan sebelum entry.`
- `> Catatan: Jam-jam ini dipelajari dari pengalaman TTrades.` — times are broker-dependent; parameterize.
- Asian Range box: `Range yang terbentuk saat sesi Asia, biasanya menjadi area awal pengambilan likuiditas. High dan low Asia sering disapu (sweep) pada sesi London atau New York.`
- Chart: `8pm / Midnight / London session 2-5am / NY AM session 8:30-11am (indices) / 12pm` timeline with `Asian range` beige box, London purple box, `HTF discount/premium array` grey bands, `1st Opportunity` (sweep low) and `2nd Opportunity` (continuation high) markers.
- **Rules for bot:**
  - London sweep of Asia high/low without displacement (`body<1.0 ATR`, no BOS) = manipulation signal, not entry. Mark `LondonSweepHigh/Low`.
  - London displacement (`body>1.5 ATR` + BOS) = potential trend-day signal; expect NY continuation same direction (Profile 1).
  - No displacement + both sides swept = Seek & Destroy warning (Profile 5) → derate size, widen confirmation.
  - Time inputs: `InpLondonStart=02:00, InpLondonEnd=08:30` server-adjusted; `InpAsiaHigh/Low` auto from 20:00–00:00 box.

## 4. New York Session — CME Open 09.30 (pages 100–102)

- `Ideal menunggu CME: Open 09.30. Harga biasanya bergerak ke H4/Daily PD Array. Setelah itu, harga sering kembali masuk ke dealing range.`
- M15 Timeframe = main execution lens for: `Manipulasi / Liquidity sweep / Entry di area ekstrem / Opportunity`.
- Daily Candle reminder: `High: harga tertinggi hari itu / Low: terendah / Open: pembukaan harian / Close: penutupan` — NY determines daily close shape; London shapes wick.
- 1st vs 2nd Opportunity:
  - `1st Opportunity: Biasanya setelah likuiditas pertama diambil (sering fake move)` — fade the first spike if SMT diverges + premium/discount extreme.
  - `2nd Opportunity: Peluang lanjutan setelah market menunjukkan reaksi yang lebih jelas` — trade the real move after retest + MSS.
- **Ambiguity:** first NY spike looks like breakout (displacement + BOS). Distinguish Judas (spike + immediate return + SMT hold) vs real D (spike + hold + LTF continuation + SMT confirms both break). Wait 2–3 M15 closes before deciding.
  ```
  if NY_Spike && CloseBackInside(3 bars) && SMT_Divergence -> Judas -> fade
  if NY_Spike && HoldsOutside && SMT_Confirms -> Real D -> continuation entry on pullback
  ```

## 5. DAILY PROFILE #5: SEEK AND DESTROY (page 105 full breakdown)

- Header: `Seek and Destroy adalah profil harian yang sering muncul dengan probabilitas rendah, tetapi bukan berarti tidak bisa ditradingkan. Profil ini biasanya menunjukkan market yang "berisik" dan belum memiliki arah jelas.`
- Conditions: `Tidak ada arah jelas di timeframe besar (HTF) / Market menunggu katalis penting (misalnya news berdampak tinggi).`
- Behavior: `Harga cenderung bergerak bolak-balik untuk mengambil likuiditas sebelum arah sebenarnya terlihat. Market mengambil likuiditas di kedua sisi. Bisa terjadi berulang kali. Tidak ada urutan pasti antara ambil high atau low dulu. Perbedaan bullish dan bearish bukan dari urutan, tetapi dari di mana harga close. Fokus utama adalah adanya HTF (H4 atau Daily) PD Array yang mendorong harga kembali ke dalam range.`
- Cara mencari setup: `Entry di area ekstrem. Setelah high/low range diambil. Target aman: Equilibrium (titik tengah range). Target agresif: Sisi sebaliknya dari Seek & Destroy range.`
- SMT note on page: `Terjadi saat ada manipulasi atau konsolidasi. Digunakan untuk menyamakan bias. Idealnya ada perbedaan arah dengan aset yang berkorelasi. SMT tidak wajib, tapi: sangat membantu meningkatkan confidence entry, terutama saat market tidak jelas arahnya.`
- **Bot S&D mode:**
  ```
  IsSeekDestroy = DayRange < 0.7*ATR_D1 && SweptHigh && SweptLow && !DisplacementClose
  // In S&D: scalp extremes to equilibrium only, size 0.5x, require SMT + CE/OCL extreme + LTF MSS
  // SafeTP = Equilibrium, AggroTP = opposite extreme
  // Disable trend-continuation entries (no D trade)
  ```

## 6. NY reversal / manipulation / Judas (pages 103–104, 106–108)

- NY Reversal = London trend then NY fake continuation + SMT divergence + premium/ERL sweep → reversal to equilibrium/opposite ERL.
- NY Manipulation & Explanation + New York Judas = classic Judas swing: spike beyond London/Asia extreme at/after 09:30 by 5–15 points, take stops, close back inside within 1–3 M15 bars, then run opposite into NY session. Book shows Judas spike above Asia high + immediate drop to discount array.
- Visual: Judas spike has long wick + small body + volume spike but no BOS hold; real breakout has body close outside + BOS + FVG.
- **Coding:**
  ```
  IsJudas = SpikeBeyond(AsiaHigh/LondonHigh, 0.2 ATR) && WickRatio>0.6 && CloseBackInside(2 bars) && SMT_Holds
  Entry = opposite direction on retest of spike CE/OCL + LTF MSS
  SL beyond Judas extreme + 0.3 ATR; TP equilibrium then opposite ERL
  ```

## 7. Visual ambiguities table — bias/profile

| Ambiguity | Looks same | Bot fix |
|---|---|---|
| Premium BOS up vs Discount BOS up? | Same green BOS | Check PD position first; premium BOS = trap unless ERL swept + SMT; discount BOS = continuation |
| London sweep vs London breakout? | Same poke high | Sweep = wick + close back + no BOS; breakout = body close outside + BOS + displacement |
| 1st vs 2nd opportunity? | Both spikes at NY open | 1st = first liquidity take (often fake, wait); 2nd = post-retest + MSS (trade) |
| Judas vs real D? | Both displace | Judas returns in ≤3 bars + SMT diverges; real holds + SMT confirms |
| S&D vs trend day? | Both sweep morning high | S&D sweeps both sides + no displacement close; trend sweeps one side + displacement + hold |
| Equilibrium target vs reversal? | Price stalls mid | In S&D take profit at EQ; in trend hold through EQ to ERL (use displacement strength + session time) |

## 8. MQL5 implementation

- Daily bias: `CalcDailyBias()` using D1/H4 range + PD + ERL swept flags + SMT bias. Output `BIAS_LONG/SHORT/NONE + TargetPool (IRL/ERL price)`.
- Profiles: `DetectProfile()` returns `P1_LondonRev_NYCont / P2_NYRev / P3_Judas / P5_SeekDestroy / UNDEFINED`. Log for journal + gate entries.
- Session boxes: `AsiaHigh/Low, LondonSweepH/L, NYOpenPrice, JudasHigh/Low` buffers + chart objects (reuse E4 range boxes).
- Inputs: `InpAsiaStart/End, InpLondonStart=02:00, InpLondonEnd=08:30, InpNYOpen=09:30 (CME), InpUseDailyBiasGate=true, InpTradeSeekDestroy=false/0.5size, InpEquilibriumTP=true`.
- Entries: London = signal only (no market order unless displacement trend-day + HTF bias); NY = execution window. Matches EA `InpSkipAsiaSession`, London/NY overlap boost.

## 9. Repo mapping

- IRL/ERL pools + PD arrays → E4 `MSNR_EMS_Range` (extend with Premium/Discount arrays + Equilibrium TP).
- PD position → E5 `MSNR_EMS_PremiumDiscount`.
- Sweep detection → E2/E3 (Asia high/low sweep, Judas spike).
- SMT confirm → Part 08 SMT filter.
- Session timing → EA time gate + Storyline session boxes.
- S&D mode → EA `ReduceRiskChoppy` + `InpMaxSpread` tightening.

---
*Next: Part 10 (pages 108–118) — Fibonacci Retracement custom (Abayfx levels), HTF key confluence, full-system synthesis, EA wiring checklist, THE END.*
