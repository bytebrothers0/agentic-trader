"""
registry.py — Pluggable strategy entry-module registry.

The bot's strategy layer is a library of entry modules. The old MSNR
storyline engine ships as 5 modules (one per model group); future
strategies register new modules here with their own engine key.

State (enabled on/off per module) persists to config/entry_modules.json so
dashboard toggles survive restarts.indicator layers are NOT managed here —
they stay on the dashboard sidebar.

To add a new entry model later:
  1. Append a dict to DEFAULT_MODULES (id, name, description, engine,
     models, enabled).
  2. Wire its engine in server.py (see the `msnr` engine handling).
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Set

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "config", "entry_modules.json")


def _state_file() -> str:
    """Honors MSNR_MODULES_FILE so tests can isolate state."""
    return os.environ.get("MSNR_MODULES_FILE", STATE_FILE)


DEFAULT_MODULES: List[Dict] = [
    {
        "id": "msnr_mn",
        "name": "MSNR Monthly Storyline",
        "description": "Monthly story → W1/MN entries (MN_STORY cascade).",
        "engine": "msnr",
        "models": ["MN_STORY_W1_ENTRY", "MN_STORY_MN_ENTRY"],
        "enabled": False,
    },
    {
        "id": "msnr_w1",
        "name": "MSNR Weekly Storyline",
        "description": "Weekly story → D1/W1 entries (W1_STORY cascade).",
        "engine": "msnr",
        "models": ["W1_STORY_D1_ENTRY", "W1_STORY_W1_ENTRY"],
        "enabled": False,
    },
    {
        "id": "msnr_d1",
        "name": "MSNR Daily Storyline",
        "description": "Daily story → H4/D1 entries (D1_STORY cascade).",
        "engine": "msnr",
        "models": ["D1_STORY_H4_ENTRY", "D1_STORY_D1_ENTRY"],
        "enabled": False,
    },
    {
        "id": "msnr_14b",
        "name": "MSNR Model B (14B)",
        "description": "1H reject + 1H breakout confirmation entries.",
        "engine": "msnr",
        "models": ["MODEL_B_14B"],
        "enabled": False,
    },
    {
        "id": "msnr_d1w4",
        "name": "MSNR Model C (D1W4)",
        "description": "D1/W4 single-candle mitigation retracements.",
        "engine": "msnr",
        "models": ["MODEL_C_D1W4"],
        "enabled": False,
    },
    {
        "id": "ts_m15",
        "name": "MNSR + TS (M15)",
        "description": "TS sweep -> BOS/CHoCH break -> QM -> IDM -> limit at QM (350pt SL / 3000pt TP).",
        "engine": "ts_m15",
        "models": ["TS_M15_ENTRY"],
        "enabled": False,
    },
]


def _read_overrides() -> Dict[str, bool]:
    try:
        with open(_state_file(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {k: bool(v) for k, v in data.items()}
    except (OSError, ValueError):
        pass
    return {}


def _write_overrides(overrides: Dict[str, bool]) -> None:
    path = _state_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(overrides, fh, indent=2)
    except OSError:
        pass


def list_modules() -> List[Dict]:
    """All registered modules with live enabled state."""
    overrides = _read_overrides()
    out = []
    for mod in DEFAULT_MODULES:
        out.append({
            "id": mod["id"],
            "name": mod["name"],
            "description": mod["description"],
            "engine": mod["engine"],
            "models": list(mod["models"]),
            "enabled": overrides.get(mod["id"], mod["enabled"]),
        })
    return out


def is_enabled(module_id: str) -> bool:
    for mod in list_modules():
        if mod["id"] == module_id:
            return mod["enabled"]
    return False


def set_enabled(module_id: str, enabled: bool) -> bool:
    """Persist a module toggle. Returns False for unknown ids."""
    known = {mod["id"] for mod in DEFAULT_MODULES}
    if module_id not in known:
        return False
    overrides = _read_overrides()
    overrides[module_id] = bool(enabled)
    _write_overrides(overrides)
    return True


def enabled_model_values(engine: str = "msnr") -> Set[str]:
    """Model value strings of all enabled modules for an engine."""
    values: Set[str] = set()
    for mod in list_modules():
        if mod["engine"] == engine and mod["enabled"]:
            values.update(mod["models"])
    return values


def any_enabled() -> bool:
    return any(mod["enabled"] for mod in list_modules())
