# Alchemist MSNR autonomous backtest — 20261118-0826
- strategy: `alchemist_mnsr_v2` | date: 2026-11-18T08:26:27+00:00
- setups found autonomously: 3 (CRT sweep + close-back at PDH/PDL)
- metric: outcome agreement (directional call vs realized close-to-close move)

| # | type | cutoff (UTC) | level | call | realized | agree | ok |
|---|---|---|---|---|---|---|---|
| 1 | BULLISH CRT at PDL | 06-19T00:30 | 4186.72 | UP | DOWN | False | True |
| 2 | BULLISH CRT at PDL | 06-19T01:15 | 4186.72 | NO-ANSWER | DOWN | False | False |
| 3 | BULLISH CRT at PDL | 06-23T03:00 | 4139.90 | NO-ANSWER | DOWN | False | False |

**Agreement vs realized: 0/1 = 0% (target >=70%)**
| NO-TRADE calls: 0 | failed turns: 2 |

## Full answers
### Setup 1 — BULLISH CRT at PDL — call UP (realized DOWN) — cutoff 06-19T00:30 UTC

D1 storyline: bearish/downtrending. From the August high near 4697, price broke down through the October–November range and is now sitting at the window low near 3757.209. External structure is down — the story is a downtrend testing its lows, not a reversal.

H4 storyline: confirms the breakdown. Price fell from the H4 window high near 4148.654 into the same low area near 3757.209 in an impulsive leg. Both frames agree price is at the lows; neither shows a fresh bullish structure yet.

The sweep at the key downside level (PDL/session extreme) with price closing back inside is a failed breakdown — a reclaim, not a real break. A real break would be a body close beyond the level; that didn't happen, so the downside probe failed and the close-back is the rejection tell.

Session: we're in the London killzone (~03:28 NY). Asia consolidated the overnight range; London is the manipulation session that sweeps one side, and NY delivers next. A London sweep of the lows with a close-back inside sets up NY delivery to the upside.

POI: the reclaimed zone above the swept low near 3757.209. Price holding above that swept extreme is the bounded area where the next decision matters.

Directional call: UP for the next few hours. The failed breakdown at the lows, with London manipulation ahead of NY delivery, favors a bounce back toward the prior range rather than a fresh breakdown. This is a mean-reversion bounce, not a trend change — the D1 downtrend is still intact, so I'd treat it as a short-term scalp, not a new long bias.

Trade plan: long on the reclaim at/above the swept level near 3757.209, stop below the sweep extreme below 3757.209, target back toward the H4 window high area near 4148.654. Invalidation: a body close back below the sweep extreme (below 3757.209) kills the reclaim and resumes the downtrend.

CALL: UP

### Setup 2 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-19T01:15 UTC

(no response)

### Setup 3 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-23T03:00 UTC

(no response)
