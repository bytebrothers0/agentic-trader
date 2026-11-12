"""Indicator-family registry: metadata + enabled state for the settings tab.

Contract with web/app.js:
  GET  /api/settings/families -> {"families": [{id, name, description, enabled}]}
  POST /api/settings/families/{id}?enabled=true|false -> {"ok": true, "families": [...]}

State persists to config/families_state.json (defaults = all enabled). The
**consumer** is the agentic chart agent: the enabled set is read fresh at each
turn start (``AgentService._settings_families`` -> ``AgentLoop(families=...)``)
and restricts the set_view tool schema, the set_view validation, every
snapshot/render fetch, and the system prompt's indicator guide. Dashboard
sidebar layers are unaffected — this knob only controls what the *agent* is
offered, so a strategy that never uses, say, `qm` can take it away from the
model entirely.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from agentic.feed import KNOWN_FAMILIES

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "families_state.json",
)

FAMILIES: List[Dict] = [
    {"id": "sr", "name": "S/R", "description": "Body-close support/resistance flips (SBR/RBS)."},
    {"id": "crt", "name": "CRT", "description": "Candle Range Theory sweeps and range edges."},
    {"id": "ts", "name": "Turtle Soup", "description": "Range-boundary sweep with body close back inside."},
    {"id": "bos", "name": "BOS / CHoCH", "description": "Structure breaks by candle close (continuation / change)."},
    {"id": "fvg", "name": "FVG / IFVG", "description": "Three-candle imbalances and inverted confirmations."},
    {"id": "ob", "name": "Order Blocks", "description": "Displacement / sweep-anchored order-block zones."},
    {"id": "liquidity", "name": "Liquidity", "description": "Equal-highs / equal-lows pools (buy-side, sell-side)."},
    {"id": "qm", "name": "Quasimodo", "description": "Failed SBR/RBS: through the level, then back across."},
    {"id": "idm", "name": "Inducement", "description": "IDM pullback levels from BOS / anchor rules."},
    {"id": "trendline", "name": "Trendlines", "description": "Swing-apex trendlines with break / retest states."},
    {"id": "ocl", "name": "OCL", "description": "Open-close levels on the chart timeframe."},
    {"id": "apex", "name": "Apex", "description": "Validated swing apexes behind structural breakouts."},
]

# Any family the feed knows but this registry does not list yet still appears
# (default-enabled) so the knob always covers the feed's full vocabulary.
for _fid in KNOWN_FAMILIES:
    if _fid not in {f["id"] for f in FAMILIES}:
        FAMILIES.append({"id": _fid, "name": _fid, "description": ""})


def _load_state() -> Dict[str, bool]:
    try:
        if os.path.isfile(_STATE_PATH):
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): bool(v) for k, v in data.items()}
    except (OSError, ValueError):
        pass
    return {}


def _save_state(state: Dict[str, bool]) -> None:
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def list_families() -> List[Dict]:
    """The knob rows for the settings tab (metadata + persisted enabled flag)."""
    state = _load_state()
    out: List[Dict] = []
    for fam in FAMILIES:
        row = dict(fam)
        row["enabled"] = bool(state.get(fam["id"], True))
        out.append(row)
    return out


def enabled_families() -> List[str]:
    """The ids the agent may request this turn — read fresh per turn."""
    return [f["id"] for f in list_families() if f["enabled"]]


def set_enabled(family_id: str, enabled: bool) -> List[Dict]:
    """Persist one family's flag; raises KeyError on unknown id."""
    if family_id not in {f["id"] for f in FAMILIES}:
        raise KeyError(f"unknown indicator family '{family_id}'")
    state = _load_state()
    for fam in FAMILIES:
        state.setdefault(fam["id"], True)
    state[family_id] = bool(enabled)
    _save_state(state)
    return list_families()
