"""
backtest/historical.py — load MT5 history once; freeze it at an instant.

The agent's perception path is ``Feed`` -> ``server.get_indicators`` /
``server.get_candles`` -> ``MT5DataLoader``. To replay a past instant we do not
touch any of that: we swap the **loader** for one that serves pre-loaded bars
truncated at ``T``, and everything above it computes exactly as it would have
live.

Why the loader is the right seam
--------------------------------
``server.get_loader(symbol)`` is the single place the endpoints acquire their
data. Patch it and ``get_indicators`` keeps running the real detectors, on the
real payload shape, with the real settings — there is no second implementation
of "what the chart looked like" to drift from the first.

No look-ahead
-------------
``FrozenLoader.fetch_timeframe`` only ever returns bars that had **closed** by
``T`` (``bar_open + nominal_duration <= T``). So a partially-formed higher-
timeframe bar can never be read whose close was still in the future, and the
newest bar of every pane is a settled bar. That is the whole correctness claim of
the harness, and ``tests/test_backtest.py`` pins it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

#: Nominal bar length in seconds, used to decide whether a bar had closed by ``T``
#: and to convert a decision bar into its close instant. Nominal on purpose: a
#: D1 bar over a weekend is longer in wall-clock than 24h, and using the nominal
#: length is the *conservative* choice (it can only make a bar look un-closed, so
#: it can never introduce look-ahead).
TF_SECONDS: Dict[str, int] = {
    "M1": 60,
    "M3": 180,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "M45": 2700,
    "H1": 3600,
    "H2": 7200,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
    "MN1": 2592000,
    "MN": 2592000,
}

#: Timeframes to preload. ``M45`` is deliberately absent: it has no native MT5
#: bars and is synthesized by the loader from M15, which the frozen loader serves
#: from its own frozen M15 (so a M45 replay is point-in-time too).
DEFAULT_TIMEFRAMES: Tuple[str, ...] = (
    "MN1", "W1", "D1", "H4", "H2", "H1", "M30", "M15", "M5",
)

#: How deep to load. MT5 holds ~125k M15 bars (~3.5 years) and ~32k H1; asking for
#: more than exists is harmless (it returns what it has).
DEFAULT_MAX_BARS = 200_000


def tf_seconds(timeframe: str) -> int:
    """Nominal seconds for a timeframe; ``M45`` is covered, unknown is an error."""
    tf = str(timeframe).upper()
    if tf not in TF_SECONDS:
        raise ValueError(f"no nominal duration for timeframe {timeframe!r}")
    return TF_SECONDS[tf]


def _format_rates(rates: Any) -> pd.DataFrame:
    """Format MT5 ``copy_rates_from_pos`` output the way ``MT5DataLoader`` does."""
    df = pd.DataFrame(rates)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.sort_values("time").drop_duplicates(subset=["time"], keep="last")
    df.set_index("datetime", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


def connect_mt5(symbol: str = "XAUUSDm", *, mt5_path: Optional[str] = None):
    """Initialise MT5 (once) and resolve ``symbol`` to the broker's name.

    Returns ``(mt5_module, resolved_symbol)``. Raises ``RuntimeError`` with MT5's
    own error when the terminal refuses to initialise, rather than failing later
    with a confusing empty frame.
    """
    import MetaTrader5 as mt5

    from config.settings import MT5_PATH
    from data.mt5_loader import MT5DataLoader

    loader = MT5DataLoader(symbol)
    if not loader.connect():
        raise RuntimeError(
            f"MT5 initialise/select failed for {symbol!r}: {mt5.last_error()}"
        )
    return mt5, loader.resolved_symbol


def load_history(
    symbol: str = "XAUUSDm",
    *,
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
    max_bars: int = DEFAULT_MAX_BARS,
    mt5_path: Optional[str] = None,
) -> Tuple[str, Dict[str, pd.DataFrame]]:
    """Fetch a deep history for every native timeframe, ascending, in loader shape.

    Returns ``(resolved_symbol, {timeframe: frame})``. A timeframe MT5 holds no
    bars for is skipped (mirrors the live feed, which 500s on an empty window).
    """
    import MetaTrader5 as mt5

    from config.settings import TIMEFRAME_MAP

    mt5, resolved = connect_mt5(symbol, mt5_path=mt5_path)
    frames: Dict[str, pd.DataFrame] = {}
    for tf in timeframes:
        key = str(tf).upper()
        native = TIMEFRAME_MAP.get(key)
        if isinstance(native, str):
            continue  # synthesized at read time from M15
        rates = mt5.copy_rates_from_pos(resolved, native, 0, int(max_bars))
        if rates is None or len(rates) == 0:
            continue
        frames[key] = _format_rates(rates)
    if not frames:
        raise RuntimeError(f"MT5 returned no bars for any of {list(timeframes)} on {resolved}")
    return resolved, frames


def save_cache(path: str, symbol: str, frames: Mapping[str, pd.DataFrame]) -> None:
    """Persist a loaded history so a re-run needs no MT5 (and no terminal)."""
    payload = {"symbol": symbol, "frames": {tf: df for tf, df in frames.items()}}
    pd.to_pickle(payload, path)


def load_cache(path: str) -> Tuple[str, Dict[str, pd.DataFrame]]:
    """Read a cache written by :func:`save_cache`."""
    payload = pd.read_pickle(path)
    return str(payload["symbol"]), dict(payload["frames"])


def load_or_fetch(
    symbol: str,
    *,
    cache: Optional[str] = None,
    refresh: bool = False,
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
    max_bars: int = DEFAULT_MAX_BARS,
) -> Tuple[str, Dict[str, pd.DataFrame]]:
    """Load from ``cache`` when it exists (unless ``refresh``), else fetch + cache."""
    if cache and not refresh:
        try:
            cached_symbol, frames = load_cache(cache)
            if frames:
                return cached_symbol, frames
        except (OSError, EOFError, KeyError, ValueError):
            pass  # unreadable/absent cache: fall through to a live fetch
    resolved, frames = load_history(
        symbol, timeframes=timeframes, max_bars=max_bars
    )
    if cache:
        try:
            save_cache(cache, resolved, frames)
        except OSError:
            pass  # a cache we cannot write must not fail the run
    return resolved, frames


# --------------------------------------------------------------------------- #
# The frozen loader
# --------------------------------------------------------------------------- #

class FrozenLoader:
    """An ``MT5DataLoader``-shaped facade over a pre-loaded, frozen history.

    Only ``fetch_timeframe`` is needed by the two endpoints and by the inherited
    ``_resample`` (which synthesizes M45 from ``self.fetch_timeframe("M15")``), so
    this does not subclass — it duck-types the four attributes they touch
    (``resolved_symbol``, ``requested_symbol``, ``fetch_timeframe``,
    ``_resample``).

    ``fetch_timeframe(tf, count, start)`` returns the ``count`` bars ending ``start``
    bars before ``as_of`` — the same "bars back from the newest" semantic MT5's
    ``copy_rates_from_pos`` uses with ``start_pos``, so the agent's ``view.offset``
    behaves exactly as it does live.
    """

    def __init__(
        self,
        symbol: str,
        frames: Mapping[str, pd.DataFrame],
        as_of: datetime,
    ):
        self.requested_symbol = symbol
        self.resolved_symbol = symbol
        self.as_of = as_of
        self._full = {str(tf).upper(): df for tf, df in frames.items()}
        self._closed = {
            tf: _closed_by(df, tf, as_of) for tf, df in self._full.items() if tf in TF_SECONDS
        }

    # the two loader attributes the endpoints read
    @property
    def closed(self) -> Dict[str, pd.DataFrame]:
        """Per-timeframe frames truncated at ``as_of`` (read-only convenience)."""
        return dict(self._closed)

    def available(self, timeframe: str) -> int:
        """How many settled bars this loader holds for ``timeframe``."""
        tf = str(timeframe).upper()
        if tf == "M45":
            return len(self._closed.get("M15", ())) // 3
        return len(self._closed.get(tf, ()))

    def fetch_timeframe(
        self, tf_key: str, count: Optional[int] = None, start: int = 0
    ) -> pd.DataFrame:
        from config.settings import CANDLE_FETCH_COUNT, TIMEFRAME_MAP
        from data.mt5_loader import InsufficientHistory

        tf = str(tf_key).upper()
        native = TIMEFRAME_MAP.get(tf)
        if isinstance(native, str):
            # Synthesized (M45): the inherited rule reads M15 from *this* loader,
            # so the synthetic series is point-in-time as well.
            return _resample(self, tf, count, start)

        series = self._closed.get(tf)
        if series is None:
            raise InsufficientHistory(
                f"backtest did not preload {tf}; preloaded: {sorted(self._closed)}"
            )
        want = int(count) if count is not None else int(CANDLE_FETCH_COUNT.get(tf, 500))
        start = int(start or 0)
        end = len(series) - start
        if want <= 0 or start < 0 or end < want:
            raise InsufficientHistory(
                f"requested {want} {tf} bar(s) at start={start}; "
                f"only {max(0, end)} settled by {self.as_of.isoformat()}"
            )
        return series.iloc[end - want : end].copy()


def _closed_by(df: pd.DataFrame, timeframe: str, as_of: datetime) -> pd.DataFrame:
    """The bars that had **closed** at ``as_of`` (no look-ahead).

    A bar is settled when ``bar_open + nominal_duration <= as_of``. The index is
    assumed ascending (the loader guarantees it), so this is a binary search.
    """
    if df is None or len(df) == 0:
        return df
    cutoff = _as_aware(as_of) - pd.Timedelta(seconds=tf_seconds(timeframe))
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise TypeError("history frame index must be a DatetimeIndex")
    pos = int(idx.searchsorted(cutoff, side="right"))
    return df.iloc[:pos]


def _as_aware(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts


def _resample(loader: FrozenLoader, tf_key: str, count: Optional[int], start: int) -> pd.DataFrame:
    """Synthesize a non-native timeframe from the frozen M15.

    A faithful copy of ``MT5DataLoader._resample``'s arithmetic (same 45-minute
    ``start_day`` grid, same "slice ``start`` bars off the newest, then ``tail``"),
    reading M15 from the frozen loader instead of the terminal.
    """
    from config.settings import CANDLE_FETCH_COUNT
    from data.mt5_loader import InsufficientHistory

    if tf_key != "M45":
        raise ValueError(f"No synthesis rule for '{tf_key}'.")
    per = 3  # 3 x M15 = M45
    want = count or CANDLE_FETCH_COUNT.get("M45", 500)
    start = int(start or 0)
    m15 = loader.fetch_timeframe("M15", count=(want + start) * per + per)
    m15 = m15.set_index(pd.to_datetime(m15["time"], unit="s", utc=True))
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    bars = m15.resample("45min", origin="start_day").agg(agg).dropna()
    # A bucket whose window extends past the freeze holds a *partial* bar, whose
    # notional close is still in the future. Dropping it is the M45 half of the
    # same no-look-ahead rule ``_closed_by`` enforces for native timeframes.
    horizon = _as_aware(loader.as_of)
    bars = bars[bars.index + pd.Timedelta(seconds=tf_seconds(tf_key)) <= horizon]
    if start:
        if len(bars) <= start:
            raise InsufficientHistory(
                f"not enough M15 history to synthesize {tf_key} at start={start}: "
                f"only {len(bars)} M45 bar(s) available"
            )
        bars = bars.iloc[: len(bars) - start]
    if count is not None and len(bars) < want:
        raise InsufficientHistory(
            f"not enough M15 history to synthesize {want} {tf_key} bar(s) at "
            f"start={start}: only {len(bars)} available after the offset"
        )
    bars = bars.tail(want)
    out = pd.DataFrame(
        {
            "time": (bars.index.astype("int64") // 10**9).astype(int),
            "open": bars["open"].values,
            "high": bars["high"].values,
            "low": bars["low"].values,
            "close": bars["close"].values,
            "volume": bars["volume"].values,
        },
        index=bars.index,
    )
    return out[["time", "open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------- #
# Installing it into the live endpoints
# --------------------------------------------------------------------------- #

@contextmanager
def frozen_server(loader: FrozenLoader) -> Iterator[Any]:
    """Serve every endpoint from ``loader`` for the duration of the block.

    Patches ``server.get_loader`` — the one function both endpoints use to acquire
    data — and restores it on exit, so a replay is fully contained in the ``with``.
    ``server`` (and so MT5, FastAPI) is imported lazily here.
    """
    import server as server_module

    original = server_module.get_loader
    server_module.get_loader = lambda symbol: loader  # every symbol -> the frozen one
    try:
        yield server_module
    finally:
        server_module.get_loader = original


def build_feed(loader: FrozenLoader):
    """A :class:`agentic.feed.Feed` bound to a frozen loader, inside a ``with``."""
    from agentic.feed import Feed

    # Feed's default providers import server.get_indicators/get_candles lazily at
    # call time, so patching get_loader before the first call is enough.
    return Feed()


@dataclass
class Instant:
    """A frozen point in time, plus the frames it was built from."""

    symbol: str
    as_of: datetime
    frames: Dict[str, pd.DataFrame]

    def loader(self) -> FrozenLoader:
        return FrozenLoader(self.symbol, self.frames, self.as_of)

    def forward(self, timeframe: str, after: pd.Timestamp) -> pd.DataFrame:
        """The **full** history strictly after ``after`` — for scoring, not perception."""
        df = self.frames.get(str(timeframe).upper())
        if df is None:
            return pd.DataFrame()
        return df[df.index > _as_aware(after)]
