"""tools/agent_interview.py -- Q&A the chart agent under a chosen playbook, safely.

Research harness for the trader-knowledge loop (docs/specs/2026-11-11-trader-
knowledge-library-design.md). It is deliberately **isolated from the live
server**: the real store file is COPIED into a temp state dir, and the
interview service gets its own render dir -- so the operator's running server
and durable state are never touched, while the copied store keeps the real
view/pins/thesis/budget context so answers are realistic.

The interview itself goes through ``AgentService.chat_turn`` in-process (the
feed's provider calls ``server.get_indicators`` directly, so only the MT5
terminal needs to be up, not the HTTP server). Each turn is $0: the shared
local provider from ``.env``.

Usage:
    python tools/agent_interview.py                        # trader_core
    python tools/agent_interview.py --strategy alchemy_mnsr --label baseline
    python tools/agent_interview.py --baseline             # run both, compare

Output: docs/research/2026-11-11-trader-knowledge/<label>/
    transcript.md     every question, the full answer, tool activity, tokens
    renders/*.png     each turn's chart render, for independent verification
    state/XAUUSDm.json  the copied store with this interview's turns appended
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESEARCH_DIR = os.path.join(ROOT, "docs", "research", "2026-11-11-trader-knowledge")

#: The question set -- deliberately phrased the way an operator asks, and
#: deliberately probing the failure the research targets ("just BOS on D1 = bearish").
DEFAULT_QUESTIONS = [
    "what is the current bias on gold right now, and what invalidation would flip it?",
    "where is liquidity resting above and below price right now? name the levels.",
    "has there been a liquidity sweep recently? how do you know it was a sweep and not a break?",
    "is price in premium or discount right now? how do you know?",
    "what session are we in, and does the session script support your bias?",
    "what would change your mind about the bias?",
]


def _build_service(strategy_name: str, work_dir: str):
    """An isolated AgentService: copied store, own renders, chosen playbook.

    If ``work_dir`` already carries a copied state file (a resumed run), it is
    kept as-is — so the agent's chat history from the earlier interview is
    still in the briefing and follow-up questions continue the conversation.
    """
    import server
    from agent_service import AgentConfig, AgentService
    from agentic.store import ContextStore

    state_dir = str(server.AGENT_STATE_DIR or "").strip() or None
    live_store = ContextStore.path_for(str(server.AGENT_SYMBOL), state_dir)
    if not os.path.isfile(live_store):
        raise SystemExit(f"live store not found: {live_store} (run the server once to seed it)")

    tmp_state = os.path.join(work_dir, "state")
    tmp_renders = os.path.join(work_dir, "renders")
    os.makedirs(tmp_state, exist_ok=True)
    os.makedirs(tmp_renders, exist_ok=True)
    copied = os.path.join(tmp_state, os.path.basename(live_store))
    if not os.path.isfile(copied):
        shutil.copy2(live_store, copied)

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
        strategy_dir=str(server.STRATEGY_DIR),
        strategy_name=strategy_name,
    )
    return AgentService(config), tmp_renders


def _one_turn(service, question: str) -> dict:
    """One chat turn; returns the collected evidence."""
    final = None
    events = []
    started = time.time()
    for event, data in service.chat_stream(question):
        events.append(event)
        if event == "done":
            final = data
    took = time.time() - started
    if final is None:
        final = {}
    return {
        "question": question,
        "answer": str(final.get("response") or ""),
        "reason": str(final.get("reason") or ""),
        "tool_calls": final.get("tool_calls") or [],
        "render_id": str(final.get("render_id") or ""),
        "turn_id": str(final.get("turn_id") or ""),
        "events": events,
        "seconds": round(took, 1),
        "ok": (
            bool(final.get("ok", True))
            and bool(str(final.get("response") or "").strip())
            and str(final.get("response")).strip() != "(no response)"
        ),
    }


def _run_question(service, question: str, attempts: int = 3, backoff_s: float = 60.0) -> dict:
    """One chat turn, retried on provider failure (gateway read timeouts).

    Each attempt is its own recorded turn (audit trail intact); a timeout
    leaves an empty response in the log, which the next attempt's briefing
    simply ignores. Returns the first good answer, else the last failure.
    ``backoff_s`` (default 60 per the operator's instruction) is the wait
    between attempts — the gateway drops under sustained load, so patience
    beats hammering.
    """
    last = None
    for attempt in range(max(1, attempts)):
        if attempt:
            print(f"    retry {attempt}/{attempts - 1} (previous attempt failed: {str(last.get('reason') or 'empty response')[:80]})")
            time.sleep(backoff_s)
        last = _one_turn(service, question)
        if last["ok"]:
            return last
    last["retries"] = max(0, attempts - 1)
    return last


def _transcript(label: str, strategy: str, results: list, out_dir: str) -> str:
    lines = [
        f"# Agent interview -- {label}",
        f"- strategy: `{strategy}`",
        f"- date: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- isolation: copied store, own renders, in-process chat_turn ($0 local provider)",
        "",
    ]
    total_tokens = 0
    for i, r in enumerate(results, 1):
        lines += [
            f"## Q{i}: {r['question']}",
            f"_{r['seconds']}s · {len(r['tool_calls'])} tool call(s) · render: {r['render_id'] or '--'} · ok: {r['ok']}_",
            "",
            r["answer"] or "*(no response)*",
            "",
        ]
        for call in r["tool_calls"]:
            call_info = call.get("call") or {}
            result = call.get("result") or {}
            lines.append(
                f"- tool: `{call_info.get('name')}` -> ok: {result.get('ok', call.get('ok'))}"
            )
        if r.get("reason"):
            lines.append(f"- failure reason: `{r['reason'][:200]}`")
        if r["tool_calls"]:
            lines.append("")
    path = os.path.join(out_dir, "transcript.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return path


def main() -> int:
    # Windows consoles default to cp1252: model answers contain arrows and
    # dashes, so force UTF-8 with replacement instead of crashing mid-run.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="trader_core", help="playbook to wear")
    parser.add_argument("--label", default=None, help="output subdirectory name")
    parser.add_argument("--baseline", action="store_true",
                        help="run the active strategy AND trader_core, for comparison")
    parser.add_argument("--questions", default=None, help="json file with a list of questions")
    parser.add_argument("--out-dir", default=None,
                        help="resume an existing run dir (state kept: the agent remembers "
                             "the earlier interview; new turns append to it)")
    parser.add_argument("--attempts", type=int, default=3, help="retries per question on failure")
    parser.add_argument("--backoff", type=float, default=60.0,
                        help="seconds to wait between retry attempts (operator default 60)")
    args = parser.parse_args()

    if os.path.isfile(args.questions or ""):
        questions = json.load(open(args.questions, encoding="utf-8"))
    else:
        questions = DEFAULT_QUESTIONS

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    if args.baseline:
        runs = [("alchemy_mnsr", "baseline-active"), ("trader_core", "trader-core")]
    else:
        runs = [(args.strategy, args.label or args.strategy)]

    for strategy, label in runs:
        if args.out_dir:
            out_dir = os.path.join(RESEARCH_DIR, args.out_dir)
        else:
            out_dir = os.path.join(RESEARCH_DIR, f"{stamp}-{label}")
        os.makedirs(out_dir, exist_ok=True)
        print(f"=== interview: {strategy} -> {out_dir} ===")
        service, renders_dir = _build_service(strategy, out_dir)
        results = []
        for q in questions:
            print(f"  Q: {q}")
            r = _run_question(service, q, attempts=args.attempts, backoff_s=args.backoff)
            print(f"  -> {r['seconds']}s, tools: {len(r['tool_calls'])}, ok: {r['ok']}")
            print(f"  -> {r['answer'][:160]}...")
            results.append(r)
            if r["render_id"]:
                src = os.path.join(renders_dir, f"{r['render_id']}.png")
                if os.path.isfile(src):
                    print(f"  -> render saved: {os.path.relpath(src, ROOT)}")
        path = _transcript(label, strategy, results, out_dir)
        print(f"  transcript: {os.path.relpath(path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
