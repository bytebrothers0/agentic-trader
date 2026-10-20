# Universal Strategy Files — design (2026-10-20)

Make the agentic trade agent strategy-agnostic: one markdown file per strategy,
loaded into the system prompt, replacing the hard-coded CRT playbook. The user
(owner/operator) predefines their own strategy and rules without touching Python.

Scope decision (owner call): **prompt-only** — the `.md` file is the strategy;
the model interprets it with its existing tools. The deterministic CRT scorer
(`agentic/crt_strategy.py`) is **removed entirely** and its content is ported
into `strategies/default.md` as prose. A future "full engine" (a generic
deterministic rule scorer driven by structured frontmatter) is deliberately
deferred; the prose today keeps its intent so a later engine can be additive.

## 1. New pieces

### `strategies/` folder (repo root)
One file per strategy, markdown:

- `strategies/default.md` — the ported CRT playbook (from `crt_strategy.py`'s
  model + `prompts.CRT_PLAYBOOK`): top-down HTF bias (MN1/W1/D1), LTF
  confirmation (BOS -> fresh FVG/OB), execution (zone entry, ATR-padded stop,
  nearest HTF CRT boundary target, equilibrium partial), the ORIENT -> LOCATE ->
  ARM -> REACT turn order, and the deterministic math the scorer used to
  perform (expressed as instructions so the model reproduces it).
- Further `*.md` files are user strategies. `strategy_notes/` material can be
  ported verbatim anytime; nothing else references the folder.

### `agentic/strategy.py` (new, pure, stdlib-only)
```
@dataclass Strategy: name: str, text: str
def load_strategy(directory: str, name: str) -> Strategy
```
- Reads `<directory>/<name>.md`, returning `Strategy(name=name, text=...)`.
- **Loud validation**: missing directory, missing file, empty/whitespace-only
  text, and text longer than `MAX_STRATEGY_CHARS` (= 20_000 ≈ 5k tokens, so one
  strategy file can never blow every turn's token budget) all raise
  `StrategyError(ValueError)` naming what is wrong.
- Imports only stdlib; guarded by `tests/test_agentic/test_standalone.py`.
- Deterministic: same file bytes -> same text, no caching state.

### `config/settings.py`
```
STRATEGY_DIR = "strategies"     # repo-root relative (absolute also accepted)
STRATEGY_ACTIVE = "default"     # the .md (without extension) the agent runs
```

## 2. Changed pieces

| File | Change |
|------|--------|
| `agentic/prompts.py` | `CRT_PLAYBOOK` and the `crt_strategy` import are deleted. `SYSTEM_PROMPT` keeps only the strategy-agnostic contract: role (propose-only analyst), perception/truth discipline/honesty rules, condition vocabulary (still from `conditions.describe()`), output contract. `build_system_prompt(*, playbook, extra)` keeps its signature but the playbook is now *the loaded strategy text*; with no strategy the prompt still contains the contract. |
| `agentic/agent_loop.py` | `AgentLoop.__init__` gains `playbook: str = ""`; `run_turn` passes `system_prompt=prompts.build_system_prompt(playbook=self._playbook)` (was no-arg, L695). |
| `agent_service.py` | `AgentConfig` gains `strategy_dir: str = ""`/`strategy_name: str = ""` (empty -> settings fallback `STRATEGY_DIR`/`STRATEGY_ACTIVE`). `AgentService.__init__` loads the strategy **once** (loud: a bad strategy raises out of the constructor — a service cannot exist without its strategy); `status()`/`panel()` report `strategy_name`. `_loop()` passes `playbook=self._strategy.text`. |
| `agentic/crt_strategy.py` | **Deleted.** Content ported to `strategies/default.md`. |
| `agentic/__init__.py` | Re-exports: drop `HTF_BIAS_TIMEFRAMES`, `LTF_EXECUTION_TIMEFRAMES`, `REQUIRED_FAMILIES`, `OPTIONAL_FAMILIES`, `CrtPlan`, `HtfBias`, `CrtRead`, `Confirmation`; add `Strategy`, `StrategyError`, `load_strategy`. Docstring updated. |
| `agentic/models.py` | Only the `DEFAULT_FAMILIES` comment changes (no more crt_strategy reference); the six-family default list is unchanged (the strategy md may instruct other views; the agent can also `set_view`). |
| `server.py` | `GET /api/agent/crt` removed — its only dependency was `crt_strategy.analyze()`. Route count **38 -> 37**. The `/api/agent/panel` body gains `strategy_name` (pass-through of the service's). |
| `web/app.js` | No required change (panel renders the same fields). |

### Backward-compatibility notes
- The CRT **detector** (`indicators/crt_detector.py`) and the `crt` family stay:
  level finding is perception, not strategy. `strategy_notes/`, backtest replay
  (`backtest/crt_scan.py` uses the detector, never `crt_strategy`), and the
  legacy `ai_agent/` layer are untouched.
- A store's persisted view/proposals survive; the only loss is the
  `/api/agent/crt` deterministic score.

## 3. Tests

- **New** `tests/test_agentic/test_strategy.py`: loads the real default.md;
  raises on missing dir / missing file / empty text / over-cap text; keeps
  name; deterministic bytes.
- **New** `tests/test_agent_loop.py` small addition: the loop's system prompt
  embeds an injected playbook string (strategy text visible in the prompt).
- `tests/test_agent_service.py`: `AgentConfig` strategy fields fallback to
  settings; service raises on a bad strategy; `status()` carries
  `strategy_name`; the loop's prompt receives the strategy text.
- `tests/test_agentic/test_store.py`: the view-defaults pin now compares
  `DEFAULT_FAMILIES` to its literal list (no crt_strategy import).
- `tests/test_agentic/test_standalone.py`: pure-core file list swaps
  `crt_strategy.py` -> `strategy.py`; the `"crt" in families` assertion moves
  to `DEFAULT_FAMILIES`.
- `tests/test_server_offset.py`: 38 -> 37 routes.
- `tests/test_agentic/test_crt_strategy.py`: **deleted**.

## 4. Lifecycle / failure matrix

- **Setup**: strategy read once at service build; a failure refuses the build
  (the server's startup hook catches and logs, the panel simply shows no
  service — same behaviour as any other arm failure).
- **Conflict/concurrency**: prompt text frozen per process boot; changing
  `STRATEGY_ACTIVE` requires a restart. No mid-turn flapping (a turn never
  mixes strategies).
- **Scale**: the 20k-char cap bounds every turn's input; many strategy files
  cost nothing (only the active one is read).
- **Cleanup/rollback**: deleting `strategies/` or reverting `STRATEGY_ACTIVE`
  picks the change up on next boot; stores stay valid across strategies (view
  is agent-controlled state, not strategy state) — switching strategies
  mid-history is allowed by design, and a fresh boot turn re-orients the agent.
- **Security**: loader refuses path traversal (name is resolved inside the
  directory, no `..`/subdirs), no code execution — the md is only ever prompt
  text; model-authored text remains escaped in the panel.
- **Observability**: `status()`/panel show the active strategy name; `StrategyError`
  names the file and reason at startup.

## 5. Deferred: the deterministic engine (phase 2 idea)

Split a strategy file into free prose + structured frontmatter (required
families, bias family/timeframes/direction rule, confirmation chain, stop/
target rules) evaluated by a generic `strategy_engine.py` over `FeedSnapshot`s
— the role `crt_strategy.py` played, strategy-expressed. Gives exact math and
unit-testable rules for any family-graph strategy at the cost of building a
small rule vocabulary. The prose-first design above keeps this open: the md
files are additive upgrades, never migrations.
