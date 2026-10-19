"""
backtest/run_crt_backtest.py — the CRT backtest, end to end.

    python -m backtest.run_crt_backtest --timeframe M15 --days 45 --min-rr 1.5

What it does, in order:

1. **Load** deep MT5 history (cached, so re-runs need no terminal).
2. **Find** classic 3-candle CRTs on ``--timeframe`` whose target was actually
   reached, and score them as naive trades (R:R). The best ``--scenarios`` win.
3. **Replay** the agent at each setup's decision instant — the close of the
   manipulation candle — on a feed frozen there, and render the CRT-only chart
   the setup looked like.
4. **Score** the thesis and any proposals against the price action that followed,
   which the frozen perception never saw.
5. **Report** to ``--out`` (JSON + Markdown) and a console summary.

Rate-limit safety: live turns are sequential, spaced by ``--cooldown-s``, gated on
a proxy ``/health`` check, and the HTTP transport already retries 429/503 with
backoff. ``--mode mock`` runs the whole pipeline with zero spend; ``--dry-run``
stops before the agent entirely.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest import crt_scan
from backtest.historical import (
    DEFAULT_MAX_BARS,
    DEFAULT_TIMEFRAMES,
    FrozenLoader,
    build_feed,
    frozen_server,
    load_or_fetch,
    tf_seconds,
)
from backtest.replay import (
    build_service,
    diagnose,
    pace,
    proxy_health,
    resolve_live_connection,
    run_replay,
    score,
)

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m backtest.run_crt_backtest",
        description="Replay the agentic CRT chart agent on historical classic 3-candle CRTs.",
    )
    p.add_argument("--symbol", default="XAUUSDm", help="MT5 symbol (default XAUUSDm)")
    p.add_argument("--timeframe", default="M15", help="timeframe to scan and to show the agent")
    p.add_argument("--days", type=float, default=45.0,
                   help="only setups decided within the last N days OF DATA (default 45)")
    p.add_argument("--min-rr", type=float, default=1.5,
                   help="drop setups whose naive trade carried a worse R:R (default 1.5)")
    p.add_argument("--scenarios", type=int, default=1,
                   help="how many setups to replay, best R:R first (default 1)")
    p.add_argument("--bars", type=int, default=200, help="agent view bars (default 200)")
    p.add_argument("--max-tokens", type=int, default=2000, help="per-call output cap")
    p.add_argument("--model", default="", help="override the provider's model (else LLM_PROVIDER's)")
    p.add_argument("--mode", default="live", choices=["live", "mock"],
                   help="live = real model; mock = zero-spend scripted agent")
    p.add_argument("--message", default="",
                   help="run a human 'request' turn with this detail instead of a boot turn")
    p.add_argument("--families", default="",
                   help="comma-separated families for the seeded view "
                        "(default: the store's own — every family, which is heavy)")
    p.add_argument("--cooldown-s", type=float, default=20.0,
                   help="pause between live scenarios (rate-limit safety)")
    p.add_argument("--cache", default="", help="history cache path (default <out>/history.pkl)")
    p.add_argument("--refresh", action="store_true", help="ignore an existing cache and re-fetch")
    p.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    p.add_argument("--dry-run", action="store_true",
                   help="detect + render only; never call a model")
    p.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES),
                   help="history timeframes to preload")
    p.add_argument("--max-bars", type=int, default=DEFAULT_MAX_BARS,
                   help="max bars to load per timeframe")
    p.add_argument("--report-only", default="",
                   help="rebuild report.json/report.md from a saved run (no model, no data)")
    return p


# --------------------------------------------------------------------------- #
# Rendering the setup (the "run the CRT indicator on past price action" step)
# --------------------------------------------------------------------------- #

def render_crt_chart(loader: FrozenLoader, symbol: str, timeframe: str, bars: int, out_dir: str):
    """Render a CRT-only chart of the frozen window; return (path, manifest, levels)."""
    from agentic.renderer import Renderer

    with frozen_server(loader):
        feed = build_feed(loader)
        snapshot = feed.snapshot(symbol, timeframe, families=["crt"], bars=bars)
        series = feed.bars(symbol, timeframe, bars=bars)
        renderer = Renderer(width=896, height=504, out_dir=out_dir)
        result = renderer.render(snapshot, series, out_dir=out_dir)
        levels = [lvl.to_dict() for lvl in snapshot.levels]
    return result.image_path, result.manifest, levels


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def summarise(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate what the agent did across every replayed setup.

    The headline a backtest should be able to state: did the agent, pointed at
    setups that *worked*, ever name a bias or propose a trade — and when it did
    not, what actually happened in the turn (thrash, runaway, fallback)?
    """
    total = len(scenarios)
    directional = proposed = aligned = 0
    ran_away = closing_ok = truncated = 0
    emitted = applied = 0
    outcomes: Dict[str, int] = {}
    for scenario in scenarios:
        diag = scenario.get("diagnosis") or {}
        verdict = scenario.get("verdict") or {}
        if diag.get("directional"):
            directional += 1
        if diag.get("proposed"):
            proposed += 1
        if verdict.get("thesis_aligned") is True:
            aligned += 1
        if diag.get("ran_away_calls"):
            ran_away += 1
        if diag.get("closing_call_finished"):
            closing_ok += 1
        if diag.get("truncated_rounds"):
            truncated += 1
        emitted += int(diag.get("proposals_emitted") or 0)
        applied += int(diag.get("proposals_applied") or 0)
        for prop in verdict.get("proposals") or []:
            outcome = str((prop.get("sim") or {}).get("outcome") or "?")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

    findings: List[str] = []
    if total:
        findings.append(
            f"{directional}/{total} turns named a directional bias; "
            f"{proposed}/{total} proposed a trade; {aligned}/{total} aligned with the CRT."
        )
        findings.append(
            f"{ran_away}/{total} turns hit the output cap mid-reasoning "
            f"(`finish_reason=length`); the tool-less closing call finished in "
            f"{closing_ok}/{total}."
        )
        if emitted != applied:
            findings.append(
                f"{emitted - applied}/{emitted} emitted proposal(s) were **rejected** on "
                f"apply (see each scenario's `apply_errors`) — a proposal the model wrote "
                f"never reached the store."
            )
    return {
        "scenarios": total,
        "directional": directional,
        "proposed": proposed,
        "aligned": aligned,
        "proposals_emitted": emitted,
        "proposals_applied": applied,
        "scenarios_with_runaway": ran_away,
        "scenarios_with_closing_recovery": closing_ok,
        "scenarios_truncated": truncated,
        "proposal_outcomes": outcomes,
        "findings": findings,
    }


def markdown_report(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    head = report["run"]
    lines.append("# CRT agent backtest")
    lines.append("")
    lines.append(f"- generated: {head['generated_at']}")
    lines.append(f"- symbol: `{head['symbol']}`   timeframe: `{head['timeframe']}`")
    lines.append(f"- mode: `{head['mode']}`   model: `{head.get('model') or '—'}`")
    lines.append(f"- scan: last {head['days']:.0f} days of data, min R:R {head['min_rr']}, "
                 f"top {head['scenarios']}")
    lines.append("")
    summary = report.get("summary") or {}
    if summary:
        lines.append("## Summary")
        lines.append("")
        for finding in summary.get("findings") or []:
            lines.append(f"- {finding}")
        if summary.get("proposal_outcomes"):
            lines.append(f"- proposed-trade outcomes: {summary['proposal_outcomes']}")
        lines.append("")
    for i, scenario in enumerate(report["scenarios"], start=1):
        cand = scenario["candidate"]
        verdict = scenario["verdict"]
        replay = scenario["replay"]
        lines.append(f"## Scenario {i} — classic {cand['direction']} CRT @ {cand['timeframe']}")
        lines.append("")
        lines.append(f"- anchor `{cand['anchor_time']}` → manipulation `{cand['manipulation_time']}` "
                     f"(decision `{cand['decision_time']}`)")
        lines.append(f"- range {_fmt(cand['crl'])}–{_fmt(cand['crh'])}, swept {_fmt(cand['swept_level'])}, "
                     f"target {_fmt(cand['target_level'])}, range {cand['range_atr']:.2f}×ATR")
        lines.append(f"- resolved at `{cand['distribution_time']}` in {cand['bars_to_target']} bars "
                     f"({cand['state']})")
        lines.append(f"- naive trade entry {_fmt(cand['entry'])} / stop {_fmt(cand['stop'])} / "
                     f"target {_fmt(cand['target'])} → R:R {cand['rr']:.2f}")
        lines.append("")
        lines.append(f"**Agent** (`{replay['reason'] or 'ok'}`, {replay['tokens']} tokens, "
                     f"${replay['cost_usd']:.4f}, {replay['tool_calls']} tool calls)")
        diag = scenario.get("diagnosis") or {}
        lines.append("")
        lines.append(f"- diagnosis: bias={diag.get('bias')!r} directional={diag.get('directional')} "
                     f"proposed={diag.get('proposed')} · {diag.get('model_calls')} model calls, "
                     f"{diag.get('ran_away_calls')} ran away (`length`), "
                     f"closing call used={diag.get('closing_call_used')} "
                     f"finished={diag.get('closing_call_finished')} · "
                     f"peak prompt {diag.get('max_prompt_tokens')} tok, "
                     f"{diag.get('completion_tokens')} completion tok")
        if diag.get("proposals_emitted"):
            lines.append(f"- proposals: {diag.get('proposals_emitted')} emitted, "
                         f"{diag.get('proposals_applied')} applied")
        for error in diag.get("apply_errors") or []:
            lines.append(f"    - **apply error**: {error}")
        lines.append("")
        lines.append(f"- perception: first view `{(replay.get('initial_view') or {}).get('timeframe')}` "
                     f"families={(replay.get('initial_view') or {}).get('families')}; "
                     f"final view `{(replay.get('view') or {}).get('timeframe')}` "
                     f"families={(replay.get('view') or {}).get('families')}")
        for entry in replay.get("tool_log") or []:
            args = ", ".join(f"{k}={v}" for k, v in (entry.get("arguments") or {}).items())
            err = f" ERROR: {entry['error']}" if entry.get("error") else ""
            lines.append(f"    - tool `{entry['name']}` ok={entry['ok']} ({args}){err}")
        for call in replay.get("model_calls") or []:
            lines.append(f"    - call #{call['index']} finish=`{call['finish_reason']}` "
                         f"image={call.get('has_image')} tools_offered={call.get('tools_offered')} "
                         f"asked={call['tool_calls']} tokens={call['tokens']}")
        voiced = [c for c in (replay.get("model_calls") or []) if c.get("text")]
        if voiced:
            lines.append("")
            lines.append("<details><summary>last model text</summary>")
            lines.append("")
            lines.append("```")
            lines.append(voiced[-1]["text"])
            lines.append("```")
            lines.append("</details>")
        lines.append("")
        thesis = replay["thesis"]
        lines.append(f"- bias: **{thesis.get('bias')}** (confidence {thesis.get('confidence')})")
        lines.append(f"- storyline: {thesis.get('storyline') or '—'}")
        lines.append(f"- invalidation: {thesis.get('invalidation') or '—'}")
        lines.append(f"- thesis aligned with the CRT: **{verdict['thesis_aligned']}**")
        if replay["subscriptions"]:
            lines.append(f"- watches/pins: {len(replay['subscriptions'])}")
            for sub in replay["subscriptions"][:6]:
                lines.append(f"    - `{sub['kind']}` {sub['condition']} — {sub['reason']}")
        if verdict["proposals"]:
            lines.append("")
            lines.append("| proposal | entry | sl | tp | aligned | outcome | bars | R |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
            for prop in verdict["proposals"]:
                sim = prop["sim"]
                lines.append(
                    f"| {prop['bias']} | {_fmt(prop['entry'])} | {_fmt(prop['sl'])} | "
                    f"{_fmt(prop['tp'])} | {prop['aligned']} | {sim['outcome']} | "
                    f"{sim['bars_to_event'] if sim['bars_to_event'] is not None else '—'} | "
                    f"{_fmt(sim['r_multiple'], 2)} |"
                )
        else:
            lines.append("- no proposal was emitted")
        if scenario.get("artifacts", {}).get("crt_chart"):
            lines.append("")
            lines.append(f"- CRT chart: `{scenario['artifacts']['crt_chart']}`")
        if scenario.get("artifacts", {}).get("agent_render"):
            lines.append(f"- agent render: `{scenario['artifacts']['agent_render']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def print_summary(report: Dict[str, Any]) -> None:
    head = report["run"]
    print("")
    print("=" * 78)
    print(f"CRT BACKTEST  {head['symbol']} {head['timeframe']}  "
          f"mode={head['mode']} model={head.get('model') or '—'}")
    print("=" * 78)
    for finding in (report.get("summary") or {}).get("findings") or []:
        print(f"  {finding}")
    for i, scenario in enumerate(report["scenarios"], start=1):
        cand, replay, verdict = scenario["candidate"], scenario["replay"], scenario["verdict"]
        print("")
        print(f"scenario {i}: classic {cand['direction'].upper()} CRT "
              f"[{cand['timeframe']}] decision {cand['decision_time']}")
        print(f"  range {cand['crl']:.3f}-{cand['crh']:.3f}  swept {cand['swept_level']:.3f}  "
              f"target {cand['target_level']:.3f}  ({cand['range_atr']:.2f}xATR)  "
              f"resolved in {cand['bars_to_target']} bars")
        print(f"  naive trade R:R {cand['rr']:.2f}")
        print(f"  agent: ok={replay['ok']} reason={replay['reason']!r} "
              f"tokens={replay['tokens']} cost=${replay['cost_usd']:.4f}")
        diag = scenario.get("diagnosis") or {}
        print(f"  diagnosis: bias={diag.get('bias')!r} directional={diag.get('directional')} "
              f"proposed={diag.get('proposed')} calls={diag.get('model_calls')} "
              f"ran_away={diag.get('ran_away_calls')} peak_prompt={diag.get('max_prompt_tokens')}")
        for error in diag.get("apply_errors") or []:
            print(f"  apply error: {error}")
        thesis = replay["thesis"]
        print(f"  thesis: bias={thesis.get('bias')!r} conf={thesis.get('confidence')} "
              f"aligned={verdict['thesis_aligned']}")
        story = (thesis.get("storyline") or "").strip()
        if story:
            print(f"    {story[:300]}")
        if verdict["proposals"]:
            for prop in verdict["proposals"]:
                sim = prop["sim"]
                print(f"  proposal {prop['bias']}: {prop['entry']}/{prop['sl']}/{prop['tp']} "
                      f"aligned={prop['aligned']} -> {sim['outcome']} "
                      f"({sim['bars_to_event']} bars, R={sim['r_multiple']})")
        else:
            print("  proposal: none")
    print("")
    print(f"report: {report['run']['report_json']}")
    print(f"        {report['run']['report_md']}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def _rebuild_report(path: str) -> int:
    """Re-render the report from a saved run — no model, no data, no spend.

    The raw turn records (every model call, the tool log, the output and its
    ``apply_errors``) all live in ``report.json``, so a report can be rebuilt and
    the findings reworded without replaying a single turn.
    """
    path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    for scenario in report.get("scenarios", []):
        scenario["diagnosis"] = diagnose(scenario.get("replay") or {})
    report["summary"] = summarise(report.get("scenarios", []))
    run = report.setdefault("run", {})
    run["report_json"] = path
    run["report_md"] = os.path.join(os.path.dirname(path), "report.md")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    with open(run["report_md"], "w", encoding="utf-8") as handle:
        handle.write(markdown_report(report))
    print_summary(report)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    # Windows consoles default to cp1252 and blow up on the arrows/maths glyphs
    # this report uses; force UTF-8 rather than sprinkle ASCII everywhere.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.report_only:
        return _rebuild_report(args.report_only)
    os.makedirs(args.out, exist_ok=True)
    # Every run gets a brand-new root: a resumed store would seed the replay with
    # the *previous* run's view and silently change what the agent saw first.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = os.path.join(args.out, f"run_{run_id}")
    os.makedirs(run_root, exist_ok=True)
    cache = args.cache or os.path.join(args.out, "history.pkl")
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    # -- connection ---------------------------------------------------------- #
    if args.mode == "live":
        conn = resolve_live_connection()
        if args.model:
            conn["model"] = str(args.model)
        health = proxy_health(conn["api_base"])
        if health is None and ("localhost" in conn["api_base"] or "127.0.0.1" in conn["api_base"]):
            print(f"ERROR: the local endpoint {conn['api_base']} is not answering /health.\n"
                  f"       Start the proxy first (see go-proxy/proxy/start-proxy.cmd).",
                  file=sys.stderr)
            return 2
        print(f"provider={conn['provider']} model={conn['model']} base={conn['api_base']}")
    else:
        conn = {"provider": "", "api_base": "", "model": "", "api_key_env": ""}
        print("mock mode: zero-spend scripted agent")

    # -- data ---------------------------------------------------------------- #
    print(f"loading history for {args.symbol} ({', '.join(timeframes)})…", flush=True)
    symbol, frames = load_or_fetch(
        args.symbol, cache=cache, refresh=args.refresh,
        timeframes=timeframes, max_bars=args.max_bars,
    )
    tf = args.timeframe.upper()
    if tf not in frames:
        print(f"ERROR: no {tf} history loaded (have: {sorted(frames)})", file=sys.stderr)
        return 2
    scan_frame = frames[tf]
    last_bar = scan_frame.index[-1]
    since = last_bar - pd.Timedelta(days=float(args.days))
    print(f"loaded {len(scan_frame)} {tf} bars, last {last_bar.isoformat()}")

    # -- scan ---------------------------------------------------------------- #
    candidates = crt_scan.scan_classic_crts(
        scan_frame, tf, since=since, min_rr=float(args.min_rr), top=int(args.scenarios)
    )
    print(f"found {len(candidates)} classic resolved CRT(s) at R:R ≥ {args.min_rr} "
          f"in the last {args.days:.0f} days")
    if not candidates:
        print("nothing to replay — lower --min-rr or widen --days", file=sys.stderr)
        return 1

    # -- replay -------------------------------------------------------------- #
    scenarios: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        print("")
        print(f"--- scenario {index + 1}/{len(candidates)}: {candidate.describe()}")
        as_of = pd.Timestamp(candidate.decision_time)
        loader = FrozenLoader(symbol, frames, as_of)

        artifacts: Dict[str, Any] = {}
        chart, manifest, levels = render_crt_chart(loader, symbol, tf, args.bars, run_root)
        artifacts["crt_chart"] = chart
        artifacts["crt_levels"] = levels
        print(f"  CRT chart: {chart}  ({len(levels)} crt levels in the frozen window)")

        replay_result: Dict[str, Any] = {
            "ok": False, "reason": "dry-run (no model called)", "thesis": {},
            "proposals": [], "subscriptions": [], "tokens": 0, "cost_usd": 0.0,
            "tool_calls": 0, "renders": 0, "trigger": "", "turns": 0, "view": {},
            "image_path": "", "render_id": "", "output": {}, "first_render_path": "",
            "initial_view": {}, "model_calls": [], "tool_log": [],
        }
        if not args.dry_run:
            if index > 0 and args.mode == "live":
                pace(args.cooldown_s, "between live scenarios")
            replay = run_replay(
                loader,
                symbol=symbol,
                model=conn["model"],
                api_base=conn["api_base"],
                api_key_env=conn["api_key_env"],
                timeframe=tf,
                bars=int(args.bars),
                max_tokens=int(args.max_tokens),
                mode=args.mode,
                message=args.message,
                families=[f.strip() for f in args.families.split(",") if f.strip()],
                workdir=os.path.join(run_root, f"scenario_{index + 1}"),
            )
            replay_result = replay.to_dict()
            artifacts["agent_render"] = replay.first_render_path or replay.image_path

        verdict = score(candidate, replay_result["thesis"], replay_result["proposals"], scan_frame)
        scenarios.append(
            {
                "candidate": candidate.to_dict(),
                "replay": replay_result,
                "verdict": verdict.to_dict(),
                "diagnosis": diagnose(replay_result),
                "artifacts": artifacts,
            }
        )

    # -- report -------------------------------------------------------------- #
    stamp = datetime.now(timezone.utc).isoformat()
    report_json = os.path.join(run_root, "report.json")
    report_md = os.path.join(run_root, "report.md")
    report = {
        "run": {
            "generated_at": stamp,
            "symbol": symbol,
            "timeframe": tf,
            "mode": args.mode,
            "model": conn["model"],
            "provider": conn["provider"],
            "api_base": conn["api_base"],
            "days": float(args.days),
            "min_rr": float(args.min_rr),
            "scenarios": len(scenarios),
            "dry_run": bool(args.dry_run),
            "run_dir": run_root,
            "report_json": report_json,
            "report_md": report_md,
        },
        "scenarios": scenarios,
        "summary": summarise(scenarios),
    }
    with open(report_json, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    with open(report_md, "w", encoding="utf-8") as handle:
        handle.write(markdown_report(report))
    print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
