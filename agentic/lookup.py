"""agentic/lookup.py — the numeric lookup tool (spec phase 3).

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "The numeric lookup
tool".

The image teaches the agent *what exists and where*; this module teaches it
*exactly what it is*. Every price the agent states must come from here — a vision
model reading ``4168.66`` off a raster will sometimes read ``4166.86``. So the
lookup is the ground truth for anything the agent saw.

The level view
--------------
:func:`level_view` is the single canonical projection of a
:class:`~agentic.feed.LevelRecord` into the ~15 numbers the agent is allowed to
cite: price and zone band, family/timeframe/direction, the life-cycle status, the
``live``/``pinned`` origin, the signed distance in points and ATR, and the
family-specific extras. Both the lookup (via :class:`LookupRecord`) and the
render manifest (via ``agentic.renderer.TagEntry``) build from this one dict, so
the two can never drift. It lives here, in the pure core, so the renderer imports
from the lookup rather than the other way round.

The dict is JSON-safe: the status is its string value and ``created_at`` is an
ISO-8601 string (round-tripped back to a :class:`datetime` on load).

Resolution precedence
---------------------
A ``query`` is resolved by the first of these keys it carries:

``tag``
    What the agent just saw. Resolved through the render manifest's ``tags`` map,
    so the answer is for *exactly* the level that was drawn under that tag — which
    is why the lookup accepts ``tags``.
``level_key``
    Something re-resolved from a previous turn; the image's tags are deliberately
    not stable across renders.
``family`` (+ optional ``timeframe``)
    A whole family, for surveying.
``near_price`` (+ ``radius``, default ``0``)
    What is around here.

A query with none of those keys answers "what is the current price and its ATR"
and nothing else.

Numbers
-------
Distances are **signed**: ``price - current_price`` (a level above the market is
positive), in points and in ATR. ``origin`` is ``live`` or ``pinned`` and comes
from the tag when resolving by tag — this is how the agent can never confuse what
the current timeframe is producing with what it deliberately held. ``note``
carries the human description the feed copies from the detector's ``desc``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from agentic._time import as_aware
from agentic.feed import FeedSnapshot, LevelRecord
from agentic.models import LevelStatus, Serde

# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass
class LookupRecord(Serde):
    """One exact answer about one level.

    ``price`` is the level itself; ``price_low``/``price_high`` are its zone band
    when it has one (CRT range, FVG/OB box, QM/OCL box). ``tag`` is filled only
    when the query resolved by tag. ``origin`` is the spec's ``live``/``pinned``,
    never the human ``desc`` — that lives in ``note``.
    """

    level_key: str = ""
    tag: str = ""
    family: str = ""
    timeframe: str = ""
    direction: str = "neutral"
    price: float = 0.0
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    created_at: Optional[datetime] = None
    status: str = "live"  # live|swept|broken|filled|not_found
    origin: str = "live"  # live|pinned (spec's origin)
    note: str = ""  # the LevelRecord.origin description
    distance_points: Optional[float] = None
    distance_atr: Optional[float] = None
    is_thesis_level: bool = False
    variant: str = ""
    inside_bars: int = 0
    target: Optional[float] = None


@dataclass
class LookupResult(Serde):
    """The answer to one query, always carrying the live market header."""

    query: Dict[str, Any] = field(default_factory=dict)
    current_price: float = 0.0
    atr: float = 0.0
    #: ``live`` or ``window_end`` — whether the header price is the live price or
    #: the last close of a past (offset) window. In split mode it is the basis of
    #: the pane the query resolved to.
    price_basis: str = "live"
    matches: List[LookupRecord] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# The canonical level projection
# --------------------------------------------------------------------------- #


def status_value(level: LevelRecord) -> str:
    """The life-cycle status as its string value (``live``/``swept``/...)."""
    status = level.status
    return status.value if isinstance(status, LevelStatus) else str(status or "live")


def _distances(price: float, current_price: float, atr: float) -> Tuple[float, Optional[float]]:
    """Signed ``(points, atr)`` distance of ``price`` from the market.

    ``atr`` is ``None`` when there is no ATR to divide by, rather than a
    division-by-zero.
    """
    points = float(price) - float(current_price)
    atr_distance = (points / atr) if atr else None
    return points, atr_distance


def level_view(
    level: LevelRecord,
    *,
    tag: str = "",
    origin: str = "live",
    current_price: float = 0.0,
    atr: float = 0.0,
    is_thesis_level: bool = False,
) -> Dict[str, Any]:
    """The canonical, JSON-safe projection of one level.

    Every number the agent may cite about a level is computed here exactly once,
    so :class:`LookupRecord` and the render manifest's ``TagEntry`` are two views
    of the same facts. ``status`` is the string value; ``created_at`` is an ISO
    string (parsed back to a datetime on :meth:`Serde.from_dict`).
    """
    points, atr_distance = _distances(level.price, current_price, atr)
    formed_at = as_aware(level.formed_at)
    return {
        "level_key": level.level_key,
        "tag": tag,
        "family": level.family,
        "timeframe": level.timeframe,
        "direction": level.direction,
        "price": float(level.price),
        "price_low": level.band_low,
        "price_high": level.band_high,
        "created_at": formed_at.isoformat() if formed_at else None,
        "status": status_value(level),
        "origin": origin,
        "note": level.origin,
        "distance_points": points,
        "distance_atr": atr_distance,
        "is_thesis_level": bool(is_thesis_level),
        "variant": level.variant,
        "inside_bars": level.inside_bars,
        "target": level.target,
    }


# --------------------------------------------------------------------------- #
# The tool
# --------------------------------------------------------------------------- #


def _not_found(level_key: str, *, tag: str) -> LookupRecord:
    return LookupRecord(level_key=level_key, tag=tag, status="not_found", origin="live")


def _manifest_record(
    data: Dict[str, Any],
    *,
    tag: str,
    current_price: float,
    atr: float,
    thesis: Set[str],
) -> LookupRecord:
    """Answer from a manifest tag entry when the level is no longer in the feed.

    The drawn state is still the state the agent saw, so the lookup answers from
    the manifest's copy rather than pretending the tag never existed. The
    manifest's ``distance_points`` is taken as drawn; ``distance_atr`` is
    recomputed against the *current* ATR, because the manifest carries no ATR.
    """
    view = dict(data)
    level_key = str(view.get("level_key", "") or "")
    price = float(view.get("price", 0.0) or 0.0)
    points = view.get("distance_points")
    points = _distances(price, current_price, atr)[0] if points is None else float(points)
    view.update(
        tag=tag,
        level_key=level_key,
        price=price,
        distance_points=points,
        distance_atr=(points / atr) if atr else None,
        is_thesis_level=level_key in thesis,
    )
    return LookupRecord.from_dict(view)


def _pane_index_for_tag(tag: str) -> int:
    """The 0-based pane a tag belongs to: ``P2:F1`` → 1, a raw ``F1`` → 0.

    The renderer prefixes every pane after the first with its 1-based index, so a
    ``P{n}:`` prefix is the map back to the pane (and thus its price basis).
    """
    head, sep, _rest = str(tag).partition(":")
    if sep and len(head) >= 2 and head[0] == "P" and head[1:].isdigit():
        return max(0, int(head[1:]) - 1)
    return 0


def level_lookup(
    snapshot: FeedSnapshot,
    query: Optional[Dict[str, Any]] = None,
    *,
    tags: Optional[Dict[str, Any]] = None,
    thesis_level_keys: Iterable[str] = (),
    price: Optional[float] = None,
    atr: Optional[float] = None,
    snapshots: Optional[Iterable[FeedSnapshot]] = None,
    panes: Optional[Iterable[Mapping[str, Any]]] = None,
) -> LookupResult:
    """Resolve a level query against the feed — the ground truth for the agent.

    ``tags`` is the render manifest's ``tags`` map (tag -> entry carrying
    ``level_key`` and ``origin``). ``thesis_level_keys`` marks which matches are
    the agent's stated levels of interest. ``price``/``atr`` override the
    snapshot's header when the caller has a fresher number.

    In **split** mode the caller passes ``snapshots`` (one per pane, primary
    first) so ``family``/``near_price``/``level_key`` search *every* pane, not just
    the primary. ``panes`` is the manifest's pane array; its recorded
    ``current_price``/``atr`` give each pane's own price basis, so a pane-2 match
    is measured against pane 2's price (not the primary's). Every match is
    measured against the price basis of the pane it was found on; the header is
    the primary pane's basis, or the tag's pane when resolving by tag.
    """
    query = dict(query or {})
    pools: List[FeedSnapshot] = [snapshot]
    for extra in (snapshots or ()):
        if extra is not snapshot and extra not in pools:
            pools.append(extra)
    pane_meta: List[Mapping[str, Any]] = [p for p in (panes or ()) if isinstance(p, Mapping)]

    primary_price = float(snapshot.current_price if price is None else price)
    primary_atr = float(snapshot.atr if atr is None else atr)
    thesis: Set[str] = {str(k) for k in (thesis_level_keys or ())}
    tag_map: Dict[str, Any] = dict(tags or {})

    def basis_for(snap: FeedSnapshot) -> Tuple[float, float, str]:
        """``(price, atr, basis)`` for a snapshot; the primary honours overrides."""
        if snap is snapshot:
            return primary_price, primary_atr, str(snapshot.price_basis or "live")
        return float(snap.current_price), float(snap.atr), str(snap.price_basis or "live")

    def pane_basis(index: int) -> Tuple[float, float, str]:
        """``(price, atr, basis)`` for pane ``index`` — the manifest's values when held."""
        snap = pools[index] if 0 <= index < len(pools) else snapshot
        price_value, atr_value, basis = basis_for(snap)
        if 0 <= index < len(pane_meta):
            pane = pane_meta[index]
            if pane.get("current_price") is not None:
                price_value = float(pane["current_price"])
            if pane.get("atr") is not None:
                atr_value = float(pane["atr"])
            basis = str(pane.get("price_basis", basis) or basis)
        return price_value, atr_value, basis

    def emit(level: LevelRecord, snap: FeedSnapshot, tag: str = "", origin: str = "live") -> LookupRecord:
        cp, at, _basis = basis_for(snap)
        view = level_view(
            level,
            tag=tag,
            origin=origin,
            current_price=cp,
            atr=at,
            is_thesis_level=level.level_key in thesis,
        )
        return LookupRecord.from_dict(view)

    def find(level_key: str) -> Tuple[Optional[LevelRecord], Optional[FeedSnapshot]]:
        for snap in pools:
            level = snap.by_key(level_key)
            if level is not None:
                return level, snap
        return None, None

    matches: List[LookupRecord] = []
    header_price = primary_price
    header_atr = primary_atr
    header_basis = str(snapshot.price_basis or "live")

    tag_query = query.get("tag")
    key_query = query.get("level_key")
    family_query = query.get("family")
    near_query = query.get("near_price")

    if tag_query is not None:
        tag = str(tag_query)
        index = _pane_index_for_tag(tag)
        header_price, header_atr, header_basis = pane_basis(index)
        entry = tag_map.get(tag)
        if entry is None:
            matches.append(_not_found("", tag=tag))
        else:
            view = entry.to_dict() if isinstance(entry, Serde) else dict(entry)
            level, snap = find(str(view.get("level_key", "") or ""))
            if level is not None and snap is not None:
                matches.append(emit(level, snap, tag, str(view.get("origin", "live") or "live")))
            else:
                matches.append(
                    _manifest_record(
                        view,
                        tag=tag,
                        current_price=header_price,
                        atr=header_atr,
                        thesis=thesis,
                    )
                )

    elif key_query is not None:
        level, snap = find(str(key_query))
        matches.append(
            emit(level, snap) if level is not None and snap is not None
            else _not_found(str(key_query), tag="")
        )

    elif family_query is not None or near_query is not None:
        family = str(family_query) if family_query is not None else None
        timeframe = query.get("timeframe")
        radius = float(query.get("radius", 0) or 0.0)
        found: List[Tuple[LevelRecord, Any]] = []
        for snap in pools:
            for level in snap.levels:
                # Family filter (optional).
                if family is not None and level.family != family:
                    continue
                # Timeframe filter (optional).
                if timeframe is not None and level.timeframe != str(timeframe):
                    continue
                # Near-price filter (optional).
                if near_query is not None and abs(float(level.price) - float(near_query)) > radius:
                    continue
                found.append((level, snap))
        # Deterministic: closest to near_price first (or price desc if no near_price).
        if near_query is not None:
            found.sort(key=lambda pair: abs(float(pair[0].price) - float(near_query)))
        else:
            found.sort(key=lambda pair: (-float(pair[0].price), pair[0].level_key))
        matches = [emit(level, snap) for level, snap in found]

    # No resolution key: the query is just the market header.

    return LookupResult(
        query=query,
        current_price=header_price,
        atr=header_atr,
        price_basis=header_basis,
        matches=matches,
    )
