from __future__ import annotations

from app.bot.ui import ikb_rows


class FormatSelect:
    slug = "format.select"

    FORMATS = [
        ("9:16 - вертикальный формат", "9:16"),
        ("16:9 - горизонтальный формат", "16:9"),
        ("1:1 - квадратный формат", "1:1"),
    ]

    def _back_target(self, ctx) -> str:
        return ctx.state.format_back or "start"

    def _markup(self, ctx):
        rows = [[(label, f"format:{value}")] for label, value in self.FORMATS]
        back_target = self._back_target(ctx)
        rows.append([(ctx.t("buttons.back"), f"nav:{back_target}")])
        return ikb_rows(rows)

    async def render(self, ctx):
        text = ctx.t("format.intro", current=ctx.state.video_format)
        return ctx.reply(text, self._markup(ctx), parse_mode="HTML")

    async def handle(self, ctx, m: str):
        # формат выбирается через инлайн-кнопки; текст не обрабатываем
        return self.slug

    async def on_callback(self, ctx, query):
        data = query.data or ""
        if data.startswith("format:"):
            label = data.split("format:", 1)[1]
            ctx.state.video_format = label
            await query.answer(ctx.t("format.selected", current=label))
            return self._back_target(ctx)
        if data.startswith("nav:"):
            return data.split("nav:", 1)[1]
        return None
