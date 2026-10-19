# backtest — replay the chart agent on historical classic CRTs

A read-only, point-in-time replay of the agentic CRT agent. It finds classic
three-candle CRTs in real history, freezes the world at each setup's decision
bar, runs **one real agent turn** against the *unmodified* indicator stack, and
then scores the thesis and any proposals against the price action the agent never
saw.

It is propose-only, like the agent: nothing here sends an order.

```
python -m backtest.run_crt_backtest --timeframe M15 --days 45 --min-rr 1.5
```

## What it does, in order

1. **Load** deep MT5 history for every native timeframe (cached to
   `<out>/history.pkl`, so re-runs need no terminal).
2. **Find** classic three-candle CRTs whose target was *reached*, and score each
   as a naive trade (entry = manipulation close, stop = beyond the sweep wick,
   target = the far boundary). The best `--scenarios` by R:R win.
3. **Freeze** the feed at each setup's decision instant (the manipulation
   candle's close) and render the CRT-only chart the setup looked like.
4. **Replay** one agent turn — boot by default, or a human `--message` request —
   through the real `AgentService`, `Feed`, `Renderer` and `VisionClient`.
5. **Score** the thesis and proposals against the bars that followed, and write a
   report (`report.json` + `report.md`) plus every PNG.

## Why the replay is faithful

The agent's perception path is `Feed -> server.get_indicators ->
MT5DataLoader`. The backtest does not reimplement any of it: it swaps the
**loader** (`server.get_loader`) for `FrozenLoader`, which serves pre-loaded bars
truncated at the freeze instant. Every detector, every payload field and every
render is therefore exactly what the live endpoint would have produced.

**No look-ahead** is the correctness claim, and it is enforced in two places:

* a native bar is served only if it had **closed** by the freeze
  (`bar_open + nominal_duration <= T`);
* a synthesized M45 bucket is dropped if its window extends past `T` (otherwise
  it would be a partial bar with a future close).

`tests/test_backtest.py` pins both. `fetch_timeframe(tf, count, start)` keeps
MT5's "bars back from the newest" semantics, so the agent's `view.offset` behaves
exactly as it does live (the newest settled bar is `offset = 0`).

## Rate-limit safety

* Live turns run **sequentially**, one scenario at a time, spaced by
  `--cooldown-s` (default 20s).
* `--mode live` first checks the local endpoint's `/health` and refuses to start
  against a dead proxy.
* The HTTP transport already retries `429`/`503` with backoff.
* `--mode mock` runs the whole pipeline against a scripted agent: zero spend,
  no network.
* `--dry-run` stops before the model entirely (detect + render only).

## Options that matter

| flag | meaning |
| --- | --- |
| `--timeframe` | timeframe to scan and to seed the agent's view with |
| `--days` | only setups decided within the last N days **of data** |
| `--min-rr` | drop setups whose naive trade carried a worse R:R |
| `--scenarios` | how many setups to replay, best R:R first |
| `--mode` | `live` (real model) or `mock` (zero spend) |
| `--message` | run a human `request` turn with this detail instead of `boot` |
| `--families` | seed the view with these families (default: the store's own — the playbook's six) |
| `--bars` | agent view bars (default: the shipped `AGENT_BARS`) |
| `--max-tokens` | per-call output cap (default: the shipped `AGENT_MAX_TOKENS`) |
| `--model` | override the provider's model (handy to compare models) |
| `--cooldown-s` | pause between live scenarios |
| `--cache` / `--refresh` | history cache path / ignore it and re-fetch |
| `--report-only` | rebuild `report.json`/`report.md` from a saved run (no model, no data) |
| `--dry-run` | never call a model |

## Output

```
<out>/
  history.pkl                     cached MT5 history
  run_<UTC-stamp>/                one run, never resumed by the next
    report.json                   the full record (candidates, calls, verdicts)
    report.md                     the readable report
    r_<hash>.png                  the CRT-only chart of each setup
    scenario_<n>/
      state/<symbol>.json         the agent's store after the turn
      renders/*.png               every render the agent made
```

The report records, per scenario: the CRT, the naive trade, **every model call**
(finish reason, tools asked for, token split, whether an image was attached), the
tool log, the thesis, the proposals, and a `diagnosis` block naming what the turn
actually did (thrashing, running away, recovering).

## What the runs showed

Three classic M15 CRTs (all resolved to target; naive R:R 3.1–4.1), replayed
against `glm-5.3-flash-free` through the local opencode-proxy with the tuned
perception the live test uses (`--families crt,bos,fvg --bars 120
--max-tokens 8000`, `--days 120`):

* **The agent orients before it trades.** Every turn ran
  `set_view` to a higher-timeframe split → `render` → work. 1/3 named a
  directional bias, and that one was **right**: a grounded bearish read of a
  bearish M15 CRT (D1 below I-CHOCH/I-BOS, price into a live H1 bearish CRT
  cluster), confidence 0.55, plus a pin and two watches. It aligned with the CRT
  that resolved to its target.
* **The image round runs away, and the closing call rescues it.** 3/3 turns hit
  the output cap mid-reasoning (`finish_reason=length`) on the round carrying the
  chart image; in 3/3 the tool-less closing call finished and wrote the object.
  The turn is lossy, not lost — but it costs ~32–54k tokens for a boot turn.
* **A written proposal can be silently dropped.** Scenario 3 also emitted a
  short plan, but it was rejected on apply:
  `proposal: bias must be one of ['bearish', 'bullish', 'neutral', 'none']` —
  the model labelled the proposal `"short"` while labelling the thesis
  `"bearish"`, and its `entry`/`sl`/`tp` were *zone strings*, not the numbers the
  schema wants. `output.apply_errors` records this; nothing surfaces it in the
  panel. 1/1 emitted proposal never reached the store.
* **A full-family render is a token bomb.** The default view carried all ten
  families; at M15/300 bars that is **639 levels ≈ 49k tokens** of manifest,
  resent every round (observed prompts of 52k–79k). Narrowing to `crt,bos,fvg`
  drops it to ~4.8k, and `crt` alone to ~1.6k.
* **The production token cap cannot absorb the runaway.** At `--max-tokens 2000`
  the closing call runs away too and the turn yields nothing; at `8000` it
  finishes.

**Fixed the same day (2026-10-19):**

* the dialect wall (`agentic/_dialect.py`) now translates at *both* boundaries —
  `short`→`bearish`, zone strings→numbers — so the scenario-3 plan shape lands;
* `models.DEFAULT_FAMILIES` is the playbook's own six families, not all ten
  (~15k tokens at M15/300 for the six, measured, vs 49k);
* `AGENT_MAX_TOKENS` is `8000`;
* the backtest CLI inherits `AGENT_BARS`/`AGENT_MAX_TOKENS` from the shipped
  settings when the flags are omitted, so a plain run replays the bot as
  configured (`--bars`/`--max-tokens`/`--families` remain overrides);
* the renderer draws the dashboard's visual language (bounded rays, zone boxes,
  per-family ink, an 80-per-family ray budget with `hidden_levels` counted in
  the manifest) after a replayed render was seen painting the chart solid blue
  with full-width band fills;
* the closing call's briefing carries a truthful `image_seen_this_turn`;
* `simulate()` treats an entry as a pending order (an unfilled limit is
  `unfilled`, not an invented excursion) and marks an open trade to market
  (`r_mark`).

Rebuild any report from its saved run, without spending a turn:

```
python -m backtest.run_crt_backtest --report-only backtest/out/run_<stamp>/report.json
```

Reproduce the run itself:

```
python -m backtest.run_crt_backtest --mode live --scenarios 3 --days 120 --timeframe M15 ^
    --cooldown-s 20
```
