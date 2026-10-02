"""Tavily web-search layer — macro/news context only, never a trade trigger."""
from __future__ import annotations
from typing import Any, Dict
import logging
import requests

logger = logging.getLogger("MSNR_Tavily")


def fetch_news_context(symbol: str, api_key: str, max_results: int = 5) -> Dict[str, Any]:
    """Search gold/macro news. Returns {summary, results, risk_hint}."""
    if not api_key:
        return {"summary": "", "results": [], "risk_hint": "unknown",
                "warning": "No TAVILY_API_KEY — news layer disabled."}
    query = f"{symbol} gold forex macroeconomic news central bank Fed CPI NFP"
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "search_depth": "basic",
                  "max_results": max_results, "time_range": "day",
                  "include_answer": True},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
        answer = str(data.get("answer", "") or "")[:1500]
        results = []
        for it in (data.get("results", []) or [])[:max_results]:
            results.append({"title": it.get("title", "")[:200],
                            "url": it.get("url", ""),
                            "snippet": str(it.get("content", ""))[:400]})
        blob = (answer + " ".join(x["title"] + x["snippet"] for x in results)).lower()
        high_kw = ("nfp", "nonfarm", "fomc", "rate decision", "cpi", "war", "missile",
                   "emergency", "halt", "intervention")
        risk_hint = "high" if any(k in blob for k in high_kw) else "normal"
        return {"summary": answer, "results": results, "risk_hint": risk_hint}
    except Exception as e:
        logger.warning("Tavily failed: %s", e)
        return {"summary": "", "results": [], "risk_hint": "unknown",
                "warning": f"Tavily error: {e}"}
