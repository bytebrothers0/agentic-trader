"""
agentic/feed.py — the read-only bridge from the indicator suite to the agent.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md (phase 1).

This is the one module in ``agentic`` allowed to reach into the running system,
and it reaches **read-only**: it calls the indicator layer and copies the level
payload into agent-native records. It never mutates a detector, a setting, or a
rendered series. Detector output is never cached in the store — it is recomputed
on every read — so a bug in the agent can never change a level's price.

Why a provider seam
-------------------
:class:`Feed` takes a ``provider`` callable returning the ``/api/indicators``
payload for ``(symbol, timeframe, families, bars)``. The default provider lazily
imports ``server.get_indicators`` (the live MT5 path) so importing this module
stays cheap and the pure core stays testable. Tests inject a fake provider of
plain dicts, which is why every normaliser here takes a mapping, never a detector
object.

Level identity
--------------
A level is keyed by ``family:timeframe:direction:price:born_at`` (see
:func:`agentic.models.make_level_key`). ``born_at`` is the formation bar, so the
same level recomputed after a timeframe change resolves to the same key — which
is what lets a pin survive a view change.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from agentic.models import LevelStatus, Serde, make_level_key, validate_timeframe

# --------------------------------------------------------------------------- #
# Family vocabulary
# --------------------------------------------------------------------------- #

CRT = "crt"
TS = "ts"
BOS = "bos"
FVG = "fvg"
IFVG = "ifvg"
OB = "ob"
LIQUIDITY = "liquidity"
SR = "sr"
QM = "qm"
IDM = "idm"
TRENDLINE = "trendline"
OCL = "ocl"
APEX = "apex"

#: Every family the indicator suite can emit, in agent vocabulary.
KNOWN_FAMILIES: tuple = (
    CRT, TS, BOS, FVG, IFVG, OB, LIQUIDITY, SR, QM, IDM, TRENDLINE, OCL, APEX,
)

#: server ``category`` -> agent family (only where the two differ).
_CATEGORY_ALIASES: Dict[str, str] = {"liq": LIQUIDITY, "tl": TRENDLINE}

#: agent family -> the ``/api/indicators`` ``show_*`` query key.
FAMILY_QUERY: Dict[str, str] = {
    CRT: "show_crt",
    TS: "show_ts",
    BOS: "show_bos",
    FVG: "show_fvg",
    IFVG: "show_ifvg",
    OB: "show_ob",
    LIQUIDITY: "show_liq",
    SR: "show_sr",
    QM: "show_qm",
    IDM: "show_idm",
    TRENDLINE: "show_tl",
    OCL: "show_ocl",
    APEX: "show_apex",
}


class InsufficientHistory(ValueError):
    """The provider does not hold the window that was requested.

    The default (live) providers translate the indicator/candles endpoint's
    HTTP ``422`` into this — the pure-core twin of
    :class:`data.mt5_loader.InsufficientHistory`. It is a ``ValueError`` so the
    tool layer can turn it into a fixable refusal (``reduce offset``) rather than
    an ``internal_error``. Defined here — not imported — so :mod:`agentic.feed`
    stays importable without ``server`` or MT5.
    """


# --------------------------------------------------------------------------- #
# Status mapping
# --------------------------------------------------------------------------- #

#: ``end_kind`` is the authoritative life-cycle marker (it is set from the
#: detector's own end index); ``state`` is the fallback when it is absent.
_STATUS_BY_END_KIND: Dict[str, LevelStatus] = {
    "active": LevelStatus.LIVE,
    "swept": LevelStatus.SWEPT,
    "broken": LevelStatus.BROKEN,
    "invalidated": LevelStatus.BROKEN,
    "distributed": LevelStatus.FILLED,
    "taken": LevelStatus.FILLED,
    "mitigated": LevelStatus.FILLED,
    "filled": LevelStatus.FILLED,
}
_STATUS_BY_STATE: Dict[str, LevelStatus] = {
    "MANIPULATED": LevelStatus.LIVE,
    "FRESH": LevelStatus.LIVE,
    "SWEPT": LevelStatus.SWEPT,
    "UNFRESH": LevelStatus.FILLED,
    "BROKEN": LevelStatus.BROKEN,
    "INVALIDATED": LevelStatus.BROKEN,
    "DISTRIBUTED": LevelStatus.FILLED,
    "TAKEN": LevelStatus.FILLED,
    "FILLED": LevelStatus.FILLED,
}

#: Family-specific payload fields worth carrying onto the record verbatim.
#: ``start_time`` is family-specific in meaning — TS: the anchor (range)
#: candle; CRT: the manipulation candle — and the renderer needs the TS one
#: to draw the ray from the anchor instead of the sweep bar.
_ATTR_KEYS: tuple = (
    "variant",
    "inside_bars",
    "start_time",
    "sweep_amount",
    "range_high",
    "range_low",
    "target",
    "box_top",
    "box_bottom",
    "box_high",
    "box_low",
    "state",
    "end_kind",
    "rule",
    "is_external",
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _dir_from_type(type_field: Any) -> str:
    text = str(type_field or "").upper()
    if "BULLISH" in text or "BULL " in text:
        return "bullish"
    if "BEARISH" in text or "BEAR " in text:
        return "bearish"
    return "neutral"


def _bos_kind(type_field: Any) -> tuple:
    """Split a BOS payload ``type`` into ``(kind, internal)``.

    The detector emits uppercase tokens (``indicators/bos_detector.py``):
    ``BOS`` / ``CHOCH``, prefixed with ``I-`` for the internal (I-BOS/I-CHOCH)
    layer. The payload formats them as ``f"{kind} ({direction})"``. Comparison is
    case-insensitive on the leading token, after stripping the ``I-`` prefix.
    """
    text = str(type_field or "").strip().upper()
    internal = text.startswith("I-")
    if internal:
        text = text[2:]
    return ("CHoCH" if text.startswith("CHOCH") else "BOS"), internal


def _to_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _unix_of(value: Any) -> Optional[int]:
    """Coerce a bar timestamp to unix seconds.

    Accepts unix seconds, an aware/naive :class:`datetime` (naive is read as
    UTC), or an ISO-8601 string. Returns ``None`` when nothing sensible parses.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _band(level: Mapping[str, Any]) -> tuple:
    """The two prices bounding the level, when it is a zone or a range.

    CRT carries its anchor range (``range_low``/``range_high``); FVG/IFVG/OB
    carry a box; QM/OCL carry ``box_low``/``box_high``.
    """
    for lo_key, hi_key in (
        ("box_bottom", "box_top"),
        ("box_low", "box_high"),
        ("range_low", "range_high"),
    ):
        lo, hi = level.get(lo_key), level.get(hi_key)
        if lo is not None and hi is not None:
            return float(lo), float(hi)
    return None, None


def family_of(level: Mapping[str, Any]) -> str:
    raw = str(level.get("category", "")).lower()
    return _CATEGORY_ALIASES.get(raw, raw)


@dataclass
class LevelRecord(Serde):
    """One level, normalised for the agent.

    ``price`` is the level itself (CRT: the swept boundary — the drawn ray);
    ``band_low``/``band_high`` are the zone or range it belongs to. ``attrs``
    carries family-specific extras untouched from the payload.
    """

    level_key: str = ""
    family: str = ""
    timeframe: str = ""
    direction: str = "neutral"
    price: float = 0.0
    status: LevelStatus = LevelStatus.LIVE
    formed_at: Optional[datetime] = None
    changed_at: Optional[datetime] = None
    band_low: Optional[float] = None
    band_high: Optional[float] = None
    target: Optional[float] = None
    origin: str = ""
    attrs: Dict[str, Any] = field(default_factory=dict)

    # -- convenience readers -------------------------------------------------

    @property
    def is_live(self) -> bool:
        return self.status is LevelStatus.LIVE

    @property
    def inside_bars(self) -> int:
        try:
            return int(self.attrs.get("inside_bars", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def variant(self) -> str:
        return str(self.attrs.get("variant", "") or "")

    @property
    def state(self) -> str:
        return str(self.attrs.get("state", "") or "")

    def band(self) -> Optional[tuple]:
        if self.band_low is None or self.band_high is None:
            return None
        return self.band_low, self.band_high


@dataclass
class FeedSnapshot(Serde):
    """A point-in-time perception: one symbol, one timeframe, its levels."""

    symbol: str = ""
    timeframe: str = ""
    current_price: float = 0.0
    atr: float = 0.0
    #: Whether ``current_price`` is the live price or the last close of a past
    #: window (``"live"`` / ``"window_end"``). Set from the payload's
    #: ``price_basis``; the lookup echoes it so a historical price can never be
    #: mistaken for live.
    price_basis: str = "live"
    levels: List[LevelRecord] = field(default_factory=list)

    # -- queries -------------------------------------------------------------

    def by_key(self, level_key: str) -> Optional[LevelRecord]:
        for lvl in self.levels:
            if lvl.level_key == level_key:
                return lvl
        return None

    def family(self, family: str) -> List[LevelRecord]:
        return [lvl for lvl in self.levels if lvl.family == family]

    def of_direction(self, direction: str) -> List[LevelRecord]:
        return [lvl for lvl in self.levels if lvl.direction == direction]

    def live(self, family: Optional[str] = None) -> List[LevelRecord]:
        return [
            lvl
            for lvl in self.levels
            if lvl.status is LevelStatus.LIVE and (family is None or lvl.family == family)
        ]

    def newest(self, levels: Optional[Sequence[LevelRecord]] = None) -> Optional[LevelRecord]:
        pool = list(self.levels if levels is None else levels)
        if not pool:
            return None
        return max(pool, key=lambda lvl: lvl.formed_at or _EPOCH)

    def near_price(self, price: float, radius: float) -> List[LevelRecord]:
        """Levels whose price sits within ``radius`` of ``price``, nearest first."""
        hits = [lvl for lvl in self.levels if abs(lvl.price - price) <= radius]
        return sorted(hits, key=lambda lvl: abs(lvl.price - price))


@dataclass
class Bars(Serde):
    """An OHLC series for one ``(symbol, timeframe)`` — the evaluator's clock.

    The ``/api/candles`` payload carries ``volume`` too, but the evaluator has no
    use for it, so it is dropped here. ``times`` are unix seconds, ascending
    (``parse_candles`` sorts them), and every price series is the same length as
    ``times``. JSON round-trips through :class:`Serde`, which is what lets a
    snapshot-and-bars pair be persisted or replayed.
    """

    symbol: str = ""
    timeframe: str = ""
    times: List[int] = field(default_factory=list)
    open: List[float] = field(default_factory=list)
    high: List[float] = field(default_factory=list)
    low: List[float] = field(default_factory=list)
    close: List[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.times)

    def index_at_or_before(self, ts: Any) -> int:
        """Index of the last bar whose time is ``<= ts``; ``-1`` when there is none.

        ``ts`` may be unix seconds, a :class:`datetime`, or an ISO string. The
        binary search assumes ``times`` is ascending, which :func:`parse_candles`
        guarantees.
        """
        target = _unix_of(ts)
        if target is None or not self.times:
            return -1
        lo, hi, found = 0, len(self.times) - 1, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if int(self.times[mid]) <= target:
                found = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return found


def parse_level(
    level: Mapping[str, Any],
    *,
    symbol: str = "",
    timeframe: str = "",
) -> LevelRecord:
    """Normalise one ``/api/indicators`` level dict into a :class:`LevelRecord`."""
    family = family_of(level)
    direction = _dir_from_type(level.get("type"))
    price = float(level.get("price", 0.0) or 0.0)
    formed_at = _to_dt(level.get("time"))
    changed_at = _to_dt(level.get("end_time"))
    band_low, band_high = _band(level)

    level_key = make_level_key(
        family,
        timeframe,
        direction,
        price,
        formed_at.isoformat() if formed_at else None,
    )

    attrs = {
        key: level[key]
        for key in _ATTR_KEYS
        if key in level and level[key] is not None
    }
    if family == BOS:
        # The evaluator must tell a BOS from a CHoCH, and internal from external;
        # the payload encodes both in the leading token of ``type``.
        kind, internal = _bos_kind(level.get("type"))
        attrs["kind"] = kind
        attrs["internal"] = internal

    return LevelRecord(
        level_key=level_key,
        family=family,
        timeframe=timeframe,
        direction=direction,
        price=price,
        status=status_of(level),
        formed_at=formed_at,
        changed_at=changed_at,
        band_low=band_low,
        band_high=band_high,
        target=float(level["target"]) if level.get("target") is not None else None,
        origin=str(level.get("desc", "") or ""),
        attrs=attrs,
    )


def status_of(level: Mapping[str, Any]) -> LevelStatus:
    """Map a payload level to a :class:`LevelStatus` (end_kind, then state)."""
    end_kind = str(level.get("end_kind", "") or "").lower()
    if end_kind in _STATUS_BY_END_KIND:
        return _STATUS_BY_END_KIND[end_kind]
    state = str(level.get("state", "") or "").upper()
    return _STATUS_BY_STATE.get(state, LevelStatus.LIVE)


#: The perception dial values (mirrored from ``agentic.models.STATUS_FILTERS``):
#: ``"all"`` keeps every life-cycle state, ``"live"`` keeps only fresh /
#: unmitigated / unbroken levels — the per-family phrase already encoded in
#: :class:`LevelStatus`.
FILTER_STATUS_VALUES = ("all", "live")


def filter_status(snapshot: "FeedSnapshot", status_filter: str) -> "FeedSnapshot":
    """A snapshot limited to the requested life-cycle states (post-parse, pure).

    ``"live"`` drops dead levels *before* the renderer's ray budget is spent, so
    a busy family's history never crowds out its fresh signal. Applied with
    ``dataclasses.replace`` — the parse itself stays untouched, and
    ``current_price``/``atr`` ride along unchanged. The watchdog deliberately
    does NOT use this: subscription evaluation needs state history for edge
    triggers.
    """
    value = str(status_filter or "all").lower()
    if value == "all":
        return snapshot
    if value != "live":
        raise ValueError("status_filter must be 'all' or 'live'")
    return replace(
        snapshot,
        levels=[rec for rec in snapshot.levels if rec.status is LevelStatus.LIVE],
    )


def parse_payload(
    payload: Mapping[str, Any],
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> FeedSnapshot:
    """Turn an ``/api/indicators`` payload into a :class:`FeedSnapshot`."""
    sym = str(payload.get("symbol") or symbol or "")
    tf = str(payload.get("timeframe") or timeframe or "")
    levels = [
        parse_level(level, symbol=sym, timeframe=tf)
        for level in (payload.get("levels") or [])
    ]
    return FeedSnapshot(
        symbol=sym,
        timeframe=tf,
        current_price=float(payload.get("current_price", 0.0) or 0.0),
        atr=float(payload.get("atr", 0.0) or 0.0),
        price_basis=str(payload.get("price_basis", "live") or "live"),
        levels=levels,
    )


def parse_candles(
    payload: Mapping[str, Any],
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> Bars:
    """Turn an ``/api/candles`` payload into a :class:`Bars`.

    The endpoint shape is ``{"symbol", "timeframe", "candles": [{time, open,
    high, low, close, volume}]}`` with ``time`` in unix seconds. ``volume`` is
    ignored (see :class:`Bars`). Rows missing a ``time`` are dropped and the rest
    are sorted ascending, so a ``Bars`` is always safe for
    :meth:`Bars.index_at_or_before`.
    """
    sym = str(payload.get("symbol") or symbol or "")
    tf = str(payload.get("timeframe") or timeframe or "")
    rows = sorted(
        (row for row in (payload.get("candles") or []) if row.get("time") is not None),
        key=lambda row: int(row["time"]),
    )
    return Bars(
        symbol=sym,
        timeframe=tf,
        times=[int(row["time"]) for row in rows],
        open=[float(row.get("open", 0.0) or 0.0) for row in rows],
        high=[float(row.get("high", 0.0) or 0.0) for row in rows],
        low=[float(row.get("low", 0.0) or 0.0) for row in rows],
        close=[float(row.get("close", 0.0) or 0.0) for row in rows],
    )


# --------------------------------------------------------------------------- #
# The feed
# --------------------------------------------------------------------------- #

#: ``provider(symbol=, timeframe=, families=, bars=) -> payload dict``.
Provider = Callable[..., Mapping[str, Any]]


class Feed:
    """Read-only access to the indicator suite for one or more timeframes.

    Two independent seams: ``provider`` serves levels (``/api/indicators``) and
    ``candles_provider`` serves OHLC bars (``/api/candles``). Either can be
    injected; both default to the lazy live bridge, so ``Feed(provider=...)``
    keeps working exactly as before.
    """

    def __init__(
        self,
        provider: Optional[Provider] = None,
        candles_provider: Optional[Provider] = None,
    ):
        self._provider = provider or default_provider()
        self._candles_provider = candles_provider or default_candles_provider()

    def snapshot(
        self,
        symbol: str,
        timeframe: str,
        *,
        families: Optional[Sequence[str]] = None,
        bars: int = 300,
        offset: int = 0,
        status_filter: str = "all",
        **provider_kwargs: Any,
    ) -> FeedSnapshot:
        tf = validate_timeframe(str(timeframe))
        payload = self._provider(
            symbol=symbol,
            timeframe=tf,
            families=list(families) if families is not None else None,
            bars=int(bars),
            offset=int(offset),
            **provider_kwargs,
        )
        if not isinstance(payload, Mapping):
            raise TypeError(f"provider returned {type(payload).__name__}, expected a mapping")
        snapshot = parse_payload(payload, symbol=symbol, timeframe=tf)
        return filter_status(snapshot, status_filter)

    def snapshots(
        self,
        symbol: str,
        timeframes: Sequence[str],
        *,
        families: Optional[Sequence[str]] = None,
        bars: int = 300,
        offset: int = 0,
        **provider_kwargs: Any,
    ) -> Dict[str, FeedSnapshot]:
        """One snapshot per timeframe, keyed by the validated timeframe."""
        out: Dict[str, FeedSnapshot] = {}
        for tf in timeframes:
            out[validate_timeframe(str(tf))] = self.snapshot(
                symbol, tf, families=families, bars=bars, offset=offset, **provider_kwargs
            )
        return out

    def level(self, symbol: str, timeframe: str, level_key: str, **kw: Any) -> Optional[LevelRecord]:
        """Re-resolve a level by key (a pin surviving a recomputation)."""
        return self.snapshot(symbol, timeframe, **kw).by_key(level_key)

    def bars(
        self,
        symbol: str,
        timeframe: str,
        *,
        bars: int = 300,
        offset: int = 0,
        **provider_kwargs: Any,
    ) -> Bars:
        """OHLC bars for ``(symbol, timeframe)`` — the evaluator's clock."""
        tf = validate_timeframe(str(timeframe))
        payload = self._candles_provider(
            symbol=symbol,
            timeframe=tf,
            bars=int(bars),
            offset=int(offset),
            **provider_kwargs,
        )
        if not isinstance(payload, Mapping):
            raise TypeError(f"candles provider returned {type(payload).__name__}, expected a mapping")
        return parse_candles(payload, symbol=symbol, timeframe=tf)


def _show_flags(families: Optional[Sequence[str]]) -> Dict[str, bool]:
    """Translate a wanted family set into the endpoint's ``show_*`` flags."""
    flags = {query: False for query in FAMILY_QUERY.values()}
    if families is None:
        return {query: True for query in FAMILY_QUERY.values()}
    for family in families:
        query = FAMILY_QUERY.get(str(family))
        if query:
            flags[query] = True
    return flags


def default_provider() -> Provider:
    """The live provider: the running indicator endpoint, imported lazily.

    The import lives inside the closure so importing :mod:`agentic.feed` never
    drags in FastAPI or the MT5 loader — the state-check test asserts this.
    """

    def _provider(
        *,
        symbol: str,
        timeframe: str,
        families: Optional[Sequence[str]] = None,
        bars: int = 300,
        offset: int = 0,
        **_: Any,
    ) -> Mapping[str, Any]:
        from server import get_indicators  # lazy, deliberate (see module docstring)

        try:
            return get_indicators(
                symbol=symbol,
                timeframe=timeframe,
                bars=bars,
                offset=offset,
                **_show_flags(families),
            )
        except Exception as exc:  # noqa: BLE001 — translate the endpoint's 422 only
            if getattr(exc, "status_code", None) == 422:
                raise InsufficientHistory(
                    getattr(exc, "detail", None) or "insufficient history"
                ) from exc
            raise

    return _provider


def default_candles_provider() -> Provider:
    """The live candles provider: ``/api/candles``, imported lazily.

    Same discipline as :func:`default_provider` — the ``server`` import lives
    inside the closure so importing :mod:`agentic.feed` never drags in FastAPI or
    the MT5 loader.
    """

    def _provider(
        *,
        symbol: str,
        timeframe: str,
        bars: int = 300,
        offset: int = 0,
        **_: Any,
    ) -> Mapping[str, Any]:
        from server import get_candles  # lazy, deliberate (see module docstring)

        try:
            return get_candles(symbol=symbol, timeframe=timeframe, bars=bars, offset=offset)
        except Exception as exc:  # noqa: BLE001 — translate the endpoint's 422 only
            if getattr(exc, "status_code", None) == 422:
                raise InsufficientHistory(
                    getattr(exc, "detail", None) or "insufficient history"
                ) from exc
            raise

    return _provider
