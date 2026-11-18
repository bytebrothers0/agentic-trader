"""Retry the 4 timed-out backtest setups at night."""
import sys, os, json
sys.path.insert(0, '.')
from tools.alchemist_backtest import _exact_offsets, _build_service, _call, REPLAY_PROMPT, _realized_direction, _extract_call
from datetime import datetime, timezone

setups = json.load(open('docs/research/2026-11-11-alchemist-mnsr/backtest_setups_retries.json', encoding='utf-8'))['setups']

out_dir = 'docs/research/2026-11-11-alchemist-mnsr/20261118-0555-retry-night'
os.makedirs(out_dir, exist_ok=True)

rows = []
for s in setups:
    cutoff = datetime.fromisoformat(s['cutoff'])
    horizon = datetime.fromisoformat(s['horizon'])
    offsets = _exact_offsets(cutoff)
    realized, c0, c1 = _realized_direction(cutoff, horizon)
    print(f'=== {s["id"]} | cutoff {cutoff:%m-%d %H:%M} | M15 offset {offsets.get("M15",0)} | realized: {realized} ({c0:.2f}->{c1:.2f})')
    
    service, renders = _build_service('alchemist_mnsr_v2', out_dir, offsets)
    r = _call(service, REPLAY_PROMPT, attempts=1, backoff_s=30.0)
    call = _extract_call(r['answer']) if r['ok'] else 'NO-ANSWER'
    agree = (call == realized) if realized in ("UP", "DOWN") else (call == "NO-TRADE")
    print(f'   call: {call} | realized: {realized} | agree: {agree} | ok: {r["ok"]}')
    if r['ok']:
        print(f'   answer tail: {r["answer"][-300:]}')
    rows.append({**s, "call": call, "realized": realized, "agree": agree, "ok": r["ok"]})
    print()
    del service

completed = [r for r in rows if r["call"] in ("UP", "DOWN")]
correct = sum(1 for r in completed if r["agree"])
print(f'RESULTS: {correct}/{len(completed)} correct ({100.0*correct/len(completed):.0f}%)')
print(f'Timed out: {len(rows)-len(completed)}/4')
