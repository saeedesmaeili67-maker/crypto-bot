# -*- coding: utf-8 -*-
"""
دریافت داده قیمتی (کندل‌ها) از صرافی با استفاده از ccxt
"""

import ccxt
import pandas as pd
from config import EXCHANGE_ID


class SymbolNotFoundError(Exception):
    pass


def get_exchange():
    exchange_class = getattr(ccxt, EXCHANGE_ID)
    return exchange_class({"enableRateLimit": True})


def normalize_symbol(exchange, user_input: str) -> str:
    """
    ورودی کاربر مثل 'BTC' یا 'RESOLV' یا 'BTC/USDT' را به فرمت جفت‌ارز
    معتبر روی صرافی (مثلا 'BTC/USDT') تبدیل می‌کند.
    """
    user_input = user_input.strip().upper().replace(" ", "")

    if "/" in user_input:
        candidate = user_input
    else:
        candidate = f"{user_input}/USDT"

    markets = exchange.load_markets()

    if candidate in markets:
        return candidate

    # اگر جفت مستقیم با USDT پیدا نشد، دنبال هر جفتی با همان بیس بگرد
    base = user_input.split("/")[0]
    for symbol in markets:
        if symbol.startswith(base + "/") and symbol.endswith("/USDT"):
            return symbol

    raise SymbolNotFoundError(f"ارز '{user_input}' روی {EXCHANGE_ID} پیدا نشد.")


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df
