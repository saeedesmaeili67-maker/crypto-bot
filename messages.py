# -*- coding: utf-8 -*-
"""
ساخت متن فارسی خروجی (خلاصه معامله، سناریوها، جدول سود/ضرر، امتیاز تایم‌فریم‌ها)
"""

from analysis import AnalysisResult


def fmt_price(p: float) -> str:
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.6f}".rstrip("0").rstrip(".")


def build_summary_text(r: AnalysisResult) -> str:
    lines = []
    lines.append(f"📊 <b>{r.symbol} · 4H · BINANCE</b>")
    lines.append(f"🌍 جلسه معاملاتی: {r.trading_session}")
    lines.append("")

    if r.risk_percent:
        lines.append("💰 <b>اطلاعات معامله (سرمایه {:,.0f}$ · ریسک {:.1f}٪)</b>".format(r.capital, r.risk_percent))
        lines.append(f"حجم پوزیشن پیشنهادی: {r.position_value:,.2f}$ ({r.risk_amount_usd:,.2f}$ در معرض ریسک)")
    else:
        lines.append("💰 <b>اطلاعات معامله با سرمایه {:,.0f} دلار</b>".format(r.capital))
    lines.append(f"Entry (قیمت ورود): <code>{fmt_price(r.entry)}</code>")
    lines.append(f"تعداد تقریبی: {r.coin_amount:,.2f} {r.symbol.split('/')[0]}")
    lines.append("")

    # ---- هشدار وضعیت کلی، اگر هیچ سناریویی تایید نشده ----
    if r.recommended_direction == "NONE":
        lines.append(
            "⚠️ <b>در حال حاضر هیچ سناریوی خرید یا فروشی توسط امتیاز تایم‌فریم‌ها تایید نمی‌شود. "
            "سناریوهای زیر صرفاً جهت اطلاع‌رسانی‌اند، نه توصیه ورود.</b>"
        )
        lines.append("")

    # ---- الگوهای کندلی ----
    if r.patterns_at_support or r.patterns_at_resistance:
        lines.append("🕯️ <b>الگوهای کندلی شناسایی‌شده</b>")
        for p in r.patterns_at_support:
            icon = "🟢" if p["signal"] == "bullish" else ("🔴" if p["signal"] == "bearish" else "⚪")
            lines.append(f"{icon} {p['name_fa']} روی حمایت — {p['description']}")
        for p in r.patterns_at_resistance:
            icon = "🟢" if p["signal"] == "bullish" else ("🔴" if p["signal"] == "bearish" else "⚪")
            lines.append(f"{icon} {p['name_fa']} روی مقاومت — {p['description']}")
        lines.append("")

    # ============================================================
    # سناریوی خرید — فقط وقتی recommended_direction == "BUY" به‌عنوان
    # سناریوی فعال نشان داده می‌شود، در غیر این صورت به‌صورت غیرفعال/اطلاعاتی
    # ============================================================
    active_buy = r.recommended_direction == "BUY"
    lines.append("🟢 <b>سناریوی خرید (صعودی)</b>" + (" — فعال ✅" if active_buy else " — غیرفعال"))
    lines.append(f"در صورت شکست قطعی بالای {fmt_price(r.breakout_level)} وارد شوید.")
    if r.fake_breakout_risk:
        lines.append("⚠️ شکست اخیر با حجم کافی تایید نشده — احتمال شکست کاذب.")
    if active_buy:
        lines.append(f"تارگت ۱: {fmt_price(r.tp_levels[0])}")
        if len(r.tp_levels) > 1:
            lines.append(f"تارگت ۲: {fmt_price(r.tp_levels[1])}")
        if len(r.tp_levels) > 2:
            lines.append(f"تارگت ۳: {fmt_price(r.tp_levels[2])}")
    else:
        lines.append(f"تصمیم فعلی ({r.final_decision}) این سناریو را تایید نمی‌کند.")
    lines.append("")

    # ============================================================
    # سناریوی فروش — حالا اعداد واقعی و مستقل شورت است، نه کپی خرید
    # ============================================================
    active_sell = r.recommended_direction == "SELL"
    lines.append("🔴 <b>سناریوی فروش (نزولی)</b>" + (" — فعال ✅" if active_sell else " — غیرفعال"))
    lines.append(f"در صورت شکست قطعی زیر حمایت {fmt_price(r.breakdown_level)} احتمال ادامه افت وجود دارد.")
    if active_sell:
        lines.append(f"ورود شورت: {fmt_price(r.short_entry)}")
        lines.append(f"تارگت ۱: {fmt_price(r.short_tp_levels[0])}")
        if len(r.short_tp_levels) > 1:
            lines.append(f"تارگت ۲: {fmt_price(r.short_tp_levels[1])}")
        if len(r.short_tp_levels) > 2:
            lines.append(f"تارگت ۳: {fmt_price(r.short_tp_levels[2])}")
        lines.append(f"حد ضرر: {fmt_price(r.short_stop_loss)}")
    else:
        lines.append(f"تصمیم فعلی ({r.final_decision}) این سناریو را تایید نمی‌کند.")
    lines.append("")

    # ============================================================
    # پلن معامله — فقط برای سناریوی فعال محاسبه می‌شود
    # ============================================================
    lines.append("📐 <b>پلن معامله (ریسک/ریوارد)</b>")
    if active_buy:
        lines.append(f"جهت: خرید (Long)")
        lines.append(f"ENTRY: <code>{fmt_price(r.entry)}</code>")
        lines.append(f"STOP LOSS: <code>{fmt_price(r.stop_loss)}</code>")
        for i, tp in enumerate(r.tp_levels, start=1):
            lines.append(f"TP{i}: <code>{fmt_price(tp)}</code>")
        if r.risk_reward:
            lines.append(f"RISK / REWARD: 1 : {r.risk_reward:.2f}")
    elif active_sell:
        lines.append(f"جهت: فروش (Short)")
        lines.append(f"ENTRY: <code>{fmt_price(r.short_entry)}</code>")
        lines.append(f"STOP LOSS: <code>{fmt_price(r.short_stop_loss)}</code>")
        for i, tp in enumerate(r.short_tp_levels, start=1):
            lines.append(f"TP{i}: <code>{fmt_price(tp)}</code>")
        if r.short_risk_reward:
            lines.append(f"RISK / REWARD: 1 : {r.short_risk_reward:.2f}")
    else:
        lines.append("هیچ سناریوی فعالی وجود ندارد — منتظر تایید تایم‌فریم‌ها بمانید.")
    lines.append("")

    # ============================================================
    # سود و ضرر احتمالی — فقط برای سناریوی فعال
    # ============================================================
    lines.append("📋 <b>سود و ضرر احتمالی</b>")
    if active_buy:
        risk_pct = (r.entry - r.stop_loss) / r.entry * 100
        risk_usd = r.position_value * risk_pct / 100
        lines.append(f"Stop Loss ({fmt_price(r.stop_loss)}): {-risk_pct:.2f}٪  (-{risk_usd:,.2f}$)")
        for i, tp in enumerate(r.tp_levels, start=1):
            pct = (tp - r.entry) / r.entry * 100
            usd = r.position_value * pct / 100
            lines.append(f"TP{i} ({fmt_price(tp)}): +{pct:.2f}٪  (+{usd:,.2f}$)")
    elif active_sell:
        risk_pct = (r.short_stop_loss - r.short_entry) / r.short_entry * 100
        risk_usd = r.position_value * risk_pct / 100
        lines.append(f"Stop Loss ({fmt_price(r.short_stop_loss)}): {-risk_pct:.2f}٪  (-{risk_usd:,.2f}$)")
        for i, tp in enumerate(r.short_tp_levels, start=1):
            pct = (r.short_entry - tp) / r.short_entry * 100
            usd = r.position_value * pct / 100
            lines.append(f"TP{i} ({fmt_price(tp)}): +{pct:.2f}٪  (+{usd:,.2f}$)")
    else:
        lines.append("سناریوی فعالی برای محاسبه سود/ضرر وجود ندارد.")
    lines.append("")

    # ---- اندیکاتورهای تکمیلی (بدون تغییر) ----
    lines.append("📈 <b>اندیکاتورهای تکمیلی</b>")
    if r.macd_cross == "bullish_cross":
        lines.append("MACD: تقاطع صعودی تازه رخ داده ✅")
    elif r.macd_cross == "bearish_cross":
        lines.append("MACD: تقاطع نزولی تازه رخ داده ⚠️")
    else:
        macd_trend = "صعودی" if r.macd_hist.iloc[-1] > 0 else "نزولی"
        lines.append(f"MACD: بدون تقاطع تازه، هیستوگرام {macd_trend}")

    if r.bb_squeeze:
        lines.append("Bollinger Bands: فشردگی باندها — احتمال حرکت بزرگ در راه است 🔔")

    if r.rsi_divergence == "bullish":
        lines.append("واگرایی RSI: صعودی (ضعف فروشندگان) 🟢")
    elif r.rsi_divergence == "bearish":
        lines.append("واگرایی RSI: نزولی (ضعف خریداران) 🔴")

    if r.volume_spike.get("is_spike"):
        lines.append(f"حجم: جهش غیرعادی ({r.volume_spike['ratio']}× میانگین) 📊")
    lines.append("")

    lines.append("🕒 <b>امتیاز تایم‌فریم‌ها</b>")
    for tf, data in r.timeframe_scores.items():
        lines.append(f"{tf}: {data['score']}/100 — {data['verdict']}")
    lines.append(f"<b>تصمیم نهایی: {r.final_decision}</b>")
    if r.mtf_confirmed is True:
        lines.append("✅ تایم‌فریم روزانه این سیگنال را تایید می‌کند")
    elif r.mtf_confirmed is False:
        lines.append("⚠️ تایم‌فریم روزانه هم‌جهت نیست — احتیاط بیشتر توصیه می‌شود")
    lines.append("")

    lines.append("🟠 <b>فیلتر بازار (BTC)</b>")
    for tf, data in r.btc_scores.items():
        lines.append(f"BTC {tf} Score: {data['score']}/100")
    lines.append(f"BTC State: {r.btc_state}")
    lines.append(f"Market Condition: {r.market_condition}")
    if r.symbol != "BTC/USDT":
        lines.append(f"همبستگی با BTC: {r.btc_correlation}")

    # ---- نهنگ‌ها (بدون تغییر) ----
    if r.whale_info and (r.whale_info.large_trades or r.whale_info.onchain_transfers):
        lines.append("")
        lines.append("🐋 <b>فعالیت نهنگ‌ها</b>")
        if r.whale_info.large_trades:
            pressure_fa = {
                "BUY_PRESSURE": "فشار خرید 🟢",
                "SELL_PRESSURE": "فشار فروش 🔴",
                "NEUTRAL": "خنثی ⚪",
            }.get(r.whale_info.pressure, "نامشخص")
            lines.append(f"فشار معاملات بزرگ اخیر: {pressure_fa}")
            for t in r.whale_info.large_trades[:3]:
                side_fa = "خرید" if t["side"] == "buy" else "فروش"
                lines.append(f"• {side_fa} بزرگ: {t['cost_usd']:,.0f}$")
        if r.whale_info.onchain_transfers:
            lines.append(f"تراکنش‌های بلاکچینی بزرگ اخیر: {len(r.whale_info.onchain_transfers)} مورد")

    # ---- ساختار بازار چند تایم‌فریمی (بدون تغییر) ----
    if r.market_structure:
        lines.append("")
        lines.append("🏗️ <b>ساختار بازار (Market Structure)</b>")
        tf_labels = {"5D": "5 روزه", "1D": "1 روزه", "4H": "4 ساعته", "30m": "30 دقیقه", "15m": "15 دقیقه"}
        for tf_key, label in tf_labels.items():
            s = r.market_structure.get(tf_key)
            if not s:
                continue
            trend_icon = "🟢" if s["trend"] == "UPTREND" else ("🔴" if s["trend"] == "DOWNTREND" else "⚪")
            line = f"{trend_icon} {label}: {s['trend_fa']}"
            if s.get("bos"):
                bos_fa = "شکست ساختار صعودی تایید شد ✅" if s["bos"] == "bullish" else "شکست ساختار نزولی تایید شد ✅"
                line += f" | {bos_fa}"
            if s.get("choch"):
                choch_fa = "⚠️ هشدار تغییر روند (CHoCH) به سمت صعودی" if s["choch"] == "bullish" else "⚠️ هشدار تغییر روند (CHoCH) به سمت نزولی"
                line += f" | {choch_fa}"
            lines.append(line)

        if r.structure_bias:
            bias_fa = r.structure_bias.get("bias_fa") if isinstance(r.structure_bias, dict) else r.structure_bias
            lines.append(f"<b>جمع‌بندی چند تایم‌فریمی: {bias_fa}</b>")

        # ناحیه ورود/خروج پیشنهادی از تایم‌فریم 4 ساعته (تایم‌فریم اصلی معامله)
        main_struct = r.market_structure.get("4H")
        if main_struct and main_struct.get("entry_zone"):
            ez = main_struct["entry_zone"]
            lines.append(f"ناحیه ورود پیشنهادی (بر پایه ساختار 4H): {fmt_price(ez[0])} تا {fmt_price(ez[1])}")
        if main_struct and main_struct.get("exit_zone"):
            lines.append(f"ناحیه خروج/هدف بعدی (بر پایه ساختار 4H): {fmt_price(main_struct['exit_zone'])}")

    return "\n".join(lines)
