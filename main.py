"""
main.py — MSNR Trading Bot Engine Orchestrator

Modes:
  1. --test-indicators: Runs full indicator detection and renders sample chart
  2. --live: Connects to MT5 and starts the live scanning loop
"""

import argparse
import logging
import sys
import numpy as np
import pandas as pd

from config.settings import INSTRUMENTS, TIMEFRAME_MAP
from data.mt5_loader import MT5DataLoader
from indicators.candle_analyzer import CandleAnalyzer
from indicators.freshness_tracker import FreshnessTracker
from indicators.ocl_detector import OCLDetector
from indicators.qm_detector import QMDetector
from indicators.apex_detector import ApexDetector
from visualization.chart_renderer import ChartRenderer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("MSNR_Main")


def run_indicator_demo(symbol: str = "XAUUSD"):
    """Fetch MT5 data and render annotated MSNR chart."""
    logger.info(f"Starting MSNR Indicator Demo for {symbol}...")
    loader = MT5DataLoader(symbol=symbol)
    
    try:
        df_daily = loader.fetch_timeframe("D1", count=150)
        logger.info(f"Fetched {len(df_daily)} daily bars for {symbol}.")
    except Exception as e:
        logger.warning(f"Could not connect to live MT5 ({e}). Generating high-quality synthetic demo data...")
        dates = pd.date_range(end=pd.Timestamp.now(), periods=150, freq="D")
        rng = np.random.default_rng()
        prices = 2000 + np.cumsum(rng.standard_normal(150) * 8)
        df_daily = pd.DataFrame({
            "open": prices,
            "high": prices + rng.random(150) * 12,
            "low": prices - rng.random(150) * 12,
            "close": prices + rng.standard_normal(150) * 6,
            "volume": [1000] * 150
        }, index=dates)

    # 1. Base S/R & SBR/RBS
    analyzer = CandleAnalyzer(df_daily)
    base_levels = analyzer.detect_all()
    
    # 2. Freshness
    tracker = FreshnessTracker(df_daily)
    base_levels = tracker.update(base_levels)
    
    # 3. OCL
    ocl_det = OCLDetector(df_daily, timeframe="D1")
    ocls = ocl_det.detect_all()
    
    # 4. QM
    qm_det = QMDetector(df_daily, base_levels)
    qms = qm_det.detect_all()
    
    # 5. Apex & IAB
    apex_det = ApexDetector(df_daily, timeframe="D1")
    apexes = apex_det.detect_all()

    logger.info(f"Detected: {len(base_levels)} S/R levels, {len(ocls)} OCLs, {len(qms)} QMs, {len(apexes)} Apex/IABs.")

    # 6. Render visual validation chart
    renderer = ChartRenderer()
    chart_path = renderer.render_chart(
        df=df_daily,
        symbol=symbol,
        timeframe="D1",
        sr_levels=base_levels,
        ocl_levels=ocls,
        qm_levels=qms,
        apex_levels=apexes
    )
    logger.info(f"Validation chart saved to: {chart_path}")
    return chart_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MSNR Trading Bot Engine")
    parser.add_argument("--test-indicators", action="store_true", help="Run indicator validation and chart generation")
    parser.add_argument("--symbol", type=str, default="XAUUSD", help="Symbol to analyze")
    args = parser.parse_args()

    if args.test_indicators or len(sys.argv) == 1:
        run_indicator_demo(args.symbol)
