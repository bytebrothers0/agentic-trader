"""Shared builders for the ``test_agentic`` suite.

Plain payload dicts in, agent records out — no MT5, no network, no clock of its
own. Kept dependency-free so ``test_subscriptions`` and ``test_watchdog`` can both
build the same shapes without duplicating them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from agentic.feed import parse_candles, parse_payload
from agentic.models import Subscription, SubscriptionKind, SubscriptionState

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #

def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    """2026-10-15 at the given UTC time."""
    return datetime(2026, 10, 15, hour, minute, second, tzinfo=UTC)


def day(d: int, hour: int = 0, minute: int = 0) -> datetime:
    """The given day of October 2026 at the given UTC time."""
    return datetime(2026, 10, d, hour, minute, tzinfo=UTC)


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


class FakeClock:
    """An injected, manually advanced clock (the pure core never reads real time)."""

    def __init__(self, start: Optional[datetime] = None):
        self.now = start or datetime(2026, 10, 17, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> datetime:
        self.now = self.now + timedelta(**kw)
        return self.now

    def set(self, when: datetime) -> datetime:
        self.now = when
        return self.now


# --------------------------------------------------------------------------- #
# Payload builders (the ``/api/indicators`` and ``/api/candles`` shapes)
# --------------------------------------------------------------------------- #

def level(category, *, type="BULLISH", price=100.0, time=None, end_time=None,
          end_kind=None, state=None, **extra):
    """One ``/api/indicators`` level dict."""
    out = {"category": category, "type": type, "price": price}
    if time is not None:
        out["time"] = time
    if end_time is not None:
        out["end_time"] = end_time
    if end_kind is not None:
        out["end_kind"] = end_kind
    if state is not None:
        out["state"] = state
    out.update(extra)
    return out


def snapshot_payload(levels, *, symbol="XAUUSDm", timeframe="M15", price=100.0, atr=0.0):
    """A ``/api/indicators`` payload."""
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": price,
        "atr": atr,
        "levels": list(levels),
    }


def candles_payload(rows, *, symbol="XAUUSDm", timeframe="M15"):
    """A ``/api/candles`` payload.

    ``rows`` are ``(time, open, high, low, close)`` tuples with ``time`` in unix
    seconds.
    """
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": [
            {"time": t, "open": o, "high": h, "low": low, "close": c}
            for (t, o, h, low, c) in rows
        ],
    }


# --------------------------------------------------------------------------- #
# Record builders
# --------------------------------------------------------------------------- #

def snapshot(levels, *, symbol="XAUUSDm", timeframe="M15", price=100.0, atr=0.0):
    """A :class:`FeedSnapshot` from level payload dicts."""
    return parse_payload(
        snapshot_payload(levels, symbol=symbol, timeframe=timeframe, price=price, atr=atr)
    )


def series(rows, *, symbol="XAUUSDm", timeframe="M15"):
    """A :class:`Bars` from ``(time, open, high, low, close)`` rows."""
    return parse_candles(candles_payload(rows, symbol=symbol, timeframe=timeframe))


def sub(condition, params=None, *, kind="watch", one_shot=True, sub_id="sub_1"):
    """A raw :class:`Subscription` (not stored)."""
    return Subscription(
        id=sub_id,
        kind=SubscriptionKind(kind),
        condition=condition,
        params=dict(params or {}),
        one_shot=one_shot,
        state=SubscriptionState.ARMED,
    )
