# Alchemist MSNR replay — baseline-night
- strategy: `alchemist_mnsr_v2` | date: 2026-11-11T14:15:57+00:00
- metric: outcome agreement (directional call vs realized move; a win is a win)
- status_filter arm: default (all)

| window | cutoff (UTC) | realized | call | agree |
|---|---|---|---|---|
| day-2-london | 11-09 07:00 | UP (4102.47->4126.94) | NO-ANSWER | False |
| day-2-nyam | 11-09 13:30 | UP (4119.54->4142.27) | NO-ANSWER | False |
| day-5-london | 11-06 07:00 | UP (4045.71->4063.60) | DOWN | False |
| day-5-nyam | 11-06 13:30 | UP (4047.96->4064.27) | NO-ANSWER | False |
| day-6-london | 11-05 07:00 | DOWN (4123.95->4096.75) | UNPARSED | False |
| day-6-nyam | 11-05 13:30 | DOWN (4121.61->4107.29) | NO-ANSWER | False |

**Agreement: 0/1 = 0%** (target >= 70%) | no-trade calls: 0 | failed turns: 4

## Full answers
### day-2-london — call: NO-ANSWER (realized UP)

(no response)

### day-2-nyam — call: NO-ANSWER (realized UP)

(no response)

### day-5-london — call: DOWN (realized UP)

H4 is bearish — price has broken down from the October area near 4472 and is now around 4055, making lower highs and lower lows on the external structure. The M15 agrees, with price at 4045 sitting below the live bearish FVG at 4054.53–4056.36. The POI that matters now is the H4 live bearish FVG at 4057.53–4071.03, which becomes resistance on any retracement. We're in the NY AM delivery window, so the true daily direction should play out now — with the bearish H4 frame, that's downside toward the untested bullish FVG at 3964.89–4021.08 and the breaker OB at 4016.53–4037.75. A body close back above 4071.03 invalidates the bearish setup by filling the FVG.

Plan: short on a retracement into 4057.53–4071.03 with a rejection/close-back trigger, stop above 4071.03, first target 4021.08, extended target 3964.89.

CALL: DOWN

### day-5-nyam — call: NO-ANSWER (realized UP)

(no response)

### day-6-london — call: UNPARSED (realized DOWN)

H4 is bearish: price broke down from the October peak near 4472 and is making lower highs and lower lows, now in a corrective bounce around 4124 after the early-November lows near 3900–3964. M15 agrees directionally at 4118 but is corrective and rotating with no confirmed sweep-and-close-back yet, so the lower timeframe leans with the higher frame but carries no trigger. The session is roughly

### day-6-nyam — call: NO-ANSWER (realized DOWN)

(no response)
