# ============================================================
# SPOT AI TRADING BOT
# Binance + Telegram
# 15M / 1H / 4H
# BOS / CHoCH / Breakout / Fake Breakout
# Liquidity Sweep / Order Book / Whale Pressure
# RSI / MACD / EMA / BB / ATR / Volume
# Support / Resistance / Trendlines
# BTC Filter
# BUY / WAIT / AVOID
# Entry / SL / TP1 / TP2 / TP3
# DCA / Position Sizing
# Chart
# ============================================================

import os
import io
import math
import logging
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE"

BINANCE_URL = "https://api.binance.com"

KLINE_LIMIT = 350

# ریسک هر معامله
RISK_PERCENT = 1.0

# حداقل حجم معاملات بزرگ برای Whale Radar
WHALE_TRADE_USDT = 50_000

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("SPOT_AI")

session = requests.Session()

session.headers.update({
    "User-Agent": "Spot-AI-Trading-Bot/1.0"
})


# ============================================================
# BINANCE API
# ============================================================

def binance(endpoint, params=None):

    url = BINANCE_URL + endpoint

    response = session.get(
        url,
        params=params or {},
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict) and data.get("code"):
        raise Exception(str(data))

    return data


def normalize_symbol(symbol):

    symbol = (
        symbol
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
    )

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    return symbol


# ============================================================
# MARKET DATA
# ============================================================

def get_klines(symbol, interval, limit=KLINE_LIMIT):

    data = binance(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore"
    ]

    df = pd.DataFrame(
        data,
        columns=columns
    )

    numeric = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote"
    ]

    for column in numeric:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df["open_time"] = pd.to_datetime(
        df["open_time"],
        unit="ms"
    )

    return df


def get_order_book(symbol, limit=100):

    return binance(
        "/api/v3/depth",
        {
            "symbol": symbol,
            "limit": limit
        }
    )


# ============================================================
# INDICATORS
# ============================================================

def ema(series, period):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = (
        avg_gain /
        avg_loss.replace(0, np.nan)
    )

    result = 100 - (
        100 / (1 + rs)
    )

    return result.fillna(50)


def atr(df, period=14):

    previous_close = df["close"].shift(1)

    tr1 = (
        df["high"] -
        df["low"]
    )

    tr2 = (
        df["high"] -
        previous_close
    ).abs()

    tr3 = (
        df["low"] -
        previous_close
    ).abs()

    tr = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    return tr.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()


def add_indicators(df):

    d = df.copy()

    d["ema20"] = ema(
        d["close"],
        20
    )

    d["ema50"] = ema(
        d["close"],
        50
    )

    d["ema200"] = ema(
        d["close"],
        200
    )

    d["rsi"] = rsi(
        d["close"]
    )

    d["atr"] = atr(d)

    macd_fast = ema(
        d["close"],
        12
    )

    macd_slow = ema(
        d["close"],
        26
    )

    d["macd"] = (
        macd_fast -
        macd_slow
    )

    d["macd_signal"] = ema(
        d["macd"],
        9
    )

    d["macd_hist"] = (
        d["macd"] -
        d["macd_signal"]
    )

    d["bb_mid"] = (
        d["close"]
        .rolling(20)
        .mean()
    )

    std = (
        d["close"]
        .rolling(20)
        .std()
    )

    d["bb_upper"] = (
        d["bb_mid"] +
        2 * std
    )

    d["bb_lower"] = (
        d["bb_mid"] -
        2 * std
    )

    d["volume_ma"] = (
        d["volume"]
        .rolling(20)
        .mean()
    )

    d["volume_ratio"] = (
        d["volume"] /
        d["volume_ma"]
    )

    return d


# ============================================================
# CANDLE RECOGNITION
# ============================================================

def candle_patterns(df):

    patterns = []

    if len(df) < 3:
        return ["Normal"]

    c = df.iloc[-1]
    p = df.iloc[-2]

    o = float(c["open"])
    h = float(c["high"])
    l = float(c["low"])
    close = float(c["close"])

    previous_open = float(p["open"])
    previous_close = float(p["close"])

    candle_range = max(
        h - l,
        1e-12
    )

    body = abs(
        close - o
    )

    upper_wick = (
        h -
        max(o, close)
    )

    lower_wick = (
        min(o, close) -
        l
    )

    body_ratio = (
        body /
        candle_range
    )

    upper_ratio = (
        upper_wick /
        candle_range
    )

    lower_ratio = (
        lower_wick /
        candle_range
    )

    # Doji
    if body_ratio <= 0.10:

        patterns.append(
            "DOJI"
        )

    # Hammer
    if (
        lower_ratio >= 0.45
        and upper_ratio <= 0.25
        and body_ratio <= 0.45
    ):

        patterns.append(
            "HAMMER"
        )

    # Shooting Star
    if (
        upper_ratio >= 0.45
        and lower_ratio <= 0.25
        and body_ratio <= 0.45
    ):

        patterns.append(
            "SHOOTING STAR"
        )

    # Bullish Engulfing
    if (
        previous_close < previous_open
        and close > o
        and o <= previous_close
        and close >= previous_open
    ):

        patterns.append(
            "BULLISH ENGULFING"
        )

    # Bearish Engulfing
    if (
        previous_close > previous_open
        and close < o
        and o >= previous_close
        and close <= previous_open
    ):

        patterns.append(
            "BEARISH ENGULFING"
        )

    # Marubozu
    if body_ratio >= 0.85:

        if close > o:
            patterns.append(
                "BULLISH MARUBOZU"
            )
        else:
            patterns.append(
                "BEARISH MARUBOZU"
            )

    if not patterns:
        patterns.append("NORMAL")

    return patterns


# ============================================================
# PIVOTS
# ============================================================

def find_pivots(df, window=3):

    highs = []
    lows = []

    highs_data = df["high"].values
    lows_data = df["low"].values

    for i in range(
        window,
        len(df) - window
    ):

        current_high = highs_data[i]

        if current_high == max(
            highs_data[
                i-window:i+window+1
            ]
        ):

            highs.append(
                (i, float(current_high))
            )

        current_low = lows_data[i]

        if current_low == min(
            lows_data[
                i-window:i+window+1
            ]
        ):

            lows.append(
                (i, float(current_low))
            )

    return highs, lows


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(df):

    highs, lows = find_pivots(df)

    if len(highs) < 3 or len(lows) < 3:

        return {
            "state": "RANGE",
            "highs": highs,
            "lows": lows,
            "bos": "NONE",
            "choch": "NONE"
        }

    h1 = highs[-2][1]
    h2 = highs[-1][1]

    l1 = lows[-2][1]
    l2 = lows[-1][1]

    if h2 > h1 and l2 > l1:

        state = "BULLISH HH/HL"

    elif h2 < h1 and l2 < l1:

        state = "BEARISH LH/LL"

    else:

        state = "RANGE / MIXED"

    last_close = float(
        df["close"].iloc[-1]
    )

    previous_high = highs[-1][1]
    previous_low = lows[-1][1]

    bos = "NONE"
    choch = "NONE"

    # Bullish BOS
    if last_close > previous_high:

        bos = "BULLISH BOS"

        if state.startswith(
            "BEARISH"
        ):

            choch = "BULLISH CHoCH"

    # Bearish BOS
    elif last_close < previous_low:

        bos = "BEARISH BOS"

        if state.startswith(
            "BULLISH"
        ):

            choch = "BEARISH CHoCH"

    return {
        "state": state,
        "highs": highs,
        "lows": lows,
        "bos": bos,
        "choch": choch
    }


# ============================================================
# BREAKOUT / FAKE BREAKOUT
# ============================================================

def breakout_analysis(df):

    if len(df) < 30:

        return {
            "state": "NONE",
            "level": None
        }

    last = df.iloc[-1]

    recent_high = (
        df["high"]
        .iloc[-21:-1]
        .max()
    )

    recent_low = (
        df["low"]
        .iloc[-21:-1]
        .min()
    )

    close = float(
        last["close"]
    )

    high = float(
        last["high"]
    )

    low = float(
        last["low"]
    )

    volume_ratio = float(
        last["volume_ratio"]
    )

    # Bullish breakout
    if (
        close > recent_high
        and volume_ratio >= 1.2
    ):

        return {
            "state": "BULLISH BREAKOUT",
            "level": recent_high
        }

    # Fake bullish breakout
    if (
        high > recent_high
        and close < recent_high
    ):

        return {
            "state": "FAKE BULLISH BREAKOUT",
            "level": recent_high
        }

    # Bearish breakout
    if (
        close < recent_low
        and volume_ratio >= 1.2
    ):

        return {
            "state": "BEARISH BREAKDOWN",
            "level": recent_low
        }

    # Fake bearish breakout
    if (
        low < recent_low
        and close > recent_low
    ):

        return {
            "state": "FAKE BEARISH BREAKDOWN",
            "level": recent_low
        }

    return {
        "state": "NO BREAKOUT",
        "level": None
    }


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def liquidity_sweep(df):

    if len(df) < 25:

        return "NONE"

    previous_high = (
        df["high"]
        .iloc[-21:-1]
        .max()
    )

    previous_low = (
        df["low"]
        .iloc[-21:-1]
        .min()
    )

    candle = df.iloc[-1]

    high = float(
        candle["high"]
    )

    low = float(
        candle["low"]
    )

    close = float(
        candle["close"]
    )

    if (
        high > previous_high
        and close < previous_high
    ):

        return "BUY-SIDE LIQUIDITY SWEEP"

    if (
        low < previous_low
        and close > previous_low
    ):

        return "SELL-SIDE LIQUIDITY SWEEP"

    return "NONE"


# ============================================================
# RSI DIVERGENCE
# ============================================================

def rsi_divergence(df):

    if len(df) < 50:

        return "NONE"

    price = df["close"]
    r = df["rsi"]

    old_price_low = (
        price.iloc[-45:-25]
        .min()
    )

    new_price_low = (
        price.iloc[-25:]
        .min()
    )

    old_rsi_low = (
        r.iloc[-45:-25]
        .min()
    )

    new_rsi_low = (
        r.iloc[-25:]
        .min()
    )

    if (
        new_price_low < old_price_low
        and new_rsi_low > old_rsi_low
    ):

        return "BULLISH DIVERGENCE"

    old_price_high = (
        price.iloc[-45:-25]
        .max()
    )

    new_price_high = (
        price.iloc[-25:]
        .max()
    )

    old_rsi_high = (
        r.iloc[-45:-25]
        .max()
    )

    new_rsi_high = (
        r.iloc[-25:]
        .max()
    )

    if (
        new_price_high > old_price_high
        and new_rsi_high < old_rsi_high
    ):

        return "BEARISH DIVERGENCE"

    return "NONE"


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def support_resistance(df):

    highs, lows = find_pivots(df)

    supports = [
        x[1]
        for x in lows[-30:]
    ]

    resistances = [
        x[1]
        for x in highs[-30:]
    ]

    return supports, resistances


def nearest_support(price, supports):

    valid = [
        x
        for x in supports
        if x < price
    ]

    if not valid:
        return None

    return max(valid)


def nearest_resistance(price, resistances):

    valid = [
        x
        for x in resistances
        if x > price
    ]

    if not valid:
        return None

    return min(valid)


# ============================================================
# ORDER BOOK
# ============================================================

def orderbook_pressure(symbol):

    book = get_order_book(
        symbol,
        100
    )

    bids = book.get(
        "bids",
        []
    )

    asks = book.get(
        "asks",
        []
    )

    bid_value = 0
    ask_value = 0

    for price, quantity in bids:

        bid_value += (
            float(price) *
            float(quantity)
        )

    for price, quantity in asks:

        ask_value += (
            float(price) *
            float(quantity)
        )

    total = (
        bid_value +
        ask_value
    )

    if total <= 0:

        return {
            "bid": 0,
            "ask": 0,
            "pressure": 50,
            "state": "UNKNOWN"
        }

    pressure = (
        bid_value /
        total
    ) * 100

    if pressure >= 60:

        state = "BUY PRESSURE"

    elif pressure <= 40:

        state = "SELL PRESSURE"

    else:

        state = "BALANCED"

    return {
        "bid": bid_value,
        "ask": ask_value,
        "pressure": pressure,
        "state": state
    }


# ============================================================
# LARGE TRADES / WHALE PRESSURE
# ============================================================

def whale_pressure(symbol):

    try:

        trades = binance(
            "/api/v3/trades",
            {
                "symbol": symbol,
                "limit": 1000
            }
        )

    except Exception:

        return {
            "buy": 0,
            "sell": 0,
            "pressure": 50,
            "large_trades": 0,
            "state": "UNKNOWN",
            "score": 50
        }

    buy_value = 0
    sell_value = 0
    large_trades = 0

    for trade in trades:

        price = float(
            trade["price"]
        )

        quantity = float(
            trade["qty"]
        )

        value = (
            price *
            quantity
        )

        if value < WHALE_TRADE_USDT:
            continue

        large_trades += 1

        # Buyer maker = true یعنی خریدار سفارش Market Sell زده
        if trade["isBuyerMaker"]:

            sell_value += value

        else:

            buy_value += value

    total = (
        buy_value +
        sell_value
    )

    if total <= 0:

        return {
            "buy": 0,
            "sell": 0,
            "pressure": 50,
            "large_trades": 0,
            "state": "NO LARGE FLOW",
            "score": 50
        }

    pressure = (
        buy_value /
        total
    ) * 100

    if pressure >= 60:

        state = "🟢 LARGE BUY PRESSURE"

    elif pressure <= 40:

        state = "🔴 LARGE SELL PRESSURE"

    else:

        state = "🟡 MIXED LARGE FLOW"

    score = int(
        max(
            0,
            min(
                100,
                pressure
            )
        )
    )

    return {
        "buy": buy_value,
        "sell": sell_value,
        "pressure": pressure,
        "large_trades": large_trades,
        "state": state,
        "score": score
    }


# ============================================================
# TIMEFRAME ANALYSIS
# ============================================================

def analyze_timeframe(df, timeframe):

    d = add_indicators(df)

    last = d.iloc[-1]
    previous = d.iloc[-2]

    price = float(
        last["close"]
    )

    score = 50

    reasons = []

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if (
        price > last["ema20"]
        and
        last["ema20"]
        >
        last["ema50"]
        and
        last["ema50"]
        >
        last["ema200"]
    ):

        score += 15

        reasons.append(
            "EMA FULL BULLISH"
        )

    elif (
        price < last["ema20"]
        and
        last["ema20"]
        <
        last["ema50"]
        and
        last["ema50"]
        <
        last["ema200"]
    ):

        score -= 15

        reasons.append(
            "EMA FULL BEARISH"
        )

    elif price > last["ema50"]:

        score += 5

    else:

        score -= 5

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    current_rsi = float(
        last["rsi"]
    )

    if 50 <= current_rsi <= 68:

        score += 7

        reasons.append(
            "RSI bullish zone"
        )

    elif current_rsi < 30:

        score += 5

        reasons.append(
            "RSI oversold"
        )

    elif current_rsi > 75:

        score -= 6

        reasons.append(
            "RSI overbought"
        )

    elif current_rsi < 45:

        score -= 5

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    hist = float(
        last["macd_hist"]
    )

    previous_hist = float(
        previous["macd_hist"]
    )

    if (
        hist > 0
        and hist > previous_hist
    ):

        score += 8

        reasons.append(
            "MACD improving"
        )

    elif (
        hist < 0
        and hist < previous_hist
    ):

        score -= 8

        reasons.append(
            "MACD weakening"
        )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    volume_ratio = float(
        last["volume_ratio"]
    )

    if volume_ratio >= 2:

        if last["close"] > last["open"]:

            score += 10

            reasons.append(
                "STRONG BUY VOLUME"
            )

        else:

            score -= 10

            reasons.append(
                "STRONG SELL VOLUME"
            )

    elif volume_ratio >= 1.3:

        if last["close"] > last["open"]:

            score += 5

        else:

            score -= 5

    # --------------------------------------------------------
    # MARKET STRUCTURE
    # --------------------------------------------------------

    structure = market_structure(d)

    if structure["state"] == "BULLISH HH/HL":

        score += 12

        reasons.append(
            "HH/HL"
        )

    elif structure["state"] == "BEARISH LH/LL":

        score -= 12

        reasons.append(
            "LH/LL"
        )

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    if structure["bos"] == "BULLISH BOS":

        score += 10

        reasons.append(
            "BULLISH BOS"
        )

    elif structure["bos"] == "BEARISH BOS":

        score -= 10

        reasons.append(
            "BEARISH BOS"
        )

    # --------------------------------------------------------
    # CHoCH
    # --------------------------------------------------------

    if structure["choch"] == "BULLISH CHoCH":

        score += 8

        reasons.append(
            "BULLISH CHoCH"
        )

    elif structure["choch"] == "BEARISH CHoCH":

        score -= 8

        reasons.append(
            "BEARISH CHoCH"
        )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout = breakout_analysis(d)

    if breakout["state"] == "BULLISH BREAKOUT":

        score += 10

        reasons.append(
            "BREAKOUT CONFIRMED"
        )

    elif breakout["state"] == "BEARISH BREAKDOWN":

        score -= 10

        reasons.append(
            "BREAKDOWN CONFIRMED"
        )

    elif breakout["state"] == "FAKE BULLISH BREAKOUT":

        score -= 7

        reasons.append(
            "FAKE BREAKOUT"
        )

    elif breakout["state"] == "FAKE BEARISH BREAKDOWN":

        score += 7

        reasons.append(
            "SELL LIQUIDITY TRAP"
        )

    # --------------------------------------------------------
    # LIQUIDITY SWEEP
    # --------------------------------------------------------

    sweep = liquidity_sweep(d)

    if sweep == "SELL-SIDE LIQUIDITY SWEEP":

        score += 7

        reasons.append(
            "SELL-SIDE SWEEP"
        )

    elif sweep == "BUY-SIDE LIQUIDITY SWEEP":

        score -= 7

        reasons.append(
            "BUY-SIDE SWEEP"
        )

    # --------------------------------------------------------
    # RSI DIVERGENCE
    # --------------------------------------------------------

    divergence = rsi_divergence(d)

    if divergence == "BULLISH DIVERGENCE":

        score += 7

        reasons.append(
            "BULLISH DIVERGENCE"
        )

    elif divergence == "BEARISH DIVERGENCE":

        score -= 7

        reasons.append(
            "BEARISH DIVERGENCE"
        )

    # --------------------------------------------------------
    # CANDLE
    # --------------------------------------------------------

    candles = candle_patterns(d)

    bullish_candles = [
        "HAMMER",
        "BULLISH ENGULFING",
        "BULLISH MARUBOZU"
    ]

    bearish_candles = [
        "SHOOTING STAR",
        "BEARISH ENGULFING",
        "BEARISH MARUBOZU"
    ]

    if any(
        c in candles
        for c in bullish_candles
    ):

        score += 7

        reasons.append(
            "BULLISH CANDLE"
        )

    if any(
        c in candles
        for c in bearish_candles
    ):

        score -= 7

        reasons.append(
            "BEARISH CANDLE"
        )

    # --------------------------------------------------------
    # FINAL SCORE
    # --------------------------------------------------------

    score = int(
        max(
            0,
            min(
                100,
                round(score)
            )
        )
    )

    if score >= 70:

        state = "BULLISH"

    elif score <= 40:

        state = "BEARISH"

    else:

        state = "NEUTRAL"

    supports, resistances = (
        support_resistance(d)
    )

    support = nearest_support(
        price,
        supports
    )

    resistance = nearest_resistance(
        price,
        resistances
    )

    return {
        "timeframe": timeframe,
        "df": d,
        "price": price,
        "score": score,
        "state": state,
        "structure": structure,
        "breakout": breakout,
        "sweep": sweep,
        "divergence": divergence,
        "candles": candles,
        "rsi": current_rsi,
        "atr": float(last["atr"]),
        "volume_ratio": volume_ratio,
        "support": support,
        "resistance": resistance,
        "reasons": reasons
    }


# ============================================================
# BTC FILTER
# ============================================================

def analyze_btc():

    btc15 = analyze_timeframe(
        get_klines(
            "BTCUSDT",
            "15m"
        ),
        "15M"
    )

    btc1 = analyze_timeframe(
        get_klines(
            "BTCUSDT",
            "1h"
        ),
        "1H"
    )

    btc4 = analyze_timeframe(
        get_klines(
            "BTCUSDT",
            "4h"
        ),
        "4H"
    )

    score = int(
        round(
            btc15["score"] * 0.15
            +
            btc1["score"] * 0.35
            +
            btc4["score"] * 0.50
        )
    )

    if score >= 70:

        state = "BULLISH"

    elif score <= 40:

        state = "BEARISH"

    else:

        state = "NEUTRAL"

    return {
        "score": score,
        "state": state,
        "15m": btc15,
        "1h": btc1,
        "4h": btc4
    }


# ============================================================
# TRADE PLAN
# ============================================================

def create_trade_plan(
    capital,
    a15,
    a1,
    a4,
    btc,
    orderbook,
    whale
):

    # --------------------------------------------------------
    # Weighted Score
    # --------------------------------------------------------

    base_score = (
        a15["score"] * 0.15
        +
        a1["score"] * 0.30
        +
        a4["score"] * 0.40
        +
        btc["score"] * 0.15
    )

    # Order book influence
    order_adjustment = (
        orderbook["pressure"] - 50
    ) * 0.10

    # Whale influence
    whale_adjustment = (
        whale["pressure"] - 50
    ) * 0.10

    final_score = (
        base_score
        +
        order_adjustment
        +
        whale_adjustment
    )

    final_score = int(
        max(
            0,
            min(
                100,
                round(final_score)
            )
        )
    )

    # --------------------------------------------------------
    # Confirmation System
    # --------------------------------------------------------

    bullish_tf = sum([
        a15["state"] == "BULLISH",
        a1["state"] == "BULLISH",
        a4["state"] == "BULLISH"
    ])

    bearish_tf = sum([
        a15["state"] == "BEARISH",
        a1["state"] == "BEARISH",
        a4["state"] == "BEARISH"
    ])

    confirmations = 0

    if a4["state"] == "BULLISH":
        confirmations += 1

    if a1["state"] == "BULLISH":
        confirmations += 1

    if (
        a4["structure"]["bos"]
        == "BULLISH BOS"
    ):
        confirmations += 1

    if (
        a1["structure"]["bos"]
        == "BULLISH BOS"
    ):
        confirmations += 1

    if (
        a4["breakout"]["state"]
        == "BULLISH BREAKOUT"
    ):
        confirmations += 1

    if (
        a1["breakout"]["state"]
        == "BULLISH BREAKOUT"
    ):
        confirmations += 1

    if (
        orderbook["pressure"]
        >= 58
    ):
        confirmations += 1

    if (
        whale["pressure"]
        >= 58
    ):
        confirmations += 1

    if (
        a4["volume_ratio"]
        >= 1.3
    ):
        confirmations += 1

    # --------------------------------------------------------
    # Decision
    # --------------------------------------------------------

    if (
        final_score >= 72
        and bullish_tf >= 2
        and confirmations >= 4
        and btc["state"] != "BEARISH"
    ):

        decision = "BUY"

    elif (
        final_score <= 40
        or bearish_tf >= 2
        or btc["state"] == "BEARISH"
    ):

        decision = "AVOID"

    else:

        decision = "WAIT"

    # --------------------------------------------------------
    # Price
    # --------------------------------------------------------

    entry = a15["price"]

    atr_value = max(
        a1["atr"],
        a4["atr"]
    )

    # --------------------------------------------------------
    # Support
    # --------------------------------------------------------

    supports = [
        x["support"]
        for x in [
            a15,
            a1,
            a4
        ]
        if x["support"]
        and x["support"] < entry
    ]

    if supports:

        support = max(supports)

    else:

        support = (
            entry -
            atr_value * 1.5
        )

    # --------------------------------------------------------
    # Stop Loss
    # --------------------------------------------------------

    sl = (
        support -
        atr_value * 0.20
    )

    if sl <= 0:

        sl = (
            entry * 0.97
        )

    risk_per_coin = (
        entry - sl
    )

    if risk_per_coin <= 0:

        risk_per_coin = (
            entry * 0.03
        )

        sl = (
            entry -
            risk_per_coin
        )

    # --------------------------------------------------------
    # Resistance
    # --------------------------------------------------------

    resistances = [
        x["resistance"]
        for x in [
            a15,
            a1,
            a4
        ]
        if x["resistance"]
        and x["resistance"] > entry
    ]

    resistances.sort()

    # TP1
    if resistances:

        tp1 = resistances[0]

    else:

        tp1 = (
            entry +
            risk_per_coin * 1.5
        )

    if tp1 <= entry:

        tp1 = (
            entry +
            risk_per_coin * 1.5
        )

    # TP2
    tp2 = max(
        entry +
        risk_per_coin * 2,
        tp1 +
        risk_per_coin * 0.5
    )

    # TP3
    tp3 = max(
        entry +
        risk_per_coin * 3,
        tp2 +
        risk_per_coin * 0.5
    )

    # --------------------------------------------------------
    # Risk Management
    # --------------------------------------------------------

    risk_money = (
        capital *
        RISK_PERCENT /
        100
    )

    quantity_by_risk = (
        risk_money /
        risk_per_coin
    )

    position_value = min(
        capital,
        quantity_by_risk *
        entry
    )

    quantity = (
        position_value /
        entry
    )

    # --------------------------------------------------------
    # DCA
    # --------------------------------------------------------

    dca = [

        (
            entry,
            capital * 0.20
        ),

        (
            max(
                entry -
                atr_value * 0.50,
                support
            ),
            capital * 0.25
        ),

        (
            max(
                entry -
                atr_value,
                sl * 1.02
            ),
            capital * 0.30
        ),

        (
            max(
                entry -
                atr_value * 1.50,
                sl * 1.01
            ),
            capital * 0.25
        )
    ]

    dca = [
        (
            max(
                price,
                0.0000000001
            ),
            money
        )
        for price, money
        in dca
    ]

    # --------------------------------------------------------
    # R:R
    # --------------------------------------------------------

    rr1 = (
        tp1 - entry
    ) / risk_per_coin

    rr2 = (
        tp2 - entry
    ) / risk_per_coin

    rr3 = (
        tp3 - entry
    ) / risk_per_coin

    return {
        "score": final_score,
        "decision": decision,
        "confirmations": confirmations,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_money": risk_money,
        "position": position_value,
        "quantity": quantity,
        "dca": dca,
        "rr1": rr1,
        "rr2": rr2,
        "rr3": rr3
    }


# ============================================================
# PRICE FORMAT
# ============================================================

def price_format(value):

    value = float(value)

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:,.4f}"

    if value >= 0.01:
        return f"{value:,.6f}"

    if value >= 0.0001:
        return f"{value:,.8f}"

    return f"{value:.10f}"


def percent(entry, target):

    return (
        (target / entry) - 1
    ) * 100


# ============================================================
# DCA AVERAGE CALCULATOR
# ============================================================

def dca_report(dca):

    total_money = 0
    total_qty = 0

    output = ""

    for i, (
        price,
        money
    ) in enumerate(
        dca,
        1
    ):

        qty = (
            money /
            price
        )

        total_money += money
        total_qty += qty

        average = (
            total_money /
            total_qty
        )

        output += (
            f"\nP{i} "
            f"@ {price_format(price)}"
            f" | ${money:,.0f}"
            f" | Avg: "
            f"{price_format(average)}"
        )

    return output


# ============================================================
# REPORT
# ------------------------------------------------------------
# تغییر مهم: بخش «🎯 SPOT PLAN» و «🪜 DCA PLAN» فقط وقتی
# plan["decision"] == "BUY" باشد با اعداد کامل (Entry/SL/TP/R:R)
# نمایش داده می‌شوند. برای WAIT یا AVOID فقط یک پیام هشدار
# نمایش داده می‌شود تا کاربر گمراه نشود که «تصمیم = اجتناب» ولی
# همزمان یک پلن معاملاتی کامل با اعداد دقیق پیشنهاد شده.
# ============================================================

def build_report(
    symbol,
    capital,
    a15,
    a1,
    a4,
    btc,
    orderbook,
    whale,
    plan
):

    icons = {
        "BUY": "🟢",
        "WAIT": "🟡",
        "AVOID": "🔴"
    }

    icon = icons[
        plan["decision"]
    ]

    is_buy = plan["decision"] == "BUY"

    if is_buy:

        dca_text = dca_report(
            plan["dca"]
        )

        plan_section = f"""━━━━━━━━━━━━━━━━━━━━
🎯 SPOT PLAN

💰 Capital:
${capital:,.2f}

ENTRY:
{price_format(plan["entry"])}

STOP LOSS:
{price_format(plan["sl"])}

TP1:
{price_format(plan["tp1"])}
{percent(plan["entry"], plan["tp1"]):+.2f}%
R:R 1:{plan["rr1"]:.2f}

TP2:
{price_format(plan["tp2"])}
{percent(plan["entry"], plan["tp2"]):+.2f}%
R:R 1:{plan["rr2"]:.2f}

TP3:
{price_format(plan["tp3"])}
{percent(plan["entry"], plan["tp3"]):+.2f}%
R:R 1:{plan["rr3"]:.2f}

━━━━━━━━━━━━━━━━━━━━
💵 RISK MANAGEMENT

Risk:
${plan["risk_money"]:,.2f}

Position:
${plan["position"]:,.2f}

Quantity:
{plan["quantity"]:,.6f}

━━━━━━━━━━━━━━━━━━━━
🪜 DCA PLAN
{dca_text}
"""

    else:

        reason_note = (
            "امتیاز نهایی و تعداد تاییدیه‌ها کافی نبوده."
            if plan["decision"] == "WAIT"
            else "شرایط فعلی بازار (امتیاز پایین، روند نزولی تایم‌فریم‌ها، یا فیلتر BTC) ریسک ورود را بالا نشان می‌دهد."
        )

        plan_section = f"""━━━━━━━━━━━━━━━━━━━━
🎯 SPOT PLAN

⚠️ در حال حاضر پلن معاملاتی (Entry/SL/TP) ارائه نمی‌شود.
تصمیم فعلی: {plan["decision"]} — {reason_note}

قیمت مرجع فعلی: {price_format(plan["entry"])}
اگر این کوین را از قبل دارید، حمایت نزدیک ({price_format(a4["support"]) if a4["support"] else "نامشخص"}) را برای ریسک احتمالی زیر نظر بگیرید.
"""

    return f"""
🤖 SPOT AI ANALYST
━━━━━━━━━━━━━━━━━━━━

💎 {symbol}

{icon} DECISION:
{plan["decision"]}

🧠 FINAL SCORE:
{plan["score"]}/100

✅ Confirmations:
{plan["confirmations"]}

━━━━━━━━━━━━━━━━━━━━
🕒 MULTI TIMEFRAME

15M
Score: {a15["score"]}/100
State: {a15["state"]}
Structure: {a15["structure"]["state"]}
BOS: {a15["structure"]["bos"]}
CHoCH: {a15["structure"]["choch"]}
Breakout: {a15["breakout"]["state"]}
Sweep: {a15["sweep"]}
RSI: {a15["rsi"]:.1f}
Candle: {", ".join(a15["candles"])}

━━━━━━━━

1H
Score: {a1["score"]}/100
State: {a1["state"]}
Structure: {a1["structure"]["state"]}
BOS: {a1["structure"]["bos"]}
CHoCH: {a1["structure"]["choch"]}
Breakout: {a1["breakout"]["state"]}
Sweep: {a1["sweep"]}
RSI: {a1["rsi"]:.1f}
Candle: {", ".join(a1["candles"])}

━━━━━━━━

4H
Score: {a4["score"]}/100
State: {a4["state"]}
Structure: {a4["structure"]["state"]}
BOS: {a4["structure"]["bos"]}
CHoCH: {a4["structure"]["choch"]}
Breakout: {a4["breakout"]["state"]}
Sweep: {a4["sweep"]}
RSI: {a4["rsi"]:.1f}
Candle: {", ".join(a4["candles"])}

━━━━━━━━━━━━━━━━━━━━
₿ BTC FILTER

BTC:
{btc["score"]}/100

State:
{btc["state"]}

━━━━━━━━━━━━━━━━━━━━
📚 ORDER BOOK

Pressure:
{orderbook["pressure"]:.1f}%

State:
{orderbook["state"]}

Bid Value:
${orderbook["bid"]:,.0f}

Ask Value:
${orderbook["ask"]:,.0f}

━━━━━━━━━━━━━━━━━━━━
🐋 LARGE FLOW

Pressure:
{whale["pressure"]:.1f}%

State:
{whale["state"]}

Large Trades:
{whale["large_trades"]}

Large Buy:
${whale["buy"]:,.0f}

Large Sell:
${whale["sell"]:,.0f}

{plan_section}
━━━━━━━━━━━━━━━━━━━━

⚠️ SPOT ONLY
روبات Short/Futures صادر نمی‌کند.

⚠️ Whale Radar بر اساس
داده عمومی معاملات و Order Book است
و مالک کیف پول را شناسایی نمی‌کند.
"""


# ============================================================
# CHART
# ------------------------------------------------------------
# تغییر: خطوط ENTRY/SL/TP روی چارت فقط وقتی decision == "BUY"
# رسم می‌شوند؛ در غیر این صورت فقط کندل/EMA/BB/Trendline نشان
# داده می‌شود تا چارت هم با متن گزارش هم‌خوان باشد.
# ============================================================

def create_chart(
    symbol,
    a4,
    plan
):

    df = a4["df"].tail(150)

    fig, ax = plt.subplots(
        figsize=(15, 8)
    )

    for i, (_, row) in enumerate(
        df.iterrows()
    ):

        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])

        # wick
        ax.vlines(
            i,
            l,
            h,
            linewidth=1
        )

        bottom = min(
            o,
            c
        )

        height = max(
            abs(c - o),
            1e-12
        )

        rect = plt.Rectangle(
            (
                i - 0.30,
                bottom
            ),
            0.60,
            height,
            fill=(c < o),
            alpha=0.35
        )

        ax.add_patch(
            rect
        )

    x = np.arange(
        len(df)
    )

    # EMA
    ax.plot(
        x,
        df["ema20"],
        linewidth=1,
        label="EMA20"
    )

    ax.plot(
        x,
        df["ema50"],
        linewidth=1,
        label="EMA50"
    )

    ax.plot(
        x,
        df["ema200"],
        linewidth=1,
        label="EMA200"
    )

    # Bollinger
    ax.plot(
        x,
        df["bb_upper"],
        linewidth=0.7,
        alpha=0.4,
        label="BB Upper"
    )

    ax.plot(
        x,
        df["bb_lower"],
        linewidth=0.7,
        alpha=0.4,
        label="BB Lower"
    )

    is_buy = plan["decision"] == "BUY"

    if is_buy:

        # Entry
        ax.axhline(
            plan["entry"],
            linewidth=2,
            label="ENTRY"
        )

        # SL
        ax.axhline(
            plan["sl"],
            linestyle=":",
            linewidth=2,
            label="STOP"
        )

        # Targets
        ax.axhline(
            plan["tp1"],
            linestyle="--",
            linewidth=1.5,
            label="TP1"
        )

        ax.axhline(
            plan["tp2"],
            linestyle="--",
            linewidth=1.5,
            label="TP2"
        )

        ax.axhline(
            plan["tp3"],
            linestyle="--",
            linewidth=1.5,
            label="TP3"
        )

    else:

        # فقط قیمت فعلی به‌عنوان مرجع، بدون پلن معاملاتی
        ax.axhline(
            plan["entry"],
            linewidth=1.5,
            linestyle="-.",
            alpha=0.6,
            label="Current Price"
        )

    # --------------------------------------------------------
    # Trendlines
    # --------------------------------------------------------

    structure = a4[
        "structure"
    ]

    lows = structure[
        "lows"
    ]

    highs = structure[
        "highs"
    ]

    if len(lows) >= 2:

        x1, y1 = lows[-2]
        x2, y2 = lows[-1]

        if x2 != x1:

            slope = (
                y2 - y1
            ) / (
                x2 - x1
            )

            xx = np.arange(
                max(0, x1 - 20),
                len(df)
            )

            yy = (
                y1 +
                slope *
                (xx - x1)
            )

            ax.plot(
                xx,
                yy,
                linewidth=2,
                label="Support Trendline"
            )

    if len(highs) >= 2:

        x1, y1 = highs[-2]
        x2, y2 = highs[-1]

        if x2 != x1:

            slope = (
                y2 - y1
            ) / (
                x2 - x1
            )

            xx = np.arange(
                max(0, x1 - 20),
                len(df)
            )

            yy = (
                y1 +
                slope *
                (xx - x1)
            )

            ax.plot(
                xx,
                yy,
                linewidth=2,
                label="Resistance Trendline"
            )

    ax.set_title(
        f"{symbol} | 4H SPOT AI | "
        f"{plan['decision']} | "
        f"Score {plan['score']}/100"
    )

    ax.grid(
        alpha=0.15
    )

    ax.legend(
        fontsize=8
    )

    plt.tight_layout()

    buffer = io.BytesIO()

    plt.savefig(
        buffer,
        format="png",
        dpi=160
    )

    plt.close()

    buffer.seek(0)

    return buffer


# ============================================================
# WHALE MARKET RADAR
# ============================================================

def whale_market_radar():

    tickers = binance(
        "/api/v3/ticker/24hr"
    )

    candidates = []

    for item in tickers:

        symbol = item["symbol"]

        if not symbol.endswith(
            "USDT"
        ):
            continue

        volume = float(
            item.get(
                "quoteVolume",
                0
            )
        )

        change = float(
            item.get(
                "priceChangePercent",
                0
            )
        )

        if volume < 10_000_000:
            continue

        momentum_score = max(
            -15,
            min(
                20,
                change * 0.8
            )
        )

        volume_score = min(
            35,
            math.log10(
                max(
                    volume,
                    1
                )
            ) * 2.8
        )

        candidates.append({
            "symbol": symbol,
            "volume": volume,
            "change": change,
            "pre_score":
                volume_score
                +
                momentum_score
        })

    candidates.sort(
        key=lambda x:
        x["pre_score"],
        reverse=True
    )

    candidates = candidates[:15]

    results = []

    for coin in candidates:

        try:

            ob = orderbook_pressure(
                coin["symbol"]
            )

            whale = whale_pressure(
                coin["symbol"]
            )

            final = int(
                round(
                    whale["score"] * 0.60
                    +
                    ob["pressure"] * 0.25
                    +
                    min(
                        100,
                        max(
                            0,
                            50 +
                            coin["change"] * 2
                        )
                    ) * 0.15
                )
            )

            if (
                whale["pressure"] >= 60
                and
                ob["pressure"] >= 55
            ):

                state = "🟢 ACCUMULATION"

            elif (
                whale["pressure"] <= 40
                and
                ob["pressure"] <= 45
            ):

                state = "🔴 DISTRIBUTION"

            else:

                state = "🟡 MIXED"

            results.append({
                **coin,
                "orderbook":
                    ob,
                "whale":
                    whale,
                "score":
                    final,
                "state":
                    state
            })

        except Exception:

            continue

    results.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    return results[:10]


# ============================================================
# TELEGRAM START
# ============================================================

def main_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📊 تحلیل ارز",
                callback_data="ANALYZE"
            ),

            InlineKeyboardButton(
                "🐋 رادار نهنگ",
                callback_data="WHALES"
            )
        ],

        [
            InlineKeyboardButton(
                "ℹ️ راهنما",
                callback_data="HELP"
            )
        ]

    ])


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        """
🤖 SPOT AI TRADING BOT

━━━━━━━━━━━━━━━━━━

📊 تحلیل خودکار:

15M
1H
4H

━━━━━━━━━━━━━━━━━━

🧠 تحلیل:

Candles
EMA
RSI
MACD
Bollinger
ATR
Volume

BOS
CHoCH
Market Structure
Liquidity Sweep
Breakout
Fake Breakout

Support
Resistance
Trendline

BTC Filter

Order Book
Whale Pressure

━━━━━━━━━━━━━━━━━━

🎯 خروجی:

BUY
WAIT
AVOID

Entry
Stop Loss
TP1
TP2
TP3

Risk / Reward

━━━━━━━━━━━━━━━━━━

🪜 خرید پله‌ای

سرمایه را بده
روبات مقدار هر پله
و میانگین خرید را حساب می‌کند.

━━━━━━━━━━━━━━━━━━

مثال:

/analyze INJ 3000

یا:

/analyze BTC 5000

━━━━━━━━━━━━━━━━━━

🐋 رادار بازار:

/whales
""",

        reply_markup=main_keyboard()
    )


# ============================================================
# ANALYZE COMMAND
# ============================================================

async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:

        await update.message.reply_text(
            "فرمت:\n\n"
            "/analyze INJ 3000"
        )

        return

    symbol = normalize_symbol(
        context.args[0]
    )

    try:

        capital = float(
            context.args[1]
            .replace(",", "")
            .replace("$", "")
        )

    except:

        await update.message.reply_text(
            "❌ سرمایه صحیح نیست."
        )

        return

    if capital <= 0:

        await update.message.reply_text(
            "❌ سرمایه باید بیشتر از صفر باشد."
        )

        return

    status = await update.message.reply_text(
        f"⏳ در حال تحلیل {symbol}...\n\n"
        "🕯 Candles\n"
        "🏗 Structure\n"
        "🔵 BOS / CHoCH\n"
        "💧 Liquidity\n"
        "📈 Breakout\n"
        "📚 Order Book\n"
        "🐋 Whale Flow\n"
        "₿ BTC Filter"
    )

    try:

        # ----------------------------------------------------
        # Timeframes
        # ----------------------------------------------------

        a15 = analyze_timeframe(
            get_klines(
                symbol,
                "15m"
            ),
            "15M"
        )

        a1 = analyze_timeframe(
            get_klines(
                symbol,
                "1h"
            ),
            "1H"
        )

        a4 = analyze_timeframe(
            get_klines(
                symbol,
                "4h"
            ),
            "4H"
        )

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        btc = analyze_btc()

        # ----------------------------------------------------
        # Order Book
        # ----------------------------------------------------

        orderbook = orderbook_pressure(
            symbol
        )

        # ----------------------------------------------------
        # Whale
        # ----------------------------------------------------

        whale = whale_pressure(
            symbol
        )

        # ----------------------------------------------------
        # Plan
        # ----------------------------------------------------

        plan = create_trade_plan(
            capital,
            a15,
            a1,
            a4,
            btc,
            orderbook,
            whale
        )

        # ----------------------------------------------------
        # Report
        # ----------------------------------------------------

        report = build_report(
            symbol,
            capital,
            a15,
            a1,
            a4,
            btc,
            orderbook,
            whale,
            plan
        )

        await status.edit_text(
            report
        )

        # ----------------------------------------------------
        # Chart
        # ----------------------------------------------------

        chart = create_chart(
            symbol,
            a4,
            plan
        )

        if plan["decision"] == "BUY":

            caption = (
                f"📈 {symbol} 4H\n"
                f"{plan['decision']} | "
                f"{plan['score']}/100\n\n"
                f"Entry: "
                f"{price_format(plan['entry'])}\n"
                f"SL: "
                f"{price_format(plan['sl'])}\n"
                f"TP1: "
                f"{price_format(plan['tp1'])}"
            )

        else:

            caption = (
                f"📈 {symbol} 4H\n"
                f"{plan['decision']} | "
                f"{plan['score']}/100\n\n"
                f"پلن معاملاتی ارائه نمی‌شود."
            )

        await update.message.reply_photo(
            photo=chart,
            caption=caption
        )

    except Exception as e:

        logger.exception(
            "Analysis error"
        )

        await status.edit_text(
            "❌ خطا در تحلیل.\n\n"
            f"{str(e)[:1500]}"
        )


# ============================================================
# WHALE COMMAND
# ============================================================

async def whales_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status = await update.message.reply_text(
        """
🐋 WHALE RADAR

در حال اسکن بازار...

📚 Order Book
💰 Large Trades
🔥 Volume
📈 Momentum

لطفاً چند لحظه صبر کن...
"""
    )

    try:

        results = whale_market_radar()

        if not results:

            await status.edit_text(
                "❌ داده کافی برای رادار نهنگ پیدا نشد."
            )

            return

        text = (
            "🐋 WHALE RADAR\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )

        for i, item in enumerate(
            results,
            1
        ):

            text += (
                f"{i}. "
                f"{item['symbol']}\n"
                f"⭐ Score: "
                f"{item['score']}/100\n"
                f"{item['state']}\n"
                f"🐋 Large Flow: "
                f"{item['whale']['pressure']:.1f}% Buy\n"
                f"📚 Order Book: "
                f"{item['orderbook']['pressure']:.1f}% Bid\n"
                f"🔥 Large Trades: "
                f"{item['whale']['large_trades']}\n"
                f"💰 24H Volume: "
                f"${item['volume']:,.0f}\n"
                f"📈 Change: "
                f"{item['change']:+.2f}%\n\n"
            )

        text += (
            "━━━━━━━━━━━━━━━━━━\n"
            "⚠️ این رادار مالک کیف‌پول را "
            "شناسایی نمی‌کند.\n\n"
            "معاملات بزرگ، Order Book و "
            "فشار خرید/فروش را بررسی می‌کند."
        )

        await status.edit_text(
            text
        )

    except Exception as e:

        logger.exception(
            "Whale error"
        )

        await status.edit_text(
            "❌ خطا در Whale Radar:\n\n"
            f"{str(e)[:1500]}"
        )


# ============================================================
# BUTTONS
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "ANALYZE":

        await query.message.reply_text(
            "📊 اسم ارز و سرمایه را بفرست.\n\n"
            "مثال:\n"
            "INJ 3000"
        )

    elif query.data == "WHALES":

        await whales_command(
            update,
            context
        )

    elif query.data == "HELP":

        await query.message.reply_text(
            """
ℹ️ راهنما

تحلیل ارز:

/analyze INJ 3000

یا:

/analyze BTC 5000

━━━━━━━━━━━━

🐋 رادار نهنگ:

/whales

━━━━━━━━━━━━

روبات Spot است و
Short/Futures نمی‌زند.
"""
        )


# ============================================================
# TEXT INPUT
# ============================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        update.message.text
        .strip()
    )

    parts = text.split()

    if len(parts) != 2:
        return

    symbol = parts[0]

    try:

        capital = float(
            parts[1]
            .replace(",", "")
            .replace("$", "")
        )

    except:

        return

    context.args = [
        symbol,
        str(capital)
    ]

    await analyze_command(
        update,
        context
    )


# ============================================================
# RUN
# ============================================================

def run():

    if (
        not BOT_TOKEN
        or
        BOT_TOKEN.startswith(
            "PUT_"
        )
    ):

        raise Exception(
            "\n\nBOT_TOKEN را داخل کد وارد کن.\n"
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "analyze",
            analyze_command
        )
    )

    app.add_handler(
        CommandHandler(
            "whales",
            whales_command
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler
        )
    )

    print(
        "================================"
    )

    print(
        "SPOT AI TRADING BOT STARTED"
    )

    print(
        "================================"
    )

    app.run_polling()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    run()
