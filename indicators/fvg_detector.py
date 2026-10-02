"""
fvg_detector.py — Fair Value Gap + Inverse Fair Value Gap.

FVG ported from the script's LuxAlgo detectFVG (3-candle gap):
  Bullish FVG at bar i: low[i] > high[i-2] (the gap) AND the displacement
    close[i-1] > high[i-2] AND gap size above threshold.
    Zone = [high[i-2] .. low[i]] (bottom .. top).
  Bearish FVG: mirror (high[i] < low[i-2], close[i-1] < low[i-2],
    zone = [high[i] .. low[i-2]]).
  Mitigation: bull FVG dies on first close below its bottom;
    bear on first close above its top (same as the script).

IFVG (user rule): a RECENT FVG broken by a FULL BODY close to the opposite
  side, confirmed by a newer opposite FVG genuinely overlapping it. Genuine
  means the overlap covers at least half the smaller zone (edge-kisses via
  wick tips don't count). Ancient FVGs never invert (recency cap),
  wick-only returns never invert. The drawn zone is the OVERLAP region —
  which equals the full first zone when the second engulfs it.
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class FVGDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class FVGLevel:
    """A single Fair Value Gap zone."""
    direction: FVGDirection
    top: float                    # zone top
    bottom: float                 # zone bottom
    formation_index: int          # iloc of bar i (gap confirmed)
    candle_time: pd.Timestamp
    mitigated: bool = False
    mitigation_index: Optional[int] = None
    forming_candle_indices: List[int] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def overlaps(self, other: "FVGLevel") -> bool:
        return self.bottom < other.top and other.bottom < self.top

    def intersection(self, other: "FVGLevel") -> tuple:
        return (min(self.top, other.top), max(self.bottom, other.bottom))

    def __repr__(self) -> str:
        state = f"mit@{self.mitigation_index}" if self.mitigated else "active"
        return (
            f"FVGLevel({self.direction.value} [{self.bottom:.5f}..{self.top:.5f}] "
            f"[idx={self.formation_index}] {state})"
        )


@dataclass
class IFVGLevel:
    """An Inverse Fair Value Gap: a recent FVG broken by a full body to the
    opposite side, confirmed by a newer opposite FVG overlapping it.
    The zone is the FIRST FVG's full zone (as traded on charts)."""
    direction: FVGDirection      # bearish = was bullish, inverted down
    top: float
    bottom: float
    formation_index: int          # iloc of the second (confirming) FVG
    candle_time: pd.Timestamp
    first_formation_index: int = 0
    forming_candle_indices: List[int] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def __repr__(self) -> str:
        return (
            f"IFVGLevel({self.direction.value} [{self.bottom:.5f}..{self.top:.5f}] "
            f"[idx={self.formation_index}])"
        )


class FVGDetector:
    """
    Detects FVG zones and IFVG overlaps on OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    threshold : float
        Minimum gap size as a fraction (script's Threshold %). Default 0.0.
    min_atr_mult : float
        Minimum zone height as a multiple of local ATR(14). Gaps thinner
        than this render as lines, so they are skipped. Default 0.1.
    atr_period : int
        ATR lookback. Default 14.
    max_gap_bars : int
        IFVG recency: the two FVGs must form within this many bars of each
        other, otherwise the first is stale history, not inducement.
        Default 50.
    min_overlap_frac : float
        IFVG overlap quality: the intersection must cover at least this
        fraction of the SMALLER zone. Default 0.5.
    """

    def __init__(self, df: pd.DataFrame, threshold: float = 0.0,
                 min_atr_mult: float = 0.1, atr_period: int = 14,
                 max_gap_bars: int = 50, min_overlap_frac: float = 0.5):
        self._validate(df)
        self.df = df.copy()
        self.threshold = threshold
        self.min_atr_mult = min_atr_mult
        self.atr_period = atr_period
        self.max_gap_bars = max_gap_bars
        self.min_overlap_frac = min_overlap_frac
        self._atr = self._compute_atr()
        self._fvgs: List[FVGLevel] = []
        self._ifvgs: List[IFVGLevel] = []

    def detect_all(self) -> List[FVGLevel]:
        self._fvgs = []
        o = self.df["open"].values
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        times = self.df.index
        n = len(self.df)

        for i in range(2, n):
            # Bullish gap: low[i] above high[i-2], displaced middle close.
            if l[i] > h[i - 2] and c[i - 1] > h[i - 2]:
                if (l[i] - h[i - 2]) / h[i - 2] > self.threshold:
                    if self._tall_enough(float(l[i] - h[i - 2]), i):
                        self._fvgs.append(FVGLevel(
                            direction=FVGDirection.BULLISH,
                            top=float(l[i]),
                            bottom=float(h[i - 2]),
                            formation_index=i,
                            candle_time=times[i],
                            forming_candle_indices=[i - 2, i - 1, i],
                        ))
            # Bearish gap: mirror.
            if h[i] < l[i - 2] and c[i - 1] < l[i - 2]:
                if (l[i - 2] - h[i]) / h[i] > self.threshold:
                    if self._tall_enough(float(l[i - 2] - h[i]), i):
                        self._fvgs.append(FVGLevel(
                            direction=FVGDirection.BEARISH,
                            top=float(l[i - 2]),
                            bottom=float(h[i]),
                            formation_index=i,
                            candle_time=times[i],
                            forming_candle_indices=[i - 2, i - 1, i],
                        ))

        # Mitigation: first close back through the zone edge.
        for fv in self._fvgs:
            for m in range(fv.formation_index + 1, n):
                if fv.direction == FVGDirection.BULLISH and c[m] < fv.bottom:
                    fv.mitigated = True
                    fv.mitigation_index = m
                    break
                if fv.direction == FVGDirection.BEARISH and c[m] > fv.top:
                    fv.mitigated = True
                    fv.mitigation_index = m
                    break

        self._fvgs.sort(key=lambda fv: fv.formation_index)
        return self._fvgs

    def detect_ifvg(self, fvgs: Optional[List[FVGLevel]] = None) -> List[IFVGLevel]:
        """A recent FVG broken by a full body to the opposite side, with a
        newer opposite FVG genuinely overlapping it, inverts into an IFVG
        drawn over the OVERLAP region."""
        if fvgs is None:
            fvgs = self.detect_all()
        self._ifvgs = []
        c = self.df["close"].values
        seen = set()
        for older in fvgs:
            for newer in fvgs:
                if newer.formation_index <= older.formation_index:
                    continue
                if newer.formation_index - older.formation_index > self.max_gap_bars:
                    continue  # first FVG is stale history, not inducement
                if newer.direction == older.direction:
                    continue
                if not older.overlaps(newer):
                    continue
                top, bottom = older.intersection(newer)
                smaller = min(older.top - older.bottom, newer.top - newer.bottom)
                if smaller <= 0 or (top - bottom) / smaller < self.min_overlap_frac:
                    continue  # wick-tip kiss, not a proper overlap
                if not self._broke_through(older, newer.formation_index, c):
                    continue  # wicks don't invert; need a full-body close
                direction = (FVGDirection.BEARISH
                             if newer.direction == FVGDirection.BEARISH
                             else FVGDirection.BULLISH)
                key = (direction, round(top, 6), round(bottom, 6),
                       newer.formation_index)
                if key in seen:
                    continue
                seen.add(key)
                self._ifvgs.append(IFVGLevel(
                    direction=direction,
                    top=top,
                    bottom=bottom,
                    formation_index=newer.formation_index,
                    candle_time=newer.candle_time,
                    first_formation_index=older.formation_index,
                    forming_candle_indices=[older.formation_index,
                                            newer.formation_index],
                ))
        self._ifvgs.sort(key=lambda iv: iv.formation_index)
        return self._ifvgs

    @staticmethod
    def _broke_through(first: FVGLevel, up_to: int, closes) -> bool:
        """A close beyond the zone's far edge after it formed (full body)."""
        for m in range(first.formation_index + 1, up_to + 1):
            if first.direction == FVGDirection.BULLISH and closes[m] < first.bottom:
                return True
            if first.direction == FVGDirection.BEARISH and closes[m] > first.top:
                return True
        return False

    def _tall_enough(self, height: float, formation: int) -> bool:
        """Zone must be visually identifiable vs local volatility."""
        atr = self._atr[formation]
        if atr is None or not (atr > 0):
            return True
        return height >= self.min_atr_mult * atr

    def _compute_atr(self) -> list:
        h = self.df["high"]
        l = self.df["low"]
        c = self.df["close"]
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                       axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / self.atr_period, min_periods=1,
                     adjust=False).mean()
        return atr.tolist()

    @property
    def fvgs(self) -> List[FVGLevel]:
        return self._fvgs

    @property
    def ifvgs(self) -> List[IFVGLevel]:
        return self._ifvgs

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
