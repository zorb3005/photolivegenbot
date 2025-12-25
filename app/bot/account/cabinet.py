from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class Cabinet:
    slug = "account.cabinet"

    async def render(self, ctx):
        snap = await ctx.ensure_snapshot()
        text = ctx.t(
            "cabinet.body",
            balance=snap.get("animate_balance_tokens", 0),
            friends=snap["friends_count"],
            user_id=snap["user_id"],
            internal_id=snap.get("internal_id") or snap["user_id"],
        )
        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=ctx.t("buttons.topup"), callback_data="nav:account.topup"),
                    InlineKeyboardButton(text=ctx.t("buttons.referral"), callback_data="nav:account.referral"),
                ],
                [
                    InlineKeyboardButton(text=ctx.t("buttons.our_bots"), callback_data="nav:our_bots"),
                    InlineKeyboardButton(text=ctx.t("buttons.help"), callback_data="nav:support"),
                ],
            ]
        )
        return ctx.reply(text, buttons, parse_mode="HTML")

    async def handle(self, ctx, m: str):
        choice = (m or "").strip()
        if choice == ctx.t("buttons.back"):
            return "start"
        if choice in (ctx.t("buttons.topup"), ctx.t("buttons.tariffs")):
            return "account.topup"
        if choice == ctx.t("buttons.our_bots"):
            return "our_bots"
        if choice == ctx.t("buttons.support"):
            return "support"
        if choice == ctx.t("buttons.referral"):
            return "account.referral"
        low = (m or "").lower()
        if "попол" in low or "тариф" in low:
            return "account.topup"
        if "бот" in low:
            return "our_bots"
        if "поддерж" in low:
            return "support"
        if "друг" in low or "рефера" in low:
            return "account.referral"
        return self.slug
