"""
ob_detector.py — Order Blocks + Breaker Blocks (web Alchemist math).

  Formation: first CLOSE through the last swing high/low spawns the OB.
    The zone is the LAST OPPOSITE-COLOUR candle before the displacement
    (bullish OB: last bearish candle in swing..break; zone = its high/low).
    Falls back to the most extreme bar if no opposite candle exists.
  Valid OB: the origin swept the previous extreme (liquidity grab) OR the
    break bar displaced (range >= displacement_mult x median prior-20 range)
    — i.e. only OBs that caused a sweep or broke a level with force.
    FVG overlap is CONFLUENCE (scorer's job), not a validity gate.
  Breaker: a body CLOSE through the OB's far edge flips it (bullish OB ->
    bearish breaker and mirror). Wick dips without close-through only
    mitigate. A close back beyond the near edge removes it.
  Display: last `show_last` zones per side.
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
    ob_type: str = ""              # Luap: "EXTREME" | "DECISIONAL" | ""
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
    require_fvg : bool
        Confluence gate (default False): zone needs an overlapping
        same-side FVG. Web-exact is False — FVG overlap scores entries,
        it does not decide OB existence.
    require_sweep : bool
        Liquidity-grab gate (default True): origin swept the previous
        extreme, OR the break bar displaced (>= displacement_mult x
        median prior-20 range). Slow overlapping moves with neither are
        "Engineered OBs" and ignored.
    displacement_mult : float
        Break-bar range multiple over the median prior-20 range that
        counts as displacement. Default 1.5.
    mark_decisional : bool
        Tag zones near same-side IDM as DECISIONAL, else EXTREME.
        Default True (metadata only).
    """

    def __init__(self, df: pd.DataFrame, swing_length: int = 10,
                 use_body: bool = False, show_last: int = 3,
                 require_fvg: bool = False, require_sweep: bool = True,
                 displacement_mult: float = 1.5,
                 mark_decisional: bool = True):
        self._validate(df)
        self.df = df.copy()
        self.swing_length = swing_length
        self.use_body = use_body
        self.show_last = show_last
        self.require_fvg = require_fvg
        self.require_sweep = require_sweep
        self.displacement_mult = displacement_mult
        self.mark_decisional = mark_decisional
        self._levels: List[OBLevel] = []
        rng = (self.df["high"] - self.df["low"]).astype(float)
        self._med_range = rng.rolling(20, min_periods=1).median().tolist()

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

        # Luap FVG filter needs gap levels up front (any state counts —
        # the gap existed at formation even if later mitigated).
        fvg_levels = []
        if self.require_fvg:
            try:
                from indicators.fvg_detector import FVGDetector
                fvg_levels = FVGDetector(self.df).detect_all()
            except Exception:
                fvg_levels = []

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
                if zone is not None and self._valid_ob(
                        zone[2], t, zone[0], zone[1], True, fvg_levels):
                    ztop, zbtm, loc = zone
                    bull.append({"top": ztop, "btm": zbtm, "loc": loc,
                                 "birth": t, "breaker": False,
                                 "break_loc": None, "mitigated": False})
            # Bearish OB: first close below the last swing low.
            if btm is not None and not btm[2] and c[t - 1] >= btm[0] and c[t] < btm[0]:
                btm[2] = True
                zone = self._origin(btm[1], t, hi, lo, bullish=False)
                if zone is not None and self._valid_ob(
                        zone[2], t, zone[0], zone[1], False, fvg_levels):
                    ztop, zbtm, loc = zone
                    bear.append({"top": ztop, "btm": zbtm, "loc": loc,
                                 "birth": t, "breaker": False,
                                 "break_loc": None, "mitigated": False})

            # Lifecycle: breaker flips, wick touches, acceptance removals.
            # Bars at/before a zone's birth predate its existence and can
            # never mitigate or flip it (else old history would mark every
            # zone touched on sight).
            for z in bull:
                if t <= z["birth"]:
                    continue
                if not z["breaker"]:
                    if c[t] < z["btm"]:
                        z["breaker"] = True
                        z["break_loc"] = t
                    elif l[t] < z["top"]:
                        z["mitigated"] = True
                elif c[t] > z["top"]:
                    z["dead"] = True
            for z in bear:
                if t <= z["birth"]:
                    continue
                if not z["breaker"]:
                    if c[t] > z["top"]:
                        z["breaker"] = True
                        z["break_loc"] = t
                    elif h[t] > z["btm"]:
                        z["mitigated"] = True
                elif c[t] < z["btm"]:
                    z["dead"] = True
            bull = [z for z in bull if not z.get("dead")]
            bear = [z for z in bear if not z.get("dead")]

        self._mark_types(bull, bear)
        for z in bull[-self.show_last:]:
            self._levels.append(OBLevel(
                direction=(OBDirection.BEARISH if z["breaker"] else OBDirection.BULLISH),
                top=z["top"], bottom=z["btm"], formation_index=z["loc"],
                candle_time=times[z["birth"]], birth_index=z["birth"],
                is_breaker=z["breaker"], break_index=z["break_loc"],
                mitigated=z["mitigated"], ob_type=z.get("ob_type", ""),
                forming_candle_indices=[z["loc"], z["birth"]],
            ))
        for z in bear[-self.show_last:]:
            self._levels.append(OBLevel(
                direction=(OBDirection.BULLISH if z["breaker"] else OBDirection.BEARISH),
                top=z["top"], bottom=z["btm"], formation_index=z["loc"],
                candle_time=times[z["birth"]], birth_index=z["birth"],
                is_breaker=z["breaker"], break_index=z["break_loc"],
                mitigated=z["mitigated"], ob_type=z.get("ob_type", ""),
                forming_candle_indices=[z["loc"], z["birth"]],
            ))
        self._levels.sort(key=lambda lv: lv.birth_index)
        return self._levels

    def _origin(self, swing_idx: int, break_idx: int, hi, lo, bullish: bool):
        """Last opposite-colour candle strictly between swing and break
        (web-exact OB origin). Falls back to the most extreme bar (script
        behavior) when no opposite candle exists or bars are adjacent."""
        o = self.df["open"].values
        c = self.df["close"].values
        rng = list(range(swing_idx + 1, break_idx)) or [break_idx - 1]
        for i in reversed(rng):
            if bullish and c[i] < o[i]:
                return (float(hi(i)), float(lo(i)), i)
            if not bullish and c[i] > o[i]:
                return (float(hi(i)), float(lo(i)), i)
        if bullish:
            bar = min(rng, key=lambda i: lo(i))
        else:
            bar = max(rng, key=lambda i: hi(i))
        return (float(hi(bar)), float(lo(bar)), bar)

    def _displaced(self, birth: int) -> bool:
        """Break bar ranged >= displacement_mult x median prior-20 range."""
        try:
            med = self._med_range[max(0, birth - 1)]
        except IndexError:
            return False
        if not (med and med > 0):
            return True
        h = self.df["high"].values
        l = self.df["low"].values
        return bool(h[birth] - l[birth] >= self.displacement_mult * med)

    def _valid_ob(self, loc: int, birth: int, ztop: float, zbtm: float,
                  bullish: bool, fvg_levels) -> bool:
        """Web validity: sweep (liquidity grab) OR displacement break.
        FVG overlap is confluence, gated separately."""
        o = self.df["open"].values
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        if self.require_sweep and not (
                self._has_sweep(loc, bullish, o, h, l, c)
                or self._displaced(birth)):
            return False
        if self.require_fvg and not self._has_gap(
                birth, ztop, zbtm, bullish, fvg_levels):
            return False
        return True

    @staticmethod
    def _has_sweep(loc: int, bullish: bool, o, h, l, c) -> bool:
        """Origin candle took the previous candle's extreme with a longer
        swept-side wick (Part 6: liquidity grab; else 'Weak OB')."""
        if loc <= 0:
            return False
        if bullish:
            if not (l[loc] < l[loc - 1]):
                return False
            wick = min(o[loc], c[loc]) - l[loc]
            prev = min(o[loc - 1], c[loc - 1]) - l[loc - 1]
            return bool(wick > prev)
        if not (h[loc] > h[loc - 1]):
            return False
        wick = h[loc] - max(o[loc], c[loc])
        prev = h[loc - 1] - max(o[loc - 1], c[loc - 1])
        return bool(wick > prev)

    @staticmethod
    def _has_gap(birth: int, ztop: float, zbtm: float, bullish: bool,
                 fvg_levels) -> bool:
        """A same-direction FVG overlaps the zone, formed around/after the
        break (the displacement gap; slow overlapping moves have none)."""
        for z in fvg_levels:
            try:
                same_side = (z.direction.value == "bullish") == bullish
            except Exception:
                same_side = True
            if not same_side:
                continue
            if z.formation_index < birth - 2:
                continue
            # The gap starts at/inside the zone edge (its bottom IS the
            # OB extreme in the textbook shape) — boundary touch counts.
            if zbtm <= z.top and z.bottom <= ztop:
                return True
        return False

    def _mark_types(self, bull: list, bear: list) -> None:
        """Luap decision point: zones near same-side IDM liquidity are
        Decisional, move origins are Extreme. Metadata only."""
        if not self.mark_decisional:
            return
        try:
            from indicators.idm_detector import IDMDetector, IDMType
            idms = IDMDetector(self.df).detect_all()
        except Exception:
            return
        lows = [(v.price, v.formation_index) for v in idms
                if v.idm_type == IDMType.IDM_LOW]
        highs = [(v.price, v.formation_index) for v in idms
                 if v.idm_type == IDMType.IDM_HIGH]
        for z, pool in ((bull, lows), (bear, highs)):
            for d in z:
                pad = max((d["top"] - d["btm"]) * 0.05, 1e-9)
                near = any(d["btm"] - pad <= p <= d["top"] + pad
                           for p, f in pool)
                d["ob_type"] = "DECISIONAL" if near else "EXTREME"

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
