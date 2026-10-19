"""
backtest/crt_scan.py — find *classic* 3-candle CRT setups that resolved, and score
them the way a trader would.

"Worked well" is given a concrete, checkable meaning here: the setup's own logic
priced as a naive trade. Entry is the manipulation candle's close (the decision
instant), the stop sits just beyond the sweep wick, and the target is the far CRT
boundary. A candidate's score is the R:R that trade would have carried.

The detector is the production one (``indicators/crt_detector.py``), run with the
production settings, so nothing about *what the chart showed* differs from live.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from indicators.crt_detector import (
    CRTDetector,
    CRTDirection,
    CRTLevel,
    CRTState,
    CRTVariant,
)

from backtest.historical import tf_seconds

#: How far beyond the sweep wick the naive stop sits, in ATR(14).
STOP_BUFFER_ATR = 0.25


def crt_settings() -> Dict[str, Any]:
    """The CRT detector parameters the live endpoint uses (``config.settings``)."""
    from config import settings as S

    return {
        "min_range_atr": S.CRT_MIN_RANGE_ATR,
        "min_sweep_atr": S.CRT_MIN_SWEEP_ATR,
        "min_close_back_atr": S.CRT_MIN_CLOSE_BACK_ATR,
        "max_inside_bars": S.CRT_MAX_INSIDE_BARS,
        "require_directional_anchor": S.CRT_REQUIRE_DIRECTIONAL_ANCHOR,
        "max_per_side": S.CRT_MAX_PER_SIDE,
        "max_live_per_side": S.CRT_MAX_LIVE_PER_SIDE,
        "atr_period": S.CRT_ATR_PERIOD,
    }


def atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR, the same smoothing the endpoint reports as ``atr``."""
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean()


@dataclass
class CrtCandidate:
    """One resolved classic CRT, priced as a naive trade."""

    timeframe: str = ""
    direction: str = ""
    variant: str = ""
    state: str = ""
    crh: float = 0.0
    crl: float = 0.0
    swept_level: float = 0.0
    target_level: float = 0.0
    anchor_index: int = 0
    manipulation_index: int = 0
    distribution_index: Optional[int] = None
    anchor_time: str = ""
    manipulation_time: str = ""
    distribution_time: Optional[str] = None
    decision_time: str = ""
    inside_bars: int = 0
    sweep_amount: float = 0.0
    range_size: float = 0.0
    range_atr: float = 0.0
    bars_to_target: Optional[int] = None
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    risk: float = 0.0
    reward: float = 0.0
    rr: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def describe(self) -> str:
        return (
            f"[{self.timeframe}] classic {self.direction.upper()} CRT "
            f"{self.anchor_time} -> manip {self.manipulation_time} "
            f"(swept {self.swept_level:.3f}, target {self.target_level:.3f}); "
            f"resolved at {self.distribution_time} in {self.bars_to_target} bars; "
            f"naive trade {self.entry:.3f}/{self.stop:.3f}/{self.target:.3f} "
            f"R:R {self.rr:.2f}"
        )


def _price(lvl: CRTLevel, df: pd.DataFrame, atr: pd.Series) -> Dict[str, float]:
    """Price one CRT as a naive trade from the manipulation close."""
    j = int(lvl.manipulation_index)
    entry = float(df["close"].iloc[j])
    buffer = STOP_BUFFER_ATR * float(atr.iloc[j] or 0.0)
    if lvl.direction is CRTDirection.BULLISH:
        stop = float(df["low"].iloc[j]) - buffer
        target = float(lvl.crh)
        risk = entry - stop
        reward = target - entry
    else:
        stop = float(df["high"].iloc[j]) + buffer
        target = float(lvl.crl)
        risk = stop - entry
        reward = entry - target
    rr = (reward / risk) if risk > 0 else 0.0
    return {
        "entry": round(entry, 3),
        "stop": round(stop, 3),
        "target": round(target, 3),
        "risk": round(risk, 3),
        "reward": round(reward, 3),
        "rr": round(rr, 3),
    }


def candidate_from(lvl: CRTLevel, df: pd.DataFrame, timeframe: str, atr: pd.Series) -> CrtCandidate:
    """Normalise one ``CRTLevel`` into a :class:`CrtCandidate`."""
    j = int(lvl.manipulation_index)
    decision = df.index[j] + pd.Timedelta(seconds=tf_seconds(timeframe))
    priced = _price(lvl, df, atr)
    return CrtCandidate(
        timeframe=str(timeframe).upper(),
        direction=lvl.direction.value,
        variant=lvl.variant.value,
        state=lvl.state.value,
        crh=round(float(lvl.crh), 3),
        crl=round(float(lvl.crl), 3),
        swept_level=round(float(lvl.swept_level), 3),
        target_level=round(float(lvl.target_level), 3),
        anchor_index=int(lvl.anchor_index),
        manipulation_index=j,
        distribution_index=(int(lvl.distribution_index) if lvl.distribution_index is not None else None),
        anchor_time=pd.Timestamp(lvl.anchor_time).isoformat(),
        manipulation_time=pd.Timestamp(lvl.manipulation_time).isoformat(),
        distribution_time=(
            pd.Timestamp(lvl.distribution_time).isoformat()
            if lvl.distribution_time is not None
            else None
        ),
        decision_time=pd.Timestamp(decision).isoformat(),
        inside_bars=int(lvl.inside_count),
        sweep_amount=round(float(lvl.sweep_amount), 3),
        range_size=round(float(lvl.range_size), 3),
        range_atr=round(float(lvl.range_atr), 3),
        bars_to_target=(
            int(lvl.distribution_index - lvl.manipulation_index)
            if lvl.distribution_index is not None
            else None
        ),
        **priced,
    )


def scan_classic_crts(
    df: pd.DataFrame,
    timeframe: str,
    *,
    since: Optional[pd.Timestamp] = None,
    min_rr: float = 1.0,
    only_distributed: bool = True,
    top: int = 5,
) -> List[CrtCandidate]:
    """Classic CRT setups, best R:R first.

    ``since`` keeps only setups whose decision falls at/after it. ``min_rr`` drops
    setups whose naive trade carried less reward than risk. With
    ``only_distributed`` (the default) only setups whose target was **reached**
    survive — the "it worked" half of the request; pass ``False`` to also see the
    ones that invalidated, for contrast.
    """
    settings = crt_settings()
    detector = CRTDetector(df, **settings)
    atr = atr_series(df, settings["atr_period"])
    since_ts = pd.Timestamp(since) if since is not None else None
    if since_ts is not None and since_ts.tzinfo is None:
        since_ts = since_ts.tz_localize("UTC")

    out: List[CrtCandidate] = []
    for lvl in detector.detect_all():
        if lvl.variant is not CRTVariant.CLASSIC:
            continue
        if only_distributed and lvl.state is not CRTState.DISTRIBUTED:
            continue
        cand = candidate_from(lvl, df, timeframe, atr)
        if since_ts is not None and pd.Timestamp(cand.decision_time) < since_ts:
            continue
        if cand.risk <= 0 or cand.rr < float(min_rr):
            continue
        out.append(cand)

    out.sort(key=lambda c: (c.rr, c.range_atr), reverse=True)
    return out[: int(top)] if top else out
