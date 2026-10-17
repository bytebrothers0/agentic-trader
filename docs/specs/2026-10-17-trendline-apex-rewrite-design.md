# Trendline Detector Rewrite — Point-to-Point Close Apexes

Date: 2026-10-17
Status: Approved
Module: `indicators/trendline_detector.py`

## Problem

The detector never connected points. It picked a single fractal pivot and
**forced** the slope to `ATR / pivot_length * slope_mult`, then projected that
fixed slope forward. A "trendline" therefore was not a line through the
reaction points — the 2nd/3rd touches were incidental.

MSNR defines a trendline as a straight line through **2-3 apex points on the
line chart (closes)** (`strategy_notes/phoenix_mnsr/MSNR_Part6`,
`strategy_notes/abax mnsr/part06_trendlines_confluence_direction.md` §7).

## Design

A trendline is built point-to-point through close-price apexes:

1. **Apexes** = strict fractals on **close** only.
   - peaks (A-tops) → resistance candidates
   - valleys (V-bottoms) → support candidates
2. **Anchors**: consecutive apex pairs.
   - UPPER/resistance: descending pair `close[p2] < close[p1]`.
   - LOWER/support: ascending pair `close[p2] > close[p1]`.
   - `slope = (close[p2] - close[p1]) / (p2 - p1)` — the real slope.
3. **Run extension**: extend the pair while the next apex is collinear
   (within `tol`) and monotonic → a 2- or 3-apex line. One line per run.
4. **Between-anchor invalidation**: a close beyond the line by more than
   `tol` between the anchors voids the candidate.
5. **Touches**: the 2nd anchor is the first respected touch (`touch_bars[0]`).
   Later bars whose wick reaches the line while the body holds on the near
   side (within `tol`) count as touches. `touches = len(touch_bars)`.
6. **tolerance** = `tol_atr * ATR(14)`, default `tol_atr = 0.25` (config
   `TL_TOL_ATR`).
7. **Break / retest** unchanged: body close through = BROKEN; far-side wick
   touch without closing back across = retest.
8. Keep the most recent `max_lines` per side (by second-anchor recency).
9. Channel = mid-line of the latest active upper/lower pair.

## Compatibility

All existing public fields keep their meaning. `slope` becomes **signed**
(negative for falling upper, positive for rising lower) and `value_at()`
projects it directly. New optional fields: `apex_points`, `second_anchor_index`.
`anchor_kind` is now `"close"`. `XDetector`, `AlchemistEngine`, `server.py`
and `web/app.js` are unaffected.

Deprecated no-op kwargs kept for callers: `slope_mult`, `body_pivots`.

## Lifecycle / edge cases

- `< 2` apexes on a side → no lines.
- Zero ATR → tolerance floor prevents crash.
- Gap apexes skipped (`skip_gap_anchors`); `require_engulfing` filters
  non-engulfing anchors.
- Duplicate (side, p1, second-anchor) lines are suppressed.
- Runs advance `i = last_apex_of_run`, so overlapping pairs are not re-emitted.

## Tests

Rewrite `tests/test_indicators/test_trendline.py`:
- 2 descending close highs → upper line through both.
- 2 ascending close lows → lower line through both.
- 3 collinear apexes → one line, `apex_points == 3`.
- ATR tolerance: a 3rd touch just off-line counts; far off does not.
- Break needs a body close; wick poke holds.
- Retest after break; close back across voids.
- Single apex → no line; ascending highs → no upper line.
- max_lines cap; channel freshness.

Update `tests/test_indicators/test_xfactor.py::test_detector_lines_carry_touch_bars`
to data that actually forms a line (the old fixture had one apex).
