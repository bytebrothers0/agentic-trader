"""
ocl_detector.py — MSNR Open Close Level (OCL) Indicator

Rules (from Advanced MSNR, Videos 2, 5, 8, 10, 11):
  - OCL is ONLY valid on Higher Timeframes (Monthly, Weekly, Daily). Not 4H or lower.
  - Base OCL = Two consecutive candles of the SAME color (2 bullish or 2 bearish).
  - Level price = CLOSE of the FIRST candle.
  - INVALID / Disqualified: Engulfing OCLs (where 2nd candle completely engulfs the 1st candle).

Subtypes:
  1. sOCL (Support OCL): Closest OCL to a newly formed Support.
     - The bullish candle that completes the support must engulf the two bearish OCL candles.
  2. rOCL (Resistance OCL): Closest OCL to a newly formed Resistance.
     - The bearish candle that completes the resistance must engulf the two bullish OCL candles.
  3. 1-Lap OCL (One-Lap OCL): Standalone OCL where the next key level above/below is another OCL (not S/R).
     - Strongest standalone OCL type.
  4. LS OCL (Left-Side OCL): An OCL broken twice (first as support, then as resistance, or vice versa).
     - Acts as a QM on the 3rd approach. Most powerful on Weekly/Daily.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import pandas as pd

from indicators.candle_analyzer import CandleLevel, LevelState, is_bullish, is_bearish


class OCLType(Enum):
    STANDARD_BULLISH = "ocl_bullish"  # 2 bullish candles
    STANDARD_BEARISH = "ocl_bearish"  # 2 bearish candles
    SOCL = "socl"                      # Support OCL (engulfed by support candle)
    ROCL = "rocl"                      # Resistance OCL (engulfed by resistance candle)
    ONE_LAP = "one_lap_ocl"            # 1-Lap OCL (isolated from immediate S/R)
    LS_OCL = "ls_ocl"                  # Left-side OCL (broken twice)


@dataclass
class OCLLevel:
    """Represents a detected Open Close Level."""
    ocl_type: OCLType
    price: float                # Close of the 1st candle in the pair
    candle_index_1: int         # iloc of 1st candle
    candle_index_2: int         # iloc of 2nd candle
    candle_time: pd.Timestamp
    state: LevelState = LevelState.FRESH

    # Wick box bounds (for FTFL box: body close to tip of wick, 1 step right)
    box_high: float = 0.0
    box_low: float = 0.0

    # Subtype metadata
    first_touch_index: Optional[int] = None
    break_count: int = 0        # For LS OCL tracking (breaks through this level)
    forming_candle_indices: List[int] = field(default_factory=list)
    # Direction of the base 2-candle formation (True = 2 bullish, False = 2 bearish).
    # Preserved through ONE_LAP / LS_OCL upgrades so polarity survives reclassification.
    is_bullish_base: Optional[bool] = None
    # Life-cycle end for zone-to-zone chart rays: iloc of the first wick touch
    # (mitigation). OCLs never go BROKEN here — repeated close-throughs are
    # tracked as break_count -> LS OCL instead of role-flips.
    end_candle_index: Optional[int] = None
    end_kind: str = "active"    # "active" | "mitigated"
    # iloc from which touch-freshness is evaluated. For LS OCL this is just
    # after the 2nd break (the pattern completes there — earlier touches are
    # the breaks themselves, not mitigations of the trade zone).
    touch_scan_from: Optional[int] = None

    def to_candle_level(self) -> CandleLevel:
        """Adapter to CandleLevel format for unified processing."""
        from indicators.candle_analyzer import LevelType
        # Per Video 2: bullish OCL (2 bullish, level below price action) acts as
        # support on pullback; bearish OCL acts as resistance on rally.
        # sOCL is bullish -> SUPPORT; rOCL is bearish -> RESISTANCE.
        if self.ocl_type == OCLType.SOCL:
            is_support_like = True
        elif self.ocl_type == OCLType.ROCL:
            is_support_like = False
        elif self.is_bullish_base is not None:
            is_support_like = self.is_bullish_base
        else:
            # Legacy fallback (pre-polarity levels): bullish standards are support-like.
            is_support_like = self.ocl_type in (OCLType.STANDARD_BULLISH, OCLType.ONE_LAP, OCLType.LS_OCL)
        lvl_type = LevelType.SUPPORT if is_support_like else LevelType.RESISTANCE
        
        lvl = CandleLevel(
            level_type=lvl_type,
            price=self.price,
            candle_index=self.candle_index_1,
            candle_time=self.candle_time,
            state=self.state,
            forming_candle_indices=self.forming_candle_indices,
            first_touch_index=self.first_touch_index
        )
        return lvl

    def __repr__(self) -> str:
        return (
            f"OCLLevel({self.ocl_type.value} @ {self.price:.5f} "
            f"[{self.candle_time.date()}] state={self.state.value})"
        )


class OCLDetector:
    """
    Detects and categorizes Open Close Levels (OCLs) from HTF OHLCV data.
    """

    def __init__(self, df: pd.DataFrame, timeframe: str = "D1"):
        self.df = df.copy()
        self.timeframe = timeframe.upper()
        self._levels: List[OCLLevel] = []

    def detect_all(self, base_sr_levels: Optional[List] = None) -> List[OCLLevel]:
        """Detect all valid OCLs on this timeframe."""
        self._levels = []
        # OCL is strictly HTF only (Monthly/Weekly/Daily). M1 = 1-minute, excluded.
        if self.timeframe not in {"MN", "MN1", "W1", "D1", "MONTHLY", "WEEKLY", "DAILY"}:
            return []

        self._detect_base_ocls()
        self._classify_socl_rocl(base_sr_levels)
        self._classify_one_lap_and_ls()
        self._apply_touch_freshness()
        return self._levels

    def _apply_touch_freshness(self):
        """
        Video 4 freshness for OCLs: first wick touch -> UNFRESH (mitigated),
        recording the touch bar for zone-to-zone chart rays. Never BROKEN:
        OCLs don't role-flip; repeated close-throughs upgrade to LS OCL.
        """
        df = self.df
        if len(df) == 0:
            return
        highs = df["high"].values
        lows = df["low"].values
        for lvl in self._levels:
            start_i = lvl.touch_scan_from if lvl.touch_scan_from is not None else lvl.candle_index_2 + 1
            for i in range(start_i, len(df)):
                if lvl.is_bullish_base is True:
                    touched = lows[i] <= lvl.price
                elif lvl.is_bullish_base is False:
                    touched = highs[i] >= lvl.price
                else:
                    touched = lows[i] <= lvl.price or highs[i] >= lvl.price
                if touched:
                    lvl.state = LevelState.UNFRESH
                    lvl.first_touch_index = i
                    lvl.end_candle_index = i
                    lvl.end_kind = "mitigated"
                    break

    def _detect_base_ocls(self):
        df = self.df
        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        times = df.index

        for i in range(len(df) - 1):
            c1_bullish = closes[i] > opens[i]
            c1_bearish = closes[i] < opens[i]
            c2_bullish = closes[i+1] > opens[i+1]
            c2_bearish = closes[i+1] < opens[i+1]

            # 1. Check if both are same color
            if not ((c1_bullish and c2_bullish) or (c1_bearish and c2_bearish)):
                continue

            # 2. Check Engulfing Disqualification (Video 2):
            # If 2nd candle body or range completely engulfs the 1st candle, it is disqualified!
            c1_body_high = max(opens[i], closes[i])
            c1_body_low = min(opens[i], closes[i])
            c2_body_high = max(opens[i+1], closes[i+1])
            c2_body_low = min(opens[i+1], closes[i+1])

            is_body_engulfing = (c2_body_high >= c1_body_high) and (c2_body_low <= c1_body_low)
            is_range_engulfing = (highs[i+1] >= highs[i]) and (lows[i+1] <= lows[i])
            if is_body_engulfing or is_range_engulfing:
                continue

            # Valid Base OCL found
            price = closes[i]  # Close of 1st candle
            ocl_type = OCLType.STANDARD_BULLISH if c1_bullish else OCLType.STANDARD_BEARISH

            # Box bounds: from body close of 1st candle to highest/lowest wick of the two
            box_high = max(highs[i], highs[i+1])
            box_low = min(lows[i], lows[i+1])

            self._levels.append(OCLLevel(
                ocl_type=ocl_type,
                price=price,
                candle_index_1=i,
                candle_index_2=i+1,
                candle_time=times[i],
                box_high=box_high,
                box_low=box_low,
                forming_candle_indices=[i, i+1],
                is_bullish_base=c1_bullish,
            ))

    def _classify_socl_rocl(self, base_sr_levels: Optional[List] = None):
        """
        Classify Support OCL (sOCL) and Resistance OCL (rOCL) per Video 2
        (web-exact engulf rule, not proximity):

        sOCL = two consecutive BEARISH candles (a bearish OCL pair)
        engulfed by the BULLISH candle that completes a Support
        (bearish[i+1] -> bullish[i+2] V-shape).
        rOCL = mirror: bullish pair engulfed by the bearish candle
        completing a Resistance.
        """
        df = self.df
        closes = df["close"].values
        opens = df["open"].values

        def _pair_extremes(i: int) -> tuple:
            top = max(max(opens[i], closes[i]), max(opens[i + 1], closes[i + 1]))
            bot = min(min(opens[i], closes[i]), min(opens[i + 1], closes[i + 1]))
            return top, bot

        def _engulfed_by(i: int, j: int) -> bool:
            """Candle j's body engulfs the [i, i+1] pair bodies."""
            top, bot = _pair_extremes(i)
            jtop, jbot = max(opens[j], closes[j]), min(opens[j], closes[j])
            return (jtop >= top and jbot <= bot
                    and (jtop > top or jbot < bot))

        for lvl in self._levels:
            i = lvl.candle_index_1
            if i + 2 >= len(df):
                continue
            # sOCL: bearish pair + bullish support-completer engulfing it.
            if lvl.ocl_type == OCLType.STANDARD_BEARISH:
                if closes[i + 2] > opens[i + 2] and _engulfed_by(i, i + 2):
                    lvl.ocl_type = OCLType.SOCL
                    continue
            # rOCL: bullish pair + bearish resistance-completer engulfing it.
            if lvl.ocl_type == OCLType.STANDARD_BULLISH:
                if closes[i + 2] < opens[i + 2] and _engulfed_by(i, i + 2):
                    lvl.ocl_type = OCLType.ROCL
                    continue

    def _classify_one_lap_and_ls(self):
        """
        Identify 1-Lap OCLs and track Left-Side (LS) OCL break counts.
        GAP 5: Enforce 1-LAB OCL rule (Video 2):
        - For bearish OCL: next level above must be another OCL (not S/R).
        - For bullish OCL: next level below must be another OCL (not S/R).
        """
        df = self.df
        closes = df["close"].values
        opens = df["open"].values

        # Detect S/R levels on this dataframe for neighbor validation
        from indicators.candle_analyzer import CandleAnalyzer
        analyzer = CandleAnalyzer(df)
        sr_levels = analyzer.detect_all()

        for lvl in self._levels:
            # Track breaks through this level price (close-through, consistent
            # with FreshnessTracker / CandleAnalyzer role-reversal semantics).
            start_i = lvl.candle_index_2 + 1
            breaks = 0
            second_break_idx: Optional[int] = None
            current_side = "above" if closes[lvl.candle_index_1] > opens[lvl.candle_index_1] else "below"

            for i in range(start_i, len(df)):
                if current_side == "above" and closes[i] < lvl.price:
                    breaks += 1
                    current_side = "below"
                    if breaks == 2:
                        second_break_idx = i
                elif current_side == "below" and closes[i] > lvl.price:
                    breaks += 1
                    current_side = "above"
                    if breaks == 2:
                        second_break_idx = i

            lvl.break_count = breaks
            if breaks >= 2:
                # Broken twice -> LS OCL (acts as QM on 3rd approach)
                lvl.ocl_type = OCLType.LS_OCL
                if second_break_idx is not None:
                    lvl.touch_scan_from = second_break_idx + 1
            elif lvl.ocl_type in (OCLType.STANDARD_BULLISH, OCLType.STANDARD_BEARISH) and breaks == 0:
                # GAP 5: Validate 1-LAB OCL condition (web-exact: next level
                # in price-space is another OCL, forward or backward).
                # Find the closest key level in the reference direction.
                is_bullish_ocl = (lvl.ocl_type == OCLType.STANDARD_BULLISH)
                other_ocls = [o for o in self._levels if o != lvl]

                if is_bullish_ocl:
                    # Look below for closest key level (any position)
                    sr_below = [s for s in sr_levels if s.price < lvl.price]
                    ocl_below = [o for o in other_ocls if o.price < lvl.price]
                    nearest_sr = max([s.price for s in sr_below], default=-float('inf'))
                    nearest_ocl = max([o.price for o in ocl_below], default=-float('inf'))
                    # If nearest level below is another OCL (closer than any S/R), it's a 1-LAB OCL
                    if nearest_ocl > nearest_sr:
                        lvl.ocl_type = OCLType.ONE_LAP
                else:
                    # Look above for closest key level (any position)
                    sr_above = [s for s in sr_levels if s.price > lvl.price]
                    ocl_above = [o for o in other_ocls if o.price > lvl.price]
                    nearest_sr = min([s.price for s in sr_above], default=float('inf'))
                    nearest_ocl = min([o.price for o in ocl_above], default=float('inf'))
                    # If nearest level above is another OCL (closer than any S/R), it's a 1-LAB OCL
                    if nearest_ocl < nearest_sr:
                        lvl.ocl_type = OCLType.ONE_LAP
