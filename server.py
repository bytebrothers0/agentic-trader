"""
server.py — MSNR TradingView-Style Interactive Web Engine API

FastAPI backend serving:
  - Live MT5 OHLCV bar data formatted for TradingView Lightweight Charts
  - On-demand MSNR indicator calculations (S/R, OCL, QM, Apex, Freshness)
  - Static interactive TradingView web frontend
"""

from __future__ import annotations

import os
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np

from config.settings import (
    INSTRUMENTS, STRATEGY_ENABLED, INDICATORS_ENABLED, TS_ENABLED,
    SR_ENABLED, QM_ENABLED, OCL_ENABLED, APEX_ENABLED, IDM_ENABLED,
    BOS_ENABLED, BOS_SWING_LENGTH,
    BOS_INTERNAL_LENGTH, BOS_SHOW_INTERNAL, FVG_ENABLED, IFVG_ENABLED,
    FVG_MIN_ATR_MULT, IFVG_MAX_GAP_BARS, IFVG_MIN_OVERLAP_FRAC,
    BOS_SWING_TOL_ATR, OB_ENABLED, OB_SWING_LENGTH, OB_SHOW_LAST,
    OB_USE_BODY,
)
from data.mt5_loader import MT5DataLoader
from indicators.ts_detector import TSDetector
from indicators.idm_detector import IDMDetector
from indicators.bos_detector import BOSDetector
from indicators.fvg_detector import FVGDetector
from indicators.ob_detector import OBDetector
# NOTE: MSNR indicator/strategy imports kept for future re-enable, but NOT
# executed while STRATEGY_ENABLED / INDICATORS_ENABLED are False.
from indicators.candle_analyzer import CandleAnalyzer, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.ocl_detector import OCLDetector
from indicators.qm_detector import QMDetector
from indicators.apex_detector import ApexDetector

from strategy.storyline_engine import StorylineEngine, StorylineEvent, BiasDirection
from strategy.registry import (
    list_modules as list_strategy_modules,
    set_enabled as set_strategy_module,
    enabled_model_values as enabled_strategy_models,
    any_enabled as any_strategy_enabled,
)
from strategy.ftfl_locator import FTFLLocator, FTFLZone
from strategy.stfl_locator import STFLLocator, STFLZone
from strategy.ttfl_locator import TTFLLocator, TTFLRefinement
from strategy.obstacle_scanner import ObstacleScanner, ObstacleTarget
from strategy.entry_engine import EntryEngine, TradeSignal, EntryModelType
from execution.risk_manager import RiskManager, PositionPlan, AccountMetrics
from execution.order_manager import OrderManager, LivePosition

app = FastAPI(title="MSNR TradingView Engine", version="1.0.0")

# AI humanised trader (Grok + Tavily, propose-only). Mounted if available.
try:
    from ai_agent.api import router as ai_router
    app.include_router(ai_router)
except Exception as _ai_err:
    print(f"AI router not mounted: {_ai_err}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global data loader cache
loader_instances = {}


def get_loader(symbol: str) -> MT5DataLoader:
    clean_sym = symbol.upper().strip()
    if clean_sym not in loader_instances:
        loader_instances[clean_sym] = MT5DataLoader(symbol=clean_sym)
    return loader_instances[clean_sym]


@app.get("/api/symbols")
def get_symbols():
    """Return all available MT5 broker symbols."""
    try:
        loader = get_loader("XAUUSD")
        symbols = loader.get_available_symbols()
        # Sort symbols with Gold and major Forex pairs first
        priority_prefixes = ["XAU", "GOLD", "BTC", "EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF"]
        
        def sort_key(s):
            for i, p in enumerate(priority_prefixes):
                if s.upper().startswith(p):
                    return (i, s)
            return (len(priority_prefixes), s)

        sorted_syms = sorted(symbols, key=sort_key)
        return {"symbols": sorted_syms}
    except Exception as e:
        return {"symbols": ["XAUUSDm", "USDJPYm", "EURUSDm", "GBPUSDm", "BTCUSDm"]}


@app.get("/api/candles")
def get_candles(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("D1"),
    bars: int = Query(300, ge=30, le=1500)
):
    """
    Fetch OHLCV candles formatted for TradingView Lightweight Charts:
    [{time: 1787529600, open: ..., high: ..., low: ..., close: ..., volume: ...}]
    """
    try:
        loader = get_loader(symbol)
        df = loader.fetch_timeframe(timeframe.upper(), count=bars)
        
        candles = []
        for idx, row in df.iterrows():
            candles.append({
                "time": int(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"])
            })

        return {
            "symbol": loader.resolved_symbol,
            "timeframe": timeframe.upper(),
            "count": len(candles),
            "candles": candles
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indicators")
def get_indicators(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("D1"),
    bars: int = Query(300, ge=30, le=1500),
    show_sr: bool = Query(True),
    freshness_filter: str = Query("all"),  # 'all', 'fresh_only', 'unfresh_only'
    show_ocl: bool = Query(True),
    show_qm: bool = Query(True),
    show_apex: bool = Query(True),
    show_ts: bool = Query(True),
    show_idm: bool = Query(True),
    show_bos: bool = Query(True),
    show_fvg: bool = Query(True),
    show_ifvg: bool = Query(True),
    show_ob: bool = Query(True),
):
    """
    Compute MSNR indicators on live MT5 data and return structured levels.
    DISABLED: returns empty payload while INDICATORS_ENABLED is False.
    """
    sr_on = (INDICATORS_ENABLED or SR_ENABLED) and show_sr
    qm_on = (INDICATORS_ENABLED or QM_ENABLED) and show_qm
    ocl_on = (INDICATORS_ENABLED or OCL_ENABLED) and show_ocl
    apex_on = (INDICATORS_ENABLED or APEX_ENABLED) and show_apex
    legacy_on = ocl_on or apex_on
    idm_on = IDM_ENABLED and show_idm
    bos_on = BOS_ENABLED and show_bos
    fvg_on = FVG_ENABLED and show_fvg
    ifvg_on = IFVG_ENABLED and show_ifvg
    ob_on = OB_ENABLED and show_ob
    if not (TS_ENABLED and show_ts) and not sr_on and not qm_on and not legacy_on and not idm_on and not bos_on and not fvg_on and not ifvg_on and not ob_on:
        try:
            loader = get_loader(symbol)
            sym = loader.resolved_symbol
        except Exception:
            sym = symbol
        return {
            "symbol": sym,
            "timeframe": timeframe.upper(),
            "current_price": 0.0,
            "total_levels": 0,
            "levels": [],
            "disabled": True,
            "message": "Indicators disabled — awaiting new strategy.",
        }
    try:
        loader = get_loader(symbol)
        df = loader.fetch_timeframe(timeframe.upper(), count=bars)
        
        current_price = float(df["close"].iloc[-1])
        times_unix = df["time"].values

        levels_data = []

        def _end_time(candle_idx: Optional[int]):
            """Map a detector iloc end-index to unix time (None = still active)."""
            if candle_idx is None:
                return None
            i = min(max(int(candle_idx), 0), len(times_unix) - 1)
            return int(times_unix[i])

        # 1. Base S/R, SBR, RBS (enabled via SR_ENABLED for the new strategy)
        if sr_on:
            analyzer = CandleAnalyzer(df)
            base_levels = analyzer.detect_all()
            tracker = FreshnessTracker(df)
            base_levels = tracker.update(base_levels)

            for lvl in base_levels:
                # Apply freshness filter
                if freshness_filter == "fresh_only" and lvl.state != LevelState.FRESH:
                    continue
                if freshness_filter == "unfresh_only" and lvl.state != LevelState.UNFRESH:
                    continue

                t_idx = min(lvl.candle_index, len(times_unix) - 1)
                time_val = int(times_unix[t_idx])

                # Zone life-cycle end: broken -> break bar, touched -> touch bar.
                if lvl.state == LevelState.BROKEN:
                    end_idx, end_kind = lvl.break_candle_index, "broken"
                elif lvl.state == LevelState.UNFRESH:
                    end_idx, end_kind = lvl.first_touch_index, "mitigated"
                else:
                    end_idx, end_kind = None, "active"

                levels_data.append({
                    "category": "sr",
                    "type": lvl.level_type.value.upper(),
                    "price": round(lvl.price, 3),
                    "state": lvl.state.value.upper(),
                    "time": time_val,
                    "candle_index": lvl.candle_index,
                    "end_time": _end_time(end_idx),
                    "end_kind": end_kind,
                    "desc": f"{lvl.level_type.value.upper()} ({lvl.state.value})"
                })

        # 2. OCL (HTF only; enabled via OCL_ENABLED)
        if ocl_on and timeframe.upper() in {"MN", "MN1", "W1", "D1"}:
            ocl_det = OCLDetector(df, timeframe=timeframe.upper())
            ocls = ocl_det.detect_all()
            for ocl in ocls:
                t_idx = min(ocl.candle_index_1, len(times_unix) - 1)
                levels_data.append({
                    "category": "ocl",
                    "type": ocl.ocl_type.value.upper(),
                    "price": round(ocl.price, 3),
                    "state": ocl.state.value.upper(),
                    "time": int(times_unix[t_idx]),
                    "box_high": round(ocl.box_high, 3),
                    "box_low": round(ocl.box_low, 3),
                    "end_time": _end_time(ocl.end_candle_index),
                    "end_kind": ocl.end_kind,
                    "desc": f"OCL: {ocl.ocl_type.value.upper()}"
                })

        # 3. Quasimodo (enabled via QM_ENABLED for the new strategy)
        if qm_on:
            analyzer = CandleAnalyzer(df)
            base_levels = analyzer.detect_all()
            qm_det = QMDetector(df, base_levels)
            qms = qm_det.detect_all()
            for qm in qms:
                # Ray starts at formation (origin candle = left shoulder),
                # not at the later break candle.
                t_idx = min(qm.origin_candle_index, len(times_unix) - 1)
                levels_data.append({
                    "category": "qm",
                    "type": f"{qm.qm_type.value.upper()} ({qm.direction.value.upper()})",
                    "price": round(qm.price, 3),
                    "state": qm.state.value.upper(),
                    "time": int(times_unix[t_idx]),
                    "box_high": round(qm.box_high, 3),
                    "box_low": round(qm.box_low, 3),
                    "end_time": _end_time(qm.end_candle_index),
                    "end_kind": qm.end_kind,
                    "desc": f"QM: {qm.qm_type.value.upper()} {qm.direction.value.upper()}"
                })

        # 4. Apex & IAB (HTF only; enabled via APEX_ENABLED)
        if apex_on and timeframe.upper() in {"MN", "MN1", "W1", "D1"}:
            apex_det = ApexDetector(df, timeframe=timeframe.upper())
            apexes = apex_det.detect_all()
            for apex in apexes:
                t_idx = min(apex.candle_index, len(times_unix) - 1)
                levels_data.append({
                    "category": "apex",
                    "type": str(apex.apex_type.value.upper()),
                    "price": float(round(apex.price, 3)),
                    "state": apex.state.value.upper(),
                    "is_external": bool(apex.is_external),
                    "time": int(times_unix[t_idx]),
                    "end_time": _end_time(apex.end_candle_index),
                    "end_kind": apex.end_kind,
                    "desc": f"{'EXTERNAL' if bool(apex.is_external) else 'INTERNAL'} {apex.apex_type.value.upper()}"
                })

        # 5. Turtle Soup (TS) — new custom logic, works on every timeframe
        if TS_ENABLED and show_ts:
            ts_det = TSDetector(df)
            for ts in ts_det.detect_all():
                t_idx = min(ts.candle_index, len(times_unix) - 1)
                s_idx = min(ts.sweep_candle_index, len(times_unix) - 1)
                levels_data.append({
                    "category": "ts",
                    "type": f"{ts.ts_type.value.upper()} ({ts.direction.value.upper()})",
                    "price": round(ts.price, 3),
                    "state": "FRESH",
                    "time": int(times_unix[t_idx]),
                    "start_time": int(times_unix[s_idx]),
                    "end_time": None,
                    "end_kind": "active",
                    "sweep_amount": round(ts.sweep_amount, 3),
                    "desc": f"TS: {ts.ts_type.value.upper()} {ts.direction.value.upper()}"
                })

        # 6. IDM (inducement/liquidity). Swept IDMs draw formation -> sweep
        # (full length); active ones are open-ended (fixed short ray).
        idm_levels = IDMDetector(df).detect_all() if idm_on else []
        if idm_on:
            for im in idm_levels:
                t_idx = min(im.formation_index, len(times_unix) - 1)
                if im.swept and im.sweep_index is not None:
                    end_idx, end_kind = min(im.sweep_index, len(times_unix) - 1), "swept"
                else:
                    end_idx, end_kind = None, "active"
                levels_data.append({
                    "category": "idm",
                    "type": f"{im.idm_type.value.upper()} ({im.direction.value.upper()})",
                    "price": round(im.price, 3),
                    "state": "SWEPT" if im.swept else "FRESH",
                    "time": int(times_unix[t_idx]),
                    "end_time": _end_time(end_idx),
                    "end_kind": end_kind,
                    "desc": f"IDM: {im.idm_type.value.upper()} {im.direction.value.upper()}"
                })

        # 7. BOS/CHoCH (Mxwll-style: swing + close through, one-shot),
        # external + internal (I-BOS) layers.
        # Ray runs swing bar -> break bar, as the script draws it.
        if bos_on:
            bos_det = BOSDetector(
                df,
                swing_length=BOS_SWING_LENGTH,
                internal_length=BOS_INTERNAL_LENGTH,
                show_internal=BOS_SHOW_INTERNAL,
                swing_tol_atr=BOS_SWING_TOL_ATR,
            )
            last_idx = len(times_unix) - 1
            for bo in bos_det.detect_all():
                t_idx = min(bo.extreme_index, last_idx)
                b_idx = min(bo.break_index, last_idx)
                kind = bo.kind
                levels_data.append({
                    "category": "bos",
                    "type": f"{kind} ({bo.direction.value.upper()})",
                    "price": round(bo.price, 3),
                    "state": "FRESH",
                    "time": int(times_unix[t_idx]),
                    "end_time": int(times_unix[b_idx]),
                    "end_kind": "active",
                    "desc": f"{kind}: {bo.direction.value.upper()}"
                })

        # 8. FVG zones (LuxAlgo port). Mitigated zones draw formation ->
        # mitigation; active ones are open-ended (fixed short span).
        # Computed once and shared with the IFVG block below. First-parent
        # rays extend to the IFVG birth so the lineage stays visible.
        fvg_det = FVGDetector(df, min_atr_mult=FVG_MIN_ATR_MULT,
                              max_gap_bars=IFVG_MAX_GAP_BARS,
                              min_overlap_frac=IFVG_MIN_OVERLAP_FRAC)
        fvg_levels = fvg_det.detect_all() if (fvg_on or ifvg_on) else []
        ifvg_levels = fvg_det.detect_ifvg(fvg_levels) if ifvg_on else []
        birth_by_first = {}
        for iv in ifvg_levels:
            f = iv.first_formation_index
            birth_by_first[f] = max(birth_by_first.get(f, 0), iv.formation_index)
        if fvg_on:
            for fv in fvg_levels:
                t_idx = min(fv.formation_index, len(times_unix) - 1)
                if fv.mitigated and fv.mitigation_index is not None:
                    end_idx, end_kind = min(fv.mitigation_index, len(times_unix) - 1), "mitigated"
                else:
                    end_idx, end_kind = None, "active"
                ext = birth_by_first.get(fv.formation_index)
                if ext is not None and (end_idx is None or ext > end_idx):
                    end_idx = min(ext, len(times_unix) - 1)
                levels_data.append({
                    "category": "fvg",
                    "type": f"FVG ({fv.direction.value.upper()})",
                    "price": round(fv.mid, 3),
                    "state": "MITIGATED" if fv.mitigated else "FRESH",
                    "time": int(times_unix[t_idx]),
                    "end_time": _end_time(end_idx),
                    "end_kind": end_kind,
                    "box_top": round(fv.top, 3),
                    "box_bottom": round(fv.bottom, 3),
                    "desc": f"FVG: {fv.direction.value.upper()}"
                })

        # 9. IFVG (genuine overlap of two opposite FVGs). Fixed short span.
        if ifvg_on:
            for iv in ifvg_levels:
                t_idx = min(iv.formation_index, len(times_unix) - 1)
                levels_data.append({
                    "category": "ifvg",
                    "type": f"IFVG ({iv.direction.value.upper()})",
                    "price": round(iv.mid, 3),
                    "state": "FRESH",
                    "time": int(times_unix[t_idx]),
                    "end_time": None,
                    "end_kind": "active",
                    "box_top": round(iv.top, 3),
                    "box_bottom": round(iv.bottom, 3),
                    "desc": f"IFVG: {iv.direction.value.upper()}"
                })

        # 10. OB + Breaker Blocks (LuxAlgo port). Non-breakers extend to
        # the last bar (as the script draws them); breakers run origin ->
        # flip, the flip bar carried separately for the two-tone drawing.
        if ob_on:
            ob_det = OBDetector(df, swing_length=OB_SWING_LENGTH,
                                use_body=OB_USE_BODY, show_last=OB_SHOW_LAST)
            last_idx = len(times_unix) - 1
            for ob in ob_det.detect_all():
                t_idx = min(ob.formation_index, last_idx)
                payload = {
                    "category": "ob",
                    "type": f"{ob.kind} ({ob.direction.value.upper()})",
                    "price": round(ob.mid, 3),
                    "state": ob.status,
                    "time": int(times_unix[t_idx]),
                    "end_time": int(times_unix[last_idx]),
                    "end_kind": "active",
                    "box_top": round(ob.top, 3),
                    "box_bottom": round(ob.bottom, 3),
                    "desc": f"{ob.kind}: {ob.direction.value.upper()}"
                }
                if ob.is_breaker and ob.break_index is not None:
                    payload["break_time"] = int(times_unix[min(ob.break_index, last_idx)])
                levels_data.append(payload)

        # Sort levels by price descending
        levels_data.sort(key=lambda x: x["price"], reverse=True)

        return {
            "symbol": loader.resolved_symbol,
            "timeframe": timeframe.upper(),
            "current_price": current_price,
            "total_levels": len(levels_data),
            "levels": levels_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/strategy")
def get_strategy_analysis(symbol: str = Query("XAUUSD")):
    """
    Computes complete Phase 2 Strategy Core & Multi-Storyline Entry analysis:
    DISABLED unless entry modules are enabled in Bot Settings.
    Only signals from enabled modules are returned.
    """
    msnr_models = enabled_strategy_models("msnr")
    ts_models = enabled_strategy_models("ts_m15")
    if not msnr_models and not ts_models:
        try:
            sym = get_loader(symbol).resolved_symbol
        except Exception:
            sym = symbol
        return {
            "symbol": sym,
            "storylines": {},
            "entries": [],
            "primary_entry": None,
            "total_entries": 0,
            "ftfl": None,
            "stfl": None,
            "ttfl": None,
            "obstacles": [],
            "analysis_schedule": {},
            "analysis_due": [],
            "disabled": True,
            "message": "Strategy disabled — enable entry modules in Bot Settings.",
        }
    try:
        from strategy.ts_entry import TSEntryEngine

        loader = get_loader(symbol)
        signals = []
        sl_summary = {}

        # 1-2. MSNR storyline engine (only if its modules are on; this is
        # the heavy multi-timeframe fetch).
        if msnr_models:
            dfs = loader.fetch_all_timeframes()
            sl_engine = StorylineEngine(dfs)
            storylines = sl_engine.analyze_all()
            entry_eng = EntryEngine(dfs, symbol=loader.resolved_symbol)
            signals = entry_eng.scan_all_models()

            # Format storyline summary
            for k, v in storylines.items():
                sl_summary[k] = {
                    "htf": v.htf,
                    "ltf": v.ltf,
                    "bias": v.bias.value,
                    "rejection_price": float(round(v.rejection_price, 3)),
                    "rejection_desc": v.rejection_level_desc,
                    "rejection_time": str(v.rejection_time),
                    "breakout_time": str(v.breakout_time)
                }

        # 3. MNSR + TS engine (M15 only, light single-timeframe fetch).
        if ts_models:
            df_m15 = loader.fetch_timeframe("M15", count=500)
            ts_eng = TSEntryEngine(df_m15, symbol=loader.resolved_symbol)
            ts_signals = [s for s in ts_eng.scan()
                          if s.model_type.value in ts_models]
            if signals:
                max_rank = max(s.priority_rank for s in signals)
                for s in ts_signals:
                    s.priority_rank += max_rank
            signals = signals + ts_signals

        # Build list of all active entry zones from signals
        entries_list = []
        for s in signals:
            p = s.primary_plan
            entry_item = {
                "model_type": s.model_type.value,
                "direction": s.direction.value,
                "storyline_key": s.storyline_key,
                "storyline_desc": s.storyline_desc,
                "storyline_rejection": float(round(s.storyline_rejection, 3)),
                "ftfl_tf": s.ftfl_tf,
                "stfl_tf": s.stfl_tf,
                "ttfl_tf": s.ttfl_tf,
                "entry_price": float(round(p.buffered_entry, 3)),
                "raw_entry": float(round(p.raw_entry, 3)),
                "stop_loss": float(round(p.stop_loss, 3)),
                "sl_points": float(p.sl_points),
                "take_profit": float(round(p.take_profit, 3)),
                "obstacle_tp": float(round(p.obstacle_tp, 3)) if p.obstacle_tp else None,
                "lot_size": float(p.lot_size),
                "risk_usd": float(round(p.risk_amount_usd, 2)),
                "confidence": s.confidence,
                "rationale": s.rationale,
                "formation_time": int(s.formation_time),
                "ftfl_box_top": float(round(s.ftfl_box_top, 3)),
                "ftfl_box_bottom": float(round(s.ftfl_box_bottom, 3)),
                "stfl_box_top": float(round(s.stfl_box_top, 3)),
                "stfl_box_bottom": float(round(s.stfl_box_bottom, 3)),
                "distance_to_entry": float(round(s.distance_to_entry, 2)),
                "priority_rank": s.priority_rank
            }
            if s.secondary_plan:
                p2 = s.secondary_plan
                entry_item["secondary_entry"] = {
                    "entry_price": float(round(p2.buffered_entry, 3)),
                    "stop_loss": float(round(p2.stop_loss, 3)),
                    "lot_size": float(p2.lot_size),
                    "risk_usd": float(round(p2.risk_amount_usd, 2)),
                    "model_name": p2.model_name
                }
            entries_list.append(entry_item)

        # Only MSNR modules enabled in Bot Settings pass through
        # (TS signals were pre-filtered at scan time).
        entries_list = [e for e in entries_list if e["model_type"] in msnr_models or e["model_type"] in ts_models]

        # Primary entry is the closest / highest priority entry
        primary_entry = entries_list[0] if entries_list else None

        # Backwards-compatible fields for single-entry display
        ftfl_data = None
        stfl_data = None
        ttfl_data = None
        obstacles_data = []

        if primary_entry:
            ttfl_data = {
                "timeframe": primary_entry["ttfl_tf"],
                "direction": primary_entry["direction"],
                "entry_price": primary_entry["entry_price"],
                "sl_reference": primary_entry["stop_loss"],
                "entry_type": primary_entry["model_type"],
                "desc": primary_entry["rationale"]
            }
            ftfl_box_top = primary_entry["ftfl_box_top"] or (primary_entry["raw_entry"] + 2.0)
            ftfl_box_bottom = primary_entry["ftfl_box_bottom"] or (primary_entry["raw_entry"] - 2.0)
            ftfl_data = {
                "timeframe": primary_entry["ftfl_tf"],
                "direction": primary_entry["direction"],
                "price": primary_entry["raw_entry"],
                "box_top": ftfl_box_top,
                "box_bottom": ftfl_box_bottom,
                "equilibrium": round((ftfl_box_top + ftfl_box_bottom) / 2.0, 3),
                "desc": primary_entry["storyline_desc"],
                "priority": primary_entry["confidence"]
            }
            stfl_box_top = primary_entry["stfl_box_top"] or (primary_entry["raw_entry"] + 1.0)
            stfl_box_bottom = primary_entry["stfl_box_bottom"] or (primary_entry["raw_entry"] - 1.0)
            stfl_data = {
                "timeframe": primary_entry["stfl_tf"],
                "direction": primary_entry["direction"],
                "box_top": stfl_box_top,
                "box_bottom": stfl_box_bottom,
                "equilibrium": round((stfl_box_top + stfl_box_bottom) / 2.0, 3),
            }
            if primary_entry["obstacle_tp"]:
                obstacles_data.append({
                    "price": primary_entry["obstacle_tp"],
                    "type": "OBSTACLE",
                    "desc": "Intermediate Obstacle",
                    "is_final_tp": False,
                    "action": "TAKE_80_PERCENT_PARTIAL"
                })
            obstacles_data.append({
                "price": primary_entry["take_profit"],
                "type": "DRAW_ON_LIQUIDITY",
                "desc": "Draw on Liquidity Final TP",
                "is_final_tp": True,
                "action": "RUNNER_TARGET"
            })

        from config.settings import ANALYSIS_SCHEDULE, get_due_analysis_scopes
        return {
            "symbol": loader.resolved_symbol,
            "storylines": sl_summary,
            "entries": entries_list,
            "primary_entry": primary_entry,
            "total_entries": len(entries_list),
            "ftfl": ftfl_data,
            "stfl": stfl_data,
            "ttfl": ttfl_data,
            "obstacles": obstacles_data,
            # Video 10 routine: which scopes (monthly/weekly/daily) are due now.
            "analysis_schedule": ANALYSIS_SCHEDULE,
            "analysis_due": get_due_analysis_scopes(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/signals")
def get_trade_signals(symbol: str = Query("XAUUSD")):
    """
    Entry signals from all enabled modules (MSNR storylines + TS M15).
    DISABLED unless entry modules are enabled in Bot Settings.
    """
    msnr_models = enabled_strategy_models("msnr")
    ts_models = enabled_strategy_models("ts_m15")
    if not msnr_models and not ts_models:
        try:
            sym = get_loader(symbol).resolved_symbol
        except Exception:
            sym = symbol
        return {
            "symbol": sym,
            "signals": [],
            "disabled": True,
            "message": "Strategy disabled — enable entry modules in Bot Settings.",
        }
    try:
        from strategy.ts_entry import TSEntryEngine

        loader = get_loader(symbol)
        signals = []
        if msnr_models:
            dfs = loader.fetch_all_timeframes()
            entry_eng = EntryEngine(dfs, symbol=loader.resolved_symbol)
            signals = entry_eng.scan_all_models()
        if ts_models:
            df_m15 = loader.fetch_timeframe("M15", count=500)
            ts_eng = TSEntryEngine(df_m15, symbol=loader.resolved_symbol)
            ts_signals = [s for s in ts_eng.scan()
                          if s.model_type.value in ts_models]
            if signals:
                max_rank = max(s.priority_rank for s in signals)
                for s in ts_signals:
                    s.priority_rank += max_rank
            signals = signals + ts_signals

        result = []
        for s in signals:
            p = s.primary_plan
            sig_dict = {
                "model_type": s.model_type.value,
                "symbol": s.symbol,
                "direction": s.direction.value,
                "storyline_key": s.storyline_key,
                "storyline": s.storyline_desc,
                "ftfl_tf": s.ftfl_tf,
                "stfl_tf": s.stfl_tf,
                "ttfl_tf": s.ttfl_tf,
                "entry_price": float(round(p.buffered_entry, 3)),
                "raw_entry": float(round(p.raw_entry, 3)),
                "stop_loss": float(round(p.stop_loss, 3)),
                "sl_points": float(p.sl_points),
                "take_profit": float(round(p.take_profit, 3)),
                "obstacle_tp": float(round(p.obstacle_tp, 3)) if p.obstacle_tp else None,
                "lot_size": float(p.lot_size),
                "risk_usd": float(round(p.risk_amount_usd, 2)),
                "confidence": s.confidence,
                "rationale": s.rationale,
                "formation_time": int(s.formation_time),
                "ftfl_box_top": float(round(s.ftfl_box_top, 3)),
                "ftfl_box_bottom": float(round(s.ftfl_box_bottom, 3)),
                "stfl_box_top": float(round(s.stfl_box_top, 3)),
                "stfl_box_bottom": float(round(s.stfl_box_bottom, 3)),
                "distance_to_entry": float(round(s.distance_to_entry, 2)),
                "priority_rank": s.priority_rank
            }
            if s.secondary_plan:
                p2 = s.secondary_plan
                sig_dict["secondary_entry"] = {
                    "entry_price": float(round(p2.buffered_entry, 3)),
                    "stop_loss": float(round(p2.stop_loss, 3)),
                    "lot_size": float(p2.lot_size),
                    "risk_usd": float(round(p2.risk_amount_usd, 2)),
                    "model_name": p2.model_name
                }
            result.append(sig_dict)

        # Only modules enabled in Bot Settings pass through
        # (TS signals were pre-filtered at scan time).
        result = [r for r in result if r["model_type"] in msnr_models or r["model_type"] in ts_models]

        return {"symbol": loader.resolved_symbol, "signals": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/settings/modules")
def get_settings_modules():
    """List all strategy entry modules with live enabled state."""
    return {"modules": list_strategy_modules()}


@app.post("/api/settings/modules/{module_id}")
def set_settings_module(module_id: str, enabled: bool = Query(...)):
    """Enable or disable a strategy entry module (persists across restarts)."""
    if not set_strategy_module(module_id, enabled):
        raise HTTPException(status_code=404, detail=f"Unknown module: {module_id}")
    return {"id": module_id, "enabled": bool(enabled)}


@app.get("/api/account")
def get_account_status():
    """Fetch live MT5 account metrics."""
    try:
        risk_mgr = RiskManager()
        metrics = risk_mgr.get_account_metrics()
        return {
            "balance": round(metrics.balance, 2),
            "equity": round(metrics.equity, 2),
            "margin": round(metrics.margin, 2),
            "free_margin": round(metrics.free_margin, 2),
            "currency": metrics.currency,
            "leverage": metrics.leverage
        }
    except Exception as e:
        return {"balance": 10000.0, "equity": 10000.0, "margin": 0.0, "free_margin": 10000.0, "currency": "USD", "leverage": 100}


@app.get("/api/positions")
def get_live_positions():
    """Fetch active open positions and pending orders from MT5."""
    try:
        order_mgr = OrderManager()
        positions = order_mgr.get_open_positions()
        orders = order_mgr.get_pending_orders()

        return {
            "positions": [
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": p.order_type,
                    "lots": p.volume,
                    "open_price": p.open_price,
                    "current_price": p.current_price,
                    "sl": p.sl,
                    "tp": p.tp,
                    "profit": round(p.profit, 2),
                    "time": p.time_open
                }
                for p in positions
            ],
            "pending_orders": [
                {
                    "ticket": o.ticket,
                    "symbol": o.symbol,
                    "type": o.order_type,
                    "lots": o.volume,
                    "open_price": o.open_price,
                    "sl": o.sl,
                    "tp": o.tp,
                    "time": o.time_open
                }
                for o in orders
            ]
        }
    except Exception as e:
        return {"positions": [], "pending_orders": []}


@app.post("/api/orders/place")
def place_order(
    symbol: str = Query("XAUUSDm"),
    direction: str = Query("BULLISH"),
    entry: float = Query(...),
    sl: float = Query(...),
    tp: float = Query(...),
    lots: float = Query(0.01),
    obstacle: Optional[float] = Query(None, description="Intermediate 80% partial level (Video 11)"),
):
    """Place a live limit order into MT5 terminal (tracks obstacle for 80%+BE management)."""
    try:
        order_mgr = OrderManager()
        is_buy = direction.upper() == "BULLISH"
        plan = PositionPlan(
            symbol=symbol,
            direction=BiasDirection.BULLISH if is_buy else BiasDirection.BEARISH,
            raw_entry=entry,
            buffered_entry=entry,
            stop_loss=sl,
            sl_points=abs(entry - sl) / 0.01,
            take_profit=tp,
            obstacle_tp=obstacle,
            risk_amount_usd=0.0,
            lot_size=lots
        )
        res = order_mgr.place_limit_order(plan)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/orders/close")
def close_order(ticket: int = Query(...)):
    """Close an active position."""
    try:
        order_mgr = OrderManager()
        success = order_mgr.close_position(ticket)
        return {"success": success, "ticket": ticket}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/orders/cancel")
def cancel_order(ticket: int = Query(...)):
    """Cancel a pending limit order."""
    try:
        order_mgr = OrderManager()
        success = order_mgr.cancel_order(ticket)
        return {"success": success, "ticket": ticket}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/orders/partial-close")
def partial_close_order(
    ticket: int = Query(...),
    fraction: float = Query(0.8, ge=0.05, le=1.0),
):
    """Close a fraction (default 80%) of a position, leaving a runner (Video 11)."""
    try:
        order_mgr = OrderManager()
        return order_mgr.partial_close(ticket, fraction)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/orders/breakeven")
def breakeven_order(ticket: int = Query(...)):
    """Move a position's SL to breakeven after the obstacle partial (Video 11)."""
    try:
        order_mgr = OrderManager()
        success = order_mgr.move_sl_to_breakeven(ticket)
        return {"success": success, "ticket": ticket}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/orders/manage-obstacles")
def manage_obstacles():
    """
    Run the Video 11 obstacle sequence over all tracked positions:
    positions at their obstacle get 80% partial + SL to breakeven.
    """
    try:
        order_mgr = OrderManager()
        return {"results": order_mgr.manage_position_obstacles()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtest/trades")
def get_backtest_trades():
    """Serve the detection-journal CSV (newest version present) for the viewer."""
    import csv as _csv
    import glob as _glob
    paths = sorted(_glob.glob(os.path.join(os.path.dirname(__file__), "backtest",
                                           "journal_Sep28-Oct02*.csv")))
    if not paths:
        raise HTTPException(status_code=404, detail="Journal CSV not found.")
    journal = paths[-1]
    if not os.path.exists(journal):
        raise HTTPException(status_code=404, detail="Journal CSV not found.")
    trades = []
    with open(journal, "r", encoding="utf-8") as fh:
        for row in _csv.DictReader(fh):
            try:
                trades.append({
                    "signal_date": row.get("signal_date", ""),
                    "fill_date": row.get("fill_date", ""),
                    "exit_date": row.get("exit_date", ""),
                    "direction": (row.get("direction", "") or "").upper(),
                    "entry": float(row.get("entry") or 0),
                    "sl": float(row.get("sl") or 0),
                    "tp": float(row.get("tp") or 0),
                    "outcome": row.get("outcome", ""),
                    "R": float(row.get("R") or 0),
                    "confidence": row.get("confidence", ""),
                    "ts_side": row.get("ts_side", ""),
                    "ts_price": row.get("ts_price", ""),
                    "break_kind": row.get("break_kind", ""),
                    "qm_entry_level": row.get("qm_entry_level", ""),
                    "liq_kind": row.get("liq_kind", ""),
                    "liq_price": row.get("liq_price", ""),
                    "confluence": row.get("confluence", ""),
                    "fallback": row.get("fallback", ""),
                    "chain": row.get("chain", ""),
                })
            except (ValueError, TypeError):
                continue
    wins = sum(1 for t in trades if t["outcome"] == "TP")
    losses = sum(1 for t in trades if t["outcome"] == "SL")
    expired = sum(1 for t in trades if t["outcome"] == "expired")
    return {"trades": trades,
            "stats": {"total": len(trades), "tp": wins, "losses": losses,
                      "expired": expired,
                      "total_R": round(sum(t["R"] for t in trades), 2)}}


@app.get("/backtest")
def read_backtest():
    backtest_path = os.path.join(os.path.dirname(__file__), "web", "backtest.html")
    if os.path.exists(backtest_path):
        return FileResponse(backtest_path)
    raise HTTPException(status_code=404, detail="Backtest viewer not found.")


# Mount web directory
static_dir = os.path.join(os.path.dirname(__file__), "web")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def read_root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "MSNR Engine Running. Please create web/index.html"}
