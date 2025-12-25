from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def format_tokens(value: int) -> str:
    """
    Форматирует число токенов с пробелом как разделителем тысяч.
    """
    return f"{int(value):,}".replace(",", " ")


def build_invoice_view(
    ctx,
    *,
    payment_id: str,
    confirmation_url: str,
    rub_amount: int | float,
    tokens: int,
    plan_title: str | None = None,
    prefix: str | None = None,
):
    """
    Универсальная вёрстка счёта (тарифы/пополнение).
    """
    title = plan_title or "Платёж"
    text = (
        f"✨ Пакет: {title}\n"
        f"🌟 Получите: {format_tokens(tokens)} генерацию\n"
        f"🆔 ID платежа: `{payment_id}`\n\n"
        "Нажмите на кнопку ниже для перехода к оплате:\n\n"
        "⚠️ После успешной оплаты баланс будет пополнен автоматически"
    )
    if prefix:
        text = prefix + "\n\n" + text

    buttons = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", url=confirmation_url)],
            [InlineKeyboardButton(text="🔄 Проверить статус", callback_data=f"check_payment:{payment_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:account.cabinet")],
        ]
    )
    return ctx.reply(text, buttons, parse_mode="Markdown")


def build_clone_invoice_view(ctx, *, payment_id: str, confirmation_url: str):
    """
    Отдельный текст для одноразовой покупки клонирования.
    """
    text = (
        "🧬 Клонирование голоса — 299 ₽\n"
        "Лицензия навсегда. Озвучивайте сколько угодно.\n"
        f"🆔 ID платежа: `{payment_id}`\n\n"
        "Нажмите на кнопку ниже для перехода к оплате:\n\n"
        "⚠️ После успешной оплаты доступ к клонированию разблокируется автоматически"
    )
    buttons = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", url=confirmation_url)],
            [InlineKeyboardButton(text="🔄 Проверить статус", callback_data=f"check_payment:{payment_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:account.cabinet")],
        ]
    )
    return ctx.reply(text, buttons, parse_mode="Markdown")
