# Findings — Trader-Knowledge Loop, night 1 (2026-11-11)

Interviews: `20261111-0211-baseline-active` (playbook `alchemy_mnsr` = "just trade")
vs `20261111-0225-trader-core` (the composed knowledge playbook). Identical
question set, identical copied store (same market context), $0 local provider.
Every number the agent quoted was independently re-checked against the live
detectors (`get_indicators`, H4/D1, bos+liquidity) and the turn renders.

## Graded comparison

| Q | Baseline | trader_core | Verdict |
|---|---|---|---|
| 1 bias + invalidation | **FAIL** — provider timeout, 120s, no answer | **A−** — bearish with verified levels: H4 CHoCH 4084.31 ✅, D1 BOS 4073.20 ✅, draw "nearest support ~3975.42" ✅, invalidation "close above 4084.31" ✅. *Flaw: calls I-CHOCH/I-BOS (internal) by external names; ignores the external H4 CHOCH (BULLISH) at 4082.907* | knowledge transformed the answer |
| 2 liquidity by side | **C+** — one level (4131.09 filled), honest about the empty sell-side | **B+** — pools by side with status: 4148.65 ✅, 4200.47 ✅ (H4 EQUAL_HIGHS BUYSIDE), D1 4066.30 taken ✅; honest about sell-side; offered a focused look | better, still no explicit draw |
| 3 sweep vs break | **B** — correct close-back-vs-body-close distinction, plausible level | **FAIL** — provider timeout (128s) | timeout, not knowledge |
| 4 premium/discount | **B** — measured a range (4148/4013 loose), correct discount | **A** — textbook: verified swings 4134.196/3971.313, EQ 4052.76 = exactly (H+L)/2 ✅, position "45% of range" ✅, bearish OTE computed 4072–4100 ✅ (62–79% retrace checks out numerically) | the taught procedure, executed |
| 5 session + script | **C** — "Asia, quieter" (UTC only, no script) | **A−** — "Asia killzone, ~21:30 NY (02:30 UTC)" ✅ DST-correct; script applied honestly: "Asia doesn't deliver; wait for London/NY sweep" | the time frame is now real |
| 6 what changes my mind | **B** — specific flip conditions with levels (oddly good) | **FAIL** — provider timeout (136s) | timeout, not knowledge |

**Timeouts (3 of 12 turns, both runs):** `client_error: TimeoutError: read
timed out` — the free gateway stalls on heavier reasoning turns; not a prompt
failure. The harness should retry once on timeout (todo below).

## Independent verification (the part that matters)

The agent's numbers are **tool-verified**, not hallucinated: every claimed level
exists in the detector output at the exact price it quoted. I also read the
turn renders myself — the split D1/H4 image confirms the described structure
(price 4040.53 below the Nov-9 high, the 4084 CHoCH region, the 3975 BOS low).

The one systematic reasoning flaw found: **internal/external discipline**. The
bearish frame was built on `I-CHOCH 4084.305` / `I-BOS 4073.195` — internal
levels — quoted as "H4 CHoCH" / "D1 BOS" (external names), while an EXTERNAL
`CHOCH (BULLISH) 4082.907` sits right there. market-structure.md teaches
"external first"; the model must be pressed on this in the next interview
round (and the file may need the rule sharpened: *always prefix I- levels
"internal" and check the external swing before committing the frame*).

## Token economics (measured from the turn records)

| Run | avg tokens/turn | single-round floor (Q5) |
|---|---|---|
| baseline ("just trade") | 19,052 | 5,343 |
| trader_core | 32,464 | 12,707 |

The knowledge layer costs **~7.4k tokens per model round** (the playbook rides
every round). Fine on the local provider ($0, large context — this entire
interview cost $0.00). **It will not fit the hosted Groq 7k-ITPM tier** — if
the operator ever switches to hosted, the knowledge layer must be trimmed or
the playbook split. Recorded as a hard constraint, not a worry.

## What the loop still needs (next rounds)

1. Retry-on-timeout in the interview harness (1 retry, then move on).
2. Interrogate the internal/external flaw: "you cited 4084.31 — internal or
   external? What does the EXTERNAL H4 CHOCH at 4082.9 say?" — grade whether
   the agent can self-correct when pressed (that is the experienced-trader test).
3. Re-interview after sharpening market-structure.md's I-/external rule.
4. Sweep-question (Q3) deserves a re-run with a fresh prompt asking for the
   DETECTOR's state fields (swept/taken + body-close), so the answer is
   grounded in tool evidence rather than recall.
5. Baseline Q6 was surprisingly good — likely the chat persona's prior, not the
   playbook. Keep it as a reminder that interview gains must be attributable:
   compare, don't assume.

## Where sources disagree (from sources.md, still standing)

CHoCH internal/external scope; OB wick-vs-close invalidation; Asia KZ start
19:00 vs 20:00; aggregate SMC edge (zero per the 44-detector study — the
library therefore teaches confluence + selectivity, not pattern trust).

## Deliverables status

- 10 topic files in `strategies/knowledge/` (dense, ≤30 lines each) ✅
- Master core 19/50 lines ✅ (operator's ≤50 budget)
- Composed `strategies/trader_core.md`: 25,014 chars — fits the loader's
  25k cap ✅ (this cap shaped the final density; enforced by the build script)
- Generator `tools/build_trader_core.py` (line + char budgets enforced) ✅
- Interview harness `tools/agent_interview.py` (isolated store copy, $0) ✅
- **Nothing activated**: `alchemy_mnsr.md`, `STRATEGY_ACTIVE`, watcher config —
  all untouched, per the operator's instruction. The agent wore trader_core
  only inside the isolated interview process.
