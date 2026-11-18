"""tools/alchemist_backtest.py — backtest the agent against manually-selected
Alchemist MSNR setups from past price action.

For each dated setup window:
  1. Clamp the agent's perception to the cutoff (per-timeframe exact offsets,
     no look-ahead — guaranteed by construction).
  2. Ask the agent for a directional call (UP/DOWN/NO-TRADE) per the Alchemist
     MSNR loop.
  3. Resolve the realized outcome from ACTUAL candles after the cutoff.
  4. Score outcome agreement (a win is a win, a loss is a loss).

Isolation: live store copied into the run dir; operator's server/state untouched.
Provider: $0 local provider from .env, retried with 60s backoff on drops.

Usage:
    python tools/alchemist_backtest.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESEARCH_DIR = os.path.join(ROOT, "docs", "research", "2026-11-11-alchemist-mnsr")
SYMBOL = "XAUUSDm"

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


def _exact_offsets(cutoff: datetime) -> dict:
    """Exact per-timeframe offsets: bars NEWER than the cutoff (never look-ahead)."""
    from data.mt5_loader import MT5DataLoader

    offsets = {}
    loader = MT5DataLoader(symbol=SYMBOL)
    loader.connect()
    try:
        for tf in ("M5", "M15", "H1", "H4", "D1"):
            try:
                df = loader.fetch_timeframe(tf, count=10000, start=0)
                idx = df.index.tz_localize("UTC") if df.index.tz is None else df.index
                offsets[tf] = int((idx > cutoff).sum())
            except Exception:
                offsets[tf] = 0
    finally:
        loader.disconnect()
    return offsets


def _force_offset_provider(offsets: dict, base_provider):
    """Clamp every perception to >= the forced offset (no fresher than cutoff)."""
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


def _realized_direction(cutoff: datetime, horizon: datetime):
    """UP/DOWN/FLAT from ACTUAL candles: close at cutoff vs close at horizon."""
    from data.mt5_loader import MT5DataLoader

    loader = MT5DataLoader(symbol=SYMBOL)
    loader.connect()
    try:
        df = loader.fetch_timeframe("M15", count=10000, start=0)
    finally:
        loader.disconnect()
    idx = df.index.tz_localize("UTC") if df.index.tz is None else df.index
    c_mask = idx <= cutoff
    h_mask = idx <= horizon
    if not c_mask.any() or not h_mask.any():
        raise SystemExit(f"no candle data around cutoff {cutoff}")
    close_cutoff = float(df["close"].values[c_mask][-1])
    close_horizon = float(df["close"].values[h_mask][-1])
    delta = close_horizon - close_cutoff
    if abs(delta) < 0.5:
        return "FLAT", close_cutoff, close_horizon
    return ("UP" if delta > 0 else "DOWN"), close_cutoff, close_horizon


def _build_service(strategy_name, work_dir, offsets):
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

    # Clear the chat context so the agent doesn't see prior turns with current
    # (live) prices — each backtest window must start with a clean memory.
    from agentic.store import ContextStore
    from agentic._time import as_aware
    cs = ContextStore(SYMBOL, state_dir=tmp_state)
    cs.load(SYMBOL)
    cs.data.agent.chat_cleared_at = as_aware(datetime.now(timezone.utc))
    cs.save()

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


def _call(service, question, attempts=3, backoff_s=60.0):
    last = None
    for attempt in range(max(1, attempts)):
        if attempt:
            print(f"    retry {attempt}/{attempts-1} (previous: {str(last.get('reason') or 'empty')[:60]})")
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


def _extract_call(answer):
    import re
    m = re.search(r"CALL\s*:\s*(UP|DOWN|NO-TRADE|NOTRADE)", answer or "", re.IGNORECASE)
    return m.group(1).upper().replace("NOTRADE", "NO-TRADE") if m else "UNPARSED"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    setups_path = os.path.join(
        RESEARCH_DIR, "backtest_setups.json"
    )
    setups = json.load(open(setups_path, encoding="utf-8"))["setups"]

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M")
    out_dir = os.path.join(RESEARCH_DIR, f"{stamp}-backtest")
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    for s in setups:
        cutoff = datetime.fromisoformat(s["cutoff"])
        horizon = datetime.fromisoformat(s["horizon"])
        offsets = _exact_offsets(cutoff)
        realized, c0, c1 = _realized_direction(cutoff, horizon)
        print(
            f"=== {s['id']} {s['setup_type']} | cutoff {cutoff:%m-%d %H:%M} UTC "
            f"| M15 offset {offsets.get('M15',0)} | realized: {realized} "
            f"({c0:.2f} -> {c1:.2f}) | expected {s['expected']}"
        )
        service, renders_dir = _build_service("alchemist_mnsr_v2", out_dir, offsets)
        r = _call(service, REPLAY_PROMPT, attempts=1, backoff_s=30.0)
        call = _extract_call(r["answer"]) if r["ok"] else "NO-ANSWER"
        agree = (call == realized) if realized in ("UP", "DOWN") else (call == "NO-TRADE")
        correct_vs_expected = (call == s["expected"]) if call in ("UP", "DOWN") else None
        rows.append({
            **s, "offset": offsets.get("M15", 0), "realized": realized,
            "close_cutoff": c0, "close_horizon": c1, "call": call,
            "agree_vs_realized": agree, "correct_vs_expected": correct_vs_expected,
            "ok": r["ok"], "answer": r["answer"], "render_id": r["render_id"],
        })
        print(
            f"    call: {call} | realized: {realized} | agree: {agree} "
            f"| vs expected {s['expected']}: {correct_vs_expected} | ok: {r['ok']}"
        )
        del service

    scored = [r for r in rows if r["realized"] in ("UP", "DOWN") and r["call"] in ("UP", "DOWN")]
    wins = sum(1 for r in scored if r["agree_vs_realized"])
    pct = 100.0 * wins / len(scored) if scored else 0.0
    expected_scored = [r for r in rows if r["correct_vs_expected"] is not None]
    exp_wins = sum(1 for r in expected_scored if r["correct_vs_expected"])
    exp_pct = 100.0 * exp_wins / len(expected_scored) if expected_scored else 0.0
    no_trade = [r for r in rows if r["call"] == "NO-TRADE"]
    failed = [r for r in rows if r["call"] == "NO-ANSWER"]

    lines = [
        f"# Alchemist MSNR backtest — {stamp}",
        f"- strategy: `alchemist_mnsr_v2` | date: {now.isoformat(timespec='seconds')}",
        f"- metric: outcome agreement (directional call vs realized move)",
        f"- setups: {len(rows)} manually-selected dated setups from past price action",
        "",
        "| id | setup | cutoff (UTC) | session | expected | call | realized | agree | vs expected |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cutoff_dt = datetime.fromisoformat(r["cutoff"])
        lines.append(
            f"| {r['id']} | {r['setup_type']} | {cutoff_dt:%m-%d %H:%M} "
            f"| {r['session']} | {r['expected']} | {r['call']} | {r['realized']} "
            f"({r['close_cutoff']:.2f}->{r['close_horizon']:.2f}) | {r['agree_vs_realized']} "
            f"| {r['correct_vs_expected']} |"
        )
    lines += [
        "",
        f"**Agreement vs realized: {wins}/{len(scored)} = {pct:.0f}% (target >=70%)**",
        f"**Correct vs my expected: {exp_wins}/{len(expected_scored)} = {exp_pct:.0f}%**",
        f"| NO-TRADE calls: {len(no_trade)} | failed turns: {len(failed)} |",
        "",
        "## Full answers",
    ]
    for r in rows:
        lines += [f"### {r['id']} {r['setup_type']} — call {r['call']} (realized {r['realized']})", "",
                  r["answer"], ""]
    path = os.path.join(out_dir, "backtest.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"\nwrote {os.path.relpath(path, ROOT)}")
    print(f"AGREEMENT vs realized: {wins}/{len(scored)} = {pct:.0f}% (target 70%)")
    print(f"CORRECT vs expected: {exp_wins}/{len(expected_scored)} = {exp_pct:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
