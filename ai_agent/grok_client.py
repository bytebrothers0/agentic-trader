"""LLM client — Groq (default) or xAI Grok, both OpenAI-compatible, strict JSON out."""
from __future__ import annotations
from typing import Any, Dict
import json
import logging
import requests

logger = logging.getLogger("MSNR_LLM")

SYSTEM_PROMPT_BASE = """You are MSNR-Trader, a humanised XAUUSD analyst. You reason like a funded trader, not a chatbot.

Rules:
- Price truth comes ONLY from the MSNR snapshot. Never invent prices.
- Prefer MSNR signals: bias must agree with at least one msnr_signals entry or storylines, else bias=NO_TRADE.
- Output STRICT JSON only, no markdown, with keys:
  {"bias": "BULLISH|BEARISH|NEUTRAL|NO_TRADE", "setup": "...", "entry": number|null,
   "sl": number|null, "tp": number|null, "invalidation": "...",
   "confidence": 0-100, "reason_human": "warm 2-4 sentence human explanation",
   "indicator_toggles": [{"name": "MSNR_EMS_FVG", "enabled": true/false, "reason": "..."}],
   "news_risk": "low|normal|high"}
- Indicator toggles: ONLY names from ALLOWED_INDICATORS below. NEVER invent RSI, MACD, Bollinger, Stochastic or any name not in the list. Empty list is fine. Max 5 toggles per scan.
- If spread unknown, confidence <= 70. If news_risk=high, confidence <= 60 and widen invalidation.
- Propose-only: you suggest setup/entry/SL/TP. You never execute.
"""


def _system_prompt() -> str:
    try:
        from ai_agent.indicator_registry import ALL_INDICATORS
        allowed = ", ".join(ALL_INDICATORS)
    except Exception:
        allowed = "MSNR registry unavailable"
    return SYSTEM_PROMPT_BASE + f"\nALLOWED_INDICATORS ({len(allowed.split(','))} total, exact names only):\n{allowed}\n"


def _mock_proposal(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    sigs = snapshot.get("msnr_signals", []) or []
    if sigs:
        s = sigs[0]
        return {"bias": s["direction"], "setup": f"{s['model']} via {s['storyline']}",
                "entry": s["entry"], "sl": s["sl"], "tp": s["tp"],
                "invalidation": f"Opposite {s['direction']} close beyond SL",
                "confidence": 62.0,
                "reason_human": f"Hey — I like this {s['direction']} spot ({s['model']}). MSNR has {s['entry']} with SL {s['sl']} and TP {s['tp']}. {s['rationale']}",
                "indicator_toggles": [], "news_risk": "normal"}
    px = snapshot.get("current_price")
    return {"bias": "NO_TRADE", "setup": "No MSNR signal", "entry": None, "sl": None,
            "tp": None, "invalidation": "Wait for fresh storyline",
            "confidence": 20.0, "reason_human": "Hey — nothing clean right now. MSNR shows no ranked entry, so I'm sitting out rather than forcing it.",
            "indicator_toggles": [], "news_risk": "normal"}


def ask_grok(snapshot: Dict[str, Any], news: Dict[str, Any], api_key: str,
             base_url: str, model: str, mock: bool = False) -> Dict[str, Any]:
    return ask_llm(snapshot, news, api_key, base_url, model, mock=mock, provider="xai")


def ask_llm(snapshot: Dict[str, Any], news: Dict[str, Any], api_key: str,
            base_url: str, model: str, mock: bool = False,
            provider: str = "groq") -> Dict[str, Any]:
    if mock or not api_key:
        return _mock_proposal(snapshot)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": json.dumps({"snapshot": snapshot, "news": {
                "summary": news.get("summary", ""),
                "risk_hint": news.get("risk_hint", "unknown"),
                "headlines": [r.get("title", "") for r in news.get("results", [])],
            }})},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(f"{base_url.rstrip('/')}/chat/completions",
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json"},
                          json=payload, timeout=60)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return _sanitize_toggles(data)
    except Exception as e:
        logger.warning("%s LLM failed (%s) — falling back to deterministic mock.", provider, e)
        out = _mock_proposal(snapshot)
        out["reason_human"] += f" [{provider} unreachable, using MSNR fallback]"
        return out


def _sanitize_toggles(data: Dict[str, Any]) -> Dict[str, Any]:
    """Drop any invented indicator names. Exact allowlist match only."""
    try:
        from ai_agent.indicator_registry import ALL_INDICATORS
        allowed = set(ALL_INDICATORS)
    except Exception:
        data["indicator_toggles"] = []
        return data
    clean = []
    for t in (data.get("indicator_toggles", []) or [])[:5]:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", "")).strip()
        if name in allowed:
            clean.append({"name": name, "enabled": bool(t.get("enabled", True)),
                          "reason": str(t.get("reason", ""))[:200]})
    data["indicator_toggles"] = clean
    return data
