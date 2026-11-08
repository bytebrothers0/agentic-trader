"""
apex_detector.py — MSNR Line Chart Apex & IAB Indicator

Rules (from Advanced MSNR, Videos 1, 4, 7, 10, 11):
  - Apex and IAB levels are strictly evaluated using a LINE CHART (close prices only).
  - Evaluated independently on whichever timeframe is supplied.
  - Apex Support: Major external swing low on line chart that led to an upward structural breakout.
  - Apex Resistance: Major external swing high on line chart that led to a downward structural breakout.
  - IAB Support (Internal Apex Break): Minor/internal swing low that caused a structural breakout.
  - IAB Resistance: Minor/internal swing high that caused a structural breakout.
  - Disqualification: Any swing point that did NOT lead to a structural breakout is FALSE/INVALID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from indicators.candle_analyzer import CandleLevel, LevelType, LevelState


class ApexType(Enum):
    APEX_SUPPORT = "apex_support"
    APEX_RESISTANCE = "apex_resistance"
    IAB_SUPPORT = "iab_support"
    IAB_RESISTANCE = "iab_resistance"


@dataclass
class ApexLevel:
    """Represents a validated Line-Chart Apex or IAB key level."""
    apex_type: ApexType
    price: float                # Exact Close price at the apex
    candle_index: int           # Index where the swing apex formed
    breakout_candle_index: int  # Index of candle where structural breakout was confirmed
    candle_time: pd.Timestamp
    is_external: bool = True    # True = Major External Apex, False = Internal (IAB)
    state: LevelState = LevelState.FRESH

    forming_candle_indices: List[int] = field(default_factory=list)
    first_touch_index: Optional[int] = None
    # Life-cycle end for zone-to-zone chart rays (see QMLevel for semantics).
    end_candle_index: Optional[int] = None
    end_kind: str = "active"    # "active" | "mitigated" | "broken"

    def to_candle_level(self) -> CandleLevel:
        """Adapter to CandleLevel format."""
        is_sup = self.apex_type in (ApexType.APEX_SUPPORT, ApexType.IAB_SUPPORT)
        lvl_type = LevelType.SUPPORT if is_sup else LevelType.RESISTANCE
        return CandleLevel(
            level_type=lvl_type,
            price=self.price,
            candle_index=self.candle_index,
            candle_time=self.candle_time,
            state=self.state,
            forming_candle_indices=self.forming_candle_indices,
            first_touch_index=self.first_touch_index
        )

    def __repr__(self) -> str:
        tag = "EXTERNAL APEX" if self.is_external else "IAB"
        return (
            f"ApexLevel({tag} {self.apex_type.value} @ {self.price:.5f} "
            f"[{self.candle_time.date()}] state={self.state.value})"
        )


class ApexDetector:
    """
    Detects Apex and IAB levels on Line Charts (Close Prices).
    """

    # Swing separation tuned per timeframe: sparse HTF (MN1: 24 bars) needs a
    # short window, dense D1 (365 bars) needs a wider one to isolate structure.
    _MIN_DISTANCE_BY_TF = {"MN1": 2, "MN": 2, "MONTHLY": 2, "W1": 3, "WEEKLY": 3, "D1": 5, "DAILY": 5}

    def __init__(self, df: pd.DataFrame, timeframe: str = "D1", min_distance: Optional[int] = None):
        self.df = df.copy()
        self.timeframe = timeframe.upper()
        if min_distance is None:
            min_distance = self._MIN_DISTANCE_BY_TF.get(self.timeframe, 3)
        self.min_distance = min_distance
        self._levels: List[ApexLevel] = []

    def detect_all(self) -> List[ApexLevel]:
        """Detect all verified Apex and IAB swing levels (with freshness states applied)."""
        self._levels = []
        df = self.df
        closes = df["close"].values
        times = df.index

        if len(closes) < 10:
            return []

        # 1. Find line-chart peaks (high swings) and valleys (low swings)
        peaks, _ = find_peaks(closes, distance=self.min_distance)
        valleys, _ = find_peaks(-closes, distance=self.min_distance)

        # 2. Validate Resistance Apexes (Highs that led to a structural break downward)
        for p_idx in peaks:
            price = closes[p_idx]
            # Check if after this peak, price broke below prior swing low (structural breakout)
            has_breakout, break_idx, is_external = self._verify_resistance_breakout(p_idx, valleys, closes)
            if has_breakout:
                apex_type = ApexType.APEX_RESISTANCE if is_external else ApexType.IAB_RESISTANCE
                self._levels.append(ApexLevel(
                    apex_type=apex_type,
                    price=price,
                    candle_index=int(p_idx),
                    breakout_candle_index=int(break_idx),
                    candle_time=times[p_idx],
                    is_external=is_external,
                    forming_candle_indices=[int(p_idx), int(break_idx)]
                ))

        # 3. Validate Support Apexes (Lows that led to a structural break upward)
        for v_idx in valleys:
            price = closes[v_idx]
            # Check if after this valley, price broke above prior swing high
            has_breakout, break_idx, is_external = self._verify_support_breakout(v_idx, peaks, closes)
            if has_breakout:
                apex_type = ApexType.APEX_SUPPORT if is_external else ApexType.IAB_SUPPORT
                self._levels.append(ApexLevel(
                    apex_type=apex_type,
                    price=price,
                    candle_index=int(v_idx),
                    breakout_candle_index=int(break_idx),
                    candle_time=times[v_idx],
                    is_external=is_external,
                    forming_candle_indices=[int(v_idx), int(break_idx)]
                ))

        # 4. Freshness (Video 4 rule applies to Apex too): a wick touch after
        # formation mitigates the level (UNFRESH); a body close-through breaks it
        # (BROKEN). Scan from the swing candle onward on candle wicks/closes.
        self._apply_freshness()
        return self._levels

    def _apply_freshness(self):
        """Mark Apex/IAB levels UNFRESH on wick touch / BROKEN on close-through."""
        df = self.df
        if len(df) == 0:
            return
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        for ap in self._levels:
            is_support = ap.apex_type in (ApexType.APEX_SUPPORT, ApexType.IAB_SUPPORT)
            start_i = int(ap.candle_index) + 1
            for i in range(start_i, len(df)):
                if is_support:
                    if closes[i] < ap.price:
                        ap.state = LevelState.BROKEN
                        ap.end_candle_index = i
                        ap.end_kind = "broken"
                        break
                    if ap.state == LevelState.FRESH and lows[i] <= ap.price:
                        ap.state = LevelState.UNFRESH
                        ap.first_touch_index = i
                        ap.end_candle_index = i
                        ap.end_kind = "mitigated"
                else:
                    if closes[i] > ap.price:
                        ap.state = LevelState.BROKEN
                        ap.end_candle_index = i
                        ap.end_kind = "broken"
                        break
                    if ap.state == LevelState.FRESH and highs[i] >= ap.price:
                        ap.state = LevelState.UNFRESH
                        ap.first_touch_index = i
                        ap.end_candle_index = i
                        ap.end_kind = "mitigated"

    def _verify_resistance_breakout(self, peak_idx: int, valleys: np.ndarray, closes: np.ndarray):
        """Verify if a peak resulted in a downward breakout below previous valleys."""
        prior_valleys = valleys[valleys < peak_idx]
        if len(prior_valleys) == 0:
            return False, -1, False

        # Most recent valley before this peak
        target_low = closes[prior_valleys[-1]]
        
        # Scan forward from peak_idx to see if price closes below target_low
        for i in range(peak_idx + 1, len(closes)):
            if closes[i] < target_low:
                # Breakout confirmed! Check if major external swing
                is_external = len(prior_valleys) >= 2 and target_low == min(closes[prior_valleys])
                return True, i, is_external
            # If price exceeds the peak before breaking low, this peak failed to cause breakout
            if closes[i] > closes[peak_idx]:
                break

        return False, -1, False

    def _verify_support_breakout(self, valley_idx: int, peaks: np.ndarray, closes: np.ndarray):
        """Verify if a valley resulted in an upward breakout above previous peaks."""
        prior_peaks = peaks[peaks < valley_idx]
        if len(prior_peaks) == 0:
            return False, -1, False

        # Most recent peak before this valley
        target_high = closes[prior_peaks[-1]]

        # Scan forward from valley_idx to see if price closes above target_high
        for i in range(valley_idx + 1, len(closes)):
            if closes[i] > target_high:
                # Breakout confirmed! Check if major external swing
                is_external = len(prior_peaks) >= 2 and target_high == max(closes[prior_peaks])
                return True, i, is_external
            if closes[i] < closes[valley_idx]:
                break

        return False, -1, False
