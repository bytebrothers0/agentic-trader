"""
liquidity_detector.py — Liquidity pools (SMC): equal highs / equal lows.

Buy-side liquidity (BSL) rests above swing highs; sell-side liquidity (SSL)
below swing lows. The high-value targets are *equal* highs/lows — two or more
swings at (almost) the same price that build a stop cluster. Single stray
swings are deliberately excluded; that is the noise lever.

Algorithm
---------
1. Fractal pivots (``swing_length``, default 5 — bigger than IDM's, so only
   meaningful swings qualify).
2. Cluster same-kind pivots that are "equal": price within ``eq_tol_atr`` x ATR
   at the cluster's first bar AND within ``eq_max_bars`` of it. The reference is
   the cluster's running extreme, so a drifting staircase cannot chain into one
   giant pool.
3. A cluster with >= ``min_touches`` members becomes an EQH (buy-side, above)
   or EQL (sell-side, below) pool. Pool price = the cluster extreme.
4. ``taken`` = the first later bar whose wick trades through the pool.
5. Cap to the newest ``max_per_side`` per pool type, fresh (untaken) first.
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence

from indicators.swings import Pivot, atr_series, find_pivots


class LIQType(Enum):
    EQH = "equal_highs"   # buy-side liquidity (above)
    EQL = "equal_lows"    # sell-side liquidity (below)


class LIQSide(Enum):
    BUYSIDE = "buyside"
    SELLSIDE = "sellside"


@dataclass
class LiquidityLevel:
    """A single equal-highs / equal-lows liquidity pool."""

    liq_type: LIQType
    side: LIQSide
    price: float
    first_index: int
    last_index: int
    candle_time: pd.Timestamp
    pool_size: int
    taken: bool = False
    taken_index: Optional[int] = None
    forming_candle_indices: List[int] = field(default_factory=list)

    def __repr__(self) -> str:
        state = f"taken@{self.taken_index}" if self.taken else "resting"
        return (
            f"LiquidityLevel({self.liq_type.value} x{self.pool_size} "
            f"@ {self.price:.5f} [idx={self.first_index}..{self.last_index}] "
            f"{state})"
        )


class LiquidityDetector:
    """
    Equal-highs / equal-lows liquidity-pool detector.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with a DatetimeIndex.
    swing_length : int
        Fractal window for swings. Default 5.
    eq_tol_atr : float
        "Equal" tolerance as a fraction of ATR at the cluster's first bar.
        Default 0.15.
    eq_max_bars : int
        Max bar distance between touches of the same pool. Default 60.
    min_touches : int
        Minimum touches for a pool to draw (>= 2). Default 2.
    max_per_side : int
        Keep at most this many pools per type (newest, untaken first).
    atr_period : int
        ATR lookback for the equality tolerance. Default 14.
    """

    def __init__(self, df: pd.DataFrame, swing_length: int = 5,
                 eq_tol_atr: float = 0.15, eq_max_bars: int = 60,
                 min_touches: int = 2, max_per_side: int = 3,
                 atr_period: int = 14):
        self._validate(df)
        self.df = df.copy()
        self.swing_length = max(1, int(swing_length))
        self.eq_tol_atr = float(eq_tol_atr)
        self.eq_max_bars = max(1, int(eq_max_bars))
        self.min_touches = max(2, int(min_touches))
        self.max_per_side = max(1, int(max_per_side))
        self.atr_period = atr_period
        self._levels: List[LiquidityLevel] = []

    def detect_all(self) -> List[LiquidityLevel]:
        self._levels = []
        h = self.df["high"].values
        l = self.df["low"].values
        atr = atr_series(self.df, self.atr_period)
        pivots = find_pivots(h, l, self.swing_length)
        pivot_highs = [p for p in pivots if p.is_high]
        pivot_lows = [p for p in pivots if p.is_low]

        for cluster in self._cluster(pivot_highs, atr, mode="high"):
            if len(cluster) < self.min_touches:
                continue
            price = max(p.price for p in cluster)
            last = cluster[-1].index
            taken = self._first_above(price, last, h)
            self._levels.append(LiquidityLevel(
                liq_type=LIQType.EQH,
                side=LIQSide.BUYSIDE,
                price=float(price),
                first_index=cluster[0].index,
                last_index=last,
                candle_time=self.df.index[cluster[0].index],
                pool_size=len(cluster),
                taken=taken is not None,
                taken_index=taken,
                forming_candle_indices=[p.index for p in cluster],
            ))

        for cluster in self._cluster(pivot_lows, atr, mode="low"):
            if len(cluster) < self.min_touches:
                continue
            price = min(p.price for p in cluster)
            last = cluster[-1].index
            taken = self._first_below(price, last, l)
            self._levels.append(LiquidityLevel(
                liq_type=LIQType.EQL,
                side=LIQSide.SELLSIDE,
                price=float(price),
                first_index=cluster[0].index,
                last_index=last,
                candle_time=self.df.index[cluster[0].index],
                pool_size=len(cluster),
                taken=taken is not None,
                taken_index=taken,
                forming_candle_indices=[p.index for p in cluster],
            ))

        self._cap()
        self._levels.sort(key=lambda lv: lv.last_index)
        return self._levels

    def _cluster(self, pivots: Sequence[Pivot], atr: Sequence[float],
                 mode: str) -> List[List[Pivot]]:
        clusters: List[List[Pivot]] = []
        cur: List[Pivot] = []
        for p in pivots:                      # already index-sorted
            if cur:
                ref = (max(x.price for x in cur) if mode == "high"
                       else min(x.price for x in cur))
                tol = self.eq_tol_atr * atr[cur[0].index]
                if (abs(p.price - ref) <= tol
                        and (p.index - cur[0].index) <= self.eq_max_bars):
                    cur.append(p)
                    continue
                clusters.append(cur)
            cur = [p]
        if cur:
            clusters.append(cur)
        return clusters

    @staticmethod
    def _first_above(price: float, from_i: int, h) -> Optional[int]:
        for m in range(from_i + 1, len(h)):
            if h[m] > price:
                return m
        return None

    @staticmethod
    def _first_below(price: float, from_i: int, l) -> Optional[int]:
        for m in range(from_i + 1, len(l)):
            if l[m] < price:
                return m
        return None

    def _cap(self) -> None:
        """Keep the newest ``max_per_side`` per type, untaken first."""
        for t in (LIQType.EQH, LIQType.EQL):
            group = [lv for lv in self._levels if lv.liq_type == t]
            if len(group) <= self.max_per_side:
                continue
            group.sort(key=lambda lv: (lv.taken, -lv.last_index))
            drop = {id(lv) for lv in group[self.max_per_side:]}
            self._levels = [lv for lv in self._levels if id(lv) not in drop]

    @property
    def levels(self) -> List[LiquidityLevel]:
        return self._levels

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
