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

## Units

- **1 pip = 0.10** of XAUUSD price. "35 pips" = **3.50** in chart units.
- All tolerances below are in chart units; convert pips where stated.

## The hard gates (skip the setup if ANY fails)

1. Fewer than **2 consecutive same-direction BOS** on M15 → no reversal hunt.
2. **No sweep**: the liquidity pool beyond the trend was not pierced-and-rejected
   (a body close beyond the pool is a breakout, not a sweep — cancel).
3. **No MSS**: no M15 CHoCH **body close** through the swing that preceded the
   sweep. A wick through is retest evidence, not a shift.
4. **MSS in the middle of nowhere**: the MSS must sit at/near an H1-level zone
   (an H1 SR/OB/OCL/liquidity extreme). Otherwise it is noise — overrule it.
5. **Wrong side of the range**: the entry POI must sit in **premium** (beyond 50%
   of the sweep→MSS range, short-side) or **discount** (below 50%, long-side).
   A trigger inside the equilibrium band (45%–55%) is skipped.
6. **M1/M5 without M15**: an M1/M5 trigger while M15 still trends against it is a
   false signal — overrule it, always.
7. **SL budget**: stop goes just beyond the sweep wick tip. If the required
   distance exceeds **35 pips (3.50)**, **skip the setup** — do not widen the
   stop, do not move the entry; skip. Target stop ≈ 35 pips or less, sized by
   the sweep's wick, not by the entry.

## Phase 0 — Orient (every fresh turn)

Open the working cockpit before reasoning about anything:

```json
set_view { "timeframe": "M15", "layout": "split", "panes": ["M15", "M5"],
           "families": ["bos", "ts", "idm", "liquidity", "ob", "fvg", "ocl", "sr"],
           "bars": 160 }
```

M15 is your setup engine (top pane); M5 is clearance/execution (bottom pane). If
the story needs a wider lens, look at H1 with an offset window before judging:

```json
set_view { "layout": "split", "panes": ["H1", "M15"], "bars": 180 }
```

Then orient the HTF context (Phase 1) before touching any M-numbered bar.

## Phase 1 — H1 bias & pools (context, not the setup)

On H1: the trend, the unmitigated zones, and the pools the day owes:

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

## Phase 2 — M15: trend established, then the sweep

**Gate 1 — continuous BOS.** Count consecutive same-direction BOS levels on the
M15 pane. 2–3 in a row = the trend to fade is established; momentum on the last
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
            "params": { "family": "liquidity", "price": 4194.30, "timeframe": "M15" },
            "ttl_hours": 36, "one_shot": true,
            "reason": "phoenix gate 2: TS of the pinned buy-side pool" }
```

When the sweep fires: `level_lookup { "level_key": "<ts level_key>" }` → read the
exact wick extreme → `add_pin` it ("sweep wick tip = invalidation"). If instead
a candle **closed** beyond the pool and drove on — that is a breakout, not a
trap: champion the opposite of nothing, cancel the watch, thesis "no setup".

## Phase 3 — M15: the MSS (structure shift)

Only a **body close** (CHoCH) through the **most recent swing** that preceded the
TS kills the defense. Watch for it:

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
level_lookup { "family": "ob", "timeframe": "M15" }
add_pin { "family": "ob", "level_key": "<poi level_key>",
          "reason": "premium POI: displacement OB at 4188.05, short-side" }
add_watch { "condition": "price_enters_zone",
            "params": { "low": 4187.85, "high": 4188.25 },
            "ttl_hours": 48, "one_shot": true,
            "reason": "phoenix gate 4: tap of the premium POI (±2 pips band)" }
```

**Inducement clearance (Gate for quality, not existence):** on the M5 pane, an
`idm` or a minor swing **within reach of the POI must be swept *before* the tap**.
Without it the POI may still work; with it the setup grades A+. Arm it:

```json
add_watch { "condition": "idm_swept", "params": { "timeframe": "M5" },
            "ttl_hours": 48, "reason": "phoenix: M5 IDM cleared before the POI tap" }
```

## Phase 5 — Execution: M1/M5 trigger

Slide the cockpit to execution when price is near the POI:

```json
set_view { "layout": "split", "panes": ["M5", "M1"],
           "families": ["bos", "ts", "idm", "ob", "fvg", "ocl", "sr"], "bars": 180 }
```

Valid triggers at the POI (any one):

1. **Doji at the tap** — entry candle body < **15%** of its range
   (body/range < 0.15), sitting in the premium POI band. Enter at the doji's
   close, or a stop-order plan just beyond the doji's wick.
2. **Limit at the micro zone** — the bottom edge of a fresh M1 FVG or the OCL of
   an M1 OB **after** the M5 IDM cleared.
3. **Squeeze passes** — the last ~5 M1 candles show shrinking ranges into the
   POI (compression = go; range blasting wider = stand down and re-arm).

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
  "invalidation": "M15 close back above the TS wick tip 4190.90",
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
  breakeven → trail the runner behind M15 fractal (lower highs / higher lows).
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
