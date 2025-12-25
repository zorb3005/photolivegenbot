from __future__ import annotations

import re
from typing import Any, Dict

import httpx
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.application.usecases.payments.create_invoice import CreateInvoice, CreateInvoiceInput
from app.bot.account.payment_views import build_clone_invoice_view, build_invoice_view
from app.infrastructure.db.base import async_session
from app.infrastructure.db.repositories.user_repo import UserRepo
from app.settings import settings

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailForReceipt:
    """
    Запрашивает у пользователя email для отправки чека YooKassa.
    Хранит данные о ожидающем платеже в ctx.state.pending_payment.
    """

    slug = "payments.email"
    _CANCEL = "email:cancel"

    @classmethod
    def prompt(cls, ctx, *, back_to: str = "account.cabinet"):
        """
        Включает режим ожидания email и возвращает view с кнопкой Отмена.
        """
        ctx.state.pending_payment_back = back_to
        ctx.state.current_page = cls.slug
        return ctx.reply(
            ctx.t("email.prompt"),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=ctx.t("buttons.cancel"), callback_data=cls._CANCEL)]
                ]
            ),
            parse_mode="HTML",
        )

    @classmethod
    async def finalize_now(cls, ctx, *, payload: Dict[str, Any], email: str):
        """
        Создаёт платёж сразу (без запроса email), используя общий код из _finish_payment.
        """
        ctx.state.pending_payment = payload
        ctx.state.pending_payment_back = payload.get("back_to")
        view = await cls()._finish_payment(ctx, email)
        ctx.state.pending_payment = None
        ctx.state.pending_payment_back = None
        return view

    async def render(self, ctx):
        back_to = ctx.state.pending_payment_back or "account.cabinet"
        # render() может вызываться повторно, поэтому не трогаем current_page здесь
        return self.prompt(ctx, back_to=back_to)

    async def handle(self, ctx, m: str):
        email = (m or "").strip()
        if not email:
            return self.slug

        if email.lower() in {"отмена", "cancel"}:
            ctx.state.pending_payment = None
            back_to = ctx.state.pending_payment_back or "account.cabinet"
            ctx.state.pending_payment_back = None
            return back_to

        if not EMAIL_RE.match(email):
            return ctx.reply(
                ctx.t("email.invalid"),
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=ctx.t("buttons.cancel"), callback_data=self._CANCEL)]
                    ]
                ),
                parse_mode="HTML",
            )

        async with async_session() as s:
            repo = UserRepo(s)
            await repo.get_or_create(telegram_id=ctx.user_id)
            await repo.set_email(telegram_id=ctx.user_id, email=email)
            await s.commit()
        ctx.state.email = email

        success = ctx.t("email.saved", email=email)

        if ctx.state.pending_payment:
            view = await self._finish_payment(ctx, email, success_prefix=success)
            ctx.state.pending_payment = None
            ctx.state.pending_payment_back = None
            return view

        back_to = ctx.state.pending_payment_back or "account.cabinet"
        ctx.state.pending_payment_back = None
        return ctx.reply(success, InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav:{back_to}")]]
        ), parse_mode="HTML")

    async def on_callback(self, ctx, query: CallbackQuery):
        if (query.data or "") == self._CANCEL:
            ctx.state.pending_payment = None
            back_to = ctx.state.pending_payment_back or "account.cabinet"
            ctx.state.pending_payment_back = None
            await query.answer("Отменено")
            return back_to
        return None

    async def _finish_payment(self, ctx, email: str, success_prefix: str | None = None):
        payload: Dict[str, Any] = ctx.state.pending_payment or {}
        ctx.state.current_page = payload.get("back_to") or ctx.state.pending_payment_back or "account.cabinet"

        async with async_session() as s:
            try:
                out = await CreateInvoice(s)(
                    CreateInvoiceInput(
                        user_id=ctx.user_id,
                        amount_tokens=int(payload.get("amount_tokens") or 0),
                        rub_amount=payload.get("rub_amount") or 0,
                        description=payload.get("description") or "",
                        return_url=payload.get("return_url") or f"{settings.BASE_URL.rstrip('/')}/payments/return",
                        metadata=payload.get("metadata"),
                        customer_email=email,
                    )
                )
                await s.commit()
            except httpx.RequestError:
                ctx.state.pending_payment = payload  # оставляем, чтобы можно было попробовать снова
                back_to = payload.get("back_to") or "account.cabinet"
                ctx.state.current_page = back_to
                text = f"{success_prefix or ctx.t('email.saved', email=email)}\n\n{ctx.t('email.error_timeout')}"
                buttons = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"nav:{back_to}")],
                    ]
                )
                return ctx.reply(text, buttons, parse_mode="HTML")

        if payload.get("remember_payment"):
            ctx.state.current_payment_id = out.payment_id

        kind = payload.get("kind", "plan")
        if kind == "clone":
            return build_clone_invoice_view(
                ctx,
                payment_id=out.payment_id,
                confirmation_url=out.confirmation_url,
            )

        plan_title = payload.get("plan_title")
        tokens = int(payload.get("amount_tokens") or 0)
        rub_amount = payload.get("rub_amount") or 0
        return build_invoice_view(
            ctx,
            payment_id=out.payment_id,
            confirmation_url=out.confirmation_url,
            rub_amount=rub_amount,
            tokens=tokens,
            plan_title=plan_title,
            prefix=success_prefix,
        )
