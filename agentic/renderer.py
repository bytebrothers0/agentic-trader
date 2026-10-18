"""agentic/renderer.py — the server-side PNG render + its manifest (spec phase 3).

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "Perception contract:
render + manifest + lookup".

There is no browser in the loop. The view is rendered to a PNG on the server, in
a style built for a *vision model* rather than a human: high contrast, thick
lines, large legible fonts, minimal chrome, no gridline noise. Every drawn level
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
from agentic.models import Serde

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

# Vision-optimised palette: saturated ink on white, so the raster survives
# downscaling and JPEG-ish tokenisation.
_BG = "#ffffff"
_INK = "#101010"
_UP = "#0b8a3e"
_DOWN = "#c62828"
_LEVEL = "#1f4fd8"
_PINNED = "#e07600"
_PRICE = "#101010"

_CANDLE_WIDTH = 0.6
_LEVEL_LINEWIDTH = 3.0
_PRICE_LINEWIDTH = 2.5
_TAG_FONTSIZE = 18
_TITLE_FONTSIZE = 22
_TICK_FONTSIZE = 16

#: Fixed axes margins. A layout engine (``tight_layout``) is expensive and forces
#: an extra full draw pass inside ``savefig``; fixed margins are cheaper *and*
#: more deterministic. Tuned so the title (top) and the y tick labels (left) are
#: not clipped at the default size; tags and the PX label sit inside the axes.
_MARGINS: Dict[str, float] = {
    "left": 0.085,
    "right": 0.995,
    "top": 0.885,
    "bottom": 0.045,
}

#: Stacked-pane margins: the same horizontal insets, a little more head-room per
#: pane for its own title, and a fixed ``hspace`` between panes. Fixed (no
#: ``tight_layout``) for the same determinism reason as ``_MARGINS``.
_SPLIT_MARGINS: Dict[str, float] = {
    "left": 0.085,
    "right": 0.995,
    "top": 0.93,
    "bottom": 0.04,
    "hspace": 0.30,
}

#: ``pyplot``, ``Rectangle``, ``Image`` — filled on first render, so the vision
#: stack is imported lazily but only once per process.
_VISION_STACK: Optional[Tuple[Any, Any, Any]] = None


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
    ):
        self.width = int(width)
        self.height = int(height)
        self.dpi = int(dpi)
        self._clock = clock or _utcnow
        self.out_dir = out_dir or DEFAULT_RENDER_DIR

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

        levels, pinned_keys = self._level_set(snapshot, pins)
        display_tags = self._display_tags(levels, pinned_keys)

        price_range = self._price_range(bars, levels)
        entries = self._entries(levels, display_tags, pinned_keys, thesis, snapshot)
        # Canonical manifest order, so a permuted `pins` cannot reorder the keys
        # of an otherwise identical render.
        entries = {tag: entries[tag] for tag in sorted(entries)}

        png = self._draw(snapshot, bars, levels, display_tags, pinned_keys, price_range)
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
        drawn: List[Tuple["Pane", List[LevelRecord], Dict[str, str], Set[str], Tuple[float, float]]] = []
        merged_entries: Dict[str, TagEntry] = {}
        pane_manifest: List[Dict[str, Any]] = []
        for index, pane in enumerate(panes):
            pane_pins = list(pane.pins) + (extra_pins if index == 0 else [])
            levels, pinned_keys = self._level_set(pane.snapshot, pane_pins)
            display_tags = self._display_tags(levels, pinned_keys)
            if index >= 1:
                prefix = f"P{index + 1}:"
                display_tags = {key: f"{prefix}{tag}" for key, tag in display_tags.items()}
            price_range = self._price_range(pane.bars, levels)
            entries = self._entries(levels, display_tags, pinned_keys, thesis, pane.snapshot)
            entries = {tag: entries[tag] for tag in sorted(entries)}
            merged_entries.update(entries)
            drawn.append((pane, levels, display_tags, pinned_keys, price_range))
            pane_manifest.append({
                "timeframe": pane.snapshot.timeframe,
                "window": self._window(pane.bars, offset),
                "price_range": [price_range[0], price_range[1]],
                "current_price": float(pane.snapshot.current_price),
                "atr": float(pane.snapshot.atr),
                "price_basis": str(pane.snapshot.price_basis or "live"),
            })

        merged_entries = {tag: merged_entries[tag] for tag in sorted(merged_entries)}
        png = self._draw_panes(drawn)
        sha = hashlib.sha256(png).hexdigest()
        render_id = f"r_{sha[:16]}"

        target_dir = out_dir or self.out_dir
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{render_id}.png")
        with open(path, "wb") as fh:
            fh.write(png)

        primary = drawn[0]
        primary_snapshot, _levels, _tags, _pinned, primary_range = primary
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
    def _price_range(
        bars: Bars, levels: Sequence[LevelRecord]
    ) -> Tuple[float, float]:
        """The drawn price range: candle extremes, level prices, and zone bands.

        Band extents are included so a zone that reaches beyond its anchor price
        (or beyond the candles) is never clipped.
        """
        lows: List[float] = [float(v) for v in bars.low]
        highs: List[float] = [float(v) for v in bars.high]
        for level in levels:
            lows.append(float(level.price))
            highs.append(float(level.price))
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
            self._draw_chrome(ax, snapshot, bars, price_range)
            return self._png_bytes(fig)
        finally:
            plt.close(fig)

    def _draw_panes(
        self,
        drawn: Sequence[Tuple[Pane, Sequence[LevelRecord], Dict[str, str], Set[str], Tuple[float, float]]],
    ) -> bytes:
        """Draw the panes stacked top→bottom on one figure.

        Each pane gets its own candles, levels, title, current-price marker and
        **independent y-range** (``_draw_chrome`` sets ``set_ylim`` per axes), so a
        quiet LTF pane is not flattened by the HTF pane's range.
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
            for ax, (pane, levels, display_tags, pinned_keys, price_range) in zip(
                axes.ravel(), drawn
            ):
                ax.set_facecolor(_BG)
                self._draw_candles(ax, pane.bars, rectangle)
                self._draw_levels(ax, pane.bars, levels, display_tags, pinned_keys)
                self._draw_chrome(ax, pane.snapshot, pane.bars, price_range)
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
            ax.plot([i, i], [low, h], color=color, linewidth=1.6, zorder=2)
            if c == o:
                ax.plot(
                    [i - _CANDLE_WIDTH / 2, i + _CANDLE_WIDTH / 2],
                    [c, c],
                    color=color,
                    linewidth=_LEVEL_LINEWIDTH,
                    zorder=3,
                )
            else:
                ax.add_patch(
                    rectangle(
                        (i - _CANDLE_WIDTH / 2, min(o, c)),
                        _CANDLE_WIDTH,
                        abs(c - o),
                        facecolor=color,
                        edgecolor=color,
                        linewidth=0.8,
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
        """Every level as a line, its band filled, its tag labelled next to it."""
        count = len(bars.times)
        label_x = (count - 1) if count else 0
        for level in levels:
            pinned = level.level_key in pinned_keys
            tag = display_tags[level.level_key]
            color = _PINNED if pinned else _LEVEL
            band = level.band()
            if band is not None:
                lo, hi = sorted(float(v) for v in band)
                ax.fill_between([-1, count], lo, hi, color=color, alpha=0.16, zorder=1)
            ax.axhline(float(level.price), color=color, linewidth=_LEVEL_LINEWIDTH, zorder=4)
            ax.text(
                label_x,
                float(level.price),
                tag,
                color=color,
                fontsize=_TAG_FONTSIZE,
                fontweight="bold",
                ha="right",
                va="center",
                zorder=6,
                bbox=dict(facecolor=_BG, edgecolor="none", alpha=0.85, pad=1.2),
            )

    def _draw_chrome(
        self,
        ax: Any,
        snapshot: FeedSnapshot,
        bars: Bars,
        price_range: Tuple[float, float],
    ) -> None:
        """The current-price marker, the title, and the minimal axes chrome."""
        count = len(bars.times)
        y_lo, y_hi = price_range
        pad = (y_hi - y_lo) * 0.05 if y_hi != y_lo else 1.0

        current_price = float(snapshot.current_price)
        ax.axhline(
            current_price, color=_PRICE, linewidth=_PRICE_LINEWIDTH, linestyle=":", zorder=5
        )
        if count:
            ax.text(
                0,
                current_price,
                f"PX {current_price:.2f}",
                color=_PRICE,
                fontsize=_TAG_FONTSIZE,
                fontweight="bold",
                ha="left",
                va="bottom",
                zorder=6,
                bbox=dict(facecolor=_BG, edgecolor="none", alpha=0.85, pad=1.2),
            )

        ax.set_title(
            f"{snapshot.symbol}  {snapshot.timeframe}  ({count} bars)",
            fontsize=_TITLE_FONTSIZE,
            fontweight="bold",
            color=_INK,
        )
        ax.set_xlim(-1, count if count else 1)
        ax.set_ylim(y_lo - pad, y_hi + pad)
        ax.grid(False)
        ax.set_xticks([])
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color(_INK)
        ax.spines["bottom"].set_color(_INK)
        ax.tick_params(axis="y", labelsize=_TICK_FONTSIZE, colors=_INK, length=4)

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
