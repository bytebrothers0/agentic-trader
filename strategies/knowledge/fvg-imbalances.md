# Fair Value Gaps & Imbalances — unfinished business in price

## Definitions
- FVG: a three-candle imbalance. Bullish: gap between candle 1's high and candle 3's low (price moved up too fast to trade every level). Bearish: mirror — candle 1's low to candle 3's high.
- A gap means one side had no chance to transact there. Price often returns to rebalance — the FVG acts as a continuation zone in the gap's direction.
- Consequent encroachment (CE): the FVG's 50% midpoint. A tag at the boundary or a pierce to CE with a close beyond it = the gap is respected.
- Life cycle: fresh (unmitigated) → partially mitigated (tapped, still reactive) → fully filled (dead as a zone). Reliability declines in that order.
- IFVG (inversion): price CLOSES through the gap and the zone flips role — a broken bullish FVG becomes resistance; a broken bearish FVG becomes support. An FVG is a continuation tool; an IFVG is a shift/reversal tool.

## Reading it here
- The `fvg` detector prints bullish/bearish gaps; `ifvg` prints inverted ones (recent FVG closed through by full body + confirmed by an overlapping opposite FVG). `level_lookup` gives exact zone edges.
- Fresh + HTF + aligned with displacement > old + LTF + isolated. An IFVG is strongest when it overlaps a fresh opposite FVG — a doubled zone.

## Feeding bias and entries
- In an established move: the retracement into a fresh FVG (ideally inside OTE, see premium-discount.md) is the entry zone; the gap's far edge or CE is the trigger.
- An IFVG right after a liquidity sweep + displacement is one of the sharpest reversal signals in this framework: sweep (liquidity) → close-through inversion (imbalance) → retrace entry, stop beyond the zone's far side, target the opposing pool.
- An FVG against the HTF draw is a trap, not an entry: skip it or use it as a target.

## Common misreads
- Trading every gap — the gap matters when CREATED by displacement out of a sweep or a structural break; gaps inside consolidation are noise.
- Treating a fully filled gap as active. It is spent; find the next one.
- Entering a gap with no structure context — a gap alone is not a setup.

## When the rule bends
- On the highest timeframe a huge gap can take days to fill — do not force intraday trades against an unfilled HTF gap in the trend's direction; it is the draw, and draws win.
- Two stacked same-direction gaps: the SECOND is usually weaker — the first held the move; the second is exhaustion risk.
