"""
storyline_engine.py — Advanced MSNR Storyline (Directional Bias) Engine

Rules (from Advanced MSNR, Videos 4, 8, 10, 11):
  Formula 1: X rejects X and Y breakout (Standard Multi-Timeframe Storyline)
    - X = {Monthly (MN1), Weekly (W1), Daily (D1)}
    - Y = {Weekly (W1), Daily (D1), 4-Hour (H4)} (one TF step lower than X)
  
  Formula 2: X rejects X and X breakout (Same-Timeframe Storyline)
    - Rejection and breakout occur on the same timeframe X.

Key Validity Conditions:
  1. The X-level that is rejected MUST BE FRESH (or unfresh Apex/OCL with no prior breakout).
  2. Rejection = Wick penetrates the level price, but candle BODY closes without breaking it.
  3. The LTF breakout swing high/low MUST HAVE BEEN FORMED BEFORE the rejection candle mitigates the level.
  4. Storyline remains active until an opposite rejection + breakout formula completes on the same timeframe pair.
"""

from __future__ import annotations

from indicators.candle_analyzer import LevelState  # noqa: F401 — needed for GAP 4 freshness check

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import pandas as pd

from indicators.candle_analyzer import CandleAnalyzer, CandleLevel, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.ocl_detector import OCLDetector
from indicators.qm_detector import QMDetector
from indicators.apex_detector import ApexDetector


class BiasDirection(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class StorylineEvent:
    """Represents a validated MSNR Storyline state for a timeframe pair."""
    htf: str                    # e.g., 'MN1', 'W1', 'D1'
    ltf: str                    # e.g., 'W1', 'D1', 'H4'
    bias: BiasDirection
    rejection_price: float      # Price of the HTF level rejected
    rejection_time: pd.Timestamp
    rejection_candle_idx: int
    breakout_time: pd.Timestamp
    breakout_candle_idx: int
    rejection_level_desc: str
    is_active: bool = True

    def __repr__(self) -> str:
        return (
            f"Storyline({self.htf}/{self.ltf} -> {self.bias.value} | "
            f"Rej @ {self.rejection_price:.2f} on {self.rejection_time.date()} -> "
            f"Break on {self.breakout_time.date()})"
        )


class StorylineEngine:
    """
    Evaluates multi-timeframe OHLCV data to track directional Storylines.
    """

    TF_PAIRS = [
        ("MN1", "W1"),   # Monthly reject Monthly -> Weekly breakout
        ("W1", "D1"),    # Weekly reject Weekly -> Daily breakout
        ("D1", "H4"),    # Daily reject Daily -> 4H breakout
        # GAP 10: Same-Timeframe Storylines (Video 8: X Rejects X and X Breakout)
        ("D1", "D1"),    # Daily reject Daily -> Daily breakout
        ("W1", "W1"),    # Weekly reject Weekly -> Weekly breakout
    ]

    def __init__(self, dataframes: Dict[str, pd.DataFrame]):
        """
        Parameters
        ----------
        dataframes : dict of {tf_str: pd.DataFrame}
            Contains at least 'MN1'/'M1', 'W1', 'D1', 'H4'.
        """
        self.dfs = {}
        for k, v in dataframes.items():
            key = k.upper()
            if key in ("MN", "MN1", "MONTHLY"):
                # Canonical monthly key is MN1; keep MN as alias.
                # NOTE: "M1" is 1-minute, never Monthly.
                self.dfs["MN1"] = v.copy()
                self.dfs["MN"] = v.copy()
            else:
                self.dfs[key] = v.copy()
        self.active_storylines: Dict[str, StorylineEvent] = {}

    def analyze_all(self) -> Dict[str, StorylineEvent]:
        """Evaluate storylines across all timeframe pairs."""
        self.active_storylines = {}

        for htf, ltf in self.TF_PAIRS:
            if htf in self.dfs and ltf in self.dfs:
                storyline = self._evaluate_pair(htf, ltf)
                if storyline:
                    self.active_storylines[f"{htf}_{ltf}"] = storyline
                    if htf == "MN1":
                        self.active_storylines[f"MN_{ltf}"] = storyline

        return self.active_storylines

    def get_bias(self, tf_pair: str = "D1_H4") -> BiasDirection:
        """Get the active bias for a specific timeframe pair."""
        if tf_pair in self.active_storylines:
            return self.active_storylines[tf_pair].bias
        return BiasDirection.NEUTRAL

    def get_overall_alignment(self) -> Dict[str, str]:
        """Returns the high-level bias alignment across Monthly, Weekly, and Daily."""
        alignment = {}
        for key, sl in self.active_storylines.items():
            alignment[key] = sl.bias.value
        return alignment

    # ------------------------------------------------------------------
    # Core Rejection & Breakout Logic
    # ------------------------------------------------------------------

    # Bullish rejection level types: wick touches level from above, close stays above
    BULLISH_REJ_TYPES = (LevelType.SUPPORT, LevelType.RBS)
    # Bearish rejection level types: wick touches level from below, close stays below
    BEARISH_REJ_TYPES = (LevelType.RESISTANCE, LevelType.SBR)

    def _evaluate_pair(self, htf: str, ltf: str) -> Optional[StorylineEvent]:
        df_htf = self.dfs[htf]
        df_ltf = self.dfs[ltf]

        if len(df_htf) < 10 or len(df_ltf) < 20:
            return None

        # 1. Detect ALL HTF key levels (S/R, SBR, RBS)
        analyzer_htf = CandleAnalyzer(df_htf)
        htf_levels = analyzer_htf.detect_all()
        tracker_htf = FreshnessTracker(df_htf)
        htf_levels = tracker_htf.update(htf_levels)

        closes_htf = df_htf["close"].values
        highs_htf = df_htf["high"].values
        lows_htf = df_htf["low"].values
        opens_htf = df_htf["open"].values
        times_htf = df_htf.index

        latest_storyline: Optional[StorylineEvent] = None

        # Scan ALL available HTF bars (not just last 30) to find the most recent storyline
        # Using last 100 bars to capture enough history but stay performant
        start_bar = max(0, len(df_htf) - 100)

        for i in range(start_bar, len(df_htf)):
            c_high = highs_htf[i]
            c_low = lows_htf[i]
            c_close = closes_htf[i]
            c_open = opens_htf[i]
            c_time = times_htf[i]

            for lvl in htf_levels:
                # Level must have been formed BEFORE this candle
                if lvl.candle_index >= i:
                    continue

                # HTF rejection level MUST be FRESH (Video 4 critical rule).
                # Unfresh or Broken levels cannot act as rejection anchors.
                if lvl.state in (LevelState.UNFRESH, LevelState.BROKEN):
                    continue

                # === BULLISH REJECTION (Video 4) ===
                # Wick touches / penetrates the Support/RBS level but candle
                # CLOSES ABOVE it. Spec requires only the close to hold; the
                # open may be on either side (e.g. gap opens below, close back above).
                if lvl.level_type in self.BULLISH_REJ_TYPES:
                    wick_touched = c_low <= lvl.price
                    body_close_above = c_close > lvl.price

                    if wick_touched and body_close_above:
                        breakout = self._check_ltf_breakout(c_time, df_ltf, is_bullish=True)
                        if breakout:
                            b_time, b_idx = breakout
                            latest_storyline = StorylineEvent(
                                htf=htf,
                                ltf=ltf,
                                bias=BiasDirection.BULLISH,
                                rejection_price=lvl.price,
                                rejection_time=c_time,
                                rejection_candle_idx=i,
                                breakout_time=b_time,
                                breakout_candle_idx=b_idx,
                                rejection_level_desc=f"{htf} {lvl.level_type.value.upper()} [FRESH]"
                            )

                # === BEARISH REJECTION (Video 4) ===
                # Wick touches / penetrates the Resistance/SBR level but candle
                # CLOSES BELOW it (close-only per spec; open position irrelevant).
                elif lvl.level_type in self.BEARISH_REJ_TYPES:
                    wick_touched = c_high >= lvl.price
                    body_close_below = c_close < lvl.price

                    if wick_touched and body_close_below:
                        breakout = self._check_ltf_breakout(c_time, df_ltf, is_bullish=False)
                        if breakout:
                            b_time, b_idx = breakout
                            latest_storyline = StorylineEvent(
                                htf=htf,
                                ltf=ltf,
                                bias=BiasDirection.BEARISH,
                                rejection_price=lvl.price,
                                rejection_time=c_time,
                                rejection_candle_idx=i,
                                breakout_time=b_time,
                                breakout_candle_idx=b_idx,
                                rejection_level_desc=f"{htf} {lvl.level_type.value.upper()} [FRESH]"
                            )

        return latest_storyline

    def _check_ltf_breakout(
        self,
        rejection_time: pd.Timestamp,
        df_ltf: pd.DataFrame,
        is_bullish: bool
    ) -> Optional[Tuple[pd.Timestamp, int]]:
        """
        Validates whether the LTF confirmed the HTF rejection with a structural breakout.

        Video 4: after the HTF rejection, the LTF must break structure — a close
        through the most recent opposite-side LTF key level (resistance for
        bullish, support for bearish) formed BEFORE the rejection bar. A rolling
        extreme is used only as fallback when no LTF levels exist.
        The forward scan covers 60 bars so current or recent storylines are found.
        """
        closes = df_ltf["close"].values
        times = df_ltf.index

        # Find the first LTF bar at or after the HTF rejection time
        ltf_indices = [idx for idx, t in enumerate(times) if t >= rejection_time]

        if not ltf_indices:
            # If no LTF bar after rejection, check if breakout already occurred before it
            # (This can happen on higher timeframe pairs like MN->W1 where W1 runs ahead)
            ltf_indices = list(range(len(df_ltf)))
            if not ltf_indices:
                return None
            rej_ltf_idx = len(df_ltf) - 1
        else:
            rej_ltf_idx = ltf_indices[0]

        if rej_ltf_idx < 5:
            return None

        # Extended forward scan: up to 60 bars after rejection
        forward_end = min(len(df_ltf), rej_ltf_idx + 60)

        # Primary: break of the most recent real LTF key level before rejection.
        try:
            ltf_analyzer = CandleAnalyzer(df_ltf.iloc[:rej_ltf_idx])
            ltf_levels = ltf_analyzer.detect_all()
            if is_bullish:
                brk = [lv for lv in ltf_levels
                       if lv.level_type in (LevelType.RESISTANCE, LevelType.SBR)]
            else:
                brk = [lv for lv in ltf_levels
                       if lv.level_type in (LevelType.SUPPORT, LevelType.RBS)]
            if brk:
                target = brk[-1].price
                if is_bullish:
                    for j in range(rej_ltf_idx, forward_end):
                        if closes[j] > target:
                            return times[j], j
                    if closes[-1] > target:
                        return times[-1], len(closes) - 1
                else:
                    for j in range(rej_ltf_idx, forward_end):
                        if closes[j] < target:
                            return times[j], j
                    if closes[-1] < target:
                        return times[-1], len(closes) - 1
                return None
        except Exception:
            pass  # fall through to rolling-extreme fallback below

        # Fallback (no LTF levels detected): rolling extreme of prior 30 bars.
        prior_start = max(0, rej_ltf_idx - 30)
        prior_window = closes[prior_start:rej_ltf_idx]
        if len(prior_window) == 0:
            return None

        if is_bullish:
            target_high = float(max(prior_window))
            # Scan forward: look for a close above the prior swing high
            for j in range(rej_ltf_idx, forward_end):
                if closes[j] > target_high:
                    return times[j], j
            # Fallback: if price is currently above target_high (breakout already happened)
            if closes[-1] > target_high:
                return times[-1], len(closes) - 1
        else:
            target_low = float(min(prior_window))
            # Scan forward: look for a close below the prior swing low
            for j in range(rej_ltf_idx, forward_end):
                if closes[j] < target_low:
                    return times[j], j
            # Fallback: if price is currently below target_low (breakout already happened)
            if closes[-1] < target_low:
                return times[-1], len(closes) - 1

        return None
