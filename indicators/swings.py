"""
swings.py — shared fractal-pivot + ATR helpers for the SMC detectors.

Kept free of BOS/TS imports so the inducement (IDM) and liquidity detectors
share one pivot definition.

Fractal pivot (symmetric): bar ``i`` is a pivot high when its high is >= every
high ``length`` bars to its left and strictly > every high ``length`` bars to
its right (mirror for lows). The left test is non-strict and the right test
strict, so a flat plateau marks exactly one pivot — its last bar — instead of
duplicates.

All indices are positional (iloc) and line up with the detector DataFrames.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import pandas as pd


@dataclass(frozen=True)
class Pivot:
    """A confirmed fractal swing point."""

    index: int          # iloc of the swing bar
    price: float        # swing high or low
    kind: str           # "high" | "low"

    @property
    def is_high(self) -> bool:
        return self.kind == "high"

    @property
    def is_low(self) -> bool:
        return self.kind == "low"


def find_pivots(high: Sequence[float], low: Sequence[float],
                length: int = 2) -> List[Pivot]:
    """Symmetric fractal pivots, oldest -> newest."""
    n = len(high)
    L = max(1, int(length))
    out: List[Pivot] = []
    for i in range(L, n - L):
        left_hi = max(high[i - L:i])
        right_hi = max(high[i + 1:i + 1 + L])
        h = high[i]
        if h >= left_hi and h > right_hi:
            out.append(Pivot(i, float(h), "high"))
            continue
        left_lo = min(low[i - L:i])
        right_lo = min(low[i + 1:i + 1 + L])
        lo = low[i]
        if lo <= left_lo and lo < right_lo:
            out.append(Pivot(i, float(lo), "low"))
    return out


def atr_series(df: pd.DataFrame, period: int = 14) -> List[float]:
    """Wilder ATR (same smoothing as BOSDetector), aligned to df rows."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    p = max(1, int(period))
    return tr.ewm(alpha=1.0 / p, min_periods=1, adjust=False).mean().tolist()
