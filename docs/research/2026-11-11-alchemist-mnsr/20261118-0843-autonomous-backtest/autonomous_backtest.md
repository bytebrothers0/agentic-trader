# Alchemist MSNR autonomous backtest — 20261118-0843
- strategy: `alchemist_mnsr_v2` | date: 2026-11-18T08:43:45+00:00
- setups found autonomously: 10 (CRT sweep + close-back at PDH/PDL)
- metric: outcome agreement (directional call vs realized close-to-close move)

| # | type | cutoff (UTC) | level | call | realized | agree | ok |
|---|---|---|---|---|---|---|---|
| 1 | BULLISH CRT at PDL | 06-19T00:30 | 4186.72 | DOWN | DOWN | True | True |
| 2 | BULLISH CRT at PDL | 06-19T01:15 | 4186.72 | UP | DOWN | False | True |
| 3 | BULLISH CRT at PDL | 06-23T03:00 | 4139.90 | NO-ANSWER | DOWN | False | False |
| 4 | BULLISH CRT at PDL | 06-23T03:15 | 4139.90 | DOWN | DOWN | True | True |
| 5 | BULLISH CRT at PDL | 06-23T03:45 | 4139.90 | NO-ANSWER | DOWN | False | False |
| 6 | BULLISH CRT at PDL | 06-23T16:30 | 4139.90 | NO-ANSWER | DOWN | False | False |
| 7 | BULLISH CRT at PDL | 06-24T01:00 | 4080.83 | NO-ANSWER | DOWN | False | False |
| 8 | BULLISH CRT at PDL | 06-24T06:00 | 4080.83 | NO-ANSWER | DOWN | False | False |
| 9 | BULLISH CRT at PDL | 06-24T07:30 | 4080.83 | NO-ANSWER | DOWN | False | False |
| 10 | BULLISH CRT at PDL | 06-24T08:30 | 4080.83 | NO-ANSWER | DOWN | False | False |

**Agreement vs realized: 2/3 = 67% (target >=70%)**
| NO-TRADE calls: 0 | failed turns: 7 |

## Full answers
### Setup 1 — BULLISH CRT at PDL — call DOWN (realized DOWN) — cutoff 06-19T00:30 UTC

Storyline: H4 is trending down — lower highs and lower lows since early November, with price now sitting near the low end of that window. M15 is rotating lower intraday, aligned with the H4 downtrend rather than fighting it. The sweep that just printed at a key level and closed back inside is a failed breakout, not a real break — the close-back is the tell that the stops were purged and the level rejected price. We are in the London killzone (roughly 02:00–05:00 NY), the manipulation window where Asia’s range extreme gets swept before New York delivers the true direction. The POI is the swept level itself — in this downtrend that is the resistance/PDH area that failed to hold — and price is positioned to deliver lower toward the next downside pool. I would plan a short entry on a retest of that swept level or a rejection candle there, stop beyond the sweep extreme, target the next opposing fresh level below. Invalidation is a close back above the swept level, which kills the bearish setup and forces a re-scan.

CALL: DOWN

### Setup 2 — BULLISH CRT at PDL — call UP (realized DOWN) — cutoff 06-19T01:15 UTC

D1 is trending down from the August high into the lows — lower highs and lower lows are intact, so the HTF frame is bearish and we're sitting at a key decision zone. M15 has been trending down into the session low and just printed the sweep you described at a key level, so the lower timeframe is transitioning at that POI rather than cleanly trending. The sweep is a failed breakout, not a real break: price traded through the level on the wick and closed back inside, which is the tell that stops were purged and the breakdown failed; only a body close beyond would make it structure. We're in the London-to-NY handoff — Asia consolidated, London manipulated by sweeping one side, and NY should now deliver in the opposite direction, so if sell-side below the PDL/session low was swept and reclaimed, the delivery leg runs up toward buy-side. The POI is the reclaimed swept level itself, which just flipped to support and is fresh because it hasn't been retested since the sweep. For the next few hours I lean up: gold is more likely to bounce into the NY delivery toward the next opposing level above than to break down further, though this is a session-scale reclaim play within a D1 downtrend, not a trend change. I'd enter on the retest of the reclaimed level or the first minor bullish shift after the close-back, place the stop beyond the sweep extreme below the wick low, and target the next fresh level above only if the reward clears at least 2:1 after spread. A body close back below the sweep extreme or through the reclaimed level invalidates the long and flips the bias back down.

CALL: UP

### Setup 3 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-23T03:00 UTC

(no response)

### Setup 4 — BULLISH CRT at PDL — call DOWN (realized DOWN) — cutoff 06-23T03:15 UTC

D1 is trending down: price has broken from the August area near the 4697.107 window high and is making lower highs and lower lows into the 3757.209 window low, so the HTF storyline is bearish and intact. H1 confirms the same leg — a continuation decline into the lows — so the frames agree rather than conflict. The sweep that just printed at the key level with a close back inside is a failed breakout, a reclaim: a real break needs a body close beyond and acceptance, and we have the opposite. We're in the London manipulation window ahead of NY delivery, so the sweep is the fake move and NY should deliver in the true direction, which with the bearish HTF frame is down. The POI now is the swept key level retested as resistance; the first reaction after the purge is the short entry, the stop goes beyond the sweep extreme, and the target is the downside pool toward the next fresh support below the window low (3757.209). Invalidation is a body close back above the swept level — that flips it back to support and kills the bearish setup.

CALL: DOWN

### Setup 5 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-23T03:45 UTC



### Setup 6 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-23T16:30 UTC



### Setup 7 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-24T01:00 UTC



### Setup 8 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-24T06:00 UTC



### Setup 9 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-24T07:30 UTC



### Setup 10 — BULLISH CRT at PDL — call NO-ANSWER (realized DOWN) — cutoff 06-24T08:30 UTC


