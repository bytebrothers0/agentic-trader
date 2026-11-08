"""
backtest/run_alchemist_backtest.py — replay the Alchemist MNSR playbook on real
history, every setup, win or lose.

    python -m backtest.run_alchemist_backtest \
        --since 2026-10-01 --until 2026-10-22 --timeframe M15

What it does, in order:

1. **Load** deep MT5 history (cached; ``--refresh`` re-pulls from the terminal).
2. **Scan** the window for Alchemist arcs (``alchemist_scan``: pool sweep ->
   body-close MSS -> premium/discount POI limit) and price each as the
   playbook's naive trade (POI limit / wick-tip stop + 0.3 ATR / nearest
   opposing swing). **Every** setup is kept — wins and losses — and each is
   scored deterministically bar-by-bar (``replay.simulate``: pending fill,
   stop-taken on one-bar ambiguity, ``r_mark`` for still-open trades).
3. **Replay** one real agent turn at each setup's decision instant (the MSS
   close) on a feed frozen there, with the real detectors — the same
   loader-swap fidelity the CRT backtest ships.
4. **Report** ``report.json`` + ``report.md``: the setups table (outcome and
   R per setup), the agent's read per scenario, and an aggregate summary.

Rate-limit safety and zero-spend modes are inherited: live turns run
sequentially behind a proxy ``/health`` gate; ``--mode mock`` spends nothing;
``--dry-run`` scans and reports without calling a model at all.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest import alchemist_scan
from backtest.alchemist_scan import AlchemistCandidate
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
    simulate,
)

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_alc")
DEFAULT_SINCE = "2026-10-01"
DEFAULT_UNTIL = "2026-10-22"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m backtest.run_alchemist_backtest",
        description="Replay the agentic agent on historical Alchemist MNSR setups — "
                    "every setup in the window, whether it won or lost.",
    )
    p.add_argument("--symbol", default="XAUUSDm", help="MT5 symbol (default XAUUSDm)")
    p.add_argument("--timeframe", default="M15", help="timeframe to scan and to show the agent")
    p.add_argument("--since", default=DEFAULT_SINCE,
                   help="scan window start, ISO date/time (default 2026-10-01)")
    p.add_argument("--until", default=DEFAULT_UNTIL,
                   help="scan window end, ISO date/time inclusive (default 2026-10-22)")
    p.add_argument("--min-rr", type=float, default=alchemist_scan.RR_FLOOR,
                   help="flag setups below this R:R as playbook-failures rather than drop them "
                        "(default 1.0 — nothing is silently dropped)")
    p.add_argument("--max-scenarios", type=int, default=0,
                   help="replay at most N scenarios (0 = every setup)")
    p.add_argument("--bars", type=int, default=None,
                   help="agent view bars (default: the shipped AGENT_BARS)")
    p.add_argument("--max-tokens", type=int, default=None,
                   help="per-call output cap (default: the shipped AGENT_MAX_TOKENS)")
    p.add_argument("--model", default="", help="override the provider's model (else LLM_PROVIDER's)")
    p.add_argument("--mode", default="live", choices=["live", "mock"],
                   help="live = real model; mock = zero-spend scripted agent")
    p.add_argument("--message", default="",
                   help="run a human 'request' turn with this detail instead of a boot turn")
    p.add_argument("--families", default="liquidity,sr,bos",
                   help="comma-separated families for the seeded view (default the playbook's "
                        "Phase-0 trio)")
    p.add_argument("--cooldown-s", type=float, default=10.0,
                   help="pause between live scenarios (rate-limit safety)")
    p.add_argument("--cache", default="", help="history cache path (default <out>/history.pkl)")
    p.add_argument("--refresh", action="store_true", help="ignore an existing cache and re-fetch")
    p.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    p.add_argument("--dry-run", action="store_true",
                   help="scan + score + render only; never call a model")
    p.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES),
                   help="history timeframes to preload")
    p.add_argument("--max-bars", type=int, default=DEFAULT_MAX_BARS,
                   help="max bars to load per timeframe")
    p.add_argument("--report-only", default="",
                   help="rebuild report.json/report.md from a saved run (no model, no data)")
    return p


# --------------------------------------------------------------------------- #
# Rendering the setup view
# --------------------------------------------------------------------------- #

def render_setup_chart(loader: FrozenLoader, symbol: str, timeframe: str,
                       families: List[str], bars: int, out_dir: str):
    """Render the setup window the playbook's Phase-0 families; return (path, manifest, levels)."""
    from agentic.renderer import Renderer

    with frozen_server(loader):
        feed = build_feed(loader)
        snapshot = feed.snapshot(symbol, timeframe, families=families, bars=bars)
        series = feed.bars(symbol, timeframe, bars=bars)
        renderer = Renderer(width=896, height=504, out_dir=out_dir, max_bars_per_pane=5000)
        result = renderer.render(snapshot, series, out_dir=out_dir)
        levels = [lvl.to_dict() for lvl in snapshot.levels]
    return result.image_path, result.manifest, levels


# --------------------------------------------------------------------------- #
# The deterministic audit: every setup's own outcome
# --------------------------------------------------------------------------- #

def audit_setups(candidates: List[AlchemistCandidate], scan_frame: pd.DataFrame,
                 until: pd.Timestamp, min_rr: float) -> List[Dict[str, Any]]:
    """Score every setup as a pending-limit trade and append its own verdict."""
    end_pos = len(scan_frame) - 1
    for ts_pos, ts in enumerate(scan_frame.index):
        if pd.Timestamp(ts) > until:
            end_pos = max(0, ts_pos - 1)
            break
    audited: List[Dict[str, Any]] = []
    for cand in candidates:
        forward = scan_frame.iloc[cand.shift_index + 1: end_pos + 1]
        sim = simulate(forward, cand.direction, cand.entry, cand.stop, cand.target)
        row = cand.to_dict()
        row["outcome"] = sim.outcome
        row["outcome_reason"] = sim.reason
        row["r_multiple"] = sim.r_multiple if sim.r_multiple is not None else sim.r_mark
        row["rr_floor_meets"] = cand.rr >= float(min_rr)
        audited.append(row)
    return audited


def summarise_audits(audits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The scoreboard the user asked for: how many setups, how many won/lost."""
    outcomes: Dict[str, int] = {}
    total_r = 0.0
    scored = 0
    for row in audits:
        outcome = str(row.get("outcome") or "?")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        r = row.get("r_multiple")
        if isinstance(r, (int, float)):
            total_r += float(r)
            scored += 1
    wins = outcomes.get("tp", 0)
    losses = outcomes.get("sl", 0) + outcomes.get("ambiguous", 0)
    decided = wins + losses
    findings: List[str] = []
    if audits:
        findings.append(f"{len(audits)} Alchemist setups in the window: "
                        f"{wins} wins, {losses} losses, "
                        f"{outcomes.get('open', 0)} still open, "
                        f"{outcomes.get('unfilled', 0)} never touched.")
        if decided:
            findings.append(f"win rate {wins / decided * 100:.0f}% on decided trades; "
                            f"total {total_r:+.2f}R across {scored} measured trades.")
        findings.append(
            f"{sum(1 for a in audits if not a.get('rr_floor_meets'))} setup(s) sit below the "
            f"playbook's 1:1.5 R:R floor — places the agent should not have proposed."
        )
    return {"setups": len(audits), "outcomes": outcomes, "total_r": round(total_r, 2),
            "win_rate": (round(wins / decided, 3) if decided else None), "findings": findings}


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def markdown_report(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    head = report["run"]
    lines.append("# Alchemist MNSR backtest")
    lines.append("")
    lines.append(f"- generated: {head['generated_at']}")
    lines.append(f"- symbol: `{head['symbol']}`   timeframe: `{head['timeframe']}`")
    lines.append(f"- window: {head['since']} .. {head['until']} (UTC)")
    lines.append(f"- mode: `{head['mode']}`   model: `{head.get('model') or '—'}`")
    lines.append("")
    summary = report.get("summary") or {}
    if summary.get("findings"):
        lines.append("## Summary")
        lines.append("")
        for finding in summary.get("findings"):
            lines.append(f"- {finding}")
        lines.append("")
    lines.append("## Skip ledger (arcs refused by the playbook's own filters)")
    lines.append("")
    lines.append("| time (UTC) | dir | pool | refused |")
    lines.append("| --- | --- | --- | --- |")
    for skip in report.get("skips") or []:
        lines.append(f"| {skip['time'][:16]} | {skip['direction']} | {skip['pool_price']} | {skip['reason']} |")
    lines.append("")
    lines.append("## All setups (win or lose)")
    lines.append("")
    lines.append("| # | dir | swept pool | sweep -> shift | limit POI | entry/SL/TP | RR | outcome | R |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, row in enumerate(report.get("audits") or [], start=1):
        lines.append(
            f"| {i} | {row['direction']} | {row['pool_price']} | {row['sweep_time'][:16]} → "
            f"{row['shift_time'][:16]} | {row['poi_kind']} {row['poi_price']} | "
            f"{row['entry']}/{row['stop']}/{row['target']} | {row['rr']:.2f} | "
            f"**{row['outcome']}** | {row['r_multiple']} |"
        )
    lines.append("")
    for i, scenario in enumerate(report.get("scenarios") or [], start=1):
        cand = scenario["candidate"]
        verdict = scenario["verdict"]
        replay = scenario["replay"]
        lines.append(f"## Scenario {i} — {cand['direction']} arc @ {cand['timeframe']}")
        lines.append("")
        lines.append(f"- sweep `{cand['sweep_time']}` (pool {cand['pool_price']}, extreme "
                     f"{cand['sweep_extreme']}) → shift `{cand['shift_time']}` "
                     f"(decision instant)")
        lines.append(f"- naive limit {cand['poi_kind']} {cand['entry']} / stop {cand['stop']} "
                     f"({cand['stop_distance_pips']} pips) / target {cand['target']} "
                     f"→ R:R {cand['rr']:.2f}, own outcome **{scenario['audit']['outcome']}** "
                     f"R {scenario['audit']['r_multiple']}")
        lines.append("")
        lines.append(f"**Agent** (`{replay['reason'] or 'ok'}`, {replay['tokens']} tokens, "
                     f"${replay['cost_usd']:.4f}, {replay['tool_calls']} tool calls)")
        diag = scenario.get("diagnosis") or {}
        lines.append("")
        lines.append(f"- diagnosis: bias={diag.get('bias')!r} directional={diag.get('directional')} "
                     f"proposed={diag.get('proposed')} · {diag.get('model_calls')} calls, "
                     f"{diag.get('ran_away_calls')} runaway, peak prompt "
                     f"{diag.get('max_prompt_tokens')} tok")
        for error in diag.get("apply_errors") or []:
            lines.append(f"    - **apply error**: {error}")
        lines.append("")
        thesis = replay["thesis"]
        lines.append(f"- bias: **{thesis.get('bias')}** (confidence {thesis.get('confidence')})")
        story = (thesis.get("storyline") or "").strip()
        if story:
            lines.append(f"- storyline: {story[:400]}")
        aligned = "\n".join(
            f"    - proposal {prop['bias']} {prop['entry']}/{prop['sl']}/{prop['tp']} "
            f"aligned={prop['aligned']} → {prop['sim']['outcome']} "
            f"(R {prop['sim']['r_multiple']}, bars {prop['sim']['bars_to_event']})"
            for prop in verdict["proposals"] or []
        )
        if aligned:
            lines.append("- agent proposals:")
            lines.append(aligned)
        else:
            lines.append("- no proposal was emitted")
        if scenario.get("artifacts", {}).get("setup_chart"):
            lines.append(f"- setup chart: `{scenario['artifacts']['setup_chart']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def print_summary(report: Dict[str, Any]) -> None:
    head = report["run"]
    print("")
    print("=" * 78)
    print(f"ALCHEMIST BACKTEST  {head['symbol']} {head['timeframe']}")
    print(f"window {head['since']} .. {head['until']}  mode={head['mode']} "
          f"model={head.get('model') or '—'}")
    print("=" * 78)
    for finding in (report.get("summary") or {}).get("findings") or []:
        print(f"  {finding}")
    audits = report.get("audits") or []
    print("")
    print(f"  {'#':>3}  {'dir':7} {'decision':19} {'limit':>9} {'stop':>9} {'target':>9} "
          f"{'RR':>5}  {'outcome':9} {'R':>6}")
    for i, row in enumerate(audits, start=1):
        print(f"  {i:>3}  {row['direction']:7} {row['shift_time'][:19]} {row['entry']:>9} "
              f"{row['stop']:>9} {row['target']:>9} {row['rr']:>5.2f}  "
              f"{row['outcome']:9} {_fmt(row['r_multiple'], 2):>6}")
    skips = report.get("skips") or []
    if skips:
        print("")
        print(f"  skip ledger — {len(skips)} arc(s) the playbook refused by its own filters:")
        for skip in skips:
            print(f"    {skip['time'][:19]}  {skip['direction']:7} pool {skip['pool_price']:<10} {skip['reason']}")
    for i, scenario in enumerate(report.get("scenarios") or [], start=1):
        cand = scenario["candidate"]
        replay = scenario["replay"]
        diag = scenario.get("diagnosis") or {}
        print("")
        print(f"agent scenario {i}: {cand['direction'].upper()} arc decided "
              f"{cand['decision_time']}")
        print(f"  own trade: {cand['entry']}/{cand['stop']}/{cand['target']} "
              f"RR {cand['rr']:.2f} -> {scenario['audit']['outcome']} "
              f"(R {scenario['audit']['r_multiple']})")
        print(f"  agent: ok={replay['ok']} reason={replay['reason']!r} "
              f"tokens={replay['tokens']} cost=${replay['cost_usd']:.4f} "
              f"proposed={diag.get('proposed')}")
        thesis = replay["thesis"]
        story = (thesis.get("storyline") or "").strip()
        if story:
            print(f"  thesis: bias={thesis.get('bias')!r} conf={thesis.get('confidence')} · "
                  f"{story[:200]}")
    print("")
    print(f"report: {report['run']['report_json']}")
    print(f"        {report['run']['report_md']}")


def _rebuild_report(path: str) -> int:
    """Re-render the report from a saved run — no model, no data, no spend."""
    path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    for scenario in report.get("scenarios", []):
        scenario["diagnosis"] = diagnose(scenario.get("replay") or {})
    report["summary"] = summarise_audits(report.get("audits") or [])
    report["summary"].setdefault("findings", [])
    run = report.setdefault("run", {})
    run["report_json"] = path
    run["report_md"] = os.path.join(os.path.dirname(path), "report.md")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    with open(run["report_md"], "w", encoding="utf-8") as handle:
        handle.write(markdown_report(report))
    print_summary(report)
    return 0


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.report_only:
        return _rebuild_report(args.report_only)
    if args.bars is None or args.max_tokens is None:
        from config.settings import AGENT_BARS, AGENT_MAX_TOKENS

        args.bars = int(args.bars if args.bars is not None else AGENT_BARS)
        args.max_tokens = int(args.max_tokens if args.max_tokens is not None else AGENT_MAX_TOKENS)
    os.makedirs(args.out, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = os.path.join(args.out, f"run_{run_id}")
    os.makedirs(run_root, exist_ok=True)
    cache = args.cache or os.path.join(args.out, "history.pkl")
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    since = pd.Timestamp(args.since, tz="UTC")
    until = pd.Timestamp(args.until, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    # -- connection ---------------------------------------------------------- #
    if args.mode == "live":
        conn = resolve_live_connection()
        if args.model:
            conn["model"] = str(args.model)
        health = proxy_health(conn["api_base"])
        if health is None:
            print(f"ERROR: the endpoint {conn['api_base']} is not answering /health.\n"
                  f"       Start the proxy first, or rerun with --mode mock.",
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
    print(f"loaded {len(scan_frame)} {tf} bars, "
          f"{scan_frame.index[0].isoformat()} .. {scan_frame.index[-1].isoformat()}")

    # -- scan ---------------------------------------------------------------- #
    candidates, skips = alchemist_scan.scan_alchemist_setups(
        scan_frame, tf, since=since, until=until
    )
    # The decision bar must leave room for a frozen perception: older than 180
    # bars back per the loaded window is fine — the frozen loader serves the
    # count it holds. Deep-window setups with too little preceding history are
    # dropped naturally by the loader's InsufficientHistory; no extra filter.
    candidates.sort(key=lambda c: c.shift_index)
    print(f"found {len(candidates)} placeable Alchemist setup(s) "
          f"{since.isoformat()} .. {until.isoformat()}")
    skip_counts: Dict[str, int] = {}
    for skip in skips:
        reason = skip["reason"].split(" (")[0]
        skip_counts[reason] = skip_counts.get(reason, 0) + 1
    if skips:
        print(f"  plus {len(skips)} arc(s) the playbook refused after its own "
              f"filters: {skip_counts}")
    if not candidates:
        print("nothing to replay — widen the window or loosen the arc", file=sys.stderr)
        return 1

    audits = audit_setups(candidates, scan_frame, until, float(args.min_rr))
    summary = summarise_audits(audits)
    for finding in summary.get("findings") or []:
        print(f"  {finding}")

    # -- replay -------------------------------------------------------------- #
    scenarios: List[Dict[str, Any]] = []
    to_replay = candidates if int(args.max_scenarios) <= 0 else candidates[: int(args.max_scenarios)]
    for index, candidate in enumerate(to_replay):
        print("")
        print(f"--- scenario {index + 1}/{len(to_replay)}: {candidate.describe()}")
        as_of = pd.Timestamp(candidate.decision_time)
        loader = FrozenLoader(symbol, frames, as_of)
        families = [f.strip() for f in args.families.split(",") if f.strip()]

        artifacts: Dict[str, Any] = {}
        chart, manifest, levels = render_setup_chart(
            loader, symbol, tf, families, args.bars, run_root
        )
        artifacts["setup_chart"] = chart
        artifacts["setup_levels"] = levels
        print(f"  setup chart: {chart}  ({len(levels)} levels in the frozen window)")

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
                families=families,
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
                "audit": audits[index],
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
            "since": args.since,
            "until": args.until,
            "min_rr": float(args.min_rr),
            "scenarios": len(scenarios),
            "bars": int(args.bars),
            "max_tokens": int(args.max_tokens),
            "families": families,
            "dry_run": bool(args.dry_run),
            "run_dir": run_root,
            "report_json": report_json,
            "report_md": report_md,
        },
        "audits": audits,
        "skips": skips,
        "scenarios": scenarios,
        "summary": summary,
    }
    with open(report_json, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    with open(report_md, "w", encoding="utf-8") as handle:
        handle.write(markdown_report(report))
    print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
