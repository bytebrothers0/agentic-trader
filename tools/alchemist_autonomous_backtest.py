"""tools/alchemist_autonomous_backtest.py — fully autonomous backtest.

The agent scans historical price action ITSELF and finds its own setups.
No human-fed windows. The harness:

1. Walks through historical M15 data bar by bar.
2. At each bar, checks if a CRT-style setup just printed (sweep of a key
   level — PDH/PDL or session extreme — with close-back inside).
3. When a setup is detected, clamps the agent's perception to THAT bar
   (offset = bars after it) — no look-ahead, guaranteed by construction.
4. Asks the agent: "is there a setup here? what's your directional call?"
5. Records the agent's answer + the realized outcome from actual candles
   after the cutoff.

Isolation: live store copied into the run dir; chat context cleared per setup.
Provider: $0 local provider from .env, retried on drops.

Usage:
    python tools/alchemist_autonomous_backtest.py --max-setups 20
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

#: Prompt given to the agent at each detected setup — must produce a directional call.
SETUP_PROMPT = (
    "You are analysing the chart as it stands right now (the data you see is "
    "your present; you know nothing about the future). Keep tool use tight: "
    "ONE set_view covering your two most important timeframes (bars=120), and "
    "at most ONE level_lookup for the exact price of the key POI you decide "
    "on. Then answer completely in a single final message — do not narrate "
    "intermediate steps, and never invent a price: every number you state must "
    "come from a tool result this turn.\n\n"
    "A liquidity sweep just printed at a key level (PDH/PDL or session extreme) "
    "and price closed back inside. Walk the Alchemist MSNR loop: storyline per "
    "timeframe, is this sweep a failed breakout (reclaim) or a real break, the "
    "session script (Asia consolidates, London manipulates, New York delivers), "
    "and the POI that matters now. Then give me your directional call: for the "
    "next few hours, is gold more likely to move UP or DOWN from where it is "
    "now, the trade you would plan (entry, stop, target), and what invalidation "
    "kills it. End with exactly one of: 'CALL: UP', 'CALL: DOWN', or "
    "'CALL: NO-TRADE' (if the frames genuinely disagree or there is no setup)."
)


def _exact_offsets(cutoff: datetime) -> dict:
    """Exact per-timeframe offsets: bars NEWER than the cutoff (never look-ahead)."""
    from data.mt5_loader import MT5DataLoader

    offsets = {}
    loader = MT5DataLoader(symbol=SYMBOL)
    loader.connect()
    try:
        for tf in ("M15", "H1", "H4", "D1"):
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


def _scan_for_setups(df_m15: "pd.DataFrame", max_setups: int = 20):
    """Scan M15 data for CRT-style setups: sweep of PDH/PDL + close-back inside.

    Returns list of (cutoff_timestamp, setup_type, level, sweep_price, close_price).
    A setup is: price sweeps beyond PDH (above) or PDL (below), then the SAME
    candle's close comes back inside the level — a purge/reclaim.
    """
    import pandas as pd

    df = df_m15.copy()
    df["date"] = df.index.date
    daily = df.groupby("date").agg(pdh=("high", "max"), pdl=("low", "min"))
    daily_shift = daily.shift(1)
    df = df.join(daily_shift, on="date")

    setups = []
    for i in range(1, len(df) - 1):
        if len(setups) >= max_setups:
            break
        row = df.iloc[i]
        pdh = row["pdh"]
        pdl = row["pdl"]
        if pd.isna(pdh) or pd.isna(pdl):
            continue

        # Bearish CRT: sweep ABOVE PDH, close back BELOW PDH (reclaim = rejection)
        if row["high"] > pdh and row["close"] < pdh and row["close"] > pdl:
            setups.append((df.index[i], "BEARISH CRT at PDH", pdh, row["high"], row["close"]))
        # Bullish CRT: sweep BELOW PDL, close back ABOVE PDL (reclaim = rejection)
        if row["low"] < pdl and row["close"] > pdl and row["close"] < pdh:
            setups.append((df.index[i], "BULLISH CRT at PDL", pdl, row["low"], row["close"]))

    return setups


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

    # Clear chat context so the agent doesn't see prior turns with live prices
    from agentic.store import ContextStore as CS
    from agentic._time import as_aware
    cs = CS(SYMBOL, state_dir=tmp_state)
    cs.load(SYMBOL)
    cs.data.agent.chat_cleared_at = as_aware(datetime.now(timezone.utc))
    # Clear the live thesis — it contains storyline/levels set during live
    # trading (November levels) which would leak future data into replay mode.
    # The agent must form its own thesis from the historical cutoff data.
    cs.data.thesis = type(cs.data.thesis)()
    # Clear live subscriptions — they may reference level keys with November prices.
    cs.data.subscriptions = []
    # Clear live proposals — they may contain entry/sl/tp at November prices.
    cs.data.proposals = []
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

    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-setups", type=int, default=20,
                        help="max number of setups to scan and test")
    parser.add_argument("--attempts", type=int, default=3,
                        help="retries per setup on provider failure")
    parser.add_argument("--backoff", type=float, default=60.0,
                        help="seconds between retries")
    args = parser.parse_args()

    from data.mt5_loader import MT5DataLoader
    loader = MT5DataLoader(symbol=SYMBOL)
    loader.connect()
    df_m15 = loader.fetch_timeframe("M15", count=10000, start=0)
    loader.disconnect()

    print(f"Loaded {len(df_m15)} M15 bars: {df_m15.index[0]} to {df_m15.index[-1]}")

    setups = _scan_for_setups(df_m15, max_setups=args.max_setups)
    print(f"Found {len(setups)} CRT setups in historical data")

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M")
    out_dir = os.path.join(RESEARCH_DIR, f"{stamp}-autonomous-backtest")
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    for i, (cutoff, setup_type, level, sweep_price, close_price) in enumerate(setups, 1):
        horizon = cutoff + __import__("datetime").timedelta(hours=3)
        offsets = _exact_offsets(cutoff)
        realized, c0, c1 = _realized_direction(cutoff, horizon)
        print(
            f"[{i}/{len(setups)}] {setup_type} | cutoff {cutoff:%m-%d %H:%M} UTC "
            f"| level {level:.2f} | sweep {sweep_price:.2f} | close {close_price:.2f} "
            f"| M15 offset {offsets.get('M15',0)} | realized: {realized} ({c0:.2f}->{c1:.2f})"
        )

        service, renders_dir = _build_service("alchemist_mnsr_v2", out_dir, offsets)
        r = _call(service, SETUP_PROMPT, attempts=args.attempts, backoff_s=args.backoff)
        call = _extract_call(r["answer"]) if r["ok"] else "NO-ANSWER"
        agree = (call == realized) if realized in ("UP", "DOWN") else (call == "NO-TRADE")
        rows.append({
            "setup_id": i, "setup_type": setup_type, "cutoff": cutoff.isoformat(),
            "level": level, "sweep": sweep_price, "close": close_price,
            "offset": offsets.get("M15", 0), "realized": realized,
            "close_cutoff": c0, "close_horizon": c1, "call": call,
            "agree_vs_realized": agree, "ok": r["ok"],
            "answer": r["answer"], "render_id": r["render_id"],
        })
        print(f"    -> call: {call} | agree: {agree} | ok: {r['ok']}")
        del service

    completed = [r for r in rows if r["call"] in ("UP", "DOWN")]
    wins = sum(1 for r in completed if r["agree_vs_realized"])
    pct = 100.0 * wins / len(completed) if completed else 0.0
    no_trade = [r for r in rows if r["call"] == "NO-TRADE"]
    failed = [r for r in rows if r["call"] == "NO-ANSWER"]

    lines = [
        f"# Alchemist MSNR autonomous backtest — {stamp}",
        f"- strategy: `alchemist_mnsr_v2` | date: {now.isoformat(timespec='seconds')}",
        f"- setups found autonomously: {len(setups)} (CRT sweep + close-back at PDH/PDL)",
        f"- metric: outcome agreement (directional call vs realized close-to-close move)",
        "",
        "| # | type | cutoff (UTC) | level | call | realized | agree | ok |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['setup_id']} | {r['setup_type']} | {r['cutoff'][5:16]} "
            f"| {r['level']:.2f} | {r['call']} | {r['realized']} "
            f"| {r['agree_vs_realized']} | {r['ok']} |"
        )
    lines += [
        "",
        f"**Agreement vs realized: {wins}/{len(completed)} = {pct:.0f}% (target >=70%)**",
        f"| NO-TRADE calls: {len(no_trade)} | failed turns: {len(failed)} |",
        "",
        "## Full answers",
    ]
    for r in rows:
        lines += [f"### Setup {r['setup_id']} — {r['setup_type']} — call {r['call']} "
                  f"(realized {r['realized']}) — cutoff {r['cutoff'][5:16]} UTC", "",
                  r["answer"], ""]
    path = os.path.join(out_dir, "autonomous_backtest.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"\nwrote {os.path.relpath(path, ROOT)}")
    print(f"AGREEMENT vs realized: {wins}/{len(completed)} = {pct:.0f}% (target 70%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
