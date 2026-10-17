"""TS entry validator — LLM second opinion on mechanical TS M15 signals.

The engine finds candidates; this judge grades them against the written
strategy and returns ENTER or SKIP. Fail-closed: any malformed model output,
any exception, or low confidence becomes SKIP, never ENTER.

Usage:
    from ai_agent.ts_validator import validate_signal
    verdict = validate_signal(snapshot)  # real LLM (needs GROQ/XAI key)
    verdict = validate_signal(snapshot, mock=True)  # deterministic offline stub
"""
from __future__ import annotations

from typing import Any, Dict, List

from ai_agent import config as cfg
from ai_agent.grok_client import ask_llm
from ai_agent.journal import log_proposal


TS_VALIDATOR_SYSTEM = """You are TS-Judge, a strict Smart Money Concepts validator. Output STRICT JSON only, no markdown, exactly:
{"verdict": "ENTER|SKIP", "confidence": 0-100, "reasons": ["..."], "failed_checks": ["..."], "invalidation": "..."}
The candidate brief and grading rubric arrive in the user message. SKIP mediocre setups freely."""

TS_VALIDATOR_BRIEF = """You are TS-Judge, a strict Smart Money Concepts validator for MNSR+TS entries on XAUUSD M15. A mechanical engine proposes a candidate; you decide ENTER or SKIP. You are expected to SKIP mediocre setups — a high SKIP rate on choppy tapes is correct behavior, not failure.

THE STRATEGY (mechanical chain that produced this candidate):
1. TS (turtle soup): a two-candle wick sweep whose body closes back inside. TS_LOW (sweep of lows) biases LONG, TS_HIGH biases SHORT. Bigger sweeps relative to ATR are more significant; sub-0.25x ATR sweeps are dust.
2. BREAK after the TS: a BOS/CHoCH close-through, or a body close through the nearest S/R shelf (impulse-proof leg).
3. QM: a Quasimodo shoulder that already existed when liquidity formed, sitting between the TS extreme and the break level, on the near side of the liquidity (LONG: below it, SHORT: above it).
4. LIQUIDITY: first structural IDM after the break, else the most recent fractal swing extreme ("wick low/high" liquidity).
5. ENTRY: limit order at the QM (or nearest support/resistance in the no-liquidity fallback). SL beyond the TS extreme, TP far (about 8.5R on fixed stops).
6. CONFLUENCE (optional boost): entry overlapping an OB / FVG / Breaker / IFVG zone.

GRADE THESE CHECKS (fail any single one and lean SKIP):
- C1 TS quality: sweep size vs ATR (given as sweep_atr_ratio). <0.3 is weak, >0.5 is strong. Wick-only micro-sweeps in chop are the #1 false-positive source.
- C2 Break quality: BOS on a real swing beats a shelf touch. Breaks inside overlapping chop (break level within half ATR of surrounding chop) are weak.
- C3 QM placement: must sit clearly between the TS extreme and the break level with daylight on both sides. A QM crammed within ~1 point of the liquidity, or nearly touching the break level, gets run over — SKIP.
- C4 Liquidity freshness: structural IDM beats fractal LIQ; fallback (no liquidity at all) is the weakest — SKIP fallbacks unless confluence is strong.
- C5 Chop check: if the last 10-15 candles show overlapping bodies with no displacement (entry sitting mid-range with the stop inside routine chop), SKIP. Entries need room: stop distance should exceed roughly half the recent chop range.
- C6 Confluence: OB/FVG/Breaker/IFVG overlap at entry is a plus, not a requirement. No confluence + any other weakness = SKIP.

Price truth comes ONLY from the snapshot candles and levels. Never invent prices.
Output STRICT JSON only, no markdown:
{"verdict": "ENTER|SKIP", "confidence": 0-100,
 "reasons": ["short phrase", ...], "failed_checks": ["C1"|"C2"|...],
 "invalidation": "one line: what proves this wrong"}
Rules: verdict must be exactly ENTER or SKIP. Confidence <60 forces SKIP regardless. Fallback entries cap at 55.
"""


def build_ts_snapshot(candles: List[Dict[str, Any]], signal: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the judge's snapshot from recent candles + engine signal fields.

    candles: [{time, open, high, low, close}] oldest-first, ending at (or just
      after) the signal bar. signal: /api/signals-style dict with entry_price,
      stop_loss, take_profit, direction, confidence, rationale and, when
      present, ts_price, qm_entry_level, liq_kind, liq_price, break_kind,
      confluence, fallback.
    """
    return {
        "symbol": signal.get("symbol", "XAUUSD"),
        "timeframe": "M15",
        "direction": signal.get("direction"),
        "entry": signal.get("entry_price"),
        "sl": signal.get("stop_loss"),
        "tp": signal.get("take_profit"),
        "engine_confidence": signal.get("confidence"),
        "engine_rationale": signal.get("storyline") or signal.get("rationale"),
        "ts_price": signal.get("ts_price"),
        "qm_entry_level": signal.get("qm_entry_level"),
        "liq_kind": signal.get("liq_kind"),
        "liq_price": signal.get("liq_price"),
        "break_kind": signal.get("break_kind"),
        "confluence": signal.get("confluence"),
        "fallback": signal.get("fallback"),
        "candles": candles[-40:],
    }


def _creds():
    if cfg.LLM_PROVIDER == "groq" or (cfg.GROQ_API_KEY and not cfg.XAI_API_KEY):
        return cfg.GROQ_API_KEY, cfg.GROQ_BASE_URL, cfg.GROQ_MODEL, "groq"
    if cfg.LLM_PROVIDER == "xai" or cfg.XAI_API_KEY:
        return cfg.XAI_API_KEY, cfg.XAI_BASE_URL, cfg.GROK_MODEL, "xai"
    return cfg.GROQ_API_KEY, cfg.GROQ_BASE_URL, cfg.GROQ_MODEL, "groq"


def _mock_verdict(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "verdict": "SKIP",
        "confidence": 50.0,
        "reasons": ["mock mode: no LLM call made"],
        "failed_checks": ["MOCK"],
        "invalidation": "n/a (mock)",
    }


def _normalize(raw: Any) -> Dict[str, Any]:
    """Fail-closed parse: anything off-spec becomes SKIP."""
    out = {"verdict": "SKIP", "confidence": 0.0, "reasons": [],
           "failed_checks": ["PARSE"], "invalidation": ""}
    try:
        data = raw if isinstance(raw, dict) else {}
        verdict = str(data.get("verdict", "SKIP")).strip().upper()
        conf = float(data.get("confidence", 0) or 0)
        reasons = data.get("reasons", []) or []
        failed = data.get("failed_checks", []) or []
        out["reasons"] = [str(r)[:200] for r in reasons if isinstance(r, (str, int, float))][:6]
        out["failed_checks"] = [str(f)[:10] for f in failed if isinstance(f, (str, int, float))][:6]
        out["invalidation"] = str(data.get("invalidation", ""))[:500]
        out["confidence"] = max(0.0, min(100.0, conf))
        if verdict == "ENTER" and out["confidence"] >= 60:
            out["verdict"] = "ENTER"
            if not out["failed_checks"]:
                out["failed_checks"] = []
        else:
            if verdict == "ENTER" and out["confidence"] < 60:
                out["failed_checks"] = sorted(set(out["failed_checks"] + ["CONF"]))
    except Exception:
        pass
    return out


def validate_signal(snapshot: Dict[str, Any], mock: bool = False) -> Dict[str, Any]:
    """Judge one TS candidate. Returns the normalized verdict dict."""
    use_mock = mock or cfg.AI_MOCK
    if use_mock:
        verdict = _mock_verdict(snapshot)
        verdict["_source"] = "mock"
    else:
        _key, _url, _model, _provider = _creds()
        news = {"summary": "", "risk_hint": "unknown", "results": []}
        try:
            import json as _json
            payload_snapshot = {"brief": TS_VALIDATOR_BRIEF,
                                "candidate": snapshot}
            raw = ask_llm(payload_snapshot, news, _key, _url, _model,
                          mock=False, provider=_provider,
                          system_prompt=TS_VALIDATOR_SYSTEM)
            if isinstance(raw, str):
                try:
                    raw = _json.loads(raw)
                except Exception:
                    raw = {}
            from_mock_fallback = not (isinstance(raw, dict) and "verdict" in raw)
            verdict = _normalize(raw)
            verdict["_source"] = "fallback" if from_mock_fallback else "model"
        except Exception as e:
            verdict = {"verdict": "SKIP", "confidence": 0.0,
                       "reasons": [f"validator error: {e}"[:200]],
                       "failed_checks": ["ERROR"], "invalidation": "",
                       "_source": "error"}
    try:
        log_proposal({"type": "ts_validation", **verdict,
                      "entry": snapshot.get("entry"),
                      "direction": snapshot.get("direction")},
                     {"provider": _provider if not use_mock else "mock"})
    except Exception:
        pass
    return verdict
