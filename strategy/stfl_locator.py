"""
stfl_locator.py — MSNR Second Time Frame Level (STFL) Locator

Rules (from Advanced MSNR, Videos 7, 8, 10, 11):
  - STFL is where the market will BUY or SELL from.
  - Searches on the timeframe one step lower than FTFL:
      - Monthly FTFL -> Weekly STFL
      - Weekly FTFL  -> Daily STFL
      - Daily FTFL   -> 4-Hour (H4) STFL
  - Look inside the FTFL Box for:
      - For Buys: Support or QM (must be fresh; apex-unfresh allowed as fallback)
      - For Sells: Resistance or QM (must be fresh; apex-unfresh allowed as fallback)
  - Strict Video 7 discipline: if NO key level is found inside the FTFL box,
    return None (no trade) instead of forcing an outside-box fallback.
  - Constructs a smaller STFL refinement box (body close to tip of wick, 1 step right).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
import pandas as pd

from indicators.candle_analyzer import CandleAnalyzer, CandleLevel, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.qm_detector import QMDetector, QMLevel, QMType, QMDirection
from indicators.apex_detector import ApexDetector, ApexLevel, ApexType
from indicators.ocl_detector import OCLDetector, OCLLevel, OCLType
from strategy.storyline_engine import BiasDirection
from strategy.ftfl_locator import FTFLZone


@dataclass
class STFLZone:
    """Represents a refined STFL key level inside the FTFL box."""
    timeframe: str              # e.g., 'D1', 'H4'
    direction: BiasDirection    # BULLISH or BEARISH
    price: float                # Exact STFL entry level price
    box_top: float              # Upper boundary of STFL box
    box_bottom: float           # Lower boundary of STFL box
    time_formed: pd.Timestamp
    candle_index: int
    level_type_desc: str
    is_inside_ftfl_box: bool = True
    is_fresh: bool = True

    @property
    def equilibrium(self) -> float:
        """50% midpoint of the STFL box (crucial for TTFL fallback)."""
        return (self.box_top + self.box_bottom) / 2.0

    def __repr__(self) -> str:
        return (
            f"STFLZone({self.timeframe} {self.direction.value} @ {self.price:.2f} | "
            f"Box: [{self.box_bottom:.2f} - {self.box_top:.2f}] | {self.level_type_desc})"
        )


class STFLLocator:
    """
    Locates STFL key levels inside the FTFL bounding box.
    """

    def __init__(self, df_stfl: pd.DataFrame, stfl_timeframe: str = "H4"):
        self.df = df_stfl.copy()
        self.timeframe = stfl_timeframe.upper()

    def find_stfl(self, ftfl_zone: FTFLZone) -> Optional[STFLZone]:
        """Search for valid STFL levels matching the FTFL zone."""
        df = self.df
        if len(df) < 5:
            return None

        is_bullish = ftfl_zone.direction == BiasDirection.BULLISH
        highs = df["high"].values
        lows = df["low"].values

        # 1. Detect Base S/R on STFL timeframe
        analyzer = CandleAnalyzer(df)
        sr_levels = analyzer.detect_all()
        tracker = FreshnessTracker(df)
        sr_levels = tracker.update(sr_levels)

        # 2. Detect QMs on STFL timeframe
        qm_det = QMDetector(df, sr_levels)
        qms = qm_det.detect_all()

        # 3. Detect iAB Apex levels on STFL timeframe
        apex_det = ApexDetector(df, timeframe=self.timeframe)
        apexes = apex_det.detect_all()

        # 4. Detect OCLs on STFL timeframe
        ocl_det = OCLDetector(df, timeframe=self.timeframe)
        ocls = ocl_det.detect_all()

        target_sr_type = LevelType.SUPPORT if is_bullish else LevelType.RESISTANCE
        target_qm_dir = QMDirection.BULLISH if is_bullish else QMDirection.BEARISH
        target_iab_type = ApexType.IAB_SUPPORT if is_bullish else ApexType.IAB_RESISTANCE

        # Find all valid levels inside FTFL box [ftfl_zone.box_bottom, ftfl_zone.box_top]
        valid_candidates: List[STFLZone] = []

        # Check S/R inside box
        for sr in sr_levels:
            if sr.level_type == target_sr_type:
                # Must fall within FTFL box bounds (with 0.5% tolerance)
                if ftfl_zone.box_bottom * 0.995 <= sr.price <= ftfl_zone.box_top * 1.005:
                    idx = sr.candle_index
                    box_top = max(highs[idx], highs[min(idx+1, len(df)-1)])
                    box_bottom = min(lows[idx], lows[min(idx+1, len(df)-1)])

                    valid_candidates.append(STFLZone(
                        timeframe=self.timeframe,
                        direction=ftfl_zone.direction,
                        price=sr.price,
                        box_top=box_top,
                        box_bottom=box_bottom,
                        time_formed=sr.candle_time,
                        candle_index=idx,
                        level_type_desc="STFL Support" if is_bullish else "STFL Resistance",
                        is_inside_ftfl_box=True,
                        is_fresh=sr.state == LevelState.FRESH
                    ))

        # Check QMs inside box
        for qm in qms:
            if qm.direction == target_qm_dir:
                if ftfl_zone.box_bottom * 0.995 <= qm.price <= ftfl_zone.box_top * 1.005:
                    valid_candidates.append(STFLZone(
                        timeframe=self.timeframe,
                        direction=ftfl_zone.direction,
                        price=qm.price,
                        box_top=qm.box_high,
                        box_bottom=qm.box_low,
                        time_formed=qm.candle_time,
                        candle_index=qm.break_candle_index,
                        level_type_desc=f"STFL {qm.qm_type.value.upper()} QM",
                        is_inside_ftfl_box=True,
                        is_fresh=qm.state == LevelState.FRESH
                    ))

        # Check iAB levels inside box
        for ap in apexes:
            if ap.apex_type == target_iab_type:
                if ftfl_zone.box_bottom * 0.995 <= ap.price <= ftfl_zone.box_top * 1.005:
                    idx = ap.candle_index
                    box_top = max(highs[idx], highs[min(idx+1, len(df)-1)])
                    box_bottom = min(lows[idx], lows[min(idx+1, len(df)-1)])
                    valid_candidates.append(STFLZone(
                        timeframe=self.timeframe,
                        direction=ftfl_zone.direction,
                        price=ap.price,
                        box_top=box_top,
                        box_bottom=box_bottom,
                        time_formed=ap.candle_time,
                        candle_index=idx,
                        level_type_desc="STFL iAB Level",
                        is_inside_ftfl_box=True,
                        is_fresh=ap.state == LevelState.FRESH
                    ))

        # Check LS OCL levels inside box
        for ocl in ocls:
            if ocl.ocl_type == OCLType.LS_OCL:
                if ftfl_zone.box_bottom * 0.995 <= ocl.price <= ftfl_zone.box_top * 1.005:
                    valid_candidates.append(STFLZone(
                        timeframe=self.timeframe,
                        direction=ftfl_zone.direction,
                        price=ocl.price,
                        box_top=ocl.box_high,
                        box_bottom=ocl.box_low,
                        time_formed=ocl.candle_time,
                        candle_index=ocl.candle_index_1,
                        level_type_desc="STFL LS OCL Level",
                        is_inside_ftfl_box=True,
                        is_fresh=ocl.state == LevelState.FRESH
                    ))

        if valid_candidates:
            # Sort: 1) Freshness (fresh first), 2) Structural Hierarchy (S/R > QM > iAB > LS OCL), 3) Recency (latest candle)
            def rank_key(c: STFLZone):
                fresh_rank = 0 if c.is_fresh else 1
                desc = c.level_type_desc.upper()
                if "SUPPORT" in desc or "RESISTANCE" in desc:
                    struct_rank = 1
                elif "ABQM" in desc or "FTQM" in desc:
                    struct_rank = 2
                elif "QM" in desc:
                    struct_rank = 3
                elif "IAB" in desc:
                    struct_rank = 4
                elif "LS OCL" in desc:
                    struct_rank = 5
                else:
                    struct_rank = 6
                return (fresh_rank, struct_rank, -c.candle_index)

            valid_candidates.sort(key=rank_key)
            return valid_candidates[0]

        # 3. No valid STFL inside the FTFL box -> return None (Video 7 discipline:
        # "do not force a trade ... let it go"). Any outside-box fallback would
        # manufacture low-quality entries the strategy explicitly forbids.
        # The caller (_build_cascade_entry) skips cascades without STFL confirmation.
        return None
