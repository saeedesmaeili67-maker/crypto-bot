# -*- coding: utf-8 -*-
"""
تولید چارت تصویری تحلیل (کندل + خطوط + RSI + حجم)
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from config import OUTPUT_DIR
from analysis import AnalysisResult


def build_chart_image(result: AnalysisResult) -> str:
    df = result.df.copy()
    df.index.name = "Date"

    add_plots = []

    rsi_panel = 2
    vol_panel = 1

    add_plots.append(mpf.make_addplot(result.rsi, panel=rsi_panel, color="purple", ylabel="RSI (14)"))
    add_plots.append(mpf.make_addplot([70] * len(df), panel=rsi_panel, color="red", linestyle="--", width=0.6))
    add_plots.append(mpf.make_addplot([30] * len(df), panel=rsi_panel, color="green", linestyle="--", width=0.6))

    # خطوط افقی: مقاومت‌ها، حمایت‌ها، Entry/SL/TP
    hlines = []
    hline_colors = []
    hline_styles = []

    for r in result.resistance_levels:
        hlines.append(r)
        hline_colors.append("#c0392b")
        hline_styles.append("--")

    for s in result.support_levels:
        hlines.append(s)
        hline_colors.append("#27ae60")
        hline_styles.append("--")

    hlines.append(result.breakout_level)
    hline_colors.append("#f39c12")
    hline_styles.append("-")

    hlines.append(result.entry)
    hline_colors.append("#2980b9")
    hline_styles.append("-")

    hlines.append(result.stop_loss)
    hline_colors.append("#e74c3c")
    hline_styles.append("-")

    for tp in result.tp_levels:
        hlines.append(tp)
        hline_colors.append("#2ecc71")
        hline_styles.append("-")

    # خطوط روند (شیب‌دار) به صورت alines
    alines = []
    aline_colors = []
    n = len(df)

    if result.down_trend is not None:
        slope, intercept, x0, x1 = result.down_trend
        y0 = slope * x0 + intercept
        y1 = slope * (n - 1) + intercept
        p0 = (df.index[int(x0)], y0)
        p1 = (df.index[n - 1], y1)
        alines.append([p0, p1])
        aline_colors.append("#f1c40f")

    if result.up_trend is not None:
        slope, intercept, x0, x1 = result.up_trend
        y0 = slope * x0 + intercept
        y1 = slope * (n - 1) + intercept
        p0 = (df.index[int(x0)], y0)
        p1 = (df.index[n - 1], y1)
        alines.append([p0, p1])
        aline_colors.append("#3498db")

    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit", wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc, gridstyle="", facecolor="#0e1621", figcolor="#0e1621")

    filename = os.path.join(OUTPUT_DIR, f"{result.symbol.replace('/', '_')}_chart.png")

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        addplot=add_plots,
        volume=True,
        panel_ratios=(3, 1, 1),
        hlines=dict(hlines=hlines, colors=hline_colors, linestyle=hline_styles, linewidths=0.9),
        alines=dict(alines=alines, colors=aline_colors, linewidths=1.2) if alines else None,
        figsize=(11, 9),
        returnfig=True,
        title=f"\n{result.symbol} · {result.entry:.5g} Entry",
    )

    fig.savefig(filename, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return filename
