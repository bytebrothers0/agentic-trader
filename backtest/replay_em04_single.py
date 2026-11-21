"""
backtest/replay_em04_single.py — Replay the agent at ONE EM04 decision instant.

Clean run: fresh workdir, no state leakage between setups.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from backtest.historical import load_or_fetch, FrozenLoader
from backtest.replay import run_replay, diagnose, score


def main() -> int:
    symbol = "XAUUSDm"
    timeframe = "M15"
    cache = "backtest/out_strategy_probe/history_recent.pkl"
    out_dir = "backtest/out_strategy_probe"

    import ai_agent.config as cfg
    provider, api_base, model, api_key_env = cfg.resolve_provider()

    sym, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                timeframes=[timeframe], max_bars=180)

    # Load the EM04 manual setups
    setups_path = os.path.join(out_dir, "em04_manual_setups.json")
    if not os.path.isfile(setups_path):
        print("No EM04 manual setups found. Run scan_em04.py first.")
        return 1

    with open(setups_path, "r", encoding="utf-8") as f:
        setups_data = json.load(f)

    setups = setups_data["setups"]
    if not setups:
        print("No EM04 setups found.")
        return 1

    # Use the first setup (rank 1)
    setup = setups[0]
    print(f"EM04 Setup #{setup['rank']}: {setup['direction'].upper()} Fresh S/R @ {setup['decision_time']}")
    print(f"  Level: {setup['price']:.3f}, entry={setup['entry']:.3f} SL={setup['stop']:.3f} TP={setup['target']:.3f} R:R={setup['rr']:.2f}\n")

    as_of = pd.Timestamp(setup["decision_time"])

    # Fresh workdir each run
    workdir = tempfile.mkdtemp(prefix=f"em04_replay_{setup['decision_time'].replace(':', '-')}_")
    print(f"Workdir: {workdir}")

    loader = FrozenLoader(symbol, frames, as_of)
    replay = run_replay(
        loader,
        symbol=symbol,
        model=model,
        api_base=api_base,
        api_key_env=api_key_env,
        timeframe=timeframe,
        bars=180,
        max_tokens=65536,
        mode="live",
        message="",
        families=["sr", "bos", "liquidity"],
        workdir=workdir,
    )

    replay_dict = replay.to_dict()
    setup_ns = SimpleNamespace(
        **setup,
        manipulation_index=0,
        bars_to_target=0,
    )
    verdict = score(setup_ns, replay_dict["thesis"], replay_dict["proposals"], frames[timeframe])
    diag = diagnose(replay_dict)

    print(f"\n  Agent result: ok={replay.ok} reason={replay.reason!r}")
    print(f"  Model calls: {diag['model_calls']}, ran_away: {diag['ran_away_calls']}")
    print(f"  Thesis: bias={replay_dict['thesis'].get('bias')} conf={replay_dict['thesis'].get('confidence')}")
    print(f"  Proposals: {len(replay_dict['proposals'])}")
    if verdict.proposals:
        for prop in verdict.proposals:
            print(f"    Proposal: bias={prop['bias']} entry={prop['entry']} SL={prop['sl']} TP={prop['tp']}")
            print(f"      Sim: outcome={prop['sim']['outcome']} R={prop['sim']['r_multiple']}")
    else:
        print("    No proposals emitted")

    manual_bias = setup["direction"]
    agent_bias = str(replay_dict["thesis"].get("bias") or "").lower()
    agreement = (agent_bias == manual_bias) and len(replay_dict["proposals"]) > 0

    print(f"\n  COMPARISON:")
    print(f"    Manual bias: {manual_bias} | Agent bias: {agent_bias or 'none'} | Match: {manual_bias == agent_bias}")
    print(f"    Manual proposal: yes | Agent proposal: {len(replay_dict['proposals']) > 0} | Match: {len(replay_dict['proposals']) > 0}")
    print(f"    Overall agreement: {agreement}")

    out_path = os.path.join(out_dir, "em04_single_agent_result.json")
    os.makedirs(out_dir, exist_ok=True)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "entry_model": "EM04",
        "mode": "live",
        "model": model,
        "manual": setup,
        "agent": replay_dict,
        "verdict": verdict.to_dict(),
        "diagnosis": diag,
        "agreement": agreement,
        "manual_bias": manual_bias,
        "agent_bias": agent_bias,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\nSaved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
