"""
risk_manager.py — MSNR Position Sizing & Risk Management Engine

Rules (from Advanced MSNR, Videos 8, 9, 10, 11):
  1. Risk per trade = 1.0% of Account Equity (customizable).
  2. Fixed Stop Loss:
     - XAUUSD (Gold): Fixed 300 points (3.00 price units / 30 pips).
     - Other pairs: Calculated distance to TTFL/STFL SL boundary.
  3. Spread Buffer (Crucial Execution Rule):
     - Buy Limit: Add +30 points (+0.30 price units / 0.5-1.0 pip) ABOVE entry so broker triggers order even on spread.
     - Sell Limit: Subtract -30 points (-0.30 price units / 0.5-1.0 pip) BELOW entry.
  4. Sizing Multipliers:
     - A+ Setup (Fresh FTFL + direct next-candle tap): 100% of risk (1.0% equity).
     - Reduced Setup (Delayed tap / Unfresh Apex): 20% of risk (0.2% equity).
     - QM-only Entry: 20% of risk.
     - Split Entry (Model B/C): 70% at Equilibrium, 30% at Body.
  5. Trade Management at Obstacles:
     - Close 80% of position size at major intermediate obstacle.
     - Move SL to Break-Even (entry price + small commission buffer).
     - Allow 20% runner to reach final Draw on Liquidity (TP target).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple
import logging
import MetaTrader5 as mt5

from config.settings import (
    RISK_PERCENT,
    FULL_RISK_FACTOR,
    REDUCED_RISK_FACTOR,
    QM_RISK_FACTOR,
    SPLIT_ENTRY_MAIN,
    SPLIT_ENTRY_SECONDARY,
    INSTRUMENT_SPECS,
)

logger = logging.getLogger("MSNR_RiskManager")


class BiasDirection(Enum):
    """Trade direction. Lives here (not in strategy/) so execution and
    future entry models share it without importing removed engines."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class AccountMetrics:
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str = "USD"
    leverage: int = 100


@dataclass
class PositionPlan:
    symbol: str
    direction: BiasDirection
    raw_entry: float
    buffered_entry: float       # Entry price with spread buffer
    stop_loss: float
    sl_points: float
    take_profit: float          # Final Draw on Liquidity
    obstacle_tp: Optional[float]# Intermediate 80% exit level
    risk_amount_usd: float
    lot_size: float
    risk_percent: float = 1.0
    model_name: str = "Model A"

    def __repr__(self) -> str:
        return (
            f"PositionPlan({self.symbol} {self.direction.value} {self.lot_size} Lots | "
            f"Entry: {self.buffered_entry:.2f} | SL: {self.stop_loss:.2f} ({self.sl_points:.0f} pts) | "
            f"TP: {self.take_profit:.2f} | Risk: ${self.risk_amount_usd:.2f})"
        )


class RiskManager:
    """
    Calculates exact position sizing, SL/TP placement, and spread buffers.
    """

    def __init__(self, risk_percent: float = RISK_PERCENT):
        self.risk_percent = risk_percent

    def get_account_metrics(self) -> AccountMetrics:
        """Fetch live account balance, equity, and margin from MT5."""
        acc = mt5.account_info()
        if acc is None:
            # Fallback to simulated $10,000 account if terminal not logged in
            return AccountMetrics(
                balance=10000.0,
                equity=10000.0,
                margin=0.0,
                free_margin=10000.0,
                currency="USD",
                leverage=100
            )

        return AccountMetrics(
            balance=float(acc.balance),
            equity=float(acc.equity),
            margin=float(acc.margin),
            free_margin=float(acc.margin_free),
            currency=str(acc.currency),
            leverage=int(acc.leverage)
        )

    def calculate_position(
        self,
        symbol: str,
        direction: BiasDirection,
        entry_price: float,
        sl_reference: float,
        final_tp: float,
        intermediate_obstacle: Optional[float] = None,
        risk_multiplier: float = 1.0,
        model_name: str = "Model A",
        sl_points_override: Optional[float] = None,
    ) -> PositionPlan:
        """
        Calculates full position plan with spread buffer, exact SL/TP, and lot size.
        sl_points_override lets custom engines (e.g. TS M15: 350pt) size off
        their own fixed SL instead of the instrument default.
        """
        metrics = self.get_account_metrics()
        is_bullish = direction == BiasDirection.BULLISH

        # 1. Instrument specifications (symbol-specific; do NOT reuse Gold sizing for FX)
        gold_specs = INSTRUMENT_SPECS.get("XAUUSD", {
            "point_value": 0.01,
            "sl_points": 300,
            "spread_buffer_pts": 10,  # Video 10: 5-10 points
            "min_lot": 0.01,
            "lot_step": 0.01,
            "contract_size": 100,
            "digits": 2
        })

        sym_u = symbol.upper()
        if "XAU" in sym_u or "GOLD" in sym_u:
            specs = gold_specs
            sl_points = sl_points_override or specs.get("sl_points", 300)
            buffer_pts = specs.get("spread_buffer_pts", 10)
            point_val = specs.get("point_value", 0.01)
            contract_size = specs.get("contract_size", 100)
            min_lot = specs.get("min_lot", 0.01)
            lot_step = specs.get("lot_step", 0.01)
        else:
            # Generic FX / crypto fallback: standard 100k contract, point by quote currency.
            is_jpy = "JPY" in sym_u
            point_val = 0.01 if is_jpy else 0.0001
            buffer_pts = 10
            contract_size = 100_000
            min_lot = 0.01
            lot_step = 0.01
            # Allow per-symbol overrides if added to INSTRUMENT_SPECS later.
            for key, cand in INSTRUMENT_SPECS.items():
                if key.upper() in sym_u or sym_u in key.upper():
                    contract_size = cand.get("contract_size", contract_size)
                    min_lot = cand.get("min_lot", min_lot)
                    lot_step = cand.get("lot_step", lot_step)
                    buffer_pts = cand.get("spread_buffer_pts", buffer_pts)
                    point_val = cand.get("point_value", point_val)
                    break
            # Calculate distance to SL reference in points
            raw_dist = abs(entry_price - sl_reference)
            sl_points = max(30, int(raw_dist / point_val)) if point_val > 0 else 30

        # 2. Spread Buffer Application:
        # Buys: Entry is slightly higher to guarantee fill
        # Sells: Entry is slightly lower
        buffer_offset = buffer_pts * point_val
        if is_bullish:
            buffered_entry = entry_price + buffer_offset
            stop_loss = buffered_entry - (sl_points * point_val)
        else:
            buffered_entry = entry_price - buffer_offset
            stop_loss = buffered_entry + (sl_points * point_val)

        # 3. Position Sizing Calculation
        # Risk Amount = Equity * (Risk% / 100) * RiskMultiplier
        target_risk_usd = (metrics.equity * (self.risk_percent / 100.0)) * risk_multiplier

        # Lot size formula: TargetRisk / (SL_points * point_val * contract_size)
        risk_per_1_lot = sl_points * point_val * contract_size

        if risk_per_1_lot > 0:
            raw_lots = target_risk_usd / risk_per_1_lot
        else:
            raw_lots = min_lot

        # Clamp to broker limits
        lots = max(min_lot, round(raw_lots / lot_step) * lot_step)
        lots = round(lots, 2)

        actual_risk_usd = lots * risk_per_1_lot

        return PositionPlan(
            symbol=symbol,
            direction=direction,
            raw_entry=round(entry_price, 3),
            buffered_entry=round(buffered_entry, 3),
            stop_loss=round(stop_loss, 3),
            sl_points=sl_points,
            take_profit=round(final_tp, 3),
            obstacle_tp=round(intermediate_obstacle, 3) if intermediate_obstacle else None,
            risk_amount_usd=round(actual_risk_usd, 2),
            lot_size=lots,
            risk_percent=self.risk_percent * risk_multiplier,
            model_name=model_name
        )
