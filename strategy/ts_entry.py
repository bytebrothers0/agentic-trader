"""
ts_entry.py — MNSR + TS entry model (M15 only).

Chain per TS (bias from the sweep side):
  1. TS forms (TS_LOW = bullish bias, TS_HIGH = bearish), at most
     TS_ENTRY_MAX_AGE bars ago.
  2. Break after it: first BOS/CHoCH/I-BOS/I-CHoCH in the bias direction,
     within TS_BREAK_MAX_BARS bars. Structure breaks win when present; else
     a body close through the nearest S/R shelf counts (impulse-proof:
     swing confirmation often can't complete mid-impulse). Shelf must sit
     within TS_SR_SHELF_DIST of the TS and be fully formed before the bar.
  3. QM: setup-side QMs sitting past the TS level toward the break
     (buys: above the TS low, sells: below the TS high — per the chart
     examples; the QM may predate the TS, "recent or previous").
  4. Liquidity: the FIRST setup-side structural IDM formed after the break
     bar ("newly formed"); else the most recent fractal swing extreme after
     the break ("wick low" liquidity, max TS_LIQ_MAX_BARS bars out). Entry =
     closest QM that already existed when the liquidity formed, on the near
     side of it AND inside the TS->BOS sandwich (buys: TS < QM < BOS level,
     sells: BOS < QM < TS — the QM sits between break and sweep, never
     outside), within TS_MAX_IDM_DIST of the liquidity and TS_MAX_QM_DIST
     of the TS. No QM there -> no entry.
  5. No-IDM fallback: if price traded back to the TS level (buys: a low
     at/under it since the break), the TS extreme becomes the IDM proxy
     and entry is the nearest S/R the right way (support buys).
  6. Confluence: entry inside an OB / FVG / Breaker / IFVG zone (any age —
     old zones still hold) boosts confidence and is logged.

Risk (user spec): fixed 350pt SL, 3000pt TP, 1% sizing via RiskManager.
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional

from config.settings import (
    TS_ENTRY_MAX_AGE,
    TS_BREAK_MAX_BARS,
    TS_ENTRY_SL_POINTS,
    TS_ENTRY_TP_POINTS,
    TS_MAX_QM_DIST,
    TS_MAX_IDM_DIST,
    TS_SR_SHELF_DIST,
    TS_MIN_SWEEP_ATR,
)
from indicators.ts_detector import TSDetector, TSType
from indicators.candle_analyzer import CandleAnalyzer, LevelType
from indicators.freshness_tracker import FreshnessTracker
from indicators.qm_detector import QMDetector, QMDirection
from indicators.idm_detector import IDMDetector, IDMType
from indicators.bos_detector import BOSDetector, BOSDirection
from indicators.ob_detector import OBDetector
from indicators.fvg_detector import FVGDetector
from strategy.entry_engine import EntryModelType, TradeSignal
from strategy.storyline_engine import BiasDirection
from execution.risk_manager import RiskManager

SR_TOL_ATR = 0.1       # S/R + confluence touch tolerance (fraction of ATR)
TS_LIQ_MAX_BARS = 30   # fractal liquidity must form soon after the break


class TSEntryEngine:
    """Scans M15 candles for MNSR+TS setups. See module docstring."""

    def __init__(self, df: pd.DataFrame, symbol: str = "XAUUSD"):
        self.df = df.copy()
        self.symbol = symbol
        self.risk_mgr = RiskManager()
        self._atr = self._compute_atr()

    # ------------------------------------------------------------------
    def scan(self) -> List[TradeSignal]:
        df, n = self.df, len(self.df)
        last = n - 1
        current = float(df["close"].iloc[-1])

        ts_list = TSDetector(df, min_sweep_atr=TS_MIN_SWEEP_ATR).detect_all()

        analyzer = CandleAnalyzer(df)
        sr_levels = FreshnessTracker(df).update(analyzer.detect_all())
        qm_levels = QMDetector(df, analyzer.detect_all()).detect_all()
        idm_levels = IDMDetector(df).detect_all()
        bos_levels = BOSDetector(df).detect_all()
        ob_levels = OBDetector(df).detect_all()
        fvg_det = FVGDetector(df)
        fvg_levels = fvg_det.detect_all()
        ifvg_levels = fvg_det.detect_ifvg(fvg_levels)

        signals: List[TradeSignal] = []
        for ts in ts_list:
            bullish = ts.ts_type == TSType.TS_LOW
            direction = BiasDirection.BULLISH if bullish else BiasDirection.BEARISH
            f = ts.candle_index
            if last - f > TS_ENTRY_MAX_AGE:
                continue  # stale TS, not a fresh setup

            # --- 2. ordered break candidates after the TS: structure
            # breaks (BOS/CHoCH either layer) plus the S/R-shelf break
            # (impulse-proof). The FIRST candidate whose QM+liquidity chain
            # completes wins — the break the sequence actually follows. ---
            want = BOSDirection.BULLISH if bullish else BOSDirection.BEARISH
            cands = []  # (bar, kind, brk, bos_price)
            for b in sorted(
                    (x for x in bos_levels
                     if x.direction == want and x.break_index > f),
                    key=lambda x: x.break_index):
                if b.break_index - f > TS_BREAK_MAX_BARS:
                    break
                cands.append((b.break_index,
                              "CHOCH" if b.is_choch else "BOS", b,
                              float(b.price)))
            sr_hit = self._sr_shelf_break(sr_levels, float(ts.price), f, bullish)
            if sr_hit is not None and sr_hit[0] - f <= TS_BREAK_MAX_BARS:
                if all(sr_hit[0] != cbar for cbar, _, _, _ in cands):
                    cands.append((sr_hit[0], "SR",
                                  SimpleNamespace(break_index=sr_hit[0],
                                                  is_choch=False),
                                  float(sr_hit[1])))
            cands.sort(key=lambda c: c[0])
            if not cands:
                continue

            # --- 3. setup-side QMs past the TS level (may predate it;
            # recency is judged against the liquidity below) ---
            want_qm = QMDirection.BULLISH if bullish else QMDirection.BEARISH
            if bullish:
                qm_pool = [q for q in qm_levels
                           if q.direction == want_qm and q.price > ts.price]
            else:
                qm_pool = [q for q in qm_levels
                           if q.direction == want_qm and q.price < ts.price]
            qm_pool.sort(key=lambda q: q.break_candle_index)
            if not qm_pool:
                continue

            # --- 4/5. walk candidates in order; first COMPLETE chain wins.
            # Liquidity = first structural IDM after the break, else the
            # most recent fractal extreme. Fallback (TS extreme as IDM +
            # S/R entry) only when no liquidity exists anywhere. ---
            want_idm = IDMType.IDM_LOW if bullish else IDMType.IDM_HIGH
            picked = None  # (brk, kind, bos_price, qm, liq_price, liq_idx, liq_kind)
            saw_liq = False
            for (bbar, kind, brk, bos_price) in cands:
                idms_after = [lv for lv in idm_levels
                              if lv.idm_type == want_idm
                              and lv.formation_index > bbar]
                entry_liq = None
                liq_kind = None
                if idms_after:
                    first = min(idms_after, key=lambda lv: lv.formation_index)
                    entry_liq = (first.price, first.formation_index)
                    liq_kind = "IDM"
                else:
                    entry_liq = self._swing_liquidity(bbar, bullish)
                    liq_kind = "LIQ" if entry_liq is not None else None
                if entry_liq is None:
                    continue
                saw_liq = True
                liq_price, liq_idx = entry_liq
                if bullish:
                    cands_qm = [q for q in qm_pool
                                if 0 <= liq_idx - q.break_candle_index <= TS_ENTRY_MAX_AGE
                                and ts.price < q.price < bos_price
                                and q.price < liq_price
                                and liq_price - q.price <= TS_MAX_IDM_DIST
                                and q.price - ts.price <= TS_MAX_QM_DIST]
                    pick = max(cands_qm, key=lambda q: q.price) if cands_qm else None
                else:
                    cands_qm = [q for q in qm_pool
                                if 0 <= liq_idx - q.break_candle_index <= TS_ENTRY_MAX_AGE
                                and bos_price < q.price
                                and q.price > liq_price
                                and q.price - liq_price <= TS_MAX_IDM_DIST
                                and ts.price - q.price <= TS_MAX_QM_DIST]
                    pick = min(cands_qm, key=lambda q: q.price) if cands_qm else None
                if pick is None:
                    continue  # liquidity with no QM on its near side; try next break
                picked = (brk, kind, bos_price, pick, liq_price, liq_idx, liq_kind)
                break

            entry_price: Optional[float] = None
            picked_qm = None
            entry_idm = None
            liq_kind = None
            liq_price = None
            fallback = False
            if picked is not None:
                brk, brk_kind, _bos_price, picked_qm, liq_price, liq_idx, liq_kind = picked
                entry_price = float(picked_qm.price)
                entry_idm = liq_idx
            else:
                if saw_liq:
                    continue  # liquidity existed but no QM fit -> no entry
                # --- 5. no-liquidity fallback: price back at the TS extreme,
                # measured from the first candidate break ---
                brk, brk_kind = cands[0][2], cands[0][1]
                tol = SR_TOL_ATR * self._atr[f]
                if bullish:
                    lows = df["low"].values[brk.break_index + 1:]
                    if len(lows) == 0 or min(lows) > ts.price + tol:
                        continue
                    sups = [lv for lv in sr_levels
                            if lv.level_type == LevelType.SUPPORT
                            and lv.price <= ts.price + tol]
                    if not sups:
                        continue
                    entry_price = float(max(sups, key=lambda lv: lv.price).price)
                else:
                    highs = df["high"].values[brk.break_index + 1:]
                    if len(highs) == 0 or max(highs) < ts.price - tol:
                        continue
                    ress = [lv for lv in sr_levels
                            if lv.level_type == LevelType.RESISTANCE
                            and lv.price >= ts.price - tol]
                    if not ress:
                        continue
                    entry_price = float(min(ress, key=lambda lv: lv.price).price)
                entry_idm = None
                fallback = True

            # --- S/R note: TS (mostly) sits on a key level ---
            tol = SR_TOL_ATR * self._atr[f]
            on_sr = [lv for lv in sr_levels if abs(lv.price - ts.price) <= tol]
            on_sr_desc = (f"{on_sr[0].level_type.value.upper()}@{on_sr[0].price:.2f}"
                          if on_sr else "no-SR")

            # --- 6. confluence: entry inside OB/FVG/Breaker/IFVG (any age) ---
            zones = ([("OB", z.top, z.bottom) for z in ob_levels] +
                     [("FVG", z.top, z.bottom) for z in fvg_levels] +
                     [("IFVG", z.top, z.bottom) for z in ifvg_levels])
            conf = sorted({name for name, top, bot in zones
                           if bot - tol <= entry_price <= top + tol})
            confidence = "B"
            if on_sr:
                confidence = "A"
            if conf:
                confidence = "A+"

            # --- risk: fixed 350pt SL / 3000pt TP ---
            point = 0.01
            if bullish:
                tp = entry_price + TS_ENTRY_TP_POINTS * point
            else:
                tp = entry_price - TS_ENTRY_TP_POINTS * point
            plan = self.risk_mgr.calculate_position(
                symbol=self.symbol,
                direction=direction,
                entry_price=entry_price,
                sl_reference=entry_price,
                final_tp=tp,
                risk_multiplier=1.0,
                model_name="TS M15",
                sl_points_override=TS_ENTRY_SL_POINTS,
            )

            if bullish:
                desc = (f"TS_LOW sweep @{ts.price:.2f} ({on_sr_desc}) -> "
                        f"{brk_kind} break -> "
                        f"QM@{picked_qm.price:.2f} -> " if picked_qm else "")
                desc += (f"{liq_kind}@{liq_price:.2f}" if entry_idm is not None
                         else f"no-IDM fallback: TS-low-as-IDM, S/R entry")
            else:
                desc = (f"TS_HIGH sweep @{ts.price:.2f} ({on_sr_desc}) -> "
                        f"{brk_kind} break -> "
                        f"QM@{picked_qm.price:.2f} -> " if picked_qm else "")
                desc += (f"{liq_kind}@{liq_price:.2f}" if entry_idm is not None
                         else f"no-IDM fallback: TS-high-as-IDM, S/R entry")
            if conf:
                desc += f" [+{','.join(conf)}]"
            if fallback:
                desc += " [fallback]"

            times = df["time"].values
            anchor = (entry_idm if entry_idm is not None
                      else len(df) - 1)
            signals.append(TradeSignal(
                model_type=EntryModelType.MODEL_TS_M15,
                symbol=self.symbol,
                direction=direction,
                storyline_key="TS_M15",
                storyline_desc=desc,
                storyline_rejection=float(ts.price),
                ftfl_tf="M15", stfl_tf="M15", ttfl_tf="M15",
                primary_plan=plan,
                confidence=confidence,
                rationale=desc,
                formation_time=int(times[min(anchor, len(times) - 1)]),
                distance_to_entry=round(abs(current - plan.buffered_entry), 2),
            ))

        signals.sort(key=lambda s: s.distance_to_entry)
        for rank, sig in enumerate(signals, start=1):
            sig.priority_rank = rank
        return signals

    # ------------------------------------------------------------------
    def _sr_shelf_break(self, sr_levels, ts_price: float, f: int, bullish: bool):
        """First body close through the nearest S/R shelf after the TS.
        Returns (bar_idx, shelf_price) or None. The shelf must sit within
        TS_SR_SHELF_DIST of the TS and be fully formed before the bar."""
        if bullish:
            shelves = sorted(
                (lv for lv in sr_levels
                 if lv.level_type == LevelType.RESISTANCE
                 and lv.price >= ts_price
                 and lv.price - ts_price <= TS_SR_SHELF_DIST),
                key=lambda lv: lv.price,
            )
            closes = self.df["close"].values
            for shelf in shelves:
                for m in range(f + 1, len(self.df)):
                    if shelf.candle_index >= m:
                        continue  # not knowable yet at bar m
                    if closes[m] > shelf.price:
                        return (m, shelf.price)
        else:
            shelves = sorted(
                (lv for lv in sr_levels
                 if lv.level_type == LevelType.SUPPORT
                 and lv.price <= ts_price
                 and ts_price - lv.price <= TS_SR_SHELF_DIST),
                key=lambda lv: -lv.price,
            )
            closes = self.df["close"].values
            for shelf in shelves:
                for m in range(f + 1, len(self.df)):
                    if shelf.candle_index >= m:
                        continue  # not knowable yet at bar m
                    if closes[m] < shelf.price:
                        return (m, shelf.price)
        return None

    def _swing_liquidity(self, start_idx: int, bullish: bool):
        """Most recent fractal swing extreme after `start_idx` (2 bars each
        side), within TS_LIQ_MAX_BARS bars. The "wick low/high" liquidity
        used when no structural IDM formed. Returns (price, idx) or None."""
        n = len(self.df)
        hi = min(n - 3, start_idx + TS_LIQ_MAX_BARS)
        if bullish:
            lows = self.df["low"].values
            for i in range(hi, start_idx, -1):
                if lows[i] < min(lows[i - 2], lows[i - 1],
                                 lows[i + 1], lows[i + 2]):
                    return (float(lows[i]), i)
        else:
            highs = self.df["high"].values
            for i in range(hi, start_idx, -1):
                if highs[i] > max(highs[i - 2], highs[i - 1],
                                  highs[i + 1], highs[i + 2]):
                    return (float(highs[i]), i)
        return None

    def _compute_atr(self, period: int = 14) -> list:
        h = self.df["high"]
        l = self.df["low"]
        c = self.df["close"]
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                       axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=1,
                      adjust=False).mean().tolist()
