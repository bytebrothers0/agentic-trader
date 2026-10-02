# ALCHEMIST 02 — Part 11: Entry Models, TP/SL & Trading Psychology — Codable Playbook (Synthesis of Pages 0–118)

> Source: synthesis of Parts 01–10 + `3b23b774-e31c-43ba-8ab5-a72e471a86a0-0.jpg` through `-118.jpg` — all entry triggers, confluence checklists, QML/QMX/CE/OCL/SMT/Judas/S&D/Fibo rules, `Kata Penutup` psychology, `sample2, v6.set` risk inputs.
> Thesis: **entries = sweep + zone + confirmation; exits = liquidity shelves; psychology = code discipline so bot does what human cannot**. No A+ setup without all three.
> Repo: `MSNR_ExactBacktestEA_v6` E9 planner, all I/E inputs, `InpMagic=888999`, `InpMoveToBreakeven=true`.

## 1. Unified entry philosophy (from book)

- `Alchemist = seni membaca niat market, bukan sekadar melihat pergerakan harga.` Intent = liquidity grab → acceptance → displacement.
- Never trade line touch alone (Mistake #1). Valid sequence everywhere in book:
  ```
  HTF Bias + PD Position -> Liquidity Sweep (fake) -> Zone Touch (SNR+OB50/OCL/CE/TL/QML) -> Confirmation (engulf/reject/close-back/MSS) -> Entry -> SL beyond fake -> TP next pool
  ```
- `Wait for sweep -> zone touch -> confirmation candle.` / `Tunggu clear reaction: rebound or rejection. Must be near HH/HL/LH/LL. If touched after sweep, valid.`
- Planning ahead vs waiting: `Confirmation through plan, not emotion.` Limit orders at pre-planned confluence allowed when score ≥5 (book: *no need extra candle — plan itself is entry*). Parameterize `RequireConfirmationCandle`.
- Patience rule (Part 03): `Most enter too early — see small move assume reversed, only to be stopped. Let break happen first — then enter on retest. No rushing/chasing. / Banyak masuk terlalu cepat — akhirnya kena stop. Biarkan break dulu — baru entry saat retest.`

## 2. Entry models catalogue (A–H) — every model in book

### Model A — Bullish Reversal Playbook (Part 01 core)
1. HTF begins shifting bullish (H4 bias up).
2. Price sweeps sell-side below prior lows.
3. Taps zone (SNR+OB+50%OB) + rejection.
4. Enter on close back above zone or LTF substructure break.
- Mirror bearish. RR≥1:1.5. This is default model; all others are filters/specializations.

### Model B — OCL Retest / Flip (Part 05)
- Virgin OCL → watch. Retest + rejection (engulf/wick+close-back/LTF MSS) → entry.
- Broken OCL (body close through) + retest from other side → role-flipped RBS/SBR entry.
- Only displacement candles birth OCL (`body>1.5 ATR`). Doji/small = ignore.
- Session weight: London/NY 1.0, Asia 0.5 + extra confirm or skip.

### Model C — QML SNR+TL Triple (Part 06 §3)
- Fake HH/HL forms QML + SNR flip + TL touch (3 red dots) + bearish/bullish candle → strong reversal.
- SL beyond QML extreme + ATR buffer. TP next liquidity/structure.
- Highest probability turning point when all three agree.

### Model D — QMX Cross (Part 06 §4, stricter than C)
- QM level × trendline geometric intersection at point 3 (1-2-3 pattern) + `EGULF` engulf before point 3.
- `IsQMX = QM + TL_Intersects + Engulf`. Weight +1 over QML-TL. After signal usually drops/rallies aggressively.

### Model E — CE Cluster Magnet (Part 07)
- Displacement CE + OBmid + FVGmid cluster `[min..max]` within 0.2 ATR.
- Pullback to cluster edge + rejection + LTF MSS → limit entry.
- SL beyond displacement extreme / FVG extreme. Invalidate after 3 crosses (chopped → fair).

### Model F — SMT Fade + NY 2nd Opportunity (Part 08–09)
- Correlated pair holds while traded symbol fakes extreme (XAU vs XAG, Corr>0.70).
- Wait close back inside (do NOT enter spike). Then OCL/CE confluence + MSS → entry to true direction.
- 1st opportunity = often fake (skip); 2nd = real (trade).

### Model G — Judas / London Sweep Fade (Part 09)
- Asia high/low swept by London (02:00–08:30) wick + close back, no BOS → mark sweep.
- NY 09:30 CME spike beyond sweep + wick>60% + return ≤3 bars + SMT holds → fade opposite.
- SL beyond Judas extreme +0.3 ATR. TP equilibrium then opposite ERL.

### Model H — Trend Continuation / Fibo Breakout-Retest (Part 10)
- HTF 6-way shelf (key+OB+RBS+FVG+QMM+classicV ≥3) anchors Fibo low.
- Break above `high (1.0)` + hold + retest 1.0–1.55 shelf → continuation long to 2.235→2.88→3.27→buyside.
- SL beyond -0.78 shelf (max Judas), not 0. Fibo never gates, +0.5 score.

## 3. Confirmation ladder (what counts as confirmation?)

1. `Confirming Candle: Engulfing / Strong rejection wick` (E1).
2. `Close-Back-In-Range: after sweep, price closes back above/below zone` (sweep rule + SMT rule + Judas rule — same).
3. `Touch 50% OB/CE + confirmation candle` (OB50/CE cluster edge).
4. `LTF MSS/BOS in entry direction after touch` (E2 — strongest, required for Asia/S&D).
- Rule: virgin touch alone = watch. One confirmation = standard entry (score≥4). Two confirmations = A+ full size (score≥5). No confirmation + full stack (score≥5 + plan-limit) → allowed limit per book, flag `PlanEntry=true`.

## 4. SL psychology & placement (where losers place stops = where book places SL)

- Principle: `Market must take others' stops before real move. / Market takes out stops before continuing.` SL goes where retail does NOT — beyond fake extreme, not beyond obvious level.
- Rules by model:
  - A/B/E: beyond sweep wick extreme + 0.2–0.3 ATR buffer + spread.
  - C/D: beyond QML/QMX extreme + ATR buffer.
  - F/G: beyond fake/Judas extreme +0.3 ATR (not true-leg extreme).
  - H: beyond -0.78 Fibo shelf + buffer (beyond = invalidation).
  - LTF 50-method scalp: ~10 pips on M15/H1 confirmation (XAU: tune points, e.g. 100–150 points) + HTF-structure fallback SL. Tag `HIGH_RISK`.
- Invalidation (When SNR Fails): `Too many touches no rejection / No sweep / HTF contradicts / Breaks with strong momentum`. Exit/skip, do not average.
- Chopped CE (≥3 crosses/20 bars) = dead, exit breakeven.
- Code: `SL = FakeExtreme ± (0.3*ATR + Spread*1.5)`. Never fixed pips except LTF scalp + fallback.

## 5. TP psychology & placement (targets predefined by liquidity)

- `Price does not move randomly. Liquidity comes first. Targets are predefined by liquidity. / Harga tidak bergerak sembarangan. Likuiditas selalu menjadi tujuan awal. Target sudah "ditentukan" oleh likuiditas.`
- Ladder: `IRL (intraday FVG/OCL/CE) -> ERL (buy/sell side day/week high-low) -> Fibo extension (2.235/2.6/2.88/3.27/4–4.733 buyside) -> HTF key`.
- Rules:
  - Trend day (London displacement + NY continuation): hold through equilibrium to ERL/Fibo ext.
  - S&D / chop: `SafeTP = Equilibrium, AggroTP = opposite extreme`, half size, no runner.
  - Premium short → discount ERL; Discount long → premium ERL (E4/E5).
  - `TP FIBO CIRCLES / end of circles` time projection = optional time-stop, not primary target.
- Partials (bot discipline for human greed/fear):
  ```
  TP1 = IRL / 1:1.5 RR -> close 50%, move SL to breakeven (InpMoveToBreakeven=true)
  TP2 = ERL / Fibo 2.6-2.88 -> close 30%, trail by structure (LTF BOS)
  TP3 = Fibo 3.27-buyside / HTF key -> runner 20%
  ```

## 6. Filters that enforce psychology (code what human cannot)

- HTF gate: `Trade only with H4/D1 bias + PD position. HTF bearish + buy = skip (Mistake #3).`
- Sweep gate: `No sweep = no trade (even if zone looks perfect).`
- Touch-count derate: `Multiple touches -> weaker -> reduce size or wait stronger confirmation.`
- Session gate: `Asia = derate/skip; London = signal; NY = execution; Overlap = best. Matches InpSkipAsiaSession.`
- SMT veto: `SMT contradicts direction -> skip or halve size (-1.5 score).`
- Spread/news: `InpMaxSpread + news blackout (S&D + high-impact news = no new entries).`
- Daily loss / revenge: `Max 2 losses/day or -X% -> stop (codes patience). Max 1 re-entry per zone (codes no chasing).`
- RR gate: `Min 1:1.5 (Quick Rules #4). Skip if SL-to-TP <1.5 after buffer calc.`

## 7. Risk & position sizing (from set file + book)

- `sample2, v6.set`: `InpMagic=888999, InpMoveToBreakeven=true` + trendline/session inputs. Extend:
  ```
  InpRiskPercent=0.5-1.0, InpMinRR=1.5, InpReduceRiskSeekDestroy=true (0.5x),
  InpAsiaRiskMult=0.5, InpAPlusSizeMult=1.0, InpStdSizeMult=0.7, InpPlanEntryAllowed=true
  Score->size: >=5 A+ full, 4 standard 0.7x, <4 no trade; S&D caps 0.5x to EQ only
  ```
- XAUUSD specifics: volatile, wide stops, 200–300 point buffers on HTF flips; M15 entries need ATR-normalized SL, not fixed 10 pips except scalps.

## 8. Visual ambiguities — entry/exit edition

| Ambiguity | Fix |
|---|---|
| Touch vs confirmation? | Touch=alert, confirmation=entry (except plan-limit score≥5) |
| Wick poke SL vs body break SL? | Wick poke holds (keep SL); body close beyond = invalid, exit/flip |
| 1st vs 2nd NY spike? | 1st often fake (wait), 2nd after retest+MSS (trade) |
| Judas vs breakout? | Return ≤3 + SMT diverge=Judas fade; hold + SMT confirm=break follow |
| EQ bounce vs reversal? | S&D take profit at EQ; trend hold through EQ to ERL |
| Fibo 0 vs -0.78 SL? | SL beyond -0.78 shelf, not 0; beyond -0.78 = invalidation |
| A+ vs B setup sizing? | Score≥5 full + runner; 4 standard no runner; S&D 0.5 to EQ |

## 9. MQL5 wiring snippet

```mql5
// E9 planner pseudo
bool CanTrade(Model m, Zone z, Bias b, Session s, SMT st) {
  if(!HTF_Agrees(b) || !PD_Allows(b)) return false;
  if(!HasSweep(z)) return false;
  if(s==ASIA && !ExtraConfirm(m)) return false;
  if(SMT_Contradicts(st,b)) return false;
  int score = Score(z); // OCL+1 SNR+1 FVG+1 TL/QML/QMX+1 CE+1 SMT+1.5 Fibo+0.5 session+1 MSS+1
  if(score < InpMinConfluenceScore) return false;
  if(!HasConfirm(m) && !(score>=5 && InpPlanEntryAllowed)) return false;
  double sl = SL_BeyondFake(z) , tp1 = NextIRL(b), tp2 = NextERL(b), tp3 = FiboExt(b);
  if((tp1-Entry)/ (Entry-sl) < InpMinRR) return false;
  return true;
}
void Manage() { TP1->50% + BE; TP2->30% + trail BOS; TP3 runner; Chopped/Invalidate->BE/exit; }
```

## 10. One-page cheat (tape to monitor / EA comment)

1. HTF bias + premium/discount? If no → wait.
2. Sweep + SMT holds? If no → wait.
3. Zone stack ≥4 votes (SNR+OCL/CE+TL/QML/Fibo)? If no → watch.
4. Confirmation (engulf/close-back/MSS)? If score≥5 plan-limit allowed.
5. SL beyond fake/-0.78, TP IRL→ERL→Fibo, RR≥1.5? If no → skip.
6. Session NY execution, Asia skip, S&D half to EQ? Enforce.
7. After TP1 → BE, no revenge, max 2L/day. Psychology = automation.

---
*End Part 11. Completes 11-part ALCHEMIST 02 series (all >100 lines). Code order: bias/PD gate → sweep/SMT → zonescore → confirm → SL/TP/partials → session/psychology filters → journal profile+score for review.*
