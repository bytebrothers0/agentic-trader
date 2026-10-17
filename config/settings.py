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
    "M30": mt5.TIMEFRAME_M30,  # 30-minute (native)
    "M45": "SYNTH_M45",        # 45-minute: MT5 has no M45 — the loader
                               # resamples 3xM15 (hour-grid :00/:45/:30...).
                               # Any str value here means "synthesized".
    "M5":  mt5.TIMEFRAME_M5,   # 5-minute
    "M3":  mt5.TIMEFRAME_M3,   # 3-minute
    "M1":  mt5.TIMEFRAME_M1,   # 1-minute (standard MT5 meaning)
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
    "M30": 600,  # ~12 days of 30m
    "M45": 500,  # ~15 days of 45m (synthesized from M15)
    "M5":  500,  # ~40 hours of 5m
    "M3":  500,  # ~25 hours of 3m
    "M1":  500,  # ~8 hours of 1m
}

# =============================================================================
# STRATEGY MASTER SWITCH — old entry models removed (fresh start).
# When False, server /api/indicators returns empty disabled payloads and
# the dashboard hides strategy UI.
# Candles / account / positions / orders keep working (infra only).
# =============================================================================
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

# IDM (inducement, SMC) — enabled. BOS-anchored: the internal pullback (minor
# fractal swing) inside an impulse leg that broke structure. SWING_LENGTH is
# the minor fractal window; MAX_PER_SIDE caps rays kept per direction (newest,
# unswept first) — the noise guard that replaces the old every-bar scan.
IDM_ENABLED = True
IDM_SWING_LENGTH = 2
IDM_SHOW_INTERNAL = True
IDM_MAX_PER_SIDE = 3
IDM_ATR_PERIOD = 14
# Luap "True SMC" valid-pullback rule (Part 1 + Part 3): a pullback only counts
# once a candle takes the liquidity of the candle that ended the impulse. Emits
# a second IDM family (rule="two_candle") alongside the BOS-anchored one.
IDM_TWO_CANDLE_RULE = True

# Liquidity pools (SMC) — enabled. Equal highs (buy-side) / equal lows
# (sell-side) stop clusters. Pools need >= LIQ_MIN_TOUCHES touches within
# LIQ_EQ_TOL_ATR x ATR and LIQ_EQ_MAX_BARS bars; single swings are excluded.
LIQ_ENABLED = True
LIQ_SWING_LENGTH = 5
LIQ_EQ_TOL_ATR = 0.15
LIQ_EQ_MAX_BARS = 60
LIQ_MIN_TOUCHES = 2
LIQ_MAX_PER_SIDE = 3

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
# Valid-OB gates (web Alchemist math): origin-candle liquidity sweep OR
# displacement break; same-side FVG overlap is entry confluence, not a
# validity gate (OB_REQUIRE_FVG=False). Zones near IDM tagged Decisional.
OB_ENABLED = True
OB_SWING_LENGTH = 10
OB_SHOW_LAST = 3
OB_USE_BODY = False
OB_REQUIRE_FVG = False
OB_REQUIRE_SWEEP = True
OB_DISPLACEMENT_MULT = 1.5
OB_MARK_DECISIONAL = True

# Auto trendlines (LuxAlgo "Trendlines with Breaks" semantics) — enabled.
# Pivot fractal window, ATR slope multiplier, recent lines kept per side,
# forward window for break-retest scan.
TL_ENABLED = True
TL_PIVOT_LENGTH = 14
# Multi-scale apex windows: a close swing counts as an apex if it is the
# extreme of ANY of these symmetric windows, and the results are merged.
# Window 5 catches the local swings a channel is built from; window 14 keeps
# the major swings. (A 3-bar window is deliberately avoided: it produces
# short, steep noise segments that crowd out the meaningful lines.)
TL_PIVOT_WINDOWS = (5, 14)
TL_SLOPE_MULT = 1.0
TL_MAX_LINES = 3
TL_RETEST_BARS = 30
# Touch/collinearity tolerance for the point-to-point trendline (fraction
# of ATR(14)). A 3rd apex or validation touch within this band respects the
# line; the line itself is drawn through the close-price apexes.
TL_TOL_ATR = 0.25
# Channel slope-match tolerance (ATR fraction over 10 bars): two lines whose
# slopes differ by less than this form a channel pair.
TL_CHANNEL_PARALLEL_ATR = 0.2
# Wick penetration past the line (ATR fraction) that counts as a liquidity
# sweep (stop-hunt) rather than an ordinary touch.
TL_SWEEP_ATR = 0.5
# Body pivots anchor at CLOSE fractals (line-chart
# A/V apexes on the candle bodies — engulfing/engulfed swing points),
# wick pivots at high/low fractals. A bar that is both yields two anchors.
# REQUIRE_ENGULFING=False keeps any swing point (engulfing only grades
# continuation vs standard); True restricts anchors to engulfing/engulfed
# bars.
TL_BODY_PIVOTS = True
TL_REQUIRE_ENGULFING = False
# Web rule: trendlines never anchor at gap bars (cannot connect GAP SNR).
# Gap = |open - prev close| beyond TL_GAP_ATR_MULT x local ATR.
TL_SKIP_GAP_ANCHORS = True
TL_GAP_ATR_MULT = 0.1

# TS indicator display: the swept extreme must be a VISIBLE wick on
# candle1, not a body edge (a candle closing at its high has no upper
# wick to sweep). Both gates must pass on the swept side:
#   wick >= TS_MIN_WICK_BODY_FRAC * body  (protrudes past the body)
#   wick >= TS_MIN_WICK_RANGE_FRAC * range (visible against whole candle)
# Body frac 0.10 (was 0.25): a small-but-visible wick on a big impulse
# body counts (Oct02 10:00: 1.76 wick on 12.42 body = 14%); dust
# (0.1 on 5.0 = 2%) still fails, range leg backstops tiny bodies.
# Range frac 0.05 (was 0.10): Oct02 06:30 wick (0.98 of 11.16 range =
# 8.8%) is visibly a wick, not a body edge. Measured Sep28-Oct02:
# 0.10 -> 170 TS, 0.05 -> 188, 0.00 -> 192 (dust already dead elsewhere).
TS_MIN_WICK_BODY_FRAC = 0.10
TS_MIN_WICK_RANGE_FRAC = 0.05

# =============================================================================
# LOGGING
# =============================================================================
LOG_DIR = "logs"
TRADE_LOG_FILE = "logs/trade_log.csv"
SIGNAL_LOG_FILE = "logs/signal_log.csv"
