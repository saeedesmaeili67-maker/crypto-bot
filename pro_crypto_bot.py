# -*- coding: utf-8 -*-
# ============================================================
# SPOT ANALYZER TELEGRAM BOT - SINGLE FILE VERSION
# ============================================================
# Features:
# - Telegram button interface
# - Any Binance USDT spot symbol
# - 15m / 30m / 4H / 1D analysis
# - BTC market filter
# - RSI, EMA20/50/200, volume
# - Support / resistance
# - Trendline approximation
# - Breakout level
# - Entry / SL / TP1 / TP2 / TP3
# - Capital-based P/L
# - Automatic annotated PNG chart
# - NO trade execution
#
# Install:
#   pip install python-telegram-bot pandas numpy requests matplotlib
#
# Set token:
# Linux/macOS:
#   export TELEGRAM_BOT_TOKEN="YOUR_BOTFATHER_TOKEN"
#
# Windows PowerShell:
#   $env:TELEGRAM_BOT_TOKEN="YOUR_BOTFATHER_TOKEN"
#
# Run:
#   python telegram_spot_analyzer.py
# ============================================================

import os
import re
import time
import math
import asyncio
from pathlib import Path

import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BINANCE_BASE = "https://api.binance.com"
REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

if not BOT_TOKEN:
    raise SystemExit(
        "ERROR: TELEGRAM_BOT_TOKEN is not set.\n"
        "Linux/macOS: export TELEGRAM_BOT_TOKEN='YOUR_TOKEN'\n"
        "Windows PowerShell: $env:TELEGRAM_BOT_TOKEN='YOUR_TOKEN'"
    )

# Conversation states
COIN, CAPITAL, ENTRY = range(3)

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🔍 تحلیل ارز", "🔄 تحلیل مجدد"],
        ["💰 سود / ضرر", "🎯 تغییر Entry"],
        ["🛑 SL / TP", "ℹ️ راهنما"],
    ],
    resize_keyboard=True,
)

ENTRY_MENU = ReplyKeyboardMarkup(
    [["📍 قیمت فعلی"], ["❌ لغو"]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


# ------------------------------------------------------------
# BINANCE
# ------------------------------------------------------------

session_http = requests.Session()
session_http.headers.update({"User-Agent": "SpotAnalyzerTelegram/1.0"})


def normalize_symbol(value: str) -> str:
    s = value.upper().strip().replace(" ", "").replace("-", "")
    if "/" in s:
        s = s.replace("/", "")
    if not s.endswith("USDT"):
        s += "USDT"
    if not re.fullmatch(r"[A-Z0-9]{5,20}", s):
        raise ValueError("نام ارز معتبر نیست.")
    return s


def get_json(path, params=None, timeout=15):
    r = session_http.get(
        BINANCE_BASE + path,
        params=params,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "code" in data and data.get("code", 0) < 0:
        raise ValueError(data.get("msg", "Binance API error"))
    return data


def get_klines(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    data = get_json(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000),
        },
    )

    if not data:
        raise ValueError(f"No candle data for {symbol} {interval}")

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_base", "taker_quote", "ignore"
    ]
    df = pd.DataFrame(data, columns=cols)

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["time", "open", "high", "low", "close", "volume"]].copy()
    return df


def get_price(symbol: str) -> float:
    data = get_json("/api/v3/ticker/price", {"symbol": symbol})
    return float(data["price"])


# ------------------------------------------------------------
# INDICATORS
# ------------------------------------------------------------

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1 / period, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df, 14)
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df


# ------------------------------------------------------------
# SUPPORT / RESISTANCE / TREND
# ------------------------------------------------------------

def find_levels(df: pd.DataFrame):
    recent = df.tail(120)

    lows = recent["low"].nsmallest(12).values
    highs = recent["high"].nlargest(12).values

    support = float(np.median(lows))
    resistance = float(np.median(highs))

    current = float(df["close"].iloc[-1])

    # Safety: make levels logically ordered around current price
    below = recent.loc[recent["low"] < current, "low"]
    above = recent.loc[recent["high"] > current, "high"]

    if len(below):
        support = float(below.quantile(0.20))
    if len(above):
        resistance = float(above.quantile(0.80))

    if support >= current:
        support = current * 0.96

    if resistance <= current:
        resistance = current * 1.06

    return support, resistance


def linear_trendline(df: pd.DataFrame, kind="low", window=80):
    d = df.tail(window).reset_index(drop=True)

    if kind == "low":
        y = d["low"].values
    else:
        y = d["high"].values

    x = np.arange(len(d))

    # Use regression on all recent values; robust enough for a visual trendline.
    slope, intercept = np.polyfit(x, y, 1)
    line = slope * x + intercept

    return d, line, slope


# ------------------------------------------------------------
# TIMEFRAME ANALYSIS
# ------------------------------------------------------------

def analyze_timeframe(symbol: str, interval: str):
    df = add_indicators(get_klines(symbol, interval, 300))

    close = float(df["close"].iloc[-1])
    e20 = float(df["ema20"].iloc[-1])
    e50 = float(df["ema50"].iloc[-1])
    e200 = float(df["ema200"].iloc[-1])
    rv = float(df["rsi"].iloc[-1])
    volume = float(df["volume"].iloc[-1])
    volume_ma = float(df["vol_ma20"].iloc[-1]) if pd.notna(df["vol_ma20"].iloc[-1]) else volume

    support, resistance = find_levels(df)

    score = 50.0

    # EMA structure
    if close > e20:
        score += 7
    else:
        score -= 7

    if e20 > e50:
        score += 8
    else:
        score -= 8

    if e50 > e200:
        score += 10
    else:
        score -= 10

    # RSI
    if 50 <= rv <= 68:
        score += 8
    elif 42 <= rv < 50:
        score += 2
    elif rv > 72:
        score -= 5
    elif rv < 35:
        score -= 5
    else:
        score -= 2

    # Volume confirmation
    if volume_ma > 0:
        vr = volume / volume_ma
        if vr >= 1.5:
            score += 7
        elif vr >= 1.0:
            score += 3
        else:
            score -= 3

    # Price location
    if close > resistance:
        score += 8
        structure = "BREAKOUT"
    elif close >= support * 1.015:
        structure = "RANGE / MID"
    else:
        score -= 3
        structure = "NEAR SUPPORT"

    score = float(np.clip(score, 0, 100))

    if score >= 70:
        signal = "BUY"
    elif score >= 58:
        signal = "BUY CONFIRMATION"
    elif score <= 38:
        signal = "SELL / AVOID"
    else:
        signal = "WAIT"

    return {
        "df": df,
        "close": close,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "rsi": rv,
        "volume": volume,
        "volume_ma": volume_ma,
        "support": support,
        "resistance": resistance,
        "score": score,
        "signal": signal,
        "structure": structure,
    }


def analyze_btc():
    analyses = {}

    for tf in ["4h", "1d"]:
        analyses[tf] = analyze_timeframe("BTCUSDT", tf)

    score = analyses["4h"]["score"] * 0.55 + analyses["1d"]["score"] * 0.45

    if score >= 70:
        state = "BULLISH"
    elif score >= 55:
        state = "NEUTRAL-BULLISH"
    elif score >= 45:
        state = "NEUTRAL"
    elif score >= 30:
        state = "NEUTRAL-BEARISH"
    else:
        state = "BEARISH"

    return {
        "score": float(score),
        "state": state,
        "4h": analyses["4h"],
        "1d": analyses["1d"],
    }


# ------------------------------------------------------------
# FINAL SCORE
# ------------------------------------------------------------

def final_score(tf):
    # Higher timeframes receive more weight.
    score = (
        tf["15m"]["score"] * 0.15
        + tf["30m"]["score"] * 0.20
        + tf["4h"]["score"] * 0.35
        + tf["1d"]["score"] * 0.30
    )

    if score >= 72:
        decision = "STRONG BUY"
    elif score >= 62:
        decision = "BUY"
    elif score >= 55:
        decision = "BUY ON CONFIRMATION"
    elif score <= 38:
        decision = "SELL / AVOID"
    else:
        decision = "WAIT"

    return float(score), decision


# ------------------------------------------------------------
# TRADE PLAN
# ------------------------------------------------------------

def make_trade_plan(entry, support, resistance, capital, atr_value):
    entry = float(entry)
    support = float(support)
    resistance = float(resistance)
    atr_value = max(float(atr_value), entry * 0.01)

    # Stop below support, with ATR buffer.
    stop = min(
        support - atr_value * 0.35,
        entry - atr_value * 0.80,
    )

    # Never create an invalid stop.
    if stop <= 0 or stop >= entry:
        stop = entry * 0.92

    risk = entry - stop

    # Target 1 is normally resistance / minimum 1R.
    tp1 = max(resistance, entry + risk * 1.0)
    tp2 = max(entry + risk * 2.0, tp1 * 1.12)
    tp3 = max(entry + risk * 3.0, tp2 * 1.12)

    quantity = capital / entry

    def pnl(target):
        dollars = quantity * (target - entry)
        pct = (target / entry - 1) * 100
        return dollars, pct

    sl_dollars, sl_pct = pnl(stop)
    tp1_dollars, tp1_pct = pnl(tp1)
    tp2_dollars, tp2_pct = pnl(tp2)
    tp3_dollars, tp3_pct = pnl(tp3)

    rr = (tp2 - entry) / risk if risk > 0 else 0

    return {
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "quantity": quantity,
        "sl_profit": sl_dollars,
        "sl_percent": sl_pct,
        "tp1_profit": tp1_dollars,
        "tp1_percent": tp1_pct,
        "tp2_profit": tp2_dollars,
        "tp2_percent": tp2_pct,
        "tp3_profit": tp3_dollars,
        "tp3_percent": tp3_pct,
        "rr": rr,
    }


# ------------------------------------------------------------
# PRICE FORMAT
# ------------------------------------------------------------

def fmt_price(x):
    x = float(x)

    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.4f}"
    if x >= 0.1:
        return f"{x:.5f}"
    if x >= 0.01:
        return f"{x:.5f}"
    if x >= 0.001:
        return f"{x:.6f}"
    if x >= 0.0001:
        return f"{x:.7f}"

    return f"{x:.10f}".rstrip("0")


# ------------------------------------------------------------
# CHART
# ------------------------------------------------------------

def make_chart(symbol, analyses, btc, plan, score, decision, capital, output):
    df = analyses["4h"]["df"].tail(140).copy()
    support = analyses["4h"]["support"]
    resistance = analyses["4h"]["resistance"]

    fig = plt.figure(figsize=(18, 11), facecolor="#071018")

    gs = fig.add_gridspec(
        4, 1,
        height_ratios=[5.8, 1.5, 1.4, 2.3],
        hspace=0.12
    )

    ax = fig.add_subplot(gs[0])
    ax_rsi = fig.add_subplot(gs[1], sharex=ax)
    ax_vol = fig.add_subplot(gs[2], sharex=ax)
    ax_info = fig.add_subplot(gs[3])

    for a in [ax, ax_rsi, ax_vol, ax_info]:
        a.set_facecolor("#071018")
        for sp in a.spines.values():
            sp.set_color("#33404d")

    # Candles
    x = np.arange(len(df))
    width = 0.62

    for i, row in enumerate(df.itertuples()):
        up = row.close >= row.open
        body_low = min(row.open, row.close)
        body_h = max(abs(row.close - row.open), row.close * 0.0002)

        color = "#16c784" if up else "#ea3943"

        ax.vlines(
            i,
            row.low,
            row.high,
            color=color,
            linewidth=0.8,
            alpha=0.9,
        )

        rect = Rectangle(
            (i - width / 2, body_low),
            width,
            body_h,
            facecolor=color,
            edgecolor=color,
            linewidth=0.5,
        )
        ax.add_patch(rect)

    # EMA
    ax.plot(x, df["ema20"], color="#f2c94c", linewidth=1.3, label="EMA20")
    ax.plot(x, df["ema50"], color="#56ccf2", linewidth=1.2, label="EMA50")
    ax.plot(x, df["ema200"], color="#bb86fc", linewidth=1.1, label="EMA200")

    # Support / Resistance
    ax.axhline(
        resistance,
        color="#ff5252",
        linestyle="--",
        linewidth=1.6,
    )
    ax.axhline(
        support,
        color="#00e676",
        linestyle="--",
        linewidth=1.6,
    )

    ax.text(
        len(df) - 1,
        resistance,
        f"  Resistance {fmt_price(resistance)}",
        color="#ff7070",
        va="bottom",
        ha="right",
        fontsize=9,
    )

    ax.text(
        len(df) - 1,
        support,
        f"  Support {fmt_price(support)}",
        color="#62e89a",
        va="top",
        ha="right",
        fontsize=9,
    )

    # Trendline approximation
    d2, line_low, slope_low = linear_trendline(df, "low", min(80, len(df)))
    start = len(df) - len(d2)
    ax.plot(
        np.arange(start, len(df)),
        line_low,
        color="#00b0ff",
        linewidth=1.5,
        alpha=0.9,
    )

    d3, line_high, slope_high = linear_trendline(df, "high", min(80, len(df)))
    ax.plot(
        np.arange(start, len(df)),
        line_high,
        color="#ffd740",
        linewidth=1.5,
        alpha=0.9,
    )

    # Trade levels
    levels = [
        (plan["entry"], "#ff9800", "ENTRY"),
        (plan["stop"], "#ff1744", "STOP LOSS"),
        (plan["tp1"], "#00e676", "TP1"),
        (plan["tp2"], "#00e676", "TP2"),
        (plan["tp3"], "#00e676", "TP3"),
    ]

    for level, color, label in levels:
        ax.axhline(
            level,
            color=color,
            linestyle=":",
            linewidth=1.4,
        )
        ax.text(
            len(df) - 1,
            level,
            f"  {label} {fmt_price(level)}",
            color=color,
            fontsize=9,
            va="center",
            ha="right",
            bbox=dict(
                boxstyle="round,pad=0.15",
                facecolor="#071018",
                edgecolor=color,
                alpha=0.9,
            ),
        )

    # Current price marker
    current = float(df["close"].iloc[-1])
    ax.scatter(
        len(df) - 1,
        current,
        s=45,
        color="#ffffff",
        zorder=10,
    )

    ax.set_title(
        f"{symbol} / USDT   •   4H   •   BINANCE",
        color="white",
        fontsize=15,
        loc="left",
        pad=10,
        fontweight="bold",
    )

    ax.text(
        0.01,
        0.96,
        f"Score: {score:.0f}/100   |   {decision}",
        transform=ax.transAxes,
        color="#ffd740",
        fontsize=11,
        va="top",
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="#111b25",
            edgecolor="#ffd740",
        ),
    )

    ax.grid(alpha=0.10)
    ax.tick_params(colors="#b8c4d0", labelsize=8)
    ax.legend(
        loc="upper left",
        fontsize=8,
        facecolor="#101a23",
        edgecolor="#33404d",
        labelcolor="white",
    )

    # RSI
    rsi_values = df["rsi"]
    ax_rsi.plot(x, rsi_values, color="#b388ff", linewidth=1.5)
    ax_rsi.axhline(70, color="#ff5252", linestyle="--", alpha=0.6)
    ax_rsi.axhline(50, color="#888888", linestyle="--", alpha=0.5)
    ax_rsi.axhline(30, color="#00e676", linestyle="--", alpha=0.6)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.set_ylabel("RSI", color="#b8c4d0")
    ax_rsi.tick_params(colors="#b8c4d0", labelsize=8)
    ax_rsi.grid(alpha=0.08)

    # Volume
    vol_colors = np.where(
        df["close"] >= df["open"],
        "#16c784",
        "#ea3943",
    )
    ax_vol.bar(
        x,
        df["volume"],
        color=vol_colors,
        width=0.65,
        alpha=0.85,
    )
    ax_vol.plot(
        x,
        df["vol_ma20"],
        color="#ffd740",
        linewidth=1.0,
    )
    ax_vol.set_ylabel("Volume", color="#b8c4d0")
    ax_vol.tick_params(colors="#b8c4d0", labelsize=8)
    ax_vol.grid(alpha=0.08)

    # Bottom information cards
    ax_info.axis("off")

    def card(x0, y0, w, h, title, lines, edge):
        ax_info.text(
            x0,
            y0 + h,
            title,
            transform=ax_info.transAxes,
            color=edge,
            fontsize=11,
            fontweight="bold",
            va="top",
        )

        text = "\n".join(lines)
        ax_info.text(
            x0,
            y0 + h - 0.12,
            text,
            transform=ax_info.transAxes,
            color="#dce5ee",
            fontsize=9,
            va="top",
            linespacing=1.55,
            bbox=dict(
                boxstyle="round,pad=0.65",
                facecolor="#0c1721",
                edgecolor=edge,
                linewidth=1.0,
            ),
        )

    card(
        0.01, 0.08, 0.30, 0.80,
        "TIMEFRAME SCORE",
        [
            f"15m  {analyses['15m']['score']:.0f}/100  {analyses['15m']['signal']}",
            f"30m  {analyses['30m']['score']:.0f}/100  {analyses['30m']['signal']}",
            f"4H   {analyses['4h']['score']:.0f}/100  {analyses['4h']['signal']}",
            f"1D   {analyses['1d']['score']:.0f}/100  {analyses['1d']['signal']}",
            f"BTC  {btc['score']:.0f}/100  {btc['state']}",
        ],
        "#00e676",
    )

    card(
        0.345, 0.08, 0.30, 0.80,
        "TRADE PLAN",
        [
            f"ENTRY   {fmt_price(plan['entry'])}",
            f"STOP    {fmt_price(plan['stop'])}",
            f"TP1     {fmt_price(plan['tp1'])}",
            f"TP2     {fmt_price(plan['tp2'])}",
            f"TP3     {fmt_price(plan['tp3'])}",
            f"R/R     1 : {plan['rr']:.2f}",
        ],
        "#ff9800",
    )

    card(
        0.68, 0.08, 0.30, 0.80,
        f"CAPITAL ${capital:,.0f}",
        [
            f"Quantity {plan['quantity']:,.2f}",
            f"SL   ${plan['sl_profit']:+,.2f}",
            f"TP1  ${plan['tp1_profit']:+,.2f}",
            f"TP2  ${plan['tp2_profit']:+,.2f}",
            f"TP3  ${plan['tp3_profit']:+,.2f}",
        ],
        "#42a5f5",
    )

    plt.setp(ax.get_xticklabels(), visible=False)
    plt.setp(ax_rsi.get_xticklabels(), visible=False)

    fig.text(
        0.5,
        0.985,
        "AUTOMATIC SPOT ANALYSIS • FOR DECISION SUPPORT",
        color="#ffd740",
        ha="center",
        va="top",
        fontsize=12,
        fontweight="bold",
    )

    fig.savefig(
        output,
        dpi=150,
        facecolor=fig.get_facecolor(),
        bbox_inches="tight",
    )
    plt.close(fig)


# ------------------------------------------------------------
# FULL ANALYSIS
# ------------------------------------------------------------

def run_analysis(symbol, capital, entry):
    tf = {}

    for interval in ["15m", "30m", "4h", "1d"]:
        tf[interval] = analyze_timeframe(symbol, interval)

    btc = analyze_btc()

    score, decision = final_score(tf)

    if entry is None:
        entry = tf["15m"]["close"]

    plan = make_trade_plan(
        entry,
        tf["4h"]["support"],
        tf["4h"]["resistance"],
        capital,
        tf["4h"]["df"]["atr"].iloc[-1],
    )

    filename = REPORT_DIR / (
        f"{symbol}_{int(time.time() * 1000)}.png"
    )

    make_chart(
        symbol,
        tf,
        btc,
        plan,
        score,
        decision,
        capital,
        str(filename),
    )

    return {
        "symbol": symbol,
        "capital": capital,
        "entry": entry,
        "tf": tf,
        "btc": btc,
        "score": score,
        "decision": decision,
        "plan": plan,
        "image": filename,
    }


# ------------------------------------------------------------
# TELEGRAM FORMATTING
# ------------------------------------------------------------

def decision_fa(decision):
    return {
        "STRONG BUY": "🟢 خرید قوی",
        "BUY": "🟢 خرید",
        "BUY ON CONFIRMATION": "🟡 خرید با تأیید",
        "WAIT": "🟡 صبر",
        "SELL / AVOID": "🔴 فروش / اجتناب",
    }.get(decision, decision)


def result_text(r):
    p = r["plan"]
    t = r["tf"]
    btc = r["btc"]

    return (
        f"📊 <b>{r['symbol']} / USDT</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎯 Score: <b>{r['score']:.0f}/100</b>\n"
        f"📌 Decision: <b>{decision_fa(r['decision'])}</b>\n"
        f"₿ BTC: <b>{btc['score']:.0f}/100</b> — {btc['state']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⏱ <b>TIMEFRAMES</b>\n"
        f"15m → {t['15m']['score']:.0f}/100 — {t['15m']['signal']}\n"
        f"30m → {t['30m']['score']:.0f}/100 — {t['30m']['signal']}\n"
        f"4H  → {t['4h']['score']:.0f}/100 — {t['4h']['signal']}\n"
        f"1D  → {t['1d']['score']:.0f}/100 — {t['1d']['signal']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Capital: <b>${r['capital']:,.2f}</b>\n"
        f"🟠 Entry: <b>{fmt_price(p['entry'])}</b>\n"
        f"🔴 SL: <b>{fmt_price(p['stop'])}</b>\n"
        f"🟢 TP1: <b>{fmt_price(p['tp1'])}</b>\n"
        f"🟢 TP2: <b>{fmt_price(p['tp2'])}</b>\n"
        f"🟢 TP3: <b>{fmt_price(p['tp3'])}</b>\n"
        f"⚖️ R/R: <b>1:{p['rr']:.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔴 SL P/L: ${p['sl_profit']:+,.2f} "
        f"({p['sl_percent']:+.2f}%)\n"
        f"🟢 TP1 P/L: ${p['tp1_profit']:+,.2f} "
        f"({p['tp1_percent']:+.2f}%)\n"
        f"🟢 TP2 P/L: ${p['tp2_profit']:+,.2f} "
        f"({p['tp2_percent']:+.2f}%)\n"
        f"🟢 TP3 P/L: ${p['tp3_profit']:+,.2f} "
        f"({p['tp3_percent']:+.2f}%)\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🪙 Quantity: <b>{p['quantity']:,.2f}</b>\n\n"
        f"⚠️ تحلیل است؛ سفارش خرید/فروش ارسال نمی‌شود."
    )


# ------------------------------------------------------------
# TELEGRAM HANDLERS
# ------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "🤖 به ربات تحلیل‌گر اسپات خوش آمدی.\n\n"
        "برای شروع روی «🔍 تحلیل ارز» بزن.",
        reply_markup=MAIN_MENU,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ راهنما\n\n"
        "🔍 تحلیل ارز:\n"
        "نام ارز + سرمایه + Entry را مرحله‌به‌مرحله می‌گیرد.\n\n"
        "🔄 تحلیل مجدد:\n"
        "همان ارز را با داده جدید تحلیل می‌کند.\n\n"
        "💰 سود / ضرر:\n"
        "P/L بر اساس سرمایه را نشان می‌دهد.\n\n"
        "🎯 تغییر Entry:\n"
        "Entry جدید می‌گیرد و محاسبه را به‌روز می‌کند.\n\n"
        "🛑 SL / TP:\n"
        "سطوح معامله را نشان می‌دهد.",
        reply_markup=MAIN_MENU,
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ لغو شد.",
        reply_markup=MAIN_MENU,
    )
    return ConversationHandler.END


async def analysis_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["trade"] = {
        "symbol": None,
        "capital": None,
        "entry": None,
        "result": None,
    }

    await update.message.reply_text(
        "🔍 نام ارز را وارد کن.\n\n"
        "مثال:\n"
        "RESOLV\n\n"
        "USDT لازم نیست.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return COIN


async def get_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = normalize_symbol(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return COIN

    context.user_data["trade"]["symbol"] = symbol

    await update.message.reply_text(
        f"✅ {symbol}\n\n"
        "💰 سرمایه را به دلار وارد کن.\n"
        "مثال: 3000"
    )

    return CAPITAL


async def get_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        capital = float(update.message.text.replace(",", "").strip())
        if capital <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text(
            "❌ سرمایه باید عدد مثبت باشد.\nمثال: 3000"
        )
        return CAPITAL

    context.user_data["trade"]["capital"] = capital

    await update.message.reply_text(
        "🎯 Entry را وارد کن.\n\n"
        "مثال:\n"
        "0.01687\n\n"
        "یا «📍 قیمت فعلی» را بزن.",
        reply_markup=ENTRY_MENU,
    )

    return ENTRY


async def get_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ لغو":
        await cancel(update, context)
        return ConversationHandler.END

    if text == "📍 قیمت فعلی":
        entry = None
    else:
        try:
            entry = float(text.replace(",", ""))
            if entry <= 0:
                raise ValueError
        except Exception:
            await update.message.reply_text(
                "❌ Entry معتبر نیست.\nمثال: 0.01687"
            )
            return ENTRY

    context.user_data["trade"]["entry"] = entry

    await update.message.reply_text(
        "⏳ در حال تحلیل Binance...\n"
        "15m + 30m + 4H + 1D + BTC\n"
        "و ساخت تصویر نمودار...",
        reply_markup=MAIN_MENU,
    )

    await do_analysis(update, context)

    return ConversationHandler.END


async def do_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trade = context.user_data.get("trade")

    if not trade or not trade.get("symbol"):
        await update.message.reply_text(
            "ابتدا «🔍 تحلیل ارز» را بزن.",
            reply_markup=MAIN_MENU,
        )
        return

    symbol = trade["symbol"]
    capital = trade["capital"]
    entry = trade["entry"]

    status = await update.message.reply_text(
        "🔄 تحلیل در حال انجام است..."
    )

    try:
        result = await asyncio.to_thread(
            run_analysis,
            symbol,
            capital,
            entry,
        )

        trade["result"] = result

        await status.edit_text(
            result_text(result),
            parse_mode="HTML",
        )

        with open(result["image"], "rb") as f:
            await update.message.reply_photo(
                photo=f,
                caption=(
                    f"📈 {symbol}/USDT — Automated Chart\n"
                    f"Score: {result['score']:.0f}/100"
                ),
            )

    except Exception as e:
        await status.edit_text(
            "❌ تحلیل انجام نشد.\n\n"
            f"{e}\n\n"
            "ممکن است نماد در Binance Spot وجود نداشته باشد."
        )


async def reanalyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("trade", {}).get("symbol"):
        await update.message.reply_text(
            "ابتدا «🔍 تحلیل ارز» را بزن.",
            reply_markup=MAIN_MENU,
        )
        return

    await update.message.reply_text("🔄 تحلیل مجدد...")
    await do_analysis(update, context)


async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = context.user_data.get("trade", {}).get("result")

    if not r:
        await update.message.reply_text(
            "هنوز تحلیلی انجام نشده.",
            reply_markup=MAIN_MENU,
        )
        return

    p = r["plan"]

    await update.message.reply_text(
        f"💰 <b>{r['symbol']} — P/L</b>\n\n"
        f"Capital: ${r['capital']:,.2f}\n\n"
        f"🔴 SL: ${p['sl_profit']:+,.2f} ({p['sl_percent']:+.2f}%)\n"
        f"🟢 TP1: ${p['tp1_profit']:+,.2f} ({p['tp1_percent']:+.2f}%)\n"
        f"🟢 TP2: ${p['tp2_profit']:+,.2f} ({p['tp2_percent']:+.2f}%)\n"
        f"🟢 TP3: ${p['tp3_profit']:+,.2f} ({p['tp3_percent']:+.2f}%)",
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )


async def levels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = context.user_data.get("trade", {}).get("result")

    if not r:
        await update.message.reply_text(
            "ابتدا یک تحلیل انجام بده.",
            reply_markup=MAIN_MENU,
        )
        return

    p = r["plan"]

    await update.message.reply_text(
        f"🎯 <b>{r['symbol']} — TRADE PLAN</b>\n\n"
        f"🟠 Entry: {fmt_price(p['entry'])}\n"
        f"🔴 SL: {fmt_price(p['stop'])}\n"
        f"🟢 TP1: {fmt_price(p['tp1'])}\n"
        f"🟢 TP2: {fmt_price(p['tp2'])}\n"
        f"🟢 TP3: {fmt_price(p['tp3'])}\n\n"
        f"⚖️ Risk/Reward: 1:{p['rr']:.2f}",
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )


async def change_entry_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trade = context.user_data.get("trade")

    if not trade or not trade.get("symbol"):
        await update.message.reply_text(
            "ابتدا یک تحلیل انجام بده.",
            reply_markup=MAIN_MENU,
        )
        return

    context.user_data["changing_entry"] = True

    await update.message.reply_text(
        f"🎯 Entry جدید برای {trade['symbol']} را وارد کن.\n"
        f"مثال: 0.01687\n\n"
        f"یا «📍 قیمت فعلی» را بزن.",
        reply_markup=ENTRY_MENU,
    )


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Entry change mode
    if context.user_data.get("changing_entry"):
        if text == "❌ لغو":
            context.user_data["changing_entry"] = False
            await update.message.reply_text(
                "لغو شد.",
                reply_markup=MAIN_MENU,
            )
            return

        if text == "📍 قیمت فعلی":
            entry = None
        else:
            try:
                entry = float(text.replace(",", ""))
                if entry <= 0:
                    raise ValueError
            except Exception:
                await update.message.reply_text(
                    "Entry معتبر نیست. مثال: 0.01687"
                )
                return

        context.user_data["trade"]["entry"] = entry
        context.user_data["changing_entry"] = False

        await update.message.reply_text(
            "🎯 Entry تغییر کرد. در حال تحلیل مجدد...",
            reply_markup=MAIN_MENU,
        )

        await do_analysis(update, context)
        return

    await update.message.reply_text(
        "از منوی ربات استفاده کن.",
        reply_markup=MAIN_MENU,
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(r"^🔍 تحلیل ارز$"),
                analysis_start,
            )
        ],
        states={
            COIN: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_coin,
                )
            ],
            CAPITAL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_capital,
                )
            ],
            ENTRY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_entry,
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conversation)

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🔄 تحلیل مجدد$"),
            reanalyze,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^💰 سود / ضرر$"),
            pnl,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🎯 تغییر Entry$"),
            change_entry_start,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🛑 SL / TP$"),
            levels,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^ℹ️ راهنما$"),
            help_cmd,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    print("SPOT ANALYZER BOT IS RUNNING...")
    app.run_polling()


if __name__ == "__main__":
    main()
