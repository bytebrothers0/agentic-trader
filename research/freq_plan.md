# Frequency Research — FINAL FINDINGS (day-trading build, ≥365 trades/year target)

> Goal: ≥365 trades/year (≥1/day) with positive net R on BOTH windows
> (IS 2025.11→2026.11 AND HO 2025.05→2025.10), accepting lower WR if RR/asymmetry
> carries it. Two-window gate is strict: both windows must be net-R positive.

## Bottom line (honest)

**365 trades/year with positive expectancy on both windows is NOT achievable** with this
single-symbol (XAUUSDm) strategy without curve-fitting. Every frequency lever tested
either (a) destroyed net R, (b) failed the hold-out window, or (c) reduced trade count.

**Critical finding: the frequency core FAILS in the MT5 EA tester.** The scout showed
positive R on both windows, but real tick data with spread/slippage/exit-timing costs
erodes the thin edge (~0.11 R/trade) into net losses:

| Config | IS trades | IS result | HO trades | HO result | EA two-window gate |
|---|---|---|---|---|---|
| Strict baseline (min_rr=1.5, dist=3) | ~23 | ~+13 R (scout) | 6 | ~+8.9 R (scout) | PASS (v1.07) |
| Frequency core (min_rr=1.0, dist=5, reuse) | 122 | **−$117 (EA loss)** | 56 | **−$84 (EA loss)** | **FAIL ❌** |

Annualized frequency: ~122/yr (IS) + ~112/yr (HO) ≈ ~234/yr combined — still ~37% short of
the 365/yr floor, AND net-negative expectancy in the EA.

## Best validated frequency core (F6 + F7 + re-use limits) — SCOUT ONLY, FAILS EA

```
min_rr=1.0, max_dist_atr=5.0, swing_near_atr=0.75,
require_fresh=False, uses_h4=6, uses_d1=12,
entry_tf=M30, max_candidates=1, trigger_required=True,
session_filter=False, bias_mode=d1, mgmt=False
```

**Scout results:**
- IS: 147 trades, 39.5% WR, +16.84 R, avg RR 2.37
- HO: 40 trades, 35.0% WR, +4.70 R, avg RR 2.38

**MT5 EA tester results (Model=4, ExecutionMode=100ms):**
- IS (2025.11→2026.11): 122 trades, final balance 9,883.06 (−$117) — NET LOSS ❌
- HO (2025.05→2025.10): 56 trades, final balance 9,916.03 (−$84) — NET LOSS ❌

**Both windows FAIL the two-window gate in the EA.** The thin scout edge (~0.11 R/trade)
does not survive real-world spread/slippage/exit-timing costs.

Edge is asymmetry (RR ~2.4×), not hit rate — consistent with the doctrine. But the edge
is too thin (~0.11 R per trade) to cover transaction costs.

## Every frequency lever tested — and why each failed the goal

| Lever | Tested config | Result | Verdict |
|---|---|---|---|
| F7: min_rr 1.5→1.0 | min_rr=1.0 | IS +13.2/+16.8, HO +3.7/+4.7 ✓ | **MERGED** (part of best core) |
| F6: max_dist 3→5 ATR | max_dist_atr=5.0 | HO R improves (+3.7→+8.8) ✓ | **MERGED** |
| F6: top-N candidates | max_candidates=3 | IS −14.2R | Rejected (dilutes quality) |
| F6: reaction-only entry | trigger_required=False | IS −11.9R, BEAR −15.2R | Rejected (trigger essential) |
| F1: Confirmation Entry | f1_module=True | IS flat +0.0R; CONF level −19.7R/19%WR | Rejected |
| Entry on M15 | entry_tf=M15 | IS +0.5R (thin), HO −0.2R ✗ | Rejected (HO fails) |
| Re-use limits | uses_h4=6, uses_d1=12 | Scout: IS 147/+16.8, HO 40/+4.7 ✓<br>EA: IS 122tr −$117, HO 56tr −$84 ✗ | **MERGED in scout, FAILS EA gate** |
| Mgmt layer ON | mgmt=True, grade_min=3.0 | IS only 3 trades (grade gate filters freq setups) | Incompatible with freq config |
| Session filter | session_filter=True | Fewer trades, both positive but lower freq | Rejected for frequency goal |

## Why 365/yr cannot be reached honestly

The entry engine is fundamentally rate-limited by:
1. **D1 bias gate** (`bias_mode=d1`): only trades when D1 structure is broken — not every day.
2. **One entry per M30 bar** max.
3. **Mandatory swing-break trigger**: removing it collapses expectancy (BEAR −15.2R IS).

Relaxing any of these to chase frequency destroys net R (proven above). Adding new entry
models (F1 Confirmation Entry implemented and tested) also destroyed expectancy. New models
F2 (D1/W4) and F3 (FTFL continuation) remain unimplemented but face the same structural
constraint; based on F1's failure, they are unlikely to add profitable frequency.

## Regression lock (unchanged)

`InpUseManagement=false` + all family flags OFF = bit-identical v1.07 baseline
(23 IS / 6 HO trades). Verified on scout; never changes.

## Recommendation

1. **Do NOT deploy the frequency core as a replacement for EA v2.00.** Both IS and HO
   windows show net losses in the MT5 EA tester. The thin scout edge does not survive
   real-world costs.
2. **EA v2.00 (management layer) remains the only validated version:**
   - IS: 28 trades / 53.6% / +425.87 / PF 1.92 / DD 2.12%
   - HO: 14 trades / 78.6% / +327.63 / PF 4.02 / DD 0.60%
   - But only ~28 trades/year — far below the 365/yr goal.
3. **Do not force 365/yr** — doing so requires curve-fitting (the hold-out discipline
   exists precisely to prevent this; the earlier 10496-combo sweep winner failed HO at
   −38.51 / PF 0.82).
4. If the user insists on ≥365/yr, the honest path is a **multi-symbol or multi-strategy**
   basket (e.g., XAUUSDm + XAGUSD SMT divergence, or additional uncorrelated entry models),
   not over-trading a single mean-reversion model on one symbol.

## Files

- `research/alchemist_backtest.py` — scout with gated-off probe code (f1_module,
  trigger_required, max_candidates, entry_tf, uses_*, min_rr, max_dist_atr).
- `research/freq_plan.md` — this document (final findings).
- `docs/research/2026-11-12-mql5-loop-runbook.md` — runbook with full ledger.
