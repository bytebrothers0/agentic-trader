# Findings — Alchemist MSNR phase (2026-11-11, day 2 of the research program)

Working notes while the replay battery grinds. Updated as results land.

## What is now in place (committed)

1. **Core→system-prompt binding** (`agentic/prompts.knowledge_layer`): the
   trader-knowledge files ride the system prompt for BOTH the watcher and the
   chat persona, so strategy files use concepts (FVG, OB, dealing range)
   without redefining them — the operator's explicit design. The layer is
   families-knob-aware: lines naming a disabled family's detector tag are
   dropped (the knob's anti-bloat intent wins over concept prose). Tests
   updated; the pure-core import-purity contract is preserved (no config
   import; optional `AGENT_KNOWLEDGE_DIR` env override only).
2. **Fresh Alchemist MSNR strategy library** (`strategies/alchemist/`, 9 files
   → composed `alchemist_mnsr_v2.md`, 11.7k/25k chars, loader-verified):
   four-stage loop (storyline → POI → trigger → invalidation), body-based
   MSNR zones, fresh/unfresh doctrine, trigger catalogue, session scripts +
   edge cases, bend doctrine, gold specifics. Written from fresh web research;
   the old `alchemy_mnsr.md` and its git history were never consulted.
3. **Replay harness** (`tools/alchemist_replay.py`): the agent's whole
   perception is clamped to a historical cutoff via per-timeframe exact
   offsets (counted from real candle history — no look-ahead by construction),
   then the call is scored against the realized move from actual candles.

## Replay-engineering findings (each verified from turn records)

- **Offset semantics bug (mine, fixed):** `offset` = bars skipped back from
  the present. My first version counted bars BEFORE the cutoff (1799 instead
  of ~206 for a 2-day-old cutoff) — sending M15 views to mid-October and D1
  views months back (the agent quoted a "3355.4 live price" — June data).
  Correct rule: offset = count of bars NEWER than the cutoff, per timeframe.
- **The provider ceiling is per-turn size, not model context:** the operator's
  model carries 1M tokens, but the free gateway drops mid-stream on heavy
  turns. Every H4-scale replay turn (~73k tokens: H4's ~517-level briefing +
  system prompt + playbook + render) died with empty responses /
  RemoteDisconnected, repeatedly. M15-scale turns (~27k) succeeded overnight
  but were also failing at midday — size + time-of-day variance.
- **Chat-leash interaction:** the replay prompt initially induced full
  multi-view workflows; the loop's CHAT_MAX_TOOL_ROUNDS=4 ended turns after
  the budget with "(no response)". Fixed by prompting a tight tool budget
  (one split view, render only if needed) — the answer must be one complete
  final message.
- **Implication for the live chat UI (from last night, still standing):**
  H4-scale questions will fail on this provider regardless of prompt quality.
  The fresh-filter POC arm (fresh-only levels) is a candidate mitigation — it
  directly shrinks the briefing.

## Status

- Baseline battery (all-levels arm): running in background, 10 windows,
  5 attempts × 60 s backoff each. Fresh-only POC arm runs next for comparison.
- Scoring: outcome agreement (a win is a win, a loss is a loss), ≥70% target;
  failed turns are reported separately and excluded from the score but listed.
