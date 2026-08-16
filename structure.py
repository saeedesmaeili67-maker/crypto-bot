# -*- coding: utf-8 -*-
"""
تحلیل ساختار بازار (Market Structure) مثل یک تریدر حرفه‌ای:
- تشخیص روند از روی توالی سقف‌ها و کف‌های سوینگ (HH/HL برای صعودی، LH/LL برای نزولی)
- تشخیص شکست ساختار (Break of Structure - BOS): تایید ادامه روند
- تشخیص تغییر کاراکتر روند (Change of Character - CHoCH): هشدار برگشت زودهنگام
- پیشنهاد ناحیه ورود و خروج بر اساس ساختار
- ترکیب چند تایم‌فریم (5D, 1D, 4H, 30m, 15m) برای گرفتن تصویر کامل
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

from data_fetcher import fetch_ohlcv_df

STRUCTURE_TIMEFRAMES = {
    "5D": {"source_tf": "1d", "limit": 400, "resample": "5D"},
    "1D": {"source_tf": "1d", "limit": 120, "resample": None},
    "4H": {"source_tf": "4h", "limit": 200, "resample": None},
    "30m": {"source_tf": "30m", "limit": 200, "resample": None},
    "15m": {"source_tf": "15m", "limit": 200, "resample": None},
}


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    resampled = df.resample(rule).agg(agg).dropna()
    return resampled


def find_swings(df: pd.DataFrame, order: int = 3):
    """پیدا کردن سوینگ‌های سقف/کف و ساخت یک لیست زمانی متناوب از آن‌ها"""
    highs = df["high"].values
    lows = df["low"].values

    high_idx = argrelextrema(highs, np.greater_equal, order=order)[0]
    low_idx = argrelextrema(lows, np.less_equal, order=order)[0]

    swings = []
    for i in high_idx:
        swings.append({"index": i, "price": highs[i], "type": "high"})
    for i in low_idx:
        swings.append({"index": i, "price": lows[i], "type": "low"})

    swings.sort(key=lambda s: s["index"])

    # حذف سوینگ‌های هم‌نوع پشت‌سرهم؛ فقط شدیدترین مورد را نگه می‌داریم
    cleaned = []
    for s in swings:
        if cleaned and cleaned[-1]["type"] == s["type"]:
            if s["type"] == "high" and s["price"] > cleaned[-1]["price"]:
                cleaned[-1] = s
            elif s["type"] == "low" and s["price"] < cleaned[-1]["price"]:
                cleaned[-1] = s
        else:
            cleaned.append(s)

    return cleaned


def classify_structure(swings: list, current_price: float) -> dict:
    """
    از روی آخرین سوینگ‌ها، روند و سیگنال‌های BOS/CHoCH را تشخیص می‌دهد.
    """
    result = {
        "trend": "RANGE",
        "trend_fa": "بدون روند مشخص (رنج)",
        "bos": None,        # 'bullish' / 'bearish' / None
        "choch": None,      # 'bullish' / 'bearish' / None
        "last_swing_high": None,
        "last_swing_low": None,
        "entry_zone": None,
        "exit_zone": None,
    }

    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]

    if len(highs) < 2 or len(lows) < 2:
        return result

    last_high, prev_high = highs[-1]["price"], highs[-2]["price"]
    last_low, prev_low = lows[-1]["price"], lows[-2]["price"]

    result["last_swing_high"] = last_high
    result["last_swing_low"] = last_low

    if last_high > prev_high and last_low > prev_low:
        result["trend"] = "UPTREND"
        result["trend_fa"] = "صعودی (سقف‌ها و کف‌های بالاتر)"
    elif last_high < prev_high and last_low < prev_low:
        result["trend"] = "DOWNTREND"
        result["trend_fa"] = "نزولی (سقف‌ها و کف‌های پایین‌تر)"
    else:
        result["trend"] = "RANGE"
        result["trend_fa"] = "بدون روند مشخص (رنج)"

    # ---- BOS: تایید ادامه روند ----
    if result["trend"] == "UPTREND" and current_price > last_high:
        result["bos"] = "bullish"
    elif result["trend"] == "DOWNTREND" and current_price < last_low:
        result["bos"] = "bearish"

    # ---- CHoCH: هشدار برگشت زودهنگام ----
    if result["trend"] == "DOWNTREND" and current_price > prev_high:
        result["choch"] = "bullish"
    elif result["trend"] == "UPTREND" and current_price < prev_low:
        result["choch"] = "bearish"

    # ---- ناحیه ورود / خروج پیشنهادی ----
    if result["trend"] == "UPTREND":
        result["entry_zone"] = (last_low, (last_low + current_price) / 2)
        result["exit_zone"] = last_high
    elif result["trend"] == "DOWNTREND":
        result["entry_zone"] = ((current_price + last_high) / 2, last_high)
        result["exit_zone"] = last_low
    else:
        result["entry_zone"] = (last_low, last_high)
        result["exit_zone"] = None

    return result


def analyze_timeframe_structure(exchange, symbol: str, tf_key: str) -> dict:
    cfg = STRUCTURE_TIMEFRAMES[tf_key]
    df = fetch_ohlcv_df(exchange, symbol, cfg["source_tf"], cfg["limit"])

    if cfg["resample"]:
        df = resample_ohlcv(df, cfg["resample"])

    # order سوینگ متناسب با حجم داده تنظیم می‌شود تا سوینگ‌های معنادار پیدا شوند
    order = 3 if len(df) < 60 else 4
    swings = find_swings(df, order=order)
    current_price = float(df["close"].iloc[-1])

    structure = classify_structure(swings, current_price)
    structure["current_price"] = current_price
    structure["candle_count"] = len(df)
    return structure


def multi_timeframe_structure(exchange, symbol: str) -> dict:
    """ساختار بازار را روی همه تایم‌فریم‌های تعریف‌شده تحلیل می‌کند"""
    results = {}
    for tf_key in STRUCTURE_TIMEFRAMES:
        try:
            results[tf_key] = analyze_timeframe_structure(exchange, symbol, tf_key)
        except Exception:
            results[tf_key] = None
    return results


def overall_structure_bias(mtf_structure: dict) -> dict:
    """
    ترکیب همه تایم‌فریم‌ها به یک جمع‌بندی نهایی.
    وزن تایم‌فریم بزرگ‌تر بیشتر است (5D > 1D > 4H > 30m > 15m).
    """
    weights = {"5D": 5, "1D": 4, "4H": 3, "30m": 2, "15m": 1}
    score = 0
    max_score = 0
    aligned_tf = []
    conflicting_tf = []

    for tf, w in weights.items():
        s = mtf_structure.get(tf)
        max_score += w
        if not s:
            continue
        if s["trend"] == "UPTREND":
            score += w
            aligned_tf.append(tf)
        elif s["trend"] == "DOWNTREND":
            score -= w
            conflicting_tf.append(tf)

    if max_score == 0:
        ratio = 0
    else:
        ratio = score / max_score

    if ratio >= 0.5:
        bias = "BULLISH"
        bias_fa = "صعودی قوی — بیشتر تایم‌فریم‌های بزرگ هم‌جهت"
    elif ratio >= 0.15:
        bias = "MILD_BULLISH"
        bias_fa = "صعودی ملایم"
    elif ratio <= -0.5:
        bias = "BEARISH"
        bias_fa = "نزولی قوی — بیشتر تایم‌فریم‌های بزرگ هم‌جهت"
    elif ratio <= -0.15:
        bias = "MILD_BEARISH"
        bias_fa = "نزولی ملایم"
    else:
        bias = "MIXED"
        bias_fa = "متناقض / بدون هم‌جهتی بین تایم‌فریم‌ها — احتیاط"

    return {"bias": bias, "bias_fa": bias_fa, "score_ratio": round(ratio, 2)}
