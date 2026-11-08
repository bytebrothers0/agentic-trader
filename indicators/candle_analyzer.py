"""
candle_analyzer.py — MSNR Foundation Indicator
Detects: Support, Resistance, SBR (Support-Becomes-Resistance),
         RBS (Resistance-Becomes-Support).

Rules (web Alchemist MSNR):
  - S/R is defined by the CLOSE of the body, NOT wicks.
  - Support  = bearish candle immediately followed by a bullish candle (V).
  - Resistance = bullish candle immediately followed by a bearish candle (A).
  - GAP SNR: opposite pair whose second open is displaced from the first
    close by more than 0.1 local ATR. Gap levels are hidden zones — trendlines
    must never connect them; they refine into LTF engulfing zones instead.
  - SBR: a prior support whose BODY closes BELOW → flips to resistance,
    fresh in the new role. RBS: mirror.
  - Web flip rule (MALIYA): "once broken with a body" — any body close
    through flips, no displacement qualifier.
  - A level may be used at most TWICE (fresh use + unfresh use); track
    touch_count and retire at 2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# Ignore feed/rounding mismatches when classifying a candle-open discontinuity
# as a real gap. This matches the trendline detector's 0.1 ATR gap threshold.
_GAP_ATR_MULT = 0.1


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class LevelType(Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    SBR = "sbr"            # Support-Becomes-Resistance
    RBS = "rbs"            # Resistance-Becomes-Support


class LevelState(Enum):
    FRESH = "fresh"
    UNFRESH = "unfresh"    # touched by wick
    BROKEN = "broken"      # body-closed through (triggers role reversal)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CandleLevel:
    """A single key level detected on the chart."""
    level_type: LevelType
    price: float                # the exact level price (body close)
    candle_index: int           # iloc of the candle that formed this level
    candle_time: pd.Timestamp
    state: LevelState = LevelState.FRESH

    # Gap flag: a meaningful open/previous-close discontinuity marks hidden SNR.
    is_gap: bool = False
    # Web 2-use rule: wick touches consumed (fresh use + unfresh use max).
    touch_count: int = 0

    # Candles involved in forming this level
    forming_candle_indices: List[int] = field(default_factory=list)

    # For SBR/RBS — reference to the original level it derived from
    derived_from: Optional["CandleLevel"] = field(default=None, repr=False)

    # Set after freshness tracking
    first_touch_index: Optional[int] = None
    break_candle_index: Optional[int] = None

    def __repr__(self) -> str:
        return (
            f"CandleLevel({self.level_type.value} @ {self.price:.5f} "
            f"[{self.candle_time.date()}] state={self.state.value})"
        )


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------

class CandleAnalyzer:
    """
    Identifies Support and Resistance levels from OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close, volume.
        Index must be a DatetimeIndex.
    """

    def __init__(self, df: pd.DataFrame):
        self._validate(df)
        self.df = df.copy()
        self._levels: List[CandleLevel] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_all(self) -> List[CandleLevel]:
        """Run full detection pipeline: S/R → SBR/RBS."""
        self._levels = []
        self._detect_sr()
        self._detect_role_reversals()
        return self._levels

    def get_supports(self, fresh_only: bool = False) -> List[CandleLevel]:
        return self._filter(LevelType.SUPPORT, fresh_only)

    def get_resistances(self, fresh_only: bool = False) -> List[CandleLevel]:
        return self._filter(LevelType.RESISTANCE, fresh_only)

    def get_sbr(self, fresh_only: bool = False) -> List[CandleLevel]:
        return self._filter(LevelType.SBR, fresh_only)

    def get_rbs(self, fresh_only: bool = False) -> List[CandleLevel]:
        return self._filter(LevelType.RBS, fresh_only)

    @property
    def levels(self) -> List[CandleLevel]:
        return self._levels

    # ------------------------------------------------------------------
    # Detection: Support & Resistance
    # ------------------------------------------------------------------

    def _detect_sr(self):
        """
        Support: candle[i] is bearish AND candle[i+1] is bullish.
            Level price = close of candle[i]  (the bearish candle close).

        Resistance: candle[i] is bullish AND candle[i+1] is bearish.
            Level price = close of candle[i]  (the bullish candle close).
        """
        df = self.df
        closes = df["close"].values
        opens = df["open"].values
        times = df.index
        prev_close = df["close"].shift(1)
        true_range = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.ewm(
            alpha=1.0 / 14.0, min_periods=1, adjust=False
        ).mean().values

        for i in range(len(df) - 1):
            c0_bearish = closes[i] < opens[i]   # candle i is bearish
            c0_bullish = closes[i] > opens[i]   # candle i is bullish
            c1_bearish = closes[i+1] < opens[i+1]
            c1_bullish = closes[i+1] > opens[i+1]
            # A tiny open/close difference is normal feed noise on MT5. Only
            # classify a gap when the discontinuity exceeds 0.1 local ATR.
            is_gap = bool(
                abs(opens[i + 1] - closes[i]) > _GAP_ATR_MULT * atr[i + 1]
            )

            if c0_bearish and c1_bullish:
                # Support formed
                self._levels.append(CandleLevel(
                    level_type=LevelType.SUPPORT,
                    price=closes[i],
                    candle_index=i,
                    candle_time=times[i],
                    is_gap=is_gap,
                    forming_candle_indices=[i, i + 1],
                ))

            elif c0_bullish and c1_bearish:
                # Resistance formed
                self._levels.append(CandleLevel(
                    level_type=LevelType.RESISTANCE,
                    price=closes[i],
                    candle_index=i,
                    candle_time=times[i],
                    is_gap=is_gap,
                    forming_candle_indices=[i, i + 1],
                ))

    # ------------------------------------------------------------------
    # Detection: Role Reversals (SBR & RBS)
    # ------------------------------------------------------------------

    def _detect_role_reversals(self):
        """
        Scan every candle AFTER a level is formed to see if it
        body-closes through that level, triggering a role reversal.

        SBR: support level → candle body-closes BELOW → becomes resistance.
        RBS: resistance level → candle body-closes ABOVE → becomes support.

        The new level price = the original S/R price (unchanged).
        Only the most recent body-close through a level creates the role reversal.
        """
        df = self.df
        closes = df["close"].values
        opens = df["open"].values
        times = df.index

        sr_levels = [
            lv for lv in self._levels
            if lv.level_type in (LevelType.SUPPORT, LevelType.RESISTANCE)
        ]

        new_levels: List[CandleLevel] = []

        for lv in sr_levels:
            start_i = lv.candle_index + 2   # scan from candle after formation

            for i in range(start_i, len(df)):
                if lv.level_type == LevelType.SUPPORT:
                    # Body-close BELOW support → SBR (close-through is definitive)
                    if closes[i] < lv.price:
                        lv.state = LevelState.BROKEN
                        lv.break_candle_index = i
                        new_levels.append(CandleLevel(
                            level_type=LevelType.SBR,
                            price=lv.price,
                            candle_index=i,
                            candle_time=times[i],
                            forming_candle_indices=[i],
                            derived_from=lv,
                            state=LevelState.FRESH,
                        ))
                        break  # one reversal per level

                elif lv.level_type == LevelType.RESISTANCE:
                    # Body-close ABOVE resistance → RBS (close-through is definitive)
                    if closes[i] > lv.price:
                        lv.state = LevelState.BROKEN
                        lv.break_candle_index = i
                        new_levels.append(CandleLevel(
                            level_type=LevelType.RBS,
                            price=lv.price,
                            candle_index=i,
                            candle_time=times[i],
                            forming_candle_indices=[i],
                            derived_from=lv,
                            state=LevelState.FRESH,
                        ))
                        break

        self._levels.extend(new_levels)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _filter(self, level_type: LevelType, fresh_only: bool) -> List[CandleLevel]:
        result = [lv for lv in self._levels if lv.level_type == level_type]
        if fresh_only:
            result = [lv for lv in result if lv.state == LevelState.FRESH]
        return result

    @staticmethod
    def _validate(df: pd.DataFrame):
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame index must be a DatetimeIndex.")
        if df.empty:
            raise ValueError("DataFrame is empty.")


# ---------------------------------------------------------------------------
# Utility: is candle bullish / bearish
# ---------------------------------------------------------------------------

def is_bullish(row: pd.Series) -> bool:
    return row["close"] > row["open"]


def is_bearish(row: pd.Series) -> bool:
    return row["close"] < row["open"]


def candle_body_high(row: pd.Series) -> float:
    return max(row["open"], row["close"])


def candle_body_low(row: pd.Series) -> float:
    return min(row["open"], row["close"])


def candle_body_size(row: pd.Series) -> float:
    return abs(row["close"] - row["open"])
