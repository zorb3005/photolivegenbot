from __future__ import annotations

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

def kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    """
    Обычная reply-клавиатура.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

def ikb_url(text: str, url: str) -> InlineKeyboardMarkup:
    """
    Одна inline-кнопка-ссылка.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]]
    )

def ikb_rows(rows: list[list[tuple[str, str]]], *, columns: int | None = None) -> InlineKeyboardMarkup:
    """
    Универсальная разметка inline-кнопок.
    rows: [[(text, callback_data), ...], ...]
    columns: если задано, строки заменяются одной строкой с указанным количеством кнопок.
    """
    inline_keyboard = []
    if columns:
        flat = [item for row in rows for item in row]
        for idx in range(0, len(flat), columns):
            chunk = flat[idx : idx + columns]
            inline_keyboard.append([InlineKeyboardButton(text=t, callback_data=cb) for t, cb in chunk])
    else:
        inline_keyboard = [
            [InlineKeyboardButton(text=t, callback_data=cb) for t, cb in row] for row in rows
        ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
