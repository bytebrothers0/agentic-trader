# Agent Run Recovery and Direction Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task.

**Goal:** Keep incomplete agent analyses resumable and make the strategy report market direction separately from trade readiness, while repairing strategy workflow detection and retrying transient provider failures.
**Architecture:** Persist an atomic sidecar checkpoint for an in-progress turn, restore its exact request/tool history for a continuation endpoint, and expose resumability to the panel UI. Correct the strategy-name matching and prompt/evidence contracts in the loop. Retry only bounded transient transport failures.
**Resilience & Lifecycle Strategy:** Save checkpoint after each completed model/tool round; do not replay completed tool calls; keep the checkpoint on recoverable truncation/provider failure; remove it only after successful completion or explicit context reset. Resume uses an existing run identifier and a dedicated endpoint.
---

### Task 1: Correct strategy identification and directional thesis contract
**Files:** `agentic/agent_loop.py`, `agentic/prompts.py`, strategy briefing code.

- [x] Recognize both `MNSR` and `MSNR` spellings in the Alchemist strategy and enforce the intended staged workflow.
- [x] Update analysis and closing instructions so market bias describes observed direction independently from whether an entry proposal passes setup rules.
- [x] Include current timeframe close/timestamp and verify invalidation against current bars before describing it as pending.

### Task 2: Bound retries for transient model endpoint failures
**Files:** `agentic/agent_service.py`, `agentic/llm.py`.

- [x] Inspect transport exception shapes and retry 404/429/5xx/network failures with a small bounded backoff.
- [x] Preserve the existing per-turn round limit of 400; distinguish it from the per-completion generation token limit.

### Task 3: Persist and restore analysis checkpoints
**Files:** `agentic/agent_loop.py`, `agentic/agent_service.py`, `agentic/tools.py`, persistence helpers.

- [x] Serialize the next model request and completed call/tool history atomically after each completed round.
- [x] Resume from the next model round without re-executing successful tool side effects.
- [x] Leave a checkpoint when a completion ends with `finish_reason=length` and no usable structured result, or when a transient client failure interrupts the turn.
- [x] Clear the checkpoint after successful completion and when the user resets agent context.

### Task 4: Expose resumable runs in the agent panel
**Files:** agent API routes and `web/app.js`.

- [x] Add a dedicated resume-run endpoint that continues the active symbol's stored checkpoint.
- [x] Return resumability in panel/run status and switch the primary action between Run now and Resume.
- [x] Preserve the existing live 400-round ceiling and show a clear in-progress/resuming state.

### Task 5: Review integration and report
- [x] Inspect the diff and document implementation details, verification performed, and remaining limitations.
