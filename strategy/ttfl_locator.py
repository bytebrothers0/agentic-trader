"""
ttfl_locator.py — MSNR Third Time Frame Level (TTFL) & Equilibrium Refinement Engine

Rules (from Advanced MSNR, Videos 8, 10, 11):
  - TTFL provides the ultimate refinement for tight Stop Loss and maximum Risk-to-Reward.
  - Step-down mapping:
      - Monthly FTFL -> Weekly STFL -> Daily (D1) TTFL
      - Weekly FTFL  -> Daily STFL  -> 4-Hour (H4) TTFL
      - Daily FTFL   -> 4-Hour STFL -> 1-Hour (H1) TTFL
  - Search inside the STFL Box for:
      - For Buys: Support, QM, or Equilibrium
      - For Sells: Resistance, QM, or Equilibrium
  - EQUILIBRIUM FALLBACK (Core Rule):
      - When no discrete Support/Resistance or QM exists inside the STFL box on the TTFL timeframe,
        use the EXACT EQUILIBRIUM (50% midpoint of the STFL box) as the entry level!
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import pandas as pd

from indicators.candle_analyzer import CandleAnalyzer, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.qm_detector import QMDetector, QMDirection
from strategy.storyline_engine import BiasDirection
from strategy.stfl_locator import STFLZone


class TTFLEntryType(Enum):
    KEY_LEVEL = "KEY_LEVEL"        # Exact Support/Resistance/QM on TTFL
    EQUILIBRIUM = "EQUILIBRIUM"    # 50% Midpoint of STFL Box


@dataclass
class TTFLRefinement:
    """Represents the final refined entry level and SL reference."""
    timeframe: str              # e.g., 'H1', 'H4'
    direction: BiasDirection    # BULLISH or BEARISH
    entry_price: float          # The exact limit entry price
    sl_reference: float         # Level boundary for SL placement
    entry_type: TTFLEntryType   # KEY_LEVEL or EQUILIBRIUM
    description: str
    is_fresh: bool = True

    def __repr__(self) -> str:
        return (
            f"TTFLRefinement({self.timeframe} {self.direction.value} @ {self.entry_price:.2f} | "
            f"SL Ref: {self.sl_reference:.2f} | {self.entry_type.value} [{self.description}])"
        )


class TTFLLocator:
    """
    Locates the ultimate entry level on the TTFL timeframe with Equilibrium fallback.
    """

    def __init__(self, df_ttfl: pd.DataFrame, ttfl_timeframe: str = "H1"):
        self.df = df_ttfl.copy()
        self.timeframe = ttfl_timeframe.upper()

    def refine(self, stfl_zone: STFLZone) -> TTFLRefinement:
        """
        Refines the STFL zone down to the exact TTFL entry level or Equilibrium.
        """
        df = self.df
        is_bullish = stfl_zone.direction == BiasDirection.BULLISH

        if len(df) < 5:
            # Fallback to STFL equilibrium if insufficient TTFL bars
            return self._create_equilibrium_refinement(stfl_zone)

        analyzer = CandleAnalyzer(df)
        sr_levels = analyzer.detect_all()
        tracker = FreshnessTracker(df)
        sr_levels = tracker.update(sr_levels)

        qm_det = QMDetector(df, sr_levels)
        qms = qm_det.detect_all()

        target_sr_type = LevelType.SUPPORT if is_bullish else LevelType.RESISTANCE
        target_qm_dir = QMDirection.BULLISH if is_bullish else QMDirection.BEARISH

        # 1. Search for S/R inside the STFL box
        for sr in sr_levels:
            if sr.level_type == target_sr_type:
                if stfl_zone.box_bottom * 0.998 <= sr.price <= stfl_zone.box_top * 1.002:
                    sl_ref = stfl_zone.box_bottom if is_bullish else stfl_zone.box_top
                    return TTFLRefinement(
                        timeframe=self.timeframe,
                        direction=stfl_zone.direction,
                        entry_price=sr.price,
                        sl_reference=sl_ref,
                        entry_type=TTFLEntryType.KEY_LEVEL,
                        description=f"TTFL {sr.level_type.value.upper()}",
                        is_fresh=sr.state == LevelState.FRESH
                    )

        # 2. Search for QM inside the STFL box
        for qm in qms:
            if qm.direction == target_qm_dir:
                if stfl_zone.box_bottom * 0.998 <= qm.price <= stfl_zone.box_top * 1.002:
                    sl_ref = stfl_zone.box_bottom if is_bullish else stfl_zone.box_top
                    return TTFLRefinement(
                        timeframe=self.timeframe,
                        direction=stfl_zone.direction,
                        entry_price=qm.price,
                        sl_reference=sl_ref,
                        entry_type=TTFLEntryType.KEY_LEVEL,
                        description=f"TTFL {qm.qm_type.value.upper()} QM",
                        is_fresh=qm.state == LevelState.FRESH
                    )

        # 3. Fallback: No discrete key level -> Use Equilibrium (50% midpoint)
        return self._create_equilibrium_refinement(stfl_zone)

    def _create_equilibrium_refinement(self, stfl_zone: STFLZone) -> TTFLRefinement:
        is_bullish = stfl_zone.direction == BiasDirection.BULLISH
        eq_price = stfl_zone.equilibrium
        sl_ref = stfl_zone.box_bottom if is_bullish else stfl_zone.box_top

        return TTFLRefinement(
            timeframe=self.timeframe,
            direction=stfl_zone.direction,
            entry_price=eq_price,
            sl_reference=sl_ref,
            entry_type=TTFLEntryType.EQUILIBRIUM,
            description="STFL Box Equilibrium (50% Midpoint)",
            is_fresh=True
        )
