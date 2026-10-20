# Agent status filter — fresh-only perception (2026-10-20)

**Decision (user-approved):** the agent gets a new `set_view` dial, `status_filter`,
controlling *which life-cycle states* of every indicator it perceives. Default is
**`"live"`** — fresh / unmitigated / unbroken — per indicator.

## Problem

The agent controls *where* (symbol/timeframe/bars/offset) and *what families*
(`crt`, `bos`, `ts`, …) it sees, but not *which states*. Status was visible
(`end_kind` in the manifest, `level_lookup`) but not controllable. Real cost on
the TS M15 render of 2026-10-20: **64 of the 80 drawn rays were dead**
(invalidated) — the per-family ray budget (`MAX_RAYS_PER_FAMILY = 80`) and the
vision surface were consumed by history, not signal.

## Design

- `View.status_filter: str = "live"` (`agentic/models.py`), values
  **`"all"` / `"live"`** (`STATUS_FILTERS`).
- Semantics: `"live"` keeps only `LevelStatus.LIVE`, which per family is exactly
  the phrase the user asked for — TS alive (`FRESH`), CRT undistributed/
  uninvalidated, FVG/IFVG fresh, OB unmitigated, IDM unswept. The mapping is
  already owned by `feed.status_of` (`end_kind` first, then `state`).
- Threaded through the tools' fetch seams only (`render_current`,
  `_fetch_snapshot`, `_resolve_pin` path, `_snapshot_for_timeframe`) by passing
  `status_filter=` to `Feed.snapshot`, which filters *after* parsing with
  `dataclasses.replace` (parse stays pure; `current_price`/`atr` ride along).
- The per-turn cache key grows to `(timeframe, bars, offset, status_filter)`.
- **Pins are never silently hidden:** a pin resolves against the filtered
  snapshot first (the normal, single-fetch path); if it misses and the view
  filter is `"live"`, the resolver fetches one `"all"` snapshot for that
  timeframe (own cache entry) and retries — a deliberately pinned *dead* level
  still draws (and the renderer already exempts pins from the ray budget).
- `watchdog.py` is deliberately NOT filtered: subscription evaluation needs
  state history (edge triggers such as "level breaks" require the dead levels).
- Unknown values are refused by `set_view` with `invalid_status_filter`; old
  persisted state lacking the field loads with the default `"live"`.
- `level_lookup` follows the dial (it reads the same filtered snapshot); the
  escape hatch is `set_view(status_filter="all")`, documented in the prompt.

## Not in scope

Per-render `status=` param (weaker: a preference that doesn't persist, chosen
against); store root schema change (the dial lives inside `View`, precedent
`offset`); any change to the propose-only discipline.
