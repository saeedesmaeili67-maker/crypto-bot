"""
ربات جامع تحلیل ارز دیجیتال + رصد نهنگ + اطلاع‌رسانی تلگرام
================================================================
این نسخه یه ربات کامل و همیشه-روشن هست که:

  1. با فرستادن دستور توی تلگرام، تحلیل تکنیکال کامل (RSI, MACD, حجم,
     حمایت/مقاومت, سیگنال خرید/فروش) رو همراه با نمودار برات می‌فرسته.
     اول دنبال نماد توی بایننس می‌گرده، اگه نبود خودکار میره سراغ بیت‌گت
     (برای ارزهای کوچیک‌تر که روی بایننس نیستن، مثل VELVET)
  2. یه موتور تصمیم‌گیری چند-عاملی داره: تکنیکال + ساختار بازار (HH/HL/LH/LL,
     BOS) + حجم/واگرایی + نهنگ تقریبی + ریسک، همه مستقل امتیاز میدن.
     بعد یه Counter-Signal Engine مستقل دنبال دلایل نخریدن می‌گرده.
     نتیجه نهایی: BUY / WAIT / NO TRADE با Entry/SL/TP1-3، دلایل موافق/مخالف،
     سناریوهای صعودی/خنثی/نزولی، و مقایسه با الگوهای مشابه گذشته همون ارز.
     (⚠️ همه این‌ها فقط بر پایه قیمت/حجم رایگانه، نه دیتای آنچین یا فاندامنتال پولی)
  3. معاملات درشت (نهنگ) روی بایننس رو لحظه‌ای رصد می‌کنه و به محض
     دیدن یه معامله بزرگ، فوری بهت پیام تلگرام میده
     (رصد نهنگ فقط روی بایننسه، بیت‌گت هنوز پشتیبانی نمیشه)
  4. هر مدت مشخص (پیش‌فرض هر ۶۰ دقیقه) خودش خودکار نمادهای تحت رصد رو
     چک می‌کنه و اگه سیگنال قوی خرید/فروش دید، بهت خبر میده
  5. با /scan کل لیست رصدت رو اسکن و رتبه‌بندی می‌کنه

⚠️ نکته مهم: این ربات باید ۲۴ ساعته روشن بمونه تا کارش رو درست انجام بده.
روی گوشی یا Replit رایگان مناسب نیست (چون با بستن صفحه متوقف میشه).
پیشنهاد: یه VPS ارزون (ماهی ۵-۱۰ دلار) یا Railway/Render با پلن Always-On.

—————————————————————————————————————————————————————————————
راه‌اندازی:
—————————————————————————————————————————————————————————————
۱) نصب پیش‌نیازها:
    pip install ccxt pandas numpy mplfinance requests websocket-client

۲) ساخت بات تلگرام:
    - توی تلگرام برو سراغ @BotFather
    - بزن /newbot و اسم دلخواه بده
    - یه توکن بهت میده شبیه این: 123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    - اون توکن رو بذار توی متغیر TELEGRAM_BOT_TOKEN پایین همین فایل

۳) اجرا:
    python pro_crypto_bot.py

۴) توی تلگرام برو سراغ باتی که ساختی و بزن /start
   (این کار باعث میشه ربات chat_id تو رو یاد بگیره و ازین به بعد بتونه پیام بده)

۵) دستورات قابل استفاده توی تلگرام:
    /start              فعال‌سازی و دیدن راهنما
    /analyze BTC/USDT   تحلیل کامل + نمودار + تصمیم BUY/WAIT/NO TRADE
    /scan               رتبه‌بندی نمادهای تحت رصد
    /watch SOLUSDT      اضافه کردن نماد به رصد نهنگ (بدون اسلش، حروف بزرگ)
    /unwatch SOLUSDT    حذف نماد از رصد نهنگ
    /watchlist          نمایش نمادهای تحت رصد
    /whales_on          روشن کردن هشدار نهنگ
    /whales_off         خاموش کردن هشدار نهنگ
    /help               راهنما
"""

import os
import sys
import json
import time
import threading
from datetime import datetime

import requests
import ccxt
import numpy as np
import pandas as pd
import mplfinance as mpf
import websocket  # از پکیج websocket-client


# ===========================================================================
# موتور تشخیص شکست خودکار (Breakout Engine)
# خط حمایت/مقاومت نزدیک‌ترین، تشخیص روند با ترندلاین ساده، تایید حجم،
# تشخیص Breakout/Breakdown، و محاسبه SL/TP بر پایه ATR و ریسک واقعی
# ===========================================================================

class AutoCandleLevels:
    """
    تشخیص خودکار حمایت/مقاومت + ترندلاین + Breakout + حد ضرر + ۳ تارگت
    برای معاملات Spot. ورودی: دیتافریم با ستون‌های open/high/low/close/volume
    """

    def __init__(self, swing_window=3, lookback=120, tolerance=0.003,
                 atr_period=14, volume_period=20):
        self.swing_window = swing_window
        self.lookback = lookback
        self.tolerance = tolerance
        self.atr_period = atr_period
        self.volume_period = volume_period

    def calculate_atr(self, df):
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(self.atr_period).mean()

    def find_swings(self, df):
        df = df.copy()
        w = self.swing_window
        df["swing_high"] = (df["high"] == df["high"].rolling(2 * w + 1, center=True).max())
        df["swing_low"] = (df["low"] == df["low"].rolling(2 * w + 1, center=True).min())
        return df

    def find_support_resistance(self, df):
        recent = df.tail(self.lookback)
        lows = recent.loc[recent["swing_low"], "low"].dropna()
        highs = recent.loc[recent["swing_high"], "high"].dropna()
        current_price = float(df["close"].iloc[-1])

        supports = [float(p) for p in lows if p <= current_price]
        support = max(supports) if supports else float(recent["low"].min())

        resistances = [float(p) for p in highs if p >= current_price]
        resistance = min(resistances) if resistances else float(recent["high"].max())

        return {
            "support": support,
            "support_zone": (support * (1 - self.tolerance), support * (1 + self.tolerance)),
            "resistance": resistance,
            "resistance_zone": (resistance * (1 - self.tolerance), resistance * (1 + self.tolerance)),
        }

    def find_trendlines(self, df):
        recent = df.tail(self.lookback)
        highs = recent[recent["swing_high"]][["high"]]
        lows = recent[recent["swing_low"]][["low"]]
        result = {"trend": "SIDEWAYS", "trendline_type": None}

        if len(highs) >= 2 and highs.iloc[-1]["high"] < highs.iloc[-2]["high"]:
            result["trend"], result["trendline_type"] = "BEARISH", "DESCENDING"
        if len(lows) >= 2 and lows.iloc[-1]["low"] > lows.iloc[-2]["low"]:
            result["trend"], result["trendline_type"] = "BULLISH", "ASCENDING"

        return result

    def volume_confirmation(self, df):
        if len(df) < self.volume_period:
            return False
        current_volume = df["volume"].iloc[-1]
        average_volume = df["volume"].rolling(self.volume_period).mean().iloc[-1]
        if average_volume <= 0:
            return False
        return current_volume > average_volume * 1.2

    def detect_breakout(self, df, resistance, support):
        if len(df) < 2:
            return "NONE"
        previous_close = df["close"].iloc[-2]
        current_close = df["close"].iloc[-1]
        volume_ok = self.volume_confirmation(df)

        if previous_close <= resistance < current_close:
            return "BULLISH_BREAKOUT_CONFIRMED" if volume_ok else "BULLISH_BREAKOUT_WEAK"
        if previous_close >= support > current_close:
            return "BEARISH_BREAKDOWN_CONFIRMED" if volume_ok else "BEARISH_BREAKDOWN_WEAK"
        return "NONE"

    def calculate_stop_loss(self, price, support, atr):
        stop_by_support = support * 0.985
        stop_by_atr = price - atr * 1.5
        return float(min(stop_by_support, stop_by_atr))

    def calculate_targets(self, entry, stop_loss, resistance):
        risk = entry - stop_loss
        if risk <= 0:
            risk = entry * 0.02
        target1 = entry + risk * 1.5
        target2 = entry + risk * 2.5
        target3 = entry + risk * 4.0
        if resistance > entry:
            target1 = min(target1, resistance)
        return {"target_1": float(target1), "target_2": float(target2), "target_3": float(target3)}

    def generate_signal(self, df, levels, trend, breakout):
        price = float(df["close"].iloc[-1])
        support = levels["support"]
        volume_ok = self.volume_confirmation(df)

        if breakout == "BULLISH_BREAKOUT_CONFIRMED":
            return "BUY"
        if trend["trend"] == "BULLISH" and price <= support * 1.02 and volume_ok:
            return "BUY"
        if breakout == "BEARISH_BREAKDOWN_CONFIRMED":
            return "SELL"
        return "WAIT"

    def analyze(self, df):
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"ستون {col} در داده وجود نداره")

        df = df.copy().tail(self.lookback).reset_index(drop=True)
        df["ATR"] = self.calculate_atr(df)
        df = self.find_swings(df)

        levels = self.find_support_resistance(df)
        trend = self.find_trendlines(df)
        breakout = self.detect_breakout(df, levels["resistance"], levels["support"])
        signal = self.generate_signal(df, levels, trend, breakout)

        current_price = float(df["close"].iloc[-1])
        atr = float(df["ATR"].iloc[-1])
        if np.isnan(atr) or atr <= 0:
            atr = current_price * 0.02

        if signal == "BUY":
            stop_loss = self.calculate_stop_loss(current_price, levels["support"], atr)
            targets = self.calculate_targets(current_price, stop_loss, levels["resistance"])
            risk = current_price - stop_loss
            reward = targets["target_3"] - current_price
            risk_reward = reward / risk if risk > 0 else 0
        else:
            stop_loss = None
            targets = {"target_1": None, "target_2": None, "target_3": None}
            risk_reward = None

        return {
            "price": current_price,
            "support": levels["support"], "support_zone": levels["support_zone"],
            "resistance": levels["resistance"], "resistance_zone": levels["resistance_zone"],
            "trend": trend["trend"], "trendline": trend["trendline_type"],
            "breakout": breakout, "volume_confirmed": self.volume_confirmation(df),
            "signal": signal, "stop_loss": stop_loss,
            "target_1": targets["target_1"], "target_2": targets["target_2"], "target_3": targets["target_3"],
            "risk_reward": risk_reward,
        }


def auto_candle_levels_text(df):
    """اجرای موتور Breakout و ساخت متن فارسی گزارش برای تلگرام"""
    try:
        analyzer = AutoCandleLevels(swing_window=3, lookback=120, tolerance=0.003)
        r = analyzer.analyze(df)
    except Exception as e:
        return f"(خطا در موتور Breakout: {e})"

    trend_fa = {"BULLISH": "صعودی 📈", "BEARISH": "نزولی 📉", "SIDEWAYS": "خنثی ↔️"}.get(r["trend"], r["trend"])
    breakout_fa = {
        "BULLISH_BREAKOUT_CONFIRMED": "🟢 شکست صعودی تایید شده (با حجم)",
        "BULLISH_BREAKOUT_WEAK": "🟡 شکست صعودی ولی بدون تایید حجم",
        "BEARISH_BREAKDOWN_CONFIRMED": "🔴 شکست نزولی تایید شده (با حجم)",
        "BEARISH_BREAKDOWN_WEAK": "🟡 شکست نزولی ولی بدون تایید حجم",
        "NONE": "بدون شکست در کندل اخیر",
    }.get(r["breakout"], r["breakout"])

    lines = [
        "⚡ <b>موتور خودکار خطوط و شکست (Breakout Engine)</b>",
        f"روند: {trend_fa}",
        f"حمایت نزدیک: {r['support']:.6f}",
        f"مقاومت نزدیک: {r['resistance']:.6f}",
        f"وضعیت: {breakout_fa}",
        f"تایید حجم: {'✅ بله' if r['volume_confirmed'] else '❌ خیر'}",
        f"سیگنال این موتور: <b>{r['signal']}</b>",
    ]

    if r["signal"] == "BUY":
        lines.append(f"SL: {r['stop_loss']:.6f}")
        lines.append(f"TP1: {r['target_1']:.6f}  |  TP2: {r['target_2']:.6f}  |  TP3: {r['target_3']:.6f}")
        if r["risk_reward"]:
            lines.append(f"R/R تا TP3: 1:{r['risk_reward']:.1f}")

    return "\n".join(lines)


# ===========================================================================
# تنظیمات — این بخش رو خودت پر کن
# ===========================================================================

TELEGRAM_BOT_TOKEN = "8891450951:AAEqBKslx3mzxzeZUt-rW7Tv8PHXYWX8zm8"

WATCHED_SYMBOLS_DEFAULT = ["BTCUSDT", "ETHUSDT"]   # نمادهای پیش‌فرض برای رصد نهنگ
WHALE_USD_THRESHOLD = 100_000                       # حداقل ارزش دلاری یک معامله برای شمردنش به‌عنوان "نهنگ"
AUTO_ANALYSIS_INTERVAL_MIN = 60                     # هر چند دقیقه یکبار خودکار سیگنال‌ها رو چک کنه

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")
OUTDIR = os.path.dirname(os.path.abspath(__file__))

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
ws_thread_ref = {"current": None}


# ===========================================================================
# ذخیره وضعیت (chat_id, لیست رصد, و غیره) روی دیسک تا با ری‌استارت از بین نره
# ===========================================================================

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"chat_id": None, "watch": list(WATCHED_SYMBOLS_DEFAULT), "whales_enabled": True}


def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


state = load_state()
state_lock = threading.Lock()


# ===========================================================================
# ارتباط با تلگرام
# ===========================================================================

def tg_send_message(text, chat_id=None):
    chat_id = chat_id or state.get("chat_id")
    if not chat_id:
        print("[تلگرام] هنوز chat_id نداریم — اول باید /start بزنی.")
        return
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", data={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML"
        }, timeout=15)
    except Exception as e:
        print(f"[تلگرام] خطا در ارسال پیام: {e}")


def tg_send_photo(path, caption="", chat_id=None):
    chat_id = chat_id or state.get("chat_id")
    if not chat_id or not os.path.exists(path):
        return
    try:
        with open(path, "rb") as f:
            requests.post(f"{TELEGRAM_API}/sendPhoto", data={
                "chat_id": chat_id, "caption": caption
            }, files={"photo": f}, timeout=30)
    except Exception as e:
        print(f"[تلگرام] خطا در ارسال عکس: {e}")


# ===========================================================================
# داده و اندیکاتورها (تحلیل تکنیکال)
# ===========================================================================

SUPPORTED_EXCHANGES = ["binance", "bitget"]


def resolve_exchange(symbol):
    """
    پیدا کردن اولین صرافی (از بین بایننس و بیت‌گت) که این نماد رو داره.
    برمی‌گردونه: (شیء صرافی, اسم صرافی) یا (None, None) اگه پیدا نشد
    """
    for ex_id in SUPPORTED_EXCHANGES:
        try:
            ex = getattr(ccxt, ex_id)()
            ex.load_markets()
            if symbol in ex.symbols:
                return ex, ex_id
        except Exception as e:
            print(f"[صرافی] خطا در بررسی {ex_id}: {e}")
            continue
    return None, None


def fetch_ohlcv(exchange, symbol, timeframe, limit=300):
    data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def resample_5d(df_daily):
    df = df_daily.set_index("timestamp")
    df5d = df.resample("5D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    return df5d.reset_index()


def compute_indicators(df):
    d = df.copy()
    d["sma20"] = d["close"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(50).mean()

    ema12 = d["close"].ewm(span=12, adjust=False).mean()
    ema26 = d["close"].ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()

    delta = d["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    d["rsi"] = (100 - (100 / (1 + rs))).fillna(50)

    d["bb_mid"] = d["close"].rolling(20).mean()
    bb_std = d["close"].rolling(20).std()
    d["bb_upper"] = d["bb_mid"] + 2 * bb_std
    d["bb_lower"] = d["bb_mid"] - 2 * bb_std

    d["vol_avg20"] = d["volume"].rolling(20).mean()
    return d


def find_pivots_chronological(df, window=3):
    """
    نسخه‌ای از تشخیص پیوت که ترتیب زمانی رو حفظ می‌کنه (برای تشخیص HH/HL/LH/LL لازمه،
    چون باید بدونیم کدوم پیوت جدیدتره، نه فقط کدوم بزرگ‌تره)
    """
    highs, lows = [], []
    for i in range(window, len(df) - window):
        seg_high = df["high"].iloc[i - window:i + window + 1]
        seg_low = df["low"].iloc[i - window:i + window + 1]
        if df["high"].iloc[i] == seg_high.max():
            highs.append(df["high"].iloc[i])
        if df["low"].iloc[i] == seg_low.min():
            lows.append(df["low"].iloc[i])
    return highs, lows  # به ترتیب زمانی (قدیم → جدید)


def find_pivots(df, window=5):
    highs, lows = [], []
    for i in range(window, len(df) - window):
        seg_high = df["high"].iloc[i - window:i + window + 1]
        seg_low = df["low"].iloc[i - window:i + window + 1]
        if df["high"].iloc[i] == seg_high.max():
            highs.append(df["high"].iloc[i])
        if df["low"].iloc[i] == seg_low.min():
            lows.append(df["low"].iloc[i])
    return sorted(set(highs), reverse=True), sorted(set(lows))


def score_row(row, prev):
    bull, bear = 0, 0
    rb, rs = [], []
    if row["rsi"] < 35:
        bull += 1; rb.append(f"RSI اشباع فروش ({row['rsi']:.0f})")
    if row["rsi"] > 65:
        bear += 1; rs.append(f"RSI اشباع خرید ({row['rsi']:.0f})")
    if row["macd"] > row["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
        bull += 1; rb.append("کراس صعودی MACD")
    if row["macd"] < row["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
        bear += 1; rs.append("کراس نزولی MACD")
    if row["close"] <= row["bb_lower"]:
        bull += 1; rb.append("قیمت روی باند پایین بولینگر")
    if row["close"] >= row["bb_upper"]:
        bear += 1; rs.append("قیمت روی باند بالای بولینگر")
    if row["sma20"] > row["sma50"] and prev["sma20"] <= prev["sma50"]:
        bull += 1; rb.append("کراس صعودی میانگین متحرک")
    if row["sma20"] < row["sma50"] and prev["sma20"] >= prev["sma50"]:
        bear += 1; rs.append("کراس نزولی میانگین متحرک")
    if pd.notna(row["vol_avg20"]) and row["volume"] > row["vol_avg20"] * 1.5:
        if row["close"] > prev["close"]:
            bull += 1; rb.append("افزایش حجم همراه رشد قیمت")
        elif row["close"] < prev["close"]:
            bear += 1; rs.append("افزایش حجم همراه افت قیمت")
    return bull, bear, rb, rs


def generate_signals(df, threshold=2):
    d = df.copy()
    d["buy_signal"] = False
    d["sell_signal"] = False
    for i in range(1, len(d)):
        bull, bear, _, _ = score_row(d.iloc[i], d.iloc[i - 1])
        if bull >= threshold and bull > bear:
            d.at[d.index[i], "buy_signal"] = True
        if bear >= threshold and bear > bull:
            d.at[d.index[i], "sell_signal"] = True
    return d


def plot_chart(df, symbol, timeframe_name):
    d = df.set_index("timestamp").rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })
    buy_marks = d["Low"].where(d["buy_signal"]) * 0.99
    sell_marks = d["High"].where(d["sell_signal"]) * 1.01
    apds = []
    if buy_marks.notna().any():
        apds.append(mpf.make_addplot(buy_marks, type="scatter", markersize=90, marker="^", color="green"))
    if sell_marks.notna().any():
        apds.append(mpf.make_addplot(sell_marks, type="scatter", markersize=90, marker="v", color="red"))

    # خطوط افقی حمایت/مقاومت روی خود نمودار
    highs, lows = find_pivots(df.tail(100), window=3)
    res_lines = highs[:3]   # تا ۳ تا مقاومت مهم
    sup_lines = lows[:3]    # تا ۳ تا حمایت مهم
    all_lines = res_lines + sup_lines
    line_colors = ["red"] * len(res_lines) + ["green"] * len(sup_lines)

    hlines_dict = None
    if all_lines:
        hlines_dict = dict(
            hlines=all_lines,
            colors=line_colors,
            linestyle="--",
            linewidths=1,
        )

    safe = symbol.replace("/", "_")
    filename = os.path.join(OUTDIR, f"{safe}_{timeframe_name}.png")
    mpf.plot(
        d[["Open", "High", "Low", "Close", "Volume"]], type="candle", volume=True,
        addplot=apds if apds else None, style="yahoo", hlines=hlines_dict,
        title=f"{symbol} - {timeframe_name}", savefig=dict(fname=filename, dpi=150, bbox_inches="tight"),
    )
    return filename


def volume_report_text(df_1d):
    lines = ["📊 <b>تحلیل حجم معاملات</b>"]
    if len(df_1d) < 2:
        lines.append("داده کافی نیست.")
        return "\n".join(lines)
    today = df_1d["volume"].iloc[-1]
    week_avg = df_1d["volume"].tail(7).mean()
    month_avg = df_1d["volume"].tail(30).mean()
    lines.append(f"حجم امروز: {today:,.2f}")
    lines.append(f"میانگین هفته: {week_avg:,.2f}")
    lines.append(f"میانگین ماه: {month_avg:,.2f}")

    def cmp_txt(val, ref):
        diff = (val - ref) / ref * 100 if ref else 0
        s = "بالاتر" if diff > 5 else ("پایین‌تر" if diff < -5 else "مشابه")
        return f"{s} ({diff:+.1f}%)"

    lines.append(f"نسبت به میانگین هفته: {cmp_txt(today, week_avg)}")
    lines.append(f"نسبت به میانگین ماه: {cmp_txt(today, month_avg)}")
    if today > month_avg * 1.5:
        lines.append("⚠ حجم غیرعادی بالا — احتمال شروع یک حرکت قوی")
    elif today < month_avg * 0.5:
        lines.append("حجم پایین‌تر از حد معمول — بازار کم‌نوسان")
    return "\n".join(lines)


def btc_correlation_text(df_coin, df_btc):
    n = min(len(df_coin), len(df_btc))
    if n < 15:
        return ""
    coin_ret = df_coin["close"].tail(n).pct_change().dropna()
    btc_ret = df_btc["close"].tail(n).pct_change().dropna()
    m = min(len(coin_ret), len(btc_ret))
    if m < 10:
        return ""
    coin_ret = coin_ret.tail(m).reset_index(drop=True)
    btc_ret = btc_ret.tail(m).reset_index(drop=True)
    corr = coin_ret.corr(btc_ret)
    if pd.isna(corr):
        return ""
    btc_var = btc_ret.var()
    beta = (coin_ret.cov(btc_ret) / btc_var) if btc_var else float("nan")
    btc_change = (df_btc["close"].iloc[-1] - df_btc["close"].iloc[-2]) / df_btc["close"].iloc[-2] * 100
    desc = ("خیلی بالا" if corr >= 0.75 else "نسبتا بالا" if corr >= 0.5
            else "متوسط" if corr >= 0.2 else "پایین")
    lines = [f"همبستگی با بیت کوین: {corr:.2f} ({desc})"]
    if not pd.isna(beta):
        lines.append(f"بتا: {beta:.2f} — بیت کوین اخیرا {btc_change:+.2f}% → اثر تخمینی: {beta * btc_change:+.2f}%")
    return "\n".join(lines)


# ===========================================================================
# موتور تصمیم‌گیری چند-عاملی (Multi-Agent Decision Engine)
# هر Agent مستقل امتیاز میده، بعد MASTER این‌ها رو ترکیب می‌کنه.
# همه چیز فقط با داده رایگان OHLCV محاسبه میشه — بدون نیاز به API پولی.
# ===========================================================================

def agent_technical(d):
    """امتیاز بر اساس RSI, MACD, EMA, Bollinger روی آخرین کندل"""
    last, prev = d.iloc[-1], d.iloc[-2]
    bull, bear, rb, rs = score_row(last, prev)
    score = bull - bear
    reasons = [f"✅ {r}" for r in rb] + [f"⚠️ {r}" for r in rs]
    return score, reasons


def agent_structure(d, window=3):
    """
    تشخیص ساختار بازار: HH/HL (صعودی) یا LH/LL (نزولی) بر اساس آخرین دو پیوت
    به ترتیب زمانی، و تشخیص ساده BOS (شکست ساختار) وقتی قیمت از آخرین
    سقف/کف پیوت رد میشه
    """
    highs, lows = find_pivots_chronological(d.tail(120), window=window)
    last_close = d["close"].iloc[-1]
    reasons = []
    score = 0

    if len(highs) >= 2 and len(lows) >= 2:
        recent_high, prev_high = highs[-1], highs[-2]
        recent_low, prev_low = lows[-1], lows[-2]

        if recent_high > prev_high:
            score += 1
            reasons.append("✅ ساختار: سقف بالاتر (HH) — روند صعودی")
        elif recent_high < prev_high:
            score -= 1
            reasons.append("⚠️ ساختار: سقف پایین‌تر (LH) — ضعف روند صعودی")

        if recent_low > prev_low:
            score += 1
            reasons.append("✅ ساختار: کف بالاتر (HL) — تایید روند صعودی")
        elif recent_low < prev_low:
            score -= 1
            reasons.append("⚠️ ساختار: کف پایین‌تر (LL) — روند نزولی")

        if last_close > recent_high:
            score += 1
            reasons.append("✅ BOS صعودی: قیمت از آخرین سقف مهم عبور کرد")
        if last_close < recent_low:
            score -= 1
            reasons.append("⚠️ BOS نزولی: قیمت زیر آخرین کف مهم شکسته")
    else:
        reasons.append("داده کافی برای تشخیص ساختار دقیق نیست")

    return score, reasons


def agent_volume(d):
    """حجم نسبی و واگرایی حجم-قیمت"""
    recent = d.tail(10)
    last = d.iloc[-1]
    reasons = []
    score = 0

    vol_avg = d["vol_avg20"].iloc[-1]
    if pd.notna(vol_avg) and vol_avg > 0:
        rel_vol = last["volume"] / vol_avg
        if rel_vol > 1.5:
            score += 1
            reasons.append(f"✅ حجم بالاتر از میانگین ({rel_vol:.1f}x)")
        elif rel_vol < 0.5:
            score -= 1
            reasons.append(f"⚠️ حجم پایین‌تر از میانگین ({rel_vol:.1f}x) — ضعف تایید حرکت")

    # واگرایی ساده: قیمت سقف جدید ولی حجم کمتر از سقف قبلی
    if len(recent) >= 6:
        first_half, second_half = recent.iloc[:5], recent.iloc[5:]
        if second_half["close"].max() > first_half["close"].max() and \
           second_half["volume"].mean() < first_half["volume"].mean():
            score -= 1
            reasons.append("⚠️ واگرایی منفی: سقف قیمتی جدید با حجم ضعیف‌تر")

    return score, reasons


def agent_whale_proxy(d):
    """
    نسخه رایگان Whale Agent: چون دسترسی به دیتابیس کیف‌پول‌ها نداریم،
    از اسپایک‌های حجمی بزرگ همراه با جهت قیمت به‌عنوان جایگزین تقریبی استفاده می‌کنیم.
    این "تقریبی" است، نه رصد واقعی کیف‌پول.
    """
    recent = d.tail(20)
    vol_avg = recent["volume"].mean()
    reasons = []
    score = 0
    spikes = recent[recent["volume"] > vol_avg * 2.5]
    if len(spikes) > 0:
        last_spike = spikes.iloc[-1]
        if last_spike["close"] > last_spike["open"]:
            score += 1
            reasons.append("✅ (تقریبی) اسپایک حجمی بزرگ همراه با رشد قیمت — احتمال ورود پول درشت")
        else:
            score -= 1
            reasons.append("⚠️ (تقریبی) اسپایک حجمی بزرگ همراه با افت قیمت — احتمال خروج پول درشت")
    else:
        reasons.append("اسپایک حجمی قابل توجهی در ۲۰ کندل اخیر دیده نشد")
    return score, reasons


def agent_risk(d, entry, sl, tp1):
    """فاصله تا مقاومت، نوسان (ATR ساده)، و R:R"""
    reasons = []
    score = 0

    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    last_close = d["close"].iloc[-1]

    if pd.notna(atr) and last_close > 0:
        volatility_pct = atr / last_close * 100
        if volatility_pct > 8:
            score -= 1
            reasons.append(f"⚠️ نوسان بالا (ATR≈{volatility_pct:.1f}% قیمت) — ریسک بیشتر")

    if entry and sl and tp1 and entry != sl:
        risk = abs(entry - sl)
        reward = abs(tp1 - entry)
        rr = reward / risk if risk else 0
        if rr >= 1.5:
            score += 1
            reasons.append(f"✅ نسبت ریسک به ریوارد مناسب (1:{rr:.1f})")
        else:
            score -= 1
            reasons.append(f"⚠️ نسبت ریسک به ریوارد ضعیف (1:{rr:.1f})")
        return score, reasons, rr

    return score, reasons, None


def counter_signal_check(d, rr, df_btc=None):
    """
    موتور مخالف: مستقل از بقیه Agentها، فقط دنبال دلایل نخریدن می‌گرده.
    """
    warnings = []
    last = d.iloc[-1]
    recent = d.tail(60)
    resistance = recent["high"].max()
    last_close = last["close"]

    if resistance > 0 and (resistance - last_close) / last_close * 100 < 2:
        warnings.append("مقاومت خیلی نزدیکه (کمتر از ۲٪ فاصله)")

    if last["rsi"] > 70:
        warnings.append("RSI در ناحیه اشباع خرید شدید (بالای ۷۰) — ریسک برگشت")

    if rr is not None and rr < 1.2:
        warnings.append("نسبت ریسک به ریوارد ضعیفه")

    if df_btc is not None and len(df_btc) > 2:
        btc_change = (df_btc["close"].iloc[-1] - df_btc["close"].iloc[-2]) / df_btc["close"].iloc[-2] * 100
        if btc_change < -2:
            warnings.append(f"بیت کوین اخیرا افت محسوسی داشته ({btc_change:+.1f}%) — ریسک کل بازار")

    vol3 = d["volume"].tail(3)
    close3 = d["close"].tail(3)
    if len(vol3) == 3 and vol3.is_monotonic_decreasing and close3.iloc[-1] > close3.iloc[0]:
        warnings.append("قیمت داره بالا میره ولی حجم مرتب داره کم میشه — تایید ضعیف")

    return warnings


def scenario_engine(d):
    """سه سناریو: صعودی، خنثی، نزولی — با شرط قیمتی مشخص (بر اساس نزدیک‌ترین سطوح)"""
    highs, lows = find_pivots(d.tail(120), window=3)
    last_close = d["close"].iloc[-1]

    resistances = sorted([h for h in highs if h > last_close])
    supports = sorted([l for l in lows if l < last_close], reverse=True)

    r1 = resistances[0] if resistances else last_close * 1.05
    r2 = resistances[1] if len(resistances) > 1 else r1 * 1.05
    s1 = supports[0] if supports else last_close * 0.95
    s2 = supports[1] if len(supports) > 1 else s1 * 0.95

    return (
        f"🟢 سناریوی صعودی: اگه قیمت از {r1:.6f} با حجم خوب رد بشه، حرکت بعدی سمت "
        f"{r2:.6f} محتمله\n"
        f"⚪ سناریوی خنثی: تا وقتی قیمت بین {s1:.6f} و {r1:.6f} بمونه، روند مشخص نیست\n"
        f"🔴 سناریوی نزولی: اگه قیمت زیر {s1:.6f} بشکنه، افت بیشتر سمت "
        f"{s2:.6f} محتمله"
    )


def entry_sl_tp_engine(d):
    """محاسبه Entry / SL / TP1-3 بر اساس نزدیک‌ترین سطوح حمایت/مقاومت واقعی به قیمت فعلی"""
    highs, lows = find_pivots(d.tail(120), window=3)
    last_close = d["close"].iloc[-1]

    # مقاومت‌های بالای قیمت فعلی، نزدیک‌ترین اول
    resistances = sorted([h for h in highs if h > last_close])
    # حمایت‌های زیر قیمت فعلی، نزدیک‌ترین اول (بزرگ‌ترین عدد کوچیک‌تر از قیمت)
    supports = sorted([l for l in lows if l < last_close], reverse=True)

    entry = last_close
    sl = supports[0] * 0.99 if supports else last_close * 0.95
    tp1 = resistances[0] if resistances else last_close * 1.05
    tp2 = resistances[1] if len(resistances) > 1 else tp1 * 1.05
    tp3 = entry + 2 * (tp1 - entry) if tp1 > entry else tp1 * 1.1

    return entry, sl, tp1, tp2, tp3


def historical_similarity(d, window=10, top_k=15, forward=5):
    """
    الگوی N کندل اخیر رو با الگوهای مشابه در گذشته همون ارز مقایسه می‌کنه
    و می‌بینه بعد از الگوهای مشابه معمولاً چند درصد صعودی/نزولی بوده.
    (این یه آمار واقعیه بر پایه دیتای واقعی، نه حدس)
    """
    if len(d) < window + forward + 50:
        return None

    returns = d["close"].pct_change()
    rsi = d["rsi"]
    vol_ratio = d["volume"] / d["vol_avg20"].replace(0, np.nan)

    current_feat = np.array([
        returns.tail(window).mean(),
        rsi.tail(window).mean(),
        vol_ratio.tail(window).mean() if pd.notna(vol_ratio.tail(window).mean()) else 1.0,
    ])

    candidates = []
    for i in range(50, len(d) - window - forward):
        seg_ret = returns.iloc[i:i + window].mean()
        seg_rsi = rsi.iloc[i:i + window].mean()
        seg_vol = vol_ratio.iloc[i:i + window].mean()
        if pd.isna(seg_ret) or pd.isna(seg_rsi) or pd.isna(seg_vol):
            continue
        feat = np.array([seg_ret, seg_rsi, seg_vol])
        dist = np.linalg.norm(feat - current_feat)
        fwd_ret = (d["close"].iloc[i + window + forward - 1] - d["close"].iloc[i + window]) / d["close"].iloc[i + window]
        candidates.append((dist, fwd_ret))

    if len(candidates) < top_k:
        return None

    candidates.sort(key=lambda x: x[0])
    top = candidates[:top_k]
    fwd_returns = [c[1] for c in top]
    win_rate = sum(1 for r in fwd_returns if r > 0) / len(fwd_returns) * 100
    avg_ret = sum(fwd_returns) / len(fwd_returns) * 100

    return (
        f"از بین {top_k} الگوی مشابه گذشته این ارز، بعد از {forward} کندل، "
        f"{win_rate:.0f}٪ صعودی بودن (میانگین تغییر: {avg_ret:+.1f}٪)"
    )


def master_decision_report(symbol, d, df_btc, ex_name):
    """گزارش نهایی: ترکیب همه Agentها، Counter-Signal، سناریو، Entry/SL/TP"""
    t_score, t_reasons = agent_technical(d)
    s_score, s_reasons = agent_structure(d)
    v_score, v_reasons = agent_volume(d)
    w_score, w_reasons = agent_whale_proxy(d)

    entry, sl, tp1, tp2, tp3 = entry_sl_tp_engine(d)
    r_score, r_reasons, rr = agent_risk(d, entry, sl, tp1)

    total = t_score + s_score + v_score + w_score + r_score
    warnings = counter_signal_check(d, rr, df_btc)

    scores = [t_score, s_score, v_score, w_score]
    conflict = (max(scores) >= 1 and min(scores) <= -1)

    if len(warnings) >= 2:
        decision, emoji = "NO TRADE", "🔴"
    elif total >= 4 and not conflict and len(warnings) == 0:
        decision, emoji = "BUY", "🟢"
    elif total <= -3:
        decision, emoji = "NO TRADE", "🔴"
    else:
        decision, emoji = "WAIT", "🟡"

    confidence = "HIGH" if (abs(total) >= 5 and not conflict) else ("MEDIUM" if abs(total) >= 2 else "LOW")

    hist = historical_similarity(d)

    lines = [
        f"🧠 <b>گزارش تصمیم‌گیری کامل — {symbol} ({ex_name.upper()})</b>",
        "",
        f"امتیاز تکنیکال: {t_score:+d}",
        f"امتیاز ساختار بازار: {s_score:+d}",
        f"امتیاز حجم: {v_score:+d}",
        f"امتیاز نهنگ (تقریبی): {w_score:+d}",
        f"امتیاز ریسک: {r_score:+d}",
        f"<b>امتیاز کل: {total:+d}</b>",
        f"اطمینان: {confidence}",
        "",
        f"{emoji} <b>تصمیم نهایی: {decision}</b>",
    ]

    if conflict:
        lines.append("⚠️ ANALYSIS CONFLICT — موتورهای تحلیل با هم اختلاف دارن")

    lines.append("\n<b>دلایل موافق:</b>")
    for r in t_reasons + s_reasons + v_reasons + w_reasons + r_reasons:
        if r.startswith("✅"):
            lines.append(r)

    lines.append("\n<b>دلایل مخالف / هشدارها:</b>")
    any_warn = False
    for r in t_reasons + s_reasons + v_reasons + w_reasons + r_reasons:
        if r.startswith("⚠️"):
            lines.append(r)
            any_warn = True
    for w in warnings:
        lines.append(f"🚩 {w}")
        any_warn = True
    if not any_warn:
        lines.append("موردی یافت نشد")

    if decision == "BUY":
        lines.append(f"\n<b>Entry:</b> {entry:.6f}")
        lines.append(f"<b>SL:</b> {sl:.6f}")
        lines.append(f"<b>TP1:</b> {tp1:.6f}")
        lines.append(f"<b>TP2:</b> {tp2:.6f}")
        lines.append(f"<b>TP3:</b> {tp3:.6f}")
        if rr:
            lines.append(f"<b>R/R:</b> 1:{rr:.1f}")

    lines.append("\n<b>سناریوها:</b>")
    lines.append(scenario_engine(d))

    if hist:
        lines.append(f"\n<b>شباهت تاریخی:</b> {hist}")

    lines.append(
        "\n[این گزارش صرفاً بر پایه داده قیمت/حجم رایگانه، نه دیتای آنچین/فاندامنتال "
        "پولی. تصمیم نهایی معامله با خودته و مدیریت ریسک رو فراموش نکن.]"
    )

    return "\n".join(lines)


def analyze_one_timeframe(df, name, symbol, df_btc=None, is_btc=False, make_chart=True):
    """برمی‌گردونه: (متن گزارش, مسیر فایل نمودار یا None, وضعیت کلی 'buy'/'sell'/'neutral')"""
    if len(df) < 55:
        return f"=== {name} ===\nداده کافی نیست.", None, "neutral"

    d = compute_indicators(df)
    d = generate_signals(d)
    last, prev = d.iloc[-1], d.iloc[-2]
    change_pct = (last["close"] - prev["close"]) / prev["close"] * 100
    recent = d.tail(60)
    resistance = recent["high"].max()
    support = recent["low"].min()
    ph, pl = find_pivots(d.tail(100), window=3)

    bull, bear, rb, rs = score_row(last, prev)
    if bull >= 2 and bull > bear:
        overall, reasons, status = "🟢 سیگنال خرید", rb, "buy"
    elif bear >= 2 and bear > bull:
        overall, reasons, status = "🔴 سیگنال فروش", rs, "sell"
    else:
        overall, reasons, status = "⚪ خنثی", ["اندیکاتورها هم‌جهت نیستن"], "neutral"

    lines = [f"=== تایم‌فریم {name} ===",
             f"قیمت: {last['close']:.6f} ({change_pct:+.2f}%)",
             f"RSI: {last['rsi']:.1f} | MACD: {last['macd']:.6f}/{last['macd_signal']:.6f}",
             f"SMA20/50: {last['sma20']:.6f} / {last['sma50']:.6f}",
             f"مقاومت نزدیک: {resistance:.6f} | حمایت نزدیک: {support:.6f}"]
    if ph[:3]:
        lines.append("مقاومت‌های مهم: " + ", ".join(f"{v:.6f}" for v in ph[:3]))
    if pl[:3]:
        lines.append("حمایت‌های مهم: " + ", ".join(f"{v:.6f}" for v in pl[:3]))
    lines.append(f"\nوضعیت: {overall}")
    lines += [f"  - {r}" for r in reasons]

    if df_btc is not None and not is_btc:
        bt = btc_correlation_text(df, df_btc)
        if bt:
            lines.append("\nتاثیر بیت کوین:")
            lines.append(bt)

    chart_path = None
    if make_chart:
        try:
            chart_path = plot_chart(d, symbol, name)
        except Exception as e:
            lines.append(f"(خطا در رسم نمودار: {e})")

    return "\n".join(lines), chart_path, status


def run_full_analysis_and_send(symbol, chat_id):
    """اجرای تحلیل کامل روی هر سه تایم‌فریم و ارسال به تلگرام"""
    exchange, ex_name = resolve_exchange(symbol)
    if exchange is None:
        tg_send_message(
            f"نماد {symbol} نه توی بایننس پیدا شد نه توی بیت‌گت. "
            f"املا رو چک کن (مثلاً VELVET/USDT) یا مطمئن شو این ارز روی یکی از این دو صرافی لیست شده.",
            chat_id=chat_id,
        )
        return

    is_btc = symbol.upper().startswith("BTC/")

    df_4h = fetch_ohlcv(exchange, symbol, "4h")
    df_1d = fetch_ohlcv(exchange, symbol, "1d")
    df_5d = resample_5d(df_1d)

    # همیشه بیت کوین رو از بایننس می‌گیریم تا همبستگی یکدست باشه
    df_btc_4h = df_btc_1d = df_btc_5d = None
    if not is_btc:
        try:
            btc_exchange = ccxt.binance()
            df_btc_4h = fetch_ohlcv(btc_exchange, "BTC/USDT", "4h")
            df_btc_1d = fetch_ohlcv(btc_exchange, "BTC/USDT", "1d")
            df_btc_5d = resample_5d(df_btc_1d)
        except Exception:
            pass

    tg_send_message(f"منبع داده: {ex_name.upper()}", chat_id=chat_id)
    tg_send_message(volume_report_text(df_1d), chat_id=chat_id)

    for df, name, dbtc in [(df_4h, "4ساعته", df_btc_4h), (df_1d, "روزانه", df_btc_1d), (df_5d, "5روزه", df_btc_5d)]:
        text, chart_path, _ = analyze_one_timeframe(df, name, symbol, df_btc=dbtc, is_btc=is_btc)
        tg_send_message(text, chat_id=chat_id)
        if chart_path:
            tg_send_photo(chart_path, caption=f"{symbol} - {name}", chat_id=chat_id)

    # گزارش نهایی موتور تصمیم‌گیری چند-عاملی (بر پایه تایم‌فریم روزانه)
    try:
        d_1d = compute_indicators(df_1d)
        report = master_decision_report(symbol, d_1d, df_btc_1d, ex_name)
        tg_send_message(report, chat_id=chat_id)
    except Exception as e:
        tg_send_message(f"(خطا در موتور تصمیم‌گیری: {e})", chat_id=chat_id)

    # موتور مستقل Breakout (خط حمایت/مقاومت + ترندلاین + SL/TP بر پایه ATR)
    try:
        breakout_report = auto_candle_levels_text(df_1d)
        tg_send_message(breakout_report, chat_id=chat_id)
    except Exception as e:
        tg_send_message(f"(خطا در موتور Breakout: {e})", chat_id=chat_id)

    tg_send_message("[یادآوری: این تحلیل تضمینی نیست، مدیریت ریسک رو فراموش نکن.]", chat_id=chat_id)


# ===========================================================================
# رصد نهنگ — معاملات درشت روی بایننس، لحظه‌ای از طریق WebSocket
# ===========================================================================

def build_stream_url(symbols):
    streams = "/".join(f"{s.lower()}@aggTrade" for s in symbols)
    return f"wss://stream.binance.com:9443/stream?streams={streams}"


def on_ws_message(ws, message):
    try:
        payload = json.loads(message)
        data = payload.get("data", {})
        price = float(data.get("p", 0))
        qty = float(data.get("q", 0))
        is_seller_taker = data.get("m", False)  # True یعنی فروشنده taker بوده (فشار فروش)
        symbol = data.get("s", "")
        value_usd = price * qty
        if value_usd >= WHALE_USD_THRESHOLD and state.get("whales_enabled", True):
            emoji = "🔴" if is_seller_taker else "🟢"
            direction = "فروش بزرگ" if is_seller_taker else "خرید بزرگ"
            text = (f"{emoji} <b>معامله نهنگ — {symbol}</b>\n"
                    f"نوع: {direction}\n"
                    f"قیمت: {price:,.4f}\n"
                    f"مقدار: {qty:,.4f}\n"
                    f"ارزش: ${value_usd:,.0f}\n"
                    f"زمان: {datetime.now().strftime('%H:%M:%S')}")
            print(text.replace("<b>", "").replace("</b>", ""))
            tg_send_message(text)
    except Exception as e:
        print(f"[نهنگ] خطا در پردازش پیام: {e}")


def on_ws_error(ws, error):
    print(f"[نهنگ] خطای اتصال: {error}")


def on_ws_close(ws, code, msg):
    print("[نهنگ] اتصال قطع شد.")


def on_ws_open(ws):
    print(f"[نهنگ] رصد فعال برای: {state.get('watch')}")


def whale_watcher_loop():
    while True:
        symbols = state.get("watch") or WATCHED_SYMBOLS_DEFAULT
        url = build_stream_url(symbols)
        ws = websocket.WebSocketApp(
            url, on_message=on_ws_message, on_error=on_ws_error,
            on_close=on_ws_close, on_open=on_ws_open,
        )
        ws_thread_ref["current"] = ws
        try:
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"[نهنگ] خطای غیرمنتظره: {e}")
        time.sleep(5)  # قبل از تلاش مجدد کمی صبر کن


# ===========================================================================
# بررسی خودکار دوره‌ای نمادهای تحت رصد و اطلاع‌رسانی سیگنال قوی
# ===========================================================================

last_alert_status = {}  # symbol -> آخرین وضعیتی که اطلاع دادیم


def auto_analysis_loop():
    while True:
        time.sleep(AUTO_ANALYSIS_INTERVAL_MIN * 60)
        symbols = state.get("watch") or []
        for sym in symbols:
            pretty = sym[:-4] + "/" + sym[-4:] if sym.endswith("USDT") else sym
            try:
                exchange, ex_name = resolve_exchange(pretty)
                if exchange is None:
                    continue
                df_1d = fetch_ohlcv(exchange, pretty, "1d")
                text, _, status = analyze_one_timeframe(df_1d, "روزانه", pretty, make_chart=False)
                if status in ("buy", "sell") and last_alert_status.get(sym) != status:
                    tg_send_message(f"⏰ <b>هشدار خودکار — {pretty} ({ex_name.upper()})</b>\n\n{text}")
                last_alert_status[sym] = status
            except Exception as e:
                print(f"[خودکار] خطا برای {sym}: {e}")


# ===========================================================================
# مدیریت دستورات تلگرام
# ===========================================================================

HELP_TEXT = (
    "دستورات:\n"
    "/analyze BTC/USDT — تحلیل کامل + نمودار + گزارش تصمیم‌گیری BUY/WAIT/NO TRADE\n"
    "/scan — رتبه‌بندی همه نمادهای تحت رصد بر اساس امتیاز\n"
    "/watch SOLUSDT — اضافه کردن به رصد نهنگ\n"
    "/unwatch SOLUSDT — حذف از رصد نهنگ\n"
    "/watchlist — نمایش لیست رصد\n"
    "/whales_on یا /whales_off — روشن/خاموش کردن هشدار نهنگ\n"
    "/help — همین راهنما"
)


def handle_command(text, chat_id):
    parts = text.strip().split()
    if not parts:
        return
    cmd = parts[0].lower()

    if cmd == "/start":
        with state_lock:
            state["chat_id"] = chat_id
            save_state(state)
        tg_send_message("سلام! ربات فعال شد. ✅\n\n" + HELP_TEXT, chat_id=chat_id)

    elif cmd == "/scan":
        symbols = state.get("watch") or []
        if not symbols:
            tg_send_message("لیست رصدت خالیه. اول با /watch یه چندتا نماد اضافه کن.", chat_id=chat_id)
            return
        tg_send_message(f"در حال اسکن {len(symbols)} نماد ... ⏳", chat_id=chat_id)
        results = []
        for sym in symbols:
            pretty = sym[:-4] + "/" + sym[-4:] if sym.endswith("USDT") else sym
            try:
                exchange, ex_name = resolve_exchange(pretty)
                if exchange is None:
                    continue
                df_1d = fetch_ohlcv(exchange, pretty, "1d")
                if len(df_1d) < 55:
                    continue
                d = compute_indicators(df_1d)
                t, _ = agent_technical(d)
                s, _ = agent_structure(d)
                v, _ = agent_volume(d)
                w, _ = agent_whale_proxy(d)
                total = t + s + v + w
                results.append((pretty, total, ex_name))
            except Exception as e:
                print(f"[اسکن] خطا برای {sym}: {e}")
        if not results:
            tg_send_message("چیزی برای گزارش پیدا نشد.", chat_id=chat_id)
            return
        results.sort(key=lambda x: x[1], reverse=True)
        lines = ["🏆 <b>رتبه‌بندی نمادهای تحت رصد</b>\n"]
        for i, (sym, score, ex_name) in enumerate(results, 1):
            lines.append(f"{i}. {sym} ({ex_name.upper()}) — امتیاز: {score:+d}")
        tg_send_message("\n".join(lines), chat_id=chat_id)

    elif cmd == "/help":
        tg_send_message(HELP_TEXT, chat_id=chat_id)

    elif cmd == "/analyze":
        if len(parts) < 2:
            tg_send_message("مثال: /analyze BTC/USDT", chat_id=chat_id)
            return
        symbol = parts[1].upper()
        if "/" not in symbol:
            symbol += "/USDT"
        tg_send_message(f"در حال تحلیل {symbol} ... ⏳", chat_id=chat_id)
        try:
            run_full_analysis_and_send(symbol, chat_id)
        except Exception as e:
            tg_send_message(f"خطا: {e}", chat_id=chat_id)

    elif cmd == "/watch":
        if len(parts) < 2:
            tg_send_message("مثال: /watch SOLUSDT", chat_id=chat_id)
            return
        sym = parts[1].upper().replace("/", "")
        with state_lock:
            if sym not in state["watch"]:
                state["watch"].append(sym)
                save_state(state)
        tg_send_message(f"{sym} به رصد نهنگ اضافه شد.", chat_id=chat_id)
        if ws_thread_ref["current"]:
            ws_thread_ref["current"].close()

    elif cmd == "/unwatch":
        if len(parts) < 2:
            tg_send_message("مثال: /unwatch SOLUSDT", chat_id=chat_id)
            return
        sym = parts[1].upper().replace("/", "")
        with state_lock:
            if sym in state["watch"]:
                state["watch"].remove(sym)
                save_state(state)
        tg_send_message(f"{sym} از رصد نهنگ حذف شد.", chat_id=chat_id)
        if ws_thread_ref["current"]:
            ws_thread_ref["current"].close()

    elif cmd == "/watchlist":
        tg_send_message("نمادهای تحت رصد:\n" + "\n".join(state.get("watch", [])), chat_id=chat_id)

    elif cmd == "/whales_on":
        with state_lock:
            state["whales_enabled"] = True
            save_state(state)
        tg_send_message("هشدار نهنگ فعال شد. ✅", chat_id=chat_id)

    elif cmd == "/whales_off":
        with state_lock:
            state["whales_enabled"] = False
            save_state(state)
        tg_send_message("هشدار نهنگ غیرفعال شد.", chat_id=chat_id)

    else:
        tg_send_message("دستور شناخته نشد. /help رو بزن.", chat_id=chat_id)


def telegram_polling_loop():
    last_update_id = 0
    print("[تلگرام] در حال گوش دادن به پیام‌ها ...")
    while True:
        try:
            resp = requests.get(f"{TELEGRAM_API}/getUpdates", params={
                "offset": last_update_id + 1, "timeout": 30
            }, timeout=35)
            data = resp.json()
            for update in data.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")
                if text and chat_id:
                    handle_command(text, chat_id)
        except Exception as e:
            print(f"[تلگرام] خطا: {e}")
            time.sleep(5)


# ===========================================================================
# اجرای برنامه
# ===========================================================================

def main():
    if "اینجا توکن" in TELEGRAM_BOT_TOKEN:
        print("⚠ اول باید توکن بات تلگرامت رو توی متغیر TELEGRAM_BOT_TOKEN بذاری.")
        sys.exit(1)

    print("ربات در حال اجراست ...")
    print(f"نمادهای تحت رصد نهنگ: {state.get('watch')}")
    print("توی تلگرام /start رو بزن تا فعال بشه.")

    threading.Thread(target=telegram_polling_loop, daemon=True).start()
    threading.Thread(target=whale_watcher_loop, daemon=True).start()
    threading.Thread(target=auto_analysis_loop, daemon=True).start()

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
