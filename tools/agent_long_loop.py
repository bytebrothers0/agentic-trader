"""
tools/agent_long_loop.py — Run the agent in a long loop against the live API
to debug session disruptions.

Usage:
    python tools/agent_long_loop.py [--turns N] [--mode live|mock] [--delay S]

Runs N chat turns in sequence, timing each and reporting failures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import server
from agent_service import AgentConfig, AgentService

#: Questions to cycle through in the loop
QUESTIONS = [
    "what is the current bias on gold right now?",
    "where is liquidity resting above and below price?",
    "has there been a liquidity sweep recently?",
    "is price in premium or discount right now?",
    "what session are we in?",
    "what would change your mind about the bias?",
    "show me the key support and resistance levels",
    "is there a BOS or CHoCH forming on any timeframe?",
]


def build_service(mode: str, work_dir: str):
    import shutil
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

    model, api_base, api_key_env = server.AGENT_MODEL, server.AGENT_API_BASE, server.AGENT_API_KEY_ENV
    if str(mode or "").strip().lower() == "live":
        _, model, api_base, api_key_env = server._resolve_agent_connection(
            mode, model, api_base, api_key_env
        )
    model = model or server.AGENT_DEFAULT_MODEL

    print(f"  provider={mode} model={model} base={api_base} key_env={api_key_env or '(none)'}")

    config = AgentConfig(
        symbol=str(server.AGENT_SYMBOL),
        timeframe=str(server.AGENT_TIMEFRAME),
        bars=int(server.AGENT_BARS),
        mode=mode,
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
        strategy_dir=str(server.STRATEGY_DIR),
        strategy_name=str(server.STRATEGY_ACTIVE),
    )
    return AgentService(config), tmp_renders


def one_turn(service, question: str):
    """One chat turn; returns (ok, seconds, reason, tool_count)."""
    started = time.time()
    final = None
    for event, data in service.chat_stream(question):
        if event == "done":
            final = data
    took = time.time() - started
    if final is None:
        final = {}
    ok = bool(final.get("ok", True)) and bool(str(final.get("response") or "").strip())
    return ok, round(took, 1), str(final.get("reason") or ""), len(final.get("tool_calls") or [])


def main():
    parser = argparse.ArgumentParser(description="Run agent in a long loop")
    parser.add_argument("--turns", type=int, default=20, help="number of turns to run")
    parser.add_argument("--mode", default="live", choices=["live", "mock"], help="agent mode")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between turns")
    parser.add_argument("--out-dir", default=None, help="output directory")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out_dir = args.out_dir or os.path.join(ROOT, "docs", "research", "2026-11-11-trader-knowledge", f"loop-{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== Agent long loop: {args.turns} turns, mode={args.mode} ===")
    print(f"Output dir: {out_dir}")

    service, renders_dir = build_service(args.mode, out_dir)

    results = []
    for i in range(args.turns):
        q = QUESTIONS[i % len(QUESTIONS)]
        print(f"\n  Turn {i+1}/{args.turns}: {q[:60]}...")
        ok, took, reason, ntools = one_turn(service, q)
        status = "OK" if ok else "FAIL"
        print(f"  -> {status} {took}s tools={ntools}" + (f" reason={reason}" if reason else ""))
        results.append({"turn": i + 1, "question": q, "ok": ok, "seconds": took, "tools": ntools, "reason": reason})

        if not ok:
            print(f"  !!! TURN FAILED: {reason} !!!")
            # Continue to next turn to see if it recovers

        if i < args.turns - 1:
            time.sleep(args.delay)

    # Summary
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = args.turns - ok_count
    avg_time = sum(r["seconds"] for r in results) / args.turns if results else 0
    print(f"\n=== Summary ===")
    print(f"  Total turns: {args.turns}")
    print(f"  OK: {ok_count}")
    print(f"  FAIL: {fail_count}")
    print(f"  Avg time: {avg_time:.1f}s")
    if fail_count > 0:
        print(f"  Failures:")
        for r in results:
            if not r["ok"]:
                print(f"    Turn {r['turn']}: {r['reason']} ({r['seconds']}s)")

    # Save results
    path = os.path.join(out_dir, "loop_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"  Results: {path}")


if __name__ == "__main__":
    sys.exit(main())
