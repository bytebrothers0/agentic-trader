"""Tests for the Turtle Soup (TS) indicator."""
import pandas as pd

from indicators.ts_detector import (
    TSDetector, TSType, TSDirection, TSVariant, TSState,
)


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def test_upper_ts_bearish_sweep():
    # bull -> bear, sweeps the high, body closes back below it
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].direction == TSDirection.BEARISH
    assert uppers[0].price == 105
    assert uppers[0].candle_index == 1


def test_lower_ts_bullish_sweep():
    # bear -> bull, sweeps the low, body closes back above it
    df = _df([
        {"open": 103, "high": 105, "low": 98, "close": 100},
        {"open": 99, "high": 102, "low": 96, "close": 101},
    ])
    lv = TSDetector(df).detect_all()
    lowers = [x for x in lv if x.ts_type == TSType.TS_LOW]
    assert len(lowers) == 1
    assert lowers[0].direction == TSDirection.BULLISH
    assert lowers[0].price == 98


def test_no_ts_same_colour():
    # NOTE: same-colour pairs now COUNT (user rule change) — a bull -> bull
    # sweep with close back inside is a valid TS.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 102, "high": 107, "low": 101, "close": 106},
    ])
    lv = TSDetector(df).detect_all()
    # candle2 body (102-106) does NOT close back below 105 -> no TS
    assert [x for x in lv if x.ts_type == TSType.TS_HIGH] == []


def test_no_ts_body_closes_through():
    # sweep but body closes ABOVE the swept high -> not ts, that's a break
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 104, "high": 107, "low": 103, "close": 106},
    ])
    lv = TSDetector(df).detect_all()
    assert [x for x in lv if x.ts_type == TSType.TS_HIGH] == []


def test_no_ts_no_sweep():
    # opposite colours but no sweep of either wick
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 102, "high": 104, "low": 100, "close": 101},
    ])
    assert TSDetector(df).detect_all() == []


def test_same_colour_sweep_counts():
    # red -> red: sweeps the low, body closes back above -> valid TS_LOW
    df = _df([
        {"open": 103, "high": 105, "low": 98, "close": 100},
        {"open": 101, "high": 102, "low": 96, "close": 99},
    ])
    lv = TSDetector(df).detect_all()
    lowers = [x for x in lv if x.ts_type == TSType.TS_LOW]
    assert len(lowers) == 1
    assert lowers[0].price == 98


def test_dojis_can_sweep():
    # Web-exact: TS is colour-independent — dojis sweep too.
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 100},
        {"open": 100, "high": 107, "low": 97, "close": 100},
    ])
    lv = TSDetector(df).detect_all()
    assert {x.ts_type for x in lv} == {TSType.TS_HIGH, TSType.TS_LOW}


def test_sweep_gate_filters_micro_sweeps():
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 103},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    # Unfiltered: upper TS (sweep 2.0) fires.
    assert len(TSDetector(df).detect_all()) == 1
    # Gated far above local volatility: nothing fires.
    assert TSDetector(df, min_sweep_atr=5.0).detect_all() == []
    # Gated at zero: fires (default behavior preserved).
    assert len(TSDetector(df, min_sweep_atr=0.0).detect_all()) == 1


def test_no_ts_body_edge_high():
    # ❌ case from the chart: candle1 closes AT its high (no upper wick —
    # the "extreme" is a body edge, nothing was swept).
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 105},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    assert [x for x in TSDetector(df).detect_all()
            if x.ts_type == TSType.TS_HIGH] == []


def test_no_ts_body_edge_low():
    # Mirror: candle1 closes AT its low (no lower wick).
    df = _df([
        {"open": 100, "high": 101, "low": 95, "close": 95},
        {"open": 96, "high": 100, "low": 93, "close": 98},
    ])
    assert [x for x in TSDetector(df).detect_all()
            if x.ts_type == TSType.TS_LOW] == []


def test_dust_wick_counts_by_default_gate_opts_in():
    # Web-exact: any wick > 0 counts by default; the fraction gates are
    # opt-in display filters (live chart passes its tuned values).
    df = _df([
        {"open": 100, "high": 105.1, "low": 99, "close": 105},
        {"open": 104, "high": 107, "low": 100, "close": 102},
    ])
    assert len([x for x in TSDetector(df).detect_all()
                if x.ts_type == TSType.TS_HIGH]) == 1
    gated = [x for x in TSDetector(df, min_wick_body_frac=0.10).detect_all()
             if x.ts_type == TSType.TS_HIGH]
    assert gated == []


def test_visible_wick_counts():
    # ✅ case from the chart: long upper wick protruding past the body.
    df = _df([
        {"open": 100, "high": 108, "low": 97, "close": 103},
        {"open": 104, "high": 110, "low": 100, "close": 102},
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].price == 108


def test_small_wick_on_big_body_counts():
    # Oct02 10:00 shape (scaled): 1.76 lower wick on a 12.42 body (14%).
    # Small but visible — the range leg (11% of range) agrees.
    df = _df([
        {"open": 184.13, "high": 186.01, "low": 169.95, "close": 171.71},
        {"open": 171.90, "high": 174.38, "low": 165.81, "close": 173.85},
    ])
    lv = TSDetector(df).detect_all()
    lowers = [x for x in lv if x.ts_type == TSType.TS_LOW]
    assert len(lowers) == 1
    assert lowers[0].price == 169.95


def test_wick_near_body_edge_fails_range():
    # Oct02 06:30 shape (scaled): 0.98 wick on 9.13 body passes the body
    # leg (10.8%) but at 8.8% of range it needs range_frac <= 0.05.
    # Guard: with the default 0.05 it fires; tightened to 0.10 it must not.
    df = _df([
        {"open": 189.54, "high": 190.59, "low": 179.43, "close": 180.41},
        {"open": 180.21, "high": 183.01, "low": 177.38, "close": 181.02},
    ])
    got = [x for x in TSDetector(df).detect_all()
           if x.ts_type == TSType.TS_LOW]
    assert len(got) == 1 and got[0].price == 179.43
    tight = [x for x in TSDetector(df, min_wick_range_frac=0.10).detect_all()
             if x.ts_type == TSType.TS_LOW]
    assert tight == []


# ---------------------------------------------------------------------------
# Variant taxonomy (spec: docs/specs/2026-10-20-ts-variant-taxonomy-design.md)
# Anchor = candle 1 = the RANGE; variant = the structure of [anchor+1, sweep].
# ---------------------------------------------------------------------------

def _b(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


def test_variant_classic_adjacent():
    # Adjacent sweep, no same-bar delivery to the far boundary -> CLASSIC.
    df = _df([
        _b(100, 105, 99, 103),   # anchor: CRH 105, CRL 99
        _b(104, 107, 101, 102),  # sweep high (107>105), low 101 > CRL 99
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].variant.value == "classic"
    assert uppers[0].inside_bars == 0
    assert uppers[0].state is TSState.SWEPT


def test_variant_two_candle_delivers_far_boundary():
    # Adjacent sweep whose candle also reaches the far boundary -> TWO_CANDLE
    # (one candle manipulates AND distributes).
    df = _df([
        _b(100, 105, 99, 103),
        _b(104, 107, 98, 102),   # sweeps the high; low 98 reaches CRL 99
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].variant is TSVariant.TWO_CANDLE


def test_variant_inside_bar_one_nest():
    # anchor -> inside bar (no manipulation) -> sweep -> INSIDE_BAR.
    df = _df([
        _b(100, 105, 99, 103),    # anchor
        _b(103, 104.5, 99.5, 102),   # inside bar: h<=CRH, l>=CRL
        _b(104, 107, 100, 102),   # sweeps the high, body back below
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].variant is TSVariant.INSIDE_BAR
    assert uppers[0].inside_bars == 1
    assert uppers[0].candle_index == 2
    assert uppers[0].sweep_candle_index == 0


def test_variant_multiple_inside_bar_three_nests():
    # anchor -> 3 inside bars -> sweep -> MULTIPLE_INSIDE_BAR (inside_bars 3).
    df = _df([
        _b(100, 105, 99, 103),
        _b(103, 104.5, 99.5, 102),
        _b(102, 104, 100, 103),
        _b(103, 104.5, 99.5, 102),
        _b(104, 107, 100, 102),   # sweep
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    outer = [x for x in uppers if x.sweep_candle_index == 0]
    assert len(outer) == 1
    assert outer[0].variant is TSVariant.MULTIPLE_INSIDE_BAR
    assert outer[0].inside_bars == 3
    assert outer[0].candle_index == 4
    # The nested mid-anchor sweep (bar 3 pokes bar 2's high) is the same
    # adjacent-pair TS the legacy detector emitted — parity, not noise.
    assert [x.sweep_candle_index for x in uppers if x.sweep_candle_index != 0] \
        == [2]


def test_variant_multiple_candle_mixed_bars_between():
    # anchor -> non-inside pullback bar -> sweep -> MULTIPLE_CANDLE.
    # Bar 1 dives below CRL (not an inside bar) and bar 2 sweeps the anchor's
    # high only (bar 1's high is below CRH, so no nested container collides).
    rows = [
        _b(100, 105, 99, 103),        # anchor: CRH 105, CRL 99
        _b(103, 104.5, 97, 104),      # raids the LOW, closes back inside
        _b(104, 107, 100, 102),       # sweeps the HIGH, body back below
    ]
    df = _df(rows)
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(mv := [x for x in uppers
                      if x.variant is TSVariant.MULTIPLE_CANDLE]) == 1
    assert mv[0].sweep_candle_index == 0 and mv[0].candle_index == 2
    assert mv[0].inside_bars == 0
    # ...and the mid bar's own lower sweep fired first (earliest per side).
    lowers = [x for x in lv if x.ts_type == TSType.TS_LOW]
    assert len(lowers) == 1 and lowers[0].candle_index == 1

    # The textbook multi-candle shape without side-competition: a calm
    # non-inside drift bar between anchor and sweep.
    df2 = _df([
        _b(100, 105, 99, 103),
        _b(104, 104.5, 99.5, 102),    # h 104.5 <= 105, l 99.5 >= 99 -> inside
        _b(103, 103.5, 98, 103),      # dives below CRL — NOT inside anymore
        _b(104, 107, 100, 102),       # upper sweep, k=3
    ])
    lv2 = TSDetector(df2).detect_all()
    uppers2 = [x for x in lv2 if x.ts_type == TSType.TS_HIGH]
    assert len(uppers2) == 1
    assert uppers2[0].variant is TSVariant.MULTIPLE_CANDLE
    assert uppers2[0].inside_bars == 1   # one of the two drift bars was inside
    # The lows: anchor0's low taken at k=2 (INSIDE_BAR); the anchor made from
    # bar 1 (its range nests inside anchor0's) collapses into that same level.
    lowers2 = [x for x in lv2 if x.ts_type == TSType.TS_LOW]
    assert len(lowers2) == 1 and lowers2[0].candle_index == 2


def test_invalidated_by_later_body_close_through():
    # Signal at bar 1; bar 2 body-closes THROUGH the swept high -> dead.
    df = _df([
        _b(100, 105, 99, 103),
        _b(104, 107, 101, 102),   # TS_HIGH (107 > 105, body back below)
        _b(105, 108, 104, 107),   # close 107 > 105 -> breakout, invalidated
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1
    assert uppers[0].state is TSState.INVALIDATED
    assert uppers[0].invalidated_candle_index == 2
    assert uppers[0].end_time == df.index[2]


def test_invalidation_not_wick_only():
    # A later candle pokes the high but closes back below -> still SWEPT.
    df = _df([
        _b(100, 105, 99, 103),
        _b(104, 107, 101, 102),
        _b(103, 106, 100, 103),   # wick above 105, close 103 below -> alive
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    assert len(uppers) == 1 and uppers[0].state is TSState.SWEPT


def test_both_side_bar_deepest_raid_wins():
    # One candle breaches both boundaries; the deeper raid wins -> one signal.
    df = _df([
        _b(100, 105, 99, 103),
        _b(104, 108, 96, 103),   # up 3.0 vs down 3.0 -> tie, both fire
    ])
    lv = TSDetector(df).detect_all()
    assert len(lv) == 2  # tie: equal depth keeps both (documented)

    df2 = _df([
        _b(100, 105, 99, 103),
        _b(104, 108, 98, 103),   # up 3.0 vs down 1.0 -> upper wins
    ])
    lv2 = TSDetector(df2).detect_all()
    assert len(lv2) == 1
    assert lv2[0].ts_type is TSType.TS_HIGH
    assert lv2[0].sweep_amount == 3.0


def test_window_cap_slices_long_anchor_lifes():
    # Valid sweep 6 bars after the anchor: beyond TS_MAX_BETWEEN=5 -> gone.
    rows = [
        _b(100, 105, 99, 103),
        _b(103, 104, 100, 103),
        _b(103, 104, 100, 103),
        _b(103, 104, 100, 103),
        _b(103, 104, 100, 103),
        _b(103, 104, 100, 103),
        _b(104, 107, 100, 102),   # anchor+6
    ]
    df = _df(rows)
    assert [x for x in TSDetector(df).detect_all()
            if x.ts_type == TSType.TS_HIGH] == []
    # Tightened window to 6 -> fires.
    got = [x for x in TSDetector(df, max_between=6).detect_all()
           if x.ts_type == TSType.TS_HIGH]
    assert len(got) == 1 and got[0].candle_index == 6


def test_one_sweep_per_anchor_side_earliest_wins():
    # Anchor 0 swept at k=1 again at k=3: only the earliest survives; the
    # later sweep belongs to a DIFFERENT anchor (bar 1, whose range is not
    # nested in anchor 0's) and still reports.
    df = _df([
        _b(100, 105, 99, 103),
        _b(104, 107, 100, 102),   # anchor 0 upper sweep (k=1)
        _b(103, 104, 100, 103),   # calm
        _b(104, 107.5, 103, 103), # sweeps anchor 1's high (107) too
    ])
    lv = TSDetector(df).detect_all()
    uppers = [x for x in lv if x.ts_type == TSType.TS_HIGH]
    anchors = sorted(x.sweep_candle_index for x in uppers)
    assert anchors == [0, 1]            # one per anchor, earliest only
    assert uppers[0].candle_index == 1  # anchor 0's earliest sweep kept


def test_side_dies_without_signal_when_first_breach_closes_through():
    # Anchor 0's FIRST breach closes through (real breakout): its upper side
    # yields NO level. Bar 2 then wick-sweeps and closes back inside — but
    # that level belongs to ANCHOR 1 (bar 1's own range), still a valid
    # adjacent TS; anchor 0 contributes nothing.
    df = _df([
        _b(100, 105, 99, 103),
        _b(104, 107, 101, 106),   # breach + close through -> anchor0 dead
        _b(105, 107.5, 102, 103), # valid sweep of anchor 1's high (107)
    ])
    uppers = [x for x in TSDetector(df).detect_all()
              if x.ts_type == TSType.TS_HIGH]
    assert [x.sweep_candle_index for x in uppers] == [1]


def test_default_max_between_is_five():
    from config import settings
    assert settings.TS_MAX_BETWEEN == 5
