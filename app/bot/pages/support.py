from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.ui import ikb_rows


class Support:
    slug = "support"

    async def render(self, ctx):
        buttons = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=ctx.t("buttons.back"), callback_data="nav:account.cabinet")]]
        )
        return ctx.reply(ctx.t("support.text"), buttons, parse_mode="HTML")

    async def handle(self, ctx, m: str):
        choice = (m or "").strip()
        if choice == ctx.t("buttons.back"):
            return "account.cabinet"
        if "назад" in (m or "").lower():
            return "account.cabinet"
        return self.slug
