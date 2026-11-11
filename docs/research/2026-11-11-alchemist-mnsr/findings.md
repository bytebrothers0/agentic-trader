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

- **Baseline battery (all-levels arm): COMPLETE — but inconclusive.** 6 windows
  ran (2 days × 3 sessions), all returned `CALL: NO-TRADE` vs realized UP/UP/UP/DOWN/DOWN.
  **Not an agent failure:** each NO-TRADE was doctrine-correct — every window
  fell inside a macro print (CPI/NFP-style 08:30 UTC), and the agent refused to
  guess ahead of it ("trade the post-data retrace, not the pre-data sweep").
  **Harness flaw:** the prompt constrained the model to ONE set_view with no
  render/level_lookup, and `set_view` returns view config but **no level
  prices** (prices only come via `level_lookup` or the render image). So the
  model honestly had no numbers to quote. `set_view`-only turns DO complete
  during the day (~27-44k tokens); anything with level_lookup or render drops.
- **Provider limitation (confirmed, daytime):** ~6 independent daytime attempts
  at tool-bearing turns (set_view + level_lookup, 43-96k tokens) ALL dropped
  with empty responses / RemoteDisconnected / read timeouts, across 2-4
  retries with 60s backoff each. The same turns (M15-scale, ~27k tokens) ran
  cleanly at night (2-4am). Conclusion: the free gateway cannot be relied on
  for agent tool turns during daytime business hours.
- **No-answer turns are excluded from the agreement score** (0/0 = 0%) and
  listed separately; they are not counted as losses.

## What the backtest needs (night run)

Re-run at night (provider stable) with this command:

    python tools/alchemist_replay.py --days 5 --attempts 3 --backoff 60 --label baseline-night

Then the fresh-filter POC arm on the same windows:

    python tools/alchemist_replay.py --days 5 --attempts 3 --backoff 60 --status-filter live --label fresh-poc-night

Compare the two agreement tables against the ≥70% target. The harness already
writes per-window renders + the copied store to each run dir for manual
verification.

## Design notes locked in

- **No look-ahead:** offsets are counted from real candle history (bars newer
  than the cutoff, per timeframe); the provider wrapper clamps every request to
  ≥ the forced offset. Verified: M15 offset 211 for a 2-day-old cutoff.
- **Metric:** outcome agreement (directional call vs realized close-to-close
  move; a win is a win, a loss is a loss). NO-TRADE calls score as correct only
  when the realized move is FLAT (noise band ±0.5 pts); otherwise they're
  excluded — a known limitation since valid "no trade ahead of news" calls
  against a trending realized move don't score.
- **Isolation:** live store copied to each run dir; operator's server and state
  untouched. $0 local provider from .env.
