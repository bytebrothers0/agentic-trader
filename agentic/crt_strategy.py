"""
agentic/crt_strategy.py — the top-down Candle Range Theory playbook.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md.

The model, as researched (CandelaCharts framework, crttrading.com, the ICT-derived
community material):

    HTF sets direction  (D1 / W1 / MN1)
        The higher-timeframe **CRT model is the container you trade inside**. A
        range candle defines CRH/CRL; a later candle sweeps one boundary and
        closes back inside; the projection is toward the **opposite** boundary.
        That direction is the bias, and the opposite boundary is the target.

    LTF builds the plan  (H4 / H1)
        Drop down to validate the bias and sketch structure: a Change in State
        of Delivery (here: a BOS in the bias direction) and points of interest
        (here: a fresh FVG or OB) that align with the bias.

    LTF executes         (M15 / M5 / M1)
        Refine the entry at the point of interest once all timeframes agree;
        place the stop beyond the protected swing / the zone, and project to the
        HTF CRT boundary.

This module is **pure**: it depends only on :mod:`agentic.feed` records and the
standard library, imports nothing from the running system, and is deterministic.
It generates a *plan* (propose-only), never an order. The agent loop that feeds it
an image and calls tools lands in a later phase; policy is separate from
perception, so the playbook can be tested against a fake feed with no server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from agentic.feed import (
    BOS,
    CRT,
    FVG,
    LIQUIDITY,
    OB,
    TS,
    Feed,
    FeedSnapshot,
    LevelRecord,
)
from agentic.models import LevelStatus, Serde

# --------------------------------------------------------------------------- #
# The top-down ladder
# --------------------------------------------------------------------------- #

#: Bias timeframes, highest first. A live monthly CRT outranks a live weekly one.
HTF_BIAS_TIMEFRAMES: tuple = ("MN1", "W1", "D1")

#: Execution/refinement timeframes, coarsest first.
LTF_EXECUTION_TIMEFRAMES: tuple = ("H4", "H1", "M15", "M5", "M1")

#: What the CRT strategy needs to be visible to reason at all. The feed requests
#: exactly this set; the agent's view defaults to it.
REQUIRED_FAMILIES: tuple = (CRT, BOS, FVG, OB, LIQUIDITY, TS)

#: Secondary families that sharpen a read but are not required.
OPTIONAL_FAMILIES: tuple = ("ifvg", "sr")

_EPOCH = datetime(1970, 1, 1)


def _newest(levels: Sequence[LevelRecord]) -> Optional[LevelRecord]:
    if not levels:
        return None
    return max(levels, key=lambda lvl: lvl.formed_at or _EPOCH)


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

@dataclass
class HtfBias(Serde):
    """The higher-timeframe CRT that defines direction and target."""

    timeframe: str = ""
    direction: str = "neutral"
    level_key: str = ""
    range_high: float = 0.0
    range_low: float = 0.0
    target: float = 0.0
    equilibrium: float = 0.0
    status: LevelStatus = LevelStatus.LIVE
    variant: str = ""
    inside_bars: int = 0

    @property
    def is_live(self) -> bool:
        """True while the manipulation stands and the target is unmet."""
        return self.status is LevelStatus.LIVE


@dataclass
class Confirmation(Serde):
    """The lower-timeframe proof that the bias is being delivered."""

    timeframe: str = ""
    kind: str = ""  # "bos" | "fvg" | "ob" | "liquidity" | "ts"
    direction: str = "neutral"
    level_key: str = ""
    price: float = 0.0
    band_low: Optional[float] = None
    band_high: Optional[float] = None
    status: LevelStatus = LevelStatus.LIVE


@dataclass
class CrtPlan(Serde):
    """A propose-only trade plan for one top-down CRT setup."""

    direction: str = "neutral"
    htf_timeframe: str = ""
    htf_level_key: str = ""
    htf_target: float = 0.0
    ltf_timeframe: str = ""
    confirmation: str = ""
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    partial: Optional[float] = None
    risk: float = 0.0
    reward: float = 0.0
    rr: float = 0.0
    invalidation: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    provenance: List[str] = field(default_factory=list)


@dataclass
class CrtAnalysis(Serde):
    """The whole read: bias, confirmation, plan, and why (or why not)."""

    symbol: str = ""
    ltf_timeframe: str = ""
    bias: Optional[HtfBias] = None
    confirmation: Optional[Confirmation] = None
    plan: Optional[CrtPlan] = None
    reason: str = ""


# --------------------------------------------------------------------------- #
# Bias
# --------------------------------------------------------------------------- #

def _crt_levels(snapshot: FeedSnapshot) -> List[LevelRecord]:
    return snapshot.family(CRT)


def _bias_from(record: LevelRecord, timeframe: str) -> HtfBias:
    band = record.band()
    low, high = band if band else (0.0, 0.0)
    if record.direction == "bullish":
        target = record.target if record.target is not None else high
    else:
        target = record.target if record.target is not None else low
    return HtfBias(
        timeframe=timeframe,
        direction=record.direction,
        level_key=record.level_key,
        range_high=high,
        range_low=low,
        target=float(target or 0.0),
        equilibrium=(high + low) / 2.0,
        status=record.status,
        variant=record.variant,
        inside_bars=record.inside_bars,
    )


def derive_htf_bias(
    snapshots: Dict[str, FeedSnapshot],
    timeframes: Sequence[str] = HTF_BIAS_TIMEFRAMES,
) -> Optional[HtfBias]:
    """Pick the bias from the highest-timeframe live CRT.

    A CRT is "live" when the manipulation stands and the target is unmet
    (``MANIPULATED``). We prefer the highest timeframe that has one; if no
    timeframe has a live CRT we fall back to the newest CRT overall, so a
    distributed-at-close read still yields context rather than nothing.
    """
    fallback: Optional[HtfBias] = None
    for tf in timeframes:
        snapshot = snapshots.get(tf)
        if snapshot is None:
            continue
        crts = _crt_levels(snapshot)
        if not crts:
            continue
        live = [c for c in crts if c.status is LevelStatus.LIVE]
        chosen = _newest(live) if live else _newest(crts)
        if chosen is None:
            continue
        bias = _bias_from(chosen, tf)
        if live:
            return bias
        if fallback is None:
            fallback = bias
    return fallback


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #

def _confirmation_from(record: LevelRecord, timeframe: str) -> Confirmation:
    return Confirmation(
        timeframe=timeframe,
        kind=record.family,
        direction=record.direction,
        level_key=record.level_key,
        price=record.price,
        band_low=record.band_low,
        band_high=record.band_high,
        status=record.status,
    )


def find_confirmation(ltf: FeedSnapshot, bias: HtfBias) -> Optional[Confirmation]:
    """The LTF proof that the HTF bias is being delivered.

    Priority: a structure shift (BOS) in the bias direction, then a fresh entry
    zone (FVG or OB) in the bias direction, then a liquidity raid / turtle soup
    on the bias side. The structure shift comes first because it is the Change in
    State of Delivery the playbook waits for; the zone is where the entry is
    refined.
    """
    want = bias.direction
    if want not in ("bullish", "bearish"):
        return None

    structures = [
        lvl for lvl in ltf.family(BOS) if lvl.direction == want
    ]
    structure = _newest(structures)
    if structure is not None:
        return _confirmation_from(structure, ltf.timeframe)

    zones = [
        lvl
        for lvl in ltf.family(FVG) + ltf.family(OB)
        if lvl.direction == want and lvl.status is LevelStatus.LIVE
    ]
    zone = _newest(zones)
    if zone is not None:
        return _confirmation_from(zone, ltf.timeframe)

    raids = [
        lvl
        for lvl in ltf.family(TS) + ltf.family(LIQUIDITY)
        if lvl.direction == want
    ]
    raid = _newest(raids)
    if raid is not None:
        return _confirmation_from(raid, ltf.timeframe)

    return None


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #

def _confidence(bias: HtfBias, conf: Confirmation) -> float:
    """A deterministic, conservative score — not a probability of profit."""
    score = 0.45
    if bias.is_live:
        score += 0.10
    if bias.variant == "inside_bar" or bias.inside_bars >= 1:
        score += 0.10
    if bias.inside_bars >= 2:
        score += 0.10
    if conf.kind == BOS:
        score += 0.05
    if conf.kind in (FVG, OB):
        score += 0.00  # a zone alone is location, not timing
    return round(min(max(score, 0.10), 0.90), 2)


def _entry_zone(
    ltf: FeedSnapshot,
    direction: str,
    ref_price: Optional[float] = None,
) -> Optional[LevelRecord]:
    """The nearest live FVG/OB on the bias side — the location and the risk unit.

    A long wants a discount zone at or below price; a short a premium zone at or
    above it. Zones on the wrong side are only used when nothing better exists.
    """
    zones = [
        lvl
        for lvl in ltf.family(FVG) + ltf.family(OB)
        if lvl.direction == direction
        and lvl.status is LevelStatus.LIVE
        and lvl.band_low is not None
        and lvl.band_high is not None
    ]
    if not zones:
        return None
    ref = ref_price or ltf.current_price or zones[0].price
    if direction == "bullish":
        pool = [z for z in zones if z.band_low <= ref]
    else:
        pool = [z for z in zones if z.band_high >= ref]
    return min(pool or zones, key=lambda z: abs(z.price - ref))


def _ladder_target(
    bias: HtfBias,
    candidates: Optional[Sequence[float]],
    entry: float,
    long: bool,
) -> float:
    """The nearest HTF boundary beyond entry, else the bias CRT's own target."""
    target = float(bias.target)
    if candidates:
        beyond = [
            float(t) for t in candidates
            if t is not None and ((t > entry) if long else (t < entry))
        ]
        if beyond:
            target = min(beyond) if long else max(beyond)
    return target


def build_plan(
    bias: HtfBias,
    conf: Confirmation,
    ltf: FeedSnapshot,
    *,
    current_price: Optional[float] = None,
    atr: float = 0.0,
    target_candidates: Optional[Sequence[float]] = None,
) -> CrtPlan:
    """Turn a bias + confirmation into an entry/stop/target plan.

    The structure shift is the *timing*; the aligned entry zone (FVG/OB) is the
    *location* and the risk unit, so entry sits at the zone and the stop beyond
    it. The target is the nearest HTF CRT boundary beyond entry (the draw-on-
    liquidity ladder), falling back to the bias CRT's own far boundary. The stop
    is padded by volatility — ATR when the feed supplies it, otherwise a slice of
    the HTF range — so it is never degenerate and the R:R is always meaningful.
    """
    long = bias.direction == "bullish"

    zone = _entry_zone(ltf, bias.direction, current_price)
    if zone is not None:
        entry = float(zone.price)
        risk_ref = zone.band_low if long else zone.band_high
    elif conf.band_low is not None and conf.band_high is not None:
        entry = float(conf.price)
        risk_ref = conf.band_low if long else conf.band_high
    else:
        entry = float(conf.price)
        risk_ref = entry

    span = abs(bias.range_high - bias.range_low)
    if atr and atr > 0:
        buffer = 0.25 * atr
    elif span > 0:
        buffer = 0.05 * span
    else:
        buffer = abs(entry) * 0.002 or 0.01
    stop = risk_ref - buffer if long else risk_ref + buffer

    target = _ladder_target(bias, target_candidates, entry, long)
    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    partial = round(bias.equilibrium, 3) if bias.equilibrium else None
    invalidation = (
        f"LTF close beyond {stop:.3f}, or invalidation of the {bias.timeframe} "
        f"CRT ({bias.level_key})"
    )
    where = f" at the {conf.timeframe} {zone.family} zone {zone.price:.3f}" if zone else ""
    reasoning = (
        f"{bias.timeframe} CRT is {bias.direction} "
        f"(range {bias.range_low:.3f}-{bias.range_high:.3f}, "
        f"target {bias.target:.3f}"
        + (f", {bias.inside_bars} inside bars" if bias.inside_bars else "")
        + f"). {conf.timeframe} confirms with a {conf.kind} "
        f"({conf.direction}) at {conf.price:.3f}{where}. Entry to the nearest HTF "
        f"boundary {target:.3f}, stop beyond the risk reference, partial at "
        f"equilibrium {bias.equilibrium:.3f}."
    )

    provenance = [bias.level_key, conf.level_key]
    if zone is not None:
        provenance.append(zone.level_key)

    return CrtPlan(
        direction=bias.direction,
        htf_timeframe=bias.timeframe,
        htf_level_key=bias.level_key,
        htf_target=float(bias.target),
        ltf_timeframe=conf.timeframe,
        confirmation=f"{conf.kind} {conf.direction} ({conf.level_key})",
        entry=round(entry, 3),
        stop=round(stop, 3),
        target=round(target, 3),
        partial=partial,
        risk=round(risk, 3),
        reward=round(reward, 3),
        rr=rr,
        invalidation=invalidation,
        confidence=_confidence(bias, conf),
        reasoning=reasoning,
        provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# Whole read
# --------------------------------------------------------------------------- #

def analyze(
    feed: Feed,
    symbol: str,
    *,
    ltf_timeframe: str = "H1",
    htf_timeframes: Sequence[str] = HTF_BIAS_TIMEFRAMES,
    bars: int = 300,
) -> CrtAnalysis:
    """Run the full top-down CRT read for one symbol.

    Fetches the HTF timeframes plus the execution timeframe from the read-only
    feed, derives the bias, looks for LTF confirmation, and builds a plan.
    """
    htf = list(htf_timeframes)
    wanted = htf + ([ltf_timeframe] if ltf_timeframe not in htf else [])
    snapshots: Dict[str, FeedSnapshot] = {}
    for tf in wanted:
        snapshots[tf] = feed.snapshot(symbol, tf, families=REQUIRED_FAMILIES, bars=bars)

    bias = derive_htf_bias({tf: snapshots[tf] for tf in htf})
    if bias is None:
        return CrtAnalysis(
            symbol=symbol,
            ltf_timeframe=ltf_timeframe,
            reason="no CRT at D1/W1/MN1 to anchor a bias",
        )

    ltf = snapshots[ltf_timeframe]
    conf = find_confirmation(ltf, bias)
    if conf is None:
        return CrtAnalysis(
            symbol=symbol,
            ltf_timeframe=ltf_timeframe,
            bias=bias,
            reason=f"bias {bias.direction} ({bias.timeframe}) awaiting LTF confirmation",
        )

    candidates: List[float] = []
    for tf in htf:
        for c in snapshots[tf].family(CRT):
            if c.direction == bias.direction and c.target is not None:
                candidates.append(float(c.target))

    plan = build_plan(
        bias,
        conf,
        ltf,
        current_price=ltf.current_price,
        atr=ltf.atr,
        target_candidates=candidates,
    )
    return CrtAnalysis(
        symbol=symbol,
        ltf_timeframe=ltf_timeframe,
        bias=bias,
        confirmation=conf,
        plan=plan,
        reason="plan ready",
    )
