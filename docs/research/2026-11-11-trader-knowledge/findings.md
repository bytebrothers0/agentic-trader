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

1. ~~Retry-on-timeout in the interview harness~~ ✅ shipped round 2.
2. ~~Interrogate the internal/external flaw~~ ✅ round 1 press-test passed;
   round 2 confirmed the sharpened prompt fixes it proactively.
3. ~~Re-interview after sharpening market-structure.md's I-/external rule~~ ✅.
4. Fresh-store round 3 (no resumed history) to isolate the premium/discount
   empty-response failure: confirm it is context size, not the topic.
5. Sweep-question grounded in detector states ✅ done round 2 (A−); keep the
   same phrasing in future rounds.
6. Remaining topics un-interviewed: order blocks, FVG, QM/IDM, trendlines,
   psychology-under-press (give the agent a wrong statement and see if it
   defends or folds — the strongest test of trader reasoning).
7. Baseline Q6 was surprisingly good — likely the chat persona's prior, not the
   playbook. Keep it as a reminder that interview gains must be attributable:
   compare, don't assume.

## Round 2 — sharpened prompt (2026-11-11 ~03:00, run `20261111-0253-round2-sharpened`)

Prompt change: FRAME step in `00-core.md` now requires every structure level be
labelled internal (I-) or external, with "the frame follows EXTERNAL structure
only — an internal break is a pullback read, not a reversal." Composed playbook
rebuilt at 25,0xx chars (still under the loader cap; the FRAME sharpening cost
~90 chars, paid for by local trims).

| Q | Result | Verification |
|---|---|---|
| bias + invalidation (label I-/external) | **A** — "bearish. The D1 external structure turned bearish at the CHoCH near 3959 (B16, external), and the H4 just printed a fresh internal …" | ✅ D1 `CHOCH (BEARISH) 3959.425` is indeed the only external D1 CHoCH; 4073.20 correctly treated as internal this time (round 1 called it "D1 BOS") |
| sweep vs break (detector states) | **A−** — honest: "can't confirm a recent liquidity sweep; here's what the levels show" with per-level status reasoning | grounded in tool states, no fabricated sweep |
| premium/discount | **FAIL** ×4 — empty final response after full tool runs (~74k tokens) | see below |
| liquidity + draw | **A** — distinguishes filled pools ("burned fuel") from live untouched pools as the draw | ✅ matches detector states |
| what would change my mind | **A** — frame restated correctly with external-first discipline | ✅ |

**The press-test passed, and the fix generalised.** Round 1 needed a human
press-question to catch the internal/external error; round 2 labels internal vs
external **proactively** on the very first question, unprompted. That is the
round-1 → round-2 attribution the loop exists to measure.

**Premium/discount regressed to empty responses.** 4 consecutive turns (fresh
rephrase too) ran 2 tool calls then emitted no final text, ~74k tokens each —
vs 50k in round 1 where the same question succeeded. Suspected cause: the
copied store carries the operator's real chat history plus our failed turns, so
the briefing/history grew; the free gateway chokes on the larger context
(evidenced also by the RemoteDisconnected + timeout cluster that started once
the run's conversation got long). Not a prompt failure — the knowledge round-1
answer (graded A) stands as evidence the topic is learnable. Action for round
3: start from a fresh store copy (not resumed), and consider capping chat
history injection lower in interview mode.

### Harness fixes shipped this round

- retry-on-failure per question (3 attempts, cool-off between) — two bugs found
  while using it: `"(no response)"` placeholders counted as success (now
  rejected), and Windows cp1252 console crashed on unicode answers (now
  UTF-8-forced).
- `--out-dir` resume: keeps the copied state, so follow-up questions continue
  the conversation (used for the round-1 press test).

## Round 3 — fresh topics + the psychology press-test (2026-11-11 ~03:15, run `20261111-0310-round3-fresh-topics`)

| Q | Result | Verification |
|---|---|---|
| premium/discount | **FAIL** ×3 — see round 2 note; gateway RemoteDisconnected persists | round 1's A grade stands |
| order blocks | **FAIL** ×3 — same gateway window (fast RemoteDisconnected) | retry next round |
| fresh FVGs + which to use | **A** — "an FVG is a zone, not a signal"; picks F29 4063.53–4067.81 as the short zone only if reached in the correct half of the range; F42 below as bullish candidate but "28 points away, not the immediate play"; "with the bias still unconfirmed, I'm flat" | ✅ H4 bearish FVG at 4064.278 exists in that range. ⚠ detector state is UNFRESH (partially mitigated) where the agent said "fresh" — freshness is the one misread; F42 not found on H4 (may have been an M15 view) |
| IDM taken? | **A** — both nearby IDMs already consumed: 4054.11 "broken (body close)", 4042.56 "swept (wick through, close back inside)"; "that box is already checked; don't stand aside waiting for it" | ✅ exact: IDM 4054.107 BROKEN, 4042.562 SWEPT — the detector's state vocabulary used correctly, distinguishing broken from swept |
| trendline | **A** — R13 4123.21 "roughly 74 points above", "break only counts as a body close — a wick poke is a lure", names the flip targets (4155.83, 4437.54) and the ascending support below (3875.70) | ✅ line at 4123.21 exists (detector tags TL_SUPPORT fresh; agent read it as descending resistance — level exact, role label uncertain: flipped lines carry both tags) |
| **press test** (operator asserts "buy, it's in discount") | **A+** — refuses with doctrine: "Discount in a bearish external structure is just a cheaper place to short, not a reason to buy"; "the wick below 4023 is a wick, not a close… a sell-side sweep into the O3 breaker zone rather than a reclaim with displacement"; adds the missing session frame; names the two body-close events that would flip it | ✅ breaker (BULLISH) 4027.141 inside the quoted 4016.53–4037.75 zone; trendlines R13/R8 live as quoted; the read is detector-faithful |
| order blocks (retry ~03:30) | **A** — O3 bullish breaker 4027.14 (4016.53–4037.75) "fresh, live, BOS-associated", flip explained ("price body-closed through the original block and flipped it"); O2 4122.88 "filled… skip since it's already mitigated"; O4/O1 triaged by distance | ✅ breaker (BULLISH) 4027.141 live; bearish OB 4122.88 filled; 3942.30/4289.74 live as quoted |

**The press test is the round's headline.** The operator asserted a trade; the
agent did not fold, did not flatter — it taught back the premium/discount rule,
separated wick from close, sweep from reclaim, checked the session, and closed
with named invalidations. That is the experienced-trader behaviour the whole
loop exists to produce, and it came from the composed playbook alone (no human
coaching inside that conversation).

**Provider instability is now the loop's main tax.** Clustered
RemoteDisconnected/Timeout failures on heavy turns (3+ tool rounds; renders
make turns long). Retries with backoff help but the premium/discount question
has now failed ~10× across three contexts while 2-tool questions succeed
reliably. Mitigations for round 4: prefer questions answerable in ≤2 tool
rounds; if the gateway keeps dropping, test one turn per prompt-engineering
change rather than full batteries.

**Premium/discount ROOT CAUSE FOUND (round 3c).** The failure is not the topic,
not the prompt, and not random: every failing turn built an **H4 bos view,
whose briefing embeds ~517 levels ≈ 45.8k tokens** (the same figure repeats to
within 400 tokens across all failures), then dropped mid-stream
(RemoteDisconnected) or emitted an empty final. Asking the same question on the
**M15 view** (~26k-token briefing) succeeded on attempt 2. The H4 + image
payload exceeds what the free gateway completes reliably.

- **Round 3c grade: A.** "Range 4133.84 → 4013.44, ~120 points, EQ 4073.64,
  price 4048.20 = ~29% of range from the low → discount, inside the ~71%
  retracement of the decline." Every number verified: EQ exact
  ((4133.84+4013.44)/2 = 4073.64), percentage exact (28.8%), 4133.843 is a live
  M15 I-CHOCH level, and 4013.443 is the exact recent M15 candle wick low.
  Invalidations named. (Caveat: it called the wick low a "confirmed swing" —
  generous; and didn't flag 4133.84 as internal.)
- **Production implication for the live chat UI:** on this provider, H4-scale
  questions (briefing ~500 levels) will fail while M15-scale succeed. Options
  to evaluate later: trim the H4 briefing's embedded level count
  (e.g. status_filter live-only by default, or cap levels per family), or keep
  the free provider on M15-scale views only. NOT changed tonight — core-briefing
  behavior is outside this research's additive scope.

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
