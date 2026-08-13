# -*- coding: utf-8 -*-
"""
RESOLV / UNIVERSAL SPOT ANALYZER - FINAL VISUAL VERSION
---------------------------------------------------------
Input:
  Coin symbol, capital in USD, optional desired entry price.

Analysis:
  15m + 30m + 4H + 1D
  BTC 4H + 1D filter
  EMA20/50/200, RSI, ATR, Volume, Support/Resistance,
  Market Structure, Trendlines, Breakout.

Output:
  A professional PNG similar to the supplied sample:
  candles + levels + trendlines + Entry/SL/TP + RSI + Volume
  + timeframe scores + BTC filter + P/L table + trade plan.

Install:
  pip install requests pandas numpy matplotlib
Optional for Persian labels:
  pip install arabic-reshaper python-bidi
"""

import os
import math
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

# ------------------------------------------------------------
# Optional Persian text support
# ------------------------------------------------------------
try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    def fa(text):
        return get_display(arabic_reshaper.reshape(str(text)))
except Exception:
    def fa(text):
        return str(text)

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
BASE_URL = "https://api.binance.com/api/v3"
FEE_RATE = 0.001  # 0.10% per side; change if your fee differs

TIMEFRAME_WEIGHTS = {
    "15m": 0.15,
    "30m": 0.20,
    "4h": 0.30,
    "1d": 0.35,
}

# Dark chart colors
BG = "#080d16"
PANEL = "#101827"
GRID = "#263244"
TEXT = "#f4f7fb"
GREEN = "#18c964"
RED = "#ff3b4d"
BLUE = "#39a0ff"
YELLOW = "#f4c542"
ORANGE = "#ff9f1c"
PURPLE = "#b36bff"
CYAN = "#4dd9ff"
GRAY = "#9aa6b2"

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().strip().replace("/", "").replace("-", "").replace(" ", "")
    if not s.endswith("USDT"):
        s += "USDT"
    return s

def fmt_price(v: float) -> str:
    if v >= 100:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:,.4f}"
    if v >= 0.1:
        return f"{v:.5f}"
    if v >= 0.01:
        return f"{v:.6f}"
    if v >= 0.001:
        return f"{v:.7f}"
    return f"{v:.10f}"

def pct(v: float) -> str:
    return f"{v:+.2f}%"

# ------------------------------------------------------------
# Binance data
# ------------------------------------------------------------
def get_klines(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    symbol = normalize_symbol(symbol)
    r = requests.get(
        f"{BASE_URL}/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=20,
    )
    r.raise_for_status()
    raw = r.json()
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"No candle data for {symbol} {interval}")

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(raw, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df

# ------------------------------------------------------------
# Indicators
# ------------------------------------------------------------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    ag = gain.ewm(alpha=1/n, adjust=False).mean()
    al = loss.ewm(alpha=1/n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def add_indicators(df):
    d = df.copy()
    d["EMA20"] = ema(d["close"], 20)
    d["EMA50"] = ema(d["close"], 50)
    d["EMA200"] = ema(d["close"], 200)
    d["RSI"] = rsi(d["close"], 14)
    d["ATR"] = atr(d, 14)
    d["VolumeMA"] = d["volume"].rolling(20).mean()
    d["VolumeRatio"] = d["volume"] / d["VolumeMA"]
    return d

# ------------------------------------------------------------
# Swings / structure / levels
# ------------------------------------------------------------
def find_swings(df, window=3):
    highs, lows = [], []
    for i in range(window, len(df) - window):
        h = float(df["high"].iloc[i])
        l = float(df["low"].iloc[i])
        if h >= df["high"].iloc[i-window:i].max() and h >= df["high"].iloc[i+1:i+window+1].max():
            highs.append((i, h))
        if l <= df["low"].iloc[i-window:i].min() and l <= df["low"].iloc[i+1:i+window+1].min():
            lows.append((i, l))
    return highs, lows

def market_structure(df):
    d = df.tail(140).reset_index(drop=True)
    highs, lows = find_swings(d, 3)
    hh = len(highs) >= 2 and highs[-1][1] > highs[-2][1]
    hl = len(lows) >= 2 and lows[-1][1] > lows[-2][1]
    lh = len(highs) >= 2 and highs[-1][1] < highs[-2][1]
    ll = len(lows) >= 2 and lows[-1][1] < lows[-2][1]
    if hh and hl:
        return "HH / HL"
    if lh and ll:
        return "LH / LL"
    return "MIXED"

def levels(df):
    d = df.tail(160).reset_index(drop=True)
    current = float(d["close"].iloc[-1])
    highs, lows = find_swings(d, 3)
    supports = [v for _, v in lows if v < current]
    resistances = [v for _, v in highs if v > current]

    if supports:
        support = max(supports)
    else:
        support = float(d["low"].nsmallest(12).max())

    if resistances:
        resistance = min(resistances)
    else:
        resistance = float(d["high"].nlargest(12).min())

    return {
        "support": support,
        "resistance": resistance,
        "major_low": float(d["low"].min()),
        "major_high": float(d["high"].max()),
    }

def trendlines(df):
    d = df.tail(160).reset_index(drop=True)
    highs, lows = find_swings(d, 3)
    out = {"down": None, "up": None}

    if len(highs) >= 2:
        x1, y1 = highs[-2]
        x2, y2 = highs[-1]
        if x2 != x1:
            m = (y2 - y1) / (x2 - x1)
            out["down"] = (m, y1 - m*x1)

    if len(lows) >= 2:
        x1, y1 = lows[-2]
        x2, y2 = lows[-1]
        if x2 != x1:
            m = (y2 - y1) / (x2 - x1)
            out["up"] = (m, y1 - m*x1)
    return out

# ------------------------------------------------------------
# Timeframe score
# ------------------------------------------------------------
def analyze_tf(raw, tf):
    d = add_indicators(raw)
    current = float(d["close"].iloc[-1])
    e20 = float(d["EMA20"].iloc[-1])
    e50 = float(d["EMA50"].iloc[-1])
    e200 = float(d["EMA200"].iloc[-1])
    rv = float(d["RSI"].iloc[-1])
    av = float(d["ATR"].iloc[-1])
    vr = float(d["VolumeRatio"].iloc[-1])
    lv = levels(d)
    struct = market_structure(d)
    tls = trendlines(d)

    score = 50
    reasons = []

    if current > e20:
        score += 5; reasons.append("Price > EMA20")
    else:
        score -= 5; reasons.append("Price < EMA20")

    if e20 > e50:
        score += 8; reasons.append("EMA20 > EMA50")
    else:
        score -= 8; reasons.append("EMA20 < EMA50")

    if current > e200:
        score += 8; reasons.append("Price > EMA200")
    else:
        score -= 8; reasons.append("Price < EMA200")

    if 50 <= rv <= 65:
        score += 8; reasons.append("Healthy RSI")
    elif 65 < rv <= 72:
        score += 3; reasons.append("Strong RSI")
    elif rv > 72:
        score -= 8; reasons.append("Overbought RSI")
    elif 30 <= rv < 40:
        score -= 5; reasons.append("Weak RSI")
    elif rv < 30:
        score += 3; reasons.append("Oversold RSI")

    if vr >= 1.50:
        score += 8; reasons.append("Very high volume")
    elif vr >= 1.20:
        score += 5; reasons.append("High volume")
    elif vr < 0.70:
        score -= 5; reasons.append("Low volume")

    if struct == "HH / HL":
        score += 10; reasons.append("Bullish structure")
    elif struct == "LH / LL":
        score -= 10; reasons.append("Bearish structure")

    sd = (current - lv["support"]) / current * 100
    rd = (lv["resistance"] - current) / current * 100

    if 0 <= sd <= 2.5:
        score += 5; reasons.append("Near support")
    if 0 <= rd <= 2.5:
        score -= 4; reasons.append("Near resistance")

    prev = float(d["close"].iloc[-2])
    breakout = "NONE"
    if prev <= lv["resistance"] and current > lv["resistance"]:
        breakout = "BULLISH BREAKOUT"
        if vr >= 1.20:
            score += 10; reasons.append("Breakout + volume")
    elif prev >= lv["support"] and current < lv["support"]:
        breakout = "BEARISH BREAKDOWN"
        if vr >= 1.20:
            score -= 10; reasons.append("Breakdown + volume")

    score = max(0, min(100, score))
    if score >= 80:
        signal = "STRONG BUY"
    elif score >= 70:
        signal = "BUY"
    elif score >= 60:
        signal = "BUY CONFIRMATION"
    elif score >= 45:
        signal = "WAIT"
    elif score >= 35:
        signal = "WEAK SELL"
    else:
        signal = "SELL"

    return {
        "df": d, "timeframe": tf, "price": current,
        "ema20": e20, "ema50": e50, "ema200": e200,
        "rsi": rv, "atr": av, "volume_ratio": vr,
        "support": lv["support"], "resistance": lv["resistance"],
        "major_low": lv["major_low"], "major_high": lv["major_high"],
        "structure": struct, "breakout": breakout,
        "trendlines": tls, "score": float(score),
        "signal": signal, "reasons": reasons,
    }

def analyze_btc():
    a4 = analyze_tf(get_klines("BTCUSDT", "4h", 300), "4h")
    a1 = analyze_tf(get_klines("BTCUSDT", "1d", 300), "1d")
    score = round(a4["score"]*0.45 + a1["score"]*0.55, 1)
    if score >= 75: state = "BULLISH"
    elif score >= 60: state = "NEUTRAL-BULLISH"
    elif score >= 45: state = "NEUTRAL"
    elif score >= 30: state = "BEARISH"
    else: state = "STRONG BEARISH"
    return {"score": score, "state": state, "4h": a4, "1d": a1}

# ------------------------------------------------------------
# Final score
# ------------------------------------------------------------
def final_score(analyses, btc):
    coin = sum(analyses[tf]["score"] * w for tf, w in TIMEFRAME_WEIGHTS.items())
    adj = 0
    if btc["score"] >= 75: adj = 5
    elif btc["score"] >= 65: adj = 3
    elif btc["score"] < 35: adj = -8
    elif btc["score"] < 45: adj = -5
    elif btc["score"] < 55: adj = -2
    score = round(max(0, min(100, coin + adj)), 1)

    if score >= 80: decision = "STRONG BUY"
    elif score >= 70: decision = "BUY"
    elif score >= 60: decision = "BUY ON CONFIRMATION"
    elif score >= 45: decision = "WAIT"
    elif score >= 35: decision = "WEAK SELL"
    else: decision = "SELL"
    return score, decision

# ------------------------------------------------------------
# Trade plan
# ------------------------------------------------------------
def trade_plan(df, entry, support, resistance, capital):
    d = add_indicators(df)
    a = float(d["ATR"].iloc[-1])
    if not np.isfinite(a) or a <= 0:
        a = entry * 0.02

    stop = min(support * 0.985, entry - 1.5*a)
    if stop >= entry:
        stop = entry * 0.97

    risk = entry - stop
    if risk <= 0:
        risk = entry * 0.03
        stop = entry - risk

    tp1 = resistance if resistance > entry else entry + 1.5*risk
    if tp1 - entry < 1.2*risk:
        tp1 = entry + 1.5*risk
    tp2 = max(tp1 + risk, entry + 2.5*risk)
    tp3 = max(tp2 + risk, entry + 4.0*risk)

    qty = capital / entry

    def pnl(price):
        buy = qty * entry
        sell = qty * price
        profit = sell - sell*FEE_RATE - buy - buy*FEE_RATE
        return profit, profit/capital*100

    sl_p, sl_pct = pnl(stop)
    p1, p1pct = pnl(tp1)
    p2, p2pct = pnl(tp2)
    p3, p3pct = pnl(tp3)

    rr = (tp3 - entry) / risk

    return {
        "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "quantity": qty, "risk": risk, "rr": rr,
        "sl_profit": sl_p, "sl_percent": sl_pct,
        "tp1_profit": p1, "tp1_percent": p1pct,
        "tp2_profit": p2, "tp2_percent": p2pct,
        "tp3_profit": p3, "tp3_percent": p3pct,
    }

# ------------------------------------------------------------
# Chart drawing
# ------------------------------------------------------------
def draw_candles(ax, df):
    for i in range(len(df)):
        o = float(df["open"].iloc[i])
        h = float(df["high"].iloc[i])
        l = float(df["low"].iloc[i])
        c = float(df["close"].iloc[i])
        color = GREEN if c >= o else RED
        ax.plot([i, i], [l, h], color=color, linewidth=1)
        body_low = min(o, c)
        body_h = max(abs(c-o), h*0.00005)
        ax.add_patch(Rectangle(
            (i-0.32, body_low), 0.64, body_h,
            facecolor=color, edgecolor=color, linewidth=0.4
        ))

def hline(ax, price, label, color, style="--", lw=1.5):
    ax.axhline(price, color=color, linestyle=style, linewidth=lw, alpha=0.9)
    ax.text(
        1.002, price, f" {label} {fmt_price(price)}",
        transform=ax.get_yaxis_transform(), color=color,
        fontsize=9, va="center", fontweight="bold"
    )

def trendline(ax, line, n, color, label):
    if line is None:
        return
    m, b = line
    x = np.array([0, n-1])
    y = m*x+b
    ax.plot(x, y, color=color, linewidth=2, alpha=0.85)
    mid = n*0.55
    ax.text(mid, m*mid+b, label, color=color, fontsize=9, fontweight="bold")

def panel(fig, rect, title, lines, edge, title_size=11, line_size=8.5):
    ax = fig.add_axes(rect)
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_edgecolor(edge)
        s.set_linewidth(1.3)
    ax.set_xticks([]); ax.set_yticks([])
    ax.text(0.04, 0.88, title, color=edge, fontsize=title_size, fontweight="bold", va="top")
    y = 0.68
    for line in lines:
        ax.text(0.04, y, line, color=TEXT, fontsize=line_size, va="top")
        y -= 0.16
    return ax

def draw_price_table(ax, plan, capital):
    rows = [
        ("Stop Loss", plan["stop"], plan["sl_profit"], plan["sl_percent"]),
        ("Entry", plan["entry"], 0.0, 0.0),
        ("TP1", plan["tp1"], plan["tp1_profit"], plan["tp1_percent"]),
        ("TP2", plan["tp2"], plan["tp2_profit"], plan["tp2_percent"]),
        ("TP3", plan["tp3"], plan["tp3_profit"], plan["tp3_percent"]),
    ]
    ax.axis("off")
    ax.set_facecolor(PANEL)
    ax.text(0.5, 1.04, fa(f"سود و ضرر احتمالی با سرمایه ${capital:,.0f}"),
            ha="center", color=TEXT, fontsize=11, fontweight="bold")
    headers = ["Level", "Price", "P/L USD", "P/L %"]
    table = ax.table(
        cellText=[[r[0], fmt_price(r[1]), f"{r[2]:+,.2f}", f"{r[3]:+.2f}%"] for r in rows],
        colLabels=headers, cellLoc="center", colLoc="center", loc="upper center",
        bbox=[0.01, 0.02, 0.98, 0.88]
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    for (row, col), cell in table.get_celld().items():
        cell.set_facecolor(PANEL)
        cell.set_edgecolor(GRID)
        cell.get_text().set_color(TEXT)
        if row == 0:
            cell.get_text().set_weight("bold")
        if row > 0 and col in (2, 3):
            val = rows[row-1][2]
            cell.get_text().set_color(RED if val < 0 else GREEN if val > 0 else TEXT)

def generate_chart(symbol, analyses, btc, plan, score, decision, capital, out_file=None):
    main = analyses["4h"]
    df = main["df"].tail(105).reset_index(drop=True)

    if out_file is None:
        out_file = f"{symbol.replace('USDT','')}_FINAL_ANALYSIS.png"

    fig = plt.figure(figsize=(18, 13), facecolor=BG)

    # Main chart
    ax = fig.add_axes([0.055, 0.405, 0.89, 0.49])
    ax.set_facecolor(BG)
    draw_candles(ax, df)

    ax.plot(df.index, df["EMA20"], color=YELLOW, linewidth=1.1, label="EMA20")
    ax.plot(df.index, df["EMA50"], color=BLUE, linewidth=1.1, label="EMA50")
    ax.plot(df.index, df["EMA200"], color=PURPLE, linewidth=1.1, label="EMA200")

    # Strong zones
    sr = main["resistance"]
    sup = main["support"]
    ax.axhspan(sr*0.992, sr*1.008, color=RED, alpha=0.10)
    ax.axhspan(sup*0.992, sup*1.008, color=GREEN, alpha=0.08)

    hline(ax, sr, "RESISTANCE", RED, "-", 1.8)
    hline(ax, sup, "SUPPORT", GREEN, "-", 1.8)
    hline(ax, plan["entry"], "ENTRY", ORANGE, "--", 2.0)
    hline(ax, plan["stop"], "STOP LOSS", RED, "--", 2.0)
    hline(ax, plan["tp1"], "TP1", GREEN, ":", 1.7)
    hline(ax, plan["tp2"], "TP2", GREEN, ":", 1.7)
    hline(ax, plan["tp3"], "TP3", GREEN, ":", 1.7)

    trendline(ax, main["trendlines"]["down"], len(df), YELLOW, fa("خط روند نزولی"))
    trendline(ax, main["trendlines"]["up"], len(df), BLUE, fa("خط روند صعودی"))

    # Breakout arrow / projected path
    breakout = sr
    x0 = len(df) - 12
    x1 = len(df) + 4
    x2 = len(df) + 15
    x3 = len(df) + 27
    y0 = plan["entry"]
    ax.annotate("", xy=(x1, breakout*1.02), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.2))
    ax.annotate("", xy=(x2, plan["tp1"]), xytext=(x1, breakout*1.02),
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.2))
    ax.annotate("", xy=(x3, plan["tp2"]), xytext=(x2, plan["tp1"]),
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.2))
    ax.text(x0+3, breakout, fa("Breakout Level"), color=ORANGE, fontsize=9, fontweight="bold")

    # Bearish path
    ax.annotate("", xy=(x2, plan["stop"]), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.8, linestyle="--"))

    # Title
    current = main["price"]
    ax.set_title(
        fa(f"{symbol} • 4H • BINANCE\n"
           f"قیمت {fmt_price(current)}   |   امتیاز نهایی {score:.0f}/100   |   {decision}"),
        color=TEXT, fontsize=16, fontweight="bold", pad=12
    )
    ax.grid(color=GRID, alpha=0.30)
    ax.tick_params(colors=TEXT, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)

    # RSI
    ar = fig.add_axes([0.055, 0.275, 0.89, 0.09])
    ar.set_facecolor(BG)
    ar.plot(df.index, df["RSI"], color=PURPLE, linewidth=1.7)
    ar.axhline(70, color=RED, linestyle="--", alpha=0.45)
    ar.axhline(50, color=YELLOW, linestyle="--", alpha=0.35)
    ar.axhline(30, color=GREEN, linestyle="--", alpha=0.45)
    ar.set_ylim(0, 100)
    ar.set_ylabel("RSI", color=TEXT)
    ar.tick_params(colors=TEXT, labelsize=8)
    ar.grid(color=GRID, alpha=0.25)
    ar.text(len(df)-16, float(df["RSI"].iloc[-1])+3,
            fa(f"RSI = {df['RSI'].iloc[-1]:.1f}"), color=PURPLE, fontsize=9, fontweight="bold")

    # Volume
    av = fig.add_axes([0.055, 0.16, 0.89, 0.08])
    av.set_facecolor(BG)
    for i in range(len(df)):
        c = GREEN if df["close"].iloc[i] >= df["open"].iloc[i] else RED
        av.bar(i, df["volume"].iloc[i], color=c, width=0.65, alpha=0.75)
    av.plot(df.index, df["VolumeMA"], color=YELLOW, linewidth=1.1)
    av.tick_params(colors=TEXT, labelsize=8)
    av.set_ylabel("VOL", color=TEXT)
    av.grid(color=GRID, alpha=0.25)

    # Panels
    tf_lines = []
    for tf in ["15m", "30m", "4h", "1d"]:
        a = analyses[tf]
        tf_lines.append(f"{tf:>3}   {a['score']:.0f}/100   {a['signal']}")
    tf_lines.append(f"BTC FILTER   {btc['score']:.0f}/100")
    tf_lines.append(f"FINAL         {score:.0f}/100")
    panel(fig, [0.055, 0.035, 0.245, 0.105], fa("امتیاز تایم‌فریم‌ها"), tf_lines, BLUE)

    buy_lines = [
        fa(f"• تثبیت بالای {fmt_price(sr)}"),
        fa(f"• هدف 1: {fmt_price(plan['tp1'])}"),
        fa(f"• هدف 2: {fmt_price(plan['tp2'])}"),
        fa(f"• هدف 3: {fmt_price(plan['tp3'])}"),
        fa("• تأیید حجم و ساختار صعودی"),
    ]
    panel(fig, [0.315, 0.035, 0.245, 0.105], fa("سناریوی خرید (صعودی)"), buy_lines, GREEN)

    sell_lines = [
        fa(f"• عدم شکست {fmt_price(sr)}"),
        fa(f"• شکست حمایت {fmt_price(sup)}"),
        fa(f"• حد ضرر: {fmt_price(plan['stop'])}"),
        fa("• ضعف حجم / ساختار نزولی"),
        fa("• در صورت شکست حمایت، خروج"),
    ]
    panel(fig, [0.575, 0.035, 0.245, 0.105], fa("سناریوی فروش / ریسک (نزولی)"), sell_lines, RED)

    money_lines = [
        f"ENTRY: {fmt_price(plan['entry'])}",
        f"STOP:  {fmt_price(plan['stop'])}",
        f"TP1:   {fmt_price(plan['tp1'])}",
        f"TP2:   {fmt_price(plan['tp2'])}",
        f"TP3:   {fmt_price(plan['tp3'])}",
        f"R/R:   1:{plan['rr']:.2f}",
    ]
    panel(fig, [0.835, 0.035, 0.11, 0.105], "TRADE PLAN", money_lines, ORANGE, line_size=7.5)

    # P/L table in a separate axis above panels
    tab_ax = fig.add_axes([0.315, 0.005, 0.47, 0.025])
    draw_price_table(tab_ax, plan, capital)

    # Small money / BTC box
    fig.text(
        0.79, 0.145,
        fa(f"سرمایه: ${capital:,.0f}\n"
           f"تعداد تقریبی: {plan['quantity']:,.0f}\n"
           f"BTC: {btc['state']} ({btc['score']:.0f}/100)"),
        color=TEXT, fontsize=9, va="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor=PANEL, edgecolor=ORANGE)
    )

    plt.savefig(out_file, dpi=180, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return out_file

# ------------------------------------------------------------
# Console report
# ------------------------------------------------------------
def print_report(symbol, capital, analyses, btc, score, decision, plan, image_path):
    print("\n" + "="*76)
    print(f"{symbol} / SPOT FINAL ANALYSIS")
    print("="*76)
    print(f"FINAL SCORE : {score:.0f}/100")
    print(f"DECISION    : {decision}")
    print(f"BTC FILTER  : {btc['score']:.0f}/100 - {btc['state']}")
    print("-"*76)

    for tf in ["15m", "30m", "4h", "1d"]:
        a = analyses[tf]
        print(
            f"{tf:>3} | Score {a['score']:>5.1f} | RSI {a['rsi']:>5.1f} | "
            f"Vol {a['volume_ratio']:>4.2f}x | {a['structure']:<8} | {a['signal']}"
        )

    print("-"*76)
    print(f"ENTRY       : {fmt_price(plan['entry'])}")
    print(f"STOP LOSS   : {fmt_price(plan['stop'])}")
    print(f"TP1         : {fmt_price(plan['tp1'])}")
    print(f"TP2         : {fmt_price(plan['tp2'])}")
    print(f"TP3         : {fmt_price(plan['tp3'])}")
    print(f"QUANTITY    : {plan['quantity']:,.6f}")
    print(f"RISK/REWARD : 1:{plan['rr']:.2f}")
    print("-"*76)
    print(f"SL  P/L     : ${plan['sl_profit']:+,.2f} ({plan['sl_percent']:+.2f}%)")
    print(f"TP1 P/L     : ${plan['tp1_profit']:+,.2f} ({plan['tp1_percent']:+.2f}%)")
    print(f"TP2 P/L     : ${plan['tp2_profit']:+,.2f} ({plan['tp2_percent']:+.2f}%)")
    print(f"TP3 P/L     : ${plan['tp3_profit']:+,.2f} ({plan['tp3_percent']:+.2f}%)")
    print("-"*76)
    print(f"IMAGE       : {os.path.abspath(image_path)}")
    print("="*76)

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    print("\n" + "="*76)
    print("UNIVERSAL SPOT ANALYZER - FINAL VISUAL")
    print("15m + 30m + 4H + 1D + BTC + AUTOMATIC PNG")
    print("="*76)

    symbol = normalize_symbol(input("نام ارز: ").strip())

    while True:
        try:
            capital = float(input("سرمایه به دلار: ").strip())
            if capital <= 0:
                raise ValueError
            break
        except ValueError:
            print("سرمایه باید عدد مثبت باشد.")

    entry_text = input(
        "قیمت ورود دلخواه (خالی = قیمت فعلی): "
    ).strip()

    print("\n[1/3] BTC...")
    btc = analyze_btc()

    print(f"[2/3] {symbol}...")
    analyses = {}
    for tf in ["15m", "30m", "4h", "1d"]:
        print(f"   -> {tf}")
        analyses[tf] = analyze_tf(get_klines(symbol, tf, 300), tf)

    if entry_text:
        entry = float(entry_text)
    else:
        entry = analyses["15m"]["price"]

    if entry <= 0:
        raise ValueError("Entry must be > 0")

    score, decision = final_score(analyses, btc)

    main = analyses["4h"]
    plan = trade_plan(
        main["df"], entry,
        main["support"], main["resistance"],
        capital
    )

    print("\n[3/3] Generating image...")
    image_path = generate_chart(
        symbol, analyses, btc, plan,
        score, decision, capital
    )

    print_report(
        symbol, capital, analyses, btc,
        score, decision, plan, image_path
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        print(f"\nERROR: {e}")
        print("Check symbol, internet connection, and Binance availability.")
