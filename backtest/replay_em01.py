"""
backtest/replay_em01.py — Replay the agent at each EM01 decision instant.

Runs run_replay() against the frozen M15 history at each manual setup's
decision instant, capturing the agent's thesis, proposals, and tool calls.
Compares against the manual setup.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from backtest.historical import load_or_fetch, FrozenLoader
from backtest.replay import run_replay, diagnose, score
from backtest.crt_scan import scan_classic_crts, CrtCandidate


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out_dir = "backtest/out_strategy_probe"

    # Resolve provider connection (live mode)
    import ai_agent.config as cfg
    provider, api_base, model, api_key_env = cfg.resolve_provider()

    # Load history
    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=180)
    scan_frame = frames[timeframe]

    # Scan manual setups
    candidates = scan_classic_crts(scan_frame, timeframe, since=None,
                                   min_rr=1.0, only_distributed=True, top=20)

    if not candidates:
        print("No EM01 setups found.")
        return 1

    results: List[Dict[str, Any]] = []

    for i, cand in enumerate(candidates):
        print(f"\n{'='*70}")
        print(f"EM01 Setup {i+1}/{len(candidates)}: {cand.direction.upper()} CRT @ {cand.decision_time}")
        print(f"  Range: {cand.crl:.3f}-{cand.crh:.3f}, swept {cand.swept_level:.3f}, target {cand.target_level:.3f}")
        print(f"  Naive trade: entry={cand.entry:.3f} SL={cand.stop:.3f} TP={cand.target:.3f} R:R={cand.rr:.2f}")
        print(f"{'='*70}")

        as_of = __import__("pandas").Timestamp(cand.decision_time)
        loader = FrozenLoader(symbol, frames, as_of)

        replay = run_replay(
            loader,
            symbol=symbol,
            model=model,
            api_base=api_base,
            api_key_env=api_key_env,
            timeframe=timeframe,
            bars=180,
            max_tokens=16384,
            mode="live",
            message="",
            families=["crt", "bos", "liquidity"],
            workdir=os.path.join(out_dir, f"replay_em01_{i+1}"),
        )

        replay_dict = replay.to_dict()
        verdict = score(cand, replay_dict["thesis"], replay_dict["proposals"], scan_frame)
        diag = diagnose(replay_dict)

        print(f"\n  Agent result: ok={replay.ok} reason={replay.reason!r}")
        print(f"  Model calls: {diag['model_calls']}, ran_away: {diag['ran_away_calls']}")
        print(f"  Thesis: bias={replay_dict['thesis'].get('bias')} conf={replay_dict['thesis'].get('confidence')}")
        print(f"  Proposals: {len(replay_dict['proposals'])}")
        print(f"  Verdict: thesis_aligned={verdict.thesis_aligned}")
        if verdict.proposals:
            for prop in verdict.proposals:
                print(f"    Proposal: bias={prop['bias']} entry={prop['entry']} SL={prop['sl']} TP={prop['tp']}")
                print(f"      Sim: outcome={prop['sim']['outcome']} R={prop['sim']['r_multiple']}")
        else:
            print("    No proposals emitted")

        # Compare manual vs agent
        manual_bias = "bullish" if cand.direction.upper() == "BULLISH" else "bearish"
        agent_bias = str(replay_dict["thesis"].get("bias") or "").lower()
        agreement = (agent_bias == manual_bias) and len(replay_dict["proposals"]) > 0

        print(f"\n  COMPARISON:")
        print(f"    Manual bias: {manual_bias} | Agent bias: {agent_bias or 'none'} | Match: {manual_bias == agent_bias}")
        print(f"    Manual proposal: yes | Agent proposal: {len(replay_dict['proposals']) > 0} | Match: {len(replay_dict['proposals']) > 0}")
        print(f"    Overall agreement: {agreement}")

        results.append({
            "manual": cand.to_dict(),
            "agent": replay_dict,
            "verdict": verdict.to_dict(),
            "diagnosis": diag,
            "agreement": agreement,
            "manual_bias": manual_bias,
            "agent_bias": agent_bias,
        })

    # Save combined results
    out_path = os.path.join(out_dir, "em01_agent_comparison.json")
    os.makedirs(out_dir, exist_ok=True)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM01",
        "mode": "live",
        "model": model,
        "setups": results,
        "summary": {
            "total": len(results),
            "agreements": sum(1 for r in results if r["agreement"]),
            "agreement_rate": round(sum(1 for r in results if r["agreement"]) / len(results) * 100, 1) if results else 0,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"EM01 SUMMARY: {data['summary']['agreements']}/{data['summary']['total']} agreements "
          f"({data['summary']['agreement_rate']}%)")
    print(f"Saved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
