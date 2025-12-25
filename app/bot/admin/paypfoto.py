from __future__ import annotations

import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.infrastructure.db.base import async_session
from app.infrastructure.db.repositories.user_repo import UserRepo


class AdminPayPfoto:
    slug = "admin.paypfoto"
    _NUM_RE = re.compile(r"\d+")
    _BACK_CB = "admin:menu"

    async def render(self, ctx):
        user_id = ctx.state.admin_paypfoto_user_id
        line1 = "1. Кому начислить:"
        if user_id:
            line1 = f"{line1} {user_id}"
        line2 = "2. Сколько начислить:"
        text = "\n".join(
            [
                line1,
                line2,
                "",
                "Можно в одном сообщении: <user_id> <кол-во>",
            ]
        )
        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=self._BACK_CB)],
            ]
        )
        return ctx.reply(text, buttons)

    async def handle(self, ctx, m: str):
        text = (m or "").strip()
        if not text:
            return self.slug

        nums = [int(x) for x in self._NUM_RE.findall(text)]
        if not nums:
            ctx.flash("Нужно указать user_id и количество.")
            return self.slug

        user_id = ctx.state.admin_paypfoto_user_id
        amount = None

        if user_id is None:
            if len(nums) == 1:
                user_id = nums[0]
            else:
                user_id, amount = self._split_user_amount(nums)
        else:
            if len(nums) == 1:
                amount = nums[0]
            else:
                user_id, amount = self._split_user_amount(nums)

        if not user_id or user_id <= 0:
            ctx.flash("Неверный user_id.")
            ctx.state.admin_paypfoto_user_id = None
            return self.slug

        if amount is None:
            ctx.state.admin_paypfoto_user_id = user_id
            return self.slug

        if amount <= 0:
            ctx.flash("Количество должно быть больше нуля.")
            return self.slug

        async with async_session() as s:
            repo = UserRepo(s)
            user = await repo.get(telegram_id=user_id)
            if not user:
                user = await repo.get_by_internal_id(user_id)
            if not user:
                ctx.state.admin_paypfoto_user_id = None
                ctx.flash(f"Пользователь {user_id} не найден.")
                return self.slug
            target_id = int(user.telegram_id)
            await repo.inc_balance(telegram_id=target_id, delta=amount, bucket="animate")
            await s.commit()

        ctx.state.admin_paypfoto_user_id = None
        ctx.flash(f"Начислено {amount} генераций пользователю {target_id}.")
        return self.slug

    @staticmethod
    def _split_user_amount(nums: list[int]) -> tuple[int | None, int | None]:
        if len(nums) < 2:
            return nums[0] if nums else None, None
        first, second = nums[0], nums[1]
        if first >= 100000 or second >= 100000:
            user_id = max(first, second)
            amount = min(first, second)
            return user_id, amount
        return first, second
