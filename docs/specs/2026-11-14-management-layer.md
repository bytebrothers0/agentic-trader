# Management Layer Spec — MSNR Alchemist EA v2 (Task 12)

> Date: 2026-11-14. Sources (read in full): `abax mnsr/part11_entry_tp_sl_psychology.md`
> (primary), `phoenix_mnsr/MSNR_Part10_Trade_Management_Psychology.md` (secondary),
> enrichments: `luap smc/Part_15`, `advance mnsr1/video_11`, `video_9`, `part09`.
> Every value below is traceable to the codification doc
> (`docs/research/2026-11-14-strategy-notes-codification.md`, rule ids in brackets).

## 0. Contract

- **Regression gate:** with `InpUseManagement=false` the EA MUST reproduce the
  2026-11-14 baseline exactly (in-sample 2025.11→2026.11: 23 trades / 47.8% WR /
  PF 1.89 / +193.46 / DD 0.57%; hold-out 2025.05→2025.10: 6 trades / 66.7% WR /
  PF 4.02 / +66.03 / DD 0.15%). No baseline rule may change.
- Layer = **post-signal trade management + admission grading**. Entry signal
  engine untouched; grading only *gates and sizes* entries; partials/BE only
  *manage* open positions.

## 1. Grading engine (score → grade → size)

Score components (each 0/1 unless noted), per [P05-02 zone ladder, P11-02
confirmation ladder, P11-06 score map, V5-02, V7-01, V11-01, LU9-01, LU12-01]:

| Component | Points | Source |
|---|---|---|
| Sweep present (wick through level + close back) | +1.0 | P01-03 (sweep mandatory), P02-04 |
| Level FRESH (zero touches at entry) | +1.0 | V5-01 freshness rule, V7-01 |
| Level TF = D1 | +1.0 | P03-05 TF weight (D1=4 highest) |
| Level TF = H4 | +0.5 | P03-05 (H4=2) |
| Storyline gate passed (D1 structure broken; `d1_h1` mode = stricter gate, same credit) | +1.0 | V4-01 storyline formula |
| Session = London OR NY (07–20 UTC filter already passed) | +0.5 | P04-03 session weight (London=1.0/NY=1.0) |
| RR ≥ 1.5 at signal | +0.5 | P01-06, P11-04 |
| Touches == 1 (one prior wick touch, still within budget) | −0.5 | P03-01 second-touch derate |
| RR < min_rr | veto (no trade) | P01-06 |

**Grade mapping** (P11-06: ≥5 = A+ full; 4 = 0.7×; <4 = no trade):

> **Calibrated default (two-window rule, 2026-11-14):** `InpGradeMin=3.0` with
> B at 0.5×. The doctrine-literal 4.0 gate FAILED the two-window rule on the
> scout (IS −2.0R / HO −1.0R — only 2 A-band signals survive, both losses);
> 3.0 passes both windows (IS 21 tr/57% WR/+8.72R, HO 6 tr/67%/+2.47R).
> Honest note: the 5.0-score (A+) band was the worst performer on this small
> sample — consistent with the runbook's `RequireSweep=false` surface finding.
> Weights stay doctrine-literal; they are NOT retuned to 2 trades.

| Score | Grade | Size multiplier | Action |
|---|---|---|---|
| ≥ 5.0 | **A+** | 1.00 | trade |
| ≥ 4.0 | **A** | 0.70 | trade |
| ≥ 3.0 | **B** | 0.70 | trade only if `InpGradeMin=3` (default 4 ⇒ skip) |
| < 3.0 | **C** | 0 | never trade |

`InpGradeMin` input (default 4.0) = admission gate. Sweep-mandatory enforcement:
**C11 resolution** — a signal without sweep can never exceed grade A (cap 4.5
score), so it trades at 0.7× at most, never A+.

## 2. Partials ladder (profile A — P11-03, canonical)

Trigger prices (fixed at entry, symmetric long/short):

1. **TP1** = entry ± `1.5 × risk` [P11-03: IRL / 1:1.5 RR] → close **50%**,
   move SL to **breakeven** (entry price; `InpMoveToBreakeven=true` per book
   set input) [PH10-03, LU15-01].
2. **TP2** = the engine's level-based TP (ERL/nearest level) → close **30%**
   [P11-03: ERL/Fibo]. If TP1 ≥ TP2 (TP2 closer than 1.5R), TP2 collapses into
   TP1 and the ladder is 50% + 50% at TP.
3. **TP3** = runner **20%** → trails behind the last confirmed **M30 swing**
   (pivot window w = engine's `swing_pivot`) structural trail [PH10-03 "trail
   behind M15 lower highs" → M30 in our engine; LU15-01 LTF-CHoCH early-exit:
   a close through the trail = exit runner]. Hard floor: original TP still
   closes the runner if untouched [P11-03].

Loss path: if price returns to BE after TP1 → parts 2+3 exit at entry
(0R). Realized R for a TP1-then-BE trade = `0.5 × 1.5R = +0.75R` — the
asymmetry source. Full loss (SL before TP1) = −1R.

## 3. Profile B — obstacle management (V11-02, optional)

`InpManagementProfile = 1 (ladder) | 2 (obstacles)`:
- At the **first same-TF obstacle** between entry and TP (nearest opposing
  unbroken level ahead): close **80%** [V11-02] or SL→BE, remainder trails.
- TP = first major HTF obstacle [V11-02]. Default = profile A (ladder).

## 4. Psychology filters (EA inputs, default ON)

| Filter | Rule | Source |
|---|---|---|
| Daily loss cap | **max 2 losses/day → no new entries until next day** [P11-05] | `InpMaxLossesPerDay=2` |
| Re-entry cap | max 1 re-entry per zone per day [P11-05] | `InpMaxReentryPerZone=1` |
| Missed entry | never chase (engine already limit/market-once) [V12-03] | — |

## 5. EA inputs added (v2)

```
InpUseManagement      = false   // regression OFF
InpGradeMin           = 4.0
InpGradeAplusScore    = 5.0
InpSizeA              = 0.70
InpTp1RR              = 1.5
InpTp1ClosePct        = 50
InpTp2ClosePct        = 30
InpMoveToBreakeven    = true
InpManagementProfile  = 1
InpObstacleClosePct   = 80
InpMaxLossesPerDay    = 2
InpMaxReentryPerZone  = 1
```

## 6. Scout parity

`research/alchemist_backtest.py` gains the identical layer behind `mgmt=False`
default; the two-window scan (`robust_scan.py`) reports both baseline and
mgmt columns. Grade/partial behavior must match EA 1:1 (same constants).
