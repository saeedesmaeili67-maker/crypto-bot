# -*- coding: utf-8 -*-
"""
تشخیص الگوهای کندل‌استیک برای سیگنال‌های ورود/خروج
"""

import pandas as pd


def _body(row):
    return abs(row["close"] - row["open"])


def _range(row):
    return row["high"] - row["low"]


def _upper_wick(row):
    return row["high"] - max(row["close"], row["open"])


def _lower_wick(row):
    return min(row["close"], row["open"]) - row["low"]


def _is_bullish(row):
    return row["close"] > row["open"]


def detect_patterns(df: pd.DataFrame, lookback: int = 5) -> list:
    """
    آخرین چند کندل را بررسی می‌کند و الگوهای شناخته‌شده را برمی‌گرداند.
    خروجی: لیستی از دیکشنری {name, signal, index, description}
    signal: 'bullish' یا 'bearish'
    """
    patterns = []
    n = len(df)
    if n < 3:
        return patterns

    for i in range(max(2, n - lookback), n):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        rng = _range(row)
        if rng <= 0:
            continue

        body = _body(row)
        upper = _upper_wick(row)
        lower = _lower_wick(row)
        body_ratio = body / rng

        # --- Doji: بدنه خیلی کوچک نسبت به کل رنج ---
        if body_ratio < 0.1:
            patterns.append({
                "name": "Doji",
                "name_fa": "دوجی",
                "signal": "neutral",
                "index": i,
                "description": "بلاتکلیفی بازار؛ احتمال برگشت روند",
            })

        # --- Hammer / Hanging Man: سایه پایینی بلند، بدنه کوچک بالای رنج ---
        if lower >= body * 2 and upper <= body * 0.5 and body_ratio < 0.4:
            is_downtrend = df["close"].iloc[max(0, i - 3):i].mean() > row["close"]
            if is_downtrend:
                patterns.append({
                    "name": "Hammer",
                    "name_fa": "چکش",
                    "signal": "bullish",
                    "index": i,
                    "description": "سیگنال برگشت صعودی از کف",
                })
            else:
                patterns.append({
                    "name": "Hanging Man",
                    "name_fa": "مرد آویزان",
                    "signal": "bearish",
                    "index": i,
                    "description": "هشدار برگشت نزولی از سقف",
                })

        # --- Shooting Star: سایه بالایی بلند، بدنه کوچک پایین رنج ---
        if upper >= body * 2 and lower <= body * 0.5 and body_ratio < 0.4:
            patterns.append({
                "name": "Shooting Star",
                "name_fa": "ستاره دنباله‌دار",
                "signal": "bearish",
                "index": i,
                "description": "هشدار برگشت نزولی از سقف",
            })

        # --- Engulfing: کندل فعلی کاملاً کندل قبلی را می‌بلعد ---
        prev_body_top = max(prev["close"], prev["open"])
        prev_body_bottom = min(prev["close"], prev["open"])
        cur_body_top = max(row["close"], row["open"])
        cur_body_bottom = min(row["close"], row["open"])

        if cur_body_top > prev_body_top and cur_body_bottom < prev_body_bottom:
            if _is_bullish(row) and not _is_bullish(prev):
                patterns.append({
                    "name": "Bullish Engulfing",
                    "name_fa": "انگالفینگ صعودی",
                    "signal": "bullish",
                    "index": i,
                    "description": "سیگنال قوی برگشت صعودی",
                })
            elif not _is_bullish(row) and _is_bullish(prev):
                patterns.append({
                    "name": "Bearish Engulfing",
                    "name_fa": "انگالفینگ نزولی",
                    "signal": "bearish",
                    "index": i,
                    "description": "سیگنال قوی برگشت نزولی",
                })

        # --- Morning Star / Evening Star (الگوی سه کندلی) ---
        if i >= 2:
            c0 = df.iloc[i - 2]
            c1 = df.iloc[i - 1]
            c2 = row

            c0_bearish = not _is_bullish(c0)
            c0_big = _body(c0) > _range(c0) * 0.5
            c1_small = _body(c1) < _range(c1) * 0.35 if _range(c1) > 0 else False
            c2_bullish = _is_bullish(c2)
            c2_big = _body(c2) > _range(c2) * 0.5 if _range(c2) > 0 else False

            if c0_bearish and c0_big and c1_small and c2_bullish and c2_big:
                if c2["close"] > (c0["open"] + c0["close"]) / 2:
                    patterns.append({
                        "name": "Morning Star",
                        "name_fa": "ستاره صبحگاهی",
                        "signal": "bullish",
                        "index": i,
                        "description": "الگوی سه‌کندلی برگشت صعودی قوی",
                    })

            c0_bullish = _is_bullish(c0)
            c2_bearish = not _is_bullish(c2)
            if c0_bullish and c0_big and c1_small and c2_bearish and c2_big:
                if c2["close"] < (c0["open"] + c0["close"]) / 2:
                    patterns.append({
                        "name": "Evening Star",
                        "name_fa": "ستاره عصرگاهی",
                        "signal": "bearish",
                        "index": i,
                        "description": "الگوی سه‌کندلی برگشت نزولی قوی",
                    })

    return patterns


def patterns_near_level(patterns: list, df: pd.DataFrame, level: float, tolerance_pct: float = 1.5) -> list:
    """فیلتر کردن الگوهایی که نزدیک یک سطح قیمتی خاص (حمایت/مقاومت) رخ داده‌اند"""
    result = []
    for p in patterns:
        idx = p["index"]
        row = df.iloc[idx]
        price_ref = row["close"]
        if level and abs(price_ref - level) / level * 100 <= tolerance_pct:
            result.append(p)
    return result
