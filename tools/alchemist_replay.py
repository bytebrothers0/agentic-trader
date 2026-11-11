"""tools/alchemist_replay.py — replay historical XAUUSD windows through the agent.

The operator's backtest design (docs/specs/2026-11-11-alchemist-mnsr-design.md):
for each replay window the agent's WHOLE perception is time-shifted — the feed
provider wrapper forces ``offset`` so the briefing, ``set_view`` and renders all
show the historical window (no look-ahead: the agent never sees data after the
cutoff) — then asks for a directional call per the Alchemist MSNR loop. The
harness resolves the realized outcome from ACTUAL candles after the cutoff and
scores outcome agreement (a win is a win, a loss is a loss).

Isolation: the live store is COPIED into the run dir (the operator's server and
state are untouched). Provider: the shared local provider from ``.env`` ($0),
retried with 60 s backoff on gateway drops.

Usage:
    python tools/alchemist_replay.py                       # default battery
    python tools/alchemist_replay.py --status-filter live  # fresh-only POC arm
    python tools/alchemist_replay.py --days 5 --label poc-fresh

Output: docs/research/2026-11-11-alchemist-mnsr/<stamp>-<label>/
    replay.md    per-window calls vs realized outcomes + the agreement table
    renders/*.png  each window's chart, for manual verification
    state/       the copied store with this run's turns appended
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESEARCH_DIR = os.path.join(ROOT, "docs", "research", "2026-11-11-alchemist-mnsr")
SYMBOL = "XAUUSDm"

#: Replay prompt: the Alchemist loop, no future knowledge, explicit horizon,
#: and a tool budget that fits the chat leash (the loop allows few rounds —
#: spend them on ONE split view + ONE render, then answer completely).
#: Simplified replay prompt: text-first, single lean set_view, tight budget
#: so the free provider can actually complete the turn.
#: Replay prompt: lean tool set — ONE set_view (M15 + D1, bars=120) for the
#: split view, ONE level_lookup for the key POI price, then a complete answer.
#: No render (it balloons the briefing and chokes the free provider on
#: H4-scale turns), no invented numbers — every price must come from a tool.
REPLAY_PROMPT = (
    "You are analysing the chart as it stands right now (the data you see is "
    "your present; you know nothing about the future). Keep tool use tight: "
    "ONE set_view covering your two most important timeframes (bars=120), and "
    "at most ONE level_lookup for the exact price of the key POI you decide "
    "on. Then answer completely in a single final message — do not narrate "
    "intermediate steps, and never invent a price: every number you state must "
    "come from a tool result this turn.\n\n"
    "Walk the Alchemist MSNR loop: storyline per timeframe, the POIs that "
    "matter now, and the session script (Asia consolidates, London "
    "manipulates, New York delivers). Then give me your call: for the next few "
    "hours, is gold more likely to move UP or DOWN from where it is now, the "
    "trade you would plan (entry, stop, target), and what invalidation kills "
    "it. End with exactly one of: 'CALL: UP', 'CALL: DOWN', or 'CALL: "
    "NO-TRADE' (if the frames genuinely disagree)."
)


def _force_offset_provider(forced_offset: int, base_provider):
    """Wrap the real provider so EVERY perception lands ``forced_offset`` bars back.

    The loop's set_view/render/level lookups all go through this provider, so
    the agent cannot accidentally (or deliberately) look ahead: any offset it
    requests is clamped to >= forced_offset, i.e. never fresher than the cutoff.
    """
    def provider(*, symbol, timeframe, families=None, bars=300, offset=0, **kwargs):
        merged = max(int(offset or 0), forced_offset)
        payload = base_provider(
            symbol=symbol, timeframe=timeframe, families=families,
            bars=bars, offset=merged, **kwargs,
        )
        payload["replay_offset"] = merged
        return payload
    return provider


def _exact_offsets(cutoff: datetime) -> dict:
    """EXACT per-timeframe offsets: the bars that exist AFTER the cutoff.

    ``offset`` semantics are "skip this many bars back from the present", so the
    replay clamp must count the bars NEWER than the cutoff — counting bars
    before it would send the perception months back instead of to the cutoff.
    Each timeframe's real candle history is counted once here; the provider
    wrapper then clamps every request to these values (never fresher than the
    cutoff: no look-ahead, guaranteed by construction).
    """
    from data.mt5_loader import MT5DataLoader

    offsets = {}
    loader = MT5DataLoader(symbol=SYMBOL)
    loader.connect()
    try:
        for tf in ("M5", "M15", "H1", "H4", "D1"):
            try:
                df = loader.fetch_timeframe(tf, count=2000, start=0)
                idx = df.index.tz_localize("UTC") if df.index.tz is None else df.index
                offsets[tf] = int((idx > cutoff).sum())
            except Exception:  # noqa: BLE001 — TF unavailable: fall back to 0-clamp
                offsets[tf] = 0
    finally:
        loader.disconnect()
    return offsets


def _force_offset_provider(offsets: dict, base_provider):
    """Wrap the real provider so EVERY perception lands at-or-before the cutoff.

    ``offsets`` maps timeframe -> exact bars-back. Any offset the agent requests
    is clamped to >= the per-timeframe forced value: it can look FURTHER back
    (deeper history for context) but never fresher than the cutoff.
    """
    def provider(*, symbol, timeframe, families=None, bars=300, offset=0, **kwargs):
        tf = str(timeframe).upper()
        forced = offsets.get(tf, offsets.get("M15", 0))
        merged = max(int(offset or 0), forced)
        payload = base_provider(
            symbol=symbol, timeframe=timeframe, families=families,
            bars=bars, offset=merged, **kwargs,
        )
        payload["replay_offset"] = merged
        return payload
    return provider


def _realized_direction(cutoff: datetime, horizon: datetime) -> tuple[str, float, float]:
    """UP/DOWN/FLAT from ACTUAL candles: close at cutoff vs close at horizon."""
    from data.mt5_loader import MT5DataLoader

    loader = MT5DataLoader(symbol=SYMBOL)
    loader.connect()
    try:
        df = loader.fetch_timeframe("M15", count=2000, start=0)
    finally:
        loader.disconnect()
    # The loader returns a tz-aware DatetimeIndex (name 'datetime').
    idx = df.index.tz_localize("UTC") if df.index.tz is None else df.index
    cutoff_mask = idx <= cutoff
    horizon_mask = idx <= horizon
    if not cutoff_mask.any() or not horizon_mask.any():
        raise SystemExit(f"no candle data around cutoff {cutoff}")
    close_cutoff = float(df["close"].values[cutoff_mask][-1])
    close_horizon = float(df["close"].values[horizon_mask][-1])
    delta = close_horizon - close_cutoff
    if abs(delta) < 0.5:  # less than half a point: noise
        return "FLAT", close_cutoff, close_horizon
    return ("UP" if delta > 0 else "DOWN"), close_cutoff, close_horizon


def _build_service(strategy_name: str, work_dir: str, offsets: dict,
                   status_filter: str = ""):
    """Isolated AgentService whose perception is pinned to the replay window."""
    import server
    from agent_service import AgentConfig, AgentService
    from agentic.feed import Feed, default_candles_provider, default_provider
    from agentic.store import ContextStore

    state_dir = str(server.AGENT_STATE_DIR or "").strip() or None
    live_store = ContextStore.path_for(str(server.AGENT_SYMBOL), state_dir)
    if not os.path.isfile(live_store):
        raise SystemExit(f"live store not found: {live_store}")

    tmp_state = os.path.join(work_dir, "state")
    tmp_renders = os.path.join(work_dir, "renders")
    os.makedirs(tmp_state, exist_ok=True)
    os.makedirs(tmp_renders, exist_ok=True)
    copied = os.path.join(tmp_state, os.path.basename(live_store))
    if not os.path.isfile(copied):
        shutil.copy2(live_store, copied)

    # POC arm: pin the copied store's view to fresh-only levels if requested.
    if status_filter:
        store = ContextStore(str(server.AGENT_SYMBOL), state_dir=tmp_state)
        store.load()
        store.set_view(status_filter=status_filter)
        store.save()
        del store

    wrapped = _force_offset_provider(offsets, default_provider())
    feed = Feed(provider=wrapped, candles_provider=default_candles_provider())

    model, api_base, api_key_env = server.AGENT_MODEL, server.AGENT_API_BASE, server.AGENT_API_KEY_ENV
    if str(server.AGENT_MODE or "").strip().lower() == "live":
        _, model, api_base, api_key_env = server._resolve_agent_connection(
            server.AGENT_MODE, model, api_base, api_key_env
        )
    model = model or server.AGENT_DEFAULT_MODEL

    config = AgentConfig(
        symbol=str(server.AGENT_SYMBOL),
        timeframe=str(server.AGENT_TIMEFRAME),
        bars=int(server.AGENT_BARS),
        mode=str(server.AGENT_MODE),
        model=model,
        api_base=api_base,
        api_key_env=api_key_env,
        max_tokens=int(server.AGENT_MAX_TOKENS),
        temperature=float(server.AGENT_TEMPERATURE),
        poll_s=float(server.AGENT_POLL_S),
        http_timeout_s=float(server.AGENT_HTTP_TIMEOUT_S),
        http_user_agent=server.AGENT_HTTP_USER_AGENT,
        state_dir=tmp_state,
        out_dir=tmp_renders,
        strategy_dir="strategies",
        strategy_name=strategy_name,
    )
    return AgentService(config, feed=feed), tmp_renders


def _call(service, question: str, attempts: int = 3, backoff_s: float = 60.0) -> dict:
    """One chat turn via the synchronous API (streaming payload keys are
    inconsistent for batch use; chat_turn returns the full result directly)."""
    last = None
    for attempt in range(max(1, attempts)):
        if attempt:
            print(f"    retry {attempt}/{attempts - 1} (previous: {str(last.get('reason') or 'empty')[:60]})")
            time.sleep(backoff_s)
        result = service.chat_turn(question)
        resp = str(result.get("response") or "").strip()
        ok = bool(result.get("ok", True)) and resp and resp != "(no response)"
        last = {
            "answer": resp,
            "reason": str(result.get("reason") or ""),
            "render_id": str(result.get("render_id") or ""),
            "ok": ok,
        }
        if ok:
            break
    return last or {}


def _extract_call(answer: str) -> str:
    import re
    m = re.search(r"CALL\s*:\s*(UP|DOWN|NO-TRADE|NOTRADE)", answer or "", re.IGNORECASE)
    return m.group(1).upper().replace("NOTRADE", "NO-TRADE") if m else "UNPARSED"


def _battery(now: datetime) -> list:
    """Default battery: last N trading days, two windows per day.

    W1: cutoff ~ London open (07:00 UTC) -> horizon = NY AM close (16:00 UTC).
    W2: cutoff ~ NY open (13:30 UTC)    -> horizon = late NY (20:00 UTC).
    """
    windows = []
    for days_back in range(2, 7):
        day = now - timedelta(days=days_back)
        if day.weekday() >= 5:  # skip weekend
            continue
        base_utc = day.replace(hour=0, minute=0, second=0, microsecond=0)
        windows.append({
            "name": f"day-{days_back}-london",
            "cutoff": base_utc + timedelta(hours=7),
            "horizon": base_utc + timedelta(hours=16),
        })
        windows.append({
            "name": f"day-{days_back}-nyam",
            "cutoff": base_utc + timedelta(hours=13, minutes=30),
            "horizon": base_utc + timedelta(hours=20),
        })
    return windows


def now_or_none() -> datetime:
    return datetime.now(timezone.utc)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="alchemist_mnsr_v2")
    parser.add_argument("--label", default=None)
    parser.add_argument("--days", type=int, default=5, help="look-back days for windows")
    parser.add_argument("--status-filter", default="", help="fresh-only POC arm (e.g. 'live')")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--backoff", type=float, default=60.0)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M")
    label = args.label or (f"replay-{args.status_filter}" if args.status_filter else "replay-all")
    out_dir = os.path.join(RESEARCH_DIR, f"{stamp}-{label}")
    os.makedirs(out_dir, exist_ok=True)

    windows = _battery(now)[: max(2, args.days * 2)]
    rows = []
    for w in windows:
        offsets = _exact_offsets(w["cutoff"])
        offset_m15 = offsets.get("M15", 0)
        realized, c0, c1 = _realized_direction(w["cutoff"], w["horizon"])
        print(f"=== {w['name']} | cutoff {w['cutoff']:%m-%d %H:%M} UTC | M15 offset {offset_m15} | realized: {realized} ({c0:.2f} -> {c1:.2f})")
        service, renders_dir = _build_service(args.strategy, out_dir, offsets, args.status_filter)
        r = _call(service, REPLAY_PROMPT, attempts=args.attempts, backoff_s=args.backoff)
        call = _extract_call(r["answer"]) if r["ok"] else "NO-ANSWER"
        agree = (call == realized) if realized in ("UP", "DOWN") else (call in ("NO-TRADE",))
        rows.append({**w, "offset": offset_m15, "realized": realized,
                     "close_cutoff": c0, "close_horizon": c1,
                     "call": call, "agree": agree, "ok": r["ok"],
                     "answer": r["answer"][:1200], "render_id": r["render_id"]})
        print(f"    call: {call} | agree: {agree} | ok: {r['ok']}")
        del service  # fresh service per window: no cross-window chat memory

    scored = [r for r in rows if r["realized"] in ("UP", "DOWN") and r["call"] in ("UP", "DOWN")]
    no_trade = [r for r in rows if r["call"] == "NO-TRADE"]
    failed = [r for r in rows if r["call"] == "NO-ANSWER"]
    wins = sum(1 for r in scored if r["agree"])
    pct = 100.0 * wins / len(scored) if scored else 0.0

    lines = [
        f"# Alchemist MSNR replay — {label}",
        f"- strategy: `{args.strategy}` | date: {now.isoformat(timespec='seconds')}",
        f"- metric: outcome agreement (directional call vs realized move; a win is a win)",
        f"- status_filter arm: {args.status_filter or 'default (all)'}",
        "",
        "| window | cutoff (UTC) | realized | call | agree |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['cutoff']:%m-%d %H:%M} | {r['realized']} "
            f"({r['close_cutoff']:.2f}->{r['close_horizon']:.2f}) | {r['call']} | {r['agree']} |"
        )
    lines += [
        "",
        f"**Agreement: {wins}/{len(scored)} = {pct:.0f}%** "
        f"(target >= 70%) | no-trade calls: {len(no_trade)} | failed turns: {len(failed)}",
        "",
        "## Full answers",
    ]
    for r in rows:
        lines += [f"### {r['name']} — call: {r['call']} (realized {r['realized']})", "",
                  r["answer"], ""]
    path = os.path.join(out_dir, "replay.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"\nwrote {os.path.relpath(path, ROOT)}")
    print(f"AGREEMENT: {wins}/{len(scored)} = {pct:.0f}% (target 70%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
