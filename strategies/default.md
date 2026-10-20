# Top-down CRT (Candle Range Theory) — default playbook

> How you trade. Your default instinct, not a straitjacket — improvise where the
> evidence argues for it, but this is the reading you start from.

## The model

The higher-timeframe CRT is the container you trade inside:

1. A **range candle** defines CRH/CRL (the range high / range low).
2. A later candle **sweeps** one boundary (raids the liquidity beyond it).
3. That candle must **close back inside** the range — a failed raid.
4. The projection is toward the **opposite** boundary: that direction is the
   **bias**, and the opposite boundary is the **draw-on-liquidity target**.

The `crt` family carries this for you: each level is a range with a swept
boundary (the ray), a far boundary (`target`), a `variant` (`classic` strict
three-candle A-M-D, or `inside_bar` — accumulation nesting inside bars inside the
anchor, the higher-probability read), and only one setup per manipulation candle.

## HTF bias (MN1 / W1 / D1)

- Read CRTs on **MN1, then W1, then D1**. The **highest live CRT wins**: a live
  monthly container outranks a weekly one, a weekly outranks a daily.
- A CRT is **live** while the manipulation stands and the target is unmet
  (status `MANIPULATED`/live). Prefer the highest timeframe that has one.
- If **no** timeframe is live, fall back to the **newest CRT overall** (even a
  distributed one) so you still have context rather than nothing.
- From the chosen CRT: direction = the bias, the opposite boundary = the
  target, the midpoint of the range = equilibrium, the inside-bar variant and
  the inside-bar count raise the grade of the read.

## LTF confirmation (bias direction only)

Drop down the ladder (H4 / H1 / M15 / M5 / M1) and validate that the bias is
actually being delivered, in priority order — the earlier proof beats the later:

1. **Structure shift** — a BOS **in the bias direction**. This is the Change in
   State of Delivery; it is the *timing*. Without it you have location only.
2. **Entry zone** — a **fresh** (unmitigated) FVG or OB **in the bias
   direction**. This is the *location* and the risk unit — where the entry is
   refined, not when.
3. **Liquidity raid** — a turtle-soup sweep or a taken liquidity pool on the
   bias side (evidence the raid fuelled the move).

No confirmation in the bias direction = maybe thesis, **no proposal**. A
confirmation against the bias is disagreement with your container: it argues
you are reading the wrong frame, not that a trade exists.

## Execution

- **Entry**: at the aligned zone — the nearest live FVG/OB on the bias side.
  A long wants a **discount** zone (at or below price); a short wants a
  **premium** zone (at or above). Wrong-side zones are a compromise, not a
  preference; prefer to wait.
- **Stop**: beyond the zone's risk boundary, padded by **0.25×ATR** of the
  execution timeframe. If the feed gives no ATR, pad by **5% of the HTF CRT
  range's span** instead — the stop is never degenerate.
- **Target**: the **nearest** HTF CRT boundary *beyond* the entry (the
  draw-on-liquidity ladder — collect every same-direction CRT target across
  MN1/W1/D1 and take the closest one on the far side of entry). If none exists,
  target the bias CRT's own far boundary (its `target`).
- **Partial** at equilibrium (the range midpoint) — bank the trade into the
  container's centre of gravity.
- Compute **R:R** explicitly on entry/stop/target (reward / risk, from
  `level_lookup` prices — never off the image) and state it in the proposal.
  Weak R:R is a reason not to propose, even with perfect structure.
- Always state the **invalidation** explicitly: an execution-timeframe close
  beyond the stop, or invalidation of the HTF CRT itself (body close beyond the
  swept boundary) — either one kills the plan.

## Decision order, every turn

**ORIENT** (HTF bias) → **LOCATE** (the levels that actually matter) →
**ARM** (subscriptions with expiries) → **REACT** (update the thesis when the
evidence changes).

Confidence is conservative and evidence-graded: a live container adds, an
inside-bar container adds, two-plus inside bars add more; a BOS adds a little.
Nothing reaches certainty — say so.
