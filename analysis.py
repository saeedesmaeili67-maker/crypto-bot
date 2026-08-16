# -*- coding: utf-8 -*-
"""
موتور تحلیل: ترکیب داده و اندیکاتورها برای تولید
Entry/SL/TP، سناریوهای خرید/فروش، امتیاز تایم‌فریم‌ها و فیلتر بازار BTC
"""

import numpy as np
import pandas as pd

from config import (
    MAIN_TIMEFRAME, MAIN_LIMIT, SCORE_TIMEFRAMES, SCORE_LIMIT,
    RSI_PERIOD, VOLUME_MA_PERIOD, BTC_SYMBOL,
)
from data_fetcher import fetch_ohlcv_df
from indicators import (
    compute_rsi, compute_volume_ma, get_support_resistance_zones, fit_trendline, find_swing_points,
    compute_macd, compute_bollinger_bands, detect_rsi_divergence, detect_volume_spike, compute_correlation,
)
from whale_detector import build_whale_info
from patterns import detect_patterns, patterns_near_level
from structure import multi_timeframe_structure, overall_structure_bias


class AnalysisResult:
    def __init__(self):
        self.symbol = None
        self.df = None
        self.rsi = None
        self.volume_ma = None
        self.resistance_levels = []
        self.support_levels = []
        self.high_idx = None
        self.low_idx = None
        self.up_trend = None   # (slope, intercept, x0, x1) خط روند صعودی از کف‌ها
        self.down_trend = None  # خط روند نزولی از سقف‌ها
        self.entry = None
        self.stop_loss = None
        self.tp_levels = []
        self.breakout_level = None
        self.main_support = None
        self.risk_reward = None
        self.capital = None
        self.coin_amount = None
        self.position_value = None
        self.timeframe_scores = {}
        self.final_decision = "WAIT"
        self.btc_scores = {}
        self.btc_state = "NEUTRAL"
        self.market_condition = ""
        self.whale_info = None

        # ---- افزوده‌های بسته تحلیل قوی‌تر ----
        self.macd_line = None
        self.macd_signal = None
        self.macd_hist = None
        self.macd_cross = None          # 'bullish_cross' / 'bearish_cross' / None
        self.bb_upper = None
        self.bb_middle = None
        self.bb_lower = None
        self.bb_squeeze = False
        self.rsi_divergence = None      # 'bullish' / 'bearish' / None
        self.volume_spike = {"is_spike": False, "ratio": 1.0}
        self.patterns = []
        self.patterns_at_support = []
        self.patterns_at_resistance = []
        self.fake_breakout_risk = False
        self.btc_correlation = 0.0
        self.trading_session = ""
        self.risk_percent = None
        self.risk_amount_usd = None
        self.mtf_confirmed = None       # آیا تایم‌فریم بزرگ‌تر جهت سیگنال را تایید می‌کند

        # ---- ساختار بازار چند تایم‌فریمی (5D/1D/4H/30m/15m) ----
        self.market_structure = {}
        self.structure_bias = None


def analyze_symbol(exchange, symbol: str, entry_price: float, capital: float, risk_percent: float = None) -> AnalysisResult:
    result = AnalysisResult()
    result.symbol = symbol
    result.capital = capital
    result.entry = entry_price
    result.risk_percent = risk_percent

    df = fetch_ohlcv_df(exchange, symbol, MAIN_TIMEFRAME, MAIN_LIMIT)
    result.df = df

    result.rsi = compute_rsi(df["close"], RSI_PERIOD)
    result.volume_ma = compute_volume_ma(df["volume"], VOLUME_MA_PERIOD)

    # ---- اندیکاتورهای جدید ----
    result.macd_line, result.macd_signal, result.macd_hist = compute_macd(df["close"])
    result.macd_cross = _detect_macd_cross(result.macd_line, result.macd_signal)

    result.bb_upper, result.bb_middle, result.bb_lower = compute_bollinger_bands(df["close"])
    result.bb_squeeze = _detect_bb_squeeze(result.bb_upper, result.bb_lower, result.bb_middle)

    result.rsi_divergence = detect_rsi_divergence(df["close"], result.rsi)
    result.volume_spike = detect_volume_spike(df["volume"])

    resistance_levels, support_levels, high_idx, low_idx = get_support_resistance_zones(df)
    result.resistance_levels = resistance_levels
    result.support_levels = support_levels
    result.high_idx = high_idx
    result.low_idx = low_idx

    # خط روند نزولی از سقف‌های اخیر (برای تشخیص خط مقاومت شیب‌دار)
    if len(high_idx) >= 2:
        recent_highs_idx = high_idx[-4:]
        slope, intercept = fit_trendline(recent_highs_idx.astype(float), df["high"].values[recent_highs_idx])
        result.down_trend = (slope, intercept, recent_highs_idx[0], len(df) - 1)

    # خط روند صعودی از کف‌های اخیر
    if len(low_idx) >= 2:
        recent_lows_idx = low_idx[-4:]
        slope, intercept = fit_trendline(recent_lows_idx.astype(float), df["low"].values[recent_lows_idx])
        result.up_trend = (slope, intercept, recent_lows_idx[0], len(df) - 1)

    current_price = df["close"].iloc[-1]

    # سطح شکست = نزدیک‌ترین مقاومت بالای قیمت فعلی (یا بالای Entry)
    ref_price = max(current_price, entry_price)
    resistances_above = [r for r in result.resistance_levels if r > ref_price * 0.995]
    result.breakout_level = min(resistances_above) if resistances_above else (
        result.resistance_levels[0] if result.resistance_levels else ref_price * 1.03
    )

    # حمایت اصلی = نزدیک‌ترین حمایت زیر Entry
    supports_below = [s for s in result.support_levels if s < entry_price]
    result.main_support = max(supports_below) if supports_below else (
        result.support_levels[0] if result.support_levels else entry_price * 0.95
    )

    # حد ضرر: کمی پایین‌تر از حمایت اصلی (بافر ۲.۵٪ فاصله ساختاری)
    result.stop_loss = result.main_support * 0.985

    # تارگت‌ها: سطح شکست + دو مقاومت بالاتر (یا پروجکشن بر اساس فاصله ریسک)
    risk = entry_price - result.stop_loss
    tp_candidates = sorted(set([r for r in result.resistance_levels if r > entry_price]))
    if not tp_candidates:
        tp_candidates = [entry_price + risk * 2, entry_price + risk * 4, entry_price + risk * 7]
    while len(tp_candidates) < 3:
        last = tp_candidates[-1] if tp_candidates else entry_price + risk * 2
        tp_candidates.append(last * 1.12)
    result.tp_levels = tp_candidates[:3]

    if risk > 0:
        result.risk_reward = (result.tp_levels[0] - entry_price) / risk

    # ---- محاسبه حجم پوزیشن ----
    if risk_percent and risk > 0:
        # بر اساس درصد ریسک: مقدار سرمایه‌ای که حاضریم از دست بدهیم / فاصله ریسک به ازای هر واحد
        result.risk_amount_usd = capital * (risk_percent / 100)
        risk_per_unit_pct = risk / entry_price
        position_value = result.risk_amount_usd / risk_per_unit_pct if risk_per_unit_pct > 0 else capital
        position_value = min(position_value, capital)  # نمی‌تواند از کل سرمایه بیشتر شود
        result.coin_amount = position_value / entry_price
        result.position_value = position_value
    else:
        result.coin_amount = capital / entry_price if entry_price else 0
        result.position_value = capital

    # ---- الگوهای کندل‌استیک ----
    result.patterns = detect_patterns(df)
    result.patterns_at_support = patterns_near_level(result.patterns, df, result.main_support)
    result.patterns_at_resistance = patterns_near_level(result.patterns, df, result.breakout_level)

    # ---- تشخیص شکست کاذب ----
    result.fake_breakout_risk = _check_fake_breakout(df, result.breakout_level, result.volume_ma)

    # ---- جلسه معاملاتی فعلی ----
    result.trading_session = _current_trading_session()

    # امتیازدهی چند تایم‌فریمی روی همین نماد
    result.timeframe_scores = _score_all_timeframes(exchange, symbol)
    result.final_decision = _combine_decision(result.timeframe_scores)

    # ---- تایید چند تایم‌فریمی (روزانه در برابر جهت سیگنال اصلی) ----
    result.mtf_confirmed = _check_mtf_confirmation(result.timeframe_scores, result.final_decision)

    # فیلتر بازار بر اساس بیت‌کوین
    result.btc_scores = _score_symbol_timeframes(exchange, BTC_SYMBOL, ["4h", "1d"])
    result.btc_state, result.market_condition = _btc_state(result.btc_scores)

    # ---- همبستگی با بیت‌کوین ----
    if symbol != BTC_SYMBOL:
        try:
            btc_df = fetch_ohlcv_df(exchange, BTC_SYMBOL, MAIN_TIMEFRAME, MAIN_LIMIT)
            result.btc_correlation = compute_correlation(df["close"], btc_df["close"])
        except Exception:
            result.btc_correlation = 0.0

    # ---- تشخیص نهنگ‌ها ----
    try:
        result.whale_info = build_whale_info(exchange, symbol)
    except Exception:
        result.whale_info = None

    # ---- ساختار بازار چند تایم‌فریمی ----
    try:
        result.market_structure = multi_timeframe_structure(exchange, symbol)
        result.structure_bias = overall_structure_bias(result.market_structure)
    except Exception:
        result.market_structure = {}
        result.structure_bias = None

    return result


def _detect_macd_cross(macd_line: pd.Series, signal_line: pd.Series) -> str:
    """تشخیص تقاطع اخیر بین خط MACD و خط سیگنال"""
    if len(macd_line) < 2:
        return None
    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    if prev_diff < 0 and curr_diff > 0:
        return "bullish_cross"
    if prev_diff > 0 and curr_diff < 0:
        return "bearish_cross"
    return None


def _detect_bb_squeeze(upper: pd.Series, lower: pd.Series, middle: pd.Series, lookback: int = 30) -> bool:
    """تشخیص فشردگی باندهای بولینگر (نوسان کم = احتمال حرکت بزرگ در راه است)"""
    if len(upper) < lookback:
        return False
    width = (upper - lower) / middle
    current_width = width.iloc[-1]
    avg_width = width.iloc[-lookback:].mean()
    if pd.isna(current_width) or pd.isna(avg_width) or avg_width == 0:
        return False
    return current_width < avg_width * 0.6


def _check_fake_breakout(df: pd.DataFrame, breakout_level: float, volume_ma: pd.Series) -> bool:
    """
    بررسی می‌کند که آیا آخرین شکست سطح مقاومت با حجم کافی همراه بوده یا خیر.
    اگر قیمت اخیراً از سطح رد شده ولی حجم پایین‌تر از میانگین بوده، ریسک شکست کاذب بالاست.
    """
    if breakout_level is None or len(df) < 3:
        return False

    last_closes = df["close"].iloc[-3:]
    crossed_above = (last_closes > breakout_level).any()
    if not crossed_above:
        return False

    last_volume = df["volume"].iloc[-1]
    avg_volume = volume_ma.iloc[-2] if len(volume_ma) >= 2 else None
    if avg_volume and last_volume < avg_volume * 0.8:
        return True

    return False


def _current_trading_session() -> str:
    """بر اساس ساعت UTC فعلی، جلسه معاملاتی فعال را تخمین می‌زند"""
    from datetime import datetime, timezone
    hour = datetime.now(timezone.utc).hour

    if 0 <= hour < 8:
        return "آسیا (Asia)"
    elif 8 <= hour < 13:
        return "اروپا (London)"
    elif 13 <= hour < 21:
        return "همپوشانی اروپا-آمریکا (پرحجم‌ترین بازه)"
    else:
        return "آمریکا (New York)"


def _check_mtf_confirmation(timeframe_scores: dict, final_decision: str) -> bool:
    """آیا امتیاز تایم‌فریم روزانه با تصمیم نهایی هم‌جهت است؟"""
    daily = timeframe_scores.get("1d")
    if not daily:
        return None
    if "BUY" in final_decision and daily["score"] >= 55:
        return True
    if "AVOID" in final_decision and daily["score"] <= 45:
        return True
    if "BUY" in final_decision and daily["score"] < 55:
        return False
    if "AVOID" in final_decision and daily["score"] > 45:
        return False
    return None


def _score_timeframe(df: pd.DataFrame) -> int:
    """
    امتیاز ۰ تا ۱۰۰ بر اساس ترکیب روند (EMA20 در برابر EMA50)،
    موقعیت RSI و حجم نسبت به میانگین
    """
    if len(df) < 55:
        return 50

    close = df["close"]
    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    rsi = compute_rsi(close, RSI_PERIOD).iloc[-1]
    vol = df["volume"].iloc[-1]
    vol_ma = df["volume"].rolling(20).mean().iloc[-1]

    score = 50

    # روند
    if ema20 > ema50:
        score += 15
    else:
        score -= 15

    # RSI: منطقه سالم صعودی بین ۴۵ تا ۶۵ امتیاز بیشتر می‌گیرد
    if 45 <= rsi <= 65:
        score += 15
    elif rsi > 70:
        score -= 10  # اشباع خرید
    elif rsi < 35:
        score -= 10  # اشباع فروش (ریسک ادامه نزول)

    # حجم بالاتر از میانگین یعنی تایید بیشتر حرکت
    if vol_ma and vol > vol_ma:
        score += 10

    # قیمت نسبت به EMA20
    if close.iloc[-1] > ema20:
        score += 10
    else:
        score -= 10

    return int(max(0, min(100, score)))


def _score_all_timeframes(exchange, symbol: str) -> dict:
    return _score_symbol_timeframes(exchange, symbol, SCORE_TIMEFRAMES)


def _score_symbol_timeframes(exchange, symbol: str, timeframes: list) -> dict:
    scores = {}
    for tf in timeframes:
        try:
            df = fetch_ohlcv_df(exchange, symbol, tf, SCORE_LIMIT)
            s = _score_timeframe(df)
            scores[tf] = {
                "score": s,
                "verdict": _verdict_from_score(s),
            }
        except Exception:
            scores[tf] = {"score": 50, "verdict": "WAIT"}
    return scores


def _verdict_from_score(score: int) -> str:
    if score >= 65:
        return "BUY CONFIRMATION"
    if score <= 35:
        return "SELL RISK"
    return "WAIT"


def _combine_decision(scores: dict) -> str:
    if not scores:
        return "WAIT"
    avg = sum(s["score"] for s in scores.values()) / len(scores)
    if avg >= 62:
        return "BUY ON CONFIRMATION"
    if avg <= 38:
        return "AVOID / WAIT"
    return "WAIT"


def _btc_state(btc_scores: dict):
    if not btc_scores:
        return "NEUTRAL", "نامشخص"
    avg = sum(s["score"] for s in btc_scores.values()) / len(btc_scores)
    if avg >= 60:
        state = "NEUTRAL-BULLISH"
        condition = "مناسب برای خرید"
    elif avg <= 40:
        state = "NEUTRAL-BEARISH"
        condition = "احتیاط، ریسک بالا"
    else:
        state = "NEUTRAL"
        condition = "خنثی، صبر بهتر است"
    return state, condition
