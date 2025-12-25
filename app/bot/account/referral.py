from html import escape
from urllib.parse import quote_plus

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.ui import ikb_rows
from app.settings import settings

class Referral:
    slug = "account.referral"

    async def render(self, ctx):
        snap = await ctx.ensure_snapshot()
        internal_id = snap.get("internal_id") or snap["user_id"]

        if settings.BOT_USERNAME:
            deep_link = f"https://t.me/{settings.BOT_USERNAME}?start=ref_{internal_id}"
        else:
            deep_link = ctx.t("referral.no_username")

        share_url = (
            f"https://t.me/share/url?url={quote_plus(deep_link)}"
            if settings.BOT_USERNAME
            else None
        )

        def _mask_link(url: str) -> str:
            head, sep, tail = url.partition("://")
            if not sep:
                return url
            # добавляем zero-width joiner, чтобы Telegram не делал ссылку кликабельной/синей
            return f"{head}://\u2060{tail}"

        safe_link = escape(_mask_link(deep_link))

        recent_refs = snap.get("recent_refs") or ""
        text = ctx.t(
            "referral.body",
            friends=snap["friends_count"],
            earned=snap.get("invitee_bonus", 0),
            link=safe_link,
            recent_refs=recent_refs or "-",
        )

        if share_url:
            buttons = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text=ctx.t("buttons.share"), url=share_url),
                        InlineKeyboardButton(text=ctx.t("buttons.back"), callback_data="nav:account.cabinet"),
                    ],
                ]
            )
        else:
            buttons = ikb_rows([
                [(ctx.t("buttons.back"), "nav:account.cabinet"), (ctx.t("buttons.share"), "ref:share")],
            ])
        return ctx.reply(text, buttons, parse_mode="HTML")

    async def handle(self, ctx, m: str):
        choice = (m or "").strip()
        low = choice.lower()

        if choice == ctx.t("buttons.back") or "назад" in low:
            return "account.cabinet"

        if choice == ctx.t("buttons.share") or "поделиться" in low:
            return self.slug

        return self.slug

    async def on_callback(self, ctx, query):
        if (query.data or "") == "ref:share":
            await query.answer(ctx.t("referral.no_username"), show_alert=True)
            return None
        return None
