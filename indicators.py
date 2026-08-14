# -*- coding: utf-8 -*-
"""
اندیکاتورها و تشخیص ساختار بازار: RSI، میانگین حجم، سوینگ‌ها،
خطوط روند، محدوده‌های حمایت/مقاومت و سطح شکست
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_volume_ma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(period).mean()


def find_swing_points(df: pd.DataFrame, order: int = 5):
    """پیدا کردن نقاط سوینگ (کف/سقف موضعی) با استفاده از پنجره لغزان"""
    highs = df["high"].values
    lows = df["low"].values

    high_idx = argrelextrema(highs, np.greater_equal, order=order)[0]
    low_idx = argrelextrema(lows, np.less_equal, order=order)[0]

    # حذف نقاط تکراری/چسبیده به هم
    high_idx = _dedupe(high_idx, order)
    low_idx = _dedupe(low_idx, order)

    return high_idx, low_idx


def _dedupe(idx_array, min_gap):
    if len(idx_array) == 0:
        return idx_array
    result = [idx_array[0]]
    for i in idx_array[1:]:
        if i - result[-1] >= min_gap:
            result.append(i)
    return np.array(result)


def fit_trendline(x: np.ndarray, y: np.ndarray):
    """رگرسیون خطی ساده برای برازش خط روند از میان نقاط سوینگ"""
    if len(x) < 2:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    return slope, intercept


def get_support_resistance_zones(df: pd.DataFrame, order: int = 5, n_levels: int = 3):
    """
    محدوده‌های حمایت و مقاومت را بر اساس تراکم نقاط سوینگ شناسایی می‌کند.
    خروجی: (لیست سطوح مقاومت به ترتیب صعودی، لیست سطوح حمایت به ترتیب نزولی)
    """
    high_idx, low_idx = find_swing_points(df, order=order)

    highs = df["high"].values[high_idx] if len(high_idx) else np.array([])
    lows = df["low"].values[low_idx] if len(low_idx) else np.array([])

    resistance_levels = _cluster_levels(highs, n_levels)
    support_levels = _cluster_levels(lows, n_levels, descending=True)

    return resistance_levels, support_levels, high_idx, low_idx


def _cluster_levels(values: np.ndarray, n_levels: int, descending: bool = False):
    if len(values) == 0:
        return []
    values_sorted = np.sort(values)
    if descending:
        values_sorted = values_sorted[::-1]

    clusters = []
    for v in values_sorted:
        placed = False
        for c in clusters:
            if abs(v - c["mean"]) / c["mean"] < 0.01:  # درصد نزدیکی برای هم‌گروه کردن
                c["values"].append(v)
                c["mean"] = float(np.mean(c["values"]))
                placed = True
                break
        if not placed:
            clusters.append({"mean": float(v), "values": [v]})

    clusters.sort(key=lambda c: len(c["values"]), reverse=True)
    levels = [c["mean"] for c in clusters[:n_levels]]
    levels.sort(reverse=descending)
    return levels
