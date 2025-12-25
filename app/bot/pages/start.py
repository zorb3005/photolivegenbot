from pathlib import Path

from app.bot.ui import ikb_rows, kb


class Start:
    slug = "start"

    async def render(self, ctx):
        text = ctx.t("start.intro")
        reply_buttons = kb(
            [
                [ctx.t("buttons.animate_photo")],
                [ctx.t("buttons.cabinet"), ctx.t("buttons.topup")],
            ]
        )

        view = ctx.reply(text, reply_buttons, parse_mode="HTML")

        # Пробуем отправить приветственное видео как в примере
        video_path = Path("pfoto/старт.MP4")
        if video_path.exists():
            try:
                view["video"] = video_path.read_bytes()
                view["video_filename"] = video_path.name
                view["video_caption"] = view.get("text")
                view["video_parse_mode"] = view.get("parse_mode")
            except Exception:
                pass

        return view

    async def handle(self, ctx, m: str):
        choice = (m or "").strip()
        if not choice:
            return "start"

        if choice == ctx.t("buttons.animate_photo"):
            return "flow.animate"
        if choice == ctx.t("buttons.cabinet"):
            return "account.cabinet"
        if choice == ctx.t("buttons.topup"):
            return "account.topup"
        return "start"
