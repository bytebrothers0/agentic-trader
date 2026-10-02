"""Proposal lifecycle: ids, expiry, execution linkage, watchlist, dedupe.

Statuses: PROPOSED -> EXECUTED | EXPIRED | INVALIDATED | SUPERSEDED
- id = stable hash of symbol+bias+rounded entry/sl/tp (same setup = same id).
- created_at / expires_at (default 8h) on every new proposal.
- executed = a live MT5 position/pending order matches symbol+direction+entry.
- duplicate = same id re-proposed while PROPOSED (no new alert, just refresh).
- watchlist = next ranked MSNR signals so the trader always has a next plan.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ai_agent import config as cfg

STORE_PATH = os.path.join(cfg.STATE_DIR, "proposals.json")
EXPIRY_HOURS = float(os.getenv("AI_PROPOSAL_EXPIRY_HOURS", "8"))
ENTRY_TOLERANCE_PCT = 0.002  # 0.2% price proximity = same setup


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_id(symbol: str, bias: str, entry: Any, sl: Any, tp: Any) -> str:
    key = f"{str(symbol).upper()}|{str(bias).upper()}|{entry}|{sl}|{tp}"
    return "P-" + hashlib.sha1(key.encode()).hexdigest()[:10]


def _load_store() -> Dict[str, Dict]:
    try:
        if os.path.isfile(STORE_PATH):
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_store(store: Dict[str, Dict]) -> None:
    os.makedirs(cfg.STATE_DIR, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def _sweep(store: Dict[str, Dict]) -> None:
    """Expire stale PROPOSED records."""
    now = _now()
    for rec in store.values():
        if rec.get("status") != "PROPOSED":
            continue
        try:
            exp = datetime.fromisoformat(rec["expires_at"])
            if now >= exp:
                rec["status"] = "EXPIRED"
        except Exception:
            pass


def find_execution_match(proposal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Match proposal against live MT5 positions + pending orders.

    Same symbol, same direction, entry within tolerance. Returns match or None.
    Propose-only safe: read-only, never trades.
    """
    try:
        from execution.order_manager import OrderManager
        om = OrderManager()
        positions = om.get_open_positions()
        pendings = om.get_pending_orders()
    except Exception:
        return None
    try:
        entry = float(proposal.get("entry"))
    except Exception:
        return None
    want_buy = str(proposal.get("bias", "")).upper() == "BULLISH"
    sym = str(proposal.get("symbol", "") or proposal.get("symbol_resolved", "")).upper()

    def _close(a: float, b: float) -> bool:
        return abs(a - b) / max(abs(b), 1e-9) <= ENTRY_TOLERANCE_PCT

    for p in list(positions) + list(pendings):
        try:
            psym = str(p.symbol).upper()
            # broker suffix tolerance: XAUUSDm contains XAUUSD
            if sym and psym and (sym not in psym and psym not in sym):
                continue
            is_buy = "BUY" in str(p.order_type).upper() and "LIMIT" not in str(p.order_type).upper() or \
                     str(p.order_type).upper() == "BUY" or str(p.order_type).upper() == "BUY_LIMIT"
            is_sell = not is_buy if "BUY" in str(p.order_type).upper() or "SELL" in str(p.order_type).upper() else None
            if want_buy and "SELL" in str(p.order_type).upper():
                continue
            if not want_buy and str(p.order_type).upper().startswith("BUY"):
                continue
            ref = float(p.open_price)
            if _close(ref, entry):
                return {"ticket": p.ticket, "type": p.order_type, "open_price": ref,
                        "lots": p.volume, "profit": getattr(p, "profit", 0.0)}
        except Exception:
            continue
    return None


def build_watchlist(snapshot: Dict[str, Any], active_id: Optional[str], n: int = 3) -> List[Dict[str, Any]]:
    out = []
    seen = {active_id}
    for s in (snapshot.get("msnr_signals", []) or [])[:n + 4]:
        try:
            wid = make_id(snapshot.get("symbol", ""), s.get("direction", ""),
                          s.get("entry"), s.get("sl"), s.get("tp"))
        except Exception:
            continue
        if wid == active_id:
            continue
        if wid in seen:
            continue
        seen.add(wid)
        out.append({"id": wid, "model": s.get("model"), "direction": s.get("direction"),
                    "entry": s.get("entry"), "sl": s.get("sl"), "tp": s.get("tp"),
                    "confidence": s.get("confidence"), "distance": s.get("distance")})
        if len(out) >= n:
            break
    return out


def track(proposal: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Register/update lifecycle for one proposal. Returns lifecycle block."""
    store = _load_store()
    _sweep(store)

    pid = make_id(proposal.get("symbol", ""), proposal.get("bias", ""),
                  proposal.get("entry"), proposal.get("sl"), proposal.get("tp"))
    now = _now()
    existing = store.get(pid)

    match = find_execution_match({**proposal, "symbol_resolved": snapshot.get("symbol", "")})
    if match:
        status = "EXECUTED"
    elif existing and existing.get("status") == "EXECUTED":
        status = "EXECUTED"  # sticky once executed
    else:
        status = "PROPOSED"

    if existing and existing.get("status") in ("PROPOSED", "EXECUTED") and status == existing.get("status"):
        # same setup re-proposed: refresh, flag duplicate, supersede others later
        existing["last_seen_at"] = now.isoformat()
        existing["refresh_count"] = int(existing.get("refresh_count", 1)) + 1
        existing["execution"] = match
        duplicate = True
        created_at = existing.get("created_at", now.isoformat())
        expires_at = existing.get("expires_at", (now + timedelta(hours=EXPIRY_HOURS)).isoformat())
        existing["expires_at"] = expires_at
        _save_store(store)
    else:
        duplicate = False
        created_at = now.isoformat()
        expires_at = (now + timedelta(hours=EXPIRY_HOURS)).isoformat()
        # supersede other PROPOSED records for same symbol+direction
        for oid, rec in store.items():
            if oid != pid and rec.get("status") == "PROPOSED" and \
               str(rec.get("symbol", "")).upper() == str(proposal.get("symbol", "")).upper():
                rec["status"] = "SUPERSEDED"
        store[pid] = {"id": pid, "symbol": proposal.get("symbol", ""),
                      "bias": proposal.get("bias"), "entry": proposal.get("entry"),
                      "sl": proposal.get("sl"), "tp": proposal.get("tp"),
                      "status": status, "created_at": created_at,
                      "last_seen_at": now.isoformat(), "expires_at": expires_at,
                      "refresh_count": 1,
                      "execution": match}
        _save_store(store)

    rec = store.get(pid, {})
    watchlist = build_watchlist(snapshot, pid)

    active = [{"id": k, **v} for k, v in store.items()
              if v.get("status") in ("PROPOSED", "EXECUTED")]
    active.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    return {"id": pid, "status": status, "duplicate": duplicate,
            "created_at": created_at, "expires_at": expires_at,
            "refresh_count": rec.get("refresh_count", 1),
            "execution": match, "watchlist": watchlist,
            "active": [{"id": a["id"], "symbol": a.get("symbol"), "bias": a.get("bias"),
                        "entry": a.get("entry"), "status": a.get("status"),
                        "expires_at": a.get("expires_at")} for a in active[:10]]}
