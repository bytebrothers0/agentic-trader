"""
ob_detector.py — Order Blocks + Breaker Blocks (LuxAlgo port + Luap status).

Ported from LuxAlgo "Order Blocks & Breaker Blocks":
  Swings: Donchian zigzag (bar `swing_length` ago exceeding all bars after
    it flips trend state; swing prints on flip only).
  Formation: first CLOSE through the last swing high/low spawns the OB.
    The zone is the range of the most extreme bar between the swing bar and
    the break bar (lowest bar for bullish OB, highest for bearish) — the
    origin that "explains" the displacement. `use_body` uses body ranges.
  Breaker: a body close through the OB's far edge flips it into a breaker
    (bullish OB -> bearish breaker and mirror). A close back beyond the
    near edge removes it (failed/accepted through).
  Display: last `show_last` zones per side (script default 3).

Luap layer (Part 5/6, 04_order_blocks): each zone carries a lifecycle
  status — FRESH (untouched), MITIGATED (wick touched, still valid),
  BREAKER (body-flipped). Mitigated zones stay valid (wick only).
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class OBDirection(Enum):
    BULLISH = "bullish"  # effective side (breakers already flipped)
    BEARISH = "bearish"


@dataclass
class OBLevel:
    """A single Order Block / Breaker Block zone."""
    direction: OBDirection
    top: float
    bottom: float
    formation_index: int          # iloc of the origin (extreme) bar
    candle_time: pd.Timestamp     # time of the break (birth) bar
    birth_index: int = 0          # iloc of the close-through bar
    is_breaker: bool = False
    break_index: Optional[int] = None
    mitigated: bool = False
    forming_candle_indices: List[int] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def kind(self) -> str:
        return "BREAKER" if self.is_breaker else "OB"

    @property
    def status(self) -> str:
        if self.is_breaker:
            return "BREAKER"
        return "MITIGATED" if self.mitigated else "FRESH"

    def __repr__(self) -> str:
        return (
            f"OBLevel({self.kind} {self.direction.value} "
            f"[{self.bottom:.5f}..{self.top:.5f}] [idx={self.formation_index}] "
            f"{self.status})"
        )


class OBDetector:
    """
    Detects Order Block / Breaker Block zones on OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    swing_length : int
        Swing lookback (script default 10, min 3).
    use_body : bool
        Zone from candle bodies instead of full ranges (script option).
    show_last : int
        Keep only the last N zones per side (script defaults 3/3).
    """

    def __init__(self, df: pd.DataFrame, swing_length: int = 10,
                 use_body: bool = False, show_last: int = 3):
        self._validate(df)
        self.df = df.copy()
        self.swing_length = swing_length
        self.use_body = use_body
        self.show_last = show_last
        self._levels: List[OBLevel] = []

    def detect_all(self) -> List[OBLevel]:
        self._levels = []
        o = self.df["open"].values
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        times = self.df.index
        n = len(self.df)
        L = self.swing_length

        bhi = [max(a, b) for a, b in zip(o, c)] if self.use_body else None
        blo = [min(a, b) for a, b in zip(o, c)] if self.use_body else None
        hi = (lambda i: bhi[i]) if self.use_body else (lambda i: h[i])
        lo = (lambda i: blo[i]) if self.use_body else (lambda i: l[i])

        intra: Optional[int] = None
        top = None      # [price, idx, crossed]
        btm = None
        bull: list = []  # dicts: top, btm, loc, breaker, break_loc, mitigated
        bear: list = []

        for t in range(L, n):
            cand = t - L
            if h[cand] > max(h[cand + 1:t + 1]):
                if intra != 0:
                    intra = 0
                    top = [float(h[cand]), cand, False]
            elif l[cand] < min(l[cand + 1:t + 1]):
                if intra != 1:
                    intra = 1
                    btm = [float(l[cand]), cand, False]

            # Bullish OB: first close above the last swing high.
            if top is not None and not top[2] and c[t - 1] <= top[0] and c[t] > top[0]:
                top[2] = True
                zone = self._origin(top[1], t, hi, lo, bullish=True)
                if zone is not None:
                    ztop, zbtm, loc = zone
                    bull.append({"top": ztop, "btm": zbtm, "loc": loc,
                                 "birth": t, "breaker": False,
                                 "break_loc": None, "mitigated": False})
            # Bearish OB: first close below the last swing low.
            if btm is not None and not btm[2] and c[t - 1] >= btm[0] and c[t] < btm[0]:
                btm[2] = True
                zone = self._origin(btm[1], t, hi, lo, bullish=False)
                if zone is not None:
                    ztop, zbtm, loc = zone
                    bear.append({"top": ztop, "btm": zbtm, "loc": loc,
                                 "birth": t, "breaker": False,
                                 "break_loc": None, "mitigated": False})

            # Lifecycle: breaker flips, wick touches, acceptance removals.
            for z in bull:
                if not z["breaker"]:
                    if min(o[t], c[t]) < z["btm"]:
                        z["breaker"] = True
                        z["break_loc"] = t
                    elif l[t] < z["top"]:
                        z["mitigated"] = True
                elif c[t] > z["top"]:
                    z["dead"] = True
            for z in bear:
                if not z["breaker"]:
                    if max(o[t], c[t]) > z["top"]:
                        z["breaker"] = True
                        z["break_loc"] = t
                    elif h[t] > z["btm"]:
                        z["mitigated"] = True
                elif c[t] < z["btm"]:
                    z["dead"] = True
            bull = [z for z in bull if not z.get("dead")]
            bear = [z for z in bear if not z.get("dead")]

        for z in bull[-self.show_last:]:
            self._levels.append(OBLevel(
                direction=(OBDirection.BEARISH if z["breaker"] else OBDirection.BULLISH),
                top=z["top"], bottom=z["btm"], formation_index=z["loc"],
                candle_time=times[z["birth"]], birth_index=z["birth"],
                is_breaker=z["breaker"], break_index=z["break_loc"],
                mitigated=z["mitigated"],
                forming_candle_indices=[z["loc"], z["birth"]],
            ))
        for z in bear[-self.show_last:]:
            self._levels.append(OBLevel(
                direction=(OBDirection.BULLISH if z["breaker"] else OBDirection.BEARISH),
                top=z["top"], bottom=z["btm"], formation_index=z["loc"],
                candle_time=times[z["birth"]], birth_index=z["birth"],
                is_breaker=z["breaker"], break_index=z["break_loc"],
                mitigated=z["mitigated"],
                forming_candle_indices=[z["loc"], z["birth"]],
            ))
        self._levels.sort(key=lambda lv: lv.birth_index)
        return self._levels

    def _origin(self, swing_idx: int, break_idx: int, hi, lo, bullish: bool):
        """Range of the most extreme bar strictly between swing and break.
        Falls back to the pre-break bar (script behavior) if adjacent."""
        rng = list(range(swing_idx + 1, break_idx)) or [break_idx - 1]
        if bullish:
            bar = min(rng, key=lambda i: lo(i))
        else:
            bar = max(rng, key=lambda i: hi(i))
        return (float(hi(bar)), float(lo(bar)), bar)

    @property
    def levels(self) -> List[OBLevel]:
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
