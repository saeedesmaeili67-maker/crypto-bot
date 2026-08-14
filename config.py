# -*- coding: utf-8 -*-
"""
تنظیمات ربات
"""

import os

# توکن ربات تلگرام را از BotFather بگیرید و اینجا (یا در متغیر محیطی TELEGRAM_BOT_TOKEN) قرار دهید
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT-YOUR-TELEGRAM-BOT-TOKEN-HERE")

# صرافی منبع داده (ccxt)
EXCHANGE_ID = "binance"

# جفت‌ارز پیش‌فرض برای فیلتر بازار (بیت‌کوین)
BTC_SYMBOL = "BTC/USDT"

# تایم‌فریم اصلی برای چارت و تحلیل ساختاری
MAIN_TIMEFRAME = "4h"
MAIN_LIMIT = 200  # تعداد کندل‌های دریافتی برای تایم‌فریم اصلی

# تایم‌فریم‌هایی که برای امتیازدهی چندگانه بررسی می‌شوند
SCORE_TIMEFRAMES = ["15m", "30m", "4h", "1d"]
SCORE_LIMIT = 150

RSI_PERIOD = 14
VOLUME_MA_PERIOD = 20

# پوشه موقت برای ذخیره چارت‌های تولید شده
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "charts")
os.makedirs(OUTPUT_DIR, exist_ok=True)
