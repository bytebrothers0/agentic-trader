"""The watchdog's language — the condition vocabulary (spec phase 2 schema).

This module is the *specification* of what can be watched; the evaluator lands in
phase 2. It exists now because the store validates against it: a watch that
cannot be evaluated deterministically cannot be created, so "watch for a good
long setup" is rejected at the door rather than silently never firing.

Conditions are **edge-triggered** (fire on ``false -> true``, never on every
evaluation while true) and **timeframe-scoped** where it makes sense, so a
``bos_forms`` on H1 is not re-evaluated on every M15 tick.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from agentic.models import validate_timeframe


class Condition(str, Enum):
    LEVEL_FORMS = "level_forms"
    LEVEL_TOUCHED = "level_touched"
    LEVEL_SWEPT = "level_swept"
    LEVEL_BROKEN = "level_broken"
    LEVEL_FILLED = "level_filled"
    LEVEL_ALIVE = "level_alive"
    BOS_FORMS = "bos_forms"
    CHOCH_FORMS = "choch_forms"
    IDM_SWEPT = "idm_swept"
    PRICE_CROSSES = "price_crosses"
    PRICE_ENTERS_ZONE = "price_enters_zone"
    RANGE_EXPANDS = "range_expands"
    SESSION_OPENS = "session_opens"
    SESSION_CLOSES = "session_closes"
    TIME_REACHED = "time_reached"


class ConditionError(ValueError):
    """A condition that cannot be watched, with a machine-readable reason."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ConditionSpec:
    name: str
    required: Tuple[str, ...] = ()
    #: param groups; at least one group must be fully present
    any_of: Tuple[Tuple[str, ...], ...] = ()
    optional: Tuple[str, ...] = ()
    timeframe_scoped: bool = True
    description: str = ""


#: A level can be referenced either by its stable key or by a family + price.
LEVEL_REF_ANY: Tuple[Tuple[str, ...], ...] = (("level_key",), ("family", "price"))

SESSIONS = ("asia", "london", "ny")
DIRECTIONS = ("bullish", "bearish")
RANGE_REFERENCES = ("ADR", "ATR")
#: CRT variants (see ``indicators/crt_detector.py``): the strict 3-candle form,
#: or the accumulation that nests inside bars inside the anchor.
CRT_VARIANTS = ("classic", "inside_bar")

CONDITION_SPECS: Dict[str, ConditionSpec] = {
    Condition.LEVEL_FORMS.value: ConditionSpec(
        name="level_forms",
        required=("family",),
        optional=("direction", "min_size_atr", "timeframe", "variant", "min_inside_bars"),
        description="a new level of the family appears (for family 'crt': a CRT sweep forms)",
    ),
    Condition.LEVEL_TOUCHED.value: ConditionSpec(
        name="level_touched",
        any_of=LEVEL_REF_ANY,
        optional=("timeframe",),
        description="price reaches the level's band",
    ),
    Condition.LEVEL_SWEPT.value: ConditionSpec(
        name="level_swept",
        any_of=LEVEL_REF_ANY,
        optional=("timeframe",),
        description="the level's freshness tracker marks it swept",
    ),
    Condition.LEVEL_BROKEN.value: ConditionSpec(
        name="level_broken",
        any_of=LEVEL_REF_ANY,
        optional=("timeframe",),
        description="body close through the level",
    ),
    Condition.LEVEL_FILLED.value: ConditionSpec(
        name="level_filled",
        required=("level_key",),
        optional=("timeframe",),
        description="an FVG/OB is mitigated",
    ),
    Condition.LEVEL_ALIVE.value: ConditionSpec(
        name="level_alive",
        required=("level_key",),
        optional=("timeframe",),
        description="internal — a pin's own condition",
    ),
    Condition.BOS_FORMS.value: ConditionSpec(
        name="bos_forms",
        optional=("timeframe", "direction", "internal"),
        description="a BOS prints",
    ),
    Condition.CHOCH_FORMS.value: ConditionSpec(
        name="choch_forms",
        optional=("timeframe", "direction", "internal"),
        description="a CHoCH prints",
    ),
    Condition.IDM_SWEPT.value: ConditionSpec(
        name="idm_swept",
        optional=("timeframe", "rule"),
        description="an IDM is taken",
    ),
    Condition.PRICE_CROSSES.value: ConditionSpec(
        name="price_crosses",
        required=("price",),
        description="close crosses an absolute price",
    ),
    Condition.PRICE_ENTERS_ZONE.value: ConditionSpec(
        name="price_enters_zone",
        required=("low", "high"),
        description="price enters a band",
    ),
    Condition.RANGE_EXPANDS.value: ConditionSpec(
        name="range_expands",
        required=("multiple",),
        optional=("reference", "timeframe"),
        description="session range exceeds multiple x reference",
    ),
    Condition.SESSION_OPENS.value: ConditionSpec(
        name="session_opens",
        required=("session",),
        timeframe_scoped=False,
        description="a session boundary opens",
    ),
    Condition.SESSION_CLOSES.value: ConditionSpec(
        name="session_closes",
        required=("session",),
        timeframe_scoped=False,
        description="a session boundary closes",
    ),
    Condition.TIME_REACHED.value: ConditionSpec(
        name="time_reached",
        required=("at",),
        timeframe_scoped=False,
        description="the given timestamp passes",
    ),
}

ALL_CONDITIONS: Tuple[str, ...] = tuple(CONDITION_SPECS)

#: A pin needs an identity: either a resolved key, or a family + price to search for.
PIN_QUERY_ANY: Tuple[Tuple[str, ...], ...] = (("level_key",), ("family", "price"))
PIN_QUERY_OPTIONAL: Tuple[str, ...] = ("timeframe", "direction", "tolerance")


def spec_for(condition: Any) -> ConditionSpec:
    name = condition.value if isinstance(condition, Enum) else str(condition)
    spec = CONDITION_SPECS.get(name)
    if spec is None:
        raise ConditionError(
            "unknown_condition",
            f"unknown condition {name!r}; known: {', '.join(ALL_CONDITIONS)}",
        )
    return spec


def is_timeframe_scoped(condition: Any) -> bool:
    return spec_for(condition).timeframe_scoped


def _present(params: Dict[str, Any], key: str) -> bool:
    return key in params and params[key] is not None and params[key] != ""


def _check_any_of(spec: ConditionSpec, params: Dict[str, Any]) -> bool:
    return any(all(_present(params, k) for k in group) for group in spec.any_of)


def _coerce_float(params: Dict[str, Any], key: str) -> None:
    try:
        params[key] = float(params[key])
    except (TypeError, ValueError):
        raise ConditionError("invalid_param", f"{key} must be a number, got {params[key]!r}")


def validate(condition: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate a watch's parameters. Returns the (coerced) params.

    Raises :class:`ConditionError` with a machine-readable ``reason`` — the agent
    sees that reason and can fix its own request.
    """
    spec = spec_for(condition)
    params = dict(params or {})

    missing = [k for k in spec.required if not _present(params, k)]
    if missing:
        raise ConditionError("missing_params", f"{spec.name} requires: {', '.join(missing)}")
    if spec.any_of and not _check_any_of(spec, params):
        groups = " or ".join("+".join(g) for g in spec.any_of)
        raise ConditionError("missing_params", f"{spec.name} requires one of: {groups}")

    allowed = set(spec.required) | set(spec.optional) | {k for g in spec.any_of for k in g}
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ConditionError("unknown_params", f"{spec.name} got unsupported params: {', '.join(unknown)}")

    if _present(params, "timeframe"):
        try:
            validate_timeframe(str(params["timeframe"]))
        except ValueError as exc:
            raise ConditionError("invalid_timeframe", str(exc))

    name = spec.name
    if name == Condition.LEVEL_FORMS.value:
        params["family"] = str(params["family"])
        if _present(params, "direction") and params["direction"] not in DIRECTIONS:
            raise ConditionError("invalid_param", f"direction must be one of {DIRECTIONS}")
        if _present(params, "min_size_atr"):
            _coerce_float(params, "min_size_atr")
            if params["min_size_atr"] <= 0:
                raise ConditionError("invalid_param", "min_size_atr must be > 0")
        if _present(params, "variant"):
            variant = str(params["variant"]).lower()
            if variant not in CRT_VARIANTS:
                raise ConditionError("invalid_param", f"variant must be one of {CRT_VARIANTS}")
            params["variant"] = variant
        if _present(params, "min_inside_bars"):
            try:
                params["min_inside_bars"] = int(params["min_inside_bars"])
            except (TypeError, ValueError):
                raise ConditionError("invalid_param", "min_inside_bars must be an integer")
            if params["min_inside_bars"] < 0:
                raise ConditionError("invalid_param", "min_inside_bars must be >= 0")

    if name in (Condition.LEVEL_TOUCHED.value, Condition.LEVEL_SWEPT.value, Condition.LEVEL_BROKEN.value):
        if _present(params, "level_key"):
            params["level_key"] = str(params["level_key"])
        else:
            params["family"] = str(params["family"])
            _coerce_float(params, "price")

    if name in (Condition.LEVEL_FILLED.value, Condition.LEVEL_ALIVE.value):
        params["level_key"] = str(params["level_key"])

    if name in (Condition.BOS_FORMS.value, Condition.CHOCH_FORMS.value, Condition.IDM_SWEPT.value):
        if _present(params, "direction") and params["direction"] not in DIRECTIONS:
            raise ConditionError("invalid_param", f"direction must be one of {DIRECTIONS}")
        if _present(params, "internal"):
            params["internal"] = bool(params["internal"])
        if _present(params, "rule"):
            params["rule"] = str(params["rule"])

    if name == Condition.PRICE_CROSSES.value:
        _coerce_float(params, "price")

    if name == Condition.PRICE_ENTERS_ZONE.value:
        _coerce_float(params, "low")
        _coerce_float(params, "high")
        if params["low"] > params["high"]:
            raise ConditionError("invalid_param", "low must be <= high")

    if name == Condition.RANGE_EXPANDS.value:
        _coerce_float(params, "multiple")
        if params["multiple"] <= 0:
            raise ConditionError("invalid_param", "multiple must be > 0")
        reference = str(params.get("reference", "ATR")).upper()
        if reference not in RANGE_REFERENCES:
            raise ConditionError("invalid_param", f"reference must be one of {RANGE_REFERENCES}")
        params["reference"] = reference

    if name in (Condition.SESSION_OPENS.value, Condition.SESSION_CLOSES.value):
        session = str(params["session"]).lower()
        if session not in SESSIONS:
            raise ConditionError("invalid_param", f"session must be one of {SESSIONS}")
        params["session"] = session

    if name == Condition.TIME_REACHED.value:
        raw = str(params["at"])
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise ConditionError("invalid_param", f"at must be an ISO timestamp, got {raw!r}")
        params["at"] = raw

    return params


def validate_pin_query(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate a pin's level query (the ``level_alive`` condition)."""
    params = dict(params or {})
    if not any(all(_present(params, k) for k in group) for group in PIN_QUERY_ANY):
        groups = " or ".join("+".join(g) for g in PIN_QUERY_ANY)
        raise ConditionError("missing_params", f"a pin requires one of: {groups}")
    unknown = sorted(set(params) - set(PIN_QUERY_OPTIONAL) - {"level_key", "family", "price"})
    if unknown:
        raise ConditionError("unknown_params", f"pin query got unsupported params: {', '.join(unknown)}")

    if _present(params, "level_key"):
        params["level_key"] = str(params["level_key"])
    else:
        params["family"] = str(params["family"])
        _coerce_float(params, "price")
    if _present(params, "timeframe"):
        try:
            validate_timeframe(str(params["timeframe"]))
        except ValueError as exc:
            raise ConditionError("invalid_timeframe", str(exc))
    if _present(params, "direction") and params["direction"] not in DIRECTIONS:
        raise ConditionError("invalid_param", f"direction must be one of {DIRECTIONS}")
    if _present(params, "tolerance"):
        _coerce_float(params, "tolerance")
    return params


def default_timeframe(condition: Any, params: Optional[Dict[str, Any]], active: str) -> str:
    """The timeframe a condition is evaluated on.

    Level conditions inherit the level's own timeframe once the feed resolves it;
    until then, and for price/range conditions, the active timeframe is used.
    """
    params = params or {}
    return str(params.get("timeframe") or active)


def describe() -> str:
    """A prompt-ready listing of the vocabulary."""
    lines = []
    for name in ALL_CONDITIONS:
        spec = CONDITION_SPECS[name]
        groups = ""
        if spec.any_of:
            groups = " | params: " + " or ".join("+".join(g) for g in spec.any_of)
        elif spec.required:
            groups = " | params: " + ", ".join(spec.required)
        opts = f" [optional: {', '.join(spec.optional)}]" if spec.optional else ""
        lines.append(f"- {name}: {spec.description}{groups}{opts}")
    return "\n".join(lines)
