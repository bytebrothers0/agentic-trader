"""Tests for the point-to-point close-apex trendline detector.

A trendline connects 2-3 close-price apex points (line-chart A/V swings).
The slope is derived from the anchors (no forced ATR slope).
"""
import pandas as pd

from indicators.trendline_detector import TLDetector, TLSide, TLState


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _from_closes(closes, wick=0.5, highs=None, lows=None):
    """Build OHLCV from a close path; open = prior close (no gaps).

    highs/lows: optional {index: value} overrides for wick control.
    """
    highs, lows = highs or {}, lows or {}
    rows = []
    prev = closes[0]
    for i, cl in enumerate(closes):
        o = prev
        hi = highs.get(i, max(o, cl) + wick)
        lo = lows.get(i, min(o, cl) - wick)
        rows.append({"open": o, "high": hi, "low": lo, "close": cl})
        prev = cl
    return _df(rows)


# Two descending close peaks: 111 @ 5, 110 @ 19 (slope = -1/14).
DESC_CLOSES = [
    105, 106, 107, 108, 109, 111,          # 0-5  rise to peak 111
    110, 109, 108, 107, 106, 105, 104,     # 6-12 fall to valley 104
    105, 106, 107, 108, 108.5, 109, 110,   # 13-19 rise to peak 110
    109, 108, 107, 106, 105, 104,          # 20-25 fall away
]

# Two ascending close valleys: 90 @ 5, 92 @ 19 (slope = +1/7).
ASC_CLOSES = [
    96, 95, 94, 93, 92, 90,                # 0-5  fall to valley 90
    92, 93, 94, 95, 96, 97, 100,           # 6-12 rise to peak 100
    99, 98, 97, 96, 95, 94, 92,            # 13-19 fall to valley 92
    93, 94, 95, 96, 97, 98,                # 20-25 rise away
]

# Three collinear descending close peaks: 111 @ 4, 110 @ 10, 109 @ 16.
THREE_CLOSES = [
    108, 108.5, 109, 110, 111,             # 0-4  peak 111
    110.5, 110.2, 109.8, 109.5, 109.4,     # 5-9
    110,                                    # 10   peak 110
    109.7, 109.4, 109.1, 108.8, 108.7,     # 11-15
    109,                                    # 16   peak 109
    108.5, 107, 106, 105,                   # 17-20
]


def test_upper_line_connects_two_descending_highs():
    df = _from_closes(DESC_CLOSES)
    uppers = [x for x in TLDetector(df, pivot_length=2).detect_all()
              if x.side == TLSide.UPPER]
    assert len(uppers) == 1, f"expected one upper line, got {uppers}"
    line = uppers[0]
    assert line.pivot_index == 5 and line.pivot_price == 111
    assert line.second_anchor_index == 19
    assert line.anchor_kind == "close"
    assert line.slope < 0  # falling resistance
    assert abs(line.value_at(19) - 110) < 1e-9  # passes THROUGH the 2nd apex
    assert line.state == TLState.ACTIVE
    # the 2nd anchor is point 2
    assert line.touch_bars[0] == 19
    assert len(line.touch_bars) == line.touches


def test_lower_line_connects_two_ascending_lows():
    df = _from_closes(ASC_CLOSES)
    lowers = [x for x in TLDetector(df, pivot_length=2).detect_all()
              if x.side == TLSide.LOWER]
    assert len(lowers) == 1, f"expected one lower line, got {lowers}"
    line = lowers[0]
    assert line.pivot_index == 5 and line.pivot_price == 90
    assert line.second_anchor_index == 19
    assert line.slope > 0  # rising support
    assert abs(line.value_at(19) - 92) < 1e-9
    assert line.state == TLState.ACTIVE


def test_three_collinear_apexes_one_line():
    df = _from_closes(THREE_CLOSES)
    uppers = [x for x in TLDetector(df, pivot_length=2).detect_all()
              if x.side == TLSide.UPPER]
    assert len(uppers) == 1, f"expected one run, got {uppers}"
    line = uppers[0]
    assert line.pivot_index == 4 and line.second_anchor_index == 16
    assert line.apex_points == 3
    assert abs(line.value_at(10) - 110) < 1e-9  # middle apex sits on the line


def test_tolerance_accepts_near_third_apex():
    closes = list(THREE_CLOSES)
    closes[16] = 109.2  # 0.2 off the (4->10) line
    det = TLDetector(_from_closes(closes), pivot_length=2, tol_atr=0.25)
    det._atr = [2.0] * len(closes)  # tol = 0.5 -> 0.2 is respected
    line = next(x for x in det.detect_all() if x.pivot_index == 4)
    assert line.apex_points == 3


def test_tolerance_rejects_far_third_apex():
    closes = list(THREE_CLOSES)
    closes[16] = 109.2
    det = TLDetector(_from_closes(closes), pivot_length=2, tol_atr=0.01)
    det._atr = [2.0] * len(closes)  # tol = 0.02 -> 0.2 is not respected
    lines = det.detect_all()
    first = next(x for x in lines if x.pivot_index == 4)
    assert first.apex_points == 2
    assert any(x.pivot_index == 10 for x in lines)  # a fresh 10->16 line


def test_single_apex_yields_no_line():
    closes = [100 + i for i in range(11)] + [110 - i for i in range(10)]
    assert TLDetector(_from_closes(closes),
                      pivot_length=2).detect_all() == []


def test_ascending_highs_form_rising_resistance():
    # Any slope is allowed now: rising highs make a rising resistance line.
    closes = [100, 101, 102, 103, 104, 105,
              104, 103, 102, 101, 100, 99, 100,
              101, 102, 103, 104, 105, 106, 110,
              109, 108, 107, 106, 105, 104]
    uppers = [x for x in TLDetector(_from_closes(closes),
                                    pivot_length=2).detect_all()
              if x.side == TLSide.UPPER]
    assert len(uppers) == 1
    line = uppers[0]
    assert line.pivot_index == 5 and line.second_anchor_index == 19
    assert line.slope > 0  # rising resistance is valid
    assert line.role == "resistance"


def test_break_needs_body_close():
    closes = list(DESC_CLOSES)
    closes[20], closes[21] = 109.9, 109.95  # 21 closes above the line
    closes[22], closes[23] = 110.0, 110.5
    lines = [x for x in TLDetector(_from_closes(closes),
                                   pivot_length=2).detect_all()
             if x.side == TLSide.UPPER]
    assert lines
    line = next(x for x in lines if x.pivot_index == 5)
    assert line.state == TLState.BROKEN
    assert line.break_index == 21


def test_wick_poke_does_not_break():
    # A wick above the line with the body holding below keeps it active.
    closes = list(DESC_CLOSES)
    highs = {20: 111.0, 21: 111.0}  # wicks pierce, closes stay below
    lines = [x for x in TLDetector(_from_closes(closes, highs=highs),
                                   pivot_length=2).detect_all()
             if x.side == TLSide.UPPER]
    line = next(x for x in lines if x.pivot_index == 5)
    assert line.state == TLState.ACTIVE


def test_retest_after_break():
    closes = list(DESC_CLOSES)
    closes[20], closes[21] = 109.9, 109.95   # break at 21
    closes[22], closes[23] = 110.5, 110.6
    # bar 22 wick stays above the line; bar 23 wick touches it from above.
    lows = {22: 109.85, 23: 109.5}
    lines = [x for x in TLDetector(_from_closes(closes, lows=lows),
                                   pivot_length=2).detect_all()
             if x.side == TLSide.UPPER]
    line = next(x for x in lines if x.pivot_index == 5)
    assert line.state == TLState.BROKEN
    assert line.retested and line.retest_index == 23


def test_close_back_across_voids_retest():
    closes = list(DESC_CLOSES)
    closes[20], closes[21] = 109.9, 109.95   # break at 21
    closes[22] = 108.5                        # close back below: failed break
    lows = {23: 108.0}
    lines = [x for x in TLDetector(_from_closes(closes, lows=lows),
                                   pivot_length=2).detect_all()
             if x.side == TLSide.UPPER]
    line = next(x for x in lines if x.pivot_index == 5)
    assert not line.retested


def test_break_retest_flips_role():
    closes = list(DESC_CLOSES)
    closes[20], closes[21] = 109.9, 109.95   # break at 21
    closes[22], closes[23] = 110.5, 110.6
    lows = {22: 109.85, 23: 109.5}
    line = next(x for x in TLDetector(_from_closes(closes, lows=lows),
                                      pivot_length=2).detect_all()
                if x.pivot_index == 5)
    assert line.state == TLState.BROKEN and line.retested
    assert line.flipped and line.kind == "BRT"
    assert line.role == "resistance"          # original
    assert line.retest_role == "support"      # flipped after the retest


def test_liquidity_sweep_flagged():
    # A wick that pierces well past the line while the close holds below.
    lines = [x for x in TLDetector(_from_closes(DESC_CLOSES, highs={22: 111.5}),
                                   pivot_length=2).detect_all()
             if x.pivot_index == 5]
    line = lines[0]
    assert line.swept and 22 in line.sweep_bars
    assert line.state == TLState.ACTIVE


def test_small_wick_is_not_a_sweep():
    lines = [x for x in TLDetector(_from_closes(DESC_CLOSES, highs={22: 110.0}),
                                   pivot_length=2).detect_all()
             if x.pivot_index == 5]
    assert not lines[0].swept


# Descending channel: peaks 110@4 -> 106@16 and valleys 104@10 -> 100@22,
# both sloping -1/3 (parallel), resistance above support.
CHANNEL_CLOSES = [
    106, 107, 108, 109, 110,      # 0-4   peak 110
    108.5, 107.5, 106.5, 105.5, 104.5,  # 5-9
    104,                           # 10    valley 104
    104.5, 105, 105.2, 105.5, 105.8, 106,  # 11-16 peak 106
    105, 104, 103, 102, 101,       # 17-21
    100,                           # 22    valley 100
    101, 102, 103,                 # 23-25
]


def test_channel_pairs_resistance_and_support():
    lines = TLDetector(_from_closes(CHANNEL_CLOSES),
                       pivot_length=2).detect_all()
    uppers = [x for x in lines if x.side == TLSide.UPPER]
    lowers = [x for x in lines if x.side == TLSide.LOWER]
    assert len(uppers) == 1 and len(lowers) == 1
    up, lo = uppers[0], lowers[0]
    assert up.role == "resistance" and lo.role == "support"
    assert lo.slope < 0  # descending support = channel lower boundary
    assert up.channel_id is not None and up.channel_id == lo.channel_id


def test_max_lines_cap():
    lines = TLDetector(_from_closes(THREE_CLOSES), pivot_length=2,
                       max_lines=1).detect_all()
    assert len([x for x in lines if x.side == TLSide.UPPER]) <= 1
