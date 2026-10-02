"""
order_manager.py — MetaTrader 5 Live Order Placement & Execution Engine

Capabilities:
  - Places pending Limit orders (BUY_LIMIT / SELL_LIMIT) with spread buffer
  - Attaches calculated Stop Loss and Take Profit (Draw on Liquidity)
  - Fetches live Open Positions and Pending Orders for dashboard
  - Modifies SL to Break-Even upon reaching intermediate obstacles
  - Executes 80% partial profit close at obstacles
  - Closes positions on demand
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import logging
import MetaTrader5 as mt5

from execution.risk_manager import PositionPlan
from strategy.storyline_engine import BiasDirection
from data.mt5_loader import _mt5_lock

logger = logging.getLogger("MSNR_OrderManager")


@dataclass
class LivePosition:
    ticket: int
    symbol: str
    order_type: str            # 'BUY', 'SELL', 'BUY_LIMIT', 'SELL_LIMIT'
    volume: float
    open_price: float
    current_price: float
    sl: float
    tp: float
    profit: float
    comment: str
    time_open: str


class OrderManager:
    """
    Executes and manages orders directly in MetaTrader 5.

    Video 11 trade management: at an intermediate obstacle, close ~80% of the
    position (partial profit), move the remaining runner's SL to breakeven,
    and let 20% run to the final Draw on Liquidity. Obstacle targets recorded
    per ticket via track_obstacle() (from PositionPlan.obstacle_tp) drive
    manage_position_obstacles().
    """

    #: Fraction closed at an intermediate obstacle (Video 11: 80% partial).
    PARTIAL_FRACTION = 0.8

    def __init__(self, magic_number: int = 888999):
        self.magic_number = magic_number
        # ticket -> obstacle price for open positions carrying a runner plan.
        self._obstacle_map: Dict[int, float] = {}

    def place_limit_order(self, plan: PositionPlan) -> Dict[str, any]:
        """
        Places a pending Limit Order in MT5 based on a calculated PositionPlan.
        Uses the same MT5_PATH/timeout as MT5DataLoader for consistent terminal binding.
        """
        with _mt5_lock:
            # Check terminal state (same init params as data.mt5_loader.MT5DataLoader)
            from config.settings import MT5_PATH, MT5_TIMEOUT
            init_params: Dict[str, any] = {"timeout": MT5_TIMEOUT}
            if MT5_PATH:
                init_params["path"] = MT5_PATH
            if not mt5.initialize(**init_params):
                return {"success": False, "error": f"MT5 not initialized: {mt5.last_error()}"}

            is_buy = plan.direction == BiasDirection.BULLISH
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT

            # Verify symbol selection
            selected = mt5.symbol_select(plan.symbol, True)
            if not selected:
                return {"success": False, "error": f"Failed to select symbol {plan.symbol}"}

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": plan.symbol,
                "volume": float(plan.lot_size),
                "type": order_type,
                "price": float(plan.buffered_entry),
                "sl": float(plan.stop_loss),
                "tp": float(plan.take_profit),
                "deviation": 20,
                "magic": self.magic_number,
                "comment": f"MSNR_{plan.model_name[:8]}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)

            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                err_code = result.retcode if result else mt5.last_error()
                err_desc = result.comment if result else "Order Send Failed"
                logger.error(f"Failed to place {plan.symbol} limit order: {err_code} - {err_desc}")
                return {"success": False, "retcode": err_code, "comment": err_desc}

            logger.info(f"Successfully placed {plan.symbol} Limit Order #{result.order} @ {plan.buffered_entry:.2f}")
            if plan.obstacle_tp:
                self.track_obstacle(int(result.order), float(plan.obstacle_tp))
            return {
                "success": True,
                "ticket": result.order,
                "price": plan.buffered_entry,
                "sl": plan.stop_loss,
                "tp": plan.take_profit,
                "obstacle_tp": plan.obstacle_tp,
                "lots": plan.lot_size
            }

    def get_open_positions(self) -> List[LivePosition]:
        """Fetch all open positions from MT5."""
        with _mt5_lock:
            positions = mt5.positions_get()
            if positions is None:
                return []

            result = []
            for p in positions:
                order_type_str = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                result.append(LivePosition(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    order_type=order_type_str,
                    volume=float(p.volume),
                    open_price=float(p.price_open),
                    current_price=float(p.price_current),
                    sl=float(p.sl),
                    tp=float(p.tp),
                    profit=float(p.profit),
                    comment=str(p.comment),
                    time_open=str(p.time)
                ))
            return result

    def get_pending_orders(self) -> List[LivePosition]:
        """Fetch all active pending orders from MT5."""
        with _mt5_lock:
            orders = mt5.orders_get()
            if orders is None:
                return []

            result = []
            for o in orders:
                type_name = "BUY_LIMIT" if o.type == mt5.ORDER_TYPE_BUY_LIMIT else (
                    "SELL_LIMIT" if o.type == mt5.ORDER_TYPE_SELL_LIMIT else "PENDING"
                )
                result.append(LivePosition(
                    ticket=o.ticket,
                    symbol=o.symbol,
                    order_type=type_name,
                    volume=float(o.volume_current),
                    open_price=float(o.price_open),
                    current_price=float(o.price_current),
                    sl=float(o.sl),
                    tp=float(o.tp),
                    profit=0.0,
                    comment=str(o.comment),
                    time_open=str(o.time_setup)
                ))
            return result

    def close_position(self, ticket: int) -> bool:
        """Close an open position by ticket number."""
        with _mt5_lock:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False

            p = pos[0]
            close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(p.symbol)
            close_price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket,
                "symbol": p.symbol,
                "volume": float(p.volume),
                "type": close_type,
                "price": close_price,
                "deviation": 20,
                "magic": self.magic_number,
                "comment": "MSNR_Manual_Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            res = mt5.order_send(request)
            return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def cancel_order(self, ticket: int) -> bool:
        """Cancel a pending limit order by ticket number."""
        with _mt5_lock:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket
            }
            res = mt5.order_send(request)
            return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    # ------------------------------------------------------------------
    # Video 11 obstacle management: 80% partial + breakeven runner
    # ------------------------------------------------------------------

    def track_obstacle(self, ticket: int, obstacle_price: float):
        """Record the intermediate obstacle (80% exit) for an open position."""
        if obstacle_price:
            self._obstacle_map[int(ticket)] = float(obstacle_price)

    def untrack_obstacle(self, ticket: int):
        """Forget obstacle state (position closed/cancelled)."""
        self._obstacle_map.pop(int(ticket), None)

    @staticmethod
    def _round_volume(symbol: str, volume: float) -> float:
        """Round a partial volume to the symbol's lot step (min 0.01)."""
        try:
            info = mt5.symbol_info(symbol)
            step = float(info.volume_step) if info and info.volume_step else 0.01
            vmin = float(info.volume_min) if info and info.volume_min else 0.01
        except Exception:
            step, vmin = 0.01, 0.01
        if step <= 0:
            step = 0.01
        lots = round(volume / step) * step
        return round(max(lots, 0.0), 2) if lots >= vmin else 0.0

    def partial_close(self, ticket: int, fraction: float = PARTIAL_FRACTION) -> Dict[str, any]:
        """
        Close `fraction` (default 80%) of an open position, leaving a runner.
        Returns a result dict; on success also records remaining volume.
        """
        with _mt5_lock:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return {"success": False, "error": f"Position {ticket} not found"}
            p = pos[0]
            close_vol = self._round_volume(p.symbol, float(p.volume) * fraction)
            if close_vol <= 0:
                # Position too small to split: close it fully instead.
                close_vol = float(p.volume)
            close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            try:
                tick = mt5.symbol_info_tick(p.symbol)
                close_price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
            except Exception as e:
                return {"success": False, "error": f"No tick for {p.symbol}: {e}"}
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket,
                "symbol": p.symbol,
                "volume": close_vol,
                "type": close_type,
                "price": close_price,
                "deviation": 20,
                "magic": self.magic_number,
                "comment": f"MSNR_PARTIAL_{int(fraction * 100)}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            res = mt5.order_send(request)
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                err = res.retcode if res else mt5.last_error()
                return {"success": False, "retcode": err,
                        "comment": res.comment if res else "Partial close failed"}
            remaining = round(float(p.volume) - close_vol, 2)
            logger.info(f"Partial closed {fraction * 100:.0f}% of #{ticket} ({close_vol} lots), {remaining} left running.")
            return {"success": True, "ticket": ticket, "closed_volume": close_vol,
                    "remaining_volume": remaining}

    def move_sl_to_breakeven(self, ticket: int, buffer_points: float = 5.0) -> bool:
        """
        Move a position's SL to its entry price (+/- small buffer), locking a
        breakeven runner after the 80% partial (Video 11).
        """
        with _mt5_lock:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            p = pos[0]
            try:
                point = mt5.symbol_info(p.symbol).point or 0.01
            except Exception:
                point = 0.01
            if p.type == mt5.POSITION_TYPE_BUY:
                be_sl = float(p.price_open) + buffer_points * float(point)
                if float(p.sl) >= be_sl:
                    return True  # already at/above breakeven
            else:
                be_sl = float(p.price_open) - buffer_points * float(point)
                if float(p.sl) and float(p.sl) <= be_sl:
                    return True
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": p.ticket,
                "symbol": p.symbol,
                "sl": be_sl,
                "tp": float(p.tp),
                "magic": self.magic_number,
            }
            res = mt5.order_send(request)
            ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
            if ok:
                logger.info(f"Moved SL to breakeven for #{ticket} (SL={be_sl}).")
            return ok

    def manage_position_obstacles(self) -> List[Dict[str, any]]:
        """
        Scan open positions with tracked obstacles; for each position whose
        current price has reached its obstacle, execute the Video 11 sequence:
        80% partial close + SL to breakeven. Intended for a periodic management
        loop (or POST /api/orders/manage-obstacles).
        """
        outcomes: List[Dict[str, any]] = []
        for pos in self.get_open_positions():
            obstacle = self._obstacle_map.get(int(pos.ticket))
            if not obstacle:
                continue
            reached = (pos.current_price >= obstacle if pos.order_type == "BUY"
                       else pos.current_price <= obstacle)
            if not reached:
                outcomes.append({"ticket": pos.ticket, "action": "hold", "obstacle": obstacle})
                continue
            part = self.partial_close(int(pos.ticket), self.PARTIAL_FRACTION)
            be = self.move_sl_to_breakeven(int(pos.ticket))
            self.untrack_obstacle(int(pos.ticket))
            outcomes.append({"ticket": pos.ticket, "action": "partial_and_breakeven",
                             "obstacle": obstacle, "partial": part, "breakeven": be})
        return outcomes
