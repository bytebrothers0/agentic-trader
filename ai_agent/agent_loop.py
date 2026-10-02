"""Orchestrator: snapshot -> Tavily -> Grok -> validate -> toggle indicators -> journal.

Usage:
    python -m ai_agent.agent_loop --symbol XAUUSD
    python -m ai_agent.agent_loop --symbol XAUUSD --mock   # no API spend
"""
from __future__ import annotations
import argparse
import json
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("MSNR_Agent")

from ai_agent import config as cfg
from ai_agent import indicator_registry as reg
from ai_agent.msnr_snapshot import build_snapshot
from ai_agent.tavily_client import fetch_news_context
from ai_agent.grok_client import ask_llm
from ai_agent.schemas import AIProposal
from ai_agent.decision_layer import validate
from ai_agent.journal import log_proposal


def _llm_creds():
    """Pick Groq by default (user key), fall back to xAI."""
    if cfg.LLM_PROVIDER == "groq" or (cfg.GROQ_API_KEY and not cfg.XAI_API_KEY):
        return cfg.GROQ_API_KEY, cfg.GROQ_BASE_URL, cfg.GROQ_MODEL, "groq"
    if cfg.LLM_PROVIDER == "xai" or cfg.XAI_API_KEY:
        return cfg.XAI_API_KEY, cfg.XAI_BASE_URL, cfg.GROK_MODEL, "xai"
    return cfg.GROQ_API_KEY, cfg.GROQ_BASE_URL, cfg.GROQ_MODEL, "groq"


def run_once(symbol: str | None = None, mock: bool = False) -> dict:
    symbol = symbol or cfg.SYMBOL_DEFAULT
    use_mock = mock or cfg.AI_MOCK

    snapshot = build_snapshot(symbol)
    news = fetch_news_context(snapshot.get("symbol", symbol), cfg.TAVILY_API_KEY)
    _key, _url, _model, _provider = _llm_creds()
    raw = ask_llm(snapshot, news, _key, _url, _model, mock=use_mock, provider=_provider)

    proposal = AIProposal.from_grok(raw)
    if not proposal.news_risk or proposal.news_risk == "normal":
        if news.get("risk_hint") in ("high", "low"):
            proposal.news_risk = news["risk_hint"]
    proposal = validate(proposal, snapshot, min_confidence=cfg.MIN_CONFIDENCE)

    # Auto-toggle indicators (max 8, known names only)
    state_before = reg.load()
    state_after = reg.apply_toggles(proposal.indicator_toggles[:8], state_before)
    tog_summary = reg.summary(state_after)

    out = proposal.to_dict()
    out["symbol"] = snapshot.get("symbol", symbol)
    out["current_price"] = snapshot.get("current_price")
    out["indicators"] = tog_summary
    out["mt5_live"] = snapshot.get("mt5_live", {})
    out["data_truth"] = snapshot.get("data_truth", "unknown")
    out["news_headlines"] = [r.get("title", "") for r in news.get("results", [])]

    # Lifecycle: id, timestamps, execution link, watchlist, dedupe.
    try:
        from ai_agent.lifecycle import track
        out["lifecycle"] = track(out, snapshot)
    except Exception as e:
        out["lifecycle"] = {"status": "UNKNOWN", "error": str(e)}

    os.makedirs(cfg.STATE_DIR, exist_ok=True)
    with open(cfg.PROPOSAL_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    log_proposal(out, {"symbol": symbol, "mock": use_mock, "provider": _provider,
                       "msnr_signals": len(snapshot.get("msnr_signals", []))})

    logger.info("Verdict=%s bias=%s entry=%s conf=%.0f | lifecycle=%s dup=%s | indicators %d on/%d off",
                out["verdict"], out["bias"], out.get("entry"),
                out.get("confidence", 0), out.get("lifecycle", {}).get("status"),
                out.get("lifecycle", {}).get("duplicate"),
                tog_summary["enabled"], tog_summary["disabled"])
    logger.info("Human: %s", out.get("reason_human", "")[:300])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="MSNR AI humanised trader (propose-only)")
    ap.add_argument("--symbol", default=cfg.SYMBOL_DEFAULT)
    ap.add_argument("--mock", action="store_true", help="No API calls; deterministic fallback")
    args = ap.parse_args()
    result = run_once(args.symbol, mock=args.mock)
    print(json.dumps(result, indent=2))
