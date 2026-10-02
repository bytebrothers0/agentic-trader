"""
mt5_loader.py — MetaTrader 5 Multi-Timeframe Data Ingestion Engine

Features:
  - Smart symbol name resolution (e.g., 'XAUUSD' matches 'XAUUSDm', 'XAUUSD.raw', 'GOLD', etc.)
  - Multi-timeframe OHLCV bar fetching (M1, W1, D1, H4, H1)
  - Converts timestamps to Unix timestamps for TradingView chart compatibility
"""

from __future__ import annotations

import threading
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

    def fetch_timeframe(self, tf_key: str, count: Optional[int] = None) -> pd.DataFrame:
        """
        Fetch OHLCV dataframe for a specific timeframe.
        """
        if not self._connected:
            if not self.connect():
                raise ConnectionError("Unable to connect to MT5 terminal.")

        mt5_tf = TIMEFRAME_MAP.get(tf_key.upper())
        if mt5_tf is None:
            raise ValueError(f"Unknown timeframe '{tf_key}'. Valid options: {list(TIMEFRAME_MAP.keys())}")

        bars_count = count or CANDLE_FETCH_COUNT.get(tf_key.upper(), 500)
        with _mt5_lock:
            rates = mt5.copy_rates_from_pos(self.resolved_symbol, mt5_tf, 0, bars_count)

        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            raise RuntimeError(f"Failed to copy rates for {self.resolved_symbol} [{tf_key}]: {err}")

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
