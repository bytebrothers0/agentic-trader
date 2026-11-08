"""
execution/agent_orders.py — turn the agent's proposals into *real* MT5 orders.

The agent stays propose-only in its vocabulary: ``propose_trade`` writes a
``Proposal`` into the store, and this module is the only thing that looks at a
proposal and sends an order. Nothing inside the agent loop or the detectors
knows MT5 exists here — the seam is one function (:func:`execute_proposal`),
called from ``AgentService._sync_proposal_orders`` after every turn.

What a proposal becomes
-----------------------
A pending order in the terminal, **with the proposal's SL and TP attached** —
the broker-side exit *is* the agent's exit; nothing needs to watch fills to
close the trade. The order type is chosen by which side of the market the entry
rests on (and by ``AGENT_ORDER_STYLE``):

===============  ============  ================================================
bias             entry vs ask     order
===============  ============  ================================================
bullish          above ask     BUY_STOP   (auto) / BUY_STOP_LIMIT (stop_limit)
bullish          at/below ask  BUY_LIMIT  (both styles)
bearish          below bid     SELL_STOP  (auto) / SELL_STOP_LIMIT (stop_limit)
bearish          at/above bid  SELL_LIMIT (both styles)
===============  ============  ================================================

The volume is the FIXED lot from ``AGENT_FIXED_LOT`` — every agent order is the
same size; proposal confidence plays no part in sizing. All settings
(``AGENT_EXECUTE_TRADES``, ``AGENT_FIXED_LOT``…) are read by the *caller* per
sync, so a config edit applies from the next proposal with no restart.

Deduplication and caps are the caller's job (it can see the whole store's
history); this module validates one proposal against one terminal and reports
honestly: ``{"success": False, "comment": ...}`` never raises past a wiring
fault, and a refused order leaves the proposal unmarked (retried next turn).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agentic.models import Proposal

#: Stop-limit body offset (points): the limit price a triggered stop-limit
#: rests at, just inside the trigger — caps the slippage of the second leg.
STOP_LIMIT_OFFSET_PTS = 10


def validate_proposal(proposal: Proposal) -> Optional[str]:
    """Whether a proposal is *placeable*; a refusal reason or None.

    A proposal must name an actionable bias, carry all three levels, and keep
    them non-crossing (a bullish long that stops out before entry is not a
    trade); anything else is refused before the terminal is even touched.
    """
    if proposal.bias not in ("bullish", "bearish"):
        return "bad_bias: execute only bullish/bearish proposals"
    entry, sl, tp = proposal.entry, proposal.sl, proposal.tp
    for name, value in (("entry", entry), ("sl", sl), ("tp", tp)):
        if value is None:
            return f"missing_{name}: a proposal needs entry, sl and tp"
    entry, sl, tp = float(entry), float(sl), float(tp)
    if proposal.bias == "bullish" and not (sl < entry < tp):
        return "crossed_levels: bullish needs sl < entry < tp"
    if proposal.bias == "bearish" and not (tp < entry < sl):
        return "crossed_levels: bearish needs tp < entry < sl"
    return None


def select_order_type(bias: str, entry: float, bid: float, ask: float) -> str:
    """The natural pending order for an entry given the live market.

    Beyond the market a breakout-style entry is a *stop*; behind the market a
    retracement entry is a *limit* (pure, named types the caller may re-map).
    """
    if bias == "bullish":
        return "buy_stop" if entry > ask else "buy_limit"
    return "sell_stop" if entry < bid else "sell_limit"


def execute_proposal(
    proposal: Proposal,
    *,
    symbol: str,
    fixed_lot: float,
    magic: int,
    style: str = "auto",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Send ``proposal`` as a pending order. Returns a result dict.

    ``{"success": True, "ticket": ..., "order_type": ..., ...}`` on a placed
    order; ``{"success": False, "comment": ...}`` on a rejection (validation
    error, MT5 refusal). Never raises for a *trade* outcome — the caller marks
    the proposal from the dict, visibly either way.

    ``dry_run=True`` walks the whole path against the live terminal — symbol,
    tick, lot rounding, style resolution — but stops short of ``order_send``,
    returning the exact request it would have sent. A way to rehearse the
    wiring without risking a fill.
    """
    failure = validate_proposal(proposal)
    if failure:
        return {"success": False, "comment": failure}

    try:
        mt5_cm = _terminal()
        mt5 = mt5_cm.__enter__()
    except Exception as exc:  # noqa: BLE001 — terminal wiring is a trade outcome too
        return {"success": False, "comment": f"terminal_unavailable: {exc}"}
    try:
        return _send(
            mt5, proposal, symbol=symbol, fixed_lot=fixed_lot, magic=magic,
            style=style, dry_run=dry_run,
        )
    finally:
        mt5_cm.__exit__(None, None, None)


def _send(
    mt5: Any,
    proposal: Proposal,
    *,
    symbol: str,
    fixed_lot: float,
    magic: int,
    style: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"success": False, "comment": f"symbol_unavailable: {symbol}"}
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or tick.bid <= 0 or tick.ask <= 0:
        return {"success": False, "comment": f"no_tick: {symbol}"}

    point = float(info.point or 0.01)
    digits = int(info.digits or 2)
    step = float(info.volume_step or 0.01) or 0.01
    vmin = float(info.volume_min or 0.01) or 0.01

    lots = round(float(fixed_lot) / step) * step
    lots = round(lots, 2)
    if lots < vmin:
        return {
            "success": False,
            "comment": f"invalid_lots: {fixed_lot} rounds below the symbol minimum {vmin}",
        }

    entry, sl, tp = (round(float(v), digits)
                     for v in (proposal.entry, proposal.sl, proposal.tp))
    natural = select_order_type(proposal.bias, entry, float(tick.bid), float(tick.ask))
    order_type, price, stoplimit, fallback = _resolve_style(
        mt5, natural, proposal.bias, entry, style, point, digits
    )
    request: Dict[str, Any] = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": lots,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": int(magic),
        "comment": f"AG{str(proposal.id)[-8:]}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    if stoplimit is not None:
        request["stoplimit"] = round(stoplimit, digits)
    placed_name = (
        natural.replace("_stop", "_stop_limit") if stoplimit is not None else natural
    )

    if dry_run:
        # rehearse only: stop short of order_send, hand back the exact request
        request.pop("deviation", None)
        return {
            "success": True,
            "dry_run": True,
            "order_type": placed_name,
            "market": f"bid {float(tick.bid):.{digits}f} / ask {float(tick.ask):.{digits}f}",
            "request": request,
            "lots": lots,
        }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result is not None else mt5.last_error()
        note = result.comment if result is not None else "Order Send Failed"
        return {
            "success": False,
            "retcode": code,
            "comment": f"order_send failed: {note}",
            "order_type": natural,
            "fallback": fallback,
            "lots": lots,
        }
    placed = placed_name
    return {
        "success": True,
        "ticket": int(result.order),
        "order_type": placed,
        "price": price,
        "stoplimit": stoplimit,
        "sl": sl,
        "tp": tp,
        "lots": lots,
        "magic": int(magic),
        "fallback": fallback,
    }


def _terminal():
    """A context manager yielding the ``mt5`` module with the terminal inited,
    mirroring OrderManager's binding (same MT5_PATH / timeout), releasing the
    shared loader lock around every terminal touch.

    **Never** ``shutdown()`` on exit: ``mt5.shutdown`` tears down the whole
    process's single MT5 connection — the candles loader, the order manager and
    every other MT5 user in the server would go down with it (``-10004 No IPC
    connection`` afterwards). ``initialize`` is idempotent for an already
    attached process, so entering is cheap and leaving owns nothing."""
    from data.mt5_loader import _mt5_lock

    class _Term:
        def __enter__(self):
            import MetaTrader5 as mt5

            from config.settings import MT5_PATH, MT5_TIMEOUT

            self._lock = _mt5_lock
            self._lock.acquire()
            init_params: Dict[str, Any] = {"timeout": MT5_TIMEOUT}
            if MT5_PATH:
                init_params["path"] = MT5_PATH
            if not mt5.initialize(**init_params):
                raise RuntimeError(f"MT5 not initialized: {mt5.last_error()}")
            return mt5

        def __exit__(self, *exc):
            self._lock.release()
            return False

    return _Term()


def _resolve_style(
    mt5: Any,
    natural: str,
    bias: str,
    entry: float,
    style: str,
    point: float,
    digits: int,
) -> Tuple[int, float, Optional[float], str]:
    """``(MT5 type, trigger price, stoplimit|None, fallback note)``.

    ``auto`` keeps the natural limit/stop. ``stop_limit`` wraps the *stop* side
    into a stop-limit order (the stop-limit's limited second price sits
    ``STOP_LIMIT_OFFSET_PTS`` inside the trigger, capping slippage on the fill).
    A stop-limit style requested for a *limit-side* entry is impossible (the
    trigger would sit behind the market), so it falls back to a plain limit and
    says so.
    """
    types = {
        "buy_limit": mt5.ORDER_TYPE_BUY_LIMIT,
        "buy_stop": mt5.ORDER_TYPE_BUY_STOP,
        "sell_limit": mt5.ORDER_TYPE_SELL_LIMIT,
        "sell_stop": mt5.ORDER_TYPE_SELL_STOP,
        "buy_stop_limit": mt5.ORDER_TYPE_BUY_STOP_LIMIT,
        "sell_stop_limit": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
    }
    if str(style or "").lower() != "stop_limit":
        return types[natural], round(entry, digits), None, ""
    if natural.endswith("_limit"):
        # A stop-limit's trigger must sit *beyond* the market; this entry
        # rests behind it. The honest order here is the plain limit.
        return types[natural], round(entry, digits), None, "stop_limit_style_fell_back_to_limit"

    offset = STOP_LIMIT_OFFSET_PTS * point
    if natural == "buy_stop":
        return (
            types["buy_stop_limit"],
            round(entry, digits),
            round(entry - offset, digits),
            "",
        )
    return (
        types["sell_stop_limit"],
        round(entry, digits),
        round(entry + offset, digits),
        "",
    )
