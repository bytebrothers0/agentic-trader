"""
qm_detector.py — MSNR Quasimodo (QM) Indicator

Rules (from Advanced MSNR, Videos 3, 6, 7, 8, 12):
  - QM = Failed SBR or Failed RBS.
  - Bullish QM (Buy QM):
      1. Support formed at Price P.
      2. Price drops and body-closes below P (Support becomes SBR).
      3. Price rallies and body-closes back ABOVE P (Failed SBR -> Bullish QM).
      4. P is now the Quasimodo Level (Left Shoulder).
  - Bearish QM (Sell QM):
      1. Resistance formed at Price P.
      2. Price rallies and body-closes above P (Resistance becomes RBS).
      3. Price drops and body-closes back BELOW P (Failed RBS -> Bearish QM).
      4. P is now the Quasimodo Level (Left Shoulder).

Subtypes & Priority:
  1. ABQM (Apex Break QM): The candle that forms the preceding extreme peak/trough
     is the SAME candle that breaks the old SBR/RBS. (Rank 1 / Highest strength).
  2. FTQM (First Time QM): The first time this price level transitions to a QM. (Rank 2).
  3. STQM (Second Time QM): The second time this zone transitions to a QM. (Rank 3).
  4. IABQM (Internal Apex Break QM): QM derived from an internal structure apex break.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import pandas as pd

from indicators.candle_analyzer import CandleLevel, LevelType, LevelState


class QMType(Enum):
    ABQM = "abqm"      # Apex Break QM (Highest strength)
    FTQM = "ftqm"      # First Time QM
    STQM = "stqm"      # Second Time QM
    IABQM = "iabqm"    # Internal Apex Break QM


class QMDirection(Enum):
    BULLISH = "bullish"  # Buy QM (Failed SBR)
    BEARISH = "bearish"  # Sell QM (Failed RBS)


@dataclass
class QMLevel:
    """Represents a Quasimodo (QM) key level."""
    qm_type: QMType
    direction: QMDirection
    price: float                # The left shoulder price
    origin_candle_index: int    # iloc where original S/R was formed
    flip_candle_index: int      # iloc where it flipped to SBR/RBS
    break_candle_index: int     # iloc where SBR/RBS failed and became QM
    candle_time: pd.Timestamp
    state: LevelState = LevelState.FRESH

    # Wick box bounds for refinement
    box_high: float = 0.0
    box_low: float = 0.0

    forming_candle_indices: List[int] = field(default_factory=list)
    first_touch_index: Optional[int] = None
    # Life-cycle end for zone-to-zone chart rays: iloc of first wick touch
    # ("mitigated") or later close-through ("broken", overwrites the touch end).
    end_candle_index: Optional[int] = None
    end_kind: str = "active"    # "active" | "mitigated" | "broken"

    def to_candle_level(self) -> CandleLevel:
        """Adapter to CandleLevel format."""
        lvl_type = LevelType.SUPPORT if self.direction == QMDirection.BULLISH else LevelType.RESISTANCE
        return CandleLevel(
            level_type=lvl_type,
            price=self.price,
            candle_index=self.break_candle_index,
            candle_time=self.candle_time,
            state=self.state,
            forming_candle_indices=self.forming_candle_indices,
            first_touch_index=self.first_touch_index
        )

    def __repr__(self) -> str:
        return (
            f"QMLevel({self.qm_type.value.upper()} {self.direction.value} @ {self.price:.5f} "
            f"[{self.candle_time.date()}] state={self.state.value})"
        )


class QMDetector:
    """
    Detects Quasimodo levels from OHLCV data and SBR/RBS levels.
    """

    def __init__(self, df: pd.DataFrame, base_levels: Optional[List[CandleLevel]] = None):
        self.df = df.copy()
        self.base_levels = base_levels or []
        self._qm_levels: List[QMLevel] = []

    def detect_all(
        self,
        base_levels: Optional[List[CandleLevel]] = None,
        apex_levels: Optional[List] = None,
    ) -> List[QMLevel]:
        """
        Run QM detection on SBR and RBS levels.

        Subtype classification per Video 3 (structural, not distance-based):
          - ABQM: the failed level coincides with an external Apex break
            (Apex Support broken -> SBR -> failed back above, or mirror).
          - IABQM: the failed level coincides with an internal (iAB) break.
          - FTQM: first time this price zone becomes a QM.
          - STQM: second+ time the same zone becomes a QM.
        """
        if base_levels is not None:
            self.base_levels = base_levels
        self._qm_levels = []

        df = self.df
        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        times = df.index

        # Structural context: detect Apex / iAB levels once (HTF semantics inside).
        if apex_levels is None:
            try:
                from indicators.apex_detector import ApexDetector
                apex_levels = ApexDetector(df, timeframe="D1").detect_all()
            except Exception:
                apex_levels = []
        self._apex_levels = list(apex_levels or [])

        # Find all SBR and RBS levels
        sbr_levels = [lv for lv in self.base_levels if lv.level_type == LevelType.SBR]
        rbs_levels = [lv for lv in self.base_levels if lv.level_type == LevelType.RBS]

        # 1. Check Failed SBR -> Bullish QM (Price breaks back above SBR)
        for sbr in sbr_levels:
            origin_idx = sbr.derived_from.candle_index if sbr.derived_from else sbr.candle_index
            start_i = sbr.candle_index + 1
            for i in range(start_i, len(df)):
                body_low = min(opens[i], closes[i])
                # Body closes above SBR price -> SBR failed!
                if closes[i] > sbr.price and body_low >= sbr.price:
                    qm_type = self._classify_qm_subtype(
                        price=sbr.price,
                        origin_idx=origin_idx,
                        flip_idx=sbr.candle_index,
                        break_idx=i,
                        is_bullish=True,
                    )

                    # Box calculation
                    box_high = max(highs[sbr.candle_index:i+1])
                    box_low = min(lows[sbr.candle_index:i+1])

                    self._qm_levels.append(QMLevel(
                        qm_type=qm_type,
                        direction=QMDirection.BULLISH,
                        price=sbr.price,
                        origin_candle_index=origin_idx,
                        flip_candle_index=sbr.candle_index,
                        break_candle_index=i,
                        candle_time=times[i],
                        box_high=box_high,
                        box_low=box_low,
                        forming_candle_indices=[sbr.candle_index, i]
                    ))
                    break

        # 2. Check Failed RBS -> Bearish QM (Price breaks back below RBS)
        for rbs in rbs_levels:
            origin_idx = rbs.derived_from.candle_index if rbs.derived_from else rbs.candle_index
            start_i = rbs.candle_index + 1
            for i in range(start_i, len(df)):
                body_high = max(opens[i], closes[i])
                # Body closes below RBS price -> RBS failed!
                if closes[i] < rbs.price and body_high <= rbs.price:
                    qm_type = self._classify_qm_subtype(
                        price=rbs.price,
                        origin_idx=origin_idx,
                        flip_idx=rbs.candle_index,
                        break_idx=i,
                        is_bullish=False,
                    )

                    box_high = max(highs[rbs.candle_index:i+1])
                    box_low = min(lows[rbs.candle_index:i+1])

                    self._qm_levels.append(QMLevel(
                        qm_type=qm_type,
                        direction=QMDirection.BEARISH,
                        price=rbs.price,
                        origin_candle_index=origin_idx,
                        flip_candle_index=rbs.candle_index,
                        break_candle_index=i,
                        candle_time=times[i],
                        box_high=box_high,
                        box_low=box_low,
                        forming_candle_indices=[rbs.candle_index, i]
                    ))
                    break

        # Classify STQM (if a price zone has multiple QMs over time)
        self._classify_stqm()
        # Freshness: wick touch -> UNFRESH, close-through -> BROKEN after formation.
        self._apply_freshness()
        return self._qm_levels

    # ------------------------------------------------------------------
    # Structural subtype classification (Video 3)
    # ------------------------------------------------------------------

    @staticmethod
    def _price_matches(a: float, b: float) -> bool:
        """Relative price match (0.05% tolerance) for cross-indicator joins."""
        if a == b:
            return True
        denom = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / denom <= 0.0005

    def _classify_qm_subtype(
        self,
        price: float,
        origin_idx: int,
        flip_idx: int,
        break_idx: int,
        is_bullish: bool,
    ) -> QMType:
        """
        ABQM: failed level coincides with an EXTERNAL Apex break (price match
        with an Apex support/resistance, or origin/flip/break within 3 bars of
        the Apex swing / its breakout candle).
        IABQM: same test against INTERNAL (iAB) levels.
        Otherwise FTQM (STQM resolved later by duplicate counting).
        """
        from indicators.apex_detector import ApexType

        if is_bullish:
            ext_types = (ApexType.APEX_SUPPORT,)
            int_types = (ApexType.IAB_SUPPORT,)
        else:
            ext_types = (ApexType.APEX_RESISTANCE,)
            int_types = (ApexType.IAB_RESISTANCE,)

        def _coincides(types) -> bool:
            for ap in self._apex_levels:
                if ap.apex_type not in types:
                    continue
                if self._price_matches(ap.price, price):
                    return True
                for ref_idx in (origin_idx, flip_idx, break_idx):
                    if abs(ref_idx - ap.candle_index) <= 3 and self._price_matches(ap.price, price):
                        return True
                    if abs(ref_idx - ap.breakout_candle_index) <= 3:
                        return True
            return False

        if _coincides(ext_types):
            return QMType.ABQM
        if _coincides(int_types):
            return QMType.IABQM
        return QMType.FTQM

    def _check_is_abqm(self, flip_idx: int, break_idx: int, is_bullish: bool) -> bool:
        """
        Legacy distance proxy kept for backward compat. Prefer structural
        _classify_qm_subtype (Apex-aware) used by detect_all.
        """
        return (break_idx - flip_idx) <= 3

    def _classify_stqm(self):
        """Identify duplicate or 2nd-time QMs on the same price level."""
        seen: List[float] = []
        for qm in self._qm_levels:
            repeat = any(self._price_matches(qm.price, p) for p in seen)
            seen.append(qm.price)
            # Structural lineages (ABQM / IABQM) keep their type on repeats.
            if repeat and qm.qm_type not in (QMType.ABQM, QMType.IABQM):
                qm.qm_type = QMType.STQM

    def _apply_freshness(self):
        """Mark QM levels UNFRESH on wick touch / BROKEN on close-through after formation."""
        df = self.df
        if len(df) == 0:
            return
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        for qm in self._qm_levels:
            start_i = qm.break_candle_index + 1
            for i in range(start_i, len(df)):
                if qm.direction == QMDirection.BULLISH:
                    if closes[i] < qm.price:
                        qm.state = LevelState.BROKEN
                        qm.end_candle_index = i
                        qm.end_kind = "broken"
                        break
                    if qm.state == LevelState.FRESH and lows[i] <= qm.price:
                        qm.state = LevelState.UNFRESH
                        qm.first_touch_index = i
                        qm.end_candle_index = i
                        qm.end_kind = "mitigated"
                else:
                    if closes[i] > qm.price:
                        qm.state = LevelState.BROKEN
                        qm.end_candle_index = i
                        qm.end_kind = "broken"
                        break
                    if qm.state == LevelState.FRESH and highs[i] >= qm.price:
                        qm.state = LevelState.UNFRESH
                        qm.first_touch_index = i
                        qm.end_candle_index = i
                        qm.end_kind = "mitigated"
