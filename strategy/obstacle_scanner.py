"""
obstacle_scanner.py — MSNR Obstacle & Take-Profit Target Scanner

Rules (from Advanced MSNR, Videos 10, 11):
  - Obstacles are key levels that can prevent price from reaching full TP:
      - Swing Highs / Lows
      - Apex Resistance / Support
      - Internal Apex Break (IAB) levels
      - RBS / SBR levels
  - TIMEFRAME MATCHING RULE (Crucial):
      - Obstacles must be evaluated on the SAME TIMEFRAME AS THE TRADE ORIGIN.
      - Daily trade -> Scan Daily obstacles ONLY.
      - Weekly trade -> Scan Weekly obstacles ONLY.
  - Trade Management at Obstacles:
      - Take 80% partial profit at major intermediate obstacles.
      - Move SL to Break-Even.
      - Allow remaining 20% to run to final Draw on Liquidity (Major Swing High/Low).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
import pandas as pd

from indicators.candle_analyzer import CandleAnalyzer, LevelType, LevelState
from indicators.apex_detector import ApexDetector, ApexType
from strategy.storyline_engine import BiasDirection


class ObstacleType(Enum):
    SWING_HIGH_LOW = "SWING_HIGH_LOW"
    APEX = "APEX"
    IAB = "IAB"
    ROLE_REVERSAL = "ROLE_REVERSAL"


@dataclass
class ObstacleTarget:
    """Represents a potential obstacle or Take-Profit level."""
    price: float
    obstacle_type: ObstacleType
    timeframe: str
    description: str
    is_final_tp: bool = False
    recommended_action: str = "TAKE_80_PERCENT_PARTIAL"

    def __repr__(self) -> str:
        tag = "FINAL TP" if self.is_final_tp else "OBSTACLE"
        return f"ObstacleTarget({tag} @ {self.price:.2f} [{self.obstacle_type.value}] -> {self.recommended_action})"


class ObstacleScanner:
    """
    Scans for obstacles and Draw on Liquidity targets on the originating timeframe.
    """

    def __init__(self, df: pd.DataFrame, timeframe: str = "D1"):
        self.df = df.copy()
        self.timeframe = timeframe.upper()

    def scan_targets(
        self,
        entry_price: float,
        direction: BiasDirection
    ) -> List[ObstacleTarget]:
        """
        Scans all obstacles in the trade direction from entry_price to final TP.
        """
        df = self.df
        is_bullish = direction == BiasDirection.BULLISH
        targets: List[ObstacleTarget] = []

        if len(df) < 10:
            return targets

        # 1. Base S/R and SBR/RBS
        analyzer = CandleAnalyzer(df)
        base_levels = analyzer.detect_all()

        # 2. Apex / IAB levels
        apex_det = ApexDetector(df, timeframe=self.timeframe)
        apexes = apex_det.detect_all()

        # Collect potential barrier levels in the trade direction
        if is_bullish:
            # Look for resistance obstacles ABOVE entry price
            for sr in base_levels:
                if sr.price > entry_price and sr.level_type in (LevelType.RESISTANCE, LevelType.SBR):
                    targets.append(ObstacleTarget(
                        price=sr.price,
                        obstacle_type=ObstacleType.ROLE_REVERSAL if sr.level_type == LevelType.SBR else ObstacleType.SWING_HIGH_LOW,
                        timeframe=self.timeframe,
                        description=f"{self.timeframe} {sr.level_type.value.upper()}"
                    ))

            for apex in apexes:
                if apex.price > entry_price and "resistance" in apex.apex_type.value:
                    targets.append(ObstacleTarget(
                        price=apex.price,
                        obstacle_type=ObstacleType.APEX if apex.is_external else ObstacleType.IAB,
                        timeframe=self.timeframe,
                        description=f"{self.timeframe} {'EXTERNAL APEX' if apex.is_external else 'IAB'} RESISTANCE"
                    ))

            # Final TP = Highest swing high in recent history (Draw on Liquidity)
            recent_high = float(df["high"].tail(50).max())
            if recent_high > entry_price:
                targets.append(ObstacleTarget(
                    price=recent_high,
                    obstacle_type=ObstacleType.SWING_HIGH_LOW,
                    timeframe=self.timeframe,
                    description=f"{self.timeframe} Major Draw on Liquidity (Swing High)",
                    is_final_tp=True,
                    recommended_action="FULL_EXIT"
                ))

            # Sort ascending (closest obstacle first)
            targets.sort(key=lambda t: t.price)

        else:
            # Bearish: Look for support obstacles BELOW entry price
            for sr in base_levels:
                if sr.price < entry_price and sr.level_type in (LevelType.SUPPORT, LevelType.RBS):
                    targets.append(ObstacleTarget(
                        price=sr.price,
                        obstacle_type=ObstacleType.ROLE_REVERSAL if sr.level_type == LevelType.RBS else ObstacleType.SWING_HIGH_LOW,
                        timeframe=self.timeframe,
                        description=f"{self.timeframe} {sr.level_type.value.upper()}"
                    ))

            for apex in apexes:
                if apex.price < entry_price and "support" in apex.apex_type.value:
                    targets.append(ObstacleTarget(
                        price=apex.price,
                        obstacle_type=ObstacleType.APEX if apex.is_external else ObstacleType.IAB,
                        timeframe=self.timeframe,
                        description=f"{self.timeframe} {'EXTERNAL APEX' if apex.is_external else 'IAB'} SUPPORT"
                    ))

            # Final TP = Lowest swing low in recent history
            recent_low = float(df["low"].tail(50).min())
            if recent_low < entry_price:
                targets.append(ObstacleTarget(
                    price=recent_low,
                    obstacle_type=ObstacleType.SWING_HIGH_LOW,
                    timeframe=self.timeframe,
                    description=f"{self.timeframe} Major Draw on Liquidity (Swing Low)",
                    is_final_tp=True,
                    recommended_action="FULL_EXIT"
                ))

            # Sort descending (closest obstacle first)
            targets.sort(key=lambda t: t.price, reverse=True)

        return targets
