"""Shared schemas: snapshot in, proposal out. Grok must return this exact JSON."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

PROPOSAL_FIELDS = [
    "bias", "setup", "entry", "sl", "tp",
    "invalidation", "confidence", "reason_human",
    "indicator_toggles", "news_risk",
]

VALID_BIAS = {"BULLISH", "BEARISH", "NEUTRAL", "NO_TRADE"}


@dataclass
class IndicatorToggle:
    name: str
    enabled: bool
    reason: str = ""


@dataclass
class AIProposal:
    bias: str = "NO_TRADE"
    setup: str = ""
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    invalidation: str = ""
    confidence: float = 0.0
    reason_human: str = ""
    indicator_toggles: List[Dict[str, Any]] = field(default_factory=list)
    news_risk: str = "normal"  # low | normal | high
    msnr_agreement: bool = False
    verdict: str = "REJECT"  # ACCEPT | REVIEW | REJECT
    verdict_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_grok(data: Dict[str, Any]) -> "AIProposal":
        bias = str(data.get("bias", "NO_TRADE")).upper()
        if bias not in VALID_BIAS:
            bias = "NO_TRADE"
        toggles = data.get("indicator_toggles", []) or []
        clean_toggles = []
        for t in toggles:
            if isinstance(t, dict) and "name" in t:
                clean_toggles.append({
                    "name": str(t["name"]),
                    "enabled": bool(t.get("enabled", True)),
                    "reason": str(t.get("reason", ""))[:200],
                })
        def _f(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None
        try:
            conf = float(data.get("confidence", 0) or 0)
        except Exception:
            conf = 0.0
        return AIProposal(
            bias=bias,
            setup=str(data.get("setup", ""))[:500],
            entry=_f(data.get("entry")),
            sl=_f(data.get("sl")),
            tp=_f(data.get("tp")),
            invalidation=str(data.get("invalidation", ""))[:500],
            confidence=max(0.0, min(100.0, conf)),
            reason_human=str(data.get("reason_human", ""))[:2000],
            indicator_toggles=clean_toggles,
            news_risk=str(data.get("news_risk", "normal")).lower(),
        )
