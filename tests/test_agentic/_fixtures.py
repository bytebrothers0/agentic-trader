"""Shared builders for the ``test_agentic`` suite.

Plain payload dicts in, agent records out — no MT5, no network, no clock of its
own. Kept dependency-free so ``test_subscriptions`` and ``test_watchdog`` can both
build the same shapes without duplicating them.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from agentic.feed import Feed, parse_candles, parse_payload
from agentic.models import Subscription, SubscriptionKind, SubscriptionState
from agentic.renderer import RenderResult

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


# --------------------------------------------------------------------------- #
# Feed stub (phase 4: the agent loop)
# --------------------------------------------------------------------------- #

class FeedStub:
    """A :class:`Feed` whose ``(symbol, timeframe)`` payloads a test can rewrite.

    Records every ``snapshot``/``bars`` fetch so a test can prove the loop and the
    tool registry re-used a ``(symbol, timeframe)`` or not. Levels and candles
    default to empty, which renders a sane empty scene.
    """

    def __init__(self, *, symbol="XAUUSDm", price=100.0, atr=5.0):
        self.symbol = symbol
        self.price = price
        self.atr = atr
        self.levels = {}
        self.candles = {}
        self.snapshot_calls = []
        self.snapshot_families = []
        self.bars_calls = []
        self.bars_requests = []
        #: The ``offset`` each provider call was made with (parallel to the call
        #: lists above), so an offset test can prove the slice was requested.
        self.snapshot_offsets = []
        self.bars_offsets = []

    def set_levels(self, levels, timeframe="M15"):
        self.levels[timeframe] = list(levels)
        return self

    def set_candles(self, rows, timeframe="M15"):
        self.candles[timeframe] = list(rows)
        return self

    def build(self) -> Feed:
        def provider(*, symbol, timeframe, families=None, bars=300, offset=0, **kwargs):
            self.snapshot_calls.append((symbol, timeframe))
            self.snapshot_families.append(list(families or []))
            self.snapshot_offsets.append(int(offset))
            return snapshot_payload(
                self.levels.get(timeframe, []),
                symbol=symbol,
                timeframe=timeframe,
                price=self.price,
                atr=self.atr,
            )

        def candles_provider(*, symbol, timeframe, bars=300, offset=0, **kwargs):
            self.bars_calls.append((symbol, timeframe))
            self.bars_requests.append((symbol, timeframe, int(bars), int(offset)))
            self.bars_offsets.append(int(offset))
            rows = self.candles.get(timeframe, [])
            if offset:
                # A past window skips the newest ``offset`` bars, exactly like the
                # live endpoint's ``offset`` dial.
                rows = rows[: max(0, len(rows) - int(offset))]
            return candles_payload(rows, symbol=symbol, timeframe=timeframe)

        return Feed(provider=provider, candles_provider=candles_provider)


def bars_rows(count=40, *, start=None, price=100.0, step_s=900):
    """``(time, open, high, low, close)`` rows for a deterministic little series."""
    start = ts(day(16, 12)) if start is None else start
    rows = []
    current = float(price)
    for i in range(count):
        o = current
        c = current + (1.0 if i % 2 else -0.5)
        h = max(o, c) + 0.5
        low = min(o, c) - 0.5
        rows.append((start + i * step_s, o, h, low, c))
        current = c
    return rows


class FakeRenderer:
    """A renderer-shaped stub: records calls, writes a marker file, no manifest.

    Deliberately *does not* synthesise a manifest. An earlier version re-implemented
    the tag initials and the ``*`` pinned suffix, which made a "the manifest marks
    the pin" test circular — it asserted the stub, not the real renderer. The real
    :class:`~agentic.renderer.Renderer` is exercised by ``test_renderer`` and by the
    ``test_agent_loop`` tests that need real tags; this stub only proves the loop and
    the registry *call* the renderer, count renders and thread its result. Rendering
    a PNG costs seconds on CI, so the loop's mechanics run here in milliseconds.
    """

    def __init__(self, *, out_dir, clock=None, width=64, height=48):
        self.out_dir = str(out_dir)
        self.clock = clock
        self.width = width
        self.height = height
        self.calls = []

    def render(self, snapshot, bars, *, pins=(), thesis_level_keys=(), out_dir=None,
               panes=(), layout="single", offset=0):
        self.calls.append(
            {
                "snapshot": snapshot,
                "bars": bars,
                "pins": list(pins),
                "thesis_level_keys": list(thesis_level_keys),
                "panes": list(panes),
                "layout": layout,
                "offset": offset,
            }
        )
        target = str(out_dir or self.out_dir)
        os.makedirs(target, exist_ok=True)
        render_id = f"r_{len(self.calls):08d}"
        path = os.path.join(target, f"{render_id}.png")
        with open(path, "wb") as handle:
            handle.write(b"fake-png")
        return RenderResult(
            render_id=render_id,
            image_path=path,
            width=self.width,
            height=self.height,
            manifest={},
        )


# --------------------------------------------------------------------------- #
# Render scene (spec phase 3)
# --------------------------------------------------------------------------- #

def render_scene():
    """A deterministic ``(snapshot, bars, pins, thesis_key)`` scene to render.

    Gold-like prices around 4150 on M15: a live FVG with a box, a BOS, and a CRT
    range. The pin is an H2 FVG — deliberately *not* in the M15 snapshot — so the
    renderer has to merge, dedupe and mark species correctly.
    """
    start = ts(day(16, 12))
    rows = []
    price = 4150.0
    for i in range(40):
        o = price
        c = price + (2.0 if i % 3 else -1.5)
        h = max(o, c) + 1.0
        low = min(o, c) - 1.0
        rows.append((start + i * 900, o, h, low, c))
        price = c

    bars = series(rows, symbol="XAUUSDm", timeframe="M15")
    snap = snapshot(
        [
            level("fvg", type="FVG (BULLISH)", price=4160.0, time=start, end_kind="active",
                  box_top=4162.0, box_bottom=4158.0, desc="FVG bullish 4158-4162"),
            level("bos", type="BOS (BEARISH)", price=4145.0, time=start + 900, end_kind="active"),
            level("crt", type="BEARISH (CLASSIC)", price=4170.0, time=start + 1800,
                  end_kind="active", range_high=4172.0, range_low=4166.0, target=4160.0),
        ],
        symbol="XAUUSDm", timeframe="M15", price=4155.0, atr=5.0,
    )
    pin_snap = snapshot(
        [
            level("fvg", type="FVG (BEARISH)", price=4180.0, time=start, end_kind="active",
                  box_top=4183.0, box_bottom=4178.0, desc="H2 FVG bearish 4178-4183"),
        ],
        symbol="XAUUSDm", timeframe="H2", price=4155.0, atr=12.0,
    )
    pins = [pin_snap.levels[0]]
    return snap, bars, pins, snap.levels[0].level_key
