"""Builds the structured market snapshot Grok reasons over.

Uses the existing deterministic stack (MT5DataLoader + StorylineEngine +
EntryEngine + RiskManager + account/positions) so the AI never sees raw
noise — only MSNR-validated state.
"""
from __future__ import annotations
from typing import Any, Dict, List
import logging

logger = logging.getLogger("MSNR_Snapshot")


def build_snapshot(symbol: str = "XAUUSD", max_signals: int = 5) -> Dict[str, Any]:
    from data.mt5_loader import MT5DataLoader
    from strategy.storyline_engine import StorylineEngine
    from strategy.entry_engine import EntryEngine
    from execution.risk_manager import RiskManager
    from execution.order_manager import OrderManager
    from ai_agent import indicator_registry as reg

    loader = MT5DataLoader(symbol=symbol)
    dfs = loader.fetch_all_timeframes()

    # Current price from H1/D1 close
    current_price = None
    for tf in ("H1", "D1", "H4", "M15"):
        if tf in dfs and len(dfs[tf]):
            current_price = float(dfs[tf]["close"].iloc[-1])
            break

    # Storylines
    sl_engine = StorylineEngine(dfs)
    storylines = sl_engine.analyze_all()
    sl_list = []
    for k, v in storylines.items():
        sl_list.append({
            "key": k, "htf": v.htf, "ltf": v.ltf,
            "bias": v.bias.value, "rejection": round(float(v.rejection_price), 2),
            "desc": v.rejection_level_desc,
        })

    # Entry signals (deterministic MSNR proposals)
    entry_eng = EntryEngine(dfs, symbol=loader.resolved_symbol)
    signals = entry_eng.scan_all_models()
    sig_list: List[Dict[str, Any]] = []
    for s in signals[:max_signals]:
        p = s.primary_plan
        sig_list.append({
            "model": s.model_type.value, "direction": s.direction.value,
            "storyline": s.storyline_key, "entry": round(float(p.buffered_entry), 2),
            "sl": round(float(p.stop_loss), 2), "tp": round(float(p.take_profit), 2),
            "lots": float(p.lot_size), "confidence": s.confidence,
            "rationale": s.rationale[:400],
            "distance": round(float(s.distance_to_entry), 2),
        })

    # Account + exposure (guardrail inputs)
    try:
        metrics = RiskManager().get_account_metrics()
        account = {"balance": round(metrics.balance, 2), "equity": round(metrics.equity, 2),
                   "free_margin": round(metrics.free_margin, 2)}
    except Exception as e:
        account = {"error": str(e)}
    try:
        om = OrderManager()
        positions = om.get_open_positions()
        exposure = {"open_positions": len(positions),
                    "symbols": sorted({p.symbol for p in positions})}
    except Exception:
        exposure = {"open_positions": 0, "symbols": []}

    # Spread from latest tick if MT5 available
    spread_info: Dict[str, Any] = {}
    try:
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(loader.resolved_symbol)
        info = mt5.symbol_info(loader.resolved_symbol)
        if tick and info:
            spread_info = {"bid": tick.bid, "ask": tick.ask,
                           "spread_points": getattr(tick, "spread", None),
                           "digits": info.digits}
    except Exception:
        pass

    tog = reg.summary()

    # REAL MT5 indicator feed (collector EA). Honest source flag.
    try:
        from ai_agent.mt5_live_state import read_live_state, export_registry_to_terminals
        from ai_agent import config as cfg
        export_registry_to_terminals(cfg.REGISTRY_PATH)  # push toggles -> terminal(s)
        live = read_live_state()
    except Exception as e:
        live = {"source": "error", "error": str(e), "indicators": []}

    mt5_indicators = live.get("indicators", []) if isinstance(live, dict) else []
    live_enabled = [i["name"] for i in mt5_indicators if i.get("enabled")]
    # Cross-check: registry command vs on-chart reality
    registry_on = set(tog.get("enabled_list", []))

    return {
        "symbol": loader.resolved_symbol,
        "current_price": current_price,
        "storylines": sl_list,
        "msnr_signals": sig_list,
        "account": account,
        "exposure": exposure,
        "spread": spread_info,
        "indicators": {"enabled_count": tog["enabled"], "disabled": tog["disabled_list"]},
        "mt5_live": {
            "source": live.get("source", "not_connected"),
            "age_sec": live.get("_age_sec"),
            "stale": live.get("_stale", True),
            "file": live.get("_file"),
            "hint": live.get("hint", ""),
            "states": [
                {"name": i.get("name"), "enabled": i.get("enabled"),
                 "objects": i.get("objects", 0), "level": i.get("level")}
                for i in mt5_indicators
            ],
        },
        "data_truth": ("live_mt5_objects+python_signals" if live.get("source") == "live_mt5" and not live.get("_stale")
                        else "python_fallback_only: collector EA not connected — indicator objects NOT live"),
        "note": "Propose-only mode. AI proposes setup/entry/SL/TP + indicator toggles. No execution.",
    }
