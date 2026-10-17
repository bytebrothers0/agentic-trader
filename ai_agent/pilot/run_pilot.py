"""
Pilot: teach the AI route to read TS_M15 setups like a pro chart reader.

Side experiment — nothing here touches the live system. Phases:
  build    : 26 chart-reading packs from v8 (NO outcome in the prompt)
  analyze  : 1 Groq call per setup -> TAKE/PASS verdict (paced, resumable)
  score    : verdicts vs actual outcomes (confusion + R of approved set)
  revise   : 1 call — feed the misses back, get a revised checklist

Usage:
  python ai_agent/pilot/run_pilot.py --phase build
  python ai_agent/pilot/run_pilot.py --phase analyze
  python ai_agent/pilot/run_pilot.py --phase score
  python ai_agent/pilot/run_pilot.py --phase revise
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
os.chdir(BOT_DIR)
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import pandas as pd  # noqa: E402

PILOT_DIR = os.path.join(BOT_DIR, "ai_agent", "pilot")
PACKS = os.path.join(PILOT_DIR, "packs.jsonl")
VERDICTS = os.path.join(PILOT_DIR, "verdicts.jsonl")
SCORECARD = os.path.join(PILOT_DIR, "scorecard.json")
CHECKLIST = os.path.join(PILOT_DIR, "checklist.md")

READER_SYSTEM = """You are a professional XAUUSD price-action reader (SMC: liquidity \
sweeps, BOS/CHOCH, QM, IDM, OB/FVG). You judge ONE M15 setup at a time.

Rules:
- Price truth comes ONLY from the pack. Never invent prices or bars.
- Think like a discretionary pro: expectations vs what price did, whether \
the QM belongs to the current legs, whether the break is same-side and \
decisive, whether liquidity was actually raided or the level just drifted \
through, confluence quality, and what happens if the entry fills.
- Output STRICT JSON only, no markdown:
{"verdict": "TAKE|PASS", "confidence": 0-100,
 "reasons": ["...", "..."],
 "expectation": "one sentence on what price should do next if taken",
 "invalidation": "what price action kills the idea",
 "change_my_mind": "what would flip this verdict",
 "lesson_tags": ["stale-qm"|"wrong-side-break"|"no-confluence"|"clean-legs"|"late-entry"|"thin-stop"|"fresh-sweep"|"other"]}
"""

REVISE_SYSTEM = """You are a trading coach reviewing a junior reader's scorecard \
on 26 backtested M15 setups (outcome now known). Extract durable lessons: \
which mistake patterns cost money, which filters would have kept winners \
while dropping losers. Output STRICT JSON only:
{"patterns": [{"name": "...", "cost_R": 0.0, "rule": "..."}],
 "checklist": ["...", "..."],
 "notes": "..."}"""


def load_frames():
    from data.mt5_loader import MT5DataLoader
    loader = MT5DataLoader(symbol="XAUUSD")
    print("fetching M15/H4/D1...", flush=True)
    return {
        "M15": loader.fetch_timeframe("M15", count=1500),
        "H4": loader.fetch_timeframe("H4", count=300),
        "D1": loader.fetch_timeframe("D1", count=120),
    }


def bars_compact(df, end, n):
    win = df[df.index <= end].tail(n)
    return [{"t": t.strftime("%m-%d %H:%M"), "o": round(r.open, 2),
             "h": round(r.high, 2), "l": round(r.low, 2),
             "c": round(r.close, 2)} for t, r in win.iterrows()]


def phase_build():
    frames = load_frames()
    j = pd.read_csv("backtest/journal_Sep28-Oct02_v8.csv",
                    parse_dates=["signal_date"])
    h4 = frames["H4"]
    d1 = frames["D1"]
    m15 = frames["M15"]
    h, l, c = m15["high"], m15["low"], m15["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / 14, min_periods=1, adjust=False).mean()
    os.makedirs(PILOT_DIR, exist_ok=True)
    n = 0
    with open(PACKS, "w", encoding="utf-8") as fh:
        for i, r in j.iterrows():
            sig = r.signal_date.tz_convert("UTC")
            risk = abs(r.entry - r.sl)
            pack = {
                "setup_id": int(i) + 1,
                "direction": r.direction,
                "entry": round(float(r.entry), 3),
                "sl": round(float(r.sl), 3),
                "tp": round(float(r.tp), 3),
                "risk": round(float(risk), 3),
                "rr": round(abs(r.tp - r.entry) / risk, 2) if risk > 0 else 0,
                "signal_time": sig.strftime("%Y-%m-%d %H:%M"),
                "confidence": r.confidence,
                "ts_side": r.ts_side or None,
                "ts_price": r.ts_price or None,
                "break_kind": r.break_kind or None,
                "qm_entry_level": r.qm_entry_level or None,
                "liq": (f"{r.liq_kind}@{r.liq_price}"
                        if str(r.liq_kind) not in ("", "nan") else None),
                "fallback": r.fallback == "yes",
                "confluence": r.confluence or None,
                "chain": r.chain,
                "atr14": round(float(atr[atr.index <= sig].iloc[-1]), 2),
                "m15_last60": bars_compact(m15, sig, 60),
                "h4_last24": bars_compact(h4, sig, 24),
                "d1_last10": bars_compact(d1, sig, 10),
                # outcome stored for scoring ONLY — never sent in the prompt
                "_outcome": r.outcome,
                "_R": float(r.R),
            }
            fh.write(json.dumps(pack) + "\n")
            n += 1
    print(f"wrote {n} packs -> {PACKS}")


def llm_call(system, user_obj):
    from ai_agent import config as cfg
    from ai_agent.grok_client import ask_llm
    if cfg.LLM_PROVIDER == "xai":
        key, base, model = cfg.XAI_API_KEY, cfg.XAI_BASE_URL, cfg.GROK_MODEL
    else:
        key, base, model = (cfg.GROQ_API_KEY, cfg.GROQ_BASE_URL,
                            cfg.GROQ_MODEL)
    import requests
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_obj)},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    last = None
    for attempt in range(4):
        try:
            r = requests.post(f"{base.rstrip('/')}/chat/completions",
                              headers={"Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json"},
                              json=payload, timeout=90)
            r.raise_for_status()
            return json.loads(
                r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            last = e
            status = getattr(getattr(e, "response", None), "status_code",
                             None)
            wait = 45 if status == 429 else 10
            print(f"  call failed ({str(e)[:80]}), retry in {wait}s...",
                  flush=True)
            time.sleep(wait)
    return {"_api_fail": str(last)[:200]}


def read_jsonl(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def phase_analyze():
    packs = read_jsonl(PACKS)
    done = {v["setup_id"] for v in read_jsonl(VERDICTS)
            if "setup_id" in v}
    print(f"{len(packs)} packs, {len(done)} already judged", flush=True)
    with open(VERDICTS, "a", encoding="utf-8") as fh:
        for p in packs:
            if p["setup_id"] in done:
                continue
            prompt = {k: v for k, v in p.items() if not k.startswith("_")}
            print(f"judging setup {p['setup_id']}/26 "
                  f"({p['direction']} {p['entry']})...", flush=True)
            v = llm_call(READER_SYSTEM, {"setup_pack": prompt})
            v["setup_id"] = p["setup_id"]
            fh.write(json.dumps(v) + "\n")
            fh.flush()
            time.sleep(8)  # pace for rate limits
    print("analyze complete")


def phase_score():
    packs = {p["setup_id"]: p for p in read_jsonl(PACKS)}
    verdicts = read_jsonl(VERDICTS)
    rows = []
    for v in verdicts:
        p = packs.get(v.get("setup_id"))
        if not p or v.get("_api_fail"):
            continue
        take = (str(v.get("verdict", "")).upper() == "TAKE")
        win = p["_outcome"] == "TP"
        rows.append({"id": p["setup_id"], "take": take, "win": win,
                     "R": p["_R"] if take else 0.0,
                     "conf": v.get("confidence"),
                     "tags": v.get("lesson_tags")})
    tp_take = sum(1 for r in rows if r["take"] and r["win"])
    tp_pass = sum(1 for r in rows if not r["take"] and r["win"])
    sl_take = sum(1 for r in rows if r["take"] and not r["win"])
    sl_pass = sum(1 for r in rows if not r["take"] and not r["win"])
    appr_R = round(sum(r["R"] for r in rows), 2)
    card = {
        "judged": len(rows),
        "TP_taken": tp_take,
        "TP_passed_missed": tp_pass,
        "SL_taken_mistake": sl_take,
        "SL_passed_saved": sl_pass,
        "approved_R": appr_R,
        "take_rate": round(sum(1 for r in rows if r["take"]) / len(rows), 3)
        if rows else 0,
        "misses": [r for r in rows
                   if (r["take"] and not r["win"])
                   or (not r["take"] and r["win"])],
    }
    with open(SCORECARD, "w", encoding="utf-8") as fh:
        json.dump(card, fh, indent=2)
    print(json.dumps({k: v for k, v in card.items() if k != "misses"},
                     indent=2))
    print(f"missedetails in {SCORECARD}")


def phase_revise():
    card = json.load(open(SCORECARD, encoding="utf-8"))
    packs = {p["setup_id"]: p for p in read_jsonl(PACKS)}
    verdicts = {v["setup_id"]: v for v in read_jsonl(VERDICTS)}
    cases = []
    for m in card.get("misses", []):
        p, v = packs[m["id"]], verdicts[m["id"]]
        cases.append({
            "setup_id": m["id"],
            "direction": p["direction"],
            "entry": p["entry"],
            "chain": p["chain"],
            "ai_verdict": v.get("verdict"),
            "ai_reasons": v.get("reasons"),
            "actual": "TP" if m["win"] else "SL",
        })
    out = llm_call(REVISE_SYSTEM, {"scorecard": {
        k: v for k, v in card.items() if k != "misses"},
        "mistakes": cases})
    with open(os.path.join(PILOT_DIR, "revision.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    lines = ["# Pilot checklist (rev 1, mistake-driven)\n"]
    for i, c in enumerate(out.get("checklist", []), 1):
        lines.append(f"{i}. {c}\n")
    lines.append("\n## Costly patterns\n")
    for p in out.get("patterns", []):
        lines.append(f"- **{p.get('name')}** (~{p.get('cost_R')}R): "
                     f"{p.get('rule')}\n")
    if out.get("notes"):
        lines.append(f"\n{out['notes']}\n")
    with open(CHECKLIST, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    print(f"revision saved -> {CHECKLIST}")


def main():
    ap = argparse.ArgumentParser(description="AI chart-reader pilot")
    ap.add_argument("--phase", required=True,
                    choices=["build", "analyze", "score", "revise"])
    args = ap.parse_args()
    {"build": phase_build, "analyze": phase_analyze, "score": phase_score,
     "revise": phase_revise}[args.phase]()


if __name__ == "__main__":
    main()
