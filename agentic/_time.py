"""agentic/_time.py — the tiny shared clock helpers (spec phase 4, review Q5).

The pure core had re-derived the same three one-liners in seven modules: an
``_as_aware`` normaliser (UTC-ify a naive datetime), a ``seconds_remaining``
subtraction, and a ``_new_id`` factory. They are one concept each, so they live
here — private (leading underscore), pure, and dependency-free — and the modules
that need them import from one place instead of copying.

* :func:`as_aware` — attach UTC to a naive datetime (or pass ``None`` through).
  Timezone handling is a correctness seam: comparing a naive and an aware
  datetime raises, so every boundary normalises first.
* :func:`seconds_remaining` — the countdown a briefing and a subscription view
  both display.
* :func:`new_id` — ``prefix_ab12cd34``, the store's id scheme, so a turn id and a
  subscription id look the same and stay collision-resistant.

Nothing here reads the wall clock; the clock is always injected by the caller.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional


def as_aware(value: Optional[datetime]) -> Optional[datetime]:
    """Return ``value`` with a UTC ``tzinfo``, or ``None`` unchanged.

    A naive datetime is read as UTC (that is the convention across the core, and
    the one MT5 stamps bars with), so this never guesses a local zone.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def seconds_remaining(until: Optional[datetime], now: datetime) -> Optional[float]:
    """Seconds from ``now`` until ``until`` — negative once ``until`` has passed.

    ``None`` when there is no deadline, so a caller can distinguish "no expiry"
    from "already expired" without a sentinel.
    """
    aware = as_aware(until)
    if aware is None:
        return None
    return (aware - as_aware(now)).total_seconds()


def new_id(prefix: str) -> str:
    """A short, prefixed, collision-resistant id: ``prefix_ab12cd34``."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"
