# Trendline Liquidity — Channels, Role Flips, Sweeps

Date: 2026-10-17
Status: Approved
Module: `indicators/trendline_detector.py` (+ `server.py`, `web/app.js`)

## Concept

A trendline is engineered liquidity: stops/pending orders rest on and just
beyond it. MSNR (`strategy_notes/phoenix_mnsr/MSNR_Part6` §4) seeks the
"double trap" where a Target Sweep happens at an established retail trendline.
A line reads as **support** (price above) or **resistance** (price below); when
broken and retested its role flips.

## Changes

### 1. Any-slope + SUPPORT/RESISTANCE classification
- Resistance lines: consecutive close **peak** apexes, any slope.
- Support lines: consecutive close **valley** apexes, any slope.
- Removed the monotonic direction gate (it rejected same-slope channel
  boundaries). The "price stays on the correct side between anchors" check
  stays. `TLLine.role` -> "resistance" | "support".

### 2. Channel = two boundary lines (no mid-line)
- `TLChannel` / mid-line removed.
- `_tag_channels` pairs an active resistance + active support line that
  overlap, whose slopes match within `TL_CHANNEL_PARALLEL_ATR` (normalised by
  ATR), and whose resistance sits above support across the overlap; both get a
  shared `channel_id`.
- Channel members are prioritised when capping `max_lines` per side.

### 3. Break-and-retest role flip
- After a break + far-side retest, `flipped = True`; role flips
  (broken resistance acts as support and vice-versa). Surfaced as `TL_BRT`.

### 4. Trendline-liquidity sweep
- A sweep = a bar whose wick pokes `> TL_SWEEP_ATR * ATR` past the line while
  its body holds on the original side. Tracked via `swept`, `sweep_bars`,
  exposed as `liquidity` on the payload.

## Config
`TL_TOL_ATR` (exists) + `TL_CHANNEL_PARALLEL_ATR = 0.2` + `TL_SWEEP_ATR = 0.5`.

## Server / frontend
- Payload: `type` = `TL_SUPPORT` / `TL_RESISTANCE` (or `..._BRT`), plus
  `role`, `flipped`, `channel`, `liquidity`, `sweeps`. Mid-line entry removed.
- `web/app.js` colours by `role`, labels `BRT`, tags channel members.

## Tests
`test_trendline.py`: same-direction channel boundaries, channel pairing,
break-retest flip, sweep flag, any-slope classification (support descending,
resistance ascending). X-Factor interface preserved.
