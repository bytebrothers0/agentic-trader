"""
idm_detector.py — Inducement (IDM / liquidity) indicator (Luap True SMC).

Valid pullback (Part 1, video examples 1-6):
  Bullish: reference candle 1 holds the leg high. A LATER candle breaking
    candle 1's LOW is the pullback; a (different or same) later candle
    breaking candle 1's HIGH is the continuation. BOTH breaks are required —
    one-sided drift with no pullback (ex. 3, 4, 6) yields no IDM.
    Inside bars (range fully inside the previous candle) are non-events and
    ignored for pullback identification. If the HIGH breaks first, reference
    candle 1 is invalidated (the target shifts, per Part 1).
  Bearish: mirror (pullback breaks candle 1's HIGH, continuation breaks LOW).

IDM (Part 3):
  - Bullish IDM = the swing low (lowest low between candle 1 and the
    continuation candle). Bearish IDM = the swing high.
  - A later new extreme does NOT discard the IDM — it confirms the leg the
    IDM belongs to. The newest pullback simply adds the newest IDM (shift).
  - If price sweeps the IDM (wick crosses it) after confirmation, the prior
    extreme is confirmed: the IDM is emitted with its full formation->sweep
    span. Unswept IDMs emit with an open end (fixed short ray on chart).
  - Output = every confirmed IDM (swept or still active).
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class IDMType(Enum):
    IDM_LOW = "idm_low"    # bullish-leg inducement (low to be swept)
    IDM_HIGH = "idm_high"  # bearish-leg inducement (high to be swept)


class IDMDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class IDMLevel:
    """A single Inducement level."""
    idm_type: IDMType
    direction: IDMDirection
    price: float                  # pullback extreme (low or high)
    formation_index: int          # iloc of the candle that set the extreme
    candle_time: pd.Timestamp
    swept: bool = False
    sweep_index: Optional[int] = None
    forming_candle_indices: List[int] = field(default_factory=list)

    def __repr__(self) -> str:
        state = f"swept@{self.sweep_index}" if self.swept else "active"
        return (
            f"IDMLevel({self.idm_type.value} @ {self.price:.5f} "
            f"[idx={self.formation_index}] {state})"
        )


class IDMDetector:
    """
    Detects IDM levels on OHLCV data (both legs independently).

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    """

    def __init__(self, df: pd.DataFrame):
        self._validate(df)
        self.df = df.copy()
        self._levels: List[IDMLevel] = []

    def detect_all(self) -> List[IDMLevel]:
        self._levels = []
        self._scan_bullish()
        self._scan_bearish()
        self._levels.sort(key=lambda lv: lv.formation_index)
        return self._levels

    # ------------------------------------------------------------------
    # Bullish: pullback breaks candle 1 low, continuation breaks its high.
    # IDM = swing low between the two breaks.
    # ------------------------------------------------------------------
    def _scan_bullish(self):
        h = self.df["high"].values
        l = self.df["low"].values
        times = self.df.index
        n = len(self.df)

        for i in range(n):
            # Phase 1: pullback = first break of low[i] before any break of high[i].
            pull = None
            both = False
            for j in range(i + 1, n):
                if self._is_inside(j):
                    continue  # non-event
                breaks_high = h[j] > h[i]
                breaks_low = l[j] < l[i]
                if breaks_high and breaks_low:
                    pull, both = j, True
                    break
                if breaks_low:
                    pull = j
                    break
                if breaks_high:
                    break  # high first -> candle 1 invalidated, no IDM
            if pull is None:
                continue
            # Phase 2: continuation = first break of high[i] at/after pull.
            cont = pull if both else None
            if cont is None:
                for k in range(pull + 1, n):
                    if h[k] > h[i]:
                        cont = k
                        break
            if cont is None:
                continue  # leg never continued -> no inducement
            # Swing low = extreme between candle 1 and continuation.
            seg = l[i + 1:cont + 1]
            f = i + 1 + min(range(len(seg)), key=lambda t: seg[t])
            price = float(l[f])
            # Phase 3: sweep = first wick cross after confirmation.
            sweep = None
            for m in range(cont + 1, n):
                if l[m] < price:
                    sweep = m
                    break
            self._add(IDMType.IDM_LOW, IDMDirection.BULLISH, price, f,
                      times[f], sweep, [i, f] + ([sweep] if sweep is not None else []))

    # ------------------------------------------------------------------
    # Bearish: pullback breaks candle 1 high, continuation breaks its low.
    # IDM = swing high between the two breaks.
    # ------------------------------------------------------------------
    def _scan_bearish(self):
        h = self.df["high"].values
        l = self.df["low"].values
        times = self.df.index
        n = len(self.df)

        for i in range(n):
            # Phase 1: pullback = first break of high[i] before any break of low[i].
            pull = None
            both = False
            for j in range(i + 1, n):
                if self._is_inside(j):
                    continue  # non-event
                breaks_high = h[j] > h[i]
                breaks_low = l[j] < l[i]
                if breaks_high and breaks_low:
                    pull, both = j, True
                    break
                if breaks_high:
                    pull = j
                    break
                if breaks_low:
                    break  # low first -> candle 1 invalidated, no IDM
            if pull is None:
                continue
            # Phase 2: continuation = first break of low[i] at/after pull.
            cont = pull if both else None
            if cont is None:
                for k in range(pull + 1, n):
                    if l[k] < l[i]:
                        cont = k
                        break
            if cont is None:
                continue  # leg never continued -> no inducement
            # Swing high = extreme between candle 1 and continuation.
            seg = h[i + 1:cont + 1]
            f = i + 1 + min(range(len(seg)), key=lambda t: -seg[t])
            price = float(h[f])
            # Phase 3: sweep = first wick cross after confirmation.
            sweep = None
            for m in range(cont + 1, n):
                if h[m] > price:
                    sweep = m
                    break
            self._add(IDMType.IDM_HIGH, IDMDirection.BEARISH, price, f,
                      times[f], sweep, [i, f] + ([sweep] if sweep is not None else []))

    def _add(self, idm_type: IDMType, direction: IDMDirection, price: float,
             formation: int, candle_time: pd.Timestamp,
             sweep: Optional[int], forming: List[int]):
        for lv in self._levels:
            if (lv.idm_type == idm_type and lv.price == price
                    and lv.formation_index == formation):
                return  # same swing from another reference; keep one ray
        self._levels.append(IDMLevel(
            idm_type=idm_type,
            direction=direction,
            price=price,
            formation_index=formation,
            candle_time=candle_time,
            swept=sweep is not None,
            sweep_index=sweep,
            forming_candle_indices=forming,
        ))

    def _is_inside(self, j: int) -> bool:
        """Range of candle j fully contained in candle j-1."""
        h = self.df["high"].values
        l = self.df["low"].values
        return bool(h[j] <= h[j - 1] and l[j] >= l[j - 1])

    @property
    def levels(self) -> List[IDMLevel]:
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
