"""The model-output <-> store-schema dialect wall.

Nothing *enforces* the field contracts the model is shown: the tool registry
dispatches without validating its arguments against ``TOOL_SCHEMAS``, and the
closing call's structured JSON reaches ``_apply_output`` untouched. So a model
that speaks trading vocabulary — ``bias: "short"``, ``entry:
"4184.55-4190.05 (sell zone)"`` — has its proposal rejected or, worse, a string
stored into a float field. A backtest replay of a real turn recorded exactly
that: a complete, correctly-argued plan lost to a one-word vocabulary mismatch.

These helpers translate the dialect at the *boundary*, not in the store: the
store keeps its own strict validation (an unknown bias is still refused), words
that are unambiguous get mapped, and prose prices are read back as the first
price-looking number. Pure: stdlib only, no clock, no I/O.
"""
import re
from typing import Any, Dict, Optional, Tuple

from agentic.models import VALID_BIAS

#: Unambiguous trade-side synonyms mapped onto the store's four-word vocabulary.
#: The *direction* word a model reaches for ("short"/"sell") is not a different
#: opinion from the one the schema asks for — it is the same one in another
#: dialect, and rejecting it throws the plan away.
_BIAS_ALIASES = {
    "bullish": "bullish",
    "bull": "bullish",
    "long": "bullish",
    "buy": "bullish",
    "bearish": "bearish",
    "bear": "bearish",
    "short": "bearish",
    "sell": "bearish",
    "neutral": "neutral",
    "none": "none",
    "no_bias": "none",
    "flat": "none",
}

#: A price-looking number: digits (decimals optional), not part of a larger word.
#: The look-behind keeps the ``1`` out of "T1 4172.84" — the ``T`` blocks it — so
#: target ladders ("T1 4172.84, T2 4169") read back as T1, the nearest target.
_PRICE_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?")


def coerce_bias(value: Any) -> Any:
    """Return ``value`` if it already names a valid bias, else its dialect twin.

    Unknown words are returned **unchanged** so the store's own ``invalid_bias``
    refusal still applies — translation is not licence to invent an opinion.
    """
    if not isinstance(value, str):
        return value
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    return _BIAS_ALIASES.get(key, value)


def first_price(value: Any) -> Optional[float]:
    """The first price-looking number in ``value``, or ``None``.

    A zone string ("4184.55-4190.05 (sell zone)") reads back as its **first**
    edge — for an entry that is the near edge a limit order would fill at, for a
    stop the nearer bound the model wrote first, for a target T1, the plan's
    first objective. Already-numeric values pass through; prose with no number
    yields ``None`` (the field stays unset rather than being guessed).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _PRICE_RE.search(str(value))
    if not match:
        return None
    head = match.group(0).split("/")[0].strip()
    try:
        return float(head)
    except ValueError:
        return None


def coerce_proposal(proposal: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
    """A copy of ``proposal`` restricted to ``keys``, dialect-translated.

    ``bias`` is mapped through :func:`coerce_bias`; the numeric plan fields read
    their first price out of whatever the model wrote. Untranslatable *bias*
    words are left as-is, so the store still refuses them and the rejection is
    still the model's to fix.
    """
    picked: Dict[str, Any] = {}
    for key in keys:
        if key not in proposal:
            continue
        value = proposal[key]
        if key == "bias":
            picked[key] = coerce_bias(value)
        elif key in ("entry", "sl", "tp"):
            picked[key] = first_price(value)
        else:
            picked[key] = value
    return picked
