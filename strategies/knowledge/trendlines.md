# Trendlines — sloped liquidity, not magic lines

## Definitions
- Two/three close-price swing extremes draw it; the third touch tests it. Quality = clean touches, even slope, time held. The steeper the line, the less it deserves respect — near-vertical lines break on noise.
- Trendline liquidity: stops cluster just beyond a long-held line — a touch is a POOL (see liquidity.md), like an equal high/low.
- Break = body close through. After a true break the line often flips (role flip): broken support-line becomes retest resistance. Channel = two parallels; the far edge is the target band.

## Reading it here
- The `trendline` detector prints sloped levels with role-flip/channel/sweep metadata. The line SLOPES — its current price is time-dependent; `level_lookup` returns the number, never your eyeball.

## Feeding bias and entries
- Touch + fresh pool + correct session = continuation entry. The line is not the trade — the reaction AT it plus confluence is.
- A break following a sweep of the touch-cluster, with displacement, is structure-grade: trade the retest of the flipped line.

## Common misreads
- Drawing through wick extremes instead of close-price pivots; trading the third touch blindly after a long decelerating slope (more likely the break); quoting "the level" without re-looking-up its current price.

## When the rule bends
- A violent displacement can close through and re-enter the line on the same bar — wait for the close and the next touch before calling the break real.
