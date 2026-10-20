# Universal Strategy Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace the hard-coded CRT playbook with per-strategy markdown files (`strategies/*.md`) loaded into the agent's system prompt; delete `agentic/crt_strategy.py` (content ported to prose).

**Architecture:** `agentic/strategy.py` (pure loader) + `strategies/default.md` (ported CRT model) + `STRATEGY_DIR`/`STRATEGY_ACTIVE` settings; `AgentService` loads the strategy once (loud), `AgentLoop` embeds it via `build_system_prompt(playbook=...)`. CRT detection stays; only the CRT *strategy scorer* and `/api/agent/crt` die.

**Resilience & Lifecycle Strategy:** Strategy is read once at service build; a missing/empty/oversized file refuses the build loudly (StrategyError) — same failure surface as other arm errors (server startup hook swallows/logs). Prompt frozen per boot = zero mid-turn flapping. 20k-char cap bounds tokens. Loader refuses traversal. Stores stay valid across strategy switches.

Spec: `docs/specs/2026-10-20-universal-strategy-files-design.md`

---

### Task 1: `strategies/default.md` — port the CRT playbook to prose

**Files:**
- Create: `strategies/default.md`

- [x] Write the file: top-down CRT model (from `crt_strategy.py` docstring + `derive_htf_bias`/`find_confirmation`/`build_plan` semantics + `CRT_PLAYBOOK`), all as instructions in the same voice `prompts.CRT_PLAYBOOK` used: HTF bias ladder (MN1/W1/D1, highest live CRT wins, newest fallback), LTF confirmation priority (BOS in bias direction → fresh FVG/OB zone → raid/TS), entry zone selection (nearest live FVG/OB on the bias side, discount longs / premium shorts), stop math (0.25×ATR beyond zone boundary, else 5% of the HTF range), target (nearest HTF CRT boundary beyond entry from same-direction CRTs, else the bias CRT's own far boundary), partial at equilibrium, ORIENT→LOCATE→ARM→REACT turn order, decision gates (structure shift is timing, zone is location).
- [x] Verify it reads as a self-contained strategy a fresh agent could follow.

### Task 2: `agentic/strategy.py` + tests (pure loader)

**Files:**
- Create: `agentic/strategy.py`
- Test: `tests/test_agentic/test_strategy.py`

- [x] Write failing tests: loads `strategies/default.md` (name="default", text non-empty); missing dir raises; missing file raises; empty/whitespace text raises; text over `MAX_STRATEGY_CHARS` raises; reason names file + problem; pure imports (stdlib only — covered by test_standalone update in Task 7).
- [x] Implement `Strategy` dataclass, `StrategyError(ValueError)`, `MAX_STRATEGY_CHARS = 20_000`, `load_strategy(directory, name)`:
  - `name` validated (non-empty, no `..`/`/`/`\`, no extension beyond optional `.md` — strip it).
  - Path resolved inside directory (containment); must exist; read utf-8; strip whitespace-only refusal; cap check.
- [x] Run tests green.
- [x] Commit.

### Task 3: settings block

**Files:**
- Modify: `config/settings.py` (AGENT_* block)

- [x] Add near the AGENT_* block:
```python
STRATEGY_DIR = "strategies"     # where the agent's playbook .md files live
STRATEGY_ACTIVE = "default"     # the strategy file (no extension) the agent runs
```
- [x] Commit.

### Task 4: `agentic/prompts.py` — strategy-agnostic prompt

**Files:**
- Modify: `agentic/prompts.py`
- Test: `tests/test_agentic/test_agent_loop.py` (system-prompt contract test)

- [x] Update `test_system_prompt_contains_the_contract`: drop the `"CRT" in prompt` assertions (playbook now external); assert the contract parts (PROPOSE-ONLY, vocabulary, truth rules, output contract) still hold and `build_system_prompt(playbook=...)` appends the strategy.
- [x] Run to red, then edit `prompts.py`: remove `from agentic.crt_strategy import ...`, delete `CRT_PLAYBOOK` and its concatenation from `SYSTEM_PROMPT`; docstring says the playbook is supplied by the caller (the loaded strategy md).
- [x] Run tests green.
- [x] Commit.

### Task 5: `agentic/agent_loop.py` — playbook injection

**Files:**
- Modify: `agentic/agent_loop.py` (`AgentLoop.__init__`, `run_turn` L695)
- Test: `tests/test_agentic/test_agent_loop.py`

- [x] Write failing test: `AgentLoop(..., playbook="STRAT-X")` → a run's `AgentRequest.system_prompt` contains "STRAT-X"; default (no playbook) still works.
- [x] Implement: `__init__(..., playbook: str = "")` → `self._playbook`; `run_turn` calls `prompts.build_system_prompt(playbook=self._playbook)`.
- [x] Green, commit.

### Task 6: `agent_service.py` + server config — load once, loud

**Files:**
- Modify: `agent_service.py` (`AgentConfig`, `AgentService.__init__`, `_loop`, `status`/`panel`)
- Modify: `server.py` (`get_agent_service` builds config with strategy fields)
- Test: `tests/test_agent_service.py`

- [x] Tests: (a) `AgentConfig(strategy_dir=str(tmp), strategy_name="s1")` + a service builds with the file's text and `status()["strategy_name"]=="s1"`; (b) missing file raises `StrategyError` at construction; (c) blank `strategy_dir`/`strategy_name` falls back to `config.settings` values; (d) loop's prompt includes the strategy text (fake client captures `AgentRequest`).
- [x] Implement: `AgentConfig` gains `strategy_dir: str = ""`, `strategy_name: str = ""` (resolved blank → settings `STRATEGY_DIR`/`STRATEGY_ACTIVE` in `AgentService.__init__`); service loads once via `agentic.strategy.load_strategy`, stores `self._strategy`; `_loop()` passes `playbook=self._strategy.text`; `status()`/`panel()` expose `strategy_name`.
- [x] `server.py` `AgentConfig(...)` gains `strategy_dir=STRATEGY_DIR, strategy_name=STRATEGY_ACTIVE` (import from settings).
- [x] Green, commit.

### Task 7: delete `crt_strategy.py` + cleanup

**Files:**
- Delete: `agentic/crt_strategy.py`, `tests/test_agentic/test_crt_strategy.py`
- Modify: `agentic/__init__.py`, `agentic/models.py` (comment), `tests/test_agentic/test_store.py`, `tests/test_agentic/test_standalone.py`

- [x] `agentic/__init__.py`: drop the crt_strategy import + `__all__` entries (`HTF_BIAS_TIMEFRAMES`, `LTF_EXECUTION_TIMEFRAMES`, `OPTIONAL_FAMILIES`, `REQUIRED_FAMILIES`, `Confirmation`, `CrtAnalysis`, `CrtPlan`, `HtfBias`, `analyze`, `build_plan`, `derive_htf_bias`, `find_confirmation`); add `from agentic.strategy import MAX_STRATEGY_CHARS, Strategy, StrategyError, load_strategy` + exports; docstring's phase-1 line now names `strategy.py`.
- [x] `models.py`: comment on `DEFAULT_FAMILIES` no longer cites crt_strategy.
- [x] `test_store.py`: pin compares `DEFAULT_FAMILIES` to the literal `["crt","bos","fvg","ob","liquidity","ts"]`.
- [x] `test_standalone.py`: pure-core file list swaps `crt_strategy.py` → `strategy.py`; L130 assertion moves to `DEFAULT_FAMILIES`.
- [x] Delete the two files.
- [x] Commit.

### Task 8: remove `/api/agent/crt` + route-count test

**Files:**
- Modify: `server.py`, `tests/test_server_offset.py`

- [x] Delete the `@app.get("/api/agent/crt")` handler block.
- [x] Update the route-count assertion 38 → 37.
- [x] Green, commit.

### Task 9: full verification + docs

**Files:**
- Modify: `architecture_index.md`, `docs/specs/2026-10-17-agentic-chart-agent-design.md` (a short pointer note)

- [x] Run the full agentic test directory + `test_agent_service.py` + `test_server_offset.py`; fix any straggler (grep for `crt_strategy`/`CrtPlan` leftovers).
- [x] Update `architecture_index.md` (3.7 rows: remove crt_strategy, add strategy.py + strategies/; data flow + conventions).
- [x] Commit.
