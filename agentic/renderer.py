"""agentic/renderer.py — the server-side PNG render + its manifest (spec phase 3).

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "Perception contract:
render + manifest + lookup".

There is no browser in the loop. The view is rendered to a PNG on the server in
the dashboard's own visual language (``web/app.js``'s dark theme: bounded
per-family rays, quiet zone boxes, right-side price scale) — the agent sees what
the operator would see, like a screenshot of the dashboard. Every drawn level
carries a short **tag** (family initial + ordinal within this render, ``F1`` /
``F1*`` when pinned), and the manifest is the machine-readable map from tag back
to the exact ``level_key``.

One projection, two faces
-------------------------
The numbers in the manifest are not computed here: :func:`agentic.lookup.
level_view` is the canonical, JSON-safe projection of a level, and
:class:`TagEntry` is built from it. That keeps the manifest and the numeric
lookup from ever drifting apart.

Determinism is a hard requirement: same store + same feed -> byte-identical PNG,
so turns are replayable and the image can be hashed. That means no randomness, no
wall-clock in the drawing (``rendered_at`` lives in the manifest only), a
canonically ordered manifest, and no PNG metadata left behind — matplotlib writes
a ``Software`` tag and PIL can add one, so the bytes are normalised through a
metadata-free PIL re-save before they are hashed or written. ``render_id`` is
derived from the hash, so identical state yields the identical filename.

Import rule
-----------
``matplotlib`` and ``PIL`` are imported **inside functions** (memoised on first
use by :func:`_vision_stack`), never at module level, so ``import agentic`` stays
cheap and ``Renderer``/``TagEntry``/``RenderResult`` can be exported from the
package. ``tests/test_agentic/test_standalone.py`` asserts this.
"""
from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from agentic._time import as_aware
from agentic.feed import Bars, FeedSnapshot, LevelRecord
from agentic.lookup import level_view
from agentic.models import LevelStatus, Serde

# --------------------------------------------------------------------------- #
# Layout constants
# --------------------------------------------------------------------------- #

DEFAULT_RENDER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "renders")

#: family -> tag initial. The ``e.g.`` list in the spec, completed for every
#: family the indicator suite can emit. Unknown families get the first free
#: letter, deterministically (see :func:`Renderer._family_initials`).
FAMILY_INITIALS: Dict[str, str] = {
    "crt": "C",
    "ts": "T",
    "bos": "B",
    "fvg": "F",
    "ifvg": "V",
    "ob": "O",
    "liquidity": "L",
    "sr": "S",
    "idm": "I",
    "qm": "Q",
    "trendline": "R",
    "ocl": "K",
    "apex": "X",
}

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Palette matched to the dashboard (``web/app.js`` dark theme) so the agent's
# PNG reads like a screenshot of it: same background, same green/red candles,
# same per-family ink. Saturated on a dark ground, which is what the vision
# stack tokenises reliably.
_BG = "#121418"
_INK = "#9aa5b5"
_GRID = "#1e222b"
#: Candles as the dashboard paints them: solid teal bodies for up, salmon red
#: for down (the look in the operator's screenshot, which the web theme's
#: ``#089981``/``#f23645`` renders the same way at this size).
_UP = "#26a69a"
_DOWN = "#ef5350"
_PINNED = "#e07600"
#: The current price is a dotted hairline with a red chip on the scale — the
#: dashboard's TradingView pose.
_PRICE = "#f23645"
#: Broken levels are history — the exact gray the dashboard fades them to.
_BROKEN = "#5a6b7a"
#: Swept/taken/distributed levels keep their family colour at the dashboard's
#: fade — history, present but no longer a decision.
_HISTORY_ALPHA = 0.35
#: The zone fill's quietness: 8% exactly like the dashboard's rgba fills.
_ZONE_FILL_ALPHA = 0.08

#: Families drawn as zones (edges + a quiet fill) rather than a single ray —
#: the dashboard's ``isZoneLevel`` set. Every other family's band is *information*
#: (y-range), never a painted slab: full-width band fills stacked across 300 bars
#: is what used to flood the chart solid blue.
_ZONE_FAMILIES = frozenset({"fvg", "ifvg", "ob"})

#: Per-family ray budget, matching the dashboard's ``MAX_RAYS_PER_CATEGORY``:
#: newest rays win, quieter families can never be starved by a busy one.
MAX_RAYS_PER_FAMILY = 80

#: A still-active level's open span, in bars (the dashboard's ``+8``).
_RAY_BARS = 8

_CANDLE_WIDTH = 0.6
_WICK_LINEWIDTH = 1.1
#: Every level is a 1px dotted hairline — the dashboard's ray look. Colour and
#: fade carry the family/status; weight is uniform by design.
_LEVEL_LINEWIDTH = 0.9
_LEVEL_STYLE = (0, (1, 2))

#: Type sizes are dashboard-sized: tags are *small plain text* next to their
#: dotted line (bold 12pt tags in bubble boxes turned the dense right cluster
#: into a wall of chips), and the header chip replaces a big title.
_TAG_FONTSIZE = 8
_HEADER_FONTSIZE = 9
_TICK_FONTSIZE = 9
_TICKS_PER_PANE = 6

#: Fixed axes margins. A layout engine (``tight_layout``) is expensive and forces
#: an extra full draw pass inside ``savefig``; fixed margins are cheaper *and*
#: more deterministic. These are **edge positions** of the axes box (matplotlib's
#: ``subplots_adjust`` semantics): the price scale sits on the **right**
#: (dashboard / TradingView pose), dates run along the bottom, and the header
#: chip lives inside the axes' top-left corner.
_MARGINS: Dict[str, float] = {
    "left": 0.005,
    "right": 0.938,
    "top": 0.97,
    "bottom": 0.075,
}

#: Stacked-pane margins: the same horizontal insets, head-room per pane for its
#: own header chip and date axis, and a fixed ``hspace`` between panes. Fixed
#: (no ``tight_layout``) for the same determinism reason as ``_MARGINS``.
_SPLIT_MARGINS: Dict[str, float] = {
    "left": 0.005,
    "right": 0.938,
    "top": 0.955,
    "bottom": 0.07,
    "hspace": 0.35,
}

#: ``pyplot``, ``Rectangle``, ``Image`` — filled on first render, so the vision
#: stack is imported lazily but only once per process.
_VISION_STACK: Optional[Tuple[Any, Any, Any]] = None

#: Sort fallback for a level with no ``formed_at`` (aware, like every record).
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _vision_stack() -> Tuple[Any, Any, Any]:
    """Import ``(pyplot, Rectangle, Image)`` once, inside the function.

    The import stays function-local so ``import agentic`` never touches
    matplotlib/PIL; the memo keeps it from re-running ``matplotlib.use("Agg")``
    and re-resolving the backend on every render.
    """
    global _VISION_STACK
    if _VISION_STACK is None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        from PIL import Image

        _VISION_STACK = (plt, Rectangle, Image)
    return _VISION_STACK


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass
class TagEntry(Serde):
    """Manifest entry for one drawn tag — the bridge back to exact numbers.

    Built from :func:`agentic.lookup.level_view`, so its fields are the lookup's
    fields minus ``distance_atr`` (the manifest carries no ATR; it is recomputed
    against the resolving pane's ATR).
    """

    tag: str = ""
    level_key: str = ""
    family: str = ""
    timeframe: str = ""
    direction: str = "neutral"
    price: float = 0.0
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    created_at: Optional[str] = None
    status: str = "live"
    origin: str = "live"
    distance_points: Optional[float] = None
    note: str = ""
    is_thesis_level: bool = False
    variant: str = ""
    inside_bars: int = 0
    target: Optional[float] = None


@dataclass
class RenderResult(Serde):
    """A rendered image plus the manifest that makes its tags resolvable."""

    render_id: str = ""
    image_path: str = ""
    image_sha256: str = ""
    width: int = 0
    height: int = 0
    manifest: Dict[str, Any] = field(default_factory=dict)
    tags: Dict[str, TagEntry] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RenderResult":
        """Load, rebuilding ``tags`` as :class:`TagEntry` values.

        :class:`Serde` loads a ``Dict[str, X]`` as a plain dict of dicts, so the
        typed ``tags`` field is restored here rather than left as raw JSON.
        """
        raw = dict(data or {})
        result = super().from_dict(raw)
        tags = raw.get("tags")
        if isinstance(tags, Mapping):
            result.tags = {
                str(tag): (
                    entry if isinstance(entry, TagEntry) else TagEntry.from_dict(entry)
                )
                for tag, entry in tags.items()
            }
        return result


@dataclass
class Pane:
    """One pane of a split render: its own snapshot, bars and resolved pins.

    Pure (a ``FeedSnapshot`` + ``Bars`` + pins), so the renderer never fetches.
    :func:`agentic.tools.render_current` builds a :class:`Pane` per timeframe in
    ``view.panes`` and draws them top→bottom in list order.
    """

    snapshot: FeedSnapshot
    bars: Bars
    pins: Sequence[LevelRecord] = ()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(value: Any) -> Optional[str]:
    """ISO-8601 UTC with a ``Z`` suffix, from unix seconds or a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = as_aware(value)
    else:
        dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_date(value: Any) -> str:
    """``"24 Oct"`` from unix seconds or a datetime — the dashboard's date label."""
    if isinstance(value, datetime):
        dt = as_aware(value)
    else:
        dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d %b")


def _date_of(value: Any) -> str:
    """Just the UTC calendar date, to detect an intraday (same-day) window."""
    return _iso_date(value)


def _time_of(value: Any) -> str:
    """``"03:15"`` from unix seconds or a datetime — an intraday bar's label."""
    if isinstance(value, datetime):
        dt = as_aware(value)
    else:
        dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%H:%M")


class Renderer:
    """Render a :class:`FeedSnapshot` + pins to a deterministic PNG + manifest."""

    def __init__(
        self,
        *,
        width: int = 1536,
        height: int = 864,
        dpi: int = 100,
        clock: Optional[Callable[[], datetime]] = None,
        out_dir: Optional[str] = None,
        max_bars_per_pane: int = 50,
    ):
        self.width = int(width)
        self.height = int(height)
        self.dpi = int(dpi)
        self._clock = clock or _utcnow
        self.out_dir = out_dir or DEFAULT_RENDER_DIR
        #: The screenshot's size cap. ``agentic.store`` refuses a view wider than
        #: this already; the renderer enforces the same invariant on anything
        #: drawn into it, so no call path can paint a pane the tag grid cannot
        #: survive. A *report* chart may raise the cap explicitly.
        self.max_bars_per_pane = int(max_bars_per_pane)

    # ------------------------------------------------------------------ render

    def render(
        self,
        snapshot: FeedSnapshot,
        bars: Bars,
        *,
        pins: Sequence[LevelRecord] = (),
        thesis_level_keys: Iterable[str] = (),
        out_dir: Optional[str] = None,
        panes: Sequence["Pane"] = (),
        layout: str = "single",
        offset: int = 0,
    ) -> RenderResult:
        """Render the perception to a deterministic PNG + manifest.

        **Single pane** (the default, and byte-identical to the pre-split
        renderer): ``snapshot`` + ``bars`` are drawn, ``pins`` merged in.

        **Split** (``layout="split"`` with ``len(panes) > 1``): each :class:`Pane`
        is drawn stacked top→bottom on one figure with its own y-range, title and
        current-price marker; the top-level manifest keys (``timeframe``/
        ``window``/``price_range``/``tags``) describe the **primary** pane
        (``panes[0]``) for back-compat, and a ``panes`` array describes each pane.
        Tags are unique across panes, so a tag from any pane resolves in
        ``level_lookup``.

        ``panes`` is honoured **only** in split layout — ``layout="single"``
        ignores it (so a stray ``panes`` cannot silently split the figure), and
        ``pins`` passed alongside panes are merged into the primary pane.

        ``offset`` is the bar offset the window was fetched at, recorded in the
        manifest's ``window`` (it does not change the pixels).
        """
        thesis: Set[str] = {str(k) for k in (thesis_level_keys or ())}
        pane_list = list(panes or ())
        if layout == "split" and len(pane_list) > 1:
            return self._render_split(
                pane_list, thesis, out_dir, int(offset), pins=list(pins or ())
            )

        # The screenshot-size invariant: a pane wider than ``max_bars_per_pane``
        # is refused, never squeezed — the store caps views at the same bound, so
        # this only trips for direct callers (a *report* chart raises its cap).
        if len(bars.times) > self.max_bars_per_pane:
            raise ValueError(
                f"too_many_bars: a pane renders at most {self.max_bars_per_pane} "
                f"bars, got {len(bars.times)} — request a narrower window (or "
                "pan back with offset) instead"
            )
        levels, pinned_keys = self._level_set(snapshot, pins)
        drawn, hidden = self._visible(levels, pinned_keys)
        display_tags = self._display_tags(drawn, pinned_keys)

        price_range = self._price_range(bars, drawn)
        entries = self._entries(drawn, display_tags, pinned_keys, thesis, snapshot)
        # Canonical manifest order, so a permuted `pins` cannot reorder the keys
        # of an otherwise identical render.
        entries = {tag: entries[tag] for tag in sorted(entries)}

        png = self._draw(snapshot, bars, drawn, display_tags, pinned_keys,
                         price_range, hidden)
        sha = hashlib.sha256(png).hexdigest()
        render_id = f"r_{sha[:16]}"

        target_dir = out_dir or self.out_dir
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{render_id}.png")
        with open(path, "wb") as fh:
            fh.write(png)

        lo, hi = price_range
        manifest: Dict[str, Any] = {
            "render_id": render_id,
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "window": self._window(bars, offset),
            "rendered_at": _iso_z(self._clock()),
            "price_range": [lo, hi],
            "hidden_levels": hidden,
            "image": {
                "path": path,
                "width": self.width,
                "height": self.height,
            },
            "tags": {tag: entry.to_dict() for tag, entry in entries.items()},
        }

        return RenderResult(
            render_id=render_id,
            image_path=path,
            image_sha256=sha,
            width=self.width,
            height=self.height,
            manifest=manifest,
            tags=entries,
        )

    def _render_split(
        self,
        panes: Sequence["Pane"],
        thesis: Set[str],
        out_dir: Optional[str],
        offset: int,
        pins: Sequence[LevelRecord] = (),
    ) -> RenderResult:
        """The multi-pane render: stacked panes, independent y-ranges, merged tags.

        Pane 1 keeps the raw tags (``F1``/``F1*``); pane *i* ≥ 2 is tag-prefixed
        (``P2:F1``) so the merged manifest cannot collide. Each pane's
        ``price_range`` is computed from its own candles + levels only, and its
        own ``current_price``/``atr``/``price_basis`` are recorded so a lookup can
        measure a pane-2 level against pane 2's price. Top-level ``pins`` are
        merged into the primary pane (deduped by ``level_key``).
        """
        extra_pins = list(pins or ())
        drawn_panes: List[Tuple["Pane", List[LevelRecord], Dict[str, str], Set[str], Tuple[float, float], int]] = []
        merged_entries: Dict[str, TagEntry] = {}
        pane_manifest: List[Dict[str, Any]] = []
        for index, pane in enumerate(panes):
            # The screenshot-size invariant, per pane (see ``render``).
            if len(pane.bars.times) > self.max_bars_per_pane:
                raise ValueError(
                    f"too_many_bars: a pane renders at most "
                    f"{self.max_bars_per_pane} bars, pane {index + 1} "
                    f"({pane.snapshot.timeframe}) has {len(pane.bars.times)} — "
                    "request narrower windows (or pan back with offset) instead"
                )
            pane_pins = list(pane.pins) + (extra_pins if index == 0 else [])
            levels, pinned_keys = self._level_set(pane.snapshot, pane_pins)
            visible, hidden = self._visible(levels, pinned_keys)
            display_tags = self._display_tags(visible, pinned_keys)
            if index >= 1:
                prefix = f"P{index + 1}:"
                display_tags = {key: f"{prefix}{tag}" for key, tag in display_tags.items()}
            price_range = self._price_range(pane.bars, visible)
            entries = self._entries(visible, display_tags, pinned_keys, thesis, pane.snapshot)
            entries = {tag: entries[tag] for tag in sorted(entries)}
            merged_entries.update(entries)
            drawn_panes.append(
                (pane, visible, display_tags, pinned_keys, price_range, hidden)
            )
            pane_manifest.append({
                "timeframe": pane.snapshot.timeframe,
                "window": self._window(pane.bars, offset),
                "price_range": [price_range[0], price_range[1]],
                "hidden_levels": hidden,
                "current_price": float(pane.snapshot.current_price),
                "atr": float(pane.snapshot.atr),
                "price_basis": str(pane.snapshot.price_basis or "live"),
            })

        merged_entries = {tag: merged_entries[tag] for tag in sorted(merged_entries)}
        png = self._draw_panes(drawn_panes)
        sha = hashlib.sha256(png).hexdigest()
        render_id = f"r_{sha[:16]}"

        target_dir = out_dir or self.out_dir
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{render_id}.png")
        with open(path, "wb") as fh:
            fh.write(png)

        primary = drawn_panes[0]
        primary_snapshot, _levels, _tags, _pinned, primary_range, _hidden = primary
        lo, hi = primary_range
        manifest: Dict[str, Any] = {
            "render_id": render_id,
            "symbol": primary_snapshot.snapshot.symbol,
            "timeframe": primary_snapshot.snapshot.timeframe,
            "window": self._window(primary_snapshot.bars, offset),
            "rendered_at": _iso_z(self._clock()),
            "price_range": [lo, hi],
            "image": {
                "path": path,
                "width": self.width,
                "height": self.height,
            },
            "tags": {tag: entry.to_dict() for tag, entry in merged_entries.items()},
            "panes": pane_manifest,
        }

        return RenderResult(
            render_id=render_id,
            image_path=path,
            image_sha256=sha,
            width=self.width,
            height=self.height,
            manifest=manifest,
            tags=merged_entries,
        )

    # --------------------------------------------------------------- level set

    @staticmethod
    def _window(bars: Bars, offset: int = 0) -> Dict[str, Any]:
        """The manifest window: ``{from, to, bars, offset}``.

        ``from``/``to`` are the first/last bar times (``Z``-suffixed, UTC) of the
        window actually drawn; ``offset`` records the requested bar offset, so the
        agent can confirm *which* bars it is looking at.
        """
        return {
            "from": _iso_z(bars.times[0]) if bars.times else None,
            "to": _iso_z(bars.times[-1]) if bars.times else None,
            "bars": len(bars.times),
            "offset": int(offset or 0),
        }

    @staticmethod
    def _level_set(
        snapshot: FeedSnapshot, pins: Sequence[LevelRecord]
    ) -> Tuple[List[LevelRecord], Set[str]]:
        """``snapshot.levels`` + ``pins``, deduped by ``level_key``.

        A key that appears in both is drawn once (the feed's record) and marked
        pinned. Order is the feed's, then any pin-only levels appended.
        """
        pinned_keys: Set[str] = {level.level_key for level in pins}
        seen: Set[str] = set()
        ordered: List[LevelRecord] = []
        for level in list(snapshot.levels) + list(pins):
            if level.level_key in seen:
                continue
            seen.add(level.level_key)
            ordered.append(level)
        return ordered, pinned_keys

    # -------------------------------------------------------------------- tags

    def _family_initials(self, levels: Sequence[LevelRecord]) -> Dict[str, str]:
        """A tag initial per family present, deterministic for unknowns.

        Known families use :data:`FAMILY_INITIALS`. An unknown family takes the
        first letter of the alphabet not already claimed by a known initial (or a
        previously assigned unknown), in sorted family order — so two renders of
        the same state assign the same letter.
        """
        initials: Dict[str, str] = {}
        used: Set[str] = set(FAMILY_INITIALS.values())
        for family in sorted({level.family for level in levels}):
            if family in FAMILY_INITIALS:
                initials[family] = FAMILY_INITIALS[family]
                continue
            free = next((ch for ch in _ALPHABET if ch not in used), "?")
            used.add(free)
            initials[family] = free
        return initials

    def _assign_tags(self, levels: Sequence[LevelRecord]) -> Dict[str, str]:
        """``level_key -> base tag`` (no ``*``), assigned deterministically.

        Assignment order is ``(family, price descending, level_key)`` and the
        ordinal counts within the family, so the tags read ``C1``, ``B1``, ``F1``,
        ``F2``, ... They are unique and stable within one render; they are *not*
        promised stable across renders.
        """
        initials = self._family_initials(levels)
        counters: Dict[str, int] = {}
        tags: Dict[str, str] = {}
        ordered = sorted(
            levels, key=lambda level: (level.family, -float(level.price), level.level_key)
        )
        for level in ordered:
            ordinal = counters.get(level.family, 0) + 1
            counters[level.family] = ordinal
            tags[level.level_key] = f"{initials[level.family]}{ordinal}"
        return tags

    def _display_tags(
        self, levels: Sequence[LevelRecord], pinned_keys: Set[str]
    ) -> Dict[str, str]:
        """``level_key -> display tag`` (with the ``*`` for a pin) computed once."""
        return {
            level_key: base + ("*" if level_key in pinned_keys else "")
            for level_key, base in self._assign_tags(levels).items()
        }

    def _entries(
        self,
        levels: Sequence[LevelRecord],
        display_tags: Dict[str, str],
        pinned_keys: Set[str],
        thesis: Set[str],
        snapshot: FeedSnapshot,
    ) -> Dict[str, TagEntry]:
        """The manifest map: display tag -> :class:`TagEntry` from ``level_view``."""
        current_price = float(snapshot.current_price)
        atr = float(snapshot.atr)
        entries: Dict[str, TagEntry] = {}
        for level in levels:
            tag = display_tags[level.level_key]
            view = level_view(
                level,
                tag=tag,
                origin="pinned" if level.level_key in pinned_keys else "live",
                current_price=current_price,
                atr=atr,
                is_thesis_level=level.level_key in thesis,
            )
            entries[tag] = TagEntry.from_dict(view)
        return entries

    # ----------------------------------------------------------------- drawing

    @staticmethod
    def _visible(
        levels: Sequence[LevelRecord], pinned_keys: Set[str]
    ) -> Tuple[List[LevelRecord], int]:
        """The per-family ray budget, dashboard parity: newest rays win.

        Rays are consumed newest-first, ``MAX_RAYS_PER_FAMILY`` per family, so a
        busy family (``ts`` emits ~130 on 300 M15 bars) can never starve a quiet
        one, and *pinned* levels are exempt — an agent's own pin is never hidden.
        Returns ``(drawn, hidden_count)``; the whole point of the count is that
        the manifest can say why a level is absent instead of the agent silently
        missing it.
        """
        per: Dict[str, int] = {}
        drawn: List[LevelRecord] = []
        ordered = sorted(
            levels,
            key=lambda level: (level.formed_at or _EPOCH, level.level_key),
            reverse=True,
        )
        for level in ordered:
            if level.level_key in pinned_keys:
                drawn.append(level)
                continue
            family = level.family
            used = per.get(family, 0)
            if used >= MAX_RAYS_PER_FAMILY:
                continue
            per[family] = used + 1
            drawn.append(level)
        return drawn, len(levels) - len(drawn)

    @staticmethod
    def _span(level: LevelRecord, bars: Bars) -> Tuple[int, int]:
        """The bar-index x-span a level is drawn across — never full-width.

        Dashboard parity: a level whose life cycle ended draws formation → end,
        and a still-active one draws formation → formation + ``_RAY_BARS`` (a
        short open span, not a ray to the right edge). Everything clamps into the
        drawn window, which is what an HTF formation outside it needs.
        """
        count = max(len(bars.times), 1)
        start = bars.index_at_or_before(level.formed_at)
        start = max(start, 0)
        if level.changed_at is not None and level.changed_at > (level.formed_at or _EPOCH):
            end = bars.index_at_or_before(level.changed_at)
            if end < 0:
                end = min(start + _RAY_BARS, count - 1)
        else:
            end = min(start + _RAY_BARS, count - 1)
        if end <= start:
            end = min(start + 1, count - 1)
        return start, end

    @staticmethod
    def _level_style(
        level: LevelRecord, pinned: bool, price: float
    ) -> Tuple[str, float]:
        """``(color, alpha)`` — the dashboard's ink rules, hairline weight fixed.

        Weight is uniform by design (the dashboard draws every level as a 1px
        dotted line), so only colour and fade vary: broken levels fade to gray;
        swept/taken/distributed ones keep their family colour at the dashboard's
        35% fade; every family carries the colour the web chart shows it in.
        ``pinned`` overrides colour (the agent's own marker must never be
        mistaken for a level's family ink) and never fades.
        """
        status = level.status
        if status is LevelStatus.BROKEN and not pinned:
            return _BROKEN, 1.0
        family = level.family
        direction = level.direction
        attrs = level.attrs
        if family == "crt":
            color = "#00e676" if direction == "bullish" else "#ff5c6c"
            return (
                color,
                _HISTORY_ALPHA if status is not LevelStatus.LIVE else 1.0,
            )
        if family == "bos":
            return "#ff9100" if attrs.get("kind") == "CHoCH" else "#7aa2ff", 1.0
        if family == "liquidity":
            # A pool above price is a buy-side magnet (EQH), below is sell-side
            # (EQL): the record's direction is neutral, so price position says it.
            color = "#ff5252" if level.price > price else "#4dd0e1"
            return (
                color,
                _HISTORY_ALPHA if status is not LevelStatus.LIVE else 1.0,
            )
        if family == "ts":
            return ("#ff5c6c" if direction == "bearish" else "#00e676"), 1.0
        if family == "idm":
            rule = str(attrs.get("rule", "") or "")
            color = "#ffab40" if rule == "two_candle" else (
                "#d4e157" if rule == "ref_candle" else "#ffd600"
            )
            return (
                color,
                _HISTORY_ALPHA if status is not LevelStatus.LIVE else 1.0,
            )
        if family == "sr":
            fresh = str(attrs.get("state", "") or "").upper() == "FRESH"
            color = (
                ("#00e5ff" if level.price <= price else "#ff9100") if fresh
                else ("#546e7a" if level.price <= price else "#78909c")
            )
            return color, 1.0
        if family == "qm":
            fresh = str(attrs.get("state", "") or "").upper() == "FRESH"
            return ("#b388ff" if fresh else "#6d5b99"), 1.0
        if family == "trendline":
            return ("#26a69a" if level.price >= price else "#ef5350"), 1.0
        return "#00e5ff", 1.0

    @staticmethod
    def _price_range(
        bars: Bars, levels: Sequence[LevelRecord]
    ) -> Tuple[float, float]:
        """The drawn price range: candle extremes, level prices, and zone bands.

        Level *rays* extend the range (the dashboard's autoscale includes every
        price series a ray is drawn at), and band extents only for the
        **zone** families actually painted as boxes — a ``crt`` or ``qm`` range
        is information the ray does not show, and including it here used to zoom
        the whole chart out to fit rectangles that were never drawn.
        """
        lows: List[float] = [float(v) for v in bars.low]
        highs: List[float] = [float(v) for v in bars.high]
        for level in levels:
            lows.append(float(level.price))
            highs.append(float(level.price))
            if level.family in _ZONE_FAMILIES:
                band = level.band()
                if band is not None:
                    lows.append(min(float(band[0]), float(band[1])))
                    highs.append(max(float(band[0]), float(band[1])))
        if not lows or not highs:
            return 0.0, 0.0
        return min(lows), max(highs)

    def _draw(
        self,
        snapshot: FeedSnapshot,
        bars: Bars,
        levels: Sequence[LevelRecord],
        display_tags: Dict[str, str],
        pinned_keys: Set[str],
        price_range: Tuple[float, float],
        hidden: int = 0,
    ) -> bytes:
        plt, rectangle, _ = _vision_stack()
        fig, ax = plt.subplots(
            figsize=(self.width / self.dpi, self.height / self.dpi), dpi=self.dpi
        )
        try:
            fig.patch.set_facecolor(_BG)
            ax.set_facecolor(_BG)
            fig.subplots_adjust(**_MARGINS)
            self._draw_candles(ax, bars, rectangle)
            self._draw_levels(ax, bars, levels, display_tags, pinned_keys)
            self._draw_chrome(
                ax, snapshot, bars, price_range,
                drawn_count=len(levels), hidden_count=hidden,
            )
            return self._png_bytes(fig)
        finally:
            plt.close(fig)

    def _draw_panes(
        self,
        drawn: Sequence[Tuple[Pane, Sequence[LevelRecord], Dict[str, str], Set[str], Tuple[float, float], int]],
    ) -> bytes:
        """Draw the panes stacked top→bottom on one figure.

        Each pane gets its own candles, levels, header chip, current-price
        marker and **independent y-range** (``_draw_chrome`` sets ``set_ylim``
        per axes), so a quiet LTF pane is not flattened by the HTF pane's range.
        """
        plt, rectangle, _ = _vision_stack()
        count = len(drawn)
        fig, axes = plt.subplots(
            nrows=count,
            ncols=1,
            figsize=(self.width / self.dpi, self.height / self.dpi),
            dpi=self.dpi,
            squeeze=False,
        )
        try:
            fig.patch.set_facecolor(_BG)
            fig.subplots_adjust(**_SPLIT_MARGINS)
            for ax, (pane, levels, display_tags, pinned_keys, price_range, hidden) in zip(
                axes.ravel(), drawn
            ):
                ax.set_facecolor(_BG)
                self._draw_candles(ax, pane.bars, rectangle)
                self._draw_levels(ax, pane.bars, levels, display_tags, pinned_keys)
                self._draw_chrome(
                    ax, pane.snapshot, pane.bars, price_range,
                    drawn_count=len(levels), hidden_count=hidden,
                )
            return self._png_bytes(fig)
        finally:
            plt.close(fig)

    def _draw_candles(self, ax: Any, bars: Bars, rectangle: Any) -> None:
        """One OHLC candlestick per bar, bullish/bearish colour-coded."""
        for i in range(len(bars.times)):
            o = float(bars.open[i])
            h = float(bars.high[i])
            low = float(bars.low[i])
            c = float(bars.close[i])
            color = _UP if c >= o else _DOWN
            ax.plot([i, i], [low, h], color=color, linewidth=_WICK_LINEWIDTH, zorder=2)
            if c == o:
                ax.plot(
                    [i - _CANDLE_WIDTH / 2, i + _CANDLE_WIDTH / 2],
                    [c, c],
                    color=color,
                    linewidth=_WICK_LINEWIDTH,
                    zorder=3,
                )
            else:
                ax.add_patch(
                    rectangle(
                        (i - _CANDLE_WIDTH / 2, min(o, c)),
                        _CANDLE_WIDTH,
                        abs(c - o),
                        facecolor=color,
                        edgecolor="none",
                        linewidth=0,
                        zorder=3,
                    )
                )

    def _draw_levels(
        self,
        ax: Any,
        bars: Bars,
        levels: Sequence[LevelRecord],
        display_tags: Dict[str, str],
        pinned_keys: Set[str],
    ) -> None:
        """Dashboard parity: bounded rays, zone boxes, per-family ink, mid tags.

        Nothing here paints a full-width band: a level draws from its formation
        bar to its life-cycle end (or a short open span while still live), zones
        draw as quiet 8%-alpha boxes with dotted edges, and each drawn level gets
        its tag at the **middle** of its span — a right-edge pile-up of 190 tags
        is exactly the unreadable column this rewrite replaces.
        """
        current_price = float(bars.close[-1]) if len(bars.close) else 0.0
        for level in levels:
            pinned = level.level_key in pinned_keys
            tag = display_tags[level.level_key]
            color, alpha = self._level_style(level, pinned, current_price)
            x0, x1 = self._span(level, bars)
            price = float(level.price)
            band = level.band() if level.family in _ZONE_FAMILIES else None
            if band is not None:
                lo, hi = sorted(float(v) for v in band)
                ax.fill_between(
                    [x0, x1], lo, hi, color=color, alpha=_ZONE_FILL_ALPHA,
                    linewidth=0, zorder=1,
                )
                for edge_price in (lo, hi):
                    ax.plot(
                        [x0, x1], [edge_price, edge_price],
                        color=color, alpha=alpha, linewidth=_LEVEL_LINEWIDTH,
                        linestyle=_LEVEL_STYLE, zorder=2,
                    )
                label_price = (lo + hi) / 2.0
            else:
                ax.plot(
                    [x0, x1], [price, price],
                    color=color, alpha=alpha, linewidth=_LEVEL_LINEWIDTH,
                    linestyle=_LEVEL_STYLE, zorder=3,
                )
                label_price = price
            if pinned:
                # A pin must survive every status fade — it is the agent's own marker.
                color, alpha = _PINNED, 1.0
            # The dashboard's label pose: tiny plain family-coloured text sitting
            # on its own dotted line — no bold, no bubble box. A tag in the
            # manifest is still always a tag on the image (the ray budget runs
            # before tagging), so the lookup bridge never points at air.
            ax.text(
                (x0 + x1) / 2.0,
                label_price,
                tag,
                color=color,
                alpha=alpha,
                fontsize=_TAG_FONTSIZE,
                ha="center",
                va="bottom",
                zorder=6,
            )

    def _draw_chrome(
        self,
        ax: Any,
        snapshot: FeedSnapshot,
        bars: Bars,
        price_range: Tuple[float, float],
        drawn_count: int = 0,
        hidden_count: int = 0,
    ) -> None:
        """The dashboard's chrome: header chip, price rail, dates — nothing else.

        The header chip is the web panel's ("``XAUUSDm  TF: D1  LEVELS DRAWN: 13``"),
        telling the agent at a glance what it is looking at and *that some levels
        are off-picture* when the ray budget hid any. The current price is a
        dotted hairline with a red chip on the right scale, as on the dashboard.
        """
        from matplotlib.ticker import FuncFormatter

        count = len(bars.times)
        y_lo, y_hi = price_range
        pad = (y_hi - y_lo) * 0.05 if y_hi != y_lo else 1.0

        current_price = float(snapshot.current_price)
        ax.axhline(current_price, color=_PRICE, linewidth=_LEVEL_LINEWIDTH,
                   linestyle=_LEVEL_STYLE, zorder=5)
        if count:
            ax.text(
                count - 1 + 0.4,
                current_price,
                f"{current_price:.2f}",
                color=_BG,
                fontsize=_TICK_FONTSIZE,
                ha="left",
                va="center",
                zorder=7,
                bbox=dict(facecolor=_PRICE, edgecolor="none", alpha=1.0, pad=1.5),
            )

        hidden_s = f" (+{hidden_count} hidden)" if hidden_count else ""
        ax.text(
            0.0,
            1.0,
            f"{snapshot.symbol}   TF: {snapshot.timeframe}   "
            f"LEVELS DRAWN: {drawn_count}{hidden_s}",
            transform=ax.transAxes,
            color=_INK,
            fontsize=_HEADER_FONTSIZE,
            ha="left",
            va="top",
            zorder=7,
            bbox=dict(
                boxstyle="round,pad=0.35", facecolor="#1c1f26", edgecolor="#2a2e39",
                alpha=0.9,
            ),
        )

        ax.set_xlim(-1, count if count else 1)
        ax.set_ylim(y_lo - pad, y_hi + pad)
        ax.grid(True, color=_GRID, linewidth=0.6, alpha=0.9)
        ax.set_axisbelow(True)
        # The date axis is real: the agent reads *when* its window starts and
        # ends straight off the picture, like the dashboard's bottom labels.
        # An intraday window (all bars on one UTC date) labels times instead —
        # repeating "19 Oct" six times says nothing.
        if count:
            same_day = _date_of(bars.times[0]) == _date_of(bars.times[-1])
            step = max(1, count // _TICKS_PER_PANE)
            ticks = list(range(0, count, step))
            ax.set_xticks(ticks)
            ax.set_xticklabels(
                [
                    _time_of(bars.times[i]) if same_day else _iso_date(bars.times[i])
                    for i in ticks
                ],
                fontsize=_TICK_FONTSIZE,
                color=_INK,
            )
        else:
            ax.set_xticks([])
        for side in ("top", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["right"].set_color(_GRID)
        ax.spines["bottom"].set_color(_GRID)
        ax.yaxis.tick_right()
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, pos: f"{v:.2f}"))
        ax.tick_params(axis="y", labelsize=_TICK_FONTSIZE, colors=_INK, length=3)
        ax.tick_params(axis="x", colors=_INK, length=3)

    def _png_bytes(self, fig: Any) -> bytes:
        """Serialise the figure to deterministic, metadata-free PNG bytes.

        The figure is rasterised exactly **once**: ``canvas.draw()`` fills the Agg
        buffer and ``buffer_rgba()`` reads it back, so there is no second draw and
        no matplotlib ``Software`` metadata to strip. PIL encodes the raw RGBA
        deterministically, so two renders of one state hash equal.
        """
        _, _, Image = _vision_stack()
        fig.canvas.draw()
        width, height = fig.canvas.get_width_height()
        buf = io.BytesIO()
        Image.frombytes("RGBA", (width, height), fig.canvas.buffer_rgba()).save(
            buf, format="PNG"
        )
        return buf.getvalue()
