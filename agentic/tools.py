"""agentic/tools.py — the agent's tool surface (spec phase 4).

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "Tool surface" and
"Perception contract: render + manifest + lookup".

The vocabulary the model acts through: eleven tools and **no order tool**. There
is deliberately nothing here that executes anything — ``propose_trade`` emits a
plan (``mode=propose``), full stop.

The one rule that shapes this module
------------------------------------
``ToolRegistry.execute`` **never raises**. A rejected mutation is reported to the
model as ``ToolResult(ok=False, error=...)`` carrying the store's own reason
(``StoreError``/``CapExceeded``/``ConditionError`` message included). The spec is
explicit: "when a cap is hit … the tool result tells the agent exactly why — so it
can release something deliberately instead of silently losing context." A model
that cannot see *why* it was refused cannot fix its own request.

What counts as a render
-----------------------
A render is one execution of the renderer that writes a PNG and produces a
manifest. The turn's **initial perception render counts as render #1**;
``MAX_RENDERS_PER_TURN`` bounds the total for the turn. The :class:`ToolRegistry`
owns that budget: :meth:`ToolRegistry.initial_render` seeds it, each successful
``render`` tool call spends one, and a further call is refused with
``render_cap`` rather than silently dropped. This is why the count lives here and
not in the loop — there is exactly one home for the cap.

Notes
-----
``add_note`` appends to a **turn-scoped** note buffer. The store has no field for
notes (its root is exactly eleven fields, pinned by ``test_store.ROOT_FIELDS``),
so notes are persisted inside the turn record's ``output["notes"]`` — the turn log
is part of the store, which makes notes durable and lets a later briefing read
them back. Documented deviation, deliberate: a note is memory, and the turn log
*is* the memory document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentic._time import as_aware, seconds_remaining
from agentic.conditions import ConditionError
from agentic.feed import Feed, FeedSnapshot, InsufficientHistory, LevelRecord
from agentic.lookup import level_lookup
from agentic.models import Layout, Serde, Subscription, SubscriptionKind
from agentic.prompts import subscription_summary
from agentic.renderer import Pane, RenderResult, Renderer
from agentic.store import (
    MAX_BARS,
    MAX_OFFSET,
    MAX_RENDERS_PER_TURN,
    MIN_BARS,
    ContextStore,
    StoreError,
)

# --------------------------------------------------------------------------- #
# The surface
# --------------------------------------------------------------------------- #

TOOL_NAMES: Tuple[str, ...] = (
    "set_view",
    "render",
    "level_lookup",
    "add_pin",
    "release_pin",
    "add_watch",
    "cancel_watch",
    "list_subscriptions",
    "set_thesis",
    "add_note",
    "propose_trade",
)

TOOL_DESCRIPTIONS: Dict[str, str] = {
    "set_view": "Change your perception: symbol, timeframe, chart type, families, bars, "
                "offset (re-render a past window), layout/panes (set layout=split with "
                "exactly 2 panes for two stacked timeframes), tags, annotations. Unknown "
                "dials are refused.",
    "render": "Re-render the store's view + pins after a change; returns image_path, "
              "render_id and manifest.",
    "level_lookup": "Exact numbers for a tag you saw, a level_key from a previous turn, a "
                    "whole family, or a price neighbourhood. This is the only source of a "
                    "price you may state.",
    "add_pin": "Hold a level across timeframes. Give a level_key, or a family (+price, "
               "+timeframe) to search for.",
    "release_pin": "Release a pin by subscription_id or level_key.",
    "add_watch": "Defer observation to a time window: arm a condition from the vocabulary "
                 "with an expiry.",
    "cancel_watch": "Cancel a watch by subscription_id.",
    "list_subscriptions": "Every open pin and watch with its state and time remaining.",
    "set_thesis": "Write the durable read: bias, storyline, levels_of_interest, "
                  "invalidation, confidence.",
    "add_note": "Append a note to this turn's durable note buffer.",
    "propose_trade": "Emit a plan (propose-only). Fields mirror AIProposal.",
}

#: The default JSON-Schema object for a tool whose arguments are free-form. Shared
#: with the wire layer (:mod:`agentic.llm`) so the "no parameters" shape is defined
#: exactly once.
DEFAULT_TOOL_PARAMETERS: Dict[str, Any] = {"type": "object", "properties": {}}

#: name -> JSON-Schema object describing the tool's arguments.
TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "set_view": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {"type": "string", "description": "e.g. M15, H2, D1"},
            "chart_type": {"type": "string", "enum": ["candles", "line"]},
            "families": {"type": "array", "items": {"type": "string"}},
            "bars": {"type": "integer", "minimum": MIN_BARS, "maximum": MAX_BARS},
            "offset": {"type": "integer", "minimum": 0, "maximum": MAX_OFFSET},
            "layout": {"type": "string", "enum": ["single", "split"]},
            "panes": {"type": "array", "items": {"type": "string"}},
            "show_tags": {"type": "boolean"},
            "annotations": {"type": "array", "items": {"type": "object"}},
        },
        "additionalProperties": False,
    },
    "render": {"type": "object", "properties": {}, "additionalProperties": False},
    "level_lookup": {
        "type": "object",
        "properties": {
            "tag": {"type": "string", "description": "a tag from the last manifest"},
            "level_key": {"type": "string"},
            "family": {"type": "string"},
            "timeframe": {"type": "string"},
            "near_price": {"type": "number"},
            "radius": {"type": "number"},
        },
        "additionalProperties": False,
    },
    "add_pin": {
        "type": "object",
        "properties": {
            "level_key": {"type": "string"},
            "family": {"type": "string"},
            "price": {"type": "number"},
            "timeframe": {"type": "string"},
            "direction": {"type": "string"},
            "tolerance": {"type": "number"},
            "ttl_hours": {"type": "number"},
            "reason": {"type": "string"},
            "note": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "release_pin": {
        "type": "object",
        "properties": {
            "subscription_id": {"type": "string"},
            "level_key": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "add_watch": {
        "type": "object",
        "properties": {
            "condition": {"type": "string"},
            "params": {"type": "object"},
            "ttl_hours": {"type": "number"},
            "one_shot": {"type": "boolean"},
            "wake_on_expiry": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["condition"],
        "additionalProperties": False,
    },
    "cancel_watch": {
        "type": "object",
        "properties": {"subscription_id": {"type": "string"}},
        "required": ["subscription_id"],
        "additionalProperties": False,
    },
    "list_subscriptions": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "set_thesis": {
        "type": "object",
        "properties": {
            "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral", "none"]},
            "storyline": {"type": "string"},
            "levels_of_interest": {"type": "array", "items": {"type": "string"}},
            "invalidation": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "additionalProperties": False,
    },
    "add_note": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    "propose_trade": {
        "type": "object",
        "properties": {
            "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral", "none"]},
            "setup": {"type": "string"},
            "entry": {"type": "number"},
            "sl": {"type": "number"},
            "tp": {"type": "number"},
            "invalidation": {"type": "string"},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "provenance": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    },
}

#: The pin query keys a flat ``add_pin`` call may carry.
_PIN_QUERY_KEYS = ("level_key", "family", "price", "timeframe", "direction", "tolerance")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

@dataclass
class ToolCall(Serde):
    """One tool invocation requested by the model."""

    name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass
class ToolResult(Serde):
    """The outcome of one tool call. ``ok=False`` always carries an ``error``.

    ``error`` is either the store's own machine-readable ``reason`` (a rejected
    mutation) or an ``internal_error: <Type>: <msg>`` label for a genuine bug, so
    the model can tell "I asked badly" from "the server broke".
    """

    call_id: str = ""
    name: str = ""
    ok: bool = True
    result: Any = None
    error: str = ""


# --------------------------------------------------------------------------- #
# Rendering the store's view + pins
# --------------------------------------------------------------------------- #

def _resolve_pin(snapshot: FeedSnapshot, sub: Subscription) -> Optional[LevelRecord]:
    """Re-resolve a pin's identity against fresh feed output.

    A pin stores a *level identity query*, not a snapshot, so it is resolved
    here: by ``level_key`` first, then by ``family`` (+ ``price``/``tolerance``).
    A level that is no longer produced resolves to ``None`` (nothing to draw) —
    the pin itself still exists and the watchdog owns its ``level_alive`` status.
    """
    params = sub.params or {}
    key = params.get("level_key") or sub.level_key
    if key:
        level = snapshot.by_key(str(key))
        if level is not None:
            return level

    family = params.get("family")
    price = params.get("price")
    if family is None or price is None:
        return None
    candidates = [
        level
        for level in snapshot.family(str(family))
        if params.get("timeframe") is None or level.timeframe == str(params["timeframe"])
    ]
    tolerance = params.get("tolerance")
    if tolerance is not None:
        candidates = [
            level for level in candidates if abs(level.price - float(price)) <= float(tolerance)
        ]
    if not candidates:
        return None
    return min(candidates, key=lambda level: abs(level.price - float(price)))


def _cache_key(timeframe: str, bars: int, offset: int) -> Tuple[str, int, int]:
    """The per-turn snapshot cache key.

    Keyed by ``(timeframe, bars, offset)`` so a changed dial — a new timeframe, a
    different lookback, or a shifted window — can never serve a stale snapshot.
    """
    return (str(timeframe), int(bars), int(offset))


def resolve_pins(
    store: ContextStore,
    feed: Feed,
    snapshot: FeedSnapshot,
    *,
    cache: Optional[Dict[Tuple[str, int, int], FeedSnapshot]] = None,
) -> List[LevelRecord]:
    """Every open pin resolved to a :class:`LevelRecord` for the render.

    A pin from another timeframe is fetched from the feed (once per timeframe at
    the view's ``bars``/``offset``, via ``cache``) and passed to the renderer as a
    pin, which is what makes the 2H level survive the drop to M15.
    """
    view = store.data.view
    symbol = view.symbol or store.data.symbol
    families = list(view.families) or None
    bars_count = int(view.bars)
    offset = int(view.offset or 0)
    cache = cache if cache is not None else {}
    resolved: List[LevelRecord] = []
    for sub in store.open_subscriptions(SubscriptionKind.PIN):
        timeframe = str((sub.params or {}).get("timeframe") or view.timeframe)
        key = _cache_key(timeframe, bars_count, offset)
        if key not in cache:
            cache[key] = feed.snapshot(
                symbol,
                timeframe,
                families=families,
                bars=bars_count,
                offset=offset,
            )
        level = _resolve_pin(cache[key], sub)
        if level is not None:
            resolved.append(level)
    return resolved


def render_current(
    store: ContextStore,
    feed: Feed,
    renderer: Renderer,
    *,
    cache: Optional[Dict[Tuple[str, int, int], FeedSnapshot]] = None,
) -> RenderResult:
    """Render the store's view + pins to an image and its tag manifest.

    Fetches the snapshot and bars for the view's ``(symbol, timeframe)`` at the
    view's ``bars``/``offset``, resolves every open pin to a :class:`LevelRecord`
    (its ``params['timeframe']`` else the view's timeframe) and passes them as
    ``pins``; the thesis's ``levels_of_interest`` are passed as
    ``thesis_level_keys`` so the manifest can flag them. The view's ``families``
    are requested from the feed so the image shows exactly what was asked for.

    In **split** mode (``layout="split"`` with a two-timeframe ``panes``) a
    ``(snapshot, bars)`` pair is fetched for *each* pane timeframe at the same
    ``bars``/``offset`` and handed to the renderer's pane path; pins are resolved
    onto the pane whose timeframe they name (a pin whose timeframe is not a pane
    is resolved against its own timeframe and attached to the primary pane).

    ``cache`` (the registry's per-turn snapshot store) is **seeded** with the view
    snapshot this render fetched and shared with :func:`resolve_pins`, so one
    render costs one view-snapshot fetch, not two, and a pin in the view's
    timeframe re-uses it rather than re-fetching.
    """
    view = store.data.view
    symbol = view.symbol or store.data.symbol
    families = list(view.families) or None
    bars_count = int(view.bars)
    offset = int(view.offset or 0)
    thesis = store.data.thesis.levels_of_interest
    pane_timeframes = [str(tf) for tf in (view.panes or [])]
    if view.layout is Layout.SPLIT and len(pane_timeframes) > 1:
        return _render_split(
            store,
            feed,
            renderer,
            symbol=symbol,
            families=families,
            bars=bars_count,
            offset=offset,
            pane_timeframes=pane_timeframes,
            thesis=thesis,
            cache=cache,
        )

    timeframe = view.timeframe
    snapshot = feed.snapshot(symbol, timeframe, families=families, bars=bars_count, offset=offset)
    bars = feed.bars(symbol, timeframe, bars=bars_count, offset=offset)
    if cache is not None:
        cache[_cache_key(timeframe, bars_count, offset)] = snapshot
    pins = resolve_pins(store, feed, snapshot, cache=cache)
    return renderer.render(
        snapshot,
        bars,
        pins=pins,
        thesis_level_keys=thesis,
        offset=offset,
    )


def _fetch_snapshot(
    feed: Feed,
    cache: Optional[Dict[Tuple[str, int, int], FeedSnapshot]],
    symbol: str,
    timeframe: str,
    families: Optional[List[str]],
    bars: int,
    offset: int,
) -> FeedSnapshot:
    """A snapshot for ``(timeframe, bars, offset)``, cached within the turn."""
    key = _cache_key(timeframe, bars, offset)
    if cache is not None and key in cache:
        return cache[key]
    snapshot = feed.snapshot(symbol, timeframe, families=families, bars=bars, offset=offset)
    if cache is not None:
        cache[key] = snapshot
    return snapshot


def _render_split(
    store: ContextStore,
    feed: Feed,
    renderer: Renderer,
    *,
    symbol: str,
    families: Optional[List[str]],
    bars: int,
    offset: int,
    pane_timeframes: List[str],
    thesis: Any,
    cache: Optional[Dict[Tuple[str, int, int], FeedSnapshot]],
) -> RenderResult:
    """The two-pane perception: one snapshot/bars pair per pane, pins per pane."""
    view = store.data.view
    pane_snapshots = {
        tf: _fetch_snapshot(feed, cache, symbol, tf, families, bars, offset)
        for tf in pane_timeframes
    }
    pane_bars = {
        tf: feed.bars(symbol, tf, bars=bars, offset=offset) for tf in pane_timeframes
    }
    primary_tf = pane_timeframes[0]
    pins_by_tf: Dict[str, List[LevelRecord]] = {tf: [] for tf in pane_timeframes}
    for sub in store.open_subscriptions(SubscriptionKind.PIN):
        pin_tf = str((sub.params or {}).get("timeframe") or view.timeframe)
        target = pin_tf if pin_tf in pins_by_tf else primary_tf
        if pin_tf in pane_snapshots:
            source = pane_snapshots[pin_tf]
        else:
            source = _fetch_snapshot(feed, cache, symbol, pin_tf, families, bars, offset)
        level = _resolve_pin(source, sub)
        if level is not None:
            pins_by_tf[target].append(level)

    pane_objs = [
        Pane(pane_snapshots[tf], pane_bars[tf], pins_by_tf[tf]) for tf in pane_timeframes
    ]
    primary = pane_objs[0]
    return renderer.render(
        primary.snapshot,
        primary.bars,
        pins=list(pins_by_tf[primary_tf]),
        thesis_level_keys=thesis,
        panes=pane_objs,
        layout="split",
        offset=offset,
    )


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #

class ToolRegistry:
    """Execute the agent's tools against one store, for one turn.

    Created per turn (its note buffer, render count and last manifest are
    turn-scoped). ``now`` is the turn's single instant: every handler stamps from
    it, so a subscription's ``starts_at`` can never post-date the turn's
    ``started_at``. ``clock`` remains for a registry built directly in a test; when
    ``now`` is absent the handlers fall back to it. The registry never reads the
    wall clock for anything the store will persist.
    """

    def __init__(
        self,
        store: ContextStore,
        feed: Feed,
        renderer: Renderer,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        now: Optional[datetime] = None,
    ):
        self._store = store
        self._feed = feed
        self._renderer = renderer
        self._clock = clock or _utcnow
        self._now = now

        self._notes: List[Dict[str, Any]] = []
        self._renders = 0
        self._render_refusals = 0
        self._snapshots: Dict[Tuple[str, int, int], FeedSnapshot] = {}
        #: The most recent render (initial or tool), for the loop to show the model.
        self.last_result: Optional[RenderResult] = None

    # ------------------------------------------------------------------ api

    def _now_utc(self) -> datetime:
        """The instant this turn stamps — the injected per-turn ``now`` when set.

        Falls back to the injected ``clock`` only for a registry constructed
        directly (a test), so a loop-built registry has exactly one timestamp.
        """
        instant = self._now if self._now is not None else self._clock()
        return as_aware(instant)

    def schemas(self) -> List[Dict[str, Any]]:
        """The tool definitions handed to the model."""
        return [
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS.get(name, ""),
                "parameters": TOOL_SCHEMAS.get(name, DEFAULT_TOOL_PARAMETERS),
            }
            for name in TOOL_NAMES
        ]

    def execute(self, call: ToolCall) -> ToolResult:
        """Run one tool call. **Never raises** — a failure is an ``ok=False`` result."""
        name = str(call.name)
        if name not in TOOL_SCHEMAS:
            return ToolResult(
                call_id=call.call_id, name=name, ok=False, error=f"unknown_tool: {name!r}"
            )
        try:
            result = self._dispatch(name, dict(call.arguments or {}))
            return ToolResult(call_id=call.call_id, name=name, ok=True, result=result)
        except (StoreError, ConditionError) as exc:
            reason = getattr(exc, "reason", type(exc).__name__)
            return ToolResult(
                call_id=call.call_id, name=name, ok=False, error=f"{reason}: {exc}"
            )
        except InsufficientHistory:
            # A feed window the broker does not hold is the model's request to fix,
            # not a server bug: name it so it can reduce the offset.
            return ToolResult(
                call_id=call.call_id,
                name=name,
                ok=False,
                error="insufficient_history: requested offset exceeds available bars; reduce offset",
            )
        except Exception as exc:  # noqa: BLE001 — the contract is "never raises"
            # A label distinct from a store reason: an internal bug must never be
            # mistaken for the model asking badly.
            return ToolResult(
                call_id=call.call_id,
                name=name,
                ok=False,
                error=f"internal_error: {type(exc).__name__}: {exc}",
            )

    def renders_used(self) -> int:
        """Renders spent this turn, **including the initial perception render**."""
        return self._renders

    def render_refusals(self) -> int:
        """How many ``render`` calls were refused because the cap was reached."""
        return self._render_refusals

    def notes(self) -> List[Dict[str, Any]]:
        """Notes added this turn, oldest first (a copy)."""
        return [dict(note) for note in self._notes]

    def reset_snapshots(self) -> None:
        """Drop every snapshot cached for the turn's old view dials.

        Called when the view changes (``set_view``) and by the loop when it
        degrades a bad offset to the live edge, so a lookup never reads a snapshot
        fetched for a different ``(timeframe, bars, offset)``.
        """
        self._snapshots.clear()

    # ------------------------------------------------------------------ render

    def initial_render(self) -> RenderResult:
        """The turn's first render — it counts as render #1 toward the cap.

        The loop calls this once, before the model sees anything. Keeping it here
        (rather than in the loop) means the cap has exactly one home.
        """
        return self._render()

    def _render(self) -> RenderResult:
        if self._renders >= MAX_RENDERS_PER_TURN:
            self._render_refusals += 1
            raise _RenderCap()
        # ``cache`` is the registry's snapshot store: ``render_current`` seeds it
        # with the view snapshot it already fetched, so the render pays for one
        # fetch and an immediate subsequent lookup re-uses it (no double fetch).
        result = render_current(
            self._store, self._feed, self._renderer, cache=self._snapshots
        )
        self._renders += 1
        self.last_result = result
        return result

    def _snapshot_for_timeframe(self, timeframe: str) -> FeedSnapshot:
        """A snapshot for one timeframe of the current view, cached within the turn.

        The cache key is ``(timeframe, bars, offset)``, matching the render path,
        so a lookup after a ``set_view`` never reads a snapshot fetched for the
        old dials.
        """
        view = self._store.data.view
        symbol = view.symbol or self._store.data.symbol
        bars = int(view.bars)
        offset = int(view.offset or 0)
        tf = str(timeframe)
        key = _cache_key(tf, bars, offset)
        if key not in self._snapshots:
            self._snapshots[key] = self._feed.snapshot(
                symbol,
                tf,
                families=list(view.families) or None,
                bars=bars,
                offset=offset,
            )
        return self._snapshots[key]

    def _snapshot_for_view(self) -> FeedSnapshot:
        """A snapshot for the view's primary timeframe, cached within the turn."""
        return self._snapshot_for_timeframe(self._store.data.view.timeframe)

    # ------------------------------------------------------------------ dispatch

    def _dispatch(self, name: str, args: Dict[str, Any]) -> Any:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:  # pragma: no cover — guarded by the schema check
            raise StoreError("unknown_tool", f"no handler for {name!r}")
        return handler(args)

    # ------------------------------------------------------------------ tools

    def _tool_set_view(self, args: Dict[str, Any]) -> Dict[str, Any]:
        view = self._store.set_view(**args)
        # The view changed, so any snapshot cached for the old dials is stale;
        # the next lookup must re-read the feed.
        self.reset_snapshots()
        return view.to_dict()

    def _tool_render(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = self._render()
        return {
            "image_path": result.image_path,
            "render_id": result.render_id,
            "manifest": result.manifest,
        }

    def _tool_level_lookup(self, args: Dict[str, Any]) -> Dict[str, Any]:
        view = self._store.data.view
        if view.layout is Layout.SPLIT and len(view.panes) > 1:
            # Split mode: search *every* pane, not just the primary, so a
            # bottom-pane level resolves by family / near_price / level_key too.
            snapshots = [self._snapshot_for_timeframe(tf) for tf in view.panes]
        else:
            snapshots = [self._snapshot_for_view()]
        manifest = self.last_result.manifest if self.last_result else {}
        result = level_lookup(
            snapshots[0],
            args,
            tags=manifest.get("tags"),
            thesis_level_keys=self._store.data.thesis.levels_of_interest,
            snapshots=snapshots if len(snapshots) > 1 else None,
            panes=manifest.get("panes"),
        )
        return result.to_dict()

    def _tool_add_pin(self, args: Dict[str, Any]) -> Dict[str, Any]:
        # The flat schema (no nested ``params``): the query keys sit at the top.
        params = {key: args[key] for key in _PIN_QUERY_KEYS if args.get(key) is not None}
        if not params:
            raise StoreError("missing_params", "add_pin needs a level_key or family+price")
        reason = str(args.get("reason", "") or "")
        note = str(args.get("note", "") or "")
        ttl = args.get("ttl_hours")
        sub, created = self._store.add_subscription(
            kind=SubscriptionKind.PIN.value,
            params=params,
            reason=reason,
            note=note,
            ttl_hours=float(ttl) if ttl is not None else None,
            now=self._now_utc(),
        )
        return {"subscription": _sub_dict(sub), "created": created}

    def _tool_release_pin(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sub_id = args.get("subscription_id")
        if not sub_id:
            level_key = args.get("level_key")
            if not level_key:
                raise StoreError("missing_params", "release_pin needs subscription_id or level_key")
            match = next(
                (
                    s
                    for s in self._store.open_subscriptions(SubscriptionKind.PIN)
                    if s.level_key == str(level_key)
                    or (s.params or {}).get("level_key") == str(level_key)
                ),
                None,
            )
            if match is None:
                raise StoreError("not_found", f"no open pin for level_key {level_key!r}")
            sub_id = match.id
        released = self._store.release_subscription(str(sub_id))
        return {"subscription": _sub_dict(released)}

    def _tool_add_watch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        condition = args.get("condition")
        if not condition:
            raise StoreError("missing_params", "add_watch needs a condition")
        ttl = args.get("ttl_hours")
        sub, created = self._store.add_subscription(
            kind=SubscriptionKind.WATCH.value,
            condition=str(condition),
            params=dict(args.get("params") or {}),
            ttl_hours=float(ttl) if ttl is not None else None,
            one_shot=bool(args.get("one_shot", True)),
            wake_on_expiry=bool(args.get("wake_on_expiry", False)),
            reason=str(args.get("reason", "") or ""),
            now=self._now_utc(),
        )
        return {"subscription": _sub_dict(sub), "created": created}

    def _tool_cancel_watch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sub_id = args.get("subscription_id")
        if not sub_id:
            raise StoreError("missing_params", "cancel_watch needs a subscription_id")
        released = self._store.release_subscription(str(sub_id))
        return {"subscription": _sub_dict(released)}

    def _tool_list_subscriptions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now_utc()
        subs = [
            _sub_dict(sub, now=now)
            for sub in self._store.open_subscriptions()
        ]
        return {"count": len(subs), "subscriptions": subs}

    def _tool_set_thesis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        thesis = self._store.set_thesis(**args, now=self._now_utc())
        return thesis.to_dict()

    def _tool_add_note(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text = args.get("text")
        if text is None or str(text).strip() == "":
            raise StoreError("missing_params", "add_note needs non-empty text")
        note = {"at": self._now_utc().isoformat(), "text": str(text)}
        self._notes.append(note)
        return note

    def _tool_propose_trade(self, args: Dict[str, Any]) -> Dict[str, Any]:
        proposal = self._store.add_proposal(**args, now=self._now_utc())
        return proposal.to_dict()


# --------------------------------------------------------------------------- #
# Errors + helpers
# --------------------------------------------------------------------------- #

class _RenderCap(StoreError):
    """The per-turn render cap was reached (internal; becomes ``render_cap``)."""

    def __init__(self, message: str = ""):
        super().__init__("render_cap", message or f"{MAX_RENDERS_PER_TURN} renders per turn")


def _sub_dict(sub: Subscription, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """A JSON-safe subscription view, with a countdown and a one-line summary."""
    data = sub.to_dict()
    data["summary"] = subscription_summary(sub)
    remaining = seconds_remaining(sub.expires_at, now) if now is not None else None
    if remaining is not None:
        data["seconds_remaining"] = remaining
    return data
