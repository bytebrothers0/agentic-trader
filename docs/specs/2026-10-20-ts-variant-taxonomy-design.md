# TS Variant Taxonomy — Turtle Soup Generalization (Design)

> 2026-10-20 · Status: DRAFT for review · targets `indicators/ts_detector.py`, `config/settings.py`, `server.py`, `web/app.js`, `tests/test_indicators/test_ts.py`

## 1. Problem

The TS (Turtle Soup) indicator implements exactly one variant: the strict **two adjacent-candle sweep** (candle1's extreme swept by candle2, whose body closes back inside). CRT — the strategy TS belongs to — defines **five** models that share one skeleton (anchor candle = range → manipulation sweep with body close-back → distribution) and differ only in **what happens between the range candle and the sweep candle** (and, for the two-candle form, what the sweep candle itself delivers). The NYSE/Raschke origin (fade of a 3–20 bar old high/low) and the ICT re-framing (liquidity sweep false-out) both reduce to the *same manipulation event*; only the bar structure and validation windows vary.

## 2. Source taxonomy (researched 2026-10-20)

Canonical community taxonomy (theinnercircletraders.com "Types of CRT"; Scribd "Types of CRT Candlestick Models"; tradingwyckoff.com; innercircletrader.net CRT tutorial):

| # | Model | Structure after the range candle (candle 1 = anchor) |
|---|-------|------------------------------------------------------|
| 1 | **Classic (3-candle)** | candle 2 manipulates (sweeps a boundary, body closes back inside); candle 3+ delivers distribution |
| 2 | **Two-candle** | candle 2 *both* manipulates and distributes within itself — signals volatility |
| 3 | **Multiple-candle** | candle 2 manipulates; distribution extends over the remaining (3+) candles |
| 4 | **Inside-bar** | candle 2 is an **inside bar** of the anchor (no manipulation); candle 3 manipulates and starts distribution |
| 5 | **Multiple inside-bar** | 2+ inside bars accumulate inside the anchor, then the manipulation candle sweeps |

Community probability ranking: **multiple inside-bar > inside-bar > classic > multi-candle** ("the more inside bars, the higher the probability" — accumulation banks more liquidity before the raid).

## 3. Unambiguous core math (the invariant)

All variants share, for anchor candle `i` (range `CRH = h[i]`, `CRL = l[i]`) and sweeping candle `j`:

- **Manipulation (the Turtle Soup), upper side**
  - `h[j] > CRH + sweep_min` (strict breach of the range high)
  - `max(o[j], c[j]) < CRH` (body closes back **inside** the range — the close-back is mandatory)
  - `invalidation (same candle)`: `min(o[j], c[j]) > CRH` → body closed through → real breakout, **no signal**, the upper side of this anchor is dead
- **Lower side**: exact mirror on `CRL`.
- **Both-side bar**: a candle breaching both boundaries in one bar is **one** event; keep the **deeper raid** (`|h[j] − CRH|` vs `|CRL − l[j]|`), emit a single signal. (Same discipline as CRT: one setup per manipulation candle.)
- `close_back_distance = CRH − max(o[j], c[j])` (upper) / `min(o[j], c[j]) − CRL` (lower)
- `sweep_amount = h[j] − CRH` (upper) / `CRL − l[j]` (lower)
- Wick/appearance gates on the *anchor* (to qualify it as a visible range) stay exactly as shipped (`TS_MIN_WICK_BODY_FRAC`, `TS_MIN_WICK_RANGE_FRAC`, default 0.10 / 0.05) so existing display behavior is preserved.

## 4. Operationalized variant rule (resolves the classification ambiguity)

Classic vs two-candle vs multiple-candle is taught around *distribution timing*, which a **sweep-only** signal cannot see (per decision: TS does not project targets or track distribution — the CRT detector owns the full lifecycle). Therefore the variant is **fully determined by the observable structure of `[i+1, j]` at the sweep bar's close**:

Let `k = j − i` (all valid: `1 ≤ k ≤ TS_MAX_BETWEEN`):

| Condition at sweep bar `j` | Variant |
|---|---|
| `k == 1` and the sweep bar **delivers to the opposite boundary** within itself (upper TS: `l[j] ≤ CRL`; lower TS: `h[j] ≥ CRH`) | `TWO_CANDLE` |
| `k == 1`, no same-bar delivery | `CLASSIC` (the textbook 3-candle form at the manipulation candle) |
| `k == 2` and bar `i+1` is a strict inside bar of the anchor (`h[i+1] < CRH` **and** `l[i+1] > CRL`) | `INSIDE_BAR` |
| `k ≥ 3` and **every** bar in `[i+1, j−1]` is a strict inside bar of the anchor | `MULTIPLE_INSIDE_BAR` |
| otherwise (non-inside bars between; the anchor's liquidity was taken after intervening pullback/consolidation bars that never breached a boundary with a valid close-back) | `MULTIPLE_CANDLE` |

Notes
- An inside bar (`h ≤ CRH and l ≥ CRL`) can never itself be the sweep candle, so "earliest valid sweep" and inside-bar accumulation do not conflict.
- **One signal per anchor per side**: for each anchor `i` and each side, scan `j` ascending from `i+1`; the **first valid sweep** wins; later re-sweeps of the same anchor side are suppressed (this also lowers duplicate/stacked rays of today's adjacent-only behavior).
- **Nested containers collapse to the outermost** (added during implementation): when ONE manipulation candle sweeps the boundaries of MANY anchors on the same side, candidates whose range sits fully inside another candidate's range are dropped, keeping the **outermost container** — CRT's "widest range wins" discipline. Non-nested candidates are independent signals and all survive; an exact size tie keeps the earliest anchor. (This suppresses a subset of the legacy adjacent-chain double counts — the intentional chart-cleaning change; the side-dies rule and earliest-sweep rule still hold.)
- **Both-side tie keeps both**: when a single candle raids one anchor's two boundaries to *exactly* equal depth, the deepest-raid rule cannot discriminate, so both sides fire (the documented legacy behaviour of the doji fixture). Only a *strictly* deeper raid collapses the shallower side.
- `k == 1` covers the manipulation candle of classic/2-candle/multi-candle CRT forms; the operationalized `TWO_CANDLE` requires the delivery evidence (touch of the opposite boundary in the same candle). This is the honest, checkable reading of "candle 2 manipulates *and* distributes".
- `MULTIPLE_INSIDE_BAR` requires ≥ 2 inside bars (`INSIDE_BAR` is the `k == 2` count-1 case); probability ranking can be derived downstream from the variant + `inside_bars` count.

## 5. Lifecycle (sweep-only)

`TSLevel.state ∈ {SWEPT, INVALIDATED}`

- Signal is emitted **SWEPT** at `j`'s close (today's payload showed `FRESH`; see §7 for the payload mapping).
- A **later** bar `t > j` with a **body close through** the swept boundary (`min(o[t], c[t]) > price` for upper / `max(o[t], c[t]) < price` for lower) → `INVALIDATED` (terminal). Wick-only re-pokes never count (MSNR fresh rule: body through closes, wick through sweeps).
- No target projection, no `TARGET_HIT` — CRT keeps that role.

## 6. Files & changes

| File | Change |
|---|---|
| `indicators/ts_detector.py` | Rewrite internals: anchor-based scan with `TS_MAX_BETWEEN` window, new `TSVariant` (`TWO_CANDLE` / `CLASSIC` / `INSIDE_BAR` / `MULTIPLE_INSIDE_BAR` / `MULTIPLE_CANDLE`), new `TSState` (`SWEPT` / `INVALIDATED`); `TSLevel` gains `variant`, `inside_bars: int`, `state`, `end_time`, `invalidated_candle_index` (all defaulted — the dataclass stays back-compatible); earliest-valid-sweep dedupe; deepest-raid both-side rule. Public API unchanged: `TSDetector(df, …).detect_all()`. |
| `config/settings.py` | Add `TS_MAX_BETWEEN = 5`; keep everything else (`TS_ENABLED`, wick fracs). |
| `server.py` | TS payload block: pass `TS_MAX_BETWEEN`; add `variant`, `inside_bars`, `target: null`-less fields as **optional keys**; `state` becomes real (`"FRESH"` when `SWEPT` — preserving `app.js`'s solid-style contract — `"INVALIDATED"` otherwise), `end_kind` becomes `"active"` / `"invalidated"`, `end_time` filled when invalidated. |
| `web/app.js` | Minimal labels only: tag text stays `TS-H`/`TS-L`; inside-bar variants render a `·IB`/`·IB…` suffix (`type` already flows through); invalidated TS drops to the dotted/dead style already used for dead levels. Cache-buster bump. |
| `web/index.html` | Cache-buster bump for `app.js` only (if style.css untouched). |
| `tests/test_indicators/test_ts.py` | Per-variant synthetic fixtures (all five), invalidation, both-side deepest, `TS_MAX_BETWEEN` bound, earliest-sweep dedupe, legacy adjacent-sweep red/green parity with the old behavior (same level price/indices), gates (`sweep_min`, `min_sweep_atr`, wick fracs) unchanged. |
| `ai_agent/ts_validator.py` | Optional one-line brief touch-up ("two-candle wick sweep" → "liquidity sweep, body close-back; variants two-candle/classic/inside-bar/multiple-inside-bar/multiple") — only if the user wants it; otherwise untouched. |

Stays untouched: `indicators/crt_detector.py` (detection is perception, not strategy), `agentic/feed.py` (family `ts` already carries generic extras; add `variant`/`inside_bars` pass-through only if it doesn't already — verify during implementation), `agent` renderer (label "T" fine).

## 7. Lifecycle-matrix honesty

- **Setup**: pure stateless detector; ATR only computed when `min_sweep_atr > 0` (unchanged).
- **Conflict**: one-signal-per-anchor rule could conflict with users who liked seeing repeated re-sweeps of the same level; #intro Small risk. The old adjacent-chained behavior is preserved for *different* anchors.
- **Scale**: window ≤ 5 keeps O(n×5) — negligible.
- **Failure/edge**: `end_time` may fall off the fetched window (level at the data edge) — clamped by the server exactly as other detectors do (`min(idx, len−1)`); invalidation may straddle the `TS_MAX_BETWEEN` horizon *after* the signal — invalidation scans forward from `j` with **no** horizon (a level only dies once).
- **Back-compat**: `detect_all()` return count can only decrease (dedupe + invalidation-suppressed signals never emitted); all existing `TSLevel` consumers keep their field set.

## 8. Test checklist (acceptance)

1. Adjacent sweep, wick-only close-back → `CLASSIC`, lifecycle `SWEPT`.
2. Adjacent sweep whose candle also touches the far boundary → `TWO_CANDLE`.
3. Anchor → inside bar → sweep → `INSIDE_BAR` (`inside_bars == 1`).
4. Anchor → 3 inside bars → sweep → `MULTIPLE_INSIDE_BAR` (`inside_bars == 3`).
5. Anchor → mixed non-inside bars → sweep → `MULTIPLE_CANDLE`.
6. Later bar closes body-through → state flips to `INVALIDATED` with `end_time` set; wick-through-for-later does **not** invalidate.
7. Both-boundary breach in one bar → exactly one signal, the deeper side.
8. `TS_MAX_BETWEEN = 5`: a valid sweep at `k == 6` is **not** a TS for that anchor.
9. Earliest-sweep rule: anchor swept twice (valid at `k==1` and again at `k==3`) → one signal.
10. Parity: the earliest qualifying adjacent sweep per anchor still appears with identical `price` / `candle_index` / `sweep_candle_index`; linked *nested* anchors swept by the same candle collapse to the outermost container (an intentional, spec'd volume reduction over the legacy adjacent-chain behavior).
11. `sweep_min`, `min_sweep_atr`, wick-fracs gates retain today's semantics (unit re-runs).
