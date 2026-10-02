"""Live MT5 indicator state reader (the REAL feed).

The collector EA (MSNR_Collector.mq5) scans the 37 object-based indicators
on-chart and writes MQL5/Files/MSNR_AI/indicator_state.json.
This module finds that file across all MetaQuotes terminals and returns it.
If absent (EA not attached yet), returns source=not_connected so the
snapshot honestly flags AI input as python_fallback, not live MT5.
"""
from __future__ import annotations
import glob
import json
import os
from typing import Any, Dict

STATE_NAME = os.path.join("MSNR_AI", "indicator_state.json")
REGISTRY_NAME = os.path.join("MSNR_AI", "indicator_registry.json")


def _candidate_dirs():
    cands = []
    appdata = os.getenv("APPDATA", "")
    if appdata:
        base = os.path.join(appdata, "MetaQuotes", "Terminal")
        if os.path.isdir(base):
            for entry in os.listdir(base):
                d = os.path.join(base, entry, "MQL5", "Files")
                if os.path.isdir(d):
                    cands.append(d)
    # also honour explicit override
    override = os.getenv("MT5_FILES_DIR", "")
    if override and os.path.isdir(override):
        cands.insert(0, override)
    return cands


def read_live_state(max_age_sec: int = 300) -> Dict[str, Any]:
    import time
    for d in _candidate_dirs():
        p = os.path.join(d, STATE_NAME)
        if not os.path.isfile(p):
            continue
        try:
            age = time.time() - os.path.getmtime(p)
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            data["_file"] = p
            data["_age_sec"] = round(age, 1)
            data["_stale"] = age > max_age_sec
            data["source"] = "live_mt5"
            return data
        except Exception:
            continue
    return {"source": "not_connected", "indicators": [],
            "hint": "Attach MSNR_Collector.mq5 to an XAUUSD chart; it writes Files/MSNR_AI/indicator_state.json"}


def export_registry_to_terminals(registry_path: str) -> int:
    """Copy ai_agent/state/indicator_registry.json -> each terminal's Files/MSNR_AI/. Returns copies made."""
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            payload = f.read()
    except Exception:
        return 0
    n = 0
    for d in _candidate_dirs():
        try:
            target_dir = os.path.join(d, "MSNR_AI")
            os.makedirs(target_dir, exist_ok=True)
            with open(os.path.join(target_dir, "indicator_registry.json"), "w", encoding="utf-8") as f:
                f.write(payload)
            n += 1
        except Exception:
            pass
    return n
