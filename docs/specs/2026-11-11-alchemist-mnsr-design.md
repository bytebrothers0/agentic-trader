# Alchemist MSNR — Strategy & Core-Binding Design

**Date:** 2026-11-11 · **Method:** deep-research (Observe → Experiment → Implement)
**Status:** approved-by-delegation (operator answered design questions, then left;
review veto window on return)
**Research:** `docs/research/2026-11-11-alchemist-mnsr/sources.md` (fresh web
research; the old local `alchemy_mnsr.md` and its git history were NOT consulted)

## 1. Decisions locked by the operator

1. **Trader-knowledge core binds to the SYSTEM PROMPT** (chat + watcher), not to
   the strategy file — strategy .md files then use FVG/OB/structure terms
   directly without redefining them. Rationale: separation of *universal trader
   knowledge* (one layer, always on) from *the strategy being traded* (a thin
   file, swappable).
2. **Model has 1M context** — token budgets are relaxed concerns; the binding
   loader caps that still apply are the strategy-file 25k chars and practical
   latency. The knowledge layer riding the system prompt is fine.
3. **Backtest metric = outcome agreement ≥70%**: replay historical windows;
   a win is a win, a loss is a loss; the agent's directional call must match
   the realized outcome.
4. **Fresh-levels filter**: decided by experiment (compare outcomes fresh-only
   vs all-levels, keep the better), not a-priori.

## 2. What the research established

- **MSNR = Malaysian Support & Resistance**: body-based (open/close) S/R zones,
  fresh vs unfresh doctrine, storyline, rejection vs acceptance evidence,
  confluence without clutter. (Grade C sources, mutually consistent.)
- **Alchemist framework** = a four-stage decision loop: **storyline → POI →
  trigger → invalidation**, with written if/then branches and "no trade" as a
  first-class outcome.
- **CRT** = each HTF candle is a dealing range: parent → purge (sweep) → close
  back inside → delivery toward the opposing boundary. Maps 1:1 onto this
  system's `crt` detector.
- **The blend (Alchemist MSNR):** MSNR zones supply the POI; SMC/ICT (structure
  shift, liquidity sweep, displacement, FVG) supply the trigger; CRT frames the
  higher-timeframe candle ranges; the knowledge core supplies execution-level
  concepts.
- **Trade history leg is BLOCKED:** the educator has no verified public track
  record (VIP-signal funnel red flags; unrelated FCA-flagged "FxAlchemist" bot
  excluded). The backtest therefore replays market windows and scores against
  realized outcomes — documented deviation.

## 3. Deliverables

### 3.1 `strategies/alchemist/` — fresh modular strategy files (no concept redefinition)

| File | Content |
|---|---|
| `00-overview.md` | Identity of the blend; the four-stage loop; conditional branches; no-trade doctrine |
| `10-storyline.md` | How to state the storyline (trend/range/transition per timeframe; one factual sentence; HTF authority) |
| `20-zones.md` | MSNR zone mechanics: body-based zones, zone vs line, proximal/distal, only obvious zones, HTF zones outrank LTF |
| `30-fresh.md` | Fresh vs unfresh: what consumes a level (touches, closes through, chop), freshness priority, unfresh = warning not ban |
| `40-poi.md` | POI selection: RBS/SBR role reversals, old breakout bodies, range boundaries; POI behind an unswept inducement is a trap |
| `50-triggers.md` | The trigger catalogue: sweep + close-back (CRT), MSS with displacement, rejection + minor structure shift, FVG retrace entry, breaker retest; each with its invalidation |
| `60-scenarios.md` | Scenario branches per session/script: Asia range → London purge → NY delivery; edge cases: news candles, runaway trend (sweeps become continuation), double-purge, EQ chop |
| `70-bend-doctrine.md` | When the rules bend: capital protection, profit lock, named bends; never bend to enter |
| `80-gold.md` | XAUUSD specifics: spread/volatility regime, killzones reference (knowledge core owns session doctrine), news candle handling |

Each ≤ ~35 lines, dense, C-not-Python. A generator `tools/build_alchemist.py`
(composing in filename order, budgets enforced: core lines + total chars under
the loader cap) produces `strategies/alchemist_mnsr_v2.md`. The OLD
`strategies/alchemy_mnsr.md` is untouched; nothing is activated.

### 3.2 Core → system prompt binding (code)

- `agentic/prompts.py`: new `knowledge_layer()` reading
  `strategies/knowledge/*.md` (ordered, cached), appended in BOTH
  `build_system_prompt` (watcher) and `build_chat_system_prompt` (chat), after
  the persona and before the playbook. Broken reads degrade to absent (never
  crash a turn). Config knob: `AGENT_KNOWLEDGE_DIR` (default `strategies/knowledge`).
- The 00-core.md persona stays where it is; the composed `trader_core.md`
  remains available as a strategy for A/B but is no longer required.
- Tests: prompt builders include the layer; broken dir degrades; watcher +
  chat both affected.

### 3.3 Replay backtest — `tools/alchemist_replay.py`

- For each replay window: pick a historical date/time (e.g. a past London or
  NY session on XAUUSD), compute the feed `offset` so the agent's
  `set_view(offset=)` lands on that window (time-machine), ask the agent for
  its directional call + entry logic per the Alchemist loop, then resolve the
  realized outcome from actual candles after the entry time.
- Score: directional agreement with the realized move (to a fixed horizon and
  to the session end), reported per window + aggregate. ≥70% = pass; honest
  report either way. Renders saved per turn for manual verification.
- Provider instability known: retries with 60s backoff (same pattern as the
  interview harness).

### 3.4 Fresh-filter POC

- Same replay battery run twice: `status_filter=all` vs fresh-only view. Compare
  agreement + answer quality; keep the better; document the result. No core
  change without evidence.

## 4. Lifecycle / risk (honest)

- **Attribution:** outcome agreement measures the AGENT+strategy vs the market,
  not "the real Alchemist strategy" — no verified ledger exists. The report
  says so.
- **Look-ahead risk:** the replay prompt must NOT reveal the future; windows
  presented via offset with post-entry resolution done by the harness, not the
  agent.
- **Overfitting:** battery size kept modest (~8–12 windows) and stated as
  provisional; one instrument (XAUUSD), one week regime.
- **Leashes:** chat turn-rate relaxed per chat turn already; replay runs an
  isolated copied store (same pattern as agent_interview).
- **Budget:** strategy file must fit the 25k loader cap (knowledge moved out to
  the system prompt makes this comfortable); 1M-context model noted.

## 5. Success criteria

1. Fresh `strategies/alchemist/` library + composed playbook, built by script,
   NOT activated.
2. Knowledge layer bound to system prompt (chat + watcher) with tests passing.
3. Replay harness runs; score table with per-window verification renders;
   ≥70% or the honest number + named weaknesses.
4. Fresh-filter POC comparison table; recommendation.
5. All committed; nothing in watcher/execution touched.
