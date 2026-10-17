# ALCHEMIST 02 — Part 07: Candle Equilibrium (CE) / Consequent Encroachment — 50% Core (Pages 64–78)

> Source: `3b23b774-e31c-43ba-8ab5-a72e471a86a0-64.jpg` through `-78.jpg` — `HOW TO USE CANDLE EQUILIBRIUM (CE) IN TRADING` (ID+EN), `TEKNIK MENGGUNAKAN ZONA 45%–50%`, `15 MINE SELLING` worked example with magnifier on 0.5, `IN SUMMARY` box, `KESIMPULAN` box, CE+FVG/OB stacking diagrams, strong vs weak CE.
> Thesis: **CE = midpoint of battle between buyers/sellers = smart-money test line**. Price returns to CE to test strength before continuation or reversal. Most traders watch close/break; pros watch center.
> Repo: E5 `MSNR_EMS_PremiumDiscount` (PD50) extension to wick/OB/FVG mids, E6 FVG, I1 levels.

## 1. APA ITU / WHAT IS CE (page 64–66 verbatim logic)

- ID: `CE (CANDLE EQUILIBRIUM) ADALAH TITIK KESEIMBANGAN DARI SEBUAH CANDLE. JIKA KAMU MENGGANGGAP SATU CANDLE SEBAGAI "MEDAN PERTARUNGAN" ANTARA BUYER DAN SELLER, MAKA CE ADALAH TITIK TENGAH DARI PERTARUNGAN TERSEBUT — DIGUNAKAN UNTUK MENENTUKAN SIAPA YANG SEDANG MENGUASAI PASAR.`
- EN: `CE IS THE BALANCE POINT OF A CANDLE. IF YOU THINK OF A CANDLE AS A "BATTLEFIELD" BETWEEN BUYERS AND SELLERS, THEN CE IS THE MIDPOINT OF THAT BATTLE — USED TO DETERMINE WHICH SIDE IS CURRENTLY IN CONTROL.`
- Three control rules (both languages):
  1. `Jika harga tetap berada di atas CE dari candle bullish yang kuat → buyer masih mengontrol / If price stays above CE of strong bullish candle → buyers remain in control.`
  2. `Jika harga turun di bawah CE dari candle bullish yang kuat → seller mulai mendapatkan keunggulan / If price falls below CE → sellers begin to gain advantage.`
  3. `Jika harga retest CE dari candle bearish kuat lalu turun kembali → tekanan jual masih dominan / If price retests CE of strong bearish and drops → selling still dominant.`
- Simple: `CE adalah titik di mana market kembali untuk "menguji kekuatan pergerakan sebelumnya" / CE is the point where market returns to "test strength of previous move."`
- **Bot rule:**
  ```
  CE = (High + Low)/2  // INCLUDING wicks, not (Open+Close)/2 — book explicit
  BullishControl = Close > CE AND Low_of_next_3 > CE
  BearishControl = Close < CE AND High_of_next_3 < CE
  LossOfControl = cross of CE with body close (not wick poke)
  ```

## 2. 45%–50% technique (pages 67–70)

- ID: `CE ADALAH TITIK KESEIMBANGAN YANG DIGUNAKAN SMART MONEY UNTUK MENGIDENTIFIKASI APAKAH SUATU PERGERAKAN ITU VALID ATAU HANYA FAKEOUT.`
- Common mistake: focus on bullish/bearish close or break of level. Overlooked: **center of candle itself**.
- `AREA TERSEBUT MERUPAKAN INTI KEKUATAN MARKET — DIKENAL SEBAGAI CE, ATAU TITIK TENGAH ANTARA TEKANAN BELI DAN TEKANAN JUAL.`
- Calculation: `CE = titik tengah antara high dan low (termasuk sumbu/wick). Zona paling sering digunakan adalah 45%–50% dari range candle, karena harga sering kembali ke area ini untuk "mengecek kekuatan sebelumnya" sebelum melanjutkan arah yang sama atau reversal.`
- EN mirror: `CE IS THE BALANCE POINT THAT SMART MONEY USES TO IDENTIFY WHETHER A MOVE IS GENUINE OR JUST A FAKEOUT... MOST COMMONLY 45%–50% ZONE... PRICE OFTEN RETURNS TO "CHECK PREVIOUS STRENGTH" BEFORE CONTINUING OR REVERSING.`
- **Ambiguity — CE vs OB-50% vs FVG-50%:**
  - All three compute 50% but on different ranges: CE on single candle `H/L`, OB-50% on order-block range, FVG-50% on gap range.
  - Charts show them stacked: `SS / CE / resis` labels overlapping within 10–20 points. Human merges them; bot must keep separate then score overlap.
  - Overlap of 2+ mids = magnet (book: `MAGNET HARGA SEBELUM PERGERAKAN BESAR`).
  ```
  CE_candle = (H_c+L_c)/2
  OB_mid = (OB_H+OB_L)/2
  FVG_mid = (FVG_Top+FVG_Bot)/2
  Magnet = (abs(CE-OB_mid)<0.2 ATR || abs(CE-FVG_mid)<0.2 ATR)
  ```

## 3. 15 MINE SELLING worked example (pages 71–73)

- Left panel `1.` : M15 uptrend into `0,65 / 0,5 / 1` Fib-like scale, then black displacement candles down, pullback to `SS` (supply) line, then continuation down.
- Right panel magnifier: `62 / 45` scale zoom on small consolidation candles into `resis`. Shows CE line through bodies, price retesting from below then dropping.
- Long vertical drop panel: series of bearish candles with lower highs, each retesting prior CE then failing — textbook `CE as dynamic resistance`.
- KESIMPULAN box (ID):
  - `CE BUKAN SEKADAR TITIK TENGAH CANDLE. CE ADALAH: Pengukuran kekuatan candle / Alat konfirmasi arah dan momentum / Support/resistance dinamis / Tempat retest favorit smart money / Magnet harga sebelum pergerakan besar.`
  - `DENGAN MENGGABUNGKAN CE DENGAN TRENDLINE, LIKUIDITAS, VOLUME, ATAU ORDER BLOCK, AKURASI TRADING DAPAT MENINGKAT SANGAT SIGNIFIKAN.`
- IN SUMMARY box (EN):
  - `CE IS NOT JUST A MIDPOINT. IT IS: A measurement of candle strength / A confirmation tool for trend continuation / A dynamic support/resistance reference / A smart-money "retest zone" / A magnet for price before large moves.`
  - `BY COMBINING CE WITH TRENDLINE, LIQUIDITY, VOLUME, OR ORDER BLOCKS, TRADERS CAN SIGNIFICANTLY IMPROVE THEIR ACCURACY AND AVOID FALSE SIGNALS.`
- **Bot entry pattern from example:**
  1. Displacement candle (body >1.5 ATR) establishes CE.
  2. Slow pullback (3–5 small candles) returns to `CE ± 0.15 ATR`.
  3. Rejection (wick + bearish close back below CE for sell) → entry.
  4. SL beyond candle high + buffer; TP next liquidity / HTF key.
  - Do not enter on first touch if pullback is impulsive (strong close through CE = loss of control, flip bias).

## 4. Strong vs weak CE (pages 74–76)

- Strong CE (tradeable):
  - Born from displacement / engulfing / BOS candle (large body, small opposite wick).
  - Retest holds with wick rejection + close back on control side.
  - Aligned with trendline / SNR / liquidity (confluence).
  - Session London/NY.
- Weak CE (skip or derate):
  - Born from doji / inside bar / low-range Asia candle.
  - Price chops across CE multiple times (3+ crosses = magnet失效, becomes fair value, not S/R).
  - No confluence, isolated mid with no structure.
- Visual ambiguity: every candle has a mathematical midpoint, but only few are CE zones. Book shows many mids drawn then crossed out — only displacement mids kept.
- **Coding filter:**
  ```
  IsCECandidate = Range > 0.8*ATR && Body > 0.6*Range && Body > 1.2*ATR*0.5
  IsStrongCE = IsCECandidate && (Engulf || Displacement || BOS) && Session!=ASIA
  InvalidateCE if CrossCount(CE, next 20 bars) >=3  // chopped -> fair, not level
  ```

## 5. CE stacking with FVG / OB (pages 76–78)

- Diagrams show CE line through FVG gap mid + OB mid converging: `FVG CE + OB CE + Candle CE` triple magnet.
- Rule: when FVG forms after displacement, its 50% often equals displacement CE within tolerance. That double-mid is preferred limit entry over single-mid.
- Order: displacement → FVG (gap) → OB (last opposite candle) → all three mids cluster → pullback to cluster → rejection → continuation.
- **Ambiguity:** which mid to use for limit? Book: use cluster zone `[min(mids)..max(mids)]`, entry at cluster edge + confirmation, SL beyond cluster + FVG extreme.
- Repo: extend E5 PD50 from range-50% to `CandleCE + OBmid + FVGmid` triple buffer. Add `CE_Cluster` object.

## 6. Visual ambiguities table — CE

| Ambiguity | Human error | Bot fix |
|---|---|---|
| CE = (O+C)/2 vs (H+L)/2? | Uses body mid | Must use `(H+L)/2` incl wicks per book; body-mid is OB-mid, different object |
| Every mid = CE? | Marks all | Only displacement/engulf/BOS candles; filter by ATR/body/range |
| Wick poke through CE = break? | Exits on wick | Require body close beyond CE; wick poke + close back = hold + entry signal |
| Chopped CE? | Keeps trading mid | Invalidate after 3 crosses in 20 bars; convert to fair value, no trade |
| Single CE vs cluster? | Picks one | Build cluster `[min..max]` of CE/OBmid/FVGmid within 0.2 ATR; trade zone |
| CE without confluence? | Trades isolated | Require TL or SNR or liquidity overlap; else watch only (score <4) |
| Session? | Ignores time | Weight London/NY CE 1.0, Asia 0.5 + extra confirm |

## 7. MQL5 implementation

- New buffers or extend E5: `CE_Level, CE_Top45 (0.45), CE_Bot50, CE_Strength (0-3), CE_State (virgin/tested/holding/broken/chopped), CE_ClusterTop/Bot`.
- Inputs: `InpCE_MinBodyATR=1.0, InpCE_MaxCross=3, InpCE_Lookback=20, InpCE_ClusterTolATR=0.2, InpCE_RequireConfluence=true`.
- Functions: `double CandleCE(int shift) { return (High[shift]+Low[shift])/2; }`, `bool IsStrongCE(shift)`, `bool IsCEHolding(shift, dir)`, `bool IsCEBroken(shift, dir)` (body close rule), `int CountCECrosses(level, lookback)`.
- Entry: limit at `CE_Cluster` edge, confirmation = rejection wick + close back + LTF MSS; SL beyond displacement extreme; TP next HTF liquidity.
- Combine: `Score += 1 if CE_Cluster && holding`; `Score += 0.5 if single strong CE`.

## 8. Repo mapping

- CE core → extend `MSNR_EMS_PremiumDiscount` (E5) beyond dealing-range 50% to per-candle CE + OBmid + FVGmid.
- FVG mid → `MSNR_EMS_FVG` (E6) add `FVG_Mid` buffer.
- OB mid →OB handling in E1/E4 add `OB_Mid`.
- Displacement qualifier → E2 BOS/displacement detector.
- Session weight → EA session gate.
- Confluence → E9 planner + Part 06 trendline/SNR stack.

---
*Next: Part 08 (pages 78–90) — SMT Divergence (XAU/XAG + correlated pairs) + Quarterly Theory / AMDX cycle (Asia/London/NY, A/M/D/X).*
