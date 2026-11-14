"""Append rule rows to research/strategy_rules.csv (idempotent-ish: skips already-present ids)."""
import csv
import io
import os

ROWS = [
    ['P01-01', 'part01_foundations_snr.md', 'abax', 'zone_model', 'Zone = SNR line + OB + OB50; never trigger on line touch alone', 'ob50=midpoint', 'yes', 'Mistake #1'],
    ['P01-02', 'part01_foundations_snr.md', 'abax', 'sweep_def', 'wick pierce + close back inside; body close beyond PrevHigh+ATR*0.2 = breakout not sweep', 'atr_mult=0.2', 'yes', ''],
    ['P01-03', 'part01_foundations_snr.md', 'abax', 'confluence_score', 'ConfluenceScore 0-4: HTF bias / sweep at zone / SNR+OB+50% / confirmation candle; require >=3, sweep mandatory', 'min_score=3', 'yes', 'grading engine anchor'],
    ['P01-04', 'part01_foundations_snr.md', 'abax', 'sequence', 'Sweep -> Zone touch -> Confirmation enforced', 'order=fixed', 'yes', ''],
    ['P01-05', 'part01_foundations_snr.md', 'abax', 'weak_zone_tolerance', '>3 wick touches without rejection -> zone WEAK -> reduce size or need stronger confirmation', 'max_touches=3', 'yes', 'rule-tolerance anchor'],
    ['P01-06', 'part01_foundations_snr.md', 'abax', 'rr_sl_tp', 'Min RR 1:1.5; SL beyond sweep extreme + buffer; TP next liquidity pool', 'min_rr=1.5', 'yes', ''],
    ['P01-07', 'part01_foundations_snr.md', 'abax', 'sessions', 'London = manipulation/sweeps; NY = expansion; avoid mid-consolidation without sweep', 'tbd_hours', 'partial', 'exact hours deferred'],
    ['P01-08', 'part01_foundations_snr.md', 'abax', 'premium_discount', 'buys only in discount, sells only in premium; EQ magnet', 'eq=range50', 'yes', ''],
    ['P01-09', 'part01_foundations_snr.md', 'abax', 'trendline_early_warning', 'trendline break = EarlyWarning only; entry needs HL + break of prior LH (MSS)', '', 'yes', ''],
    ['P02-01', 'part02_xauusd_phases_snrbasics.md', 'abax', 'snr_close_line', 'SNR drawn at Close of pivot candle, not high/low', '', 'yes', ''],
    ['P02-02', 'part02_xauusd_phases_snrbasics.md', 'abax', 'fresh_lifecycle', 'wick touch -> unfresh UseCount++; body break -> fresh again + role flip; max 2 uses; daily-gap exception', 'max_uses=2', 'yes', ''],
    ['P02-03', 'part02_xauusd_phases_snrbasics.md', 'abax', 'zone_strength', 'ZoneStrength = sweep + retest-hold; >=2 = HIGH_RELIABILITY re-entry allowed', 'threshold=2', 'yes', ''],
    ['P02-04', 'part02_xauusd_phases_snrbasics.md', 'abax', 'two_sweep_scopes', 'MicroSweep (prev candle H/L) vs SwingSweep (swing/equal highs); require >=1, both strongest', '', 'yes', ''],
    ['P02-05', 'part02_xauusd_phases_snrbasics.md', 'abax', 'classic_v_a', 'ClassicV buy / ClassicA sell candle patterns with tolerance ATR*0.05, pierce < ATR*0.3', 'tol=0.05atr', 'yes', ''],
    ['P02-06', 'part02_xauusd_phases_snrbasics.md', 'abax', 'premium_inhibit', 'inhibit new longs above RangeEQ+buffer (profit-taking-only mode)', '', 'yes', 'management rule'],
    ['P02-07', 'part02_xauusd_phases_snrbasics.md', 'abax', 'storyline_roadblock', 'daily bearish blocks weekly bullish; lower-TF storyline gates higher-TF', '', 'yes', ''],
    ['P02-08', 'part02_xauusd_phases_snrbasics.md', 'abax', 'fifty_method', 'HTF zone touch -> LTF OB50 + sweep -> SL ~10 pips; HIGH_RISK tag; HTF bias required', 'sl=10pips', 'partial', ''],
    ['P02-09', 'part02_xauusd_phases_snrbasics.md', 'abax', 'bos_namespaces', 'BOS_LTF / BOS_INTERNAL / BOS_HTF; only HTF BOS flips bias', '', 'yes', ''],
    ['P03-01', 'part03_fresh_storyline_50method.md', 'abax', 'touch_state', 'TouchState FRESH/WICK_TOUCHED/BODY_TOUCHED; 2nd wick touch = half size + sweep required', '', 'yes', 'grade/risk scaling anchor'],
    ['P03-02', 'part03_fresh_storyline_50method.md', 'abax', 'll_ul_band', 'zone = [LL,UL]; buy valid iff Close > LL (wick below allowed)', '', 'yes', ''],
    ['P03-03', 'part03_fresh_storyline_50method.md', 'abax', 'fake_vs_brake', 'wick+close-back = FAKE (no flip); body close + displacement >1.2ATR = BRAKE (flip RBS/SBR)', 'disp=1.2atr', 'yes', ''],
    ['P03-04', 'part03_fresh_storyline_50method.md', 'abax', 'rbs_sbr_close_rule', 'flip requires close beyond, not wick; retest+rejection = entry', '', 'yes', ''],
    ['P03-05', 'part03_fresh_storyline_50method.md', 'abax', 'rbs_strength', 'TF weight M15=1/H1=2/H4=3/D1=4 + sweep + OB + FVG; require >=3 full size', 'min=3', 'yes', ''],
    ['P03-06', 'part03_fresh_storyline_50method.md', 'abax', 'qm_family', 'QM 4-step; QMR wait BOS+retest+rejection; QMM fake break of QML; QMC fake continuation + break-retest', '', 'yes', 'QM module source'],
    ['P03-07', 'part03_fresh_storyline_50method.md', 'abax', 'qm_no_chase', 'never enter fake leg; if no retest + strong continuation = momentum, chase only on retest', '', 'partial', 'psych discipline'],
    ['P04-01', 'part04_quasimodo_qmr_qmm_qmc.md', 'abax', 'qm_quality_gate', 'BOS_ATR>=0.8, retest delay>=3 bars, confirm in engulfing/pin/OB50, HTF agrees; else LOW_QUALITY halve or skip', 'bos_atr=0.8;delay=3', 'yes', 'QM module'],
    ['P04-02', 'part04_quasimodo_qmr_qmm_qmc.md', 'abax', 'qm_hesitation', 'QM forms only in uncertainty: range contraction / wick expansion / equal-touch before BOS; impulsive BOS = continuation', '', 'yes', 'psych nuance'],
    ['P04-03', 'part04_quasimodo_qmr_qmm_qmc.md', 'abax', 'session_weight', 'Asia=0.5 London=1.0 NY=1.0 Overlap=1.5; Asia entries need extra confirm', '', 'yes', 'session layer'],
    ['P04-04', 'part04_quasimodo_qmr_qmm_qmc.md', 'abax', 'oc_hidden_base', 'two same-color HTF candles (OC cluster 20-30%) -> LTF drill: OB/V/accum/volume; trade if >=2 sub-elements', 'tol=0.3atr', 'yes', ''],
    ['P04-05', 'part04_quasimodo_qmr_qmm_qmc.md', 'abax', 'trendline_rules', 'built on closes, >=3 touches, R2>0.85, equal spacing (maxGap/minGap<1.5), anchored to 4 main MSNR zones, never force', 'r2=0.85', 'yes', ''],
    ['P04-06', 'part04_quasimodo_qmr_qmm_qmc.md', 'abax', 'direction_law', 'Higher can break lower, lower cannot break higher; LTF BOS vs HTF = internal sweep only', '', 'yes', 'storyline gate basis'],
    ['P05-01', 'part05_ocl_hiddenbase.md', 'abax', 'ocl_qualifier', 'OCL only from key candles: body>1.5ATR and range>median*1.2; doji rejected', 'body=1.5atr', 'yes', ''],
    ['P05-02', 'part05_ocl_hiddenbase.md', 'abax', 'zone_grade_ladder', 'wick-only=C (extra sweep), OCL-only=B (session+MSS), OCL+SNR=A+; Tradeable>=4, A+>=5', 'trade=4;aplus=5', 'yes', 'grading engine'],
    ['P05-03', 'part05_ocl_hiddenbase.md', 'abax', 'separate_buffers', 'never merge wick level and OCL zone layers (Buf_Wick vs Buf_OCL_*)', '', 'yes', ''],
    ['P06-01', 'part06_trendlines_confluence_direction.md', 'abax', 'qml_tl_stack', 'QML + nearest SNR (40pts) + nearest TL (>=2 touches) sides agree = strongest reversal zone', 'tol=40pts', 'yes', ''],
    ['P06-02', 'part06_trendlines_confluence_direction.md', 'abax', 'qmx', 'TL geometrically crosses QM/SNR at point3 + engulfing before point3; stricter than QML-TL, +1 score', '', 'yes', ''],
    ['P06-03', 'part06_trendlines_confluence_direction.md', 'abax', 'limit_no_candle', 'confluence stack complete -> limit entry without confirmation candle (parameterized)', 'param', 'partial', 'deviation from part01 logged'],
    ['P06-04', 'part06_trendlines_confluence_direction.md', 'abax', 'side_agreement', 'confluence requires same-direction agreement; counter-trend cross = conflict not confluence', '', 'yes', ''],
    ['P07-01', 'part07_ce_equilibrium.md', 'abax', 'ce_definition', 'CE = (High+Low)/2 INCLUDING wicks; body-mid = OB-mid different object', '', 'yes', ''],
    ['P07-02', 'part07_ce_equilibrium.md', 'abax', 'ce_45_50', 'price returns to 45-50% of range to test strength before continue/reverse', 'zone=0.45-0.50', 'yes', ''],
    ['P07-03', 'part07_ce_equilibrium.md', 'abax', 'ce_magnet_cluster', 'CE + OBmid + FVGmid within 0.2ATR = magnet; trade cluster zone edge + confirm', 'tol=0.2atr', 'yes', ''],
    ['P07-04', 'part07_ce_equilibrium.md', 'abax', 'ce_chop_invalidation', 'CE invalid after 3 crosses in 20 bars (fair value, not S/R)', 'cross=3/20', 'yes', ''],
    ['P07-05', 'part07_ce_equilibrium.md', 'abax', 'ce_strong_filter', 'Range>0.8ATR, Body>0.6Range, born from displacement/engulf/BOS, session != Asia', '', 'yes', ''],
    ['P08-01', 'part08_smt_quarterly.md', 'abax', 'smt_divergence', 'XAU/XAG (and 3 forex pairs): fake extreme vs holder; follow the refuser; compare 2 swings 50-bar lookback tol 0.3ATR', 'corr>0.70', 'yes', 'needs 2nd symbol'],
    ['P08-02', 'part08_smt_quarterly.md', 'abax', 'smt_veto', 'SMT agrees +1.5 score; contradicts -> skip or halve size (-1.5)', '', 'yes', 'grading input'],
    ['P08-03', 'part08_smt_quarterly.md', 'abax', 'amdx_cycle', 'A=range ADX<20, M=sweep of A extreme + quick return, D=displacement+BOS, X=reset; detect by price not clock', '', 'yes', 'session timing layer'],
    ['P08-04', 'part08_smt_quarterly.md', 'abax', 'trade_d_not_m', 'M = signal, D = entry; never chase late-phase', '', 'yes', ''],
    ['P09-01', 'part09_daily_bias_profile.md', 'abax', 'pd_gate', 'PD=(price-low)/(high-low) on D1/H4; long only discount (or premium + ERL swept + SMT + MSS flip); EQ = no bias', '', 'yes', 'daily bias gate'],
    ['P09-02', 'part09_daily_bias_profile.md', 'abax', 'profiles', 'London reversal/NY continuation, NY reversal, NY Judas, Seek&Destroy; detect, do not force', '', 'partial', 'journaling + gating'],
    ['P09-03', 'part09_daily_bias_profile.md', 'abax', 'judas_rule', 'NY 09:30 spike: wick>0.6, close back inside <=3 M15 bars, SMT holds -> fade opposite; SL beyond Judas extreme +0.3ATR', '', 'yes', ''],
    ['P09-04', 'part09_daily_bias_profile.md', 'abax', 'seek_destroy', 'DayRange<0.7*ATR_D1 + both sides swept + no displacement close -> scalp to EQ only, half size', 'size=0.5', 'yes', ''],
    ['P09-05', 'part09_daily_bias_profile.md', 'abax', 'first_second_opportunity', '1st NY liquidity take often fake (fade only with SMT+PD extreme); 2nd after retest+MSS = trade', '', 'yes', ''],
    ['P10-01', 'part10_fibo_synthesis.md', 'abax', 'abay_fibo_levels', 'custom levels 0/1/1.47/1.55 entry shelf, -0.72/-0.75/-0.78 invalidation SL, extensions 2.235-4.733 TPs; never classic 0.618', '', 'yes', 'TP ladder source'],
    ['P10-02', 'part10_fibo_synthesis.md', 'abax', 'htf_shelf_anchor', 'Fibo low anchors to 6-way HTF shelf (key+OB+RBS+FVG+QMM+classicV); HTF_Score>=3 anchor, >=4 A+', '', 'yes', ''],
    ['P11-01', 'part11_entry_tp_sl_psychology.md', 'abax', 'entry_models_AH', 'A reversal, B OCL retest/flip, C QML-SNR-TL, D QMX, E CE cluster, F SMT fade, G Judas fade, H Fibo continuation', '', 'yes', 'full catalogue'],
    ['P11-02', 'part11_entry_tp_sl_psychology.md', 'abax', 'confirmation_ladder', 'virgin touch=watch; 1 confirm=standard (score>=4); 2 confirms=A+ full (>=5); score>=5 stack allows plan-limit', '', 'yes', 'grading core'],
    ['P11-03', 'part11_entry_tp_sl_psychology.md', 'abax', 'partials', 'TP1 IRL/1:1.5RR -> close 50% + SL to breakeven; TP2 ERL/Fibo2.6-2.88 -> close 30% + trail LTF BOS; TP3 runner 20%', '50/30/20', 'yes', 'management layer core'],
    ['P11-04', 'part11_entry_tp_sl_psychology.md', 'abax', 'sl_beyond_fake', 'SL beyond fake extreme +/- (0.3*ATR + spread*1.5); per-model variants; never average losers', '', 'yes', ''],
    ['P11-05', 'part11_entry_tp_sl_psychology.md', 'abax', 'daily_loss_cap', 'max 2 losses/day or -X% -> stop; max 1 re-entry per zone (anti-revenge, anti-chase)', '', 'yes', 'psychology filter'],
    ['P11-06', 'part11_entry_tp_sl_psychology.md', 'abax', 'score_size_map', '>=5 A+ full size; 4 = 0.7x; <4 no trade; S&D caps 0.5x', '', 'yes', 'risk scaling'],
    ['PH1-01', 'MSNR_Part1_Top_Down_Analysis.md', 'phoenix', 'topdown_state', 'H1 bias/POI -> M15 setup (BOS->TS->MSS) -> M5/M1 execution; two parallel structure mappers', '', 'yes', ''],
    ['PH2-01', 'MSNR_Part2_Market_Structure_BOS.md', 'phoenix', 'bos_body_close', 'BOS = body close beyond prior swing; wick = sweep not BOS; momentum filter on breakout body size', '', 'yes', ''],
    ['PH2-02', 'MSNR_Part2_Market_Structure_BOS.md', 'phoenix', 'continuous_bos', 'require 2-3 consecutive directional BOS before hunting reversal setups', 'min=2-3', 'yes', ''],
    ['PH3-01', 'MSNR_Part3_Liquidity_and_Target_Sweeps.md', 'phoenix', 'eqh_pools', 'EQH/EQL = >=2 swing points within 2-3 pips = massive pool; time-based pools mapped daily', 'band=2-3pips', 'yes', ''],
    ['PH3-02', 'MSNR_Part3_Liquidity_and_Target_Sweeps.md', 'phoenix', 'idm_concept', 'minor swing below main POI swept before POI tap = higher probability', '', 'yes', ''],
    ['PH4-01', 'MSNR_Part4_Market_Structure_Shift_MSS.md', 'phoenix', 'mss_trigger', 'MSS level = last swing low before TS high, locked at TS; body close + impulse required', '', 'yes', ''],
    ['PH5-01', 'MSNR_Part5_Retracements_and_Triggers.md', 'phoenix', 'doji_trigger', 'body <15% of range, in premium, at resistance zone = trigger', 'ratio=0.15', 'yes', ''],
    ['PH5-02', 'MSNR_Part5_Retracements_and_Triggers.md', 'phoenix', 'tight_sl_gate', 'SL ~10 pips above TS/Doji + buffer; SKIP if required SL distance > ~15 pips', 'max=15pips', 'yes', 'core risk rule'],
    ['PH7-01', 'MSNR_Part7_Advanced_Entry_Patterns.md', 'phoenix', 'ocl_body', 'OCL = Max(Open,Close) of swing-peak candle; bodies respected by institutions', '', 'yes', ''],
    ['PH7-02', 'MSNR_Part7_Advanced_Entry_Patterns.md', 'phoenix', 'perfect_storm', 'SBR level + specific OCL + Doji on tap = entry (triple confluence)', '', 'yes', ''],
    ['PH8-01', 'MSNR_Part8_Wick_Analysis_and_50_Percent.md', 'phoenix', 'wick_tip_sl', 'SL a fraction beyond sweep wick tip; violation = thesis invalid', '', 'yes', ''],
    ['PH8-02', 'MSNR_Part8_Wick_Analysis_and_50_Percent.md', 'phoenix', 'wick_50', 'institutional wick (>=3x body, during sweep/BOS) midpoint = Wick_50_Level POI; confluence OCL+50%+TL', 'wicks>=3x body', 'yes', ''],
    ['PH9-01', 'MSNR_Part9_Refining_Entries_M1_M5.md', 'phoenix', 'squeeze_filter', 'M1 ATR of last 5 bars compressing into POI = probability up; blasting in = cancel order', 'bars=5', 'yes', ''],
    ['PH9-02', 'MSNR_Part9_Refining_Entries_M1_M5.md', 'phoenix', 'ob_must_damage', 'OB valid only if associated with sweep/BOS structural damage', '', 'yes', ''],
    ['PH10-01', 'MSNR_Part10_Trade_Management_Psychology.md', 'phoenix', 'entry_zone_buffer', 'EntryZone = OCL +/- 2 pips; trigger inside band suffices (anti "too accurate")', 'band=2pips', 'yes', 'tolerance layer'],
    ['PH10-02', 'MSNR_Part10_Trade_Management_Psychology.md', 'phoenix', 'fractional_scale_in', '1/3 at FVG edge + 1/3 at 50% + 1/3 at OCL extreme', 'thirds', 'yes', ''],
    ['PH10-03', 'MSNR_Part10_Trade_Management_Psychology.md', 'phoenix', 'runner_mgmt', 'close 50% at first SSL pool -> SL to BE -> trail rest behind M15 lower highs (fractal)', '50%+BE+trail', 'yes', 'management core'],
    ['PH10-04', 'MSNR_Part10_Trade_Management_Psychology.md', 'phoenix', 'reliability_threshold', 'structure narrative from M15/M5 only; M1 = trigger after green light; M1-only signal = false', '', 'yes', ''],
    ['PH10-05', 'MSNR_Part10_Trade_Management_Psychology.md', 'phoenix', 'tp_above_pool', 'place TP slightly above/beyond the liquidity pool to ensure fill before bounce', '', 'yes', ''],
]

PATH = os.path.join(os.path.dirname(__file__), "strategy_rules.csv")
existing = set()
if os.path.exists(PATH):
    with io.open(PATH, encoding="utf-8") as f:
        for r in csv.reader(f):
            if r:
                existing.add(r[0])
with io.open(PATH, "a", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    added = 0
    for r in ROWS:
        if r[0] not in existing:
            w.writerow(r)
            added += 1
print(f"added {added} rules (total ids now: {len(existing) + added})")
