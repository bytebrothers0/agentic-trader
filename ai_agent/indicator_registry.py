"""Registry of the 37 real MQL5 chart indicators. AI auto-toggles these.

Architectural truth (verified from .mq5 source):
- 36 of 37 are OBJECT indicators (indicator_plots 0): they draw boxes/lines
  with an InpPrefix (e.g. MSNR_FVG_) and expose NO data buffers.
- 1 (MSNR_EMS_BBMA) has 8 buffers + objects.
- So the AI cannot CopyBuffer() them. Real data path = MT5 collector EA
  scans chart objects by prefix and exports counts/levels to Files.
- Toggles here are the command channel: collector EA polls this registry
  and attaches/detaches (or hides) the disabled indicators for real.
"""
from __future__ import annotations
import json
import os
from typing import Dict, List

from ai_agent import config as cfg

# Exact .mq5 basenames (37). MSNR_AlchemistBase is a base library, not an indicator.
ALL_INDICATORS: List[str] = [
    # ABX (11)
    "MSNR_ABX_AMDX", "MSNR_ABX_CECluster", "MSNR_ABX_Classic", "MSNR_ABX_CloseTL",
    "MSNR_ABX_DayProfile", "MSNR_ABX_Fibo", "MSNR_ABX_FreshZone", "MSNR_ABX_HiddenBase",
    "MSNR_ABX_OCLZone", "MSNR_ABX_QMX", "MSNR_ABX_SMT",
    # APA (4)
    "MSNR_APA_AOL", "MSNR_APA_EngulfTypes", "MSNR_APA_FTA", "MSNR_APA_Shift",
    # Apex (1)
    "MSNR_Apex",
    # EMS (8)
    "MSNR_EMS_BBMA", "MSNR_EMS_BOS_Sweep", "MSNR_EMS_CRT", "MSNR_EMS_Engulfing",
    "MSNR_EMS_FVG", "MSNR_EMS_Liquidity", "MSNR_EMS_PremiumDiscount", "MSNR_EMS_Range",
    # Levels / OCL / Freshness / RoleFlip (4)
    "MSNR_Freshness", "MSNR_Levels_SR", "MSNR_OCL", "MSNR_RoleFlip",
    # PHX (6)
    "MSNR_PHX_DojiTrigger", "MSNR_PHX_Liquidity", "MSNR_PHX_MSS",
    "MSNR_PHX_OrderBlock", "MSNR_PHX_Trendline", "MSNR_PHX_Wick50",
    # QM / Storyline / TFL (3)
    "MSNR_QM_Taxonomy", "MSNR_Storyline", "MSNR_TFL_Zones",
]

# Chart-object prefix per indicator (from `input string InpPrefix` in each .mq5).
# This is what the MT5 collector EA scans with ObjectsTotal()/ObjectName().
PREFIX_MAP: Dict[str, str] = {
    "MSNR_ABX_AMDX": "MSNR_AX_", "MSNR_ABX_CECluster": "MSNR_CEC_",
    "MSNR_ABX_Classic": "MSNR_AC_", "MSNR_ABX_CloseTL": "MSNR_CTL_",
    "MSNR_ABX_DayProfile": "MSNR_DP_", "MSNR_ABX_Fibo": "MSNR_FB_",
    "MSNR_ABX_FreshZone": "MSNR_FZ_", "MSNR_ABX_HiddenBase": "MSNR_HB_",
    "MSNR_ABX_OCLZone": "MSNR_OZ_", "MSNR_ABX_QMX": "MSNR_QX_",
    "MSNR_ABX_SMT": "MSNR_SMT_", "MSNR_APA_AOL": "MSNR_AOL_",
    "MSNR_APA_EngulfTypes": "MSNR_AET_", "MSNR_APA_FTA": "MSNR_FTA_",
    "MSNR_APA_Shift": "MSNR_AS_", "MSNR_Apex": "MSNR_APX_",
    "MSNR_EMS_BBMA": "MSNR_BBMA_", "MSNR_EMS_BOS_Sweep": "MSNR_BS_",
    "MSNR_EMS_CRT": "MSNR_CRT_", "MSNR_EMS_Engulfing": "MSNR_EG_",
    "MSNR_EMS_FVG": "MSNR_FVG_", "MSNR_EMS_Liquidity": "MSNR_LQ_",
    "MSNR_EMS_PremiumDiscount": "MSNR_PD_", "MSNR_EMS_Range": "MSNR_RG_",
    "MSNR_Freshness": "MSNR_FR_", "MSNR_Levels_SR": "MSNR_SR_",
    "MSNR_OCL": "MSNR_OCL_", "MSNR_PHX_DojiTrigger": "MSNR_DT_",
    "MSNR_PHX_Liquidity": "MSNR_PR_", "MSNR_PHX_MSS": "MSNR_MS_",
    "MSNR_PHX_OrderBlock": "MSNR_OB_", "MSNR_PHX_Trendline": "MSNR_TL_",
    "MSNR_PHX_Wick50": "MSNR_W50_", "MSNR_QM_Taxonomy": "MSNR_QM_",
    "MSNR_RoleFlip": "MSNR_RF_", "MSNR_Storyline": "MSNR_ST_",
    "MSNR_TFL_Zones": "MSNR_TFL_",
}


def default_state() -> Dict[str, bool]:
    return {name: True for name in ALL_INDICATORS}


def load() -> Dict[str, bool]:
    try:
        if os.path.isfile(cfg.REGISTRY_PATH):
            with open(cfg.REGISTRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = default_state()
            for k, v in (data.get("indicators", {}) or {}).items():
                if k in state:
                    state[k] = bool(v)
            return state
    except Exception:
        pass
    return default_state()


def save(state: Dict[str, bool]) -> None:
    os.makedirs(cfg.STATE_DIR, exist_ok=True)
    with open(cfg.REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump({"indicators": state, "count": len(state)}, f, indent=2)


def apply_toggles(toggles: List[Dict], current: Dict[str, bool] | None = None) -> Dict[str, bool]:
    """Apply AI toggles. Exact allowlist match only — invented names dropped."""
    state = dict(current) if current else load()
    for t in (toggles or [])[:5]:
        name = str(t.get("name", "")).strip()
        if name not in state:
            continue
        state[name] = bool(t.get("enabled", True))
    save(state)
    return state


def summary(state: Dict[str, bool] | None = None) -> Dict:
    st = state or load()
    on = [k for k, v in st.items() if v]
    off = [k for k, v in st.items() if not v]
    return {"total": len(st), "enabled": len(on), "disabled": len(off),
            "enabled_list": on, "disabled_list": off}
