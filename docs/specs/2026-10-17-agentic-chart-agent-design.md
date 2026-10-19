# Agentic Chart Agent — Self-Directed Perception, Pins and Watches

Date: 2026-10-17
Status: Phases 0–6 built and wired 2026-10-17; phase 6c (live-mode wiring against the shared provider, 2026-10-18) is in place and was confirmed against the live API up to the Groq on-demand tier's per-request token ceiling — which the **local provider** (`LLM_PROVIDER=local`) lifts; phase 6d added the `offset` dial and a real two-pane `split`. The live agent now runs **end to end** against the local provider (a real boot turn reads the chart and writes a grounded thesis; see the provider subsection). Phase 7 (execution) deferred. The pure core, the loop, the renderer, the LLM client, the runtime service and the web panel are all in place.
Module: `agentic/` (new) — the pure, LLM-free substrate (`models`, `conditions`, `store`, `crt_strategy`, `subscriptions`, `watchdog`, `lookup`, `tools`, `prompts`, `agent_loop`, `_time`, `llm`), the two impure edges (`feed.py`, the single lazy read-only bridge; `renderer.py`, which loads the vision stack inside its functions), and the repo-root runtime `agent_service.py`. `GET /api/agent/*` wires it into the running system.

## Problem

The bot today is a fixed dashboard. A human decides which symbol, timeframe and
indicators to look at; the detectors compute levels; `web/app.js` draws them. Every
question about the market is answered by a person clicking, and every insight expires
the moment the timeframe changes, because loading a new timeframe *replaces* the level
set instead of adding to it.

There is no component that can:

- decide **what to look at** on its own,
- **hold a level in view** across a timeframe change (the 2H FVG that survives the drop
  to M5),
- **defer observation** to a future time window ("watch for an FVG from now until it
  forms"),
- or wake itself when the thing it was waiting for finally happens.

`ai_agent/` is not that component. It reasons over a **text** snapshot, it is built for a
different indicator world (the 37 `MSNR_*` MQL5 objects, not the Python suite), and its
snapshot builder is currently **broken**: `ai_agent/msnr_snapshot.py:16-17` imports
`strategy.storyline_engine` and `strategy.entry_engine`, neither of which exists, so
`/api/ai/scan` cannot run despite the router being mounted in `server.py:60-64`.

## Idea

An agent that **owns its own perception**. The strategy lives in a system prompt; the
agent then declares what it wants to see — symbol, timeframe, indicators, chart style —
the system renders that to an **image**, and the agent reasons over the image. It may
**pin** a level from one timeframe and keep it mapped while working in another, it may
**watch** for a condition over an explicit time window, and when a watch fires the system
wakes it with the evidence.

Nothing about the agent's world is implicit. Its perception, its subscriptions, its
thesis and its reasoning are an explicit, durable, inspectable object.

**Non-goal for v1: placing orders.**

## Principles (locked in design review)

| # | Principle |
|---|---|
| P1 | The Python indicator suite is the single source of truth for levels. The agent never becomes a second one. |
| P2 | The agent owns its perception and declares it. Perception settings are state, not UI state. |
| P3 | Perception is **vision-first**; exact numbers are fetched on request. |
| P4 | All agent state is explicit, durable and inspectable. Memory is a document, not a transcript. |
| P5 | The substrate (store, subscriptions, watchdog, renderer) is **LLM-free** and testable without a model. |
| P6 | A **pin** and a **watch** are the same primitive: a subscription. |
| P7 | The indicator and rendering paths are read-only. The agent cannot corrupt what it perceives. |
| P8 | Autonomous but leashed: caps, expiries, coalescing, spend ceilings, kill switch. |
| P9 | Propose-only. The agent emits plans; it does not execute. |

## Architecture

```
                      ┌──────────────────────────────────────────┐
   Python indicator   │              LevelFeed                   │
   suite (read-only) ─▶  computes + caches the level payload     │
   indicators/*.py    │  per (symbol, timeframe)                 │
                      └───────┬──────────────────────┬───────────┘
                              │                      │
                              ▼                      ▼
                    ┌──────────────────┐   ┌────────────────────┐
                    │    Renderer      │   │    Watchdog        │
                    │  store → PNG +   │   │  evaluates open    │
                    │  manifest        │   │  subscriptions     │
                    └────────┬─────────┘   └─────────┬──────────┘
                             │                       │ fire
                             ▼                       ▼
                    ┌──────────────────────────────────────────┐
                    │   Context Store  (state of record, disk) │
                    │  view · pins · watches · thesis · turns   │
                    │  proposals · budget                       │
                    └────────┬───────────────────────┬─────────┘
                             │                       │
                             ▼                       ▼
                    ┌──────────────────┐   ┌────────────────────┐
                    │   Agent Loop     │   │   Agent Panel      │
                    │  (LLM turn)      │   │  (human view)      │
                    └──────────────────┘   └────────────────────┘
```

**Components**

| Component | Responsibility | Uses an LLM? |
|---|---|---|
| `LevelFeed` | Computes and caches the indicator payload per (symbol, timeframe). Single source of truth, read-only over `indicators/`. | No |
| `Renderer` | Renders the current store to an image (PNG) plus a manifest of what was drawn, with tags. | No |
| `SubscriptionEngine` | Owns pins and watches: creation, dedupe, caps, expiry, edge-triggered evaluation. | No |
| `Watchdog` | Evaluates open subscriptions against fresh feed data on bar close; backs up fires; coalesces them. | No |
| `ContextStore` | The durable state of record. Everything above reads or mutates it. | No |
| `AgentLoop` | A turn: build briefing → render → LLM → tools → persist. | **Yes** |
| `AgentPanel` | The human view of the store + chat + kill switch. | No |

**The loop**

1. Something starts a turn — boot, a fired subscription, or a human request.
2. The Renderer draws the store: live levels for the active timeframe plus every pinned
   level from other timeframes, each carrying a legible tag.
3. The agent receives the image, its thesis, its open subscriptions, and **why this turn
   happened**.
4. It reasons, then calls tools: change the view, look up exact numbers for a tag it saw,
   add or release a pin, register or cancel a watch, write a note, emit a proposal.
5. Tool calls mutate the store; it may render again to look at what it changed.
6. The turn ends and is logged. The Watchdog keeps evaluating subscriptions. Its next fire
   begins step 1 again.

## The Context Store

The central rule: **the store never duplicates detector output.** Levels are recomputed by
`LevelFeed` on every render. The store holds *intent* (what to look at) and *agent
metadata* (what is pinned, what is watched, what it thinks). Consequences: the store stays
small, detector drift is impossible, a store bug can never change a level's price, and the
indicator layer stays strictly read-only.

One store per **symbol**; one symbol active at a time in v1.

### Fields

**`view`** — the agent's current perception settings.

```json
{
  "symbol": "XAUUSDm",
  "timeframe": "M15",
  "chart_type": "candles",
  "families": ["bos", "idm", "fvg", "ob", "liquidity", "trendline", "sr", "qm"],
  "bars": 300,
  "offset": 0,
  "layout": "single",
  "panes": [],
  "show_tags": true,
  "annotations": []
}
```

`layout` ∈ `single | split`; `panes` is the multi-timeframe list when `split` (e.g.
`["H2","M15"]`, top pane first). `bars` is the lookback window and `offset` is how many
of the most-recent bars to skip back, so the visible window is
`[now-(offset+bars)*tf, now-offset*tf]` — `offset=0` is the live edge. `split` needs
exactly two **distinct** panes in v1; `timeframe` is kept equal to the primary pane
`panes[0]` on every split mutation (an explicit `timeframe` that disagrees with `panes[0]`
is refused). `single` ignores `panes`.

**`pins`** — durable records of pinned levels. A pin stores a **level identity query**,
not a snapshot, and is re-resolved against fresh feed output on every render.

```json
{
  "id": "pin_7f3a",
  "query": {
    "family": "fvg",
    "timeframe": "H2",
    "direction": "bullish",
    "price": 4152.86,
    "tolerance": 0.5
  },
  "level_key": "fvg:H2:bullish:4152.86:2026-10-16T14:00",
  "added_at": "2026-10-17T06:10:00Z",
  "expires_at": "2026-10-20T06:10:00Z",
  "status": "live",
  "note": "HTF draw, watch for mitigation"
}
```

`status` ∈ `live | swept | broken | filled | not_found`. `not_found` means the feed no
longer produces the level at all (aged out of the lookback, or genuinely gone) — reported
rather than silently dropped, which is the whole point of a live pin.

**`watches`** — durable records of conditions.

```json
{
  "id": "watch_c19d",
  "condition": "fvg_forms",
  "params": { "timeframe": "M15", "direction": "bullish", "min_size_atr": 0.3 },
  "starts_at": "2026-10-17T06:10:00Z",
  "expires_at": "2026-10-17T16:00:00Z",
  "one_shot": true,
  "wake_on_expiry": false,
  "state": "armed",
  "fire_count": 0,
  "last_evaluated_at": "2026-10-17T06:25:00Z",
  "reason": "waiting for the LTF FVG that confirms the sweep"
}
```

`state` ∈ `armed | fired | expired | released`. `one_shot` (default `true`) retires a watch
on its first fire; otherwise a `cooldown_s` gate applies before it can fire again.

**A pin is a watch on level existence.** Both reduce to
`Subscription{id, kind, condition, params, starts_at, expires_at, one_shot, state,
fire_count, last_evaluated_at, reason}`, with `kind='pin'` using the condition
`level_alive`.

**`thesis`** — the agent's current read. This, not a transcript, is its memory.

```json
{
  "updated_at": "2026-10-17T06:25:00Z",
  "bias": "bullish",
  "storyline": "H4 took the Asian low and reclaimed the range; expecting continuation to the 2H FVG at 4152.86.",
  "levels_of_interest": ["fvg:H2:bullish:4152.86:2026-10-16T14:00"],
  "invalidation": "M15 close below 4130.20 (the 15 Oct range low)",
  "confidence": 0.6
}
```

**`turns`** — append-only log. Per turn: `id`, `started_at`, `trigger`
(`boot | fire | request | schedule`), `trigger_detail`, the view at the time, subscription
states, every tool call with arguments and results, the output, `renders`, `tokens`,
`cost_usd`. This is what makes a self-starting agent debuggable, and it is where the leash
reads from.

**`proposals`** — emitted plans. Fields deliberately mirror `ai_agent/schemas.py:AIProposal`
for continuity: `bias`, `setup`, `entry`, `sl`, `tp`, `invalidation`, `confidence`,
`reason`, plus `provenance` (the level keys the plan rests on) and `status`
(`proposed | expired | invalidated | superseded`).

**`budget`** — `turns_today`, `turns_this_hour`, `renders_today`, `spend_usd_today`,
`window_started_at`.

**`agent`** — `enabled`, `mode` (`propose`), `model`, `spec_version`, `last_evaluated_at`.

### Caps and expiry rules

| Rule | Default | Why |
|---|---|---|
| `MAX_PINS` | 8 | Unbounded pins degrade the very image the agent reads. |
| `MAX_OPEN_SUBSCRIPTIONS` | 20 | Same. |
| `WATCH_TTL_DEFAULT` / `WATCH_TTL_MAX` | 24h / 7d | A watch without a deadline is a leak. |
| `PIN_TTL_DEFAULT` / `PIN_TTL_MAX` | 72h / 14d | Context must expire. |
| `MAX_RENDERS_PER_TURN` | 3 | Leash on the render loop. |
| `MAX_TOOL_CALLS_PER_TURN` | 8 | Leash on the tool loop. |
| `SUB_COOLDOWN_S` (repeating watches) | 300 | No machine-gunning. |

Every expiry is **required**, not optional. When a cap is hit, the store rejects the
mutation and the tool result tells the agent exactly why — so it can release something
deliberately instead of silently losing context.

### Persistence

Plain JSON, one file per symbol, under `agentic/state/<symbol>.json`, written
**atomically** (write temp, then replace). Loaded on boot. Same pattern as
`config/modules_state.json`.

## Perception contract: render + manifest + lookup

### The image

- Server-side render to PNG. No browser in the loop.
- **Vision-optimised style**: high contrast, thick lines, large legible fonts, minimal
  chrome, no gridline noise. Rendering for a vision model is not the same as rendering for
  a human.
- Default ~1536×864 (proposal), inside vision token budgets.
- Size and DPI are parameters of `Renderer`, not hard-coded.

### Tags and the manifest

Every drawn level carries a short **tag** rendered legibly next to it — family initial plus
ordinal within that render (`F1`, `F2`, `B1`, `L3`), with pinned levels additionally
marked (`F1*`). The manifest is the machine-readable map:

```json
{
  "render_id": "r_01H9...",
  "symbol": "XAUUSDm",
  "timeframe": "M15",
  "window": { "from": "2026-10-16T12:00Z", "to": "2026-10-17T06:25Z", "bars": 300 },
  "rendered_at": "2026-10-17T06:25:12Z",
  "price_range": [4128.4, 4192.7],
  "image": { "path": "...", "width": 1536, "height": 864 },
  "tags": {
    "F1": {
      "level_key": "fvg:H2:bullish:4152.86:2026-10-16T14:00",
      "family": "fvg", "timeframe": "H2", "direction": "bullish",
      "price": 4152.86, "price_low": 4151.90, "price_high": 4153.40,
      "status": "live", "origin": "pinned", "distance_points": 118.0
    }
  }
}
```

Rules:

- Tags are **unique within a render** and **stable within a render**. They are *not*
  guaranteed stable across renders — the agent cites tags *within* a turn and exact level
  keys or prices *across* turns.
- `origin` ∈ `live | pinned` is always present, so the agent can never confuse what the
  current timeframe is producing with what it deliberately held.
- The manifest is always produced, even though the default perception is vision-first: it
  is how tags resolve, how the lookup answers, and how a turn is audited later.

### Determinism

Same store + same feed → byte-identical image. No randomness, no wall-clock in the drawing.
This makes turns replayable and lets Phase 3 assert an image hash.

### The numeric lookup tool

Ground truth for anything the agent saw. `level_lookup` accepts any of:

- `tag` — resolve what it just saw (`{"tag": "F1"}`),
- `level_key` — re-resolve something from a previous turn,
- `family` + `timeframe` — list a whole family,
- `near_price` + `radius` — what is around here.

Returns exact records: price (and zone band), family, timeframe, direction, `created_at`,
`status`, `origin`, distance from current price in **points** and in **ATR**, and whether
it is the thesis's stated level of interest. It also answers "what is the current price and
its ATR".

**The discipline this enforces:** the image teaches the agent *what exists and where*; the
lookup teaches it *exactly what it is*. Any price the agent states must have come from the
lookup, not from reading pixels. This is a prompt-level rule and a review-level check — a
vision model reading `4168.66` off a raster will sometimes read `4166.86`.

## Subscriptions: pins ≡ watches

One mechanism, two faces.

| | Pin | Watch |
|---|---|---|
| Subscribes to | a level's continued existence | a condition over time |
| Condition | `level_alive` | one of the vocabulary below |
| Fires when | the level transitions out of `live` (swept/broken/filled) or stops being produced | the condition rises `false → true` |
| Typical use | "keep the 2H FVG mapped while I work in M15" | "tell me when an M15 FVG forms before 16:00" |

### Condition vocabulary

The Watchdog's language. **A condition that cannot be evaluated deterministically cannot
wake the agent** — so "watch for a good long setup" is not expressible, by design. This
list is the most important enumeration in the design.

| Condition | Params | Fires when | Default TF |
|---|---|---|---|
| `level_forms` | `family`, `direction?`, `min_size_atr?` | a new level of the family appears | active |
| `level_touched` | `level_key` or `family`+`price` | price reaches the level's band | level's TF |
| `level_swept` | `level_key` or `family`+`price` | the level's freshness tracker marks it swept | level's TF |
| `level_broken` | as above | body close through the level | level's TF |
| `level_filled` | `level_key` | an FVG/OB is mitigated | level's TF |
| `level_alive` | `level_key` | internal — the pin's condition | level's TF |
| `bos_forms` | `timeframe`, `direction?`, `internal?` | a BOS prints | as given |
| `choch_forms` | `timeframe`, `direction?`, `internal?` | a CHoCH prints | as given |
| `idm_swept` | `timeframe`, `rule?` | an IDM is taken | as given |
| `price_crosses` | `price` | close crosses an absolute price | active |
| `price_enters_zone` | `low`, `high` | price enters a band | active |
| `range_expands` | `multiple`, `reference` (`ADR`/`ATR`) | session range exceeds `multiple × reference` | active |
| `session_opens` / `session_closes` | `session` (`asia`/`london`/`ny`) | the session boundary passes | — |
| `time_reached` | `at` | the given timestamp passes | — |

Semantics:

- **Edge-triggered.** A condition fires on a rising edge (`false → true`), never on every
  evaluation while it stays true. `level_touched` fires once per touch sequence, not once
  per bar.
- **Timeframe-scoped.** Each condition names the timeframe it is evaluated on, so a
  `bos_forms` on H1 is not re-evaluated on every M15 tick.
- **Deterministic.** Evaluated by the same detectors the chart uses. No model, no
  interpretation.

## The Watchdog

- Runs in the server process, **LLM-free and render-free**.
- **Cadence:** on the close of any bar whose timeframe is referenced by an open
  subscription, plus a throttled price check for price-based conditions (proposal: 15s).
- **Cheap:** reuses `LevelFeed`'s cached payloads. If a subscription references a
  (symbol, timeframe) nobody has computed, it computes it once and caches it.
- **Coalescing:** fires inside `COALESCE_WINDOW_S` (proposal: 45s) merge into **one turn**
  whose briefing lists them all. A burst of fires is usually one regime event, and one
  turn with the full picture is both cheaper and more useful than five turns with
  fragments.
- **Backfill on boot:** the watchdog is not running while the server is down. On startup,
  every open subscription is evaluated against the bars between `last_evaluated_at` and
  now. Missed fires are reported as **retroactive** (`"would have fired 2026-10-17T14:05Z"`)
  and clearly marked as not live. Without this, downtime silently swallows exactly the
  events the agent was waiting for — which would make the whole watch mechanism untrustworthy.
- **Fire payload:** `{subscription_id, kind, fired_at, retroactive, condition, params,
  evidence{level record | price | bars}, state_before, state_after}`.
- **Expiry is not a fire by default.** Expiries are batched into the *next* turn's briefing
  ("3 watches expired since your last turn"). A subscription may opt in with
  `wake_on_expiry: true` when the deadline itself is the event.

## The Agent Loop

### Triggers

| Trigger | When | Notes |
|---|---|---|
| `boot` | server start, if `agent.enabled` | **mandatory** first turn; seeds perception |
| `fire` | a watch fired (possibly several, coalesced) | the steady state |
| `request` | the human asks, or hits "run now" | always allowed |
| `schedule` | optional slow cadence (proposal: off by default) | a fresh look even in a quiet market |

### Turn anatomy

1. **Briefing** — the trigger and its detail; the current thesis; every open subscription
   with state and time remaining; the budget position; the previous turn's conclusion in
   one line.
2. **Render** — the store's `view` + `pins` → image + manifest.
3. **LLM call** — system prompt + image + briefing + tool definitions.
4. **Tool phase** — mutate the store; the agent may render again to look. Bounded by
   `MAX_TOOL_CALLS_PER_TURN` and `MAX_RENDERS_PER_TURN`.
5. **Output** — a structured result: thesis update, proposals, subscription changes, notes.
6. **Persist and log** — the store is written; the turn is appended to `turns`.

### The boot turn

On an armed server start, the system renders a **default/"raw" perception** — current
symbol, a default timeframe, the default family set — and hands it to the agent
unprompted. If a store already exists it is **resumed**, not reset: the briefing says
where it left off, what its thesis was, what is still open, and what fired while it was
down. A restart must not lobotomise it.

The boot turn's job, per the playbook: orient (HTF bias) → locate (the levels that matter)
→ set its own view → write a thesis with an explicit invalidation → arm subscriptions.

### Tool surface

| Tool | Purpose |
|---|---|
| `set_view` | symbol, timeframe, chart type, families, bars, offset, layout/panes, tags, annotations |
| `render` | re-render after a change; returns image + manifest |
| `level_lookup` | exact numbers for a tag, a level key, a family, or a price neighbourhood |
| `add_pin` / `release_pin` | hold a level across timeframes |
| `add_watch` / `cancel_watch` | defer observation to a time window |
| `list_subscriptions` | see what is open, with time remaining |
| `set_thesis` / `add_note` | durable memory |
| `propose_trade` | emit a plan (propose-only) |

There is deliberately **no** order tool in v1.

### System prompt contract

- **Role:** analyst of this chart. Propose-only.
- **Strategy:** the MSNR playbook — survey → locate → arm → react → journal — as the
  agent's *default instinct*, drawn from `strategy_notes/`. Prompted behaviour, not
  enforced control: it may improvise when the playbook does not fit.
- **Perception rules:** ask for what you need; do not assume the default view is the right
  view; a pinned level stays visible across timeframes so use pins instead of re-finding
  the same level.
- **Truth rules:** every price you state must come from `level_lookup`; never read a price
  off the image; cite level keys for across-turn references and tags within a turn.
- **Discipline rules:** always state a thesis and an explicit invalidation; always set an
  expiry on a subscription; prefer one well-reasoned wait over five speculative ones.
- **Honesty rules:** report uncertainty; do not claim an edge the evidence does not show.

### Output contract

Structured, mirroring `AIProposal` where possible: `thesis`, `proposals[]`,
`subscriptions_added[]`, `subscriptions_released[]`, `notes`, `reasoning`.
`mode=propose` means a `proposal` is a *plan*, never an order.

## Memory, persistence, restart

- **Not a transcript.** Each turn's context is *built fresh* from the store, so prompt size
  is bounded and roughly constant regardless of how long the agent has been running. A
  growing conversation would inflate cost and drift; the store is the memory instead.
- **What is durable:** the view, pins, watches, thesis, proposals, the turn log, and the
  budget counters.
- **Restart:** load the store → run backfill over the downtime → boot turn briefed with
  what changed. `last_evaluated_at` is the seam that makes this work.
- **Replayability:** because the feed adapter, renderer and subscription engine are
  deterministic, a recorded turn can be re-rendered and re-evaluated. That is what makes
  "why did it do that" answerable.

## Human surface

- **Agent Panel** — reads the store, never duplicates it: current thesis, open
  subscriptions with countdowns, pins, the current view, the turn log, proposals, budget
  position. This doubles as the context inspector.
- **Chat** — a box that starts a `request` turn. One view onto the store, not the store.
- **Settings tab** — the `agent.enabled` toggle (integrated the same way
  `strategy/registry.py` integrates entry modules), model selection, mode, budget limits.
- **Kill switch** — disable, plus "pause" (stop waking, keep state).

## Economics and the leash

Cost drivers: **images** (vision tokens) and **turn count**.

| Leash | Default (proposed) |
|---|---|
| `MIN_TURN_INTERVAL_S` | 60 |
| `MAX_TURNS_PER_HOUR` | 6 |
| `MAX_TURNS_PER_DAY` | 60 |
| `MAX_SPEND_PER_DAY_USD` | configurable, hard stop |
| `COALESCE_WINDOW_S` | 45 |
| expiry batching | on (expiry does not wake) |
| `wake_on_expiry` | opt-in per subscription |
| mock mode | full loop with a scripted agent, zero API spend |

An armed agent that self-starts needs a leash, not as a flourish but as a required
component: a chatty watchdog is a subscription you did not sign up for.

## Integration points (as wired — phase 6)

Phases 0–5 add `agentic/*` only. **Phase 1 already touched `server.py`** (the read-only `GET /api/agent/crt` and the `atr` field on `/api/indicators`); **phase 6 is the first phase to wire the runtime into the running system** — the endpoints, the startup hook, the `AGENT_*` settings, the registry entry and the web panel.

| Where | What changed |
|---|---|
| `agentic/feed.py` | read-only adapter over `indicators/*` (via `server.get_indicators`) producing the level payload + statuses; the single **lazy** bridge |
| `server.py` | mounts `/api/agent/*` (panel state, turns, render, enable/disable/pause/resume, run-now) in the existing try/except style; a `startup` hook arms the service when `AGENT_ENABLED`; `_sync_agent_module` keeps the registry entry in step with the store gate |
| `web/` | Agent Panel drawer + chat box + kill switch; cache-buster bump in `index.html` |
| `config/settings.py` | an `AGENT_*` block (`AGENT_ENABLED` autostart, `AGENT_MODE`, `AGENT_MODEL`, `AGENT_SYMBOL`/`AGENT_TIMEFRAME`/`AGENT_BARS`, `AGENT_POLL_S`, `AGENT_API_BASE`/`AGENT_API_KEY_ENV`, `AGENT_MAX_TOKENS`/`AGENT_TEMPERATURE`, `AGENT_HTTP_TIMEOUT_S`, `AGENT_STATE_DIR`/`AGENT_RENDER_DIR`) |
| `strategy/registry.py` | the `agent` module id for the settings tab (default disabled) |
| `ai_agent/` | untouched. Its broken imports (`strategy.storyline_engine`, `strategy.entry_engine`) and the MQL5 MSNR world are legacy; retiring it is a separate decision. |

## Build order

| Phase | Deliverable | Acceptance |
|---|---|---|
| **0** ✅ | `models.py` + `store.py`: schemas, atomic persistence, caps/expiry enforcement, budget accounting | round-trip a store; caps and expiries reject with a reason; no LLM, no repo changes |
| **1** ✅ | `feed.py`: read-only level adapter, level-key identity, status mapping from the freshness tracker. Landed with `crt_strategy.py` (the top-down CRT playbook) and a read-only `GET /api/agent/crt`, and `atr` added to the `/api/indicators` payload | keys are stable across recomputation; a swept level reports `swept`, not `live` |
| **2** ✅ | `feed.py` bars + `subscriptions.py` + `watchdog.py`: the vocabulary, edge-triggered evaluation, dedupe, coalescing, backfill | every vocabulary entry tested against a fake feed; backfill reports a retroactive fire across simulated downtime |
| **3** ✅ | `renderer.py` + `lookup.py`: store → PNG + manifest, tags, vision-optimised style; exact numbers on request | byte-identical render for identical state (image hash test, incl. across processes); manifest resolves every tag |
| **4** ✅ | `tools.py` + `prompts.py` + `agent_loop.py` with a **scripted mock agent** | full turn end-to-end with zero API spend; turn log complete; leash enforced |
| **5** ✅ | `llm.py`: the vision client — prompt, tool-calling, structured output — pure over an **injected transport** | the request/parse path is exercised on a canned transport; the live call is wired by phase 6, never by the core |
| **6a** ✅ | *(backend)* `agent_service.py` + the `AGENT_*` settings + the registry entry + `/api/agent/*` | panel reflects the store; disable stops all waking; the store gate is authoritative |
| **6b** ✅ | *(web)* Agent Panel + chat + kill switch in `web/` | the drawer reads `/api/agent/panel`; enable toggle and pause/resume drive the service |
| **7** | *(deferred)* execution | out of scope for this spec |

Phases 0–2 were pure logic, buildable and testable independently of any indicator
work, because they depend on nothing outside themselves; the loop, renderer, LLM
client and the wiring followed in phases 3–6.

## As built — phases 0–6 (2026-10-17)

**Phase 0** shipped `models.py` + `conditions.py` + `store.py` as specified.

**Phase 1** shipped the wiring the CRT strategy needs:

- `feed.py` — read-only adapter over `/api/indicators`. `LevelRecord` (family, timeframe, direction, price, band, status, CRT extras) with a stable `level_key`; `LevelStatus` mapped `end_kind`-first; `Feed(provider)` with a **lazily-importing** default provider. Family aliases normalise `liq`→`liquidity`.
- `crt_strategy.py` — the **top-down CRT playbook** (research: CandelaCharts framework, crttrading.com, the ICT-derived community material):

  | Tier | Timeframes | Role |
  |---|---|---|
  | HTF bias | MN1 → W1 → D1 | the CRT container: a live CRT (swept, target unmet) sets direction; its opposite boundary is the draw |
  | LTF execution | H4 → H1 → M15 | confirmation: a BOS in the bias direction (CISD), then a fresh FVG/OB as the entry |

  `analyze()` derives the bias from the highest live HTF CRT, requires an LTF confirmation matching the bias, and builds a `CrtPlan`: entry at the aligned zone (discount for longs / premium for shorts), stop beyond the zone padded by 0.25×ATR (else 5% of the HTF range), target the **nearest** HTF CRT boundary beyond entry, partial at equilibrium, R:R and provenance. Propose-only.
- `conditions.py` gained `level_forms` optionals `variant` and `min_inside_bars` (watch for an inside-bar CRT specifically).
- `models.py`: `DEFAULT_FAMILIES` includes `crt`; the timeframe regex now accepts monthly `MN1`/`MN`.
- `server.py`: `atr` added to the `/api/indicators` payload, and `GET /api/agent/crt` exposes the read (read-only).
- `tests/test_agentic/test_standalone.py` now enforces: the pure core imports nothing from the repo, and `feed.py` is lazy.

**Phase 2a** — `feed.py` gained OHLC `Bars` (`snapshot` + `bars`); `subscriptions.py` (598 lines) added the deterministic, edge-triggered evaluator. `evaluate(sub, snapshot, bars, now=, last_evaluated_at=)` fires on the rising edge `false → true` only; `event_time` picks the fire instant per condition; sessions are fixed UTC windows; `price_crosses` needs strictly opposite closes; `range_expands` compares the UTC-day range to `ATR`/`ADR`. Two consecutive windows share no event time, so nothing double-fires.

**Phase 2b** — `watchdog.py` (420 lines): the LLM-free, render-free loop over the store's open subscriptions. `scan` retires expiries, evaluates, applies the repeating-watch cooldown, buffers fires, and emits **one** `fire` turn once `COALESCE_WINDOW_S` (45s) has elapsed; `backfill` recovers downtime fires (`retroactive=True`) and emits no turn; `flush` force-emits for `request`/`boot`. Expiry is not a fire unless `wake_on_expiry` is set. The clock is injected, never read.

**Phase 3** — `renderer.py` (560 lines) + `lookup.py` (298 lines). The renderer draws a vision-optimised PNG (default 1536×864) with a tag per drawn level and a canonical tag→`level_key` manifest; determinism is enforced by stripping PNG metadata and deriving `render_id = "r_" + sha256(png)[:16]` (`rendered_at` is manifest-only), so identical state → byte-identical image (asserted across processes). `lookup.py` is the single canonical `level_view` projection that both the manifest and `level_lookup` build from, so exact numbers can never drift from what was drawn; it resolves by `tag`, `level_key`, `family`(+`timeframe`) or `near_price`(+`radius`).

**Phase 4** — `tools.py` (628 lines) + `prompts.py` (330 lines) + `agent_loop.py` (575 lines) + `_time.py` (51 lines). The tool surface is eleven tools and **no order tool**; `ToolRegistry.execute` never raises (a refusal returns the store's own reason) and owns the `MAX_RENDERS_PER_TURN` budget (the initial perception render is render #1). `prompts.py` holds the policy prompt (top-down CRT playbook + vocabulary + perception/truth/discipline rules) and rebuilds the briefing fresh from the store each turn. `agent_loop.py` runs one turn — leash → gate → briefing + render → LLM + tools → output → persist — with a zero-spend `ScriptedAgent` so the whole loop is testable without a model. `_time.py` is the shared `as_aware`/`seconds_remaining`/`new_id` helper set.

**Phase 5** — `llm.py` (548 lines): the OpenAI-compatible vision client, pure over an injected `Transport`. `build_messages` assembles the system prompt, the briefing text, the image as a data URI and any prior tool calls; `parse_reply` reads the model's reply back tolerantly (a malformed tool-argument string becomes `{}` rather than an exception). `DEFAULT_MODEL` is `gpt-4o-mini`; `PRICES` is a configurable estimate table used only for leash accounting. **No real model call has been made yet** — the transport is supplied by phase 6, and the default mode is mock.

**Phase 6a** *(backend)* — `agent_service.py` (745 lines, repo root, non-pure: stdlib + `agentic` at module level only), the `AGENT_*` block in `config/settings.py`, the `agent` registry entry in `strategy/registry.py`, and the `/api/agent/*` routes in `server.py` (panel, turns, render, enable/disable/pause/resume, run-now) plus a `startup` hook. `AgentService` holds one symbol's store, watchdog and loop; a single `RLock` serialises whole turns across `boot`/`scan_once`/`run_now`. `scan_once` pre-checks the leash and, on `LeashExceeded`, returns without scanning (nothing is consumed, so the next poll re-detects). The scanning thread owns its own `threading.Event`; `stop()` clears the handle only after the join confirms exit, otherwise the service is *draining* and refuses a second thread. `enable()` also makes sure the thread is running.

**Phase 6b** *(web)* — the Agent Panel drawer (`#agentDrawer`) and top-nav button (`#btnAgent`) in `web/`: it reads `/api/agent/panel` (thesis, open subscriptions with server-side `seconds_remaining`, the dedicated `pins` projection, view, proposals, budget, recent turns, last render), exposes the enable toggle and pause/resume, and runs a chat box through `POST /api/agent/run-now?message=`. It polls only while the drawer is open and escapes model-authored text. Cache busters bumped (`style.css?v=16`, `app.js?v=24`).

**Phase 6c** *(live wiring)* — `AGENT_MODE="live"` now works end to end against the **already-integrated** provider, with no new secret and no new dependency. Four changes:

- **Provider inheritance.** `AGENT_MODEL` / `AGENT_API_BASE` / `AGENT_API_KEY_ENV` in `config/settings.py` default to `""`, meaning *inherit the shared provider*. A new pure `ai_agent.config.resolve_provider() -> (provider, base_url, model, key_env)` mirrors the selection `ai_agent/agent_loop.py` and `ai_agent/ts_validator.py` already inline (those two call sites are left byte-identical). `server.get_agent_service()` resolves it **lazily**, inside the function, only when `AGENT_MODE == "live"` (via the pure `server._resolve_agent_connection()`, which merges one field at a time), and logs one line (provider + model + base, never the key). Mock mode resolves nothing and needs no provider key. Note the scope: `server.py` **does** import `ai_agent.api` — and so `ai_agent.config` — at module scope for the `/api/ai` routes; the lazy call is what keeps `get_agent_service()` independent of the provider, not the import graph.
- **User-Agent (the Cloudflare 1010 fix).** `agent_service.make_transport` now sends an explicit `User-Agent` (`AGENT_HTTP_USER_AGENT`, default `trading-bot-agent/1.0`; `AgentConfig.http_user_agent`). `urllib.request`'s default `Python-urllib/3.x` is rejected at the edge by Cloudflare with `HTTP 403` / error code 1010 **before authentication** — every live turn failed until this was added. Factored into `_request_headers()` so a network-free unit test can prove the header.
- **Bounded retry on 429/503.** A multi-round vision turn re-sends the whole conversation each round, so on a low per-minute tier a turn legitimately needs the minute to roll over mid-turn; the transport retries up to `TRANSPORT_MAX_RETRIES` (4) honouring `Retry-After` / `x-ratelimit-reset-tokens` / the body hint, capped at `TRANSPORT_RETRY_CAP_S` (75s). A 429 that names a **daily** quota is *not* retried (`_is_daily_quota`) — no short wait clears it.
- **Pricing + an opt-in live test.** `qwen/qwen3.8-27b` is added to `agentic.llm.PRICES` (Groq's published `$0.80/$4.00` per 1M); the unknown-model fallback stays the default model's non-zero rate so the leash never silently stops counting. `tests/test_agent_live.py` (marker `live`, registered in a new `pytest.ini`) runs exactly one real `boot` turn through `AgentService` — real MT5 feed, real renderer, real vision client, temp state/render dirs, a non-production symbol alias, hard cost cap — and is **skipped unless `AGENT_LIVE_TEST=1`** and a provider key resolves, so `pytest -q` stays offline.

**Phase 6c — what the one real run proved, and the ceiling it hit.** The UA fix and the wiring are confirmed against the live API: with `AGENT_MODE="live"` the real client reaches Groq (HTTP 200), the real 1536×864 chart is legible to `qwen/qwen3.8-27b` (round 1 replies with a coherent `set_view` to D1 and a real tag manifest: e.g. `tag_count 28`, a live `price_range`), and the round is billed. A full boot turn, however, cannot complete on this account's Groq **on-demand** tier: it caps a *request* at **7000 input tokens** (ITPM), and every round re-sends a fixed prefix measured at ~**3839** tokens (system prompt 1177 + 11-tool schema 1478 + image 783 + briefing ~401), leaving ~3161 for tool results — while a single `render` tool result carries the tag manifest at **2314 tokens** (M15/20 bars/crt+bos) to **5936** (M15/crt+bos+fvg). The round that carries the manifest is refused with `HTTP 413` (and, once the daily cap is also spent, `HTTP 429` on TPD). The live test asserts the whole contract and, when the provider refuses a round on a documented quota, records the fact and **skips** — a half-run vision turn (real image in, a real parsed reply out, billed) is proven before the skip. The full-thesis assertion therefore runs only on a tier that fits; the wiring is proven regardless.

**Phase 6d** *(perception: the offset dial + a real split)* — the agent can now look at a past window and at two timeframes at once.

- **`offset` (the dial).** `View.offset` is an integer count of the most-recent bars to skip back, per timeframe, so the visible window is `[now-(offset+bars)*tf, now-offset*tf]`; `offset=0` is the live edge and renders **byte-identically** to before (same PNG, same `render_id`). `set_view` validates it as an integer `0 <= offset <= MAX_OFFSET` (5000, mirroring `MAX_BARS`) or refuses with `StoreError("invalid_offset", ...)`. The value threads the whole way down: `Feed.snapshot`/`bars`/`snapshots` **always** pass `offset` to the provider (including `0`), `/api/candles` and `/api/indicators` take an `offset` query param (`ge=0`, `le=MAX_OFFSET`; `bars` is bounded `MIN_BARS`..`MAX_BARS`) and hand it to `fetch_timeframe(..., start=offset)`, and `MT5DataLoader.fetch_timeframe` maps `start` onto MT5 `start_pos` (the synthesized M45 path fetches enough M15, resamples, slices off the newest `start` bars, and raises on insufficient history). Every render manifest's `window` now carries `offset`, so `window.from`/`window.to` (with `offset`) is exactly how the agent confirms which bars it is looking at; the per-turn snapshot cache is keyed by `(timeframe, bars, offset)` and dropped (`reset_snapshots()`) whenever the view changes.
- **Past-window truth (`price_basis`).** Off the live edge the endpoint labels the window `price_basis="window_end"` (at `offset=0` it is `"live"`); the field is carried on the payload, the `FeedSnapshot`, the `LookupResult` and each split pane's manifest entry. So a past `current_price`/`atr` — and every `distance_points` — is measured **inside the window**, never mistaken for the live market. `level_view`/`TagEntry` are built from the resolving snapshot/pane, so a `P2:` tag's distance is measured against pane 2's price.
- **Insufficient history is a refusal, not a crash.** An explicit-window request the feed cannot fill raises `InsufficientHistory(ValueError)` (`data.mt5_loader` for the loader; an identical, independently-defined `agentic.feed.InsufficientHistory` for the pure core, which the default live providers raise when the endpoint answers `HTTP 422`). The endpoint maps it to `422` (not the blanket `500`), and the tool surface maps it to a fixable `ToolResult(ok=False, error="insufficient_history: … reduce offset")` rather than an `internal_error`. A **persisted** bad `offset` cannot brick the loop either: the turn's first render degrades to the live edge (`offset=0`, same timeframe/families), and if that too fails the turn still completes with the failure recorded in `output["render_error"]`.
- **Real `split`.** `layout="split"` renders two stacked panes top→bottom in `view.panes` order (HTF above, LTF below), each with its own y-range, title and price markers. v1 caps this at exactly two **distinct** timeframes: `set_view(layout="split")` with `len(panes) != 2` (or two equal panes) is refused with `StoreError("invalid_split", ...)`, and an explicit `timeframe` that disagrees with `panes[0]` is refused too. `view.timeframe` is re-asserted to the primary pane `panes[0]` on **every** split mutation, so a bare `set_view(timeframe=…)` while split cannot desync it; `layout="single"` ignores `panes` (a stray `panes` cannot silently split the figure) and is otherwise unchanged. Top-level `pins` are merged into the primary pane (deduped by `level_key`).
- **Tag scheme.** The primary pane keeps its raw tags (`F1`, `F1*`); every pane after the first is prefixed with its 1-based index (`P2:F1`) so tags stay globally unique. All panes' tags are merged into `manifest["tags"]` and `result.tags` (sorted), so a `P2:*` tag resolves through the merged manifest even though `_snapshot_for_view` returns the primary (HTF) snapshot. Each `TagEntry` carries `created_at`. The manifest's top-level keys (`window`/`timeframe`/`price_range`/`tags`) always describe the primary pane; a `"panes": [{timeframe, window{from,to,bars,offset}, price_range, current_price, atr, price_basis}]` array is added **only in split mode**, so the single-mode manifest's key set is unchanged. `render_current` fetches a `(snapshot, bars)` pair per pane and resolves pins onto their own pane (falling back to the primary pane when a pin's timeframe is not a pane).
- **Lookup spans the panes.** In split mode `level_lookup` (via `_tool_level_lookup`) passes **every** pane's `snapshot` plus the manifest `panes` array, so `family`/`near_price`/`level_key` search all panes (not just the primary) and each match is measured against **its own pane's** `current_price`/`atr`/`price_basis`; a `tag` query maps `P{n}:` back to pane *n* via `_pane_index_for_tag`. The header is the primary pane's basis (or the tag's pane for a tag query).
- **Purity held.** Only the two impure files were touched outside the pure core — `data/mt5_loader.py` and `server.py`; the pure module set now imports `InsufficientHistory` only from within `agentic` (defined in `feed.py`, never imported from the loader) and the store root stays exactly 11 fields; `ai_agent/` was untouched.

**Provider — the local endpoint (`LLM_PROVIDER=local`).** The shared provider is not limited to a hosted key: `ai_agent.config.resolve_provider()` accepts `LLM_PROVIDER=local` and returns `LOCAL_BASE_URL`/`LOCAL_MODEL` (defaults `http://localhost:8080/v1` and `glm-5.3-flash-free`) with `LOCAL_API_KEY_ENV` as the key-variable name — **blank by default**, which means *keyless*: no `Authorization` header is sent and the endpoint injects its own upstream credential. Setting `LOCAL_API_KEY_ENV=OPENCODE_API_KEY` makes it **keyed** instead, for an endpoint that authenticates the *client* (a newer opencode-proxy build accepts either its own `-key`/`OPENCODE_API_KEY` or the client's `Authorization: Bearer oc_sk_…`, billing the client's key). The agent inherits the whole tuple, so `AGENT_MODE="live"` with the three `AGENT_*` connection settings blank talks to the local model with no configuration of its own. Three supporting changes make a blank key name first-class: `server._resolve_agent_connection` requires only `model` and `api_base` to be non-empty (blank and non-blank key names are both valid), and `agent_service._request_headers`/`make_transport` treat a blank name as keyless — no key is read, none is required, and no bare `"Bearer "` header is sent. `make_transport` also tolerates a full `…/v1/chat/completions` value for `api_base` (the tail is stripped, so the path is never doubled). The local provider's free models (`glm-5.3-flash-free`, `deepseek-v4.1-flash-free`) are added to `agentic.llm.PRICES` as *known free* models, `(0.0, 0.0)` — deliberate exceptions to "an unknown model is never free", which is unchanged; if the endpoint is ever pointed at a paid model, those lines must change. The legacy `/api/ai` prose flow (`agent_loop._llm_creds` / `ts_validator._creds`) is untouched and keeps its own Groq/xAI selection, so setting `LLM_PROVIDER=local` routes the **agentic agent** to the local endpoint without disturbing it. The shipped `AGENT_MODE` default is `"live"` against this provider (a zero-spend `"mock"` run is one line away); `AGENT_ENABLED` still gates autostart, so nothing watches on its own.

**Verified end-to-end against the live local endpoint (2026-10-19).** The opt-in `tests/test_agent_live.py` **passes** on this provider: one real boot turn reads the rendered XAUUSD chart, bills ~32k tokens, and writes a grounded `Thesis` (e.g. `bias="bearish"`, a storyline citing a D1 I-CHOCH/I-BOS, the freshest D1 CRT and an M15 FVG with prices, plus an invalidation and `confidence`), `cost_usd=0.0`. Reaching that took three findings, all now closed in code:

1. **A non-standard `name` field on `tool` messages.** The client sent `{"role":"tool","tool_call_id":…,"name":<tool>,"content":…}`. The OpenAI spec's `tool` message is exactly `{role, content, tool_call_id}` and some gateways reject the extra field outright — `400 [unsupported_parameter] messages[2]: "name" is not supported by this endpoint` — which killed every turn after the first tool round. `name` is now omitted (`agentic.llm`), pinned by a test.
2. **A vision model with nothing to stop it.** The strong local models are **reasoning** models: the hidden reasoning is billed against `max_tokens`, and a chart image plus a tool-calling history sends them into a reasoning runaway — `finish_reason="length"` with **empty content** (observed at 600, 2000 and 8000 tokens; the same models answer a *compact, tool-less, image-less* prompt with the exact strict-JSON object). The loop now makes one **closing call** when a turn ends with no structured object: tool-less (the evidence is folded into the briefing as a compact text digest) and image-less, with an explicit "end the turn now" instruction (`agentic.agent_loop.CLOSING_CALL`/`CLOSING_INSTRUCTION`). It fires only when there is nothing to lose — a failed or still-empty closing call leaves the turn exactly as it was — and is billed like any other round. This is what turns `ok=True, thesis empty` into a real thesis. `tests/test_agent_live.py`'s `MAX_OUTPUT_TOKENS` is 2000 for the same reason (600 truncated the reasoning models).
3. **Model choice matters, and vision is not universal.** The proxy's free catalog mixes text-only and vision models behind the same `/v1/models` list; `nemotron-3-ultra-free` and `nemotron-3.5-lightning-free` reject an `image_url` part with gateway `404 Endpoint is unavailable`, and `beam-free` with `400 invalid_request_error`. `glm-5.3-flash-free`, `mimo-v2.6-flash-free`, `nemotron-3.5-super-vl-free`, `space-bunny-free`, `longcat-2.5-preview-free` and `deepseek-v4.1-flash-free` all accept images *and* tool calls. A quick vision probe (one `image_url` part, ask what is in it) is the check before pinning a new `LOCAL_MODEL`.

The default `pytest -q` stays green and offline because the live test only runs under `AGENT_LIVE_TEST=1`.

**Invariants now enforced by tests**

- **Purity** — `agentic/*` imports only stdlib + `agentic.*`; `feed.py` is the single lazy bridge; `renderer.py` loads `matplotlib`/`PIL` inside functions. `tests/test_agentic/test_standalone.py` pins this with an AST check (`PURE_MODULES`/`BRIDGE_MODULES`).
- **Store root is exactly 11 fields** — pinned by `tests/test_agentic/test_store.py::ROOT_FIELDS`; notes are **not** a field but live in `TurnRecord.output["notes"]` and resurface in the briefing.
- **Deterministic render** — same state → byte-identical PNG and `render_id`; `rendered_at` is manifest-only; asserted across processes.
- **Turn serialisation** — one `RLock` across `boot`/`scan_once`/`run_now`; `ContextStore.save` writes a unique per-process/per-thread temp file before `os.replace`.
- **Per-thread stop event** — each scanning thread owns its own `threading.Event`; a timed-out `stop()` leaves the service *draining* and no second thread can spawn.
- **Leash pre-check** — `scan_once` checks the leash before scanning; a refusal consumes nothing.
- **Zero-spend by default; live is a one-line switch** — the shipped `AGENT_MODE` is `"live"` against the local provider, but `AGENT_MODE="mock"` still runs the whole loop against a scripted agent with zero spend and no provider at all, and `AGENT_ENABLED=False` keeps the watchdog from autostarting either way.
- **Provider inheritance is pure and lazy** — `ai_agent.config.resolve_provider()` is a pure function; `server.get_agent_service()` merges it in (via the pure `server._resolve_agent_connection()`) only when `AGENT_MODE=="live"`, so a live agent never needs a secret of its own. The three inheritance fields default to `""`. (`server.py` already imports `ai_agent.api` → `ai_agent.config` at module scope for `/api/ai`; it is the in-function call that keeps `get_agent_service()` independent of the provider, not the import graph.)
- **Live requests carry an explicit User-Agent** — `_request_headers()` always sends a non-blank UA (blank falls back to `DEFAULT_USER_AGENT`), pinned network-free in `tests/test_agent_service.py`; Cloudflare 1010 otherwise blocks the turn before auth.
- **429/503 are retried, daily quotas are not** — bounded retry honouring `Retry-After`; a `429` naming a per-day quota raises at once (`_is_daily_quota`).
- **Unknown models are never free** — `estimate_cost` falls back to the default model's non-zero rate, so the leash always counts.
- **The live test is opt-in and offline by default** — `tests/test_agent_live.py` is skipped unless `AGENT_LIVE_TEST=1` with a resolved key; on a provider quota refusal it skips rather than red-fails.
- **`offset=0` is byte-identical** — the offset dial defaults to the live edge, and a zero-offset single render matches the pre-6d output byte for byte (`render_id` and PNG); `offset` is forwarded to the provider even when `0`, and the manifest `window` always echoes it.
- **Split is exactly two distinct panes** — `set_view(layout="split")` refuses `len(panes) != 2` or two equal panes; an explicit `timeframe` disagreeing with `panes[0]` is refused; `view.timeframe` is re-asserted to the primary pane `panes[0]` on every split mutation; tags stay globally unique across panes and any pane's tag resolves through the merged manifest, with each match measured against its own pane's price basis.
- **A window past history is fixable, never fatal** — `InsufficientHistory` reaches the endpoint as `422` and the tools as `insufficient_history: … reduce offset`; a persisted bad `offset` degrades the turn's first render to the live edge, and a still-failing render is recorded as `output["render_error"]` while the turn completes.

Baseline: **485 passed, 2 skipped**; `import server` → **38 routes**. (Both shipped skips are opt-in/environment-gated: the pre-existing one and the phase-6c live test.)

## Deferred / out of scope

- Order placement and position management (Phase 7).
- Multiple concurrent symbols in one agent.
- The MQL5 `MSNR_*` world and the legacy `ai_agent/` package.
- Linkage to the parked entry-logic engine — the agent's `propose_trade` should eventually
  route through it, but not in this spec.
- The parked research proof bar. Nothing here claims an edge.

## Decision log

| Decision | Choice |
|---|---|
| Scope | Agentic system — built and wired in phases 0–6 (see "As built"); initially planned with no wiring until the indicator work landed |
| Data world | Python indicator suite (not the MQL5 objects) |
| Render path | Server-side |
| Turn driver | Deterministic watchdog + mandatory boot turn when armed |
| Input channel | Image (vision) first; exact numbers on request |
| Lock semantics | Live subscription to a level by identity, capped |
| Organisation | Explicit context store + lifecycle as prompted playbook |
| Authority | Propose-only |
| Store scope | One per symbol; one active symbol in v1 |
| Runtime switch | The store gate (`store.data.agent.enabled`) is **authoritative** for "is it on"; `AGENT_ENABLED` is only the process **autostart** switch. The registry flag in `config/modules_state.json` is written *after* `enable()`/`disable()` succeeds, so the two cannot disagree. |
| Default mode | `AGENT_MODE="live"` against the local provider (`LLM_PROVIDER=local`) — but `AGENT_ENABLED=False` gates autostart, and `AGENT_MODE="mock"` runs the full loop against a scripted agent with zero API spend. |
| Render determinism | The PNG is drawn once and `render_id = "r_" + sha256(png)[:16]`; `rendered_at` lives in the manifest only, so identical state yields a byte-identical image. |
| Notes storage | Agent notes are **not** a store field: they persist in `TurnRecord.output["notes"]` and resurface in the briefing. The store root stays exactly 11 fields. |
| Pins | A pin is a watch (`level_alive`) on level existence; the panel's `pins` are rendered from the shared subscription projection, so pins ≡ watches. |
| Wake cadence | The daemon is woken by the watchdog only, and its fires are **coalesced** (`COALESCE_WINDOW_S`) into one turn; `scan_once` never force-flushes. |
| Live provider | Live mode **inherits** the shared provider (`LLM_PROVIDER` via `ai_agent.config.resolve_provider()`); `AGENT_MODEL`/`AGENT_API_BASE`/`AGENT_API_KEY_ENV` default to `""` = inherit and can pin one field each. Hosted groq/xai return a key-variable name; `LLM_PROVIDER=local` returns the local endpoint (`LOCAL_BASE_URL`/`LOCAL_MODEL`) with `LOCAL_API_KEY_ENV` as its key-variable name — blank (keyless) unless you set it. |
| Live transport | stdlib `urllib` only, with an explicit `User-Agent` (`AGENT_HTTP_USER_AGENT`) because Cloudflare 1010 blocks urllib's default before auth; a blank key name is **keyless** (no `Authorization` header at all); bounded retry on `429`/`503` honouring `Retry-After`, but not on a per-day quota. A full `…/v1/chat/completions` `api_base` is tolerated (tail stripped). |
| Live test | `tests/test_agent_live.py` is opt-in (`AGENT_LIVE_TEST=1` + a resolved key *or* a keyless provider with a base) and skips on a provider quota refusal, so `pytest -q` stays offline; `qwen/qwen3.8-27b` priced at Groq's `$0.80/$4.00`, the local free models priced zero (so their spend assertion is exactness, not positivity). It **passes** against the local provider: one real boot turn reads the chart and writes a grounded thesis (see the provider subsection). |
| Past window | `View.offset` (integer, `0 <= offset <= MAX_OFFSET`=5000) skips that many newest bars per timeframe, so the window is `[now-(offset+bars)*tf, now-offset*tf]`; `offset=0` is the live edge and byte-identical to pre-6d. `manifest.window` always echoes `offset`, so `window.from`/`to` is the agent's ground truth for which bars it sees; off the live edge `price_basis="window_end"` (else `"live"`) marks that the window's price is not the live market. A window the feed does not hold is `InsufficientHistory` → `422` / a fixable `insufficient_history` refusal, and a persisted bad `offset` degrades the turn's first render to the live edge instead of bricking the loop. |
| Split layout | `layout="split"` renders exactly two **distinct** stacked panes (v1) top→bottom = `view.panes`; `panes[0]` is primary and `view.timeframe` stays synced to it on every split mutation (a disagreeing `timeframe` is refused). `level_lookup` searches every pane, measuring each match against its own pane's price basis. The primary pane keeps raw tags and later panes are `P{i+1}:`-prefixed into one merged, sorted manifest; the `panes` array appears in the manifest only in split mode. |

## Open questions (resolved, phase 6c)

1. **Condition vocabulary** — **Decided: keep the implemented fifteen as-is for v1.**
   `agentic.conditions.ALL_CONDITIONS` is the authoritative list — level formation and
   lifecycle (`level_forms`/`level_touched`/`level_swept`/`level_broken`/`level_filled`/
   `level_alive`), structure (`bos_forms`/`choch_forms`/`idm_swept`), price interaction
   (`price_crosses`/`price_enters_zone`/`range_expands`) and time (`session_opens`/
   `session_closes`/`time_reached`) — which is the right *shape* of things to sit and
   wait for. The one live turn did not surface a missing shape, only that the agent
   reaches for more timeframes (phase 6d now lets it *look* at two at once and at a past
   window, so that reach needs no new conditions). Revisit only after sustained live turns, and then by
   **adding** conditions to the table, never reshaping it.
2. **Timezone** — **Decided: UTC only, and nothing on the image to label.** The renderer
   draws **no x-axis tick labels** (`ax.set_xticks([])`), and every timestamp the agent
   can cite (manifest `rendered_at`, bar `event_time`, subscription deadlines, the
   briefing) is **UTC** — `Z`-suffixed in the render manifest (`renderer._iso_z`),
   `+00:00` in the briefing, subscriptions and turn records (`prompts._iso` /
   `models._dump`). There is no broker-vs-UTC ambiguity to resolve, so no axis change is
   needed.
3. **Image size and style** — **Decided: keep the 1536×864 vision-optimised default; it
   is legible.** Phase 6c made the first real model calls and the default-size chart read
   cleanly (round 1 returned a coherent perception and a sensible `set_view`, with a real
   tag manifest and a live `price_range`). Measured caveat for later: image cost is a
   flat ~**783 tokens** and is effectively **size-independent** on this provider (783 at
   320×180 through 896×504), so shrinking the image buys no token headroom. The remaining
   legibility work is style, not pixels, and is deferred until live turns accumulate.
4. **Boot turn on reconnect** — **Decided: no catch-up turn on a bare reconnect.** The
   watchdog re-evaluates every open subscription from its own `last_evaluated_at`
   (`scan` passes it into `subscriptions.evaluate` and only advances the window for the
   subscriptions it actually looked at), so an event that occurs during a feed or session
   outage still fires a **normal** turn on the next successful scan — a reconnect needs no
   special case. Process downtime is separately covered by `backfill()` on an armed
   `start()`, which reports those fires as `retroactive=True` and emits no turn. The
   runtime therefore never spends on its own outside an armed `start()` or a real fire,
   which keeps spend deliberate and operator-armed.
5. **Model choice** *(was "settled during the build", now revised)* — **Decided: live mode
   inherits the shared provider's model.** `ai_agent.config.resolve_provider()` returns the
   `LLM_PROVIDER` selection (Groq `qwen/qwen3.8-27b`, or `glm-5.3-flash-free` for
   `LLM_PROVIDER=local`, for the local `.env`), so the
   agent reuses the already-integrated model instead of pinning `gpt-4o-mini`. The pin
   remains available via a non-empty `AGENT_MODEL`. Hard requirement: the inherited model
   must be **vision-capable** (a text-only model such as `openai/gpt-oss-120b` — or, on the
   local proxy, `nemotron-3-ultra-free` — cannot see the chart, and the request is refused).

Also settled during the build (unchanged): the **Agent Panel placement** is a drawer in
the web UI (`#agentDrawer`), not a separate route.
