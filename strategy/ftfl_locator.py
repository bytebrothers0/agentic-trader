"""
ftfl_locator.py — MSNR First Time Frame Level (FTFL) Locator

Rules (from Advanced MSNR, Videos 5, 6, 7, 10, 11):
  1. Immediately After Storyline Formed:
     - Priority 1: Fresh Support (for Buys) / Fresh Resistance (for Sells) -> A+ setup.
     - Priority 2: Fresh QM (ABQM > FTQM > STQM) -> A+ setup.
     - Priority 3: sOCL / rOCL (only when the S/R that caused rejection is mitigated).

  2. Continuation Mode (when price creates continuation candles):
     - Check Previous Candle (PC):
       - If PC did NOT break any key level -> FTFL = 1-Lap OCL of PC.
       - If PC DID break key levels -> FTFL = QM created by that break (ABQM + FTQM > FTQM > STQM).
       - (RBS/SBR on FTFL only used with reduced 10-20% risk).

  3. FTFL Box Construction:
     - Drawn from the candle body close line to the tip of the wick (lowest wick for Support, highest wick for Resistance).
     - Extended 1 step to the right (into next candle space).
     - Defines the exact zone to search for the Second Time Frame Level (STFL).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import pandas as pd

from indicators.candle_analyzer import CandleAnalyzer, CandleLevel, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.ocl_detector import OCLDetector, OCLLevel, OCLType
from indicators.qm_detector import QMDetector, QMLevel, QMType, QMDirection
from indicators.apex_detector import ApexDetector, ApexLevel, ApexType  # GAP 2: iAB support
from strategy.storyline_engine import BiasDirection, StorylineEvent


class FTFLPriority(Enum):
    A_PLUS = "A_PLUS"          # Fresh S/R or ABQM (100% Risk)
    STANDARD = "STANDARD"      # 1-Lap OCL or FTQM (70-100% Risk)
    REDUCED = "REDUCED"        # Mitigated / SBR / RBS (20% Risk)


@dataclass
class FTFLZone:
    """Represents a located FTFL key zone with its refinement box."""
    timeframe: str              # e.g., 'W1', 'D1'
    direction: BiasDirection    # BULLISH (Support) or BEARISH (Resistance)
    price: float                # Base level price (body close)
    box_top: float              # Upper boundary of box (highest wick/body)
    box_bottom: float           # Lower boundary of box (lowest wick/body)
    time_formed: pd.Timestamp
    candle_index: int
    level_type_desc: str
    priority: FTFLPriority = FTFLPriority.STANDARD
    is_fresh: bool = True

    # Midpoint of the box (used for equilibrium refinement fallback)
    @property
    def equilibrium(self) -> float:
        return (self.box_top + self.box_bottom) / 2.0

    def __repr__(self) -> str:
        return (
            f"FTFLZone({self.timeframe} {self.direction.value} @ {self.price:.2f} | "
            f"Box: [{self.box_bottom:.2f} - {self.box_top:.2f}] | {self.level_type_desc} | {self.priority.value})"
        )


class FTFLLocator:
    """
    Locates valid FTFL zones and computes bounding refinement boxes.
    """

    def __init__(self, df: pd.DataFrame, timeframe: str = "D1"):
        self.df = df.copy()
        self.timeframe = timeframe.upper()

    def find_ftfl(self, storyline: StorylineEvent) -> Optional[FTFLZone]:
        """
        Find the active FTFL zone matching the current Storyline bias.

        Mode selection per Videos 5 vs 6:
          - Immediate mode (storyline formed within the last ~3 FTFL bars):
            fresh S/R -> QM -> LS OCL -> iAB -> sOCL/rOCL/1-Lap priority.
          - Continuation mode (older storyline, market creating new candles):
            Previous-Candle rule: PC broke a key level -> that QM;
            PC broke nothing -> 1-Lap OCL box of the PC (Video 6).
        """
        if storyline.bias == BiasDirection.NEUTRAL:
            return None

        is_bullish = storyline.bias == BiasDirection.BULLISH
        df = self.df
        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        times = df.index

        if len(df) < 5:
            return None

        # 1. Detect all indicators on this FTFL timeframe
        analyzer = CandleAnalyzer(df)
        sr_levels = analyzer.detect_all()
        tracker = FreshnessTracker(df)
        sr_levels = tracker.update(sr_levels)

        ocl_det = OCLDetector(df, timeframe=self.timeframe)
        ocls = ocl_det.detect_all()

        qm_det = QMDetector(df, sr_levels)
        qms = qm_det.detect_all()

        # GAP 2: Detect iAB apex levels for use as FTFL (Video 3)
        apex_det = ApexDetector(df, timeframe=self.timeframe)
        apexes = apex_det.detect_all()

        # 2. Continuation mode (Video 6): storyline is older than ~3 FTFL bars,
        # so the market is extending without returning to origin. Apply the
        # Previous-Candle rule before falling back to immediate-mode priority.
        if self._bars_since_breakout(storyline) > 3:
            cont_zone = self._continuation_ftfl(
                storyline, is_bullish, sr_levels, qms,
            )
            if cont_zone is not None:
                return cont_zone
            # QM-from-break not yet confirmable (needs a future break bar):
            # fall through to immediate-mode priority levels.

        # Priority 1: Fresh S/R (A+ setup)
        target_sr_type = LevelType.SUPPORT if is_bullish else LevelType.RESISTANCE
        matching_sr = [
            lv for lv in sr_levels 
            if lv.level_type == target_sr_type and lv.state == LevelState.FRESH
        ]
        if matching_sr:
            # Pick the most recent fresh S/R
            best_sr = matching_sr[-1]
            idx = best_sr.candle_index
            box_top = max(highs[idx], highs[min(idx+1, len(df)-1)])
            box_bottom = min(lows[idx], lows[min(idx+1, len(df)-1)])

            return FTFLZone(
                timeframe=self.timeframe,
                direction=storyline.bias,
                price=best_sr.price,
                box_top=box_top,
                box_bottom=box_bottom,
                time_formed=best_sr.candle_time,
                candle_index=idx,
                level_type_desc="Fresh Support" if is_bullish else "Fresh Resistance",
                priority=FTFLPriority.A_PLUS,
                is_fresh=True
            )

        # Priority 2a: Fresh QM (ABQM > FTQM)
        target_qm_dir = QMDirection.BULLISH if is_bullish else QMDirection.BEARISH
        matching_qms = [
            qm for qm in qms 
            if qm.direction == target_qm_dir and qm.state == LevelState.FRESH
        ]
        if matching_qms:
            # Sort ABQM first
            matching_qms.sort(key=lambda q: 0 if q.qm_type == QMType.ABQM else 1)
            best_qm = matching_qms[0]
            idx = best_qm.break_candle_index

            return FTFLZone(
                timeframe=self.timeframe,
                direction=storyline.bias,
                price=best_qm.price,
                box_top=best_qm.box_high,
                box_bottom=best_qm.box_low,
                time_formed=best_qm.candle_time,
                candle_index=idx,
                level_type_desc=f"{best_qm.qm_type.value.upper()} QM",
                priority=FTFLPriority.A_PLUS if best_qm.qm_type == QMType.ABQM else FTFLPriority.STANDARD,
                is_fresh=True
            )

        # ---------------------------------------------------------------
        # GAP 1 FIX: Priority 2b — LS OCL (Video 2)
        # An OCL broken twice acts like a QM on the 3rd approach.
        # Most powerful on Daily and Weekly timeframes.
        # ---------------------------------------------------------------
        matching_ls_ocl = [
            ocl for ocl in ocls
            if ocl.ocl_type == OCLType.LS_OCL and ocl.state == LevelState.FRESH
        ]
        if matching_ls_ocl:
            best_ls = matching_ls_ocl[-1]  # Most recent
            idx = best_ls.candle_index_1

            return FTFLZone(
                timeframe=self.timeframe,
                direction=storyline.bias,
                price=best_ls.price,
                box_top=best_ls.box_high,
                box_bottom=best_ls.box_low,
                time_formed=best_ls.candle_time,
                candle_index=idx,
                level_type_desc="LS OCL (QM-Equivalent, 3rd Approach)",
                priority=FTFLPriority.STANDARD,  # Strong but slightly below ABQM
                is_fresh=True
            )

        # ---------------------------------------------------------------
        # GAP 2 FIX: Priority 2c — iAB (Internal Apex Break) Levels (Video 3)
        # An internal swing that caused a structural breakout is a valid
        # strong S/R level, eligible as FTFL.
        # ---------------------------------------------------------------
        target_iab_type = ApexType.IAB_SUPPORT if is_bullish else ApexType.IAB_RESISTANCE
        matching_iabs = [
            ap for ap in apexes
            if ap.apex_type == target_iab_type and ap.state == LevelState.FRESH
        ]
        if matching_iabs:
            best_iab = matching_iabs[-1]
            idx = best_iab.candle_index
            box_top = max(highs[idx], highs[min(idx+1, len(df)-1)])
            box_bottom = min(lows[idx], lows[min(idx+1, len(df)-1)])

            return FTFLZone(
                timeframe=self.timeframe,
                direction=storyline.bias,
                price=best_iab.price,
                box_top=box_top,
                box_bottom=box_bottom,
                time_formed=best_iab.candle_time,
                candle_index=idx,
                level_type_desc="iAB (Internal Apex Break)",
                priority=FTFLPriority.STANDARD,
                is_fresh=True
            )

        # Priority 3: 1-Lap OCL or sOCL/rOCL
        target_ocl_type = OCLType.SOCL if is_bullish else OCLType.ROCL
        matching_ocls = [
            ocl for ocl in ocls
            if ocl.ocl_type in (target_ocl_type, OCLType.ONE_LAP) and ocl.state == LevelState.FRESH
        ]
        if matching_ocls:
            best_ocl = matching_ocls[-1]
            idx = best_ocl.candle_index_1

            return FTFLZone(
                timeframe=self.timeframe,
                direction=storyline.bias,
                price=best_ocl.price,
                box_top=best_ocl.box_high,
                box_bottom=best_ocl.box_low,
                time_formed=best_ocl.candle_time,
                candle_index=idx,
                level_type_desc=f"{best_ocl.ocl_type.value.upper()}",
                priority=FTFLPriority.STANDARD,
                is_fresh=True
            )

        return None

    # ------------------------------------------------------------------
    # Continuation mode (Video 6): Previous-Candle rule
    # ------------------------------------------------------------------

    def _bars_since_breakout(self, storyline: StorylineEvent) -> int:
        """FTFL bars elapsed since the storyline breakout (0 = just formed)."""
        try:
            matching = [idx for idx, t in enumerate(self.df.index) if t >= storyline.breakout_time]
            if not matching:
                return 0
            return max(0, (len(self.df) - 1) - matching[0])
        except Exception:
            return 0

    def _continuation_ftfl(
        self,
        storyline: StorylineEvent,
        is_bullish: bool,
        sr_levels: List[CandleLevel],
        qms: List[QMLevel],
    ) -> Optional[FTFLZone]:
        """
        Video 6 continuation: inspect the Previous Candle (most recent closed bar).
          - Scenario B: PC broke a key level -> FTFL is the QM created by that
            break (ABQM > IABQM > FTQM > STQM).
          - Scenario A: PC broke nothing -> FTFL is the 1-Lap OCL box of the PC:
            body close to wick tip (low wick for bullish continuation, high wick
            for bearish), the spec-exact one-sided box.
        """
        df = self.df
        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        times = df.index
        pc_idx = len(df) - 1
        pc_close = closes[pc_idx]
        pc_open = opens[pc_idx]

        # Which S/R levels did the PC body-close through?
        broken = []
        for lv in sr_levels:
            if lv.candle_index >= pc_idx:
                continue
            if lv.level_type in (LevelType.SUPPORT, LevelType.RBS) and pc_close < lv.price:
                broken.append(lv)
            elif lv.level_type in (LevelType.RESISTANCE, LevelType.SBR) and pc_close > lv.price:
                broken.append(lv)

        if broken:
            # Scenario B: QM created by that break becomes the FTFL.
            target_qm_dir = QMDirection.BULLISH if is_bullish else QMDirection.BEARISH
            cands = [
                qm for qm in qms
                if qm.direction == target_qm_dir
                and abs(qm.break_candle_index - pc_idx) <= 3
            ]
            if cands:
                rank = {QMType.ABQM: 0, QMType.IABQM: 1, QMType.FTQM: 2, QMType.STQM: 3}
                cands.sort(key=lambda q: (rank.get(q.qm_type, 4), -q.break_candle_index))
                best_qm = cands[0]
                return FTFLZone(
                    timeframe=self.timeframe,
                    direction=storyline.bias,
                    price=best_qm.price,
                    box_top=best_qm.box_high,
                    box_bottom=best_qm.box_low,
                    time_formed=best_qm.candle_time,
                    candle_index=best_qm.break_candle_index,
                    level_type_desc=f"Continuation {best_qm.qm_type.value.upper()} QM (PC break)",
                    priority=FTFLPriority.A_PLUS if best_qm.qm_type == QMType.ABQM else FTFLPriority.STANDARD,
                    is_fresh=best_qm.state == LevelState.FRESH,
                )
            # Break detected but QM not yet confirmable -> fall through to standard.
            return None

        # Scenario A: 1-Lap OCL box of the PC (spec-exact one-sided geometry).
        if pc_close >= pc_open:
            # Bullish PC: body close on top, wick tip below.
            price = float(pc_close)
            box_top = float(pc_close)
            box_bottom = float(min(lows[pc_idx], pc_close))
        else:
            # Bearish PC: body close at bottom, wick tip above.
            price = float(pc_close)
            box_top = float(max(highs[pc_idx], pc_close))
            box_bottom = float(pc_close)
        return FTFLZone(
            timeframe=self.timeframe,
            direction=storyline.bias,
            price=price,
            box_top=box_top,
            box_bottom=box_bottom,
            time_formed=times[pc_idx],
            candle_index=pc_idx,
            level_type_desc="Continuation 1-Lap OCL (PC)",
            priority=FTFLPriority.STANDARD,
            is_fresh=True,
        )
