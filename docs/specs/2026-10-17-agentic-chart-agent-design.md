# Agentic Chart Agent — Self-Directed Perception, Pins and Watches

Date: 2026-10-17
Status: Proposed (awaiting review; no code written)
Module: `agentic/` (new, standalone, **unwired** — touches no existing file)

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
  "layout": "single",
  "panes": [],
  "show_tags": true,
  "annotations": []
}
```

`layout` ∈ `single | split`; `panes` is the multi-timeframe list when `split` (e.g.
`["H2","M15"]`). `bars` is the lookback window.

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
| `set_view` | symbol, timeframe, chart type, families, bars, layout/panes, tags, annotations |
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

## Integration points (deferred — not touched until after the build)

| Where | What will change |
|---|---|
| `agentic/feed.py` | read-only adapter over `indicators/*` (or `server.get_indicators`) producing the level payload + statuses |
| `server.py` | mount `/api/agent/*` (panel state, chat, enable/pause, kill switch) in the existing try/except style |
| `web/` | Agent Panel + settings toggle; cache-buster bump in `index.html` |
| `config/settings.py` | an `AGENT_*` block |
| `strategy/registry.py` | register the agent module id for the settings tab |
| `ai_agent/` | untouched. Its broken imports (`strategy.storyline_engine`, `strategy.entry_engine`) and the MQL5 MSNR world are legacy; retiring it is a separate decision. |

**Phases 0–4 require no change to any existing file.**

## Build order

| Phase | Deliverable | Acceptance |
|---|---|---|
| **0** | `models.py` + `store.py`: schemas, atomic persistence, caps/expiry enforcement, budget accounting | round-trip a store; caps and expiries reject with a reason; no LLM, no repo changes |
| **1** | `feed.py`: read-only level adapter, level-key identity, status mapping from the freshness tracker | keys are stable across recomputation; a swept level reports `swept`, not `live` |
| **2** | `conditions.py` + `subscriptions.py` + `watchdog.py`: the vocabulary, edge-triggered evaluation, dedupe, coalescing, backfill | every vocabulary entry tested against a fake feed; backfill reports a retroactive fire across simulated downtime |
| **3** | `renderer.py`: store → PNG + manifest, tags, vision-optimised style | byte-identical render for identical state (image hash test); manifest resolves every tag |
| **4** | `agent_loop.py` with a **scripted mock agent** | full turn end-to-end with zero API spend; turn log complete; leash enforced |
| **5** | real vision model: prompt, tool-calling, structured output | a boot turn produces a thesis, a view change and at least one armed watch |
| **6** | Agent Panel + settings toggle + kill switch | panel reflects the store; disable stops all waking |
| **7** | *(deferred)* execution | out of scope for this spec |

Phases 0–2 are pure logic and can be built and tested **today**, in parallel with any
indicator work, because they depend on nothing outside themselves.

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
| Scope | Agentic system; plan only for now, no wiring until the pending indicator work lands |
| Data world | Python indicator suite (not the MQL5 objects) |
| Render path | Server-side |
| Turn driver | Deterministic watchdog + mandatory boot turn when armed |
| Input channel | Image (vision) first; exact numbers on request |
| Lock semantics | Live subscription to a level by identity, capped |
| Organisation | Explicit context store + lifecycle as prompted playbook |
| Authority | Propose-only |
| Store scope | One per symbol; one active symbol in v1 |

## Open questions

1. **Condition vocabulary** — is the table the right *shape* of things to wait for? What
   would you sit and wait for that it misses?
2. **Timezone** — label the axis in UTC or broker time? Levels carry bar timestamps, so the
   render must be unambiguous about which.
3. **Image size and style** — the proposed 1536×864 vision-optimised style needs a real
   legibility check against the chosen model before Phase 3 is frozen.
4. **Model choice** — which vision model, and does it support the tool-calling shape needed
   in Phase 5?
5. **Boot turn on reconnect** — should a reconnect without a process restart also schedule
   a catch-up turn?
6. **Agent Panel placement** — a new panel beside the chart, or a separate route?
