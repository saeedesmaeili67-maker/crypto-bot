# -*- coding: utf-8 -*-
"""
تشخیص فعالیت نهنگ‌ها (Whale Activity)
دو منبع:
  1) معاملات بزرگ اخیر مستقیماً از صرافی (بایننس) - همیشه فعال، رایگان
  2) تراکنش‌های بزرگ بلاکچینی از Whale Alert API - فقط اگر API Key تنظیم شده باشد
"""

import time
import requests

from config import (
    LARGE_TRADE_USD_THRESHOLD,
    WHALE_ALERT_API_KEY,
    WHALE_ALERT_MIN_USD,
)


class WhaleInfo:
    def __init__(self):
        self.large_trades = []       # لیست معاملات بزرگ اخیر روی صرافی
        self.buy_volume_usd = 0.0
        self.sell_volume_usd = 0.0
        self.pressure = "NEUTRAL"    # BUY_PRESSURE / SELL_PRESSURE / NEUTRAL
        self.onchain_transfers = []  # تراکنش‌های Whale Alert (در صورت وجود API key)
        self.onchain_enabled = False


def detect_large_exchange_trades(exchange, symbol: str, lookback: int = 300) -> WhaleInfo:
    """
    آخرین معاملات یک نماد را از صرافی می‌گیرد و معاملات با ارزش دلاری بالا
    (بزرگ‌تر از LARGE_TRADE_USD_THRESHOLD) را به‌عنوان فعالیت نهنگ علامت می‌زند.
    """
    info = WhaleInfo()

    try:
        trades = exchange.fetch_trades(symbol, limit=lookback)
    except Exception:
        return info

    buy_usd = 0.0
    sell_usd = 0.0

    for t in trades:
        price = t.get("price") or 0
        amount = t.get("amount") or 0
        cost = price * amount
        side = t.get("side")  # 'buy' or 'sell'

        if side == "buy":
            buy_usd += cost
        elif side == "sell":
            sell_usd += cost

        if cost >= LARGE_TRADE_USD_THRESHOLD:
            info.large_trades.append({
                "side": side,
                "price": price,
                "amount": amount,
                "cost_usd": cost,
                "timestamp": t.get("timestamp"),
            })

    info.buy_volume_usd = buy_usd
    info.sell_volume_usd = sell_usd

    # فشار خرید/فروش کلی بر اساس نسبت حجم
    total = buy_usd + sell_usd
    if total > 0:
        buy_ratio = buy_usd / total
        if buy_ratio >= 0.60:
            info.pressure = "BUY_PRESSURE"
        elif buy_ratio <= 0.40:
            info.pressure = "SELL_PRESSURE"
        else:
            info.pressure = "NEUTRAL"

    # مرتب‌سازی معاملات بزرگ از بزرگ به کوچک، فقط ۵ مورد برتر
    info.large_trades.sort(key=lambda x: x["cost_usd"], reverse=True)
    info.large_trades = info.large_trades[:5]

    return info


def fetch_whale_alert_transfers(base_symbol: str, minutes_back: int = 60) -> list:
    """
    از Whale Alert API تراکنش‌های بزرگ اخیر مربوط به یک ارز خاص را می‌گیرد.
    نیازمند WHALE_ALERT_API_KEY در config.py است.
    مستندات: https://docs.whale-alert.io/
    """
    if not WHALE_ALERT_API_KEY:
        return []

    now = int(time.time())
    start = now - minutes_back * 60

    url = "https://api.whale-alert.io/v1/transactions"
    params = {
        "api_key": WHALE_ALERT_API_KEY,
        "min_value": WHALE_ALERT_MIN_USD,
        "start": start,
        "end": now,
        "currency": base_symbol.lower(),
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("result") == "success":
            return data.get("transactions", [])
    except Exception:
        pass

    return []


def build_whale_info(exchange, symbol: str) -> WhaleInfo:
    """نقطه ورود اصلی: ترکیب داده صرافی + (در صورت وجود) Whale Alert"""
    info = detect_large_exchange_trades(exchange, symbol)

    base = symbol.split("/")[0]
    onchain = fetch_whale_alert_transfers(base)
    if onchain:
        info.onchain_enabled = True
        info.onchain_transfers = onchain[:5]

    return info
