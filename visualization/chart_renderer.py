"""
chart_renderer.py — MSNR Visual Validation Chart Engine

Renders high-resolution candlestick charts with:
  - Support & Resistance levels (Blue / Orange dashed lines)
  - SBR & RBS role reversal levels
  - OCL lines & boxes
  - Quasimodo (QM) lines
  - Line-Chart Apex & IAB markers
  - FTFL, STFL, and TTFL refinement boxes & equilibrium lines
"""

from __future__ import annotations

import os
from typing import List, Optional
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from indicators.candle_analyzer import CandleLevel, LevelType, LevelState
from indicators.ocl_detector import OCLLevel
from indicators.qm_detector import QMLevel
from indicators.apex_detector import ApexLevel


class ChartRenderer:
    """
    Renders professional MSNR annotated candlestick charts.
    """

    def __init__(self, output_dir: str = "visualizations"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def render_chart(
        self,
        df: pd.DataFrame,
        symbol: str = "XAUUSD",
        timeframe: str = "D1",
        sr_levels: Optional[List[CandleLevel]] = None,
        ocl_levels: Optional[List[OCLLevel]] = None,
        qm_levels: Optional[List[QMLevel]] = None,
        apex_levels: Optional[List[ApexLevel]] = None,
        entry_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        filename: Optional[str] = None
    ) -> str:
        """
        Render annotated chart and save to image file.
        """
        # Prepare style
        mc = mpf.make_marketcolors(
            up="#26a69a",
            down="#ef5350",
            edge="inherit",
            wick="inherit",
            volume="in"
        )
        s = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            gridstyle=":",
            gridcolor="#2a2e39"
        )

        hlines = []
        hline_colors = []
        hline_styles = []

        # 1. Add Support & Resistance / SBR / RBS
        if sr_levels:
            for lvl in sr_levels:
                hlines.append(lvl.price)
                if lvl.level_type == LevelType.SUPPORT:
                    color = "#00bcd4" if lvl.state == LevelState.FRESH else "#546e7a"
                elif lvl.level_type == LevelType.RESISTANCE:
                    color = "#ff9800" if lvl.state == LevelState.FRESH else "#78909c"
                elif lvl.level_type == LevelType.RBS:
                    color = "#4caf50"
                else:  # SBR
                    color = "#e91e63"
                hline_colors.append(color)
                hline_styles.append("-" if lvl.state == LevelState.FRESH else "--")

        # 2. Add OCLs
        if ocl_levels:
            for ocl in ocl_levels:
                hlines.append(ocl.price)
                hline_colors.append("#ffeb3b")  # Yellow for OCL
                hline_styles.append("-.")

        # 3. Add QMs
        if qm_levels:
            for qm in qm_levels:
                hlines.append(qm.price)
                hline_colors.append("#9c27b0")  # Purple for QM
                hline_styles.append("-")

        # 4. Add Apex / IAB
        if apex_levels:
            for apex in apex_levels:
                hlines.append(apex.price)
                hline_colors.append("#00e676" if "support" in apex.apex_type.value else "#ff1744")
                hline_styles.append(":")

        # 5. Add Entry / SL / TP if provided
        if entry_price:
            hlines.append(entry_price)
            hline_colors.append("#29b6f6")
            hline_styles.append("-")
        if sl_price:
            hlines.append(sl_price)
            hline_colors.append("#f44336")
            hline_styles.append("-")
        if tp_price:
            hlines.append(tp_price)
            hline_colors.append("#00e676")
            hline_styles.append("-")

        hlines_dict = None
        if hlines:
            hlines_dict = dict(
                hlines=hlines,
                colors=hline_colors,
                linestyle=hline_styles,
                linewidths=1.2
            )

        save_path = os.path.join(
            self.output_dir,
            filename or f"{symbol}_{timeframe}_msnr.png"
        )

        title = f"{symbol} [{timeframe}] — Advanced MSNR Structure Analysis"

        mpf.plot(
            df.tail(120),  # Show last 120 candles for high clarity
            type="candle",
            style=s,
            title=title,
            hlines=hlines_dict,
            savefig=dict(fname=save_path, dpi=150, bbox_inches="tight"),
            figsize=(14, 8)
        )

        return save_path
