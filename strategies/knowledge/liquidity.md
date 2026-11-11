# Liquidity — where the orders actually are

## Definitions
- Liquidity = clusters of resting stop orders and pending entries. Buy-side rests ABOVE highs (shorts' stops + breakout buys); sell-side rests BELOW lows (longs' stops + breakdown sells).
- Pools live at: equal highs/lows, previous-day high/low (PDH/PDL), session extremes (Asia range, London range), old swing extremes, obvious round numbers.
- Sweep / purge: price trades THROUGH a pool on a wick, then CLOSES BACK INSIDE. The close-back is the tell — a sweep is a failed breakout. A body close beyond is a real break — that is structure now (see market-structure.md).
- Draw on liquidity: the magnet — the nearest untouched pool price is being pulled toward. Name the current draw before you name a direction.
- Equal highs/lows are not support/resistance — they are engineered liquidity. Price is drawn to them; the real move usually starts AFTER they are taken, not before.

## The canonical sequence (AMD)
- Accumulation → Manipulation → Distribution. In a bullish day: price sweeps sell-side below the Asia/London low (the "Judas swing"), displaces up, then distributes toward buy-side. The day's true move is usually OPPOSITE the first sweep outside the range.

## Reading it here
- The `liquidity` detector prints equal-level pools with a side (buy-side above highs, sell-side below lows); `crt`/`ts` flag range-boundary sweeps with body-close-back-inside. `level_lookup` gives exact pool prices — never quote one from the image.
- Sweep = wick through + close back. Break = body close beyond → now structure, not liquidity.
- Before answering "where is price going", answer "which pool is nearest and untouched?" — that is the draw. A bias without a named draw is a guess.

## Feeding bias and entries
- Best longs: sell-side swept + close back above + displacement up + price in the discount half of the range (see premium-discount.md). Mirror for shorts.
- Stop beyond the sweep extreme — never just beyond the zone — a second probe of the same pool is normal.
- Fresh untouched pools ahead are targets; swept pools behind are fuel already burned.

## When the rule bends
- In a strong trend, price runs pool after pool in ONE direction — the "sweep then reverse" read inverts into continuation; follow the displacement, not the doctrine.
- Some pools get swept twice (second probe = true move). Immediate reclaim with displacement → sweep read wins; price sits beyond the level → break read wins. The close decides, not your hope.
