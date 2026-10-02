"""Append-only trade journal (JSONL) — the AI's memory of what it proposed."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from ai_agent import config as cfg


def log_proposal(proposal: Dict[str, Any], snapshot_meta: Dict[str, Any] | None = None) -> None:
    os.makedirs(cfg.STATE_DIR, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(),
           "proposal": proposal, "meta": snapshot_meta or {}}
    with open(cfg.JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def recent(n: int = 20):
    if not os.path.isfile(cfg.JOURNAL_PATH):
        return []
    with open(cfg.JOURNAL_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()[-n:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out
