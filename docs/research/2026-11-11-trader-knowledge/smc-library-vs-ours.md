# SMC Python Library vs Our Detectors — verdict (2026-11-11)

Question: replace our indicator stack with the `smartmoneyconcepts` pip
library (joshyattridge, v0.0.27)? Short answer: **no — keep ours as the
primary, keep the library as an offline cross-validation referee, and port two
of its primitives.** Evidence below.

## What the library actually is

- 2.2k stars / 910 forks / MIT / 157 commits / single maintainer / 20 open
  issues, 10 open PRs. Wheel is 13.7 kB (~600 lines of code).
- PyPI metadata classifies it **"Development Status: 1 — Planning"** (the
  most immature classifier), and its own disclaimer: *"for educational
  purposes only. Do not use this indicator as a sole decision maker"*.
- **"Institutional grade" is marketing, not lineage**: no institutional
  provenance, no peer review, no published backtest. Our own research log
  (sources.md [S18], SSRN 7483658) formalised 44 community SMC detectors of
  exactly this class on S&P 500 daily bars and found **zero aggregate
  predictive edge**. The library is a clean implementation of that class —
  useful primitives, no proven edge.

## Empirical head-to-head (same XAUUSDm candles, Nov 9–11 window, 180 bars)

Tool: `tools/smc_library_compare.py` + `tools/smc_library_tune_probe.py`.

| Detector | smc library (defaults) | smc library (retuned) | Ours |
|---|---|---|---|
| Swings M15/H4 | 3 / **0** | 25 / 15 (length=5) | granular Donchian zigzag, 14–20 structure levels |
| BOS/CHoCH M15/H4 | **0 / 0** | 9 / 8 total | 14 / 20 levels incl. FRESH standing levels |
| Liquidity pools M15/H4 | **0 / 0** | 3 / 1 | 3 / 2 with FRESH/TAKEN states |
| FVG | 34 / 40 gaps, 6 / 4 unmitigated | same | 47 / 60 active — **overlap: 9/10 of its unmitigated gaps sit inside our active gaps** |
| PDH/PDL | ✅ 4141.43 / 4013.44 + broken flags | — | not a first-class family (gap, see below) |
| Retracement % | ✅ current 42.1% / deepest 60.1% | — | agent computes by hand |

The one definition where both agree is the raw 3-candle FVG — that definition
is universal. Everything else diverges categorically.

## Why it cannot be the primary source for the agent (code-level, not opinion)

1. **Swing look-ahead.** `swing_length=50` is doubled to a 100-candle window
   with 50 bars of look-FORWARD: a swing is only confirmed 50 bars after it
   happens (12.5h on M15, ~8 days on H4). Live, recent structure does not
   exist yet. Retuning to 5–10 helps but keeps the delay (and its H4 session
   windows confirm 20h late).
2. **It deletes standing structure.** `bos_choch` removes every BOS/CHoCH
   that price has not yet broken (`broken == 0 → removed`). The levels a
   trader reasons FROM — "bias is bearish, invalidation is a close above
   4094.842" — are exactly the ones it throws away. Our stack keeps FRESH
   levels with the invalidation semantics the agent interviewed on all night.
3. **No sweep-vs-break rule.** Its liquidity `Swept` flag fires on a wick
   pierce of a range boundary — no body-close-back test. The close-back rule
   is the single most load-bearing distinction in our knowledge layer
   (liquidity.md), and the agent used it correctly in the graded interviews.
4. **No internal/external structure** — the exact flaw we caught in the agent
   in round 1 and fixed via the prompt, and our detector labels natively
   (`I-` prefixes).
5. **Missing 9 of our 13 families**: no IFVG, QM, IDM, trendlines (sloped,
   role-flip, channel), CRT, TS, SR, OCL, APEX; no breaker-flip semantics on
   OBs, no BOS/sweep association metadata.
6. **Sessions are hardcoded UTC** — no DST handling. Our own research (S10)
   established UK/US DST shifts move the windows; half the year the library's
   killzones are an hour off. We read MT5 server time.
7. **No integration surface**: no level_lookup, no render/labels, no durable
   store, no families knob, no feed→briefing pipeline, no tests in our CI
   sense — 427 tests stand behind our detectors.

## What the library IS good for

1. **Cross-validation referee (recommended, adopt).** It is independent code
   implementing the same primitives; running it offline against our detectors
   catches definition drift and labeling bugs on OUR side. Last night's one
   agent misread (UNFRESH FVG called "fresh") is exactly the class of issue an
   independent second opinion referees. `tools/smc_library_compare.py` is the
   starting harness; make it a weekly check, and investigate any disagreement
   rather than assume.
2. **Two primitives worth porting (candidate, additive only — operator
   decides):**
   - `previous_high_low`: clean PDH/PDL + BrokenHigh/Low flags. Its output
     (PDH 4141.43 / PDL 4013.44) cross-checks OUR data: 4013.44 is exactly the
     M15 dealing-range low the agent used and verified. If our briefing does
     not emit PDH/PDL as first-class levels, that is a real gap worth filling.
   - `retracements`: current/deepest retracement % per swing — the
     premium/discount math the agent currently performs by hand in prose.

## Deployment hygiene (done)

- `pip install smartmoneyconcepts` pulled `numba`/`llvmlite`. It stays
  **research-only**: nothing in `server.py`/`agent_service.py` imports it, and
  it is deliberately NOT added to the runtime requirements. The comparison
  tools degrade gracefully if it is missing (import at top of the tools only).

## Bottom line

The library is a decent, readable educational toolkit whose FVG definition
matches ours and whose PDH/PDL + retracement primitives are worth borrowing.
It is not "institutional grade" and not a replacement: structurally
batch-oriented (look-ahead swings, standing-structure deletion, no states),
missing most of our families, and from the evidence class our own research
graded at zero aggregate edge. Ours wins as primary; the library wins a
permanent side job as referee.
