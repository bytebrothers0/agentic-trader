"""Entry-module registry: metadata + enabled state for the settings tab.

Contract with web/app.js:
  GET  /api/settings/modules -> {"modules": [{id, name, description, engine, enabled}]}
  POST /api/settings/modules/{id}?enabled=true|false -> {"ok": true, "modules": [...]}

State persists to config/modules_state.json (defaults = all enabled).
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "modules_state.json",
)

MODULES: List[Dict] = [
    {
        "id": "alchemist_x",
        "name": "Alchemist X-Factor (MSNR)",
        "description": (
            "Web Alchemist top-down stack: HTF storyline bias (D1/H4, W1/D1, "
            "MN1/W1) + M15 trendline x SNR cross (point 3) with mandatory "
            "engulfing validation, TS sweep bonus, M5 refinement, 2-use "
            "level cap, RR >= 1.5."
        ),
        "engine": "strategy.alchemist:AlchemistEngine",
        "enabled": True,
    },
]


def _load_state() -> Dict[str, bool]:
    try:
        if os.path.isfile(_STATE_PATH):
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            return {str(k): bool(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_state(state: Dict[str, bool]) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def list_modules() -> List[Dict]:
    """Registry metadata merged with persisted enabled flags."""
    state = _load_state()
    out = []
    for mod in MODULES:
        row = dict(mod)
        if row["id"] in state:
            row["enabled"] = state[row["id"]]
        out.append(row)
    return out


def set_enabled(module_id: str, enabled: bool) -> List[Dict]:
    """Persist one module's flag; raises KeyError on unknown id."""
    if module_id not in {m["id"] for m in MODULES}:
        raise KeyError(f"unknown entry module '{module_id}'")
    state = _load_state()
    for mod in MODULES:
        state.setdefault(mod["id"], bool(mod.get("enabled", True)))
    state[module_id] = bool(enabled)
    _save_state(state)
    return list_modules()


def is_enabled(module_id: str) -> bool:
    for mod in list_modules():
        if mod["id"] == module_id:
            return bool(mod["enabled"])
    return False
