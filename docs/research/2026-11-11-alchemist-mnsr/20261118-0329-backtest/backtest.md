# Alchemist MSNR backtest — 20261118-0329
- strategy: `alchemist_mnsr_v2` | date: 2026-11-18T03:29:53+00:00
- metric: outcome agreement (directional call vs realized move)
- setups: 8 manually-selected dated setups from past price action

| id | setup | cutoff (UTC) | session | expected | call | realized | agree | vs expected |
|---|---|---|---|---|---|---|---|---|
| S1 | BEARISH reclaim at PDH | 09-17 13:45 | NY AM | DOWN | UNPARSED | DOWN (4366.62->4359.81) | False | None |
| S2 | BEARISH reclaim at PDH | 09-30 13:30 | NY AM | DOWN | NO-ANSWER | DOWN (4183.61->4160.07) | False | None |
| S3 | BEARISH reclaim at PDH | 10-02 13:30 | NY AM | DOWN | NO-ANSWER | DOWN (4186.08->4135.10) | False | None |
| S4 | BEARISH reclaim at PDH | 10-16 09:45 | London | DOWN | DOWN | DOWN (4176.96->4167.48) | True | True |
| S5 | BULLISH reclaim at PDL | 10-07 15:30 | NY AM | UP | NO-ANSWER | UP (4108.28->4110.01) | False | None |
| S6 | BULLISH reclaim at PDL | 10-26 13:45 | NY AM | UP | NO-ANSWER | UP (3992.88->4019.65) | False | None |
| S7 | BULLISH reclaim at PDL | 11-10 13:30 | NY AM | UP | NO-ANSWER | DOWN (4056.30->4021.34) | False | None |
| S8 | BULLISH reclaim at PDL | 11-11 14:30 | NY AM | UP | DOWN | DOWN (4016.17->4000.16) | True | False |

**Agreement vs realized: 2/2 = 100% (target >=70%)**
**Correct vs my expected: 1/2 = 50%**
| NO-TRADE calls: 0 | failed turns: 5 |

## Full answers
### S1 BEARISH reclaim at PDH — call UNPARSED (realized DOWN)

D1 storyline: bearish/downtrend — price peaked near the top of the window in mid‑August and has made lower highs and lower lows since, now testing the lows around 3785.361. H4 storyline: bearish breakdown — from the early‑November high of 4148.654, price displaced down with large bearish candles into the same low area, with no confirmed reversal close. Both frames agree, so there is no HTF/LTF conflict.

The POI that matters now is the recent low zone around 3785.361–3800 where D1 and H4 converge — a fresh support/V candidate. But price is already down at the lows (deep discount), so shorting here is chasing with poor location; the better entry is a retracement into the premium/OTE of the H4 leg (between the 3785.361 low and the 4148.654 high), ideally stacking on a fresh bearish FVG or order block, or a close‑back below 3785.361 for continuation.

Session: it is roughly 03:29 UTC (≈22:30 NY), inside the Asia consolidation window (20:00–00:00 NY); London opens near 07:00 UTC. Asia consolidates and builds the overnight range, London manipulates/sweeps, and NY delivers — we are in the choppy pre‑London window, not the delivery window.

My call: D1 and H4 are aligned bearish, so this 

### S2 BEARISH reclaim at PDH — call NO-ANSWER (realized DOWN)

(no response)

### S3 BEARISH reclaim at PDH — call NO-ANSWER (realized DOWN)

(no response)

### S4 BEARISH reclaim at PDH — call DOWN (realized DOWN)

D1 storyline: BEAR — XAUUSD peaked near 4697.107 in August and has since carved lower structure down into the 3785.361 area; external structure is down and that low is the current floor. M15 storyline: BEAR — the Nov 16–18 session rallied to 3891.043, then sold off into that same 3785.361 floor, so the lower timeframe is trading in the direction of the higher timeframe, not against it.

POIs that matter now: support at 3785.361 (the fresh D1/M15 window low — untested as a hold, so it still carries weight) and resistance at 3891.043 (the M15 session high, the level a reclaim would have to close back above to negate the decline). No other levels were drawn on this view, so I'm treating these two as the bounded decision area.

Session: it is 03:33 UTC on 18 Nov, roughly 22:33 New York time — inside the Asia consolidation window. Asia builds the range and its pools; London manipulates one extreme; NY delivers. We are in the quiet leg, so a clean breakout in either direction is more likely after London opens rather than right now.

My read: the bias is bearish, but price is already sitting at the 3785.361 floor with 3891.043 as the ceiling, so an Asia-session short here offers poor risk

### S5 BULLISH reclaim at PDL — call NO-ANSWER (realized UP)

(no response)

### S6 BULLISH reclaim at PDL — call NO-ANSWER (realized UP)

(no response)

### S7 BULLISH reclaim at PDL — call NO-ANSWER (realized DOWN)

(no response)

### S8 BULLISH reclaim at PDL — call DOWN (realized DOWN)

H4 storyline: bearish trend — price broke down from the early-Nov high near 4148.654 and is making lower highs and lower lows into the low end of the window around 3785.361. M15 storyline: bearish, trending down — over Nov 16–18 price collapsed from the 3891.043 area toward 3785.361, an impulsive breakdown with no close-back reclaim. Both frames agree, so there's no HTF/LTF conflict; the bias is down. Session: it's late Asia (03:38 UTC), the consolidation window, so I'd expect chop rather than a clean trend until London/NY delivery begins — but the structural draw is to the downside. The POI that matters is the downside area near 3785.361 (fresh, untested on this leg); the upside resistance to watch is the M15 high near 3891.043, now prior support turned resistance. Plan: I'd only short on a M15 retracement back into that supply zone near 3891.043 with a reaction, stop above the recent swing high (above 3891.043), target down toward 3785.361 and below. Invalidation: an M15/H4 close back above the breakdown level (reclaim of ~3891.043) kills the short and flips the bias. CALL: DOWN
