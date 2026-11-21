import sys, os, json
sys.path.insert(0, '.')
from tools.alchemist_backtest import _exact_offsets, _build_service, _call, REPLAY_PROMPT, _realized_direction, _extract_call
from datetime import datetime, timezone

# Retry timed-out setups individually
setups = [
    {'id':'S2','cutoff':'2026-09-30T13:30:00+00:00','horizon':'2026-09-30T16:30:00+00:00','setup_type':'BEARISH reclaim at PDH','expected':'DOWN'},
    {'id':'S3','cutoff':'2026-10-02T13:30:00+00:00','horizon':'2026-10-02T16:30:00+00:00','setup_type':'BEARISH reclaim at PDH','expected':'DOWN'},
    {'id':'S5','cutoff':'2026-10-07T15:30:00+00:00','horizon':'2026-10-07T18:30:00+00:00','setup_type':'BULLISH reclaim at PDL','expected':'UP'},
    {'id':'S6','cutoff':'2026-10-26T13:45:00+00:00','horizon':'2026-10-26T16:30:00+00:00','setup_type':'BULLISH reclaim at PDL','expected':'UP'},
    {'id':'S7','cutoff':'2026-11-10T13:30:00+00:00','horizon':'2026-11-10T16:30:00+00:00','setup_type':'BULLISH reclaim at PDL','expected':'UP'},
]

for s in setups:
    cutoff = datetime.fromisoformat(s['cutoff'])
    horizon = datetime.fromisoformat(s['horizon'])
    offsets = _exact_offsets(cutoff)
    realized, c0, c1 = _realized_direction(cutoff, horizon)
    print(f'=== {s["id"]} | cutoff {cutoff:%m-%d %H:%M} | M15 offset {offsets.get("M15",0)} | realized: {realized} ({c0:.2f}->{c1:.2f})')
    
    service, renders = _build_service('alchemist_mnsr_v2', '/tmp/bt_retry', offsets)
    r = _call(service, REPLAY_PROMPT, attempts=1, backoff_s=30.0)
    call = _extract_call(r['answer']) if r['ok'] else 'NO-ANSWER'
    agree = (call == realized) if realized in ("UP", "DOWN") else (call == "NO-TRADE")
    print(f'   call: {call} | realized: {realized} | agree: {agree} | ok: {r["ok"]}')
    if r['ok']:
        print(f'   answer tail: {r["answer"][-200:]}')
    print()
