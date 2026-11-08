"""
mt5_loader.py — MetaTrader 5 Multi-Timeframe Data Ingestion Engine

Features:
  - Smart symbol name resolution (e.g., 'XAUUSD' matches 'XAUUSDm', 'XAUUSD.raw', 'GOLD', etc.)
  - Multi-timeframe OHLCV bar fetching (M1, W1, D1, H4, H1)
  - Converts timestamps to Unix timestamps for TradingView chart compatibility
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional
import logging
import pandas as pd
import MetaTrader5 as mt5

from config.settings import (
    MT5_PATH,
    MT5_TIMEOUT,
    TIMEFRAME_MAP,
    CANDLE_FETCH_COUNT,
)

logger = logging.getLogger("MSNR_MT5Loader")
_mt5_lock = threading.Lock()

#: A fresh ``copy_rates`` can briefly return nothing (or a short window) while
#: the terminal is still downloading that timeframe's series into memory — the
#: very first D1/W1 request after boot is the classic case. Before declaring
#: ``InsufficientHistory``, give the terminal this much slack.
FEED_RETRY_ATTEMPTS = 3
FEED_RETRY_WAIT_S = 0.4


class InsufficientHistory(ValueError):
    """The feed does not hold the window that was requested.

    Raised when an **explicit** ``count`` was asked for (an offset past the
    available history, or a broker that holds fewer bars than requested) and the
    feed could not fill it. It is a ``ValueError`` subclass so the pure layers can
    translate it without importing MT5, and it is distinct from a genuine feed
    failure (``RuntimeError``) so a caller can tell "reduce your offset" from
    "the server broke".
    """


class MT5DataLoader:
    """
    Connects to MT5 and fetches multi-timeframe OHLCV data.
    """

    def __init__(self, symbol: str = "XAUUSD"):
        self.requested_symbol = symbol
        self.resolved_symbol = symbol
        self._connected = False

    def connect(self) -> bool:
        """Initialize connection to MetaTrader 5 terminal."""
        with _mt5_lock:
            if self._connected:
                return True

            init_params = {"timeout": 30_000}
            if MT5_PATH:
                init_params["path"] = MT5_PATH

            if not mt5.initialize(**init_params):
                logger.error(f"MT5 initialization failed: {mt5.last_error()}")
                return False

            # Resolve broker symbol name
            self.resolved_symbol = self._resolve_symbol(self.requested_symbol)
            selected = mt5.symbol_select(self.resolved_symbol, True)
            if not selected:
                logger.warning(f"Failed to select symbol '{self.resolved_symbol}'.")
                return False

            self._connected = True
            logger.info(f"Connected to MT5 successfully. Active Symbol: {self.resolved_symbol}")
            return True

    def _reattach(self) -> bool:
        """Re-``initialize`` after the process's IPC pipe died (``-10004``).

        MT5's Python bindings hold **one** connection per *process*: a stray
        ``shutdown()`` — anywhere in the server — drops it for every user at
        once, and ``copy_rates`` then fails with ``No IPC connection`` until
        someone attaches again. This heals in place, so a broken pipe on the
        candles feed costs one retry round, not a restart of the server.
        """
        init_params = {"timeout": 30_000}
        if MT5_PATH:
            init_params["path"] = MT5_PATH
        with _mt5_lock:
            if mt5.initialize(**init_params):
                self._connected = True
                mt5.symbol_select(self.resolved_symbol, True)
                return True
            logger.error(f"MT5 reattach failed: {mt5.last_error()}")
            return False

    def _resolve_symbol(self, symbol: str) -> str:
        """Find the broker's exact symbol name for a given request."""
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return symbol

        names = [s.name for s in all_symbols]
        if symbol in names:
            return symbol

        # Try case-insensitive and suffix match
        target = symbol.upper()
        candidates = [n for n in names if target in n.upper()]
        if candidates:
            # Prefer shortest match (e.g. XAUUSDm over XAUUSD247m)
            candidates.sort(key=len)
            logger.info(f"Resolved '{symbol}' -> '{candidates[0]}'")
            return candidates[0]

        # Try Gold alias
        if "XAU" in target or "GOLD" in target:
            gold_matches = [n for n in names if "XAU" in n.upper() or "GOLD" in n.upper()]
            if gold_matches:
                gold_matches.sort(key=len)
                return gold_matches[0]

        return symbol

    def get_available_symbols(self) -> List[str]:
        """Return list of trading symbols available in MT5."""
        if not self._connected and not self.connect():
            return [self.requested_symbol]
        all_syms = mt5.symbols_get()
        if not all_syms:
            return [self.requested_symbol]
        return [s.name for s in all_syms]

    def disconnect(self):
        """Shutdown MT5 connection."""
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 connection closed.")

    def fetch_timeframe(self, tf_key: str, count: Optional[int] = None, start: int = 0) -> pd.DataFrame:
        """
        Fetch OHLCV dataframe for a specific timeframe.

        ``start`` is MT5's ``start_pos``: the number of bars to skip back from the
        newest bar before the window begins. ``start=0`` (the default) is the
        latest window, so every existing caller is unchanged; ``start=n`` returns
        the ``count`` bars ending ``n`` bars before the newest one, in ascending
        order — the same "offset" semantic the agent's ``view.offset`` uses.
        """
        if not self._connected:
            if not self.connect():
                raise ConnectionError("Unable to connect to MT5 terminal.")

        start = int(start or 0)
        mt5_tf = TIMEFRAME_MAP.get(tf_key.upper())
        if mt5_tf is None:
            raise ValueError(f"Unknown timeframe '{tf_key}'. Valid options: {list(TIMEFRAME_MAP.keys())}")
        if isinstance(mt5_tf, str):
            # Synthesized timeframe (e.g. M45 = 3xM15, no native MT5 TF).
            return self._resample(tf_key.upper(), count, start)

        bars_count = count or CANDLE_FETCH_COUNT.get(tf_key.upper(), 500)
        rates: Optional[list] = None
        for attempt in range(max(1, FEED_RETRY_ATTEMPTS)):
            with _mt5_lock:
                rates = mt5.copy_rates_from_pos(self.resolved_symbol, mt5_tf, start, bars_count)
                err = mt5.last_error()
            got = 0 if rates is None else len(rates)
            if got >= bars_count:
                break
            if rates is None and err and err[0] == -10004:
                # The process's IPC attach to the terminal died (something
                # called ``mt5.shutdown()`` in-process, or the terminal
                # restarted). Re-attach and copy again on the next attempt —
                # this is healable, not "insufficient history".
                logger.warning(
                    f"MT5 IPC dropped ({err}); re-attaching for '{self.resolved_symbol}'"
                )
                if self._reattach():
                    continue
            if attempt + 1 < max(1, FEED_RETRY_ATTEMPTS):
                # Terminal may still be syncing this timeframe's history; a short
                # wait beats reporting "insufficient history" on a series that is
                # merely mid-download.
                time.sleep(FEED_RETRY_WAIT_S)

        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            if count is not None:
                # An explicit window that yields nothing means the offset (or the
                # request) is past the feed's history — a fixable client error.
                raise InsufficientHistory(
                    f"requested {count} {tf_key.upper()} bar(s) at start={start}; "
                    f"the feed returned none (terminal: {err})"
                )
            raise RuntimeError(f"Failed to copy rates for {self.resolved_symbol} [{tf_key}]: {err}")

        if count is not None and len(rates) < int(count):
            # ``copy_rates_from_pos`` silently returns a short window when the
            # request reaches past the oldest bar (or the terminal has not
            # finished downloading); surface it instead of letting the caller
            # reason over the wrong window.
            raise InsufficientHistory(
                f"requested {count} {tf_key.upper()} bar(s) at start={start}; "
                f"only {len(rates)} available"
            )

        df = pd.DataFrame(rates)
        # MT5 rates are already timestamped in seconds, but we still normalize
        # ordering and dedupe timestamps so the chart always receives a clean
        # ascending series.
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.sort_values("time").drop_duplicates(subset=["time"], keep="last")
        # Keep unix timestamp in 'time' column for TradingView chart compatibility.
        df.set_index("datetime", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df[["time", "open", "high", "low", "close", "volume"]]

    def _resample(self, tf_key: str, count: Optional[int] = None, start: int = 0) -> pd.DataFrame:
        """Build a non-native timeframe from M15 (currently only M45).

        ``start`` shifts the synthesized window back by that many M45 bars: enough
        M15 is fetched to cover ``start + count`` M45 bars, the series is
        resampled, then the newest ``start`` M45 bars are sliced off. If the feed
        does not hold that much history the window cannot be honoured, so this
        raises rather than silently returning the wrong window.
        """
        if tf_key != "M45":
            raise ValueError(f"No synthesis rule for '{tf_key}'.")
        per = 3  # 3 x M15 = M45
        want = count or CANDLE_FETCH_COUNT.get("M45", 500)
        start = int(start or 0)
        m15 = self.fetch_timeframe("M15", count=(want + start) * per + per)
        m15 = m15.set_index(pd.to_datetime(m15["time"], unit="s", utc=True))
        agg = {"open": "first", "high": "max", "low": "min",
               "close": "last", "volume": "sum"}
        # Midnight-anchored 45-min grid (:00/:45/1:30/2:15/3:00...),
        # same grid TradingView uses. Bin label = bar OPEN time.
        bars = m15.resample("45min", origin="start_day").agg(agg).dropna()
        if start:
            if len(bars) <= start:
                raise InsufficientHistory(
                    f"not enough M15 history to synthesize {tf_key} at start={start}: "
                    f"only {len(bars)} M45 bar(s) available"
                )
            bars = bars.iloc[: len(bars) - start]
        if count is not None and len(bars) < want:
            # An explicit window that cannot be filled (at start=0 *or* after the
            # offset) is a fixable refusal, not a silent short series.
            raise InsufficientHistory(
                f"not enough M15 history to synthesize {want} {tf_key} bar(s) at "
                f"start={start}: only {len(bars)} available after the offset"
            )
        bars = bars.tail(want)
        out = pd.DataFrame({
            "time": (bars.index.astype("int64") // 10**9).astype(int),
            "open": bars["open"].values,
            "high": bars["high"].values,
            "low": bars["low"].values,
            "close": bars["close"].values,
            "volume": bars["volume"].values,
        }, index=bars.index)
        return out[["time", "open", "high", "low", "close", "volume"]]

    def fetch_all_timeframes(self) -> Dict[str, pd.DataFrame]:
        """Fetch all timeframes simultaneously (MN1/W1/D1/H4/H1 + M15 for TTFL)."""
        result = {}
        for tf in ["MN1", "W1", "D1", "H4", "H1", "M15"]:
            try:
                df = self.fetch_timeframe(tf)
            except Exception:
                # M15 is optional on some servers; skip if unavailable.
                # EntryEngine falls back to H1 for TTFL refinement.
                if tf == "M15":
                    continue
                raise
            result[tf] = df
            if tf == "MN1":
                result["MN"] = df  # Monthly alias (MN1 canonical)
        return result
