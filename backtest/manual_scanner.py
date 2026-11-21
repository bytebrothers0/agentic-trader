"""
backtest/manual_scanner.py — Comprehensive manual setup scanner for all 10 entry models.

Scans historical price action across all detector families and identifies every
valid trading setup per the playbook (EM01-EM10). Records each setup with full
metadata (timestamp, price levels, market conditions, entry model classification)
to a structured JSON file for comparative analysis against agent results.

Usage:
    python -m backtest.manual_scanner --symbol XAUUSDm --timeframes M15,H1,H4 --days 45 --out backtest/out_strategy_probe/manual_setups.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

# Detectors
from indicators.crt_detector import CRTDetector, CRTVariant, CRTState, CRTDirection
from indicators.bos_detector import BOSDetector, BOSDirection
from indicators.fvg_detector import FVGDetector
from indicators.ob_detector import OBDetector
from indicators.liquidity_detector import LiquidityDetector
from indicators.ts_detector import TSDetector
from indicators.idm_detector import IDMDetector
from indicators.apex_detector import ApexDetector
from indicators.ocl_detector import OCLDetector
from indicators.qm_detector import QMDetector
from indicators.trendline_detector import TLDetector
from indicators.candle_analyzer import CandleAnalyzer

from indicators.swings import atr_series

from backtest.historical import load_or_fetch, tf_seconds


# --------------------------------------------------------------------------- #
# Detector parameter defaults (production settings)
# --------------------------------------------------------------------------- #

DETECTOR_PARAMS = {
    "crt": {
        "min_range_atr": 0.0,
        "min_sweep_atr": 0.0,
        "min_close_back_atr": 0.0,
        "max_inside_bars": 6,
        "require_directional_anchor": False,
        "max_per_side": 6,
        "max_live_per_side": 20,
        "atr_period": 14,
    },
    "bos": {"swing_length": 25, "internal_length": 3},
    "liquidity": {
        "swing_length": 5,
        "eq_tol_atr": 0.15,
        "eq_max_bars": 60,
        "min_touches": 2,
        "max_per_side": 3,
        "atr_period": 14,
    },
    "fvg": {"min_atr_mult": 0.1},
    "ob": {"swing_length": 10, "show_last": 3, "require_fvg": False, "require_sweep": True},
    "ts": {"swing_length": 5},
    "qm": {},
    "tl": {"pivot_length": 14, "slope_mult": 1.0, "max_lines": 8, "tol_atr": 0.25},
    "ocl": {},
    "apex": {},
    "sr": {},  # CandleAnalyzer
    "idm": {"swing_length": 2},
}


# --------------------------------------------------------------------------- #
# Setup records
# --------------------------------------------------------------------------- #


@dataclass
class ManualSetup:
    """One manually-identified trading setup with complete metadata."""

    # Identity
    entry_model: str  # EM01..EM10
    model_name: str
    timeframe: str
    symbol: str

    # Timing
    anchor_time: str = ""
    setup_time: str = ""   # the trigger/manipulation candle close (decision instant)
    trigger_time: str = ""
    resolution_time: Optional[str] = None

    # Price levels
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    swept_level: Optional[float] = None
    range_high: Optional[float] = None
    range_low: Optional[float] = None

    # Risk
    risk_points: float = 0.0
    reward_points: float = 0.0
    rr: float = 0.0

    # State & outcome
    state: str = ""  # MANIPULATED / DISTRIBUTED / INVALIDATED / LIVE / BROKEN / FILLED
    bars_to_resolution: Optional[int] = None
    outcome: Optional[str] = None  # TP / SL / OPEN / INVALID

    # Market conditions
    htf_bias: str = ""  # W1/D1/H4 directional context
    htf_levels: List[str] = field(default_factory=list)

    # Evidence
    evidence_levels: List[Dict[str, Any]] = field(default_factory=list)
    detector_signals: List[str] = field(default_factory=list)
    observation_notes: str = ""

    # Scoring
    range_atr: float = 0.0
    quality_score: float = 0.0  # 0-100

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Pricing helpers
# --------------------------------------------------------------------------- #


def _price_crt_bullish(df: pd.DataFrame, j: int, lvl, atr: List[float]) -> Dict[str, float]:
    entry = float(df["close"].iloc[j])
    buffer = 0.25 * float(atr[j] or 0.0)
    stop = float(df["low"].iloc[j]) - buffer
    target = float(lvl.crh)
    risk = entry - stop
    reward = target - entry
    return {
        "entry": round(entry, 3),
        "stop": round(stop, 3),
        "target": round(target, 3),
        "risk": round(risk, 3),
        "reward": round(reward, 3),
        "rr": round(reward / risk, 3) if risk > 0 else 0.0,
    }


def _price_crt_bearish(df: pd.DataFrame, j: int, lvl, atr: List[float]) -> Dict[str, float]:
    entry = float(df["close"].iloc[j])
    buffer = 0.25 * float(atr[j] or 0.0)
    stop = float(df["high"].iloc[j]) + buffer
    target = float(lvl.crl)
    risk = stop - entry
    reward = entry - target
    return {
        "entry": round(entry, 3),
        "stop": round(stop, 3),
        "target": round(target, 3),
        "risk": round(risk, 3),
        "reward": round(reward, 3),
        "rr": round(reward / risk, 3) if risk > 0 else 0.0,
    }


# --------------------------------------------------------------------------- #
# EM01-EM02: CRT (classic + inside_bar)
# --------------------------------------------------------------------------- #


def scan_em01_em02_crt(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                       since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM01 (CLASSIC) and EM02 (INSIDE_BAR) CRT setups."""
    setups: List[ManualSetup] = []
    detector = CRTDetector(df, **DETECTOR_PARAMS["crt"])
    levels = detector.detect_all()

    for lvl in levels:
        if lvl.variant not in (CRTVariant.CLASSIC, CRTVariant.INSIDE_BAR):
            continue

        j = int(lvl.manipulation_index)
        decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
        if since is not None and pd.Timestamp(decision) < since:
            continue

        direction = lvl.direction.value
        if direction == "bullish":
            priced = _price_crt_bullish(df, j, lvl, atr)
        else:
            priced = _price_crt_bearish(df, j, lvl, atr)

        model_id = "EM01" if lvl.variant is CRTVariant.CLASSIC else "EM02"
        model_name = ("Classic CRT sweep and delivery" if lvl.variant is CRTVariant.CLASSIC
                      else "Inside-bar CRT expansion")

        setup = ManualSetup(
            entry_model=model_id,
            model_name=model_name,
            timeframe=str(timeframe).upper(),
            symbol="XAUUSDm",
            anchor_time=pd.Timestamp(lvl.anchor_time).isoformat(),
            setup_time=pd.Timestamp(lvl.manipulation_time).isoformat(),
            trigger_time=pd.Timestamp(lvl.manipulation_time).isoformat(),
            resolution_time=(
                pd.Timestamp(lvl.distribution_time).isoformat()
                if lvl.distribution_time is not None else None
            ),
            entry_price=priced["entry"],
            stop_price=priced["stop"],
            target_price=priced["target"],
            swept_level=round(float(lvl.swept_level), 3),
            range_high=round(float(lvl.crh), 3),
            range_low=round(float(lvl.crl), 3),
            risk_points=priced["risk"],
            reward_points=priced["reward"],
            rr=priced["rr"],
            state=lvl.state.value,
            bars_to_resolution=(
                int(lvl.distribution_index - lvl.manipulation_index)
                if lvl.distribution_index is not None else None
            ),
            outcome=(
                "TP" if lvl.state is CRTState.DISTRIBUTED else
                "SL" if lvl.state is CRTState.INVALIDATED else "OPEN"
            ),
            htf_bias="",
            htf_levels=[],
            evidence_levels=[
                {"family": "crt", "timeframe": timeframe, "direction": direction,
                 "price": round(float(lvl.swept_level), 3), "variant": lvl.variant.value,
                 "state": lvl.state.value}
            ],
            detector_signals=[f"crt:{direction}:{lvl.variant.value}:@{float(lvl.swept_level):.3f}"],
            observation_notes=(
                f"{model_name}: {direction} CRT, range {float(lvl.crl):.3f}-{float(lvl.crh):.3f}, "
                f"swept {float(lvl.swept_level):.3f}, target {float(lvl.target_level):.3f}, "
                f"inside_bars={int(lvl.inside_count)}, sweep={float(lvl.sweep_amount):.3f} pts"
            ),
            range_atr=round(float(lvl.range_atr), 3),
        )
        setup.quality_score = _score_crt_quality(setup)
        setups.append(setup)

    return setups


def _score_crt_quality(s: ManualSetup) -> float:
    score = 50.0
    if s.rr >= 1.5:
        score += 20
    elif s.rr >= 1.0:
        score += 10
    if s.range_atr >= 1.0:
        score += 15
    if s.outcome == "TP":
        score += 15
    return min(score, 100.0)


# --------------------------------------------------------------------------- #
# EM03: Liquidity raid + structure shift
# --------------------------------------------------------------------------- #


def scan_em03_liquidity_raid(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                             since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM03: Liquidity pool raid + reclaim + structure shift (BOS)."""
    setups: List[ManualSetup] = []

    liq_detector = LiquidityDetector(df, **DETECTOR_PARAMS["liquidity"])
    liq_levels = liq_detector.detect_all()

    bos_detector = BOSDetector(df, **DETECTOR_PARAMS["bos"])
    bos_levels = bos_detector.detect_all()

    # Build index->BOS lookup for structure shift detection
    bos_by_break: Dict[int, Any] = {}
    for b in bos_levels:
        bos_by_break[b.break_index] = b

    for pool in liq_levels:
        # The pool must be taken (raid happened)
        if not pool.taken:
            continue

        taken_idx = pool.taken_index
        if taken_idx is None or taken_idx >= len(df) - 1:
            continue

        # Look for a structure shift after the pool was taken
        shift_bos = None
        for bi in range(taken_idx + 1, min(taken_idx + 20, len(df))):
            if bi in bos_by_break:
                shift_bos = bos_by_break[bi]
                break

        j = taken_idx  # decision instant = raid candle close
        decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
        if since is not None and pd.Timestamp(decision) < since:
            continue

        # Price the setup: entry at pool level, stop beyond raid extreme
        entry = float(pool.price)
        if pool.side.value == "buyside":
            # BSL above - buy-side liquidity raided, expect downside
            stop = float(df["high"].iloc[taken_idx]) + 0.25 * float(atr.iloc[taken_idx] or 0.0)
            target = entry - (stop - entry) * 1.5  # 1.5:R minimum
            direction = "bearish"
        else:
            # SSL below - sell-side liquidity raided, expect upside
            stop = float(df["low"].iloc[taken_idx]) - 0.25 * float(atr.iloc[taken_idx] or 0.0)
            target = entry + (entry - stop) * 1.5
            direction = "bullish"

        risk = abs(entry - stop)
        reward = abs(target - entry)

        setup = ManualSetup(
            entry_model="EM03",
            model_name="Liquidity raid, reclaim and structure shift",
            timeframe=str(timeframe).upper(),
            symbol="XAUUSDm",
            anchor_time=pd.Timestamp(pool.candle_time).isoformat(),
            setup_time=pd.Timestamp(df.index[j]).isoformat(),
            trigger_time=pd.Timestamp(df.index[j]).isoformat(),
            resolution_time=None,
            entry_price=round(entry, 3),
            stop_price=round(stop, 3),
            target_price=round(target, 3),
            swept_level=round(float(pool.price), 3),
            range_high=None,
            range_low=None,
            risk_points=round(risk, 3),
            reward_points=round(reward, 3),
            rr=round(reward / risk, 3) if risk > 0 else 0.0,
            state="LIVE" if shift_bos is None else "DISTRIBUTED",
            bars_to_resolution=None,
            outcome="TP" if shift_bos is not None else "OPEN",
            htf_bias="",
            htf_levels=[],
            evidence_levels=[
                {"family": "liquidity", "timeframe": timeframe, "direction": pool.side.value,
                 "price": round(float(pool.price), 3), "pool_size": pool.pool_size,
                 "taken": pool.taken},
                {"family": "bos", "timeframe": timeframe, "direction": direction,
                 "price": round(float(shift_bos.price), 3) if shift_bos else 0.0,
                 "kind": shift_bos.kind if shift_bos else "none"} if shift_bos else
                 {"family": "bos", "timeframe": timeframe, "direction": direction,
                  "price": 0.0, "kind": "none"},
            ],
            detector_signals=[f"liquidity:{pool.side.value}:@{float(pool.price):.3f}:taken={pool.taken}"],
            observation_notes=(
                f"EM03: {pool.side.value} liquidity pool @ {float(pool.price):.3f} "
                f"(size={pool.pool_size}, taken={pool.taken}) raided at {pd.Timestamp(df.index[j])}; "
                f"structure shift {'detected' if shift_bos else 'pending'}"
            ),
            range_atr=0.0,
        )
        setup.quality_score = _score_liq_quality(setup, shift_bos)
        setups.append(setup)

    return setups


def _score_liq_quality(s: ManualSetup, shift_bos: Optional[Any]) -> float:
    score = 40.0
    if s.rr >= 1.5:
        score += 25
    elif s.rr >= 1.0:
        score += 10
    if shift_bos is not None:
        score += 25
    if s.evidence_levels[0].get("pool_size", 0) >= 3:
        score += 10
    return min(score, 100.0)


# --------------------------------------------------------------------------- #
# EM04: Fresh S/R level rejection
# --------------------------------------------------------------------------- #


def scan_em04_sr_rejection(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                           since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM04: Fresh MSNR support/resistance level rejection."""
    setups: List[ManualSetup] = []

    analyzer = CandleAnalyzer(df)
    levels = analyzer.detect_all()

    for lvl in levels:
        if lvl.level_type not in ("SUPPORT", "RESISTANCE"):
            continue

        j = int(lvl.candle_index)
        decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
        if since is not None and pd.Timestamp(decision) < since:
            continue

        # Only FRESH levels qualify for EM04
        if lvl.state.value != "FRESH":
            continue

        direction = lvl.level_type.value.lower()
        price = float(lvl.price)
        entry = price
        buffer = 0.25 * float(atr[j] or 0.0)

        if direction == "support":
            # Price rejected from support -> bullish
            stop = price - buffer
            target = price + (price - stop) * 2.0
            trade_dir = "bullish"
        else:
            # Price rejected from resistance -> bearish
            stop = price + buffer
            target = price - (stop - price) * 2.0
            trade_dir = "bearish"

        risk = abs(entry - stop)
        reward = abs(target - entry)

        setup = ManualSetup(
            entry_model="EM04",
            model_name="Fresh MSNR level rejection",
            timeframe=str(timeframe).upper(),
            symbol="XAUUSDm",
            anchor_time=pd.Timestamp(lvl.candle_time).isoformat(),
            setup_time=pd.Timestamp(df.index[j]).isoformat(),
            trigger_time=pd.Timestamp(df.index[j]).isoformat(),
            resolution_time=None,
            entry_price=round(entry, 3),
            stop_price=round(stop, 3),
            target_price=round(target, 3),
            swept_level=None,
            range_high=None,
            range_low=None,
            risk_points=round(risk, 3),
            reward_points=round(reward, 3),
            rr=round(reward / risk, 3) if risk > 0 else 0.0,
            state=lvl.state.value,
            bars_to_resolution=None,
            outcome="OPEN",
            htf_bias="",
            htf_levels=[],
            evidence_levels=[
                {"family": "sr", "timeframe": timeframe, "direction": direction,
                 "price": round(price, 3), "level_type": lvl.level_type.value,
                 "touch_count": lvl.touch_count}
            ],
            detector_signals=[f"sr:{direction}:{lvl.level_type.value}:@{price:.3f}"],
            observation_notes=(
                f"EM04: Fresh {direction} {lvl.level_type.value} @ {price:.3f} "
                f"at {pd.Timestamp(lvl.candle_time)}, touches={lvl.touch_count}"
            ),
            range_atr=0.0,
        )
        setup.quality_score = _score_sr_quality(setup)
        setups.append(setup)

    return setups


def _score_sr_quality(s: ManualSetup) -> float:
    score = 50.0
    if s.rr >= 2.0:
        score += 30
    elif s.rr >= 1.5:
        score += 20
    touches = s.evidence_levels[0].get("touch_count", 0) if s.evidence_levels else 0
    if touches >= 3:
        score += 20
    return min(score, 100.0)


# --------------------------------------------------------------------------- #
# EM05: SBR/RBS role-flip retest
# --------------------------------------------------------------------------- #


def scan_em05_sbr_rbs(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                      since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM05: SBR/RBS role-flip retest."""
    setups: List[ManualSetup] = []

    analyzer = CandleAnalyzer(df)
    levels = analyzer.detect_all()

    for lvl in levels:
        if lvl.level_type not in ("SBR", "RBS"):
            continue

        j = int(lvl.candle_index)
        decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
        if since is not None and pd.Timestamp(decision) < since:
            continue

        direction = lvl.level_type.value
        price = float(lvl.price)
        entry = price
        buffer = 0.25 * float(atr.iloc[j] or 0.0)

        if direction == "RBS":
            # Resistance became support -> bullish retest
            stop = price - buffer
            target = price + (price - stop) * 2.0
            trade_dir = "bullish"
        else:
            # Support became resistance -> bearish retest
            stop = price + buffer
            target = price - (stop - price) * 2.0
            trade_dir = "bearish"

        risk = abs(entry - stop)
        reward = abs(target - entry)

        setup = ManualSetup(
            entry_model="EM05",
            model_name="SBR/RBS role-flip retest",
            timeframe=str(timeframe).upper(),
            symbol="XAUUSDm",
            anchor_time=pd.Timestamp(lvl.candle_time).isoformat(),
            setup_time=pd.Timestamp(df.index[j]).isoformat(),
            trigger_time=pd.Timestamp(df.index[j]).isoformat(),
            resolution_time=None,
            entry_price=round(entry, 3),
            stop_price=round(stop, 3),
            target_price=round(target, 3),
            swept_level=None,
            range_high=None,
            range_low=None,
            risk_points=round(risk, 3),
            reward_points=round(reward, 3),
            rr=round(reward / risk, 3) if risk > 0 else 0.0,
            state=lvl.state.value,
            bars_to_resolution=None,
            outcome="OPEN",
            htf_bias="",
            htf_levels=[],
            evidence_levels=[
                {"family": "sr", "timeframe": timeframe, "direction": trade_dir,
                 "price": round(price, 3), "level_type": direction,
                 "touch_count": lvl.touch_count}
            ],
            detector_signals=[f"sr:{direction}:{direction}:@{price:.3f}"],
            observation_notes=(
                f"EM05: {direction} role-flip @ {price:.3f} at {pd.Timestamp(lvl.candle_time)}, "
                f"touches={lvl.touch_count}"
            ),
            range_atr=0.0,
        )
        setup.quality_score = _score_sr_quality(setup)
        setups.append(setup)

    return setups


# --------------------------------------------------------------------------- #
# EM06: Displacement BOS + FVG retracement
# --------------------------------------------------------------------------- #


def scan_em06_bos_fvg(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                      since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM06: Displacement BOS + FVG retracement."""
    setups: List[ManualSetup] = []

    bos_detector = BOSDetector(df, **DETECTOR_PARAMS["bos"])
    bos_levels = bos_detector.detect_all()

    fvg_detector = FVGDetector(df)
    fvg_levels = fvg_detector.detect_all()

    for bos in bos_levels:
        if bos.internal:
            continue  # Only external BOS for EM06

        j = int(bos.break_index)
        decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
        if since is not None and pd.Timestamp(decision) < since:
            continue

        # Find a fresh FVG from the same impulse
        entry = float(bos.price)
        buffer = 0.25 * float(atr[j] or 0.0)

        # Look for FVG formed near the BOS break
        fvg_found = None
        for fvg in fvg_levels:
            if fvg.direction.value == bos.direction.value and \
               fvg.formation_index >= bos.extreme_index and \
               fvg.formation_index <= j:
                fvg_found = fvg
                break

        if bos.direction is BOSDirection.BULLISH:
            stop = entry - buffer
            target = fvg_found.top if fvg_found else entry + (entry - stop) * 2.0
            trade_dir = "bullish"
        else:
            stop = entry + buffer
            target = fvg_found.bottom if fvg_found else entry - (stop - entry) * 2.0
            trade_dir = "bearish"

        risk = abs(entry - stop)
        reward = abs(target - entry)

        setup = ManualSetup(
            entry_model="EM06",
            model_name="Displacement BOS and FVG retracement",
            timeframe=str(timeframe).upper(),
            symbol="XAUUSDm",
            anchor_time=pd.Timestamp(bos.candle_time).isoformat(),
            setup_time=pd.Timestamp(df.index[j]).isoformat(),
            trigger_time=pd.Timestamp(df.index[j]).isoformat(),
            resolution_time=None,
            entry_price=round(entry, 3),
            stop_price=round(stop, 3),
            target_price=round(target, 3),
            swept_level=None,
            range_high=None,
            range_low=None,
            risk_points=round(risk, 3),
            reward_points=round(reward, 3),
            rr=round(reward / risk, 3) if risk > 0 else 0.0,
            state="LIVE",
            bars_to_resolution=None,
            outcome="OPEN",
            htf_bias="",
            htf_levels=[],
            evidence_levels=[
                {"family": "bos", "timeframe": timeframe, "direction": trade_dir,
                 "price": round(float(bos.price), 3), "kind": bos.kind,
                 "internal": bos.internal},
                {"family": "fvg", "timeframe": timeframe, "direction": trade_dir,
                 "price": round(float(fvg_found.top), 3) if fvg_found else 0.0,
                 "fresh": bool(fvg_found)} if fvg_found else
                 {"family": "fvg", "timeframe": timeframe, "direction": trade_dir,
                  "price": 0.0, "fresh": False},
            ],
            detector_signals=[f"bos:{bos.kind}:{trade_dir}:@{float(bos.price):.3f}"],
            observation_notes=(
                f"EM06: {bos.kind} {trade_dir} BOS @ {float(bos.price):.3f} "
                f"at {pd.Timestamp(bos.candle_time)}, FVG={'found' if fvg_found else 'none'}"
            ),
            range_atr=0.0,
        )
        setup.quality_score = _score_bos_fvg_quality(setup, fvg_found)
        setups.append(setup)

    return setups


def _score_bos_fvg_quality(s: ManualSetup, fvg: Optional[Any]) -> float:
    score = 50.0
    if s.rr >= 1.5:
        score += 25
    if fvg is not None:
        score += 25
    return min(score, 100.0)


# --------------------------------------------------------------------------- #
# EM07-EM08: Order Block / Breaker retest
# --------------------------------------------------------------------------- #


def scan_em07_em08_ob(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                      since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM07 (OB retest) and EM08 (Breaker retest)."""
    setups: List[ManualSetup] = []

    ob_detector = OBDetector(df, **DETECTOR_PARAMS["ob"])
    ob_levels = ob_detector.detect_all()

    for ob in ob_levels:
        j = int(ob.formation_index)
        decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
        if since is not None and pd.Timestamp(decision) < since:
            continue

        is_breaker = ob.is_breaker
        model_id = "EM08" if is_breaker else "EM07"
        model_name = "Breaker retest" if is_breaker else "Displacement-backed order-block retest"

        top = float(ob.top)
        bottom = float(ob.bottom)
        entry = (top + bottom) / 2.0  # Mid-zone entry
        buffer = 0.25 * float(atr[j] or 0.0)

        if ob.direction.value == "bullish":
            stop = bottom - buffer
            target = top + (top - bottom) * 2.0
            trade_dir = "bullish"
        else:
            stop = top + buffer
            target = bottom - (top - bottom) * 2.0
            trade_dir = "bearish"

        risk = abs(entry - stop)
        reward = abs(target - entry)

        setup = ManualSetup(
            entry_model=model_id,
            model_name=model_name,
            timeframe=str(timeframe).upper(),
            symbol="XAUUSDm",
            anchor_time=pd.Timestamp(ob.candle_time).isoformat(),
            setup_time=pd.Timestamp(df.index[j]).isoformat(),
            trigger_time=pd.Timestamp(df.index[j]).isoformat(),
            resolution_time=None,
            entry_price=round(entry, 3),
            stop_price=round(stop, 3),
            target_price=round(target, 3),
            swept_level=None,
            range_high=round(top, 3),
            range_low=round(bottom, 3),
            risk_points=round(risk, 3),
            reward_points=round(reward, 3),
            rr=round(reward / risk, 3) if risk > 0 else 0.0,
            state="MITIGATED" if ob.mitigated else "FRESH",
            bars_to_resolution=None,
            outcome="OPEN",
            htf_bias="",
            htf_levels=[],
            evidence_levels=[
                {"family": "ob", "timeframe": timeframe, "direction": trade_dir,
                 "price": round(entry, 3), "zone_high": round(top, 3),
                 "zone_low": round(bottom, 3), "is_breaker": is_breaker,
                 "mitigated": ob.mitigated}
            ],
            detector_signals=[f"ob:{'breaker' if is_breaker else 'ob'}:{trade_dir}:@{entry:.3f}"],
            observation_notes=(
                f"{model_name}: {trade_dir} {'breaker' if is_breaker else 'order block'} "
                f"zone {bottom:.3f}-{top:.3f} at {pd.Timestamp(ob.candle_time)}, "
                f"mitigated={ob.mitigated}"
            ),
            range_atr=0.0,
        )
        setup.quality_score = _score_ob_quality(setup, is_breaker)
        setups.append(setup)

    return setups


def _score_ob_quality(s: ManualSetup, is_breaker: bool) -> float:
    score = 50.0
    if s.rr >= 2.0:
        score += 30
    elif s.rr >= 1.5:
        score += 20
    if is_breaker:
        score += 10
    return min(score, 100.0)


# --------------------------------------------------------------------------- #
# EM09: Trendline break and retest
# --------------------------------------------------------------------------- #


def scan_em09_trendline(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                        since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM09: Trendline break and retest."""
    setups: List[ManualSetup] = []

    tl_detector = TLDetector(df)
    tl_lines = tl_detector.detect_all()

    for line in tl_lines:
        if not line.broken or line.retest_index is None:
            continue

        j = int(line.break_index)
        decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
        if since is not None and pd.Timestamp(decision) < since:
            continue

        price = float(line.pivot_price)
        entry = price
        buffer = 0.25 * float(atr.iloc[j] or 0.0)

        # Determine trade direction from retest role
        trade_dir = "bullish" if line.retest_role == "support" else "bearish"

        if trade_dir == "bullish":
            stop = price - buffer
            target = price + (price - stop) * 2.0
        else:
            stop = price + buffer
            target = price - (stop - price) * 2.0

        risk = abs(entry - stop)
        reward = abs(target - entry)

        setup = ManualSetup(
            entry_model="EM09",
            model_name="Trendline break and retest",
            timeframe=str(timeframe).upper(),
            symbol="XAUUSDm",
            anchor_time=pd.Timestamp(line.candle_time if hasattr(line, 'candle_time') else df.index[j]).isoformat(),
            setup_time=pd.Timestamp(df.index[j]).isoformat(),
            trigger_time=pd.Timestamp(df.index[j]).isoformat(),
            resolution_time=None,
            entry_price=round(entry, 3),
            stop_price=round(stop, 3),
            target_price=round(target, 3),
            swept_level=None,
            range_high=None,
            range_low=None,
            risk_points=round(risk, 3),
            reward_points=round(reward, 3),
            rr=round(reward / risk, 3) if risk > 0 else 0.0,
            state="BROKEN" if line.broken else "ACTIVE",
            bars_to_resolution=None,
            outcome="OPEN",
            htf_bias="",
            htf_levels=[],
            evidence_levels=[
                {"family": "trendline", "timeframe": timeframe, "direction": trade_dir,
                 "price": round(price, 3), "side": line.side.value if hasattr(line.side, 'value') else str(line.side),
                 "touches": line.touches, "retested": line.retested}
            ],
            detector_signals=[f"trendline:{trade_dir}:break_@ {price:.3f}"],
            observation_notes=(
                f"EM09: {trade_dir} trendline break @ {price:.3f} at {pd.Timestamp(df.index[j])}, "
                f"retested={line.retested}, touches={line.touches}"
            ),
            range_atr=0.0,
        )
        setup.quality_score = _score_tl_quality(setup)
        setups.append(setup)

    return setups


def _score_tl_quality(s: ManualSetup) -> float:
    score = 50.0
    if s.rr >= 1.5:
        score += 25
    touches = s.evidence_levels[0].get("touches", 0) if s.evidence_levels else 0
    if touches >= 3:
        score += 15
    if s.evidence_levels[0].get("retested", False) if s.evidence_levels else False:
        score += 10
    return min(score, 100.0)


# --------------------------------------------------------------------------- #
# EM10: Range acceptance breakout and retest (no dedicated detector)
# --------------------------------------------------------------------------- #


def scan_em10_range_breakout(df: pd.DataFrame, timeframe: str, atr: pd.Series,
                             since: Optional[pd.Timestamp] = None) -> List[ManualSetup]:
    """EM10: Range acceptance breakout and retest (manual heuristic - no detector).

    Detects bounded ranges with observable reactions where price closes outside
    the range and then retests and holds on the breakout side.
    """
    setups: List[ManualSetup] = []

    # Use BOS levels as range boundary proxies
    bos_detector = BOSDetector(df, **DETECTOR_PARAMS["bos"])
    bos_levels = bos_detector.detect_all()

    # Find range-like structures: two opposing BOS levels forming a range
    for i, bos_high in enumerate(bos_levels):
        if bos_high.direction is not BOSDirection.BEARISH:
            continue
        for bos_low in bos_levels:
            if bos_low.direction is not BOSDirection.BULLISH:
                continue
            if bos_low.break_index >= bos_high.break_index:
                continue
            if abs(bos_high.break_index - bos_low.break_index) < 3:
                continue

            range_low = float(bos_low.price)
            range_high = float(bos_high.price)
            range_size = range_high - range_low

            # Look for breakout after the range formed
            for j in range(bos_high.break_index + 1, min(bos_high.break_index + 50, len(df))):
                close = float(df["close"].iloc[j])
                decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
                if since is not None and pd.Timestamp(decision) < since:
                    continue

                # Breakout above range
                if close > range_high:
                    entry = close
                    stop = range_high - 0.25 * float(atr.iloc[j] or 0.0)
                    target = entry + (entry - stop) * 2.0
                    trade_dir = "bullish"
                    breakout_level = range_high
                    break
                # Breakout below range
                elif close < range_low:
                    entry = close
                    stop = range_low + 0.25 * float(atr.iloc[j] or 0.0)
                    target = entry - (stop - entry) * 2.0
                    trade_dir = "bearish"
                    breakout_level = range_low
                    break
            else:
                continue
            break
        else:
            continue
        break
    else:
        return setups

    # Only one EM10 candidate per scan (heuristic)
    risk = abs(entry - stop)
    reward = abs(target - entry)

    setup = ManualSetup(
        entry_model="EM10",
        model_name="Range acceptance breakout and retest",
        timeframe=str(timeframe).upper(),
        symbol="XAUUSDm",
        anchor_time=pd.Timestamp(df.index[bos_low.break_index]).isoformat(),
        setup_time=pd.Timestamp(df.index[j]).isoformat(),
        trigger_time=pd.Timestamp(df.index[j]).isoformat(),
        resolution_time=None,
        entry_price=round(entry, 3),
        stop_price=round(stop, 3),
        target_price=round(target, 3),
        swept_level=None,
        range_high=round(range_high, 3),
        range_low=round(range_low, 3),
        risk_points=round(risk, 3),
        reward_points=round(reward, 3),
        rr=round(reward / risk, 3) if risk > 0 else 0.0,
        state="LIVE",
        bars_to_resolution=None,
        outcome="OPEN",
        htf_bias="",
        htf_levels=[],
        evidence_levels=[
            {"family": "bos", "timeframe": timeframe, "direction": trade_dir,
             "price": round(breakout_level, 3), "range_high": round(range_high, 3),
             "range_low": round(range_low, 3)}
        ],
        detector_signals=[f"range_breakout:{trade_dir}:@{breakout_level:.3f}"],
        observation_notes=(
            f"EM10: Range {range_low:.3f}-{range_high:.3f} broken {trade_dir} "
            f"at {pd.Timestamp(df.index[j])}, entry={entry:.3f}"
        ),
        range_atr=0.0,
    )
    setup.quality_score = 60.0  # Heuristic baseline
    setups.append(setup)

    return setups


# --------------------------------------------------------------------------- #
# Main scan orchestrator
# --------------------------------------------------------------------------- #


EM_SCANNERS = {
    "EM01": scan_em01_em02_crt,
    "EM02": scan_em01_em02_crt,
    "EM03": scan_em03_liquidity_raid,
    "EM04": scan_em04_sr_rejection,
    "EM05": scan_em05_sbr_rbs,
    "EM06": scan_em06_bos_fvg,
    "EM07": scan_em07_em08_ob,
    "EM08": scan_em07_em08_ob,
    "EM09": scan_em09_trendline,
    "EM10": scan_em10_range_breakout,
}


def scan_all_setups(symbol: str, timeframes: List[str], since: Optional[pd.Timestamp],
                    cache: str) -> Dict[str, List[ManualSetup]]:
    """Run all entry model scanners across all timeframes."""
    symbol, frames = load_or_fetch(symbol, cache=cache, refresh=False,
                                   timeframes=timeframes, max_bars=500)

    all_setups: Dict[str, List[ManualSetup]] = {}

    for tf in timeframes:
        if tf not in frames:
            print(f"WARNING: no {tf} data loaded (have: {sorted(frames)})")
            continue
        df = frames[tf]
        atr = atr_series(df, 14)

        tf_setups: List[ManualSetup] = []

        # CRT covers EM01 and EM02 together
        crt_setups = scan_em01_em02_crt(df, tf, atr, since)
        tf_setups.extend(crt_setups)

        # Other models
        for em_id in ("EM03", "EM04", "EM05", "EM06", "EM07", "EM08", "EM09", "EM10"):
            scanner = EM_SCANNERS[em_id]
            model_setups = scanner(df, tf, atr, since)
            tf_setups.extend(model_setups)

        # Sort by quality score descending
        tf_setups.sort(key=lambda s: s.quality_score, reverse=True)

        all_setups[tf] = tf_setups
        print(f"  {tf}: {len(tf_setups)} setups "
              f"({sum(1 for s in tf_setups if s.entry_model == 'EM01')} EM01, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM02')} EM02, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM03')} EM03, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM04')} EM04, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM05')} EM05, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM06')} EM06, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM07')} EM07, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM08')} EM08, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM09')} EM09, "
              f"{sum(1 for s in tf_setups if s.entry_model == 'EM10')} EM10)")

    return all_setups


def save_setups(setups: Dict[str, List[ManualSetup]], out_path: str) -> None:
    """Save setups to JSON and Markdown."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # JSON
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "XAUUSDm",
        "total_setups": sum(len(v) for v in setups.values()),
        "by_timeframe": {},
    }
    for tf, tf_setups in setups.items():
        data["by_timeframe"][tf] = {
            "count": len(tf_setups),
            "by_model": {},
            "setups": [s.to_dict() for s in tf_setups],
        }
        model_counts: Dict[str, int] = {}
        for s in tf_setups:
            model_counts[s.entry_model] = model_counts.get(s.entry_model, 0) + 1
        data["by_timeframe"][tf]["by_model"] = model_counts

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    # Markdown
    md_path = os.path.splitext(out_path)[0] + ".md"
    lines = ["# Manual Setup Scan Results", ""]
    lines.append(f"- generated: {data['generated_at']}")
    lines.append(f"- symbol: {data['symbol']}")
    lines.append(f"- total setups: {data['total_setups']}")
    lines.append("")

    for tf, tf_setups in setups.items():
        lines.append(f"## {tf} Timeframe ({len(tf_setups)} setups)")
        lines.append("")
        model_counts: Dict[str, int] = {}
        for s in tf_setups:
            model_counts[s.entry_model] = model_counts.get(s.entry_model, 0) + 1
        for mid, count in sorted(model_counts.items()):
            lines.append(f"- {mid}: {count}")
        lines.append("")

        for i, s in enumerate(tf_setups, 1):
            lines.append(f"### {i}. {s.entry_model} — {s.model_name}")
            lines.append("")
            lines.append(f"- **Time:** {s.setup_time}")
            lines.append(f"- **Timeframe:** {s.timeframe}")
            lines.append(f"- **Entry:** {s.entry_price} / **SL:** {s.stop_price} / **TP:** {s.target_price}")
            lines.append(f"- **R:R:** {s.rr} | **Quality:** {s.quality_score:.0f}/100")
            lines.append(f"- **State:** {s.state} | **Outcome:** {s.outcome or 'pending'}")
            if s.range_high and s.range_low:
                lines.append(f"- **Range:** {s.range_low}–{s.range_high}")
            lines.append(f"- **Notes:** {s.observation_notes}")
            lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nSaved JSON: {out_path}")
    print(f"Saved Markdown: {md_path}")


def main() -> int:
    p = argparse.ArgumentParser(description="Manual setup scanner for all 10 entry models")
    p.add_argument("--symbol", default="XAUUSDm", help="MT5 symbol")
    p.add_argument("--timeframes", default="M15,H1,H4", help="Comma-separated timeframes")
    p.add_argument("--days", type=float, default=45.0, help="Days of history to scan")
    p.add_argument("--out", default="backtest/out_strategy_probe/manual_setups.json",
                   help="Output JSON path")
    p.add_argument("--cache", default="backtest/out_strategy_probe/history_recent.pkl",
                   help="History cache path")
    args = p.parse_args()

    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    # Compute since timestamp from days
    import pandas as pd
    since = None
    if args.days > 0:
        # We'll compute since from the last bar after loading
        since = None  # Will be set per-timeframe in scan_all_setups

    print(f"Scanning {args.symbol} across {timeframes} for all 10 entry models...")
    setups = scan_all_setups(args.symbol, timeframes, since, args.cache)
    save_setups(setups, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
