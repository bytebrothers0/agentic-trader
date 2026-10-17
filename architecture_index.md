# Architecture Index — MSNR Trading Bot

> Living document. Update when adding/moving components. Paths relative to repo root.

## 1. Purpose

An MT5 (MetaTrader 5) trading bot for **XAUUSD** implementing the **MSNR** (Multi-Story Network Recognition) strategy. It ships as a **FastAPI web terminal** (TradingView Lightweight Charts frontend) with rule-based indicator detectors, live order execution via MT5, a backtest journal viewer, a propose-only AI agent layer (Grok + Tavily), and a separate read-only, propose-only **vision** agentic layer (`agentic/` + `agent_service.py`) that renders its own perception, watches for conditions and reasons over images — distinct from the legacy `ai_agent/`.

Language: Python 3.11 (backend), vanilla JS (frontend). Data: live MT5 OHLCV.

## 2. Entry Points

| File | Role |
|------|------|
| `start_live.py` (L1-91) | Main launcher. Self-heals interpreter (`_ensure_interpreter`, L27), `check_deps` (L54), runs `uvicorn server:app` (L87). |
| `start_live.bat` | Windows double-click wrapper. |
| `server.py` (L1-1194) | FastAPI app `app`. All REST endpoints + static `web/` mount. **Core API surface.** |
| `main.py` (L1-97) | Standalone CLI: `--test-indicators` renders an annotated chart (legacy demo, L32-87). |
| `ai_agent/agent_loop.py` (L35 `run_once`) | CLI entry for one AI scan. |
| `ai_agent/pilot/run_pilot.py` (L278 `main`) | Offline AI strategy pilot (build/analyze/score/revise phases). |
| `agent_service.py` (L1-745) | The agentic runtime/daemon (repo root). `AgentConfig`, `build_client` (a zero-spend mock `ScriptedAgent` or a live `VisionClient`), `make_transport` (the one stdlib `urllib` edge), and `AgentService` (store + watchdog thread + loop + panel/toggle surface). Imports only `agentic.*` + stdlib. Armed by `server.py`'s startup hook, or toggled by the panel. |

## 3. Core Subsystems

### 3.1 Config & Data
| File | Lines | Responsibility |
|------|-------|----------------|
| `config/settings.py` | 272 | All constants: MT5 conn, instrument specs (`INSTRUMENT_SPECS` L19), risk (`RISK_PERCENT` L42), timeframe map (`TIMEFRAME_MAP` L53, incl. synthesized M45), and one enable/param block per indicator (SR/QM/OCL/APEX/IDM/LIQ/BOS/FVG/IFVG/OB/TL/TS/CRT). `INDICATORS_ENABLED=False` master switch L109. |
| `data/mt5_loader.py` | 154 | `MT5DataLoader` (L29). Symbol resolution (`_resolve_symbol` L64), `fetch_timeframe` (L108, unix `time` column for charts), `_resample` (L142, M45 = 3×M15), `fetch_all_timeframes` (L166). Thread-locked MT5 calls. |

### 3.2 Indicator Detectors (`indicators/`)
Each exposes a `detect_all()` returning typed dataclass levels. All consume a pandas OHLCV DataFrame.

| File | Lines | Class(es) | Detects |
|------|-------|-----------|---------|
| `candle_analyzer.py` | 227 | `CandleAnalyzer` (L86), `CandleLevel` (L52), enums `LevelType`/`LevelState` | Base S/R, SBR, RBS from candle wicks/bodies; freshness state. |
| `freshness_tracker.py` | 127 | `FreshnessTracker` (L23) | Marks levels FRESH/UNFRESH/BROKEN by touch count (`update` L43); filters (`filter_fresh` L141, `is_usable` L156). |
| `ocl_detector.py` | 276 | `OCLDetector` (L106) | Open-Close Levels (HTF only). |
| `qm_detector.py` | 277 | `QMDetector` (L90) | Quasimodo (QMR/QMM/QMC) reversal patterns. |
| `apex_detector.py` | 191 | `ApexDetector` (L72) | Apex & IAB swings (HTF line-chart analysis). |
| `ts_detector.py` | 166 | `TSDetector` (L58) | Turtle Soup liquidity sweeps (wick-gated, L28 enums). |
| `crt_detector.py` | 435 | `CRTDetector` (L144), `CRTLevel` (L88), enums `CRTDirection`/`CRTVariant`/`CRTState` | **Candle Range Theory**. An anchor candle defines the range (`crh`/`crl`); a later candle **sweeps** one boundary and **closes back inside** (mandatory); the projection targets the **opposite** boundary. `CLASSIC` = strict 3-candle A-M-D; `INSIDE_BAR` = the accumulation nests inside bars inside the anchor (higher-probability read). One setup per manipulation candle — the **widest** range wins, so nested competitions collapse to the real container; a bar that sweeps both sides picks the deeper raid. Life cycle `MANIPULATED` -> `DISTRIBUTED` (target reached) / `INVALIDATED` (body close beyond the swept boundary; beats distribution on the same bar). Footer `end_kind`: `active`/`distributed`/`invalidated`. Gates: `min_range_atr`, `min_sweep_atr`, `min_close_back_atr`, `max_inside_bars`, `sweep_min`, opt-in `require_directional_anchor`. Drawn ray = the **swept** boundary; the far boundary ships as `target`. |
| `idm_detector.py` | 675 | `IDMDetector` (L105), `LuapIDMDetector` (L357), `RefCandleIDMDetector` (L529) | **Inducement, three families merged** (tagged on `IDMLevel.rule`). *BOS-anchored* (`rule="bos"`): after a structural break, the most recent minor fractal swing inside the impulse leg beyond the leg origin (a higher low / lower high). One IDM per BOS, deduped and capped per side. *Two-candle* (`rule="two_candle"`): Luap "True SMC" valid pullback (Part 1 + Part 3) — a candle takes the wick/body liquidity of the candle that ended the impulse (the previous HH/LL candle); new-extreme-without-taking **shifts** the IDM; inside bars ignored. *Reference-candle* (`rule="ref_candle"`): **every** candle is "candle 1" — upside leg -> the range LOW is the IDM, downside -> the range HIGH; a later candle must take candle 1's low then its high (mirror down) and the pullback series' extreme is the IDM. The leg is read at the **continuation** bar (the break the IDM precipitates, via `_structure_direction`), *not* at candle 1: candle 1 lies before its break, so gating there would miss every pullback that precedes a break (every CHoCH/reversal, and the first break in view). `_structure_direction` reads pivot breaks only (skips `BOSLevel.from_range` range-boundary takes, which repeat a break on the same leg). `IDMDetector(two_candle_rule=, ref_candle_rule=)` merges all three, dropping levels that repeat an earlier family's pullback (same type + bar). Resolves each IDM to `swept` (wick through, body back inside) / `broken` (body close-through) / active. |
| `liquidity_detector.py` | 211 | `LiquidityDetector` (L67) | **Liquidity pools**: equal highs (buy-side) / equal lows (sell-side) stop clusters, from fractal pivots clustered within `eq_tol_atr` x ATR and `eq_max_bars`. Needs `>= min_touches`; single swings excluded. Marks each pool `taken` on the first wick through. Capped per side. |
| `swings.py` | 73 | `find_pivots` (L41), `atr_series`, `Pivot` | Shared symmetric fractal-pivot finder + Wilder ATR for the IDM/liquidity detectors. |
| `bos_detector.py` | 248 | `BOSDetector` (L66) | BOS / CHoCH (Mxwll-style; external + internal I-BOS). Donchian-zigzag swings (a bar `L` back exceeding all `L` bars after it) + a **close** through the level; one shot per level; breaks against the trend state are CHoCH. Two levels sit armed per side: the **last swing** (the pullback pivot a CHoCH takes out) and the **range extreme** since the range last expanded (the boundary a continuation BOS clears) — a shallow pullback high can no longer demote the real range high, so e.g. a 19:30 take of the 13:15 high reports even after the 17:30 pullback CHoCH. Range takes are flagged `BOSLevel.from_range`; when both go on one bar the nearer swing reports and the range level is consumed silently. `_structure_direction` (the IDM gate) ignores range breaks so the pivot timeline the IDM rules were specified against is unchanged. |
| `fvg_detector.py` | 257 | `FVGDetector` (L103) | FVG zones (LuxAlgo port) + IFVG inversion (`detect_ifvg` L189). A zone is mitigated on the **first wick into it** (MSNR fresh rule) — tracked on both (`FVGLevel.fresh` / `IFVGLevel.fresh`); the API shows **unmitigated (fresh) zones only**. |
| `ob_detector.py` | 320 | `OBDetector` (L68) | Order Blocks + Breaker Blocks (LuxAlgo port + Luap status). |
| `trendline_detector.py` | 483 | `TLDetector` (L121), `TLLine` (L53) | **Point-to-point trendlines through 2-3 close-price apexes**, any slope, using **multi-scale apex windows** (`pivot_windows`, default `(5, 14)`, merged). Builds resistance from peak apexes / support from valley apexes (`role`), tags **channel pairs** (`channel_id`), **break-retest role flips** (`flipped`/`retest_role`), and **liquidity sweeps** (`swept`). Break = body close through; retest = far-side wick touch. Tolerances `tol_atr`/`channel_parallel_atr`/`sweep_atr`. |

### 3.3 Strategy (`strategy/`)
| File | Lines | Responsibility |
|------|-------|----------------|
| `registry.py` | 72 | Generic entry-module registry for the settings tab. `MODULES` is currently empty (no entry modules registered); `list_modules`/`set_enabled`/`is_enabled`. Persists `config/modules_state.json`. |

`strategy/__init__.py` is a namespace pkg.

### 3.4 Execution (`execution/`)
| File | Lines | Responsibility |
|------|-------|----------------|
| `risk_manager.py` | 192 | `RiskManager` (L85), `PositionPlan` (L63), `AccountMetrics` (L53), `BiasDirection` (L44). Position sizing, SL/TP planning, account metrics. |
| `order_manager.py` | 302 | `OrderManager` (L41), `LivePosition` (L27). MT5 order placement, open/pending queries, close/cancel, partial close, breakeven, obstacle-based 80% management. |

### 3.5 Visualization
| File | Lines | Responsibility |
|------|-------|----------------|
| `visualization/chart_renderer.py` | 129 | `ChartRenderer` — static mplfinance annotated charts (used by `main.py` demo). |

### 3.6 AI Agent (`ai_agent/`) — propose-only layer
| File | Lines | Responsibility |
|------|-------|----------------|
| `api.py` | 73 | FastAPI router `/api/ai/*`: proposal, scan, indicators, journal, proposals, validate-ts. Mounted in `server.py` L54-58. |
| `agent_loop.py` | 75 | `run_once` (L35) — single AI scan cycle. |
| `grok_client.py` | 96 | `ask_llm`/`ask_grok` (L53-58), sanitizes toggles. LLM proposal generation. |
| `tavily_client.py` | 37 | `fetch_news_context` (L10) — news context. |
| `msnr_snapshot.py` | 112 | `build_snapshot` (L14) — MSNR state snapshot for LLM. |
| `ts_validator.py` | 140 | `validate_signal` (L125) + `build_ts_snapshot` (L52) — LLM judges TS candidates. |
| `decision_layer.py` | 82 | `validate` (L22) — deterministic gates (RR, sanity) on AI proposals. |
| `schemas.py` | 67 | `AIProposal` (L23), `IndicatorToggle` (L16) — pydantic models. |
| `indicator_registry.py` | 94 | `load`/`save`/`apply_toggles`/`summary` — indicator toggle state (JSON). |
| `lifecycle.py` | 163 | Proposal lifecycle: `track` (L132), `build_watchlist` (L110), `find_execution_match` (L65). Persists state store. |
| `journal.py` | 25 | `log_proposal`/`recent` — proposal journal. |
| `mt5_live_state.py` | 66 | Reads/exports live MT5 state to terminals. |
| `config.py` | 31 | dotenv load + paths (`PROPOSAL_PATH`). |
| `pilot/run_pilot.py` | 259 | Offline pilot harness (phases: build/analyze/score/revise). |
| `state/*.json` | — | Runtime state: `proposals.json`, `ai_proposal.json`, `indicator_registry.json`. |

### 3.7 Agentic Agent (`agentic/`) — read-only perception, propose-only policy
Spec: `docs/specs/2026-10-17-agentic-chart-agent-design.md`. Phases 0–6 are complete (schemas + store → feed + CRT playbook → evaluator + watchdog → renderer + lookup → tools + prompts + loop → vision client → runtime + web panel); phase 7 (execution) is deferred. Nothing here places an order; `mode=propose` throughout.

The pure core (`models`/`conditions`/`store`/`crt_strategy`/`subscriptions`/`watchdog`/`lookup`/`tools`/`prompts`/`agent_loop`/`_time`/`llm`) imports only stdlib + `agentic.*`; `feed.py` is the single lazy bridge and `renderer.py` loads the vision stack inside functions. Guarded by `tests/test_agentic/test_standalone.py` (AST). `agent_service.py` at the repo root is the non-pure runtime.

| File | Lines | Responsibility |
|------|-------|----------------|
| `models.py` | 328 | Schemas (`View`/`Subscription`/`Thesis`/`Proposal`/`TurnRecord`/`Budget`/`StoreState`), the `Serde` JSON round-trip, and `make_level_key` (`family:timeframe:direction:price:born_at`). Timeframes are shape-validated (`M\d`/`MN\d`/`H\d`/`D\d`/`W\d`) — monthly is `MN1`/`MN`, **not** `M1` (which is 1-minute). `DEFAULT_FAMILIES` now includes `crt`. |
| `conditions.py` | 345 | The closed condition vocabulary the watchdog can evaluate; a watch that cannot be evaluated deterministically is rejected at the door. `level_forms` gained CRT-aware optionals `variant` (`classic`/`inside_bar`) and `min_inside_bars`, so a watch can wait specifically for an inside-bar CRT. |
| `store.py` | 617 | The durable context store: atomic JSON persistence, caps (8 pins / 20 subscriptions), TTLs (watch 24h/7d, pin 72h/14d), the turn leash (60s / 6 per hour / 60 per day / $5 per day) and budget accounting. Holds **intent + metadata only** — never detector output. `save` writes a unique per-process/per-thread temp file, then `os.replace` (with a Windows retry). |
| `feed.py` | 602 | **Phase 1 — the single sanctioned bridge to the running system, read-only.** `Feed(provider)` calls the indicator layer and normalises the `/api/indicators` payload into `LevelRecord`s with stable `level_key`s and a `LevelStatus` (`end_kind` first, then `state`). Family aliases (`liq`→`liquidity`), zone bands (`box_*`/`range_*`), CRT extras (`variant`/`inside_bars`/`target`) and ATR are carried through. `default_provider()` **lazily** imports `server.get_indicators`, so importing the package stays cheap (the state-check test asserts the laziness). Phase 2a added OHLC `Bars` via `snapshot`/`bars`. |
| `crt_strategy.py` | 483 | **The top-down CRT playbook** the agent runs: HTF bias from D1/W1/MN1 CRT (`HTF_BIAS_TIMEFRAMES`, highest live CRT wins), LTF confirmation (`bos` → `fvg`/`ob` → raid, bias-direction matched), and a propose-only `CrtPlan` — entry at the aligned zone, stop padded by ATR (else 5% of the HTF range), target the **nearest** HTF CRT boundary beyond entry (draw-on-liquidity ladder), partial at equilibrium, R:R and provenance (CRT + confirmation + zone level keys). `analyze(feed, symbol, ltf_timeframe=…)` is the whole read. Depends only on `feed` records. |
| `subscriptions.py` | 598 | **Phase 2a — the deterministic, edge-triggered condition evaluator.** Answers one question: did this subscription's condition *newly* occur in `(last_evaluated_at, now]`? No model, no randomness. `evaluate(sub, snapshot, bars, now=, last_evaluated_at=)` and `event_time` (the fire instant per condition). Sessions are fixed UTC windows; `price_crosses` needs strictly opposite closes; `range_expands` uses the UTC-day range vs `ATR`/`ADR`. Never mutates the sub or the snapshot. |
| `watchdog.py` | 420 | **Phase 2b — the LLM-free, render-free loop that makes the agent self-starting.** Drives the evaluator over the store's open subscriptions, retires fires/expiries, and coalesces a burst into one turn (`COALESCE_WINDOW_S=45`, `PRICE_CHECK_S=15`). `scan` emits a `fire` turn once the window elapses and applies the repeating-watch cooldown; `backfill` recovers downtime fires (`retroactive=True`) and emits no turn; `flush` force-emits for `request`/`boot`. Clock injected, never read; expiry is not a fire unless `wake_on_expiry`. |
| `renderer.py` | 560 | **Phase 3 — the deterministic server-side PNG render + tag manifest.** Vision-optimised style (default 1536×864), every drawn level tagged (`F1`, `F1*` when pinned). Same store + feed → byte-identical PNG: no randomness, no wall-clock in the drawing (`rendered_at` is manifest-only), canonical manifest order, PNG metadata stripped; `render_id = "r_" + sha256(png)[:16]`. `matplotlib`/`PIL` imported lazily inside functions. |
| `lookup.py` | 298 | **Phase 3 — the numeric ground truth for anything the agent saw.** `level_view` is the single canonical ~15-number projection of a `LevelRecord` (price/band, family/TF/direction, status, `live`/`pinned` origin, signed distance in points and ATR); both the lookup and the manifest's `TagEntry` build from it, so they cannot drift. `level_lookup` resolves by `tag`, `level_key`, `family`(+`timeframe`) or `near_price`(+`radius`). |
| `tools.py` | 628 | **Phase 4 — the tool surface: eleven tools, no order tool.** `set_view`/`render`/`level_lookup`/`add_pin`/`release_pin`/`add_watch`/`cancel_watch`/`list_subscriptions`/`set_thesis`/`add_note`/`propose_trade`. `ToolRegistry.execute` never raises — a refused mutation returns `ToolResult(ok=False, error=…)` with the store's own reason — and it owns the `MAX_RENDERS_PER_TURN` budget (the initial perception render is render #1). |
| `prompts.py` | 330 | **Phase 4 — the system prompt (policy) and the per-turn briefing (memory).** The prompt carries the top-down CRT playbook, the condition vocabulary (described from `conditions.describe()`) and the perception/truth/discipline rules; the briefing is rebuilt fresh from the store each turn (thesis, open subscriptions with countdowns, budget, last conclusion, recent notes read back from the turn log, fires/expiries). No wall clock, no repo imports. |
| `agent_loop.py` | 575 | **Phase 4 — one turn: leash → gate → briefing + render → LLM + tools → output → persist.** `AgentLoop.run_turn`/`wake`/`boot`; `MAX_TOOL_ROUNDS=4`. `ScriptedAgent` replays canned replies for zero-spend tests; a transport error refuses the turn (`client_error`/`bad_response`) and bills any spend already incurred; truncation is surfaced, never silent. |
| `_time.py` | 51 | **Phase 4 — the shared one-liners** the core had copied seven times: `as_aware` (UTC-normalise a naive datetime), `seconds_remaining`, and `new_id` (`prefix_ab12cd34`). Private, pure, dependency-free; reads no clock. |
| `llm.py` | 548 | **Phase 5 — the OpenAI-compatible vision client over an injected `Transport`.** Pure: `build_messages` assembles the system prompt + briefing text + image data-URI + any prior tool calls; `parse_reply` tolerantly reads the reply back (malformed tool args → `{}`, never an exception); only a message-less reply raises. `DEFAULT_MODEL='gpt-4o-mini'`; `PRICES` is a configurable USD-per-1M estimate table for leash accounting, not billing. The network call is supplied by phase 6. |
| `agent_service.py` (repo root) | 745 | **Phase 6a — the runtime entry point (non-pure: stdlib + `agentic` at module level only).** `AgentService` holds one symbol's store, watchdog and loop; one `RLock` serialises `boot`/`scan_once`/`run_now`. `build_client` returns a mock `ScriptedAgent` (`AGENT_MODE="mock"`) or a live `VisionClient`; `make_transport` is the only network edge (stdlib `urllib`). `start`/`stop`/`enable`/`disable`/`pause`/`resume`/`run_now`; `panel()`/`turns()`/`render_path()` back the HTTP surface. |
| `tests/test_agentic/` | — | `test_store.py`, `test_conditions.py`, `test_standalone.py` (AST guard: the pure core imports nothing from the repo; `feed.py` is the one lazy bridge; `renderer.py` loads the vision stack lazily), `test_feed.py`, `test_crt_strategy.py`, `test_subscriptions.py`, `test_watchdog.py`, `test_renderer.py` (incl. a cross-process image-hash check), `test_lookup.py`, `test_agent_loop.py`, `test_llm.py`. Helpers: `_fixtures.py`, `_render_probe.py`. |
| `tests/test_agent_service.py` | 557 | The runtime, exercised in-memory: fake feed + renderer + clock and the zero-spend `ScriptedAgent`; also asserts `agent_service` imports without `server`/MT5/`config.settings`. |

### 3.8 Frontend (`web/`)
| File | Lines | Responsibility |
|------|-------|----------------|
| `index.html` | 576 | TradingView terminal shell. Carries the Agent Panel drawer (`#agentDrawer` + `#agentBackdrop`) and its top-nav bot button (`#btnAgent`); cache busters are `style.css?v=16` / `app.js?v=24`. |
| `app.js` | 1906 | Frontend engine: chart, indicator levels overlay, levels table, live positions, and the Agent Panel drawer. Mirrors settings switches (L8-21, incl. `CRT_ENABLED`). One IDM colour per family: gold = BOS-anchored `IDM`, amber = `IDM·2C`, lime = `IDM·RC` (badges `badge-idm`/`badge-idm-2c`/`badge-idm-rc`). CRT: green = bullish (sell-side raid), red = bearish (tags `crt-bull`/`crt-bear`), dashed = the inside-bar variant, distributed setups fade, invalidated ones go gray dotted. Ray budget is **per category** (`MAX_RAYS_PER_CATEGORY=80`), not one global recency cap, so a busy layer (SR/TS/QM) cannot starve a small one. The indicators request drops `undefined` params: mode pills assign a *partial* indicator set, and the literal `"undefined"` made FastAPI reject the whole request (422) so the chart silently showed nothing. The Agent Panel drawer reads `GET /api/agent/panel` (thesis, open subscriptions with countdowns, the dedicated `pins` projection, view, proposals, budget, recent turns, last render), drives the enable toggle + pause/resume, and sends chat via `POST /api/agent/run-now?message=`; it polls only while open and escapes all model-authored text. |
| `style.css` | 1500 | Styling (incl. the `.agent-drawer` panel and chat styles). |
| `backtest.html` / `backtest.js` | 101 / 871 | Backtest journal viewer (reads `/api/backtest/*`). |

### 3.9 Tests (`tests/`)
`test_indicators/`: `test_bos.py`, `test_fvg.py`, `test_crt.py` (CRT: classic/inside-bar, dedupe, both-side bars, life cycle, gates, caps), `test_idm.py` (BOS family, pinned via `two_candle_rule=False` + `ref_candle_rule=False`), `test_luap_idm.py` (two-candle family + merge/dedupe), `test_ref_candle_idm.py` (reference-candle family + structure gate), `test_liquidity.py`, `test_ob.py`, `test_trendline.py`, `test_ts.py`, `test_indicators_all.py`. Run with pytest.

### 3.10 Docs & Reference (non-code)
- `strategy_notes/` — strategy playbooks (phoenix_mnsr, ems mnsr, apa, abax mnsr, advance mnsr1) as markdown + subtitle transcripts.
- `mql5/` — MT5-side resource mirror (Experts/Indicators) and a nested `.agents/` skill copy; plan `.txt` files.
- `temp/xauusd-ai-trading-signal/` — older standalone prototype (separate engines, `live_scanner.py`, dispatchers, README).
- `mql5/Experts/advace mnsr/` — duplicates of the strategy notes.
- Root `New Text Document*.txt`, `visualizations/`, `backtest/` (empty at index time; server reads journal CSVs from here), `logs/` (gitignored).

## 4. HTTP API Surface (`server.py`)

Candles/indicators (L146-718):
- `GET /api/symbols` — broker symbols, priority-sorted.
- `GET /api/candles` — OHLCV for TradingView.
- `GET /api/indicators` — computes ALL detectors, returns unified `levels[]` payload. Params gate each category (sr/ocl/qm/apex/ts/idm/bos/fvg/ifvg/ob/tl/liq/crt). The payload also carries `atr` (ATR-14, Wilder) alongside `current_price`, for the agent's stops/sizing and level lookups.

Settings: `GET /api/settings/modules`, `POST /api/settings/modules/{id}?enabled=`.

Account/trading (L884-1034): `GET /api/account`, `GET /api/positions`, `POST /api/orders/place|close|cancel|partial-close|breakeven|manage-obstacles`.

Backtest (L1035-1194): `GET /api/backtest/trades`, `GET /api/backtest/journals`, `GET /backtest` (viewer HTML), `GET /` (index).

AI (mounted router): `/api/ai/proposal|scan|indicators|journal|proposals|validate-ts`.

Agent (read-only perception; the runtime endpoints are backed by `agent_service.py`):
- `GET /api/agent/crt?symbol&ltf&bars` — the top-down CRT read (HTF bias + LTF confirmation + propose-only plan) through `agentic.feed` → `agentic.crt_strategy`. Read-only, no store mutation, no orders.
- `GET /api/agent/panel` — the Agent Panel's read of the store (`AgentService.panel()`) plus `service.status()`; the drawer's whole data source.
- `GET /api/agent/turns?limit=` — the append-only turn log, newest first.
- `GET /api/agent/render?render_id=` — serves a rendered PNG by id; 404 for an unknown or unsafe id (path containment checked).
- `POST /api/agent/enable` / `POST /api/agent/disable` — arm/disarm the runtime gate (the kill switch); syncs the `strategy/registry.py` entry.
- `POST /api/agent/pause` / `POST /api/agent/resume` — stop/allow waking, keep state.
- `POST /api/agent/run-now?message=` — start a `request` turn regardless of the gate (a human asked).

A FastAPI `startup` hook arms the service when `AGENT_ENABLED` is true (swallowing errors); `POST /api/settings/modules/agent` special-cases the store gate as authoritative (the runtime flips first, the registry flag only after it succeeds). `import server` → 38 routes.

## 5. Key Data Flow

```
MT5 terminal
  → MT5DataLoader.fetch_timeframe(tf, count)   [data/mt5_loader.py]
      → pandas OHLCV (unix 'time' col)
  → Detectors detect_all()                      [indicators/*]
  → server /api/indicators aggregates levels[]
  → web/app.js renders → TradingView chart
  → POST /api/orders/place → OrderManager → MT5
AI layer (propose-only):
  ai_agent/agent_loop.run_once → snapshot + news + LLM → decision_layer.validate → proposal JSON
Agentic layer (read-only perception, propose-only policy, phases 0–6):
  GET /api/agent/crt → agentic.feed.Feed (lazy server.get_indicators) → normalised levels
  → crt_strategy.analyze: HTF bias (D1/W1/MN1 CRT) → LTF confirmation → CrtPlan
  Daemon: server startup hook (AGENT_ENABLED) → AgentService.start → watchdog thread
  → watchdog.scan (coalesced fires, COALESCE_WINDOW_S) → agent_loop.run_turn
  → tool phase (store mutations, optional re-render) → llm vision turn
  → store save + turn log → GET /api/agent/panel → web drawer (#agentDrawer)
```

## 6. Conventions & Notes
- Enable/disable every indicator via `config/settings.py` flags; `INDICATORS_ENABLED=False` disables the legacy unified stack, but per-indicator flags (SR/QM/BOS/…) run independently.
- Detectors are stateless and take a DataFrame in the constructor; `detect_all()` is the uniform entry.
- `web/app.js` duplicates the switches at top (L8-21) — keep in sync with `settings.py`.
- `backtest/` journals (CSV) feed `/api/backtest/*`; label map in `server.py` `_journal_label` (L828).
- Inducement ships **three families at once**: BOS-anchored, the Luap "True SMC" two-candle valid-pullback IDMs (`IDM_TWO_CANDLE_RULE=True`), and the Luap reference-candle ("candle 1") IDMs (`IDM_REF_CANDLE_RULE=True`, bounded by `IDM_REF_MAX_BARS`). All are the `idm` category and told apart by `IDMLevel.rule` / the gold-amber-lime tags (`IDM` / `IDM·2C` / `IDM·RC`). Each family caps **only its swept/broken history** to `IDM_MAX_PER_SIDE` per side — live IDMs are always kept (bounded by `MAX_LIVE_PER_SIDE=30`), because an untaken inducement is the only one still a target.
- Interpreter quirk on Windows: `start_live.py` re-execs into Python311.
- CRT (`CRT_*` in `config/settings.py`) keeps **one setup per manipulation candle**, resolved to the **widest** range (the outermost accumulation container). The ATR gates (`min_range_atr`/`min_sweep_atr`) are off by default — every candle is a candidate anchor and a sweep counts on price alone — and the per-side caps (`CRT_MAX_PER_SIDE` history / `CRT_MAX_LIVE_PER_SIDE` live) bound chart volume instead. Re-enable by setting the ATR floors >0 if micro-ranges ever need gating. `CRT_REQUIRE_DIRECTIONAL_ANCHOR` is off because sources disagree on the anchor's required colour — the sweep plus close-back-inside is the definition.
- Trendlines are built as lines **through close-price apexes** using **multi-scale apex windows** (`TL_PIVOT_WINDOWS`, default `(5, 14)`, merged — small windows catch local channel swings, the large one the major swings) plus `TL_TOL_ATR`, `TL_CHANNEL_PARALLEL_ATR`, `TL_SWEEP_ATR` in `config/settings.py`, passed to `TLDetector`. `TLLine.slope` is signed and `value_at()` projects it; `role` = support/resistance by anchor set; lines carry `channel_id`, `flipped`/`retest_role` and `swept`. The old mid-line channel (`TLChannel`) is removed. `slope_mult`/`body_pivots` are deprecated no-ops.
- The agentic layer (`agentic/`) is **read-only and propose-only**. `agentic/feed.py` is the only module allowed to touch the running system, and only **lazily** — importing `agentic` never pulls FastAPI/MT5. The pure core (`models`/`conditions`/`store`/`crt_strategy`/`subscriptions`/`watchdog`/`lookup`/`tools`/`prompts`/`agent_loop`/`_time`/`llm`) imports nothing from the repo and no network library; `tests/test_agentic/test_standalone.py` enforces this with an AST check, that `feed.py` stays a lazy bridge, and that `renderer.py` loads `matplotlib`/`PIL` inside functions. `agent_service.py` (repo root) is the non-pure runtime, but imports only stdlib + `agentic` at module level. Its CRT playbook is **top-down**: bias from the D1/W1/MN1 CRT, confirmation/execution on a lower timeframe, target the **nearest** HTF CRT boundary. It never caches detector output (levels are recomputed each read) and holds no order tool.
- The agentic **store root is pinned at exactly eleven fields** (`tests/test_agentic/test_store.py::ROOT_FIELDS`); agent **notes are not a field** — they persist in `TurnRecord.output["notes"]` and resurface in the briefing. One store per symbol, one active symbol in v1.
- Two agent switches, not one: `config.settings.AGENT_ENABLED` (default `False`) is only the **autostart** switch; the store gate (`store.data.agent.enabled`, per symbol) is **authoritative** at runtime. `POST /api/agent/enable|disable` (and `/api/settings/modules/agent`) move the store gate first, then sync `config/modules_state.json`. `AGENT_MODE="mock"` is the default — the full loop runs against a scripted agent with **zero spend**; `"live"` uses `AGENT_MODEL` over an injected stdlib transport (`AGENT_API_KEY_ENV`). `AGENT_STATE_DIR`/`AGENT_RENDER_DIR` empty → the in-package `agentic/state`/`agentic/renders` defaults (both gitignored).
- The agentic render is **deterministic**: the PNG is drawn once and `render_id = "r_" + sha256(png)[:16]`; `rendered_at` lives in the manifest only, so identical state yields a byte-identical image and filename (asserted across processes). A turn holds one `RLock` across `boot`/`scan_once`/`run_now`.
