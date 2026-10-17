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
    INSTRUMENTS, INDICATORS_ENABLED, TS_ENABLED,
    SR_ENABLED, QM_ENABLED, OCL_ENABLED, APEX_ENABLED, IDM_ENABLED,
    BOS_ENABLED, BOS_SWING_LENGTH,
    BOS_INTERNAL_LENGTH, BOS_SHOW_INTERNAL, FVG_ENABLED, IFVG_ENABLED,
    FVG_MIN_ATR_MULT, IFVG_MAX_GAP_BARS, IFVG_MIN_OVERLAP_FRAC,
    BOS_SWING_TOL_ATR, OB_ENABLED, OB_SWING_LENGTH, OB_SHOW_LAST,
    OB_USE_BODY, OB_REQUIRE_FVG, OB_REQUIRE_SWEEP, OB_DISPLACEMENT_MULT,
    OB_MARK_DECISIONAL,
    TS_MIN_WICK_BODY_FRAC, TS_MIN_WICK_RANGE_FRAC,
    TL_ENABLED, TL_PIVOT_LENGTH, TL_PIVOT_WINDOWS, TL_SLOPE_MULT, TL_MAX_LINES,
    TL_RETEST_BARS, TL_BODY_PIVOTS, TL_REQUIRE_ENGULFING,
    TL_SKIP_GAP_ANCHORS, TL_GAP_ATR_MULT, TL_TOL_ATR,
    TL_CHANNEL_PARALLEL_ATR, TL_SWEEP_ATR,
    IDM_SWING_LENGTH, IDM_SHOW_INTERNAL, IDM_MAX_PER_SIDE, IDM_ATR_PERIOD,
    LIQ_ENABLED, LIQ_SWING_LENGTH, LIQ_EQ_TOL_ATR, LIQ_EQ_MAX_BARS,
    LIQ_MIN_TOUCHES, LIQ_MAX_PER_SIDE,
)
from data.mt5_loader import MT5DataLoader
from indicators.ts_detector import TSDetector
from indicators.idm_detector import IDMDetector
from indicators.liquidity_detector import LiquidityDetector
from indicators.bos_detector import BOSDetector
from indicators.fvg_detector import FVGDetector
from indicators.ob_detector import OBDetector
from indicators.trendline_detector import TLDetector
from indicators.candle_analyzer import CandleAnalyzer, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.ocl_detector import OCLDetector
from indicators.qm_detector import QMDetector
from indicators.apex_detector import ApexDetector
from execution.risk_manager import RiskManager, PositionPlan, AccountMetrics, BiasDirection
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
    show_tl: bool = Query(True),
    show_liq: bool = Query(True),
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
    tl_on = TL_ENABLED and show_tl
    liq_on = LIQ_ENABLED and show_liq
    if not (TS_ENABLED and show_ts) and not sr_on and not qm_on and not legacy_on and not idm_on and not bos_on and not fvg_on and not ifvg_on and not ob_on and not tl_on and not liq_on:
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
            ts_det = TSDetector(
                df,
                min_wick_body_frac=TS_MIN_WICK_BODY_FRAC,
                min_wick_range_frac=TS_MIN_WICK_RANGE_FRAC,
            )
            ts_levels = list(ts_det.detect_all())
            for ts in ts_levels:
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

        # 6. IDM (inducement): the internal pullback inside a BOS impulse leg,
        # anchored on structure (not every bar, as before). One IDM per break,
        # deduped and capped per direction. Swept ones draw formation -> sweep;
        # active ones a short ray.
        idm_levels = IDMDetector(
            df,
            swing_length=IDM_SWING_LENGTH,
            bos_swing_length=BOS_SWING_LENGTH,
            bos_internal_length=BOS_INTERNAL_LENGTH,
            show_internal=IDM_SHOW_INTERNAL,
            swing_tol_atr=BOS_SWING_TOL_ATR,
            max_per_side=IDM_MAX_PER_SIDE,
            atr_period=IDM_ATR_PERIOD,
        ).detect_all() if idm_on else []
        if idm_on:
            for im in idm_levels:
                t_idx = min(im.formation_index, len(times_unix) - 1)
                if im.swept and im.sweep_index is not None:
                    end_idx, end_kind = min(im.sweep_index, len(times_unix) - 1), "swept"
                elif im.broken and im.broken_index is not None:
                    end_idx, end_kind = min(im.broken_index, len(times_unix) - 1), "broken"
                else:
                    end_idx, end_kind = None, "active"
                state = ("SWEPT" if im.swept
                         else "BROKEN" if im.broken else "FRESH")
                levels_data.append({
                    "category": "idm",
                    "type": f"{im.idm_type.value.upper()} ({im.direction.value.upper()})",
                    "price": round(im.price, 3),
                    "state": state,
                    "time": int(times_unix[t_idx]),
                    "end_time": _end_time(end_idx),
                    "end_kind": end_kind,
                    "desc": (
                        f"IDM: {im.idm_type.value.upper()} {im.direction.value.upper()}"
                        f" after {im.bos_kind or 'BOS'}"
                    )
                })

        # 6b. Liquidity pools: equal highs (buy-side) / equal lows (sell-side).
        # A pool spans its first -> last touch; taken pools draw to the sweep.
        liq_levels = LiquidityDetector(
            df,
            swing_length=LIQ_SWING_LENGTH,
            eq_tol_atr=LIQ_EQ_TOL_ATR,
            eq_max_bars=LIQ_EQ_MAX_BARS,
            min_touches=LIQ_MIN_TOUCHES,
            max_per_side=LIQ_MAX_PER_SIDE,
        ).detect_all() if liq_on else []
        if liq_on:
            last_i = len(times_unix) - 1
            for ql in liq_levels:
                start_i = min(ql.first_index, last_i)
                if ql.taken and ql.taken_index is not None:
                    end_i, end_kind = min(ql.taken_index, last_i), "taken"
                else:
                    end_i, end_kind = min(ql.last_index, last_i), "active"
                side = ql.side.value.upper()
                levels_data.append({
                    "category": "liquidity",
                    "type": f"{ql.liq_type.value.upper()} ({side})",
                    "price": round(ql.price, 3),
                    "state": "TAKEN" if ql.taken else "FRESH",
                    "time": int(times_unix[start_i]),
                    "end_time": _end_time(end_i),
                    "end_kind": end_kind,
                    "desc": (
                        f"Liquidity: {ql.liq_type.value.upper()} "
                        f"x{ql.pool_size} {side}"
                    )
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

        # 8. FVG zones (LuxAlgo port). Only UNMITIGATED (fresh) zones are
        # shown; mitigated zones are dropped. Computed once and shared with
        # the IFVG block below.
        fvg_det = FVGDetector(df, min_atr_mult=FVG_MIN_ATR_MULT,
                              max_gap_bars=IFVG_MAX_GAP_BARS,
                              min_overlap_frac=IFVG_MIN_OVERLAP_FRAC)
        fvg_levels = fvg_det.detect_all() if (fvg_on or ifvg_on) else []
        ifvg_levels = fvg_det.detect_ifvg(fvg_levels) if ifvg_on else []
        if fvg_on:
            for fv in fvg_levels:
                if not fv.fresh:
                    continue  # mitigated zones are hidden
                t_idx = min(fv.formation_index, len(times_unix) - 1)
                levels_data.append({
                    "category": "fvg",
                    "type": f"FVG ({fv.direction.value.upper()})",
                    "price": round(fv.mid, 3),
                    "state": "FRESH",
                    "time": int(times_unix[t_idx]),
                    "end_time": None,
                    "end_kind": "active",
                    "box_top": round(fv.top, 3),
                    "box_bottom": round(fv.bottom, 3),
                    "desc": f"FVG: {fv.direction.value.upper()}"
                })

        # 9. IFVG (genuine overlap of two opposite FVGs). Only UNMITIGATED
        # (fresh) inversions are shown.
        if ifvg_on:
            for iv in ifvg_levels:
                if not iv.fresh:
                    continue  # mitigated inversions are hidden
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
                                use_body=OB_USE_BODY, show_last=OB_SHOW_LAST,
                                require_fvg=OB_REQUIRE_FVG,
                                require_sweep=OB_REQUIRE_SWEEP,
                                displacement_mult=OB_DISPLACEMENT_MULT,
                                mark_decisional=OB_MARK_DECISIONAL)
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
                    "desc": (f"{ob.kind}: {ob.direction.value.upper()}"
                             + (f" [{ob.ob_type}]" if ob.ob_type else ""))
                }
                if ob.is_breaker and ob.break_index is not None:
                    payload["break_time"] = int(times_unix[min(ob.break_index, last_idx)])
                levels_data.append(payload)

        # 11. Auto trendlines (point-to-point close apexes): support /
        # resistance lines, channel pairs, break-retest role flips and
        # trendline-liquidity sweeps.
        if tl_on:
            tl_det = TLDetector(df, pivot_length=TL_PIVOT_LENGTH,
                                pivot_windows=TL_PIVOT_WINDOWS,
                                slope_mult=TL_SLOPE_MULT,
                                max_lines=TL_MAX_LINES,
                                retest_bars=TL_RETEST_BARS,
                                body_pivots=TL_BODY_PIVOTS,
                                require_engulfing=TL_REQUIRE_ENGULFING,
                                skip_gap_anchors=TL_SKIP_GAP_ANCHORS,
                                gap_atr_mult=TL_GAP_ATR_MULT,
                                tol_atr=TL_TOL_ATR,
                                channel_parallel_atr=TL_CHANNEL_PARALLEL_ATR,
                                sweep_atr=TL_SWEEP_ATR)
            tl_lines = list(tl_det.detect_all())
            last_idx = len(times_unix) - 1
            for tl in tl_lines:
                s_idx = min(tl.pivot_index, last_idx)
                e_idx = min(tl.end_index, last_idx)
                role = tl.role.upper()
                typ = "TL_BRT" if tl.flipped else f"TL_{role}"
                payload = {
                    "category": "trendline",
                    "type": typ,
                    "role": tl.role,
                    "flipped": bool(tl.flipped),
                    "retest_role": tl.retest_role,
                    "channel": tl.channel_id,
                    "liquidity": bool(tl.swept),
                    "price": round(tl.pivot_price, 3),
                    "price_end": round(tl.value_at(e_idx), 3),
                    "state": ("FRESH" if tl.state.value == "active"
                              else "BROKEN"),
                    "time": int(times_unix[s_idx]),
                    "end_time": int(times_unix[e_idx]),
                    "end_kind": ("retest" if tl.retested else
                                 ("broken" if tl.state.value == "broken"
                                  else "active")),
                    "slope": round(tl.slope, 5),
                    "touches": int(tl.touches),
                    "anchor": tl.anchor_kind,
                    "alchemist": tl.alchemist,
                    "desc": (f"{'BRT ' if tl.flipped else ''}TL {role} "
                             f"@{tl.pivot_price:.2f} {tl.state.value}"
                             f"{' +retest' if tl.retested else ''} "
                             f"({tl.touches} touches"
                             f"{', CH' + str(tl.channel_id) if tl.channel_id else ''}"
                             f"{', sweep' if tl.swept else ''}"
                             f", {tl.anchor_kind}"
                             f"{', ' + tl.alchemist if tl.alchemist == 'continuation' else ''}"
                             f"{', ENG' if tl.anchor_engulfing or tl.anchor_engulfed else ''})"),
                }
                if tl.break_index is not None:
                    payload["break_time"] = int(times_unix[min(tl.break_index,
                                                               last_idx)])
                if tl.retest_index is not None:
                    payload["retest_time"] = int(times_unix[min(tl.retest_index,
                                                                last_idx)])
                if tl.sweep_bars:
                    payload["sweep_times"] = [
                        int(times_unix[min(b, last_idx)]) for b in tl.sweep_bars]
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


@app.get("/api/settings/modules")
def get_settings_modules():
    """Entry-module registry for the settings tab."""
    try:
        from strategy.registry import list_modules
        return {"modules": list_modules()}
    except Exception:
        return {"modules": []}


@app.post("/api/settings/modules/{module_id}")
def toggle_settings_module(module_id: str, enabled: bool = Query(True)):
    """Enable/disable one entry module (persists to config/)."""
    try:
        from strategy.registry import set_enabled
        return {"ok": True, "modules": set_enabled(module_id, enabled)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
def get_backtest_trades(journal: str = Query("")):
    """Serve a detection-journal CSV for the viewer.

    journal: relpath under backtest/ (see /api/backtest/journals).
    Empty = newest journal_Sep28-Oct02*.csv (the live book).
    """
    import csv as _csv
    import glob as _glob
    base = os.path.dirname(__file__)
    bt = os.path.join(base, "backtest")
    if journal:
        p = os.path.normpath(os.path.join(bt, journal))
        if (not p.startswith(bt + os.sep) or not p.endswith(".csv")
                or not os.path.isfile(p)):
            raise HTTPException(status_code=404, detail="Journal not found.")
        journal_path = p
    else:
        paths = sorted(_glob.glob(os.path.join(bt, "journal_Sep28-Oct02*.csv")))
        if not paths:
            raise HTTPException(status_code=404, detail="Journal CSV not found.")
        journal_path = paths[-1]
    trades, stats = _read_journal_csv(journal_path)
    return {"trades": trades, "stats": stats,
            "journal": os.path.relpath(journal_path, bt)}


@app.get("/api/backtest/journals")
def list_backtest_journals():
    """List every loadable journal: live book, archive, experiment scans."""
    import glob as _glob
    bt = os.path.join(os.path.dirname(__file__), "backtest")
    pats = ("journal_*.csv", "archive/journal_*.csv", "qm_scan/*.csv",
            "sweep_scan/*.csv", "side_scan/*.csv")
    found = sorted({p for pat in pats
                    for p in _glob.glob(os.path.join(bt, pat))})
    journals = []
    for path in found:
        try:
            trades, stats = _read_journal_csv(path)
        except Exception:
            continue
        rel = os.path.relpath(path, bt).replace(os.sep, "/")
        journals.append({"id": rel, "label": _journal_label(rel),
                         "total": stats["total"], "tp": stats["tp"],
                         "losses": stats["losses"],
                         "total_R": stats["total_R"]})
    journals.sort(key=lambda j: (not j["id"].startswith("journal_"),
                                  j["id"]))
    default = next((j["id"] for j in reversed(journals)
                    if j["id"].startswith("journal_Sep28")), None)
    if default is None:
        default = next((j["id"] for j in journals
                        if j["id"].startswith("journal_")), None)
    if default is None and journals:
        default = journals[0]["id"]
    return {"journals": journals, "default": default}


def _journal_label(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    known = {
        "journal_AI_pilot.csv": "AI pilot: 3 approved setups",
        "journal_Sep28-Oct02_v7.csv": "v7 · LIVE (B: win8+unique)",
        "journal_Sep28-Oct02_v6.csv": "v6 · break-side rule",
        "journal_Sep28-Oct02_v5.csv": "v5 · unique setups",
        "journal_Sep28-Oct02_v4.csv": "v4 · relaxed wicks",
        "journal_Sep28-Oct02_v3.csv": "v3 · structural SL",
        "journal_Sep28-Oct02_v2.csv": "v2 · fixed SL",
        "journal_Sep28-Oct02.csv": "v1 · first journal",
        "sweep_005.csv": "sweep 0.05",
        "sweep_010.csv": "sweep 0.10",
        "sweep_015.csv": "sweep 0.15",
        "sweep_020.csv": "sweep 0.20",
        "side_fixed.csv": "break-side check",
        "qm_win8.csv": "A · window ±8",
        "qm_win8_confl.csv": "A+D · window8+confluence",
        "qm_win8_unique.csv": "B · window8+unique",
        "qm_recent.csv": "C · most-recent pick",
        "qm_confluence.csv": "D · confluence pick",
        "qm_legs2.csv": "E · leg-anchored",
        "qm_legs2_unique.csv": "E2 · legs+unique",
        "qm_merge_tie.csv": "F · tie-abstain",
        "qm_merge_min1.csv": "G · tie+min-score",
        "qm_win12.csv": "window ±12",
        "qm_win16.csv": "window ±16",
        "qm_win20.csv": "window ±20",
        "qm_win25.csv": "window ±25",
        "journal_LUAP_Sep28-Oct02_v1.csv": "LUAP v1 · SMC entries",
    }
    if name in known:
        return known[name]
    stem = name[:-4] if name.endswith(".csv") else name
    if "/" in rel:
        return f"{rel.split('/')[0]}: {stem}"
    return stem


def _read_journal_csv(journal: str):
    import csv as _csv
    trades = []
    with open(journal, "r", encoding="utf-8") as fh:
        reader = _csv.DictReader(fh)
        if not reader.fieldnames or "signal_date" not in reader.fieldnames \
                or "entry" not in reader.fieldnames:
            raise ValueError("Not a journal CSV.")
        for row in reader:
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
    stats = {"total": len(trades), "tp": wins, "losses": losses,
             "expired": expired,
             "total_R": round(sum(t["R"] for t in trades), 2)}
    return trades, stats


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
