"""
freshness_tracker.py — MSNR Level Freshness State Machine (web math).

Rules (MALIYA / MALAYSIAN_SNR web spec):
  FRESH   → A wick touches the level    → UNFRESH (use 1 consumed)
  UNFRESH → A body closes through it    → BROKEN (role reversal flips it
            fresh in the new role via CandleAnalyzer)
  FRESH   → A body closes through it    → BROKEN (no wick-touch step needed)

  Web 2-use rule: a level may be used at most TWICE. Every wick-touch bar
  increments touch_count (fresh use + unfresh use); entries must retire
  the level at touch_count >= 2 even if still UNFRESH.
"""

from __future__ import annotations

from typing import List, Optional
import pandas as pd

from indicators.candle_analyzer import CandleLevel, LevelState


class FreshnessTracker:
    """
    Updates the freshness state of a list of CandleLevels by scanning
    subsequent OHLCV candles after each level's formation.

    Usage
    -----
    tracker = FreshnessTracker(df)
    levels  = tracker.update(levels)   # mutates each level's .state in-place
    """

    def __init__(self, df: pd.DataFrame):
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame index must be a DatetimeIndex.")
        self.df = df.copy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, levels: List[CandleLevel]) -> List[CandleLevel]:
        """
        Scan candles after each level's formation candle and update
        state (FRESH → UNFRESH → BROKEN).  Mutates in-place.
        """
        for level in levels:
            if level.state == LevelState.BROKEN:
                continue  # already determined
            self._evaluate_level(level)
        return levels

    def is_fresh(self, level: CandleLevel) -> bool:
        return level.state == LevelState.FRESH

    def is_unfresh(self, level: CandleLevel) -> bool:
        return level.state == LevelState.UNFRESH

    def is_broken(self, level: CandleLevel) -> bool:
        return level.state == LevelState.BROKEN

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    def _evaluate_level(self, level: CandleLevel):
        """
        Walk candles from (level.candle_index + 2) onward.

        A wick crosses the level  → UNFRESH (record first_touch_index)
        A body closes through it  → BROKEN  (record break_candle_index)
        """
        df = self.df
        price = level.price
        start_i = level.candle_index + 2   # skip the two forming candles

        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values
        closes = df["close"].values

        for i in range(start_i, len(df)):
            wick_high = highs[i]
            wick_low = lows[i]
            body_high = max(opens[i], closes[i])
            body_low = min(opens[i], closes[i])

            # --- Check for body-close-through (BROKEN) ---
            if self._body_closes_through(level, body_high, body_low, closes[i]):
                level.state = LevelState.BROKEN
                level.break_candle_index = i
                return

            # --- Check for wick touch (consumes one of max 2 uses) ---
            if self._wick_touches(level, wick_high, wick_low):
                level.touch_count += 1
                if level.state == LevelState.FRESH:
                    level.state = LevelState.UNFRESH
                    level.first_touch_index = i
                    # Do NOT return — keep scanning for a possible body break

    @staticmethod
    def _wick_touches(level: CandleLevel, wick_high: float, wick_low: float) -> bool:
        """Return True if any part of the candle's wick crossed the level price."""
        # Use the level type name directly (handles both LevelType enum and raw string)
        lt = level.level_type.value if hasattr(level.level_type, "value") else str(level.level_type)

        if lt in ("support", "rbs"):
            # Wick dips to or below the support price
            return wick_low <= level.price
        else:
            # Wick rises to or above the resistance price
            return wick_high >= level.price

    @staticmethod
    def _body_closes_through(
        level: CandleLevel,
        body_high: float,
        body_low: float,
        close: float,
    ) -> bool:
        """
        Return True if the BODY of the candle closes on the opposite
        side of the level (definitive break — triggers role reversal).
        """
        lt = level.level_type.value if hasattr(level.level_type, "value") else str(level.level_type)

        if lt in ("support", "rbs"):
            # Body close is below support/rbs (close-through)
            return close < level.price
        else:
            # Body close is above resistance/sbr (close-through)
            return close > level.price


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def filter_fresh(levels: List[CandleLevel]) -> List[CandleLevel]:
    """Return only levels that are currently FRESH."""
    return [lv for lv in levels if lv.state == LevelState.FRESH]


def filter_unfresh(levels: List[CandleLevel]) -> List[CandleLevel]:
    """Return levels that have been wick-touched but not body-broken."""
    return [lv for lv in levels if lv.state == LevelState.UNFRESH]


def filter_active(levels: List[CandleLevel]) -> List[CandleLevel]:
    """Return levels that are not yet BROKEN (fresh or unfresh)."""
    return [lv for lv in levels if lv.state != LevelState.BROKEN]


def is_usable(level: CandleLevel, max_uses: int = 2) -> bool:
    """Web 2-use rule: not broken and fewer than max_uses wick touches."""
    return level.state != LevelState.BROKEN and level.touch_count < max_uses


def filter_usable(levels: List[CandleLevel], max_uses: int = 2) -> List[CandleLevel]:
    """Return levels still tradable under the web 2-use rule."""
    return [lv for lv in levels if is_usable(lv, max_uses)]
