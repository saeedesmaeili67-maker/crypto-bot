# -*- coding: utf-8 -*-
"""
ربات تلگرام Spot Analyzer Bot
دستور اجرا: python bot.py
"""

import logging

from telegram import Update, ReplyKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters,
)

from config import BOT_TOKEN
from data_fetcher import get_exchange, normalize_symbol, SymbolNotFoundError
from analysis import analyze_symbol
from chart import build_chart_image
from messages import build_summary_text, fmt_price

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---- حالت‌های مکالمه ----
ASK_COIN, ASK_CAPITAL, ASK_ENTRY, ASK_NEW_ENTRY = range(4)

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        ["🔍 تحلیل ارز", "📊 تحلیل مجدد"],
        ["💰 سود و ضرر", "🎯 تغییر Entry"],
        ["⛔ SL / TP", "ℹ️ راهنما"],
    ],
    resize_keyboard=True,
)

WELCOME_TEXT = "به ربات تحلیل‌گر حرفه‌ای اسپات خوش آمدید.\nلطفاً یک گزینه را انتخاب کنید."

HELP_TEXT = (
    "🔍 <b>تحلیل ارز</b>: تحلیل کامل یک ارز جدید (حمایت/مقاومت، RSI، Entry/SL/TP)\n"
    "📊 <b>تحلیل مجدد</b>: تحلیل مجدد همان ارز با داده‌های لحظه‌ای جدید\n"
    "💰 <b>سود و ضرر</b>: جدول سود/ضرر بر اساس سرمایه فعلی\n"
    "🎯 <b>تغییر Entry</b>: محاسبه مجدد با قیمت ورود جدید\n"
    "⛔ <b>SL / TP</b>: نمایش مجدد سطوح حد ضرر و تارگت‌ها\n"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT, reply_markup=MAIN_MENU_KB)
    return ConversationHandler.END


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if "تحلیل ارز" in text:
        await update.message.reply_text("نام ارز مورد نظر را وارد کنید (مثال: BTC یا RESOLV):")
        return ASK_COIN

    if "تحلیل مجدد" in text:
        if "symbol" not in context.user_data:
            await update.message.reply_text("ابتدا یک‌بار «🔍 تحلیل ارز» را انجام دهید.")
            return ConversationHandler.END
        await _run_analysis(update, context, context.user_data["symbol"],
                             context.user_data["capital"], context.user_data["entry"])
        return ConversationHandler.END

    if "سود و ضرر" in text:
        if "result" not in context.user_data:
            await update.message.reply_text("ابتدا یک‌بار «🔍 تحلیل ارز» را انجام دهید.")
            return ConversationHandler.END
        r = context.user_data["result"]
        await update.message.reply_text(build_summary_text(r), parse_mode="HTML", reply_markup=MAIN_MENU_KB)
        return ConversationHandler.END

    if "تغییر Entry" in text or "تغییر  Entry" in text:
        if "symbol" not in context.user_data:
            await update.message.reply_text("ابتدا یک‌بار «🔍 تحلیل ارز» را انجام دهید.")
            return ConversationHandler.END
        await update.message.reply_text("قیمت ورود (Entry) جدید را وارد کنید:")
        return ASK_NEW_ENTRY

    if "SL" in text or "TP" in text:
        if "result" not in context.user_data:
            await update.message.reply_text("ابتدا یک‌بار «🔍 تحلیل ارز» را انجام دهید.")
            return ConversationHandler.END
        r = context.user_data["result"]
        msg = [f"ENTRY: {fmt_price(r.entry)}", f"STOP LOSS: {fmt_price(r.stop_loss)}"]
        for i, tp in enumerate(r.tp_levels, start=1):
            msg.append(f"TP{i}: {fmt_price(tp)}")
        if r.risk_reward:
            msg.append(f"RISK/REWARD: 1 : {r.risk_reward:.2f}")
        await update.message.reply_text("\n".join(msg), reply_markup=MAIN_MENU_KB)
        return ConversationHandler.END

    if "راهنما" in text:
        await update.message.reply_text(HELP_TEXT, parse_mode="HTML", reply_markup=MAIN_MENU_KB)
        return ConversationHandler.END

    await update.message.reply_text("لطفاً یکی از گزینه‌های منو را انتخاب کنید.", reply_markup=MAIN_MENU_KB)
    return ConversationHandler.END


async def ask_coin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["coin_input"] = update.message.text.strip()
    await update.message.reply_text("سرمایه خود را به دلار وارد کنید (مثال: 3000):")
    return ASK_CAPITAL


async def ask_capital_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        capital = float(update.message.text.strip().replace(",", ""))
    except ValueError:
        await update.message.reply_text("لطفاً یک عدد معتبر برای سرمایه وارد کنید:")
        return ASK_CAPITAL

    context.user_data["capital"] = capital
    await update.message.reply_text("قیمت ورود مورد نظر (Entry) را وارد کنید (مثال: 0.01687):")
    return ASK_ENTRY


async def ask_entry_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entry = float(update.message.text.strip().replace(",", ""))
    except ValueError:
        await update.message.reply_text("لطفاً یک عدد معتبر برای Entry وارد کنید:")
        return ASK_ENTRY

    coin_input = context.user_data["coin_input"]
    capital = context.user_data["capital"]
    await _run_analysis(update, context, coin_input, capital, entry)
    return ConversationHandler.END


async def ask_new_entry_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entry = float(update.message.text.strip().replace(",", ""))
    except ValueError:
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید:")
        return ASK_NEW_ENTRY

    symbol = context.user_data["symbol"]
    capital = context.user_data["capital"]
    await _run_analysis(update, context, symbol, capital, entry)
    return ConversationHandler.END


async def _run_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, coin_input: str, capital: float, entry: float):
    progress = await update.message.reply_text("⏳ در حال دریافت داده‌ها و تحلیل بازار... لطفاً چند ثانیه صبر کنید")

    try:
        exchange = get_exchange()
        symbol = normalize_symbol(exchange, coin_input)
        result = analyze_symbol(exchange, symbol, entry, capital)
    except SymbolNotFoundError as e:
        await progress.edit_text(str(e))
        return
    except Exception as e:
        logger.exception("analysis failed")
        await progress.edit_text(f"خطا در تحلیل: {e}")
        return

    context.user_data["symbol"] = symbol
    context.user_data["capital"] = capital
    context.user_data["entry"] = entry
    context.user_data["result"] = result

    await progress.edit_text("تحلیل تکمیل شد ✅")

    chart_path = build_chart_image(result)
    summary = build_summary_text(result)

    with open(chart_path, "rb") as f:
        await update.message.reply_photo(photo=InputFile(f), caption=None)

    await update.message.reply_text(summary, parse_mode="HTML", reply_markup=MAIN_MENU_KB)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=MAIN_MENU_KB)
    return ConversationHandler.END


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, menu_router),
        ],
        states={
            ASK_COIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_coin_received)],
            ASK_CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_capital_received)],
            ASK_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_entry_received)],
            ASK_NEW_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_new_entry_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.run_polling()


if __name__ == "__main__":
    main()
