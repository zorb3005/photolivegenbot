from __future__ import annotations

from app.bot.context import BotContext
from app.bot.pages import ALL_PAGES

# Индекс по slug -> объект страницы
PAGE_INDEX = {p.slug: p for p in ALL_PAGES}


async def route(ctx: BotContext, incoming_text: str):
    """
    Универсальный маршрутизатор.
    1) Берём текущую страницу по slug из state
    2) Гарантируем наличие снапшота пользователя (создаст его при первом заходе)
    3) Отдаём управление handle(), который может вернуть следующий slug
    4) Рендерим целевую страницу и возвращаем {"text", "buttons"}
    """
    # текущая страница (если slug неизвестен, идём на "start")
    page = PAGE_INDEX.get(ctx.state.current_page, PAGE_INDEX["start"])

    # гарантируем, что в контексте есть данные юзера
    await ctx.ensure_snapshot()

    # сначала даём странице обработать входящий текст
    next_step = await page.handle(ctx, (incoming_text or "").strip())

    if isinstance(next_step, dict):
        return next_step

    if next_step:
        ctx.state.current_page = next_step

    # рендерим уже целевую страницу (вдруг handle перекинул пользователя)
    target = PAGE_INDEX.get(ctx.state.current_page, PAGE_INDEX["start"])

    # ещё раз гарантируем снапшот (на случай, если handle изменил юзера/баланс)
    await ctx.ensure_snapshot(refresh=True)

    return await target.render(ctx)
