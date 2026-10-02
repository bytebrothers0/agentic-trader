"""Decision + safety layer. AI proposes; deterministic rules dispose.

ACCEPT  — AI agrees with MSNR (same direction, entry near an MSNR signal),
          sane SL/TP, confidence >= threshold, news not high-risk.
REVIEW  — plausible but needs human eyes (minor divergence / low confidence).
REJECT  — contradicts MSNR, insane numbers, or NO_TRADE.
Never places orders in propose mode.
"""
from __future__ import annotations
from typing import Any, Dict

from ai_agent.schemas import AIProposal


def _rr(entry: float, sl: float, tp: float) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    return abs(tp - entry) / risk


def validate(proposal: AIProposal, snapshot: Dict[str, Any],
             min_confidence: float = 55.0) -> AIProposal:
    sigs = snapshot.get("msnr_signals", []) or []
    px = snapshot.get("current_price")

    if proposal.bias == "NO_TRADE" or proposal.entry is None:
        proposal.verdict = "REJECT"
        proposal.verdict_reason = "AI found no trade (or MSNR has no signal)."
        proposal.msnr_agreement = False
        return proposal

    # 1. Sanity on numbers
    try:
        entry, sl, tp = float(proposal.entry), float(proposal.sl), float(proposal.tp)
    except Exception:
        proposal.verdict = "REJECT"
        proposal.verdict_reason = "Non-numeric entry/SL/TP."
        return proposal
    if not (sl > 0 and tp > 0 and entry > 0):
        proposal.verdict = "REJECT"
        proposal.verdict_reason = "Entry/SL/TP must be positive."
        return proposal
    is_buy = proposal.bias == "BULLISH"
    if is_buy and not (sl < entry < tp or sl < entry):
        proposal.verdict = "REJECT"
        proposal.verdict_reason = "BULLISH needs SL < entry (TP above ideally)."
        return proposal
    if proposal.bias == "BEARISH" and not (sl > entry > tp or sl > entry):
        proposal.verdict = "REJECT"
        proposal.verdict_reason = "BEARISH needs SL > entry (TP below ideally)."
        return proposal
    # XAUUSD SL guard: fixed 300pts = ~3.00 price units; allow 1.0–10.0 window
    sl_dist = abs(entry - sl)
    if "XAU" in str(snapshot.get("symbol", "")).upper() and not (0.5 <= sl_dist <= 15.0):
        proposal.verdict = "REJECT"
        proposal.verdict_reason = f"XAU SL distance {sl_dist:.2f} outside 0.5–15.0 guard."
        return proposal
    rr = _rr(entry, sl, tp)
    if rr < 1.0:
        proposal.verdict = "REVIEW"
        proposal.verdict_reason = f"RR {rr:.2f} < 1.0 — human should review."

    # 2. MSNR agreement: same-direction signal within 0.5% of entry
    agreement = False
    for s in sigs:
        if s.get("direction") != proposal.bias:
            continue
        ref = float(s.get("entry", 0) or 0)
        if ref and abs(ref - entry) / max(ref, 1e-9) <= 0.005:
            agreement = True
            break
    proposal.msnr_agreement = agreement
    if not agreement:
        proposal.verdict = "REVIEW"
        proposal.verdict_reason = (proposal.verdict_reason + " " if proposal.verdict_reason else "") + \
            "AI diverges from MSNR signals — needs human review."
        return proposal

    # 3. Confidence + news
    if proposal.news_risk == "high" and proposal.confidence > 60:
        proposal.confidence = 60.0
    if proposal.confidence < min_confidence and proposal.verdict != "REVIEW":
        proposal.verdict = "REVIEW"
        proposal.verdict_reason = f"Confidence {proposal.confidence:.0f} < {min_confidence:.0f}."
        return proposal

    if not proposal.verdict_reason:
        proposal.verdict = "ACCEPT"
        proposal.verdict_reason = f"MSNR-agreed {proposal.bias} @ {entry}, RR {rr:.2f}."
    elif proposal.verdict != "REVIEW":
        proposal.verdict = "ACCEPT"
    return proposal
