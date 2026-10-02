"""
entry_engine.py — Advanced MSNR Full Multi-Storyline Entry Engine (v2)

Complete implementation per MSNR Top-Down Analysis (Videos 4, 5, 6, 8, 9, 10, 12):

HOW THE STRATEGY WORKS (from Video 10 subtitle, the definitive guide):
------------------------------------------------------------------------
1. Determine the storyline on Monthly, Weekly, and Daily independently.
2. For each ACTIVE storyline, generate ALL valid entry zones:
   - For the WEEKLY storyline:
       a) FIRST look for a DAILY entry zone (market uses daily first before weekly)
          W1 Story → D1 FTFL → H4 STFL → H1 TTFL
       b) THEN mark the WEEKLY entry zone (deeper retracement)
          W1 Story → W1 FTFL → D1 STFL → H4 TTFL
   - For the MONTHLY storyline:
       a) FIRST look for a WEEKLY entry zone
          MN Story → W1 FTFL → D1 STFL → H4 TTFL
       b) THEN mark the MONTHLY zone
          MN Story → MN FTFL → W1 STFL → D1 TTFL
   - For the DAILY storyline:
       a) Look for a 4H entry zone (fastest / most frequent)
          D1 Story → H4 FTFL → H1 STFL → M15 TTFL (or H1 Equilibrium)
       b) THEN Daily continuation entry
          D1 Story → D1 FTFL → H4 STFL → H1 TTFL

3. The market will always use the CLOSEST entry to current price first.
   Sort all entries by distance from current price.

4. When no FTFL/STFL entry is available (market is running), use Confirmation Entry:
   Model B: 1H reject 1H (on top of D1/W1 level) + 1H breakout → 70% Eq + 30% Body
   Model C: D1W4 (1H mitigates D1 level with 1 candle + 1H breakout)

CONFIDENCE LEVELS:
  - A+ : Fresh S/R or ABQM FTFL, next-candle retracement
  - A  : Standard OCL FTFL or delayed retracement (full risk)
  - B  : Confirmation entry or cross-storyline alignment needed
  - B- : 20% risk (unfresh level, multiple-candle delay, or LS OCL used)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import pandas as pd

from strategy.storyline_engine import StorylineEngine, StorylineEvent, BiasDirection
from strategy.ftfl_locator import FTFLLocator, FTFLZone, FTFLPriority
from strategy.stfl_locator import STFLLocator, STFLZone
from strategy.ttfl_locator import TTFLLocator, TTFLRefinement, TTFLEntryType
from strategy.obstacle_scanner import ObstacleScanner, ObstacleTarget
from execution.risk_manager import RiskManager, PositionPlan
from indicators.candle_analyzer import CandleAnalyzer, LevelType, LevelState
from indicators.freshness_tracker import FreshnessTracker
from indicators.qm_detector import QMDetector, QMDirection


class EntryModelType(Enum):
    # Standard Cascade: FTFL → STFL → TTFL (per storyline TF cascade)
    MODEL_A_MN_WEEKLY  = "MN_STORY_W1_ENTRY"    # Monthly story, W1 FTFL
    MODEL_A_MN_MONTHLY = "MN_STORY_MN_ENTRY"    # Monthly story, MN FTFL (deep pullback)
    MODEL_A_W1_DAILY   = "W1_STORY_D1_ENTRY"    # Weekly story, D1 FTFL (market uses daily first)
    MODEL_A_W1_WEEKLY  = "W1_STORY_W1_ENTRY"    # Weekly story, W1 FTFL (deeper retracement)
    MODEL_A_D1_4H      = "D1_STORY_H4_ENTRY"    # Daily story, H4 FTFL (fastest entry)
    MODEL_A_D1_DAILY   = "D1_STORY_D1_ENTRY"    # Daily story, D1 FTFL (continuation)
    # Confirmation / Retracement Models
    MODEL_B_14B        = "MODEL_B_14B"           # 1H reject 1H + 1H breakout
    MODEL_C_D1W4       = "MODEL_C_D1W4"          # D1/W4 single-candle mitigation
    # Custom strategy engines (registered in strategy/registry.py)
    MODEL_TS_M15       = "TS_M15_ENTRY"          # MNSR+TS: TS → break → QM → IDM (M15)


# TF Cascade map: for each entry variant, which TF to use for FTFL, STFL, TTFL, Obstacles
# NOTE: "MN1" = Monthly. "M1" = 1-minute, never Monthly. H4-based entries refine to M15.
TF_CASCADE = {
    # Monthly storyline entries
    "MN_STORY_W1_ENTRY":  {"ftfl": "W1",  "stfl": "D1", "ttfl": "H4", "obstacle": "W1"},
    "MN_STORY_MN_ENTRY":  {"ftfl": "MN1", "stfl": "W1", "ttfl": "D1", "obstacle": "MN1"},
    # Weekly storyline entries (daily first is standard; weekly is the deeper zone)
    "W1_STORY_D1_ENTRY":  {"ftfl": "D1",  "stfl": "H4", "ttfl": "H1", "obstacle": "D1"},
    "W1_STORY_W1_ENTRY":  {"ftfl": "W1",  "stfl": "D1", "ttfl": "H4", "obstacle": "W1"},
    # Daily storyline entries (H4 entry refines H4 -> H1 -> M15; falls back to H1 eq if M15 missing)
    "D1_STORY_H4_ENTRY":  {"ftfl": "H4",  "stfl": "H1", "ttfl": "M15", "obstacle": "H4"},
    "D1_STORY_D1_ENTRY":  {"ftfl": "D1",  "stfl": "H4", "ttfl": "H1", "obstacle": "D1"},
}


@dataclass
class TradeSignal:
    """A fully computed trade signal with entry, SL, TP and metadata."""
    model_type: EntryModelType
    symbol: str
    direction: BiasDirection

    # Originating storyline
    storyline_key: str           # e.g., "W1_D1", "M1_W1", "D1_H4"
    storyline_desc: str          # Human-readable e.g., "W1 BULLISH → D1 breakout"
    storyline_rejection: float   # Price of the HTF rejection level

    # TF cascade used for this entry
    ftfl_tf: str
    stfl_tf: str
    ttfl_tf: str

    # Entry plan
    primary_plan: PositionPlan
    secondary_plan: Optional[PositionPlan] = None  # Split entries (70/30 for 14B)

    confidence: str = "A+"
    rationale: str = ""
    formation_time: int = 0      # Unix timestamp of the candle where level/rejection formed

    # Box geometry from locators
    ftfl_box_top: float = 0.0
    ftfl_box_bottom: float = 0.0
    stfl_box_top: float = 0.0
    stfl_box_bottom: float = 0.0

    # Distance from current price (populated after all signals are collected)
    distance_to_entry: float = 0.0
    priority_rank: int = 999     # Lower = closer / higher priority

    def __repr__(self) -> str:
        return (
            f"Signal({self.model_type.value} | {self.direction.value} | "
            f"Entry: {self.primary_plan.buffered_entry:.2f} | "
            f"SL: {self.primary_plan.stop_loss:.2f} | "
            f"TP: {self.primary_plan.take_profit:.2f} | Conf: {self.confidence})"
        )


class EntryEngine:
    """
    Full multi-storyline MSNR Entry Engine.

    Evaluates ALL 3 active storylines and generates ALL valid entry zones per
    the MSNR Top-Down Analysis methodology. Entries are ranked by:
      1. Proximity to current price (closest = most likely to trigger first)
      2. Confidence (A+ > A > B > B-)
    """

    def __init__(self, dataframes: Dict[str, pd.DataFrame], symbol: str = "XAUUSD"):
        self.dfs = {k.upper(): v.copy() for k, v in dataframes.items()}
        self.symbol = symbol
        self.risk_mgr = RiskManager()

    def scan_all_models(self) -> List[TradeSignal]:
        """
        Full top-down scan:
          1. Model A variants — all cascade entries per storyline
          2. Model B — 14B confirmation
          3. Model C — D1W4 retracement
        Returns all signals sorted by distance to current price (closest first).
        """
        signals: List[TradeSignal] = []

        # Step 1: Determine all active storylines
        sl_engine = StorylineEngine(self.dfs)
        storylines = sl_engine.analyze_all()

        if not storylines:
            return signals

        # Step 2: Get current price
        current_price = self._get_current_price()

        # Step 3: Generate entries for each active storyline
        # Legacy "M1_W1" key supported for backward compat (M1 formerly meant Monthly).
        mn_sl = storylines.get("MN1_W1") or storylines.get("MN_W1") or storylines.get("M1_W1")
        w1_sl = storylines.get("W1_D1") or storylines.get("W1_W1")
        d1_sl = storylines.get("D1_H4") or storylines.get("D1_D1")

        # Monthly storyline → W1 entry first (closer), then MN entry (deeper)
        if mn_sl and mn_sl.bias != BiasDirection.NEUTRAL:
            if "MN1_W1" in storylines:
                sl_key = "MN1_W1"
            elif "MN_W1" in storylines:
                sl_key = "MN_W1"
            else:
                sl_key = "M1_W1"
            sig = self._build_cascade_entry(
                storyline=mn_sl,
                sl_key=sl_key,
                model_type=EntryModelType.MODEL_A_MN_WEEKLY,
                cascade_key="MN_STORY_W1_ENTRY",
                risk_mult=1.0,
                confidence="A+"
            )
            if sig:
                signals.append(sig)

            sig_deep = self._build_cascade_entry(
                storyline=mn_sl,
                sl_key=sl_key,
                model_type=EntryModelType.MODEL_A_MN_MONTHLY,
                cascade_key="MN_STORY_MN_ENTRY",
                risk_mult=0.5,      # Deeper/older zone = reduced risk
                confidence="A"
            )
            if sig_deep:
                signals.append(sig_deep)

        # Weekly storyline → D1 entry first (market uses daily first per Video 10)
        if w1_sl and w1_sl.bias != BiasDirection.NEUTRAL:
            sig_daily_first = self._build_cascade_entry(
                storyline=w1_sl,
                sl_key="W1_D1",
                model_type=EntryModelType.MODEL_A_W1_DAILY,
                cascade_key="W1_STORY_D1_ENTRY",
                risk_mult=1.0,
                confidence="A+"
            )
            if sig_daily_first:
                signals.append(sig_daily_first)

            sig_w1_deep = self._build_cascade_entry(
                storyline=w1_sl,
                sl_key="W1_D1",
                model_type=EntryModelType.MODEL_A_W1_WEEKLY,
                cascade_key="W1_STORY_W1_ENTRY",
                risk_mult=0.7,      # Deeper weekly zone
                confidence="A"
            )
            if sig_w1_deep:
                signals.append(sig_w1_deep)

        # Daily storyline → H4 entry first (fastest), then D1 continuation
        if d1_sl and d1_sl.bias != BiasDirection.NEUTRAL:
            sig_4h = self._build_cascade_entry(
                storyline=d1_sl,
                sl_key="D1_H4",
                model_type=EntryModelType.MODEL_A_D1_4H,
                cascade_key="D1_STORY_H4_ENTRY",
                risk_mult=1.0,
                confidence="A+"
            )
            if sig_4h:
                signals.append(sig_4h)

            sig_d1 = self._build_cascade_entry(
                storyline=d1_sl,
                sl_key="D1_H4",
                model_type=EntryModelType.MODEL_A_D1_DAILY,
                cascade_key="D1_STORY_D1_ENTRY",
                risk_mult=0.7,
                confidence="A"
            )
            if sig_d1:
                signals.append(sig_d1)

        # Step 4: Model B — Confirmation entries on H1 and H4 (both directions).
        # Video 9: 1H rejects 1H + 1H breakout, 4H rejects 4H + 4H/1H breakout,
        # each rejection sitting ON a D1/W1/MN1 key level and aligned with storyline.
        for conf_tf in ["H1", "H4"]:
            if conf_tf not in self.dfs:
                continue
            for direction in [BiasDirection.BULLISH, BiasDirection.BEARISH]:
                # Only scan direction that aligns with at least one storyline
                aligned = any(
                    sl.bias == direction
                    for sl in storylines.values()
                    if sl.bias != BiasDirection.NEUTRAL
                )
                if aligned:
                    sig_b = self._evaluate_confirmation(conf_tf, direction)
                    if sig_b:
                        signals.append(sig_b)

        # Step 5: Model C — D1 Retracement (1H mitigates Daily level).
        # Returns a list: Option A S/R eq + optional Option B QM eq (Video 12).
        sig_c = self._evaluate_model_c(storylines)
        if isinstance(sig_c, list):
            signals.extend(sig_c)
        elif sig_c:
            signals.append(sig_c)

        # Step 5b: GAP 7 FIX — W4 Retracement (4H mitigates Weekly level).
        sig_c_w4 = self._evaluate_model_c_w4(storylines)
        if isinstance(sig_c_w4, list):
            signals.extend(sig_c_w4)
        elif sig_c_w4:
            signals.append(sig_c_w4)

        # Step 6: Rank by distance to current price (closest triggers first)
        for sig in signals:
            sig.distance_to_entry = abs(sig.primary_plan.buffered_entry - current_price)

        signals.sort(key=lambda s: s.distance_to_entry)
        for i, sig in enumerate(signals):
            sig.priority_rank = i + 1

        return signals

    # ------------------------------------------------------------------
    # Core Cascade Builder (Model A variants)
    # ------------------------------------------------------------------

    def _build_cascade_entry(
        self,
        storyline: StorylineEvent,
        sl_key: str,
        model_type: EntryModelType,
        cascade_key: str,
        risk_mult: float,
        confidence: str
    ) -> Optional[TradeSignal]:
        """
        Builds a full FTFL → STFL → TTFL cascade for a given storyline
        and TF cascade configuration.
        """
        cascade = TF_CASCADE.get(cascade_key)
        if not cascade:
            return None

        ftfl_tf   = cascade["ftfl"]
        stfl_tf   = cascade["stfl"]
        ttfl_tf   = cascade["ttfl"]
        obs_tf    = cascade["obstacle"]

        # Graceful TTFL fallback: M15 may be absent in tests / older caches.
        # Fall back to H1 so H4-based entries still refine instead of vanishing.
        if ttfl_tf == "M15" and "M15" not in self.dfs and "H1" in self.dfs:
            ttfl_tf = "H1"

        # Check we have the required dataframes
        for tf in [ftfl_tf, stfl_tf, ttfl_tf]:
            if tf not in self.dfs:
                return None

        # 1. FTFL — on the cascade's FTFL timeframe
        ftfl_loc = FTFLLocator(self.dfs[ftfl_tf], timeframe=ftfl_tf)
        ftfl_zone = ftfl_loc.find_ftfl(storyline)
        if not ftfl_zone:
            return None

        # Scale risk down if FTFL is not A+
        if ftfl_zone.priority != FTFLPriority.A_PLUS:
            risk_mult = min(risk_mult, 0.2)
            confidence = "B"

        # ---------------------------------------------------------------
        # GAP 3 FIX: Next-Candle Rule (Video 11)
        # The strongest entries occur when market returns to FTFL on the
        # VERY NEXT candle after the storyline forms. Delays = reduce risk.
        # ---------------------------------------------------------------
        bars_since_storyline = self._bars_since_storyline(storyline, ftfl_tf)
        if bars_since_storyline > 1 and confidence == "A+":
            # Delayed retracement — downgrade to A and halve risk
            confidence = "A"
        if bars_since_storyline > 3:
            # Significantly delayed — cut to B- (20% risk per Video 11)
            risk_mult = min(risk_mult, 0.2)
            confidence = "B-"

        # 2. STFL — inside FTFL box, on the cascade's STFL timeframe
        stfl_loc = STFLLocator(self.dfs[stfl_tf], stfl_timeframe=stfl_tf)
        stfl_zone = stfl_loc.find_stfl(ftfl_zone)
        if not stfl_zone:
            return None

        # 3. TTFL — inside STFL box, on the cascade's TTFL timeframe
        ttfl_loc = TTFLLocator(self.dfs[ttfl_tf], ttfl_timeframe=ttfl_tf)
        ttfl_ref = ttfl_loc.refine(stfl_zone)
        if not ttfl_ref:
            return None

        # 4. Obstacles & TP — scanned on the cascade's obstacle timeframe
        obs_tf_data = self.dfs.get(obs_tf, self.dfs.get(ftfl_tf))
        obs_scanner = ObstacleScanner(obs_tf_data, timeframe=obs_tf)
        targets = obs_scanner.scan_targets(
            entry_price=ttfl_ref.entry_price,
            direction=ttfl_ref.direction
        )

        # ---------------------------------------------------------------
        # GAP 8 FIX: Pullback vs Continuation TP (Video 12)
        # Counter-trend (Model C / pullback) → TP at closest obstacle.
        # Continuation (same as storyline bias) → TP at final obstacle.
        # ---------------------------------------------------------------
        is_continuation = (ttfl_ref.direction == storyline.bias)
        if targets:
            if is_continuation:
                final_tp = targets[-1].price  # allow to run to final level
                obstacle_tp = targets[0].price if len(targets) > 1 else None
            else:
                # Pullback trade: must exit at the CLOSEST obstacle on originating TF
                final_tp = targets[0].price
                obstacle_tp = None
        else:
            # Fallback TP: storyline rejection if it lies in trade direction,
            # else a 2R projection from the SL distance (never a fixed $30 offset).
            obstacle_tp = None
            final_tp = self._projected_tp(
                entry_price=ttfl_ref.entry_price,
                sl_reference=ttfl_ref.sl_reference,
                direction=ttfl_ref.direction,
                storyline_rejection=storyline.rejection_price,
            )

        # 5. Risk sizing
        plan = self.risk_mgr.calculate_position(
            symbol=self.symbol,
            direction=ttfl_ref.direction,
            entry_price=ttfl_ref.entry_price,
            sl_reference=ttfl_ref.sl_reference,
            final_tp=final_tp,
            intermediate_obstacle=obstacle_tp,
            risk_multiplier=risk_mult,
            model_name=model_type.value
        )

        # ---------------------------------------------------------------
        # GAP 9 FIX: Split Entry — body + equilibrium (Video 9)
        # When TTFL uses Equilibrium (no discrete key level), also generate
        # a secondary entry at the STFL body price so the trade is never missed.
        # ---------------------------------------------------------------
        secondary_plan = None
        if ttfl_ref.entry_type == TTFLEntryType.EQUILIBRIUM:
            body_price = stfl_zone.price  # The close of the STFL candle body
            if abs(body_price - ttfl_ref.entry_price) > 0.5:  # Only if meaningfully different
                secondary_plan = self.risk_mgr.calculate_position(
                    symbol=self.symbol,
                    direction=ttfl_ref.direction,
                    entry_price=body_price,
                    sl_reference=ttfl_ref.sl_reference,
                    final_tp=final_tp,
                    intermediate_obstacle=obstacle_tp,
                    risk_multiplier=risk_mult * 0.3,  # 30% at body per Video 9
                    model_name=f"{model_type.value}_body_30"
                )
                # Main plan gets 70% of risk
                plan = self.risk_mgr.calculate_position(
                    symbol=self.symbol,
                    direction=ttfl_ref.direction,
                    entry_price=ttfl_ref.entry_price,
                    sl_reference=ttfl_ref.sl_reference,
                    final_tp=final_tp,
                    intermediate_obstacle=obstacle_tp,
                    risk_multiplier=risk_mult * 0.7,  # 70% at equilibrium per Video 9
                    model_name=f"{model_type.value}_eq_70"
                )

        # Get formation timestamp
        form_ts = 0
        if hasattr(ftfl_zone.time_formed, 'timestamp'):
            form_ts = int(ftfl_zone.time_formed.timestamp())
        elif "time" in self.dfs[ftfl_tf].columns and ftfl_zone.candle_index < len(self.dfs[ftfl_tf]):
            form_ts = int(self.dfs[ftfl_tf]["time"].iloc[ftfl_zone.candle_index])

        return TradeSignal(
            model_type=model_type,
            symbol=self.symbol,
            direction=ttfl_ref.direction,
            storyline_key=sl_key,
            storyline_desc=f"{storyline.htf}/{storyline.ltf} {storyline.bias.value} @ {storyline.rejection_price:.2f}",
            storyline_rejection=storyline.rejection_price,
            ftfl_tf=ftfl_tf,
            stfl_tf=stfl_tf,
            ttfl_tf=ttfl_tf,
            primary_plan=plan,
            secondary_plan=secondary_plan,
            confidence=confidence,
            formation_time=form_ts,
            ftfl_box_top=ftfl_zone.box_top,
            ftfl_box_bottom=ftfl_zone.box_bottom,
            stfl_box_top=stfl_zone.box_top,
            stfl_box_bottom=stfl_zone.box_bottom,
            rationale=(
                f"FTFL({ftfl_tf}): {ftfl_zone.level_type_desc} @ {ftfl_zone.price:.2f} -> "
                f"STFL({stfl_tf}): {stfl_zone.level_type_desc} @ {stfl_zone.price:.2f} -> "
                f"TTFL({ttfl_tf}): {ttfl_ref.description} @ {ttfl_ref.entry_price:.2f}"
                + (f" [bars_delayed={bars_since_storyline}]" if bars_since_storyline > 1 else "")
                + (" | SPLIT: 70% Eq / 30% Body" if secondary_plan else "")
            )
        )

    # ------------------------------------------------------------------
    # Model B: 14B Confirmation Entry (1H/4H reject + breakout)
    # Both BULLISH and BEARISH directions
    # ------------------------------------------------------------------

    def _evaluate_model_b(self, direction: BiasDirection) -> Optional[TradeSignal]:
        """Backward-compat wrapper: H1 confirmation entry."""
        return self._evaluate_confirmation("H1", direction)

    def _get_htf_confluence_zones(self, is_bullish: bool) -> List[dict]:
        """
        Video 9 crucial rule: a confirmation rejection is only valid ON a
        Daily/Weekly/Monthly key level (Support, Resistance, RBS, SBR, or QM).
        Returns [{tf, desc, price, top, bottom, is_qm}] for the requested side.
        """
        zones: List[dict] = []
        for htf in ["D1", "W1", "MN1", "MN"]:
            if htf not in self.dfs:
                continue
            df = self.dfs[htf]
            if len(df) < 10:
                continue
            canon = "MN1" if htf == "MN" else htf
            try:
                analyzer = CandleAnalyzer(df)
                sr_levels = analyzer.detect_all()
                sr_levels = FreshnessTracker(df).update(sr_levels)
                qms = QMDetector(df, sr_levels).detect_all()
            except Exception:
                continue
            if is_bullish:
                for lv in sr_levels:
                    if lv.level_type in (LevelType.SUPPORT, LevelType.RBS) and lv.state == LevelState.FRESH:
                        zones.append({"tf": canon, "desc": f"{canon} {lv.level_type.value.upper()}",
                                      "price": lv.price, "top": lv.price, "bottom": lv.price, "is_qm": False})
                for qm in qms:
                    from indicators.qm_detector import QMDirection as _QMD
                    if qm.direction == _QMD.BULLISH and qm.state == LevelState.FRESH:
                        zones.append({"tf": canon, "desc": f"{canon} {qm.qm_type.value.upper()} QM",
                                      "price": qm.price, "top": qm.box_high, "bottom": qm.box_low, "is_qm": True})
            else:
                for lv in sr_levels:
                    if lv.level_type in (LevelType.RESISTANCE, LevelType.SBR) and lv.state == LevelState.FRESH:
                        zones.append({"tf": canon, "desc": f"{canon} {lv.level_type.value.upper()}",
                                      "price": lv.price, "top": lv.price, "bottom": lv.price, "is_qm": False})
                for qm in qms:
                    from indicators.qm_detector import QMDirection as _QMD
                    if qm.direction == _QMD.BEARISH and qm.state == LevelState.FRESH:
                        zones.append({"tf": canon, "desc": f"{canon} {qm.qm_type.value.upper()} QM",
                                      "price": qm.price, "top": qm.box_high, "bottom": qm.box_low, "is_qm": True})
        return zones

    def _find_htf_confluence(self, price: float, is_bullish: bool, zones: List[dict]) -> Optional[dict]:
        """Check a confirmation price sits on an HTF zone (inside box or 0.1% tolerance)."""
        for z in zones:
            tol = max(abs(z["price"]) * 0.001, abs(z["top"] - z["bottom"]) * 0.25, 1e-9)
            lo = min(z["top"], z["bottom"]) - tol
            hi = max(z["top"], z["bottom"]) + tol
            if lo <= price <= hi:
                return z
        return None

    def _evaluate_confirmation(self, timeframe: str, direction: BiasDirection) -> Optional[TradeSignal]:
        """
        Video 9 confirmation entry, generalized over H1 and H4.

        H1: 1H rejects 1H S/R (or 1H QM) + 1H breakout, rejection ON D1/W1/MN1 level.
        H4: 4H rejects 4H S/R (or 4H QM) + 4H breakout, rejection ON D1/W1/MN1 level.
        Entry split: 70% at Equilibrium, 30% at Body (Video 9 best practice).
        QM-based rejections carry confidence B at half risk (Video 9: QM weaker).
        Unfresh LTF levels allowed only at confidence B, half risk (Video 7 freshness).
        """
        tf = timeframe.upper()
        if tf not in self.dfs:
            return None
        if tf not in ("H1", "H4"):
            return None

        df_ltf = self.dfs[tf]
        if len(df_ltf) < 20:
            return None

        analyzer = CandleAnalyzer(df_ltf)
        levels_ltf = analyzer.detect_all()
        levels_ltf = FreshnessTracker(df_ltf).update(levels_ltf)
        qms_ltf = QMDetector(df_ltf, levels_ltf).detect_all()

        closes = df_ltf["close"].values
        highs = df_ltf["high"].values
        lows = df_ltf["low"].values
        opens = df_ltf["open"].values

        is_bullish = direction == BiasDirection.BULLISH
        htf_zones = self._get_htf_confluence_zones(is_bullish)
        if not htf_zones:
            return None

        # LTF breakout reference levels (real S/R break, not rolling extremes).
        if is_bullish:
            brk_levels = [lv for lv in levels_ltf if lv.level_type in (LevelType.RESISTANCE, LevelType.SBR)]
        else:
            brk_levels = [lv for lv in levels_ltf if lv.level_type in (LevelType.SUPPORT, LevelType.RBS)]

        from indicators.qm_detector import QMDirection as _QMD
        target_qm_dir = _QMD.BULLISH if is_bullish else _QMD.BEARISH
        qm_by_idx = {}
        for qm in qms_ltf:
            if qm.direction == target_qm_dir and qm.state != LevelState.BROKEN:
                qm_by_idx.setdefault(qm.break_candle_index, []).append(qm)

        scan_start = max(0, len(df_ltf) - 12)

        for i in range(scan_start, len(df_ltf) - 1):
            c_high = highs[i]
            c_low = lows[i]
            c_close = closes[i]
            c_open = opens[i]

            # Collect LTF rejection candidates at bar i: (kind, price, is_fresh, label).
            cands = []
            if is_bullish:
                for lvl in levels_ltf:
                    if lvl.level_type not in (LevelType.SUPPORT, LevelType.RBS):
                        continue
                    if lvl.candle_index >= i or lvl.state == LevelState.BROKEN:
                        continue
                    if c_low <= lvl.price and c_close > lvl.price:
                        cands.append(("sr", lvl.price, lvl.state == LevelState.FRESH,
                                      f"{tf} {lvl.level_type.value}"))
                for qm in qms_ltf:
                    if qm.direction != target_qm_dir or qm.state == LevelState.BROKEN:
                        continue
                    if qm.break_candle_index > i:
                        continue
                    if c_low <= qm.price and c_close > qm.price:
                        cands.append(("qm", qm.price, qm.state == LevelState.FRESH,
                                      f"{tf} {qm.qm_type.value.upper()} QM"))
            else:
                for lvl in levels_ltf:
                    if lvl.level_type not in (LevelType.RESISTANCE, LevelType.SBR):
                        continue
                    if lvl.candle_index >= i or lvl.state == LevelState.BROKEN:
                        continue
                    if c_high >= lvl.price and c_close < lvl.price:
                        cands.append(("sr", lvl.price, lvl.state == LevelState.FRESH,
                                      f"{tf} {lvl.level_type.value}"))
                for qm in qms_ltf:
                    if qm.direction != target_qm_dir or qm.state == LevelState.BROKEN:
                        continue
                    if qm.break_candle_index > i:
                        continue
                    if c_high >= qm.price and c_close < qm.price:
                        cands.append(("qm", qm.price, qm.state == LevelState.FRESH,
                                      f"{tf} {qm.qm_type.value.upper()} QM"))

            for kind, rej_price, ltf_fresh, ltf_label in cands:
                # Crucial rule: rejection must sit ON an HTF key level.
                htf = self._find_htf_confluence(rej_price, is_bullish, htf_zones)
                if htf is None:
                    continue

                # Structural breakout on the confirmation TF after the rejection:
                # close through the most recent opposite-side S/R level; rolling
                # extreme fallback only when no levels exist (spec proxy).
                if is_bullish:
                    ref = [lv for lv in brk_levels if lv.candle_index < i]
                    if ref:
                        target = ref[-1].price
                        breakout_found = any(closes[k] > target for k in range(i + 1, min(len(df_ltf), i + 20)))
                    else:
                        prior_high = max(highs[max(0, i - 12):i]) if i > 0 else c_high
                        breakout_found = any(closes[k] > prior_high for k in range(i + 1, min(len(df_ltf), i + 20)))
                else:
                    ref = [lv for lv in brk_levels if lv.candle_index < i]
                    if ref:
                        target = ref[-1].price
                        breakout_found = any(closes[k] < target for k in range(i + 1, min(len(df_ltf), i + 20)))
                    else:
                        prior_low = min(lows[max(0, i - 12):i]) if i > 0 else c_low
                        breakout_found = any(closes[k] < prior_low for k in range(i + 1, min(len(df_ltf), i + 20)))
                if not breakout_found:
                    continue

                # Box: body to wick tip of the rejection bar (Video 9 step 5).
                if is_bullish:
                    box_top = max(highs[i], c_open)
                    box_bottom = min(lows[i], c_close)
                    sl_ref = box_bottom
                else:
                    box_top = max(highs[i], c_close)
                    box_bottom = min(lows[i], c_open)
                    sl_ref = box_top
                eq_price = (box_top + box_bottom) / 2.0
                body_price = c_close

                # Confidence / risk: QM-based or unfresh LTF rejection is weaker.
                confidence = "A"
                risk_scale = 1.0
                weak_reasons = []
                if kind == "qm":
                    confidence = "B"
                    risk_scale *= 0.5
                    weak_reasons.append("QM rejection (weaker per V9)")
                if not ltf_fresh:
                    confidence = "B"
                    risk_scale *= 0.5
                    weak_reasons.append("unfresh LTF level")
                if htf["is_qm"]:
                    confidence = "B"
                    weak_reasons.append(f"HTF confluence on QM ({htf['desc']})")

                dir_txt = "BULL" if is_bullish else "BEAR"
                eq_tp = self._resolve_tp_with_obstacles(eq_price, sl_ref, direction, tf)
                body_tp = self._resolve_tp_with_obstacles(body_price, sl_ref, direction, tf)
                plan_70 = self.risk_mgr.calculate_position(
                    symbol=self.symbol, direction=direction,
                    entry_price=eq_price, sl_reference=sl_ref,
                    final_tp=eq_tp, risk_multiplier=0.7 * risk_scale,
                    model_name=f"Model B {tf} {dir_txt} 70% Eq"
                )
                plan_30 = self.risk_mgr.calculate_position(
                    symbol=self.symbol, direction=direction,
                    entry_price=body_price, sl_reference=sl_ref,
                    final_tp=body_tp, risk_multiplier=0.3 * risk_scale,
                    model_name=f"Model B {tf} {dir_txt} 30% Body"
                )

                weak_txt = f" [{'; '.join(weak_reasons)}]" if weak_reasons else ""
                arrow = "SUPPORT" if is_bullish else "RESISTANCE"
                return TradeSignal(
                    model_type=EntryModelType.MODEL_B_14B,
                    symbol=self.symbol, direction=direction,
                    storyline_key="CONFIRMATION",
                    storyline_desc=f"{tf} reject {tf} {ltf_label} on {htf['desc']} @ {htf['price']:.2f} + {tf} Breakout ({dir_txt})",
                    storyline_rejection=htf["price"],
                    ftfl_tf=tf, stfl_tf=tf, ttfl_tf=tf,
                    primary_plan=plan_70, secondary_plan=plan_30,
                    confidence=confidence,
                    rationale=f"Confirmation {dir_txt}: {ltf_label} @ {rej_price:.2f} on {htf['desc']}, Eq={eq_price:.2f}, Body={body_price:.2f}{weak_txt}"
                )

        return None

    # ------------------------------------------------------------------
    # Model C: D1W4 — 1H mitigates Daily level with 1 candle + 1H breakout
    # Also covers W4: 4H mitigates Weekly level
    # ------------------------------------------------------------------

    @staticmethod
    def _is_isolated_mitigation(
        highs, lows, idx: int, price: float, is_bullish: bool,
    ) -> bool:
        """
        Video 12 single-candle rule: mitigation must happen with a wick or
        EXACTLY ONE candle. If an adjacent candle also touches the level, the
        setup is invalid (multi-candle break).
        """
        n = len(highs)
        for j in (idx - 1, idx + 1):
            if 0 <= j < n:
                if is_bullish:
                    if lows[j] <= price:
                        return False
                else:
                    if highs[j] >= price:
                        return False
        return True

    def _ltf_qm_option_b(
        self,
        ltf: str,
        direction: BiasDirection,
        near_idx: int,
        htf_desc: str,
        htf_price: float,
        obstacle_tf: str,
        window: int = 12,
    ) -> Optional[TradeSignal]:
        """
        Video 12 Option B: after the mitigation + breakout, the LTF QM
        equilibrium catches the 20-30% of moves that skip the S/R entry.
        Sized at 20% risk, confidence B-.
        """
        from indicators.qm_detector import QMType as _QMT, QMDirection as _QMD
        if ltf not in self.dfs:
            return None
        df = self.dfs[ltf]
        if len(df) < 10:
            return None
        try:
            analyzer = CandleAnalyzer(df)
            sr = FreshnessTracker(df).update(analyzer.detect_all())
            qms = QMDetector(df, sr).detect_all()
        except Exception:
            return None
        want = _QMD.BULLISH if direction == BiasDirection.BULLISH else _QMD.BEARISH
        cands = [q for q in qms if q.direction == want and abs(q.break_candle_index - near_idx) <= window]
        if not cands:
            return None
        rank = {_QMT.ABQM: 0, _QMT.IABQM: 1, _QMT.FTQM: 2, _QMT.STQM: 3}
        cands.sort(key=lambda q: (rank.get(q.qm_type, 4), -q.break_candle_index))
        qm = cands[0]
        eq = (qm.box_high + qm.box_low) / 2.0
        sl_ref = qm.box_low if direction == BiasDirection.BULLISH else qm.box_high
        tp = self._resolve_tp_with_obstacles(eq, sl_ref, direction, obstacle_tf)
        plan = self.risk_mgr.calculate_position(
            symbol=self.symbol, direction=direction,
            entry_price=eq, sl_reference=sl_ref,
            final_tp=tp, risk_multiplier=0.2,
            model_name=f"Model C {ltf} QM Option B",
        )
        tag = "BULL" if direction == BiasDirection.BULLISH else "BEAR"
        return TradeSignal(
            model_type=EntryModelType.MODEL_C_D1W4,
            symbol=self.symbol, direction=direction,
            storyline_key="D1W4_QM_OPTION_B",
            storyline_desc=f"{ltf} QM eq after {htf_desc} mitigation @ {htf_price:.2f} ({tag} Option B)",
            storyline_rejection=htf_price,
            ftfl_tf=ltf, stfl_tf=ltf, ttfl_tf=ltf,
            primary_plan=plan,
            confidence="B-",
            rationale=f"Option B QM: {ltf} {qm.qm_type.value.upper()} QM eq={eq:.2f} (20% risk, market uses QM 20-30%)",
        )

    def _evaluate_model_c(self, storylines: dict):
        """
        D1W4 Retracement Model (returns list: Option A + optional Option B):
          - 1H wick / EXACTLY ONE candle mitigates a Daily key level (Video 12
            single-candle rule enforced via _is_isolated_mitigation)
          - Swing high/low must exist BEFORE the mitigation (critical rule)
          - 1H breaks out after mitigation
          - Option A (100%): 1H Support/Resistance Equilibrium
          - Option B (20%, B-): 1H QM Equilibrium (missed-entry catcher)
        Backward compat: callers may treat the return as a single signal or a list.
        """
        if "D1" not in self.dfs or "H1" not in self.dfs:
            return []

        # Get overall bias from storylines
        overall_bias = None
        for sl in storylines.values():
            if sl.bias != BiasDirection.NEUTRAL:
                overall_bias = sl.bias
                break
        if not overall_bias:
            return []

        df_d1 = self.dfs["D1"]
        df_h1 = self.dfs["H1"]

        analyzer_d1 = CandleAnalyzer(df_d1)
        levels_d1 = analyzer_d1.detect_all()
        tracker_d1 = FreshnessTracker(df_d1)
        levels_d1 = tracker_d1.update(levels_d1)

        closes_h1 = df_h1["close"].values
        highs_h1 = df_h1["high"].values
        lows_h1 = df_h1["low"].values

        is_bullish = overall_bias == BiasDirection.BULLISH
        direction = BiasDirection.BULLISH if is_bullish else BiasDirection.BEARISH

        # Check last 8 H1 candles for an isolated single-candle mitigation
        scan_start = max(0, len(df_h1) - 8)

        for i in range(scan_start, len(df_h1)):
            c_high = highs_h1[i]
            c_low = lows_h1[i]
            c_close = closes_h1[i]

            for lvl in levels_d1:
                if is_bullish:
                    target_types = (LevelType.SUPPORT, LevelType.RBS)
                    mitigated = c_low <= lvl.price and c_close >= lvl.price
                else:
                    target_types = (LevelType.RESISTANCE, LevelType.SBR)
                    mitigated = c_high >= lvl.price and c_close <= lvl.price

                if lvl.level_type not in target_types:
                    continue
                if not mitigated:
                    continue

                # Video 12 single-candle rule: neighbors must NOT touch the level.
                if not self._is_isolated_mitigation(highs_h1, lows_h1, i, lvl.price, is_bullish):
                    continue

                # CRITICAL RULE (Video 12): swing high/low must have formed BEFORE mitigation
                if i < 5:
                    continue

                prior_closes = closes_h1[max(0, i-15):i]
                if len(prior_closes) == 0:
                    continue

                if is_bullish:
                    swing_target = float(max(highs_h1[max(0, i-15):i]))
                    # After mitigation, check for breakout above swing target
                    breakout = any(
                        closes_h1[k] > swing_target
                        for k in range(i, min(len(df_h1), i + 15))
                    )
                    if not breakout:
                        continue

                    box_top = c_high
                    box_bottom = lvl.price
                    eq_entry = (box_top + box_bottom) / 2.0

                    d1_tp = self._resolve_tp_with_obstacles(
                        entry_price=eq_entry,
                        sl_reference=box_bottom - 0.5,
                        direction=BiasDirection.BULLISH,
                        obstacle_tf="D1",
                    )
                    plan = self.risk_mgr.calculate_position(
                        symbol=self.symbol, direction=BiasDirection.BULLISH,
                        entry_price=eq_entry, sl_reference=box_bottom - 0.5,
                        final_tp=d1_tp, risk_multiplier=1.0,
                        model_name="Model C D1W4 BULL"
                    )

                    signals = [TradeSignal(
                        model_type=EntryModelType.MODEL_C_D1W4,
                        symbol=self.symbol, direction=BiasDirection.BULLISH,
                        storyline_key="D1W4_RETRACEMENT",
                        storyline_desc=f"1H mitigates D1 {lvl.level_type.value.upper()} @ {lvl.price:.2f} (1 candle)",
                        storyline_rejection=lvl.price,
                        ftfl_tf="D1", stfl_tf="H1", ttfl_tf="H1",
                        primary_plan=plan,
                        confidence="A",
                        rationale=f"D1W4 Bull: 1H single-candle mitigation of D1 {lvl.level_type.value} @ {lvl.price:.2f} -> 1H breakout above {swing_target:.2f}"
                    )]
                    opt_b = self._ltf_qm_option_b("H1", direction, i, f"D1 {lvl.level_type.value.upper()}", lvl.price, "D1")
                    if opt_b:
                        signals.append(opt_b)
                    return signals

                else:
                    swing_target = float(min(lows_h1[max(0, i-15):i]))
                    breakout = any(
                        closes_h1[k] < swing_target
                        for k in range(i, min(len(df_h1), i + 15))
                    )
                    if not breakout:
                        continue

                    box_top = lvl.price
                    box_bottom = c_low
                    eq_entry = (box_top + box_bottom) / 2.0

                    d1_tp = self._resolve_tp_with_obstacles(
                        entry_price=eq_entry,
                        sl_reference=box_top + 0.5,
                        direction=BiasDirection.BEARISH,
                        obstacle_tf="D1",
                    )
                    plan = self.risk_mgr.calculate_position(
                        symbol=self.symbol, direction=BiasDirection.BEARISH,
                        entry_price=eq_entry, sl_reference=box_top + 0.5,
                        final_tp=d1_tp, risk_multiplier=1.0,
                        model_name="Model C D1W4 BEAR"
                    )

                    signals = [TradeSignal(
                        model_type=EntryModelType.MODEL_C_D1W4,
                        symbol=self.symbol, direction=BiasDirection.BEARISH,
                        storyline_key="D1W4_RETRACEMENT",
                        storyline_desc=f"1H mitigates D1 {lvl.level_type.value.upper()} @ {lvl.price:.2f} (1 candle)",
                        storyline_rejection=lvl.price,
                        ftfl_tf="D1", stfl_tf="H1", ttfl_tf="H1",
                        primary_plan=plan,
                        confidence="A",
                        rationale=f"D1W4 Bear: 1H single-candle mitigation of D1 {lvl.level_type.value} @ {lvl.price:.2f} -> 1H breakdown below {swing_target:.2f}"
                    )]
                    opt_b = self._ltf_qm_option_b("H1", direction, i, f"D1 {lvl.level_type.value.upper()}", lvl.price, "D1")
                    if opt_b:
                        signals.append(opt_b)
                    return signals

        return []

    def _evaluate_model_c_w4(self, storylines: dict):
        """
        W4 variant of Model C (Video 12); returns list (Option A + optional B).
        4H wick / EXACTLY ONE candle mitigates a Weekly key level (single-candle
        rule enforced), then a 4H breakout occurs.
        Option A (100%): 4H S/R Equilibrium. Option B (20%, B-): 4H QM Equilibrium.
        """
        if "W1" not in self.dfs or "H4" not in self.dfs or "H1" not in self.dfs:
            return []

        # Determine overall bias from storylines
        overall_bias = None
        for sl in storylines.values():
            if sl.bias != BiasDirection.NEUTRAL:
                overall_bias = sl.bias
                break
        if not overall_bias:
            return []

        df_w1 = self.dfs["W1"]
        df_h4 = self.dfs["H4"]

        analyzer_w1 = CandleAnalyzer(df_w1)
        levels_w1 = analyzer_w1.detect_all()
        tracker_w1 = FreshnessTracker(df_w1)
        levels_w1 = tracker_w1.update(levels_w1)

        closes_h4 = df_h4["close"].values
        highs_h4 = df_h4["high"].values
        lows_h4 = df_h4["low"].values

        is_bullish = overall_bias == BiasDirection.BULLISH
        direction = BiasDirection.BULLISH if is_bullish else BiasDirection.BEARISH
        scan_start = max(0, len(df_h4) - 8)

        for i in range(scan_start, len(df_h4)):
            c_high = highs_h4[i]
            c_low = lows_h4[i]
            c_close = closes_h4[i]

            for lvl in levels_w1:
                if is_bullish:
                    target_types = (LevelType.SUPPORT, LevelType.RBS)
                    mitigated = c_low <= lvl.price and c_close >= lvl.price
                else:
                    target_types = (LevelType.RESISTANCE, LevelType.SBR)
                    mitigated = c_high >= lvl.price and c_close <= lvl.price

                if lvl.level_type not in target_types:
                    continue
                if not mitigated:
                    continue

                # Video 12 single-candle rule: neighbors must NOT touch the level.
                if not self._is_isolated_mitigation(highs_h4, lows_h4, i, lvl.price, is_bullish):
                    continue

                # Critical rule: swing must have formed BEFORE mitigation
                if i < 5:
                    continue

                if is_bullish:
                    swing_target = float(max(highs_h4[max(0, i-15):i]))
                    breakout = any(
                        closes_h4[k] > swing_target
                        for k in range(i, min(len(df_h4), i + 15))
                    )
                    if not breakout:
                        continue

                    # Use H4 FTFL box -> H1 STFL -> H1 TTFL
                    box_top = c_high
                    box_bottom = lvl.price
                    eq_entry = (box_top + box_bottom) / 2.0

                    w1_tp = self._resolve_tp_with_obstacles(
                        entry_price=eq_entry,
                        sl_reference=box_bottom - 0.5,
                        direction=BiasDirection.BULLISH,
                        obstacle_tf="W1",
                    )
                    plan = self.risk_mgr.calculate_position(
                        symbol=self.symbol, direction=BiasDirection.BULLISH,
                        entry_price=eq_entry, sl_reference=box_bottom - 0.5,
                        final_tp=w1_tp, risk_multiplier=1.0,
                        model_name="Model C W4 BULL"
                    )
                    signals = [TradeSignal(
                        model_type=EntryModelType.MODEL_C_D1W4,
                        symbol=self.symbol, direction=BiasDirection.BULLISH,
                        storyline_key="W4_RETRACEMENT",
                        storyline_desc=f"4H mitigates W1 {lvl.level_type.value.upper()} @ {lvl.price:.2f} (1 candle)",
                        storyline_rejection=lvl.price,
                        ftfl_tf="H4", stfl_tf="H1", ttfl_tf="H1",
                        primary_plan=plan,
                        confidence="A",
                        rationale=f"W4 Bull: 4H single-candle mitigation of W1 {lvl.level_type.value} @ {lvl.price:.2f} -> 4H breakout above {swing_target:.2f}"
                    )]
                    opt_b = self._ltf_qm_option_b("H4", direction, i, f"W1 {lvl.level_type.value.upper()}", lvl.price, "W1")
                    if opt_b:
                        opt_b.storyline_key = "W4_QM_OPTION_B"
                        signals.append(opt_b)
                    return signals

                else:
                    swing_target = float(min(lows_h4[max(0, i-15):i]))
                    breakout = any(
                        closes_h4[k] < swing_target
                        for k in range(i, min(len(df_h4), i + 15))
                    )
                    if not breakout:
                        continue

                    box_top = lvl.price
                    box_bottom = c_low
                    eq_entry = (box_top + box_bottom) / 2.0

                    w1_tp = self._resolve_tp_with_obstacles(
                        entry_price=eq_entry,
                        sl_reference=box_top + 0.5,
                        direction=BiasDirection.BEARISH,
                        obstacle_tf="W1",
                    )
                    plan = self.risk_mgr.calculate_position(
                        symbol=self.symbol, direction=BiasDirection.BEARISH,
                        entry_price=eq_entry, sl_reference=box_top + 0.5,
                        final_tp=w1_tp, risk_multiplier=1.0,
                        model_name="Model C W4 BEAR"
                    )
                    signals = [TradeSignal(
                        model_type=EntryModelType.MODEL_C_D1W4,
                        symbol=self.symbol, direction=BiasDirection.BEARISH,
                        storyline_key="W4_RETRACEMENT",
                        storyline_desc=f"4H mitigates W1 {lvl.level_type.value.upper()} @ {lvl.price:.2f} (1 candle)",
                        storyline_rejection=lvl.price,
                        ftfl_tf="H4", stfl_tf="H1", ttfl_tf="H1",
                        primary_plan=plan,
                        confidence="A",
                        rationale=f"W4 Bear: 4H single-candle mitigation of W1 {lvl.level_type.value} @ {lvl.price:.2f} -> 4H breakdown below {swing_target:.2f}"
                    )]
                    opt_b = self._ltf_qm_option_b("H4", direction, i, f"W1 {lvl.level_type.value.upper()}", lvl.price, "W1")
                    if opt_b:
                        opt_b.storyline_key = "W4_QM_OPTION_B"
                        signals.append(opt_b)
                    return signals

        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _projected_tp(
        self,
        entry_price: float,
        sl_reference: float,
        direction: BiasDirection,
        storyline_rejection: float = 0.0,
        rr_multiple: float = 2.0,
    ) -> float:
        """
        2R fallback TP derived from the actual SL distance (never a fixed $30/$50 offset).
        Prefers the storyline rejection level when it lies in the trade direction.
        """
        is_bullish = direction == BiasDirection.BULLISH
        risk_dist = abs(entry_price - sl_reference)
        if risk_dist <= 0:
            # Gold fixed SL = 3.00 price units; FX fallback = 1% of entry.
            sym_u = (self.symbol or "").upper()
            risk_dist = 3.0 if ("XAU" in sym_u or "GOLD" in sym_u) else abs(entry_price) * 0.01 or 1.0

        if storyline_rejection:
            if is_bullish and storyline_rejection > entry_price:
                return float(storyline_rejection)
            if not is_bullish and storyline_rejection < entry_price:
                return float(storyline_rejection)

        return float(entry_price + risk_dist * rr_multiple) if is_bullish else float(entry_price - risk_dist * rr_multiple)

    def _resolve_tp_with_obstacles(
        self,
        entry_price: float,
        sl_reference: float,
        direction: BiasDirection,
        obstacle_tf: str,
        rr_multiple: float = 2.0,
    ) -> float:
        """
        Obstacle-aware TP on the trade-origin timeframe; falls back to 2R projection.
        Replaces legacy fixed +30/+50 price-unit offsets (which equal ~10R on Gold).
        """
        try:
            obs_df = self.dfs.get(obstacle_tf)
            if obs_df is not None and len(obs_df) >= 10:
                scanner = ObstacleScanner(obs_df, timeframe=obstacle_tf)
                targets = scanner.scan_targets(entry_price=entry_price, direction=direction)
                if targets:
                    # Closest obstacle in trade direction is the disciplined TP for
                    # confirmation / retracement models (they must not run through it).
                    return float(targets[0].price)
        except Exception:
            pass
        return self._projected_tp(entry_price, sl_reference, direction, rr_multiple=rr_multiple)

    def _bars_since_storyline(self, storyline: StorylineEvent, ftfl_tf: str) -> int:
        """
        GAP 3 HELPER: Count HTF bars elapsed between storyline breakout
        and the most recent candle on the FTFL timeframe.

        Returns 0 if data is unavailable (conservative assumption: next-candle).
        """
        if ftfl_tf not in self.dfs:
            return 0
        df = self.dfs[ftfl_tf]
        if len(df) == 0:
            return 0
        try:
            breakout_time = storyline.breakout_time
            # Find the index of the first bar on or after the breakout
            matching = [idx for idx, t in enumerate(df.index) if t >= breakout_time]
            if not matching:
                return 0
            breakout_bar_idx = matching[0]
            last_bar_idx = len(df) - 1
            return max(0, last_bar_idx - breakout_bar_idx)
        except Exception:
            return 0

    def _get_current_price(self) -> float:
        """Get the most recent close price from H1 or D1."""
        for tf in ["H1", "H4", "D1"]:
            if tf in self.dfs and len(self.dfs[tf]) > 0:
                return float(self.dfs[tf]["close"].iloc[-1])
        return 0.0
