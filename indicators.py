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


def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line, histogram"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """Bollinger Bands: upper, middle (SMA), lower"""
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return upper, middle, lower


def detect_rsi_divergence(close: pd.Series, rsi: pd.Series, lookback: int = 20) -> str:
    """
    تشخیص ساده واگرایی RSI در N کندل اخیر.
    خروجی: 'bullish', 'bearish', یا None
    - واگرایی صعودی: قیمت کف پایین‌تر می‌سازد ولی RSI کف بالاتر می‌سازد (ضعف فروشندگان)
    - واگرایی نزولی: قیمت سقف بالاتر می‌سازد ولی RSI سقف پایین‌تر می‌سازد (ضعف خریداران)
    """
    if len(close) < lookback + 5:
        return None

    recent_close = close.iloc[-lookback:]
    recent_rsi = rsi.iloc[-lookback:]

    price_min_idx = recent_close.idxmin()
    price_max_idx = recent_close.idxmax()

    half = lookback // 2
    first_half_close = recent_close.iloc[:half]
    second_half_close = recent_close.iloc[half:]
    first_half_rsi = recent_rsi.iloc[:half]
    second_half_rsi = recent_rsi.iloc[half:]

    if len(first_half_close) == 0 or len(second_half_close) == 0:
        return None

    # واگرایی صعودی: کف قیمت دوم پایین‌تر از کف اول، ولی کف RSI دوم بالاتر
    if second_half_close.min() < first_half_close.min() and second_half_rsi.min() > first_half_rsi.min():
        return "bullish"

    # واگرایی نزولی: سقف قیمت دوم بالاتر از سقف اول، ولی سقف RSI دوم پایین‌تر
    if second_half_close.max() > first_half_close.max() and second_half_rsi.max() < first_half_rsi.max():
        return "bearish"

    return None


def detect_volume_spike(volume: pd.Series, period: int = 20, spike_mult: float = 2.5) -> dict:
    """تشخیص جهش غیرعادی حجم نسبت به میانگین"""
    if len(volume) < period + 1:
        return {"is_spike": False, "ratio": 1.0}

    vol_ma = volume.rolling(period).mean().iloc[-2]  # میانگین بدون احتساب کندل فعلی
    current_vol = volume.iloc[-1]

    if not vol_ma or vol_ma == 0:
        return {"is_spike": False, "ratio": 1.0}

    ratio = current_vol / vol_ma
    return {"is_spike": ratio >= spike_mult, "ratio": round(ratio, 2)}


def compute_correlation(series_a: pd.Series, series_b: pd.Series) -> float:
    """همبستگی پیرسون بین دو سری قیمت (بازدهی درصدی) - عددی بین -1 و 1"""
    a = series_a.pct_change().dropna()
    b = series_b.pct_change().dropna()
    n = min(len(a), len(b))
    if n < 10:
        return 0.0
    corr = a.iloc[-n:].reset_index(drop=True).corr(b.iloc[-n:].reset_index(drop=True))
    return round(float(corr), 2) if pd.notna(corr) else 0.0


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
