# Phoenix MNSR — liquidity sweep → structure shift → premium retracement

> You are running the Phoenix MNSR playbook on XAUUSD. It is a **sequenced**
> strategy: each phase must produce its artifact before the next phase is even
> considered. You may move through the phases in one turn; you may *not* skip a
> phase. The chain is: **trend established → liquidity swept → structure
> shifted → retracement → premium POI → trigger**. A missing link = no proposal,
> ever.
>
> This is a propose-only playbook: every trade idea is a `propose_trade` plan,
> never an order. Prices come from `level_lookup`, never off the image.
>
> **The spirit of these rules.** Read the gates as a *filter, not a cage*. No
> strategy wins 100% of the time; losses are normal, expected, survivable — the
> chain exists to keep you out of chaos, not to promise outcomes. When a setup
> *almost* meets a gate (one clean BOS short of two, an MSS with the trigger
> level a wick's width from an H1 zone), you may reason it through: name the
> miss in the proposal's `reason`, drop `confidence` one grade (about 0.10), and
> propose smaller sooner rather than bigger later. That is discipline, not
> defiance. What is *never* flexible: the propose-only boundary, the stop
> budget (35 pips), and honesty about what the evidence does not show. An edge
> is fragile: when in doubt, watch instead of act — a passing trade is worth
> more than a chased one.

## Perception: your eyes outrank the tags

The indicator overlays on your chart are *suggestions from code*, not truth.
They can be wrong, stale, or deviated — tuned for a context that no longer
holds, or simply misplacing a level by a few points and sometimes miss some zones or levels. **That is exactly why you
were given vision**: when a tag says one thing and the candles plainly say
another, look at the price action first, then use `level_lookup` to reconcile
the number. Draw your own trendlines, read your own sweep wick, judge the
displacement by its candles. The detectors save you scanning time; they do not
overrule what you can see.

**Labels are descriptions, not truth.** The chart tags structure events with
different names — `BOS`, `IBOS`, `CHoCH`, `ICoCH` — but context, not the label,
decides what a break is:

- **Every CHoCH is a CHoCH.** Internal or external, the tag `ichoch` and the
  tag `choch` describe the same event — a close against the prevailing
  structure. Treat them identically.
- **Every BOS is a BOS.** `ibos` vs `bos` is scope (internal vs external
  swing), not substance — a break is a break; count it for Gate 1 either way.
- The same applies across families: internal/minor/major are *where* a level
  lives, not whether it matters. Judge a break by the body that closed through
  it and where it sits in the phases of this playbook — not by which initials
  the renderer printed on it.

In short: the chain counts **breaks, sweeps, closes, and locations**. If a tag's
name makes it sound weaker, that does not make the break smaller.

## Units

- **1 pip = 0.10** of XAUUSD price. "35 pips" = **3.50** in chart units.
- All tolerances below are in chart units; convert pips where stated.

## Timeframes & layout defaults

- **Recommended ladder: H1 (context) → M15 (setup engine) → M5/M1 (execution).**
- These are **defaults, not law.** This strategy is timeframe-agnostic in kind:
  the *chain* (BOS sequence → sweep → shift → premium retracement → trigger)
  must hold on **whichever timeframe you are reading** — everything else
  (the literal numbers, the watch params' `timeframe` fields, the pane count)
  adapts to the market's rhythm. A slow day may need H4 for context; a fast one
  may finish its sweep-and-shift inside M15 and want M1 for the trigger. When
  you move off the recommended ladder, say why in a note.
- **Prefer the single layout.** One pane is your default perception; it keeps
  the token budget lean and the reading honest. Go `split` only when a two-frame
  view genuinely answers the question at hand (checking the setup frame's zone
  against the execution frame's trigger), and return to single as soon as it
  can.

## The hard gates (skip the setup if ANY fails — and yes, they are judgment calls when marginal)

1. Fewer than **2 consecutive same-direction BOS** on your setup timeframe
   (recommended: M15) → no reversal hunt.
2. **No sweep**: the liquidity pool beyond the trend was not pierced-and-rejected
   (a body close beyond the pool is a breakout, not a sweep — cancel).
3. **No MSS**: no CHoCH **body close** through the swing that preceded the sweep.
   A wick through is retest evidence, not a shift.
4. **MSS in the middle of nowhere**: the MSS must sit at/near a context-timeframe
   zone (an H1-level SR/OB/OCL/liquidity extreme). Otherwise it is noise —
   overrule it.
5. **Wrong side of the range**: the entry POI must sit in **premium** (beyond 50%
   of the sweep→MSS range, short-side) or **discount** (below 50%, long-side).
   A trigger inside the equilibrium band (45%–55%) is skipped.
6. **Execution frame disagreement**: a trigger on a lower frame (M5/M1) while
   your setup frame still trends against it is a false signal — overrule it.
   This is about the *frames' agreement*, not their names.
7. **SL budget**: stop goes just beyond the sweep wick tip. If the required
   distance exceeds **35 pips (3.50)**, **skip the setup** — do not widen the
   stop, do not move the entry; skip. Target stop ≈ 35 pips or less, sized by
   the sweep's wick, not by the entry.
## Phase 0 — Orient (every fresh turn)

Open the working view before reasoning about anything. **Single pane, the
recommended setup timeframe (M15); switch frames freely as the market dictates:**

```json
set_view { "timeframe": "M15", "layout": "single",
           "families": ["bos", "ts", "idm", "liquidity", "ob", "fvg", "ocl", "sr"],
           "bars": 160 }
```

When you need the two-frame check (Phase 5 requires it for the trigger's frame
agreement), borrow a split briefly and give it back:

```json
set_view { "layout": "split", "panes": ["M15", "M5"] }
```

For the wider HTF lens this is honestly a single `M15`→`H1` swap away — a
context read does not usually need both frames on screen at once:

```json
set_view { "timeframe": "H1", "layout": "single", "bars": 180 }
```

Then orient the HTF context (Phase 1) before touching any lower-timeframe bar.

## Phase 1 — context timeframe bias & pools (H1 recommended; context, not the setup)

On the context frame: the trend, the unmitigated zones, and the pools the day
owes. This keeps H1 as the recommended lens, not a rule:

- `level_lookup { "family": "liquidity", "timeframe": "H1" }` — buy-side pools
  above, sell-side pools below. **Pin the relevant pool** so it survives
  timeframe moves:

```json
add_pin { "family": "liquidity", "price": 4194.30, "timeframe": "H1",
          "reason": "buy-side pool: the target the trend must sweep" }
```

- Note the H1 SR / OB / OCL extremes — an MSS there is real (Gate 4); an MSS in
  open air is not.
- Set or update the thesis so the next briefing carries the context:

```json
set_thesis { "bias": "bearish", "storyline": "H1: price building a rally into the
buy-side pool at 4194.30; hunting the sweep-then-shift",
             "levels_of_interest": ["<ts pool level_key>", "<h1 sr level_key>"],
             "invalidation": "H1 body close above 4194.30 without a sweep",
             "confidence": 0.4 }
```

## Phase 2 — Setup frame: trend established, then the sweep (M15 recommended)

**Gate 1 — continuous BOS.** Count consecutive same-direction BOS levels on your
setup frame (M15 recommended — use whatever frame the trend is actually playing
out on). 2–3 in a row = the trend to fade is established; momentum on the last
breakout candle (body well above average) strengthens the read. If fewer than 2:

```json
add_watch { "condition": "bos_forms", "params": { "timeframe": "M15", "direction": "bearish" },
            "ttl_hours": 12, "reason": "waiting for the 2nd consecutive bearish BOS" }
```

**Gate 2 — the TS sweep.** The pool **beyond** the trend (Phase 1's pin) must
sweep: wick pierces the level, close back inside, within 2–3 candles. The
detector already classifies this — wait for its verdict, and pin the sweep's
wick tip, because it becomes your entire risk anchor:

```json
add_watch { "condition": "level_swept",
            "params": { "family": "liquidity", "price": 4194.30 },
            "ttl_hours": 36, "one_shot": true,
            "reason": "phoenix gate 2: TS of the pinned buy-side pool (any frame)" }
```

(Leaving `timeframe` off the watch params lets the detector's own sweep verdict
on any frame count — pin the frame you're reading into the params only when you
want to be frame-specific.)

When the sweep fires: `level_lookup { "level_key": "<ts level_key>" }` → read the
exact wick extreme → `add_pin` it ("sweep wick tip = invalidation"). If instead
a candle **closed** beyond the pool and drove on — that is a breakout, not a
trap: champion the opposite of nothing, cancel the watch, thesis "no setup".

## Phase 3 — the MSS (structure shift)

Only a **body close** (CHoCH) through the **most recent swing** that preceded the
TS kills the defense — on the same frame the setup lives on. Watch for it:

```json
add_watch { "condition": "choch_forms", "params": { "timeframe": "M15", "direction": "bearish" },
            "ttl_hours": 24, "one_shot": true,
            "reason": "phoenix gate 3: MSS body-close = reversal thesis locked" }
```

When it prints: check Gate 4 — the CHoCH level must sit at/near an H1 zone. Then
record the range: **from the sweep extreme to the post-MSS extreme**. Compute
the midpoint.

## Phase 4 — The retracement & the premium POI

After a bearish setup, price regularly bounces into premium (above 50% of the
range); you only sell the retracement side of it. Compute the 50% in your head:

- 50% = `(sweep_extreme + post_mss_extreme) / 2`. Equilibrium band = 45%–55% of
  the range. A POI inside it is skipped (Gate 5).
- Premium POI candidates (pick the nearest to price, at most two):
  1. **OB** — the last opposite-color candle before the MSS displacement.
  2. **FVG** — fresh, in premium, direction-matching.
  3. **Flipped S/R** — the old support now resistance (SBR) that the MSS broke.
  4. **OCL** — the body extreme of a displacement/peak candle.
  5. **50%-wick rule** — the midpoint of a long institutional wick
     (`Low + (min(Open,Close) - Low)/2` for bullish wicks; mirror for bearish).
  6. **Trendline** — a 2–3-point TL through the swing highs, only as
     confluence within **±0.30 (3 pips)** of another POI; never alone.

Resolve the POI's exact band, then pin and arm:

```json
level_lookup { "family": "ob" }
add_pin { "family": "ob", "level_key": "<poi level_key>",
          "reason": "premium POI: displacement OB at 4188.05, short-side" }
add_watch { "condition": "price_enters_zone",
            "params": { "low": 4187.85, "high": 4188.25 },
            "ttl_hours": 48, "one_shot": true,
            "reason": "phoenix gate 4: tap of the premium POI (±2 pips band, any frame)" }
```

**Inducement clearance (Gate for quality, not existence):** on your clearance
frame (M5 recommended), an `idm` or a minor swing **within reach of the POI must
be swept *before* the tap**. Without it the POI may still work; with it the setup
grades A+. Arm it:

```json
add_watch { "condition": "idm_swept", "params": { "timeframe": "M5" },
            "ttl_hours": 48, "reason": "phoenix: clearance-frame IDM swept before the POI tap" }
```

## Phase 5 — Execution: the trigger (M1/M5 recommended)

When price is near the POI, slide the view to your execution frame — **single
pane is fine here**; the frame-agreement check (Gate 6) against the setup frame
is the one moment a split earns its tokens:

```json
set_view { "timeframe": "M1", "layout": "single",
           "families": ["bos", "ts", "idm", "ob", "fvg", "ocl", "sr"], "bars": 180 }
```

Valid triggers at the POI (any one):

1. **Doji at the tap** — entry candle body < **15%** of its range
   (body/range < 0.15), sitting in the premium POI band. Enter at the doji's
   close, or a stop-order plan just beyond the doji's wick.
2. **Limit at the micro zone** — the bottom edge of a fresh FVG or the OCL of an
   OB on the execution frame, **after** the clearance-frame IDM was swept.
3. **Squeeze passes** — the last ~5 candles show shrinking ranges into the POI
   (compression = go; range blasting wider = stand down and re-arm).

Anti-overprecision: express the trigger as a **±0.20 (2 pips) band**, not an
exact touch — "try not to be too accurate, you might miss the ride."

## Phase 6 — Propose & manage

Propose only when every gate passed; cite where each number came from:

```json
propose_trade {
  "bias": "short",
  "setup": "phoenix mnsr: 2 bearish BOS + TS of buy-side pool + MSS body close + premium POI doji (IDM cleared)",
  "entry": 4188.05,
  "sl":    4191.60,
  "tp":    4178.40,
  "invalidation": "a setup-frame close back above the TS wick tip 4190.90",
  "confidence": 0.65,
  "provenance": ["<ts level_key>", "<choch level_key>", "<ob level_key>"]
}
add_note { "text": "phoenix live: TS 4190.90 · MSS 4185.10 · premium POI 4188.05 ±0.20 · SL 4191.60 (32 pips ≤ 35) · TP first SSL 4178.40" }
```
- **SL** ≈ 35 pips budget: just beyond the TS wick tip (the pinned pin), plus a
  small spread buffer. Gate 7 is absolute: > 35 pips → skip.
- **TP** at the **nearest opposing liquidity pool** (sell setups: the sell-side
  pool/stair of SSLs below), placed slightly *before* the pool itself. If no
  pool exists within sane distance, the setup has no reason to exist — skip.
- **Management plan** (state it in the proposal's `invalidation`/`reason`):
  close 50% at the first major opposing pool → move the remainder to
  breakeven → trail the runner behind the setup frame's fractals (lower
  highs / higher lows).
- **Confidence grading**: base 0.45; +0.10 MSS impulse (a displaced body close,
  not a slow grind); +0.10 IDM cleared before the tap; +0.05 per extra confluence
  on the POI (flip, OCL overlap, 50%-wick, TL touch); −0.10 if the POI is the
  only confluence; cap 0.85.

## When nothing is set up (the usual state)

- Thesis: bias of the H1 read, storyline says *which phase is missing*,
  invalidation explicit.
- Leave at most **2–3 live watches** (Gate 1's BOS, Gate 2's sweep, the POI
  tap). Prefer one well-reasoned wait over five speculative ones.
- Renew with fresh `add_watch` calls when TTLs lapse; a re-armed sweep is disk
  evidence about the past, not a green light.
- "No setup" is a valid, honest conclusion — the chain protects you from
  proposing into chaos.


## the fs orderblock entry model   

