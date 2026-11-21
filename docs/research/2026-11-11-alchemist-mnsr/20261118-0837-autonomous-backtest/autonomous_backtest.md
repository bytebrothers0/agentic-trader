# Alchemist MSNR autonomous backtest — 20261118-0837
- strategy: `alchemist_mnsr_v2` | date: 2026-11-18T08:37:07+00:00
- setups found autonomously: 3 (CRT sweep + close-back at PDH/PDL)
- metric: outcome agreement (directional call vs realized close-to-close move)

| # | type | cutoff (UTC) | level | call | realized | agree | ok |
|---|---|---|---|---|---|---|---|
| 1 | BULLISH CRT at PDL | 06-19T00:30 | 4186.72 | NO-TRADE | DOWN | False | True |
| 2 | BULLISH CRT at PDL | 06-19T01:15 | 4186.72 | NO-ANSWER | DOWN | False | False |
| 3 | BULLISH CRT at PDL | 06-23T03:00 | 4139.90 | UP | DOWN | False | True |

**Agreement vs realized: 0/1 = 0% (target >=70%)**
| NO-TRADE calls: 1 | failed turns: 1 |

## Full answers
### Setup 1 — BULLISH CRT at PDL — call NO-TRADE (realized DOWN) — cutoff 06-19T00:30 UTC

H1 storyline: bearish trend — price has broken down from the 4067 area to the 3757 area with lower highs and lower lows intact; external structure is down. M15 storyline: corrective pullback at the bottom of that H1 move, with price rotating near the window low around 3757–3780 after a sweep.

The sweep printed at a key level and price closed back inside, so it is a failed breakout (reclaim), not a real breakdown. The close-back is the tell — the wick took the stops, the body reclaimed the level.

Session: it is 08:37 NY, inside the NY AM killzone (07:00–10:00), the core reference window where London’s manipulation is supposed to give way to the day’s true delivery direction.

POI: the reclaimed swept level itself. If sell-side (PDL/session low) was taken and reclaimed, that level is now the immediate area of interest; a hold above it invites a retracement, a close back below it resumes the drop.

Directional read: the H1 frame is bearish and carries authority. The M15 reclaim is a counter-trend signal inside a downtrend, and per the Alchemist MSNR validity rule I do not trade lower-timeframe breakouts against the higher frame. I also have no confirmed exact level prices — level_lookup returned no matches for the POI neighbourhood — so I cannot state an entry, stop, or target with a number I am allowed to quote.

Because the frames disagree and there is no confirmed level to build a plan around, there is no setup.

CALL: NO-TRADE

### Setup 2 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-19T01:15 UTC

(no response)

### Setup 3 — BULLISH CRT at PDL — call UP (realized DOWN) — cutoff 06-23T03:00 UTC

Storyline: H1 is trending down — price has fallen from the 4067 area toward the 3757 lows, with lower highs and lower lows intact. M15 is extending that decline and is now rotating at the bottom of the move near the 3757 area.

The sweep at the key level with price closing back inside is a failed breakout — a reclaim, not a real break. The wick took the stops below the level, the close-back shows the downside move failed, and the level is now acting as support rather than breaking.

We are in the London killzone (02:00–05:00 NY), the manipulation window. Asia consolidated the overnight range; London just swept one side and failed. The NY delivery window (07:00–10:00 NY) is ahead, which typically runs in the opposite direction of the London purge.

The POI is the swept level near the 3757 lows — fresh, untested since the move away, and now the boundary between the failed breakdown and the next leg.

Direction: UP. Gold is more likely to move up over the next few hours as the failed sell-side sweep sets up a reversal into the NY delivery.

Trade: Entry on the reclaim/retest of the swept level near 3757.209. Stop below the sweep extreme, beneath 3757.209. Target toward the prior M15 structure around 3891.043 or higher. Invalidation: a body close back below the sweep extreme at 3757.209 kills the setup.

CALL: UP
