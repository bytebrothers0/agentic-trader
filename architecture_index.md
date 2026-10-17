# Architecture Index — MSNR Trading Bot

> Living document. Update when adding/moving components. Paths relative to repo root.

## 1. Purpose

An MT5 (MetaTrader 5) trading bot for **XAUUSD** implementing the **MSNR** (Multi-Story Network Recognition) / Alchemist X-Factor strategy. It ships as a **FastAPI web terminal** (TradingView Lightweight Charts frontend) with rule-based indicator detectors, an "Alchemist" top-down entry engine, live order execution via MT5, a backtest journal viewer, and a propose-only AI agent layer (Grok + Tavily).

Language: Python 3.11 (backend), vanilla JS (frontend). Data: live MT5 OHLCV.

## 2. Entry Points

| File | Role |
|------|------|
| `start_live.py` (L1-91) | Main launcher. Self-heals interpreter (`_ensure_interpreter`, L27), `check_deps` (L54), runs `uvicorn server:app` (L87). |
| `start_live.bat` | Windows double-click wrapper. |
| `server.py` (L1-986) | FastAPI app `app`. All REST endpoints + static `web/` mount. **Core API surface.** |
| `main.py` (L1-97) | Standalone CLI: `--test-indicators` renders an annotated chart (legacy demo, L32-87). |
| `ai_agent/agent_loop.py` (L35 `run_once`) | CLI entry for one AI scan. |
| `ai_agent/pilot/run_pilot.py` (L278 `main`) | Offline AI strategy pilot (build/analyze/score/revise phases). |

## 3. Core Subsystems

### 3.1 Config & Data
| File | Lines | Responsibility |
|------|-------|----------------|
| `config/settings.py` | 222 | All constants: MT5 conn, instrument specs (`INSTRUMENT_SPECS` L19), risk (`RISK_PERCENT` L42), timeframe map (`TIMEFRAME_MAP` L53, incl. synthesized M45), and one enable/param block per indicator (SR/QM/OCL/APEX/IDM/BOS/FVG/IFVG/OB/TL/TS/XF). `INDICATORS_ENABLED=False` master switch L109. Alchemist params L118-130. |
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
| `idm_detector.py` | 207 | `IDMDetector` (L65) | Inducement / pre-zone liquidity. |
| `bos_detector.py` | 167 | `BOSDetector` (L58) | BOS / CHoCH (Mxwll-style; external + internal I-BOS). |
| `fvg_detector.py` | 257 | `FVGDetector` (L103) | FVG zones (LuxAlgo port) + IFVG inversion (`detect_ifvg` L189). A zone is mitigated on the **first wick into it** (MSNR fresh rule) — tracked on both (`FVGLevel.fresh` / `IFVGLevel.fresh`); the API shows **unmitigated (fresh) zones only**. |
| `ob_detector.py` | 320 | `OBDetector` (L68) | Order Blocks + Breaker Blocks (LuxAlgo port + Luap status). |
| `trendline_detector.py` | 483 | `TLDetector` (L121), `TLLine` (L53) | **Point-to-point trendlines through 2-3 close-price apexes**, any slope, using **multi-scale apex windows** (`pivot_windows`, default `(5, 14)`, merged). Builds resistance from peak apexes / support from valley apexes (`role`), tags **channel pairs** (`channel_id`), **break-retest role flips** (`flipped`/`retest_role`), and **liquidity sweeps** (`swept`). Break = body close through; retest = far-side wick touch. Tolerances `tol_atr`/`channel_parallel_atr`/`sweep_atr`. |
| `xfactor_detector.py` | 400 | `XDetector` (L201), `detect_storyline` (L393), `detect_engulfing_zones` (L153), `XLevel` (L71) | **Key strategy piece**: trendline × SNR confluences (X-Factor), engulfing zones, HTF storyline chains. |

### 3.3 Strategy (`strategy/`)
| File | Lines | Responsibility |
|------|-------|----------------|
| `alchemist.py` | 372 | `AlchemistEngine` (L83). Full top-down stack: `_compute` (L125) → `_storylines` (L186, MN1→W1/W1→D1/D1→H4) → `_resolve_bias` (L232, storyline then PD+BOS fallback) → `_trigger` (L266, M15 XDetector tradable) → `_refine` (L298, M5 IDM/doji) → `_signal` (L326, 70/30 split, SL floor, TP pool, RR gate, sizing). 20s cache (L46). `signals()` L121. |
| `registry.py` | 69 | Entry-module registry for settings tab. `MODULES` (L21, only `alchemist_x`), `list_modules`/`set_enabled`/`is_enabled`. Persists `config/modules_state.json`. |

`strategy/__init__.py` is empty (namespace pkg).

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

### 3.7 Frontend (`web/`)
| File | Lines | Responsibility |
|------|-------|----------------|
| `index.html` | 470 | TradingView terminal shell. |
| `app.js` | 1734 | Frontend engine: chart, levels, strategy deck, order UI. Mirrors settings switches (L10-22). |
| `style.css` | 1325 | Styling. |
| `backtest.html` / `backtest.js` | 99 / 820 | Backtest journal viewer (reads `/api/backtest/*`). |

### 3.8 Tests (`tests/`)
`test_indicators/`: `test_bos.py`, `test_fvg.py`, `test_idm.py`, `test_ob.py`, `test_trendline.py`, `test_ts.py`, `test_xfactor.py`, `test_indicators_all.py`. `test_strategy/test_alchemist.py`. Run with pytest.

### 3.9 Docs & Reference (non-code)
- `strategy_notes/` — strategy playbooks (phoenix_mnsr, ems mnsr, apa, abax mnsr, advance mnsr1) as markdown + subtitle transcripts.
- `mql5/` — MT5-side resource mirror (Experts/Indicators) and a nested `.agents/` skill copy; plan `.txt` files.
- `temp/xauusd-ai-trading-signal/` — older standalone prototype (separate engines, `live_scanner.py`, dispatchers, README).
- `mql5/Experts/advace mnsr/` — duplicates of the strategy notes.
- Root `New Text Document*.txt`, `visualizations/`, `backtest/` (empty at index time; server reads journal CSVs from here), `logs/` (gitignored).

## 4. HTTP API Surface (`server.py`)

Candles/indicators (L79-579):
- `GET /api/symbols` — broker symbols, priority-sorted.
- `GET /api/candles` — OHLCV for TradingView.
- `GET /api/indicators` — computes ALL detectors, returns unified `levels[]` payload. Params gate each category (sr/ocl/qm/apex/ts/idm/bos/fvg/ifvg/ob/tl/xf).

Strategy (L582-654): `GET /api/strategy` (Alchemist payload), `GET /api/signals` (Alchemist entries).

Settings (L656-673): `GET /api/settings/modules`, `POST /api/settings/modules/{id}?enabled=`.

Account/trading (L676-824): `GET /api/account`, `GET /api/positions`, `POST /api/orders/place|close|cancel|partial-close|breakeven|manage-obstacles`.

Backtest (L827-972): `GET /api/backtest/trades`, `GET /api/backtest/journals`, `GET /backtest` (viewer HTML), `GET /` (index).

AI (mounted router): `/api/ai/proposal|scan|indicators|journal|proposals|validate-ts`.

## 5. Key Data Flow

```
MT5 terminal
  → MT5DataLoader.fetch_timeframe(tf, count)   [data/mt5_loader.py]
      → pandas OHLCV (unix 'time' col)
  → Detectors detect_all()                      [indicators/*]
  → server /api/indicators aggregates levels[]
  → web/app.js renders → TradingView chart
AlchemistEngine.analyze()                        [strategy/alchemist.py]
  → /api/strategy + /api/signals → app.js strategy deck
  → POST /api/orders/place → OrderManager → MT5
AI layer (propose-only):
  ai_agent/agent_loop.run_once → snapshot + news + LLM → decision_layer.validate → proposal JSON
```

## 6. Conventions & Notes
- Enable/disable every indicator via `config/settings.py` flags; `INDICATORS_ENABLED=False` disables the legacy unified stack, but per-indicator flags (SR/QM/BOS/…) run independently.
- Detectors are stateless and take a DataFrame in the constructor; `detect_all()` is the uniform entry.
- `web/app.js` duplicates the switches at top (L10-22) — keep in sync with `settings.py`.
- `backtest/` journals (CSV) feed `/api/backtest/*`; label map in `server.py` `_journal_label` (L886).
- Interpreter quirk on Windows: `start_live.py` re-execs into Python311.
- Trendlines are built as lines **through close-price apexes** using **multi-scale apex windows** (`TL_PIVOT_WINDOWS`, default `(5, 14)`, merged — small windows catch local channel swings, the large one the major swings) plus `TL_TOL_ATR`, `TL_CHANNEL_PARALLEL_ATR`, `TL_SWEEP_ATR` in `config/settings.py`, passed to `TLDetector`. `TLLine.slope` is signed and `value_at()` projects it; `role` = support/resistance by anchor set; lines carry `channel_id`, `flipped`/`retest_role` and `swept`. The old mid-line channel (`TLChannel`) is removed. `slope_mult`/`body_pivots` are deprecated no-ops.
