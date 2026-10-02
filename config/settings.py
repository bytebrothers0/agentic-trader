"""
MSNR Trading Bot — Central Configuration
All strategy constants, instrument specs, and MT5 settings.
"""

import MetaTrader5 as mt5

# =============================================================================
# MT5 CONNECTION
# =============================================================================
MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
MT5_TIMEOUT = 10_000  # ms

# =============================================================================
# INSTRUMENTS (Start with XAUUSD, expand later)
# =============================================================================
INSTRUMENTS = ["XAUUSD"]

INSTRUMENT_SPECS = {
    "XAUUSD": {
        "pip_value": 0.01,        # 1 pip = 0.01 price units for XAUUSD
        "point_value": 0.01,      # MT5 point = 0.01
        # Fixed SL = 300 points = 3.00 price units (~30 pips). Risk-management
        # default for HTF cascade entries (FTFL/STFL boxes are several dollars
        # tall). Video 9's 5.5-7 pip example is the tight 1H-equilibrium
        # confirmation case, where the box-derived SL is naturally tighter;
        # the fixed 300pt cap keeps HTF entries from risking more than 1%.
        "sl_points": 300,
        # Video 10 spread buffer: 0.5-1.0 pip (5-10 points) above buy entries
        # (below sell entries) so the broker tags the limit in on spread.
        "spread_buffer_pts": 10,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "contract_size": 100,     # 100 oz per lot
        "digits": 2,
    }
}

# =============================================================================
# RISK MANAGEMENT
# =============================================================================
RISK_PERCENT = 1.0          # Risk 1% of account per trade
FULL_RISK_FACTOR = 1.0      # A+ setup: 100% of risk
REDUCED_RISK_FACTOR = 0.2   # Weak setup: 20% of risk
QM_RISK_FACTOR = 0.2        # QM-only entry: 20% of risk
SPLIT_ENTRY_MAIN = 0.7      # 70% at equilibrium (Model B/C)
SPLIT_ENTRY_SECONDARY = 0.3 # 30% at body level (Model B/C)

# =============================================================================
# TIMEFRAMES
# NOTE: "M1" is MT5 1-minute (TIMEFRAME_M1), NOT Monthly. Use "MN1"/"MN" for Monthly.
# =============================================================================
TIMEFRAME_MAP = {
    "MN1": mt5.TIMEFRAME_MN1,  # Standard MT5 Monthly key
    "MN":  mt5.TIMEFRAME_MN1,  # Alias for Monthly
    "W1":  mt5.TIMEFRAME_W1,
    "D1":  mt5.TIMEFRAME_D1,
    "H4":  mt5.TIMEFRAME_H4,
    "H2":  mt5.TIMEFRAME_H2,   # 2-hour
    "H1":  mt5.TIMEFRAME_H1,
    "M15": mt5.TIMEFRAME_M15,  # 15-minute (TTFL refinement for H4-based entries)
    "M5":  mt5.TIMEFRAME_M5,   # 5-minute
    "M3":  mt5.TIMEFRAME_M3,   # 3-minute
    "M1":  mt5.TIMEFRAME_M1,   # 1-minute (standard MT5 meaning)
}

# TF hierarchy for FTFL → STFL → TTFL step-down
TF_STEPDOWN = {
    "MN1": ("W1", "D1"),   # FTFL=Monthly → STFL=Weekly → TTFL=Daily
    "MN":  ("W1", "D1"),
    "W1":  ("D1", "H4"),   # FTFL=Weekly  → STFL=Daily  → TTFL=4H
    "D1":  ("H4", "H1"),   # FTFL=Daily   → STFL=4H     → TTFL=1H
    "H4":  ("H1", "M15"),  # FTFL=4H      → STFL=1H     → TTFL=15m
    "H1":  ("M15", "M1"),  # FTFL=1H      → STFL=15m    → TTFL=1m
}

# Timeframes where OCL detection is valid (HTF only)
OCL_VALID_TIMEFRAMES = {"MN1", "MN", "W1", "D1"}

# Timeframes where Apex/IAB detection is valid (line chart analysis)
APEX_VALID_TIMEFRAMES = {"MN1", "MN", "W1", "D1"}

# =============================================================================
# INDICATOR PARAMETERS
# =============================================================================
# Number of candles to look back for swing detection
SWING_LOOKBACK = 5

# Freshness: tolerance in price units for wick-touch detection
FRESHNESS_TOUCH_TOLERANCE = 0.0  # Exact touch counts as unfresh

# Minimum candles to fetch per timeframe
CANDLE_FETCH_COUNT = {
    "MN1": 24,   # 2 years of monthly
    "MN":  24,
    "W1":  104,  # 2 years of weekly
    "D1":  365,  # 1 year of daily
    "H4":  500,  # ~83 days of 4H
    "H2":  500,  # ~41 days of 2H
    "H1":  500,  # ~20 days of 1H
    "M15": 500,  # ~5 days of 15m
    "M5":  500,  # ~40 hours of 5m
    "M3":  500,  # ~25 hours of 3m
    "M1":  500,  # ~8 hours of 1m
}

# =============================================================================
# STORYLINE ANALYSIS SCHEDULE (Video 10 routine)
# =============================================================================
# Monthly analysis: first Saturday of month
# Weekly analysis: Saturday/Sunday
# Daily analysis: every day at market open
ANALYSIS_SCHEDULE = {
    "monthly": "first_saturday",
    "weekly": "saturday",
    "daily": "daily_open",
}


def get_due_analysis_scopes(now=None) -> list:
    """
    Video 10 top-down routine: which analysis scopes are due at `now`.
      - Monthly: first 7 days of the month (covers the first Saturday window).
      - Weekly: Saturday or Sunday.
      - Daily: always due (intraday continuation/confirmation scanned daily).
    Returns e.g. ["monthly", "weekly", "daily"].
    """
    import datetime as _dt
    now = now or _dt.datetime.now()
    due = ["daily"]
    if now.weekday() in (5, 6):
        due.append("weekly")
    if now.day <= 7:
        due.append("monthly")
    return due

# =============================================================================
# STRATEGY MASTER SWITCH — set True to re-enable your own logic later.
# When False, server /api/indicators, /api/strategy, /api/signals return
# empty disabled payloads and the dashboard hides strategy UI.
# Candles / account / positions / orders keep working (infra only).
# =============================================================================
STRATEGY_ENABLED = False
INDICATORS_ENABLED = False

# New custom logic lives behind its own flags so it works while the
# old MSNR stack stays off.
TS_ENABLED = True

# S/R + QM are part of the new strategy — enabled. OCL/Apex stay off.
SR_ENABLED = True
QM_ENABLED = True

# Open Close Levels + Apex/IAB swings — enabled.
OCL_ENABLED = True
APEX_ENABLED = True

# IDM (inducement/liquidity, Luap True SMC) — enabled.
IDM_ENABLED = True

# BOS (break of structure, Mxwll-style port) — enabled.
# Swing sensitivity in bars (script's Externals options: 10/25/50,
# Internals options: 3/5/8). Internals draw as I-BOS / I-CHOCH.
# Internal 3 = fastest confirmation at the live edge.
BOS_ENABLED = True
BOS_SWING_LENGTH = 25
BOS_INTERNAL_LENGTH = 3
BOS_SHOW_INTERNAL = True
# Same-level tolerance for swing confirmation (fraction of ATR(14)):
# taps within this band still confirm the swing.
BOS_SWING_TOL_ATR = 0.05

# FVG + IFVG (LuxAlgo detectFVG port + overlap inversion) — enabled.
# MIN_ATR_MULT drops sub-visual slivers (zone height < mult x ATR(14)).
# IFVG_MAX_GAP_BARS: first FVG must be this recent to invert.
# IFVG_MIN_OVERLAP_FRAC: overlap must cover this fraction of the smaller zone.
FVG_ENABLED = True
IFVG_ENABLED = True
FVG_MIN_ATR_MULT = 0.1
IFVG_MAX_GAP_BARS = 50
IFVG_MIN_OVERLAP_FRAC = 0.5

# OB + Breaker Blocks (LuxAlgo port + Luap status) — enabled.
# Swing lookback, last N zones per side, body-based zones option.
OB_ENABLED = True
OB_SWING_LENGTH = 10
OB_SHOW_LAST = 3
OB_USE_BODY = False

# MNSR + TS entry model (M15): TS -> break -> QM -> IDM -> QM entry.
# Fixed 350pt SL / 3000pt TP. TS older than MAX_AGE bars is stale;
# the break must land within BREAK_MAX_BARS after the TS.
# MAX_QM_DIST / MAX_IDM_DIST (price units): the TS->QM->IDM stack must stay
# local — far-away levels chained together are not one setup.
TS_ENTRY_MAX_AGE = 100
TS_BREAK_MAX_BARS = 50
TS_ENTRY_SL_POINTS = 350
TS_ENTRY_TP_POINTS = 3000
TS_MAX_QM_DIST = 20.0
TS_MAX_IDM_DIST = 20.0
# S/R-shelf break leg: shelf must sit this close to the TS level.
TS_SR_SHELF_DIST = 25.0
# TS significance for entries: sweep must be this multiple of ATR(14).
# The chart indicator stays unfiltered; only entries are gated.
# 0.25 kills sub-visual dust (median noise is ~0.15) while keeping real
# sweeps (~0.3+ even in volatile weeks).
TS_MIN_SWEEP_ATR = 0.25

# =============================================================================
# LOGGING
# =============================================================================
LOG_DIR = "logs"
TRADE_LOG_FILE = "logs/trade_log.csv"
SIGNAL_LOG_FILE = "logs/signal_log.csv"
