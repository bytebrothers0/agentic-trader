"""
ts_detector.py — Turtle Soup (TS) indicator.

TS is formed by TWO ADJACENT candles (colour-independent):

  UPPER TS (bearish sweep of highs):
    - candle2.high > candle1.high        (candle 1 upper wick is swept)
    - candle2 body closes BELOW candle1.high:
        max(candle2.open, candle2.close) < candle1.high
    - candle1 must have a real upper wick:
        candle1.high > max(candle1.open, candle1.close)

  LOWER TS (bullish sweep of lows):
    - candle2.low < candle1.low          (candle 1 lower wick is swept)
    - candle2 body closes ABOVE candle1.low:
        min(candle2.open, candle2.close) > candle1.low
    - candle1 must have a real lower wick:
        candle1.low < min(candle1.open, candle1.close)

Dojis (open == close) never qualify — TS needs real bodies.
Level price = the swept level (candle1.high for UPPER, candle1.low for LOWER).
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TSType(Enum):
    TS_HIGH = "ts_high"  # bearish — sweep of highs, body back below
    TS_LOW = "ts_low"    # bullish — sweep of lows, body back above


class TSDirection(Enum):
    BEARISH = "bearish"
    BULLISH = "bullish"


@dataclass
class TSLevel:
    """A single Turtle Soup sweep."""
    ts_type: TSType
    direction: TSDirection
    price: float              # swept level (candle1 high or low)
    candle_index: int         # iloc of candle2 (the sweeping candle)
    candle_time: pd.Timestamp
    sweep_candle_index: int = 0   # iloc of candle1 (the swept candle)
    sweep_amount: float = 0.0     # how far the wick swept past (price units)
    close_back_distance: float = 0.0  # body-close back inside vs level
    forming_candle_indices: List[int] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"TSLevel({self.ts_type.value} @ {self.price:.5f} "
            f"[idx={self.candle_index}] dir={self.direction.value})"
        )


class TSDetector:
    """
    Detects Turtle Soup sweeps on OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    sweep_min : float
        Minimum sweep distance in price units (default 0.0 = any strict sweep).
    min_sweep_atr : float
        Minimum sweep size as a multiple of local ATR(14). Micro-sweeps
        below this never count (default 0.0 = off, keeps indicator display
        unfiltered; entry engines pass their own gate, e.g. 0.5).
    atr_period : int
        ATR lookback for the sweep gate. Default 14.
    """

    def __init__(self, df: pd.DataFrame, sweep_min: float = 0.0,
                 min_sweep_atr: float = 0.0, atr_period: int = 14):
        self._validate(df)
        self.df = df.copy()
        self.sweep_min = sweep_min
        self.min_sweep_atr = min_sweep_atr
        self.atr_period = atr_period
        self._atr = self._compute_atr() if min_sweep_atr > 0 else None
        self._levels: List[TSLevel] = []

    def detect_all(self) -> List[TSLevel]:
        self._levels = []
        o = self.df["open"].values
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        times = self.df.index

        for i in range(len(self.df) - 1):
            if c[i] == o[i] or c[i + 1] == o[i + 1]:
                continue  # dojis have no body direction; never TS

            # --- UPPER TS: sweep of highs, body back below ---
            c1_upper_wick = h[i] > max(o[i], c[i])
            swept_high = h[i + 1] > h[i] + self.sweep_min
            body_back_below = max(o[i + 1], c[i + 1]) < h[i]
            if (c1_upper_wick and swept_high and body_back_below
                    and self._big_enough(float(h[i + 1] - h[i]), i + 1)):
                self._levels.append(TSLevel(
                    ts_type=TSType.TS_HIGH,
                    direction=TSDirection.BEARISH,
                    price=float(h[i]),
                    candle_index=i + 1,
                    candle_time=times[i + 1],
                    sweep_candle_index=i,
                    sweep_amount=float(h[i + 1] - h[i]),
                    close_back_distance=float(h[i] - max(o[i + 1], c[i + 1])),
                    forming_candle_indices=[i, i + 1],
                ))

            # --- LOWER TS: sweep of lows, body back above ---
            c1_lower_wick = l[i] < min(o[i], c[i])
            swept_low = l[i + 1] < l[i] - self.sweep_min
            body_back_above = min(o[i + 1], c[i + 1]) > l[i]
            if (c1_lower_wick and swept_low and body_back_above
                    and self._big_enough(float(l[i] - l[i + 1]), i + 1)):
                self._levels.append(TSLevel(
                    ts_type=TSType.TS_LOW,
                    direction=TSDirection.BULLISH,
                    price=float(l[i]),
                    candle_index=i + 1,
                    candle_time=times[i + 1],
                    sweep_candle_index=i,
                    sweep_amount=float(l[i] - l[i + 1]),
                    close_back_distance=float(min(o[i + 1], c[i + 1]) - l[i]),
                    forming_candle_indices=[i, i + 1],
                ))

        return self._levels

    @property
    def levels(self) -> List[TSLevel]:
        return self._levels

    def _big_enough(self, sweep: float, idx: int) -> bool:
        if self.min_sweep_atr <= 0 or self._atr is None:
            return True
        atr = self._atr[idx]
        if atr is None or not (atr > 0):
            return True
        return sweep >= self.min_sweep_atr * atr

    def _compute_atr(self) -> list:
        h = self.df["high"]
        l = self.df["low"]
        c = self.df["close"]
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                       axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / self.atr_period, min_periods=1,
                      adjust=False).mean().tolist()

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
