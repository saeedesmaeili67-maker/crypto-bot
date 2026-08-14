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
    coin_amount = r.coin_amount
    risk_pct = (r.entry - r.stop_loss) / r.entry * 100
    risk_usd = r.capital * risk_pct / 100

    lines = []
    lines.append(f"📊 <b>{r.symbol} · 4H · BINANCE</b>")
    lines.append("")
    lines.append("💰 <b>اطلاعات معامله با سرمایه {:,.0f} دلار</b>".format(r.capital))
    lines.append(f"Entry (قیمت ورود): <code>{fmt_price(r.entry)}</code>")
    lines.append(f"تعداد تقریبی: {coin_amount:,.2f} {r.symbol.split('/')[0]}")
    lines.append(f"ارزش سرمایه: {r.capital:,.2f} USDT")
    lines.append("")

    lines.append("🟢 <b>سناریوی خرید (صعودی)</b>")
    lines.append(f"در صورت شکست قطعی بالای {fmt_price(r.breakout_level)} وارد شوید.")
    lines.append(f"تارگت ۱: {fmt_price(r.tp_levels[0])}")
    if len(r.tp_levels) > 1:
        lines.append(f"تارگت ۲: {fmt_price(r.tp_levels[1])}")
    if len(r.tp_levels) > 2:
        lines.append(f"تارگت ۳: {fmt_price(r.tp_levels[2])}")
    lines.append("")

    lines.append("🔴 <b>سناریوی فروش (نزولی)</b>")
    lines.append(f"در صورت عدم شکست {fmt_price(r.breakout_level)}، برگشت قیمت محتمل است.")
    lines.append(f"در صورت افت زیر حمایت {fmt_price(r.main_support)} ضعف نشانه بازار است.")
    lines.append(f"حد ضرر: {fmt_price(r.stop_loss)}")
    lines.append("")

    lines.append("📐 <b>پلن معامله (ریسک/ریوارد)</b>")
    lines.append(f"ENTRY: <code>{fmt_price(r.entry)}</code>")
    lines.append(f"STOP LOSS: <code>{fmt_price(r.stop_loss)}</code>")
    for i, tp in enumerate(r.tp_levels, start=1):
        lines.append(f"TP{i}: <code>{fmt_price(tp)}</code>")
    if r.risk_reward:
        lines.append(f"RISK / REWARD: 1 : {r.risk_reward:.2f}")
    lines.append("")

    lines.append("📋 <b>سود و ضرر احتمالی با سرمایه {:,.0f} دلار</b>".format(r.capital))
    lines.append(f"Stop Loss ({fmt_price(r.stop_loss)}): {-risk_pct:.2f}٪  (-{risk_usd:,.2f}$)")
    for i, tp in enumerate(r.tp_levels, start=1):
        pct = (tp - r.entry) / r.entry * 100
        usd = r.capital * pct / 100
        lines.append(f"TP{i} ({fmt_price(tp)}): +{pct:.2f}٪  (+{usd:,.2f}$)")
    lines.append("")

    lines.append("🕒 <b>امتیاز تایم‌فریم‌ها</b>")
    for tf, data in r.timeframe_scores.items():
        lines.append(f"{tf}: {data['score']}/100 — {data['verdict']}")
    lines.append(f"<b>تصمیم نهایی: {r.final_decision}</b>")
    lines.append("")

    lines.append("🟠 <b>فیلتر بازار (BTC)</b>")
    for tf, data in r.btc_scores.items():
        lines.append(f"BTC {tf} Score: {data['score']}/100")
    lines.append(f"BTC State: {r.btc_state}")
    lines.append(f"Market Condition: {r.market_condition}")

    return "\n".join(lines)
