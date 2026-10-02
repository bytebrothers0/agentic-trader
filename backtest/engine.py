"""
backtest/engine.py — MSNR walk-forward backtesting engine (v1).

Why our own engine instead of backtesting.py / vectorbt / Strategy Tester?
  - The edge lives in proprietary multi-timeframe logic (Storyline -> FTFL ->
    STFL -> TTFL -> obstacles -> 80% partial + breakeven runner). Generic
    frameworks can't express that cascade without rewriting it anyway.
  - The MQL5 EA in mql5/ covers only the EMS variant, not this Python MSNR core.
  - So the honest setup is: reuse THIS repo's EntryEngine/indicators directly
    on historical bars, with a small limit-order fill simulator around them.

No-lookahead discipline (the #1 backtesting sin):
  - At each step time T, every timeframe is sliced to bars with index <= T and
    EntryEngine runs ONLY on that past-only window. Freshness, QM, Apex and
    storyline states can therefore never peek at future bars.
  - Signals are recomputed every `step_bars` step-TF bars (default 24 H1 bars
    ~= daily) to keep runtime sane; fills are still evaluated bar-by-bar.

Fill simulator assumptions (conservative where ambiguous):
  - BUY_LIMIT fills if bar low <= entry; SELL_LIMIT if bar high >= entry.
  - If SL and TP are both touched in the same bar, SL counts first.
  - Obstacle (80% partial + SL->entry runner) is checked before final TP.
  - No spread/commission/slippage by default (slippage_pts configurable).
  - FX P/L assumes quote-currency ~= USD (exact for XXX/USD pairs).
  - v1 trades the primary (#1) signal only, one open position at a time.

Reference: strategy_notes/video_11.md (obstacles, 80% partial + BE),
           strategy_notes/video_12.md (pullback vs continuation TP).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from strategy.entry_engine import EntryEngine, TradeSignal
from strategy.storyline_engine import BiasDirection


@dataclass
class SimTrade:
    ticket: int
    model: str
    direction: str
    lots: float
    entry: float
    sl: float
    tp: float
    obstacle: Optional[float]
    open_time: pd.Timestamp
    close_time: Optional[pd.Timestamp] = None
    exit_price: float = 0.0
    pnl_usd: float = 0.0
    close_reason: str = "open"  # tp | sl | obstacle_runner_tp | obstacle_runner_sl | expired | partial_then_*
    partial_pnl_usd: float = 0.0


@dataclass
class BacktestResult:
    trades: List[SimTrade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)
    stats: Dict[str, float] = field(default_factory=dict)


def _specs_for(symbol: str):
    """(point_value, contract_size) — mirrors execution/risk_manager.py."""
    sym_u = symbol.upper()
    if "XAU" in sym_u or "GOLD" in sym_u:
        return 0.01, 100
    if "JPY" in sym_u:
        return 0.01, 100_000
    return 0.0001, 100_000


class Backtester:
    """
    Walk-forward simulator over a {tf: DataFrame} history dict.

    Parameters
    ----------
    data : dict of {TF: pd.DataFrame} with DatetimeIndex + OHLC columns.
    symbol : traded symbol (sizing + P/L assumptions).
    initial_balance : starting equity in USD.
    risk_percent : base risk % per trade (signal plans scale it via risk_multiplier).
    step_tf : timeframe whose bars drive the simulation clock (default H1).
    step_bars : recompute signals every N step-bars (default 24 ~= daily on H1).
    order_expiry_bars : cancel unfilled pendings after N step-bars (default 48).
    max_entry_distance_pct : ignore primary signals whose entry is further than
        this % from current price (stale zones from old storylines).
    slippage_pts : extra adverse fill distance in points (default 0).
    reentry_cooldown_bars : after a stopped-out trade, ignore the same
        model+direction+entry zone for N step-bars (default 24). Prevents the
        simulator from re-buying an identical failed zone every recompute.
    engine : "msnr" (multi-TF EntryEngine) or "ts_m15" (M15 TSEntryEngine).
    """

    STEP_TFS = ("M15", "H1", "H4", "D1")

    def __init__(
        self,
        data: Dict[str, pd.DataFrame],
        symbol: str = "XAUUSD",
        initial_balance: float = 10_000.0,
        risk_percent: float = 1.0,
        step_tf: str = "H1",
        step_bars: int = 24,
        order_expiry_bars: int = 48,
        max_entry_distance_pct: float = 1.5,
        slippage_pts: float = 0.0,
        reentry_cooldown_bars: int = 24,
        engine: str = "msnr",
    ):
        self.symbol = symbol
        self.initial_balance = float(initial_balance)
        self.risk_percent = float(risk_percent)
        self.step_tf = step_tf.upper()
        if self.step_tf not in data:
            for alt in self.STEP_TFS:
                if alt in data:
                    self.step_tf = alt
                    break
        self.data = {k.upper(): v.copy() for k, v in data.items()}
        self.step_bars = max(1, int(step_bars))
        self.order_expiry_bars = int(order_expiry_bars)
        self.max_entry_distance_pct = float(max_entry_distance_pct)
        self.slippage_pts = float(slippage_pts)
        self.reentry_cooldown_bars = int(reentry_cooldown_bars)
        self.engine = str(engine).lower()
        self.point_value, self.contract_size = _specs_for(symbol)

    # ------------------------------------------------------------------
    # Sizing (equity-driven; mirrors RiskManager math without live MT5)
    # ------------------------------------------------------------------

    def _lots_for(self, equity: float, entry: float, sl: float, plan_risk_pct: float) -> float:
        risk_usd = equity * (plan_risk_pct / 100.0)
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return 0.01
        sl_points = sl_dist / self.point_value
        per_lot = sl_points * self.point_value * self.contract_size
        if per_lot <= 0:
            return 0.01
        lots = round((risk_usd / per_lot) / 0.01) * 0.01
        return max(0.01, round(lots, 2))

    def _pnl(self, direction: str, lots: float, entry: float, exit_: float) -> float:
        signed = (exit_ - entry) if direction == "BULLISH" else (entry - exit_)
        return signed * lots * self.contract_size

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> BacktestResult:
        step_df = self.data[self.step_tf]
        step_idx = list(range(0, len(step_df), self.step_bars))
        equity = self.initial_balance
        ticket_seq = 0
        pending: Optional[dict] = None   # {signal, plan, lots, placed_step, expiry_step}
        open_pos: Optional[SimTrade] = None
        be_sl: Optional[float] = None    # breakeven SL after obstacle partial
        cooled: Dict[tuple, int] = {}    # (model, direction, entry) -> step-bar idx of stop-out
        result = BacktestResult()
        result.equity_curve.append({"time": step_df.index[0], "equity": equity})

        for si, upto in enumerate(step_idx):
            step_time = step_df.index[upto]
            # Past-only window on every timeframe (no lookahead).
            window = {tf: df[df.index <= step_time] for tf, df in self.data.items()}
            if any(len(w) < 10 for w in window.values()):
                continue
            current_price = float(step_df["close"].iloc[upto])

            # (Re)compute signals on past-only data.
            # msnr = multi-TF EntryEngine; ts_m15 = M15-only TSEntryEngine.
            try:
                if self.engine == "ts_m15":
                    from strategy.ts_entry import TSEntryEngine
                    signals = TSEntryEngine(window[self.step_tf],
                                            symbol=self.symbol).scan()
                else:
                    engine = EntryEngine(window, symbol=self.symbol)
                    signals = engine.scan_all_models()
            except Exception:
                signals = []
            primary = signals[0] if signals else None

            # Manage open position bar-by-bar until the next recompute step.
            horizon = step_idx[si + 1] if si + 1 < len(step_idx) else len(step_df)
            for bi in range(upto, horizon):
                bar = step_df.iloc[bi]
                bar_time = step_df.index[bi]

                # Fill pending limit (conservative touch fill + slippage).
                if pending and open_pos is None:
                    plan = pending["plan"]
                    sig = pending["signal"]
                    slip = self.slippage_pts * self.point_value
                    if sig.direction == BiasDirection.BULLISH:
                        if bar["low"] <= plan.buffered_entry:
                            ticket_seq += 1
                            open_pos = SimTrade(
                                ticket=ticket_seq, model=sig.model_type.value,
                                direction="BULLISH", lots=pending["lots"],
                                entry=plan.buffered_entry + slip,
                                sl=plan.stop_loss, tp=plan.take_profit,
                                obstacle=plan.obstacle_tp, open_time=bar_time,
                            )
                            be_sl = None
                            pending = None
                    else:
                        if bar["high"] >= plan.buffered_entry:
                            ticket_seq += 1
                            open_pos = SimTrade(
                                ticket=ticket_seq, model=sig.model_type.value,
                                direction="BEARISH", lots=pending["lots"],
                                entry=plan.buffered_entry - slip,
                                sl=plan.stop_loss, tp=plan.take_profit,
                                obstacle=plan.obstacle_tp, open_time=bar_time,
                            )
                            be_sl = None
                            pending = None
                    # Expire stale pendings.
                    if pending and bi - pending["placed_step"] >= self.order_expiry_bars:
                        pending = None

                # Manage open position: SL first, then obstacle, then TP.
                if open_pos:
                    done = self._manage_bar(open_pos, bar, be_sl)
                    if done is not None:
                        exit_price, reason, partial = done
                        if reason == "obstacle_partial":
                            # 80% off at obstacle, runner SL -> entry (Video 11).
                            open_pos.partial_pnl_usd = self._pnl(
                                open_pos.direction, open_pos.lots * 0.8, open_pos.entry, exit_price)
                            open_pos.lots = round(open_pos.lots * 0.2, 2)
                            be_sl = open_pos.entry
                            open_pos.close_reason = "partial_then_runner"
                        else:
                            open_pos.exit_price = exit_price
                            open_pos.close_time = bar_time
                            open_pos.close_reason = reason
                            open_pos.pnl_usd = self._pnl(
                                open_pos.direction, open_pos.lots, open_pos.entry, exit_price)
                            equity += open_pos.partial_pnl_usd + open_pos.pnl_usd
                            if reason in ("sl", "runner_sl"):
                                cooled[(open_pos.model, open_pos.direction,
                                        round(open_pos.entry, 1))] = bi
                            result.trades.append(open_pos)
                            result.equity_curve.append({"time": bar_time, "equity": equity})
                            open_pos = None
                            be_sl = None
                            if equity <= 0:
                                return self._finalize(result, equity)

            # Place next pending from the fresh primary signal (single position,
            # single pending — v1 discipline).
            if open_pos is None and pending is None and primary is not None:
                plan = primary.primary_plan
                dist_pct = abs(plan.buffered_entry - current_price) / max(current_price, 1e-9) * 100.0
                touched = self._already_touched(window[self.step_tf], primary, current_price)
                cool_key = (primary.model_type.value, primary.direction.value,
                            round(plan.buffered_entry, 1))
                in_cooldown = (cool_key in cooled
                               and (horizon - 1) - cooled[cool_key] < self.reentry_cooldown_bars)
                if dist_pct <= self.max_entry_distance_pct and not touched and not in_cooldown:
                    lots = self._lots_for(equity, plan.buffered_entry, plan.stop_loss, plan.risk_percent)
                    pending = {"signal": primary, "plan": plan, "lots": lots,
                               "placed_step": horizon - 1, "expiry_step": horizon - 1 + self.order_expiry_bars}

        # Close any dangling position at the last price (marked expired).
        if open_pos:
            last = step_df.iloc[-1]
            px = float(last["close"])
            open_pos.exit_price = px
            open_pos.close_time = step_df.index[-1]
            open_pos.close_reason = "expired_eod"
            open_pos.pnl_usd = self._pnl(open_pos.direction, open_pos.lots, open_pos.entry, px)
            equity += open_pos.partial_pnl_usd + open_pos.pnl_usd
            result.trades.append(open_pos)
            result.equity_curve.append({"time": step_df.index[-1], "equity": equity})

        return self._finalize(result, equity)

    # ------------------------------------------------------------------
    # Bar management helpers
    # ------------------------------------------------------------------

    def _manage_bar(self, pos: SimTrade, bar: pd.Series, be_sl: Optional[float]):
        """Returns (exit_price, reason, partial) or None if position survives the bar."""
        sl = be_sl if be_sl is not None else pos.sl
        if pos.direction == "BULLISH":
            sl_hit = bar["low"] <= sl
            tp_hit = bar["high"] >= pos.tp
            ob_hit = pos.obstacle is not None and bar["high"] >= pos.obstacle and be_sl is None
            if sl_hit:
                return sl, ("runner_sl" if be_sl is not None else "sl"), 0.0
            if ob_hit:
                return pos.obstacle, "obstacle_partial", 0.0
            if tp_hit:
                return pos.tp, ("runner_tp" if be_sl is not None else "tp"), 0.0
        else:
            sl_hit = bar["high"] >= sl
            tp_hit = bar["low"] <= pos.tp
            ob_hit = pos.obstacle is not None and bar["low"] <= pos.obstacle and be_sl is None
            if sl_hit:
                return sl, ("runner_sl" if be_sl is not None else "sl"), 0.0
            if ob_hit:
                return pos.obstacle, "obstacle_partial", 0.0
            if tp_hit:
                return pos.tp, ("runner_tp" if be_sl is not None else "tp"), 0.0
        return None

    @staticmethod
    def _already_touched(step_window: pd.DataFrame, signal: TradeSignal, current_price: float) -> bool:
        """Skip entries price already ran through (stale zones)."""
        plan = signal.primary_plan
        if signal.direction == BiasDirection.BULLISH:
            return bool((step_window["low"] <= plan.buffered_entry).any()
                        and current_price > plan.buffered_entry)
        return bool((step_window["high"] >= plan.buffered_entry).any()
                    and current_price < plan.buffered_entry)

    def _finalize(self, result: BacktestResult, equity: float) -> BacktestResult:
        wins = [t for t in result.trades if t.partial_pnl_usd + t.pnl_usd > 0]
        losses = [t for t in result.trades if t.partial_pnl_usd + t.pnl_usd <= 0]
        gross_w = sum(t.partial_pnl_usd + t.pnl_usd for t in wins)
        gross_l = abs(sum(t.partial_pnl_usd + t.pnl_usd for t in losses))
        peak, max_dd = equity, 0.0
        # Recompute drawdown from the equity curve.
        eq = self.initial_balance
        peak = eq
        for pt in result.equity_curve:
            peak = max(peak, pt["equity"])
            max_dd = max(max_dd, peak - pt["equity"])
        n = len(result.trades)
        result.stats = {
            "initial_balance": self.initial_balance,
            "final_equity": round(equity, 2),
            "net_pnl": round(equity - self.initial_balance, 2),
            "return_pct": round((equity - self.initial_balance) / self.initial_balance * 100.0, 2),
            "total_trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / n * 100.0, 2) if n else 0.0,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else (float("inf") if gross_w > 0 else 0.0),
            "expectancy_usd": round((equity - self.initial_balance) / n, 2) if n else 0.0,
            "max_drawdown_usd": round(max_dd, 2),
        }
        return result
