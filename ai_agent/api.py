"""FastAPI router — mount into server.py. Propose-only endpoints."""
from __future__ import annotations
import json
import os
from typing import Any, Dict
from fastapi import APIRouter

router = APIRouter(prefix="/api/ai", tags=["ai"])

from ai_agent import config as cfg
from ai_agent import indicator_registry as reg
from ai_agent.journal import recent as journal_recent


@router.get("/proposal")
def get_proposal() -> Dict[str, Any]:
    if not os.path.isfile(cfg.PROPOSAL_PATH):
        return {"verdict": "NONE", "detail": "No proposal yet. Run: python -m ai_agent.agent_loop --symbol XAUUSD"}
    with open(cfg.PROPOSAL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/scan")
def run_scan(symbol: str = "XAUUSD", mock: bool = False) -> Dict[str, Any]:
    from ai_agent.agent_loop import run_once
    try:
        return run_once(symbol, mock=mock)
    except Exception as e:
        return {"verdict": "ERROR", "detail": str(e)}


@router.get("/indicators")
def get_indicators() -> Dict[str, Any]:
    return reg.summary()


@router.post("/indicators")
def set_indicators(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Manual override: {toggles: [{name, enabled}]} — same path the AI uses."""
    toggles = payload.get("toggles", []) or []
    state = reg.apply_toggles(toggles)
    return reg.summary(state)


@router.get("/journal")
def get_journal(n: int = 20) -> Dict[str, Any]:
    return {"entries": journal_recent(min(max(n, 1), 100))}


@router.get("/proposals")
def get_proposals() -> Dict[str, Any]:
    """Active lifecycle records: PROPOSED/EXECUTED with id, expiry, watchlist."""
    import json as _json
    import os as _os
    from ai_agent.lifecycle import STORE_PATH
    if not _os.path.isfile(STORE_PATH):
        return {"active": [], "detail": "No lifecycle records yet. Run a scan first."}
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        store = _json.load(f)
    active = [{"id": k, **v} for k, v in store.items()
              if v.get("status") in ("PROPOSED", "EXECUTED")]
    active.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"active": active[:20], "count": len(active)}


@router.post("/validate-ts")
def validate_ts(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Judge one TS M15 candidate: {symbol, signal: {...}} -> verdict dict.

    signal follows /api/signals shape (direction, entry_price, stop_loss,
    take_profit, confidence, storyline, + ts_price, qm_entry_level,
    liq_kind, liq_price, break_kind, confluence, fallback when known).
    """
    from ai_agent.ts_validator import build_ts_snapshot, validate_signal
    symbol = str(payload.get("symbol", "XAUUSD"))
    signal = payload.get("signal", {}) or {}
    mock = bool(payload.get("mock", False))
    try:
        from data.mt5_loader import MT5DataLoader
        df = MT5DataLoader(symbol=symbol).fetch_timeframe("M15", count=120)
        candles = [{"time": int(r["time"]), "open": float(r["open"]),
                    "high": float(r["high"]), "low": float(r["low"]),
                    "close": float(r["close"])} for _, r in df.iterrows()]
    except Exception as e:
        return {"verdict": "SKIP", "confidence": 0.0,
                "reasons": [f"candle fetch failed: {e}"[:200]],
                "failed_checks": ["DATA"], "invalidation": ""}
    snapshot = build_ts_snapshot(candles[-60:], {"symbol": symbol, **signal})
    verdict = validate_signal(snapshot, mock=mock)
    return {"symbol": symbol, **verdict}
