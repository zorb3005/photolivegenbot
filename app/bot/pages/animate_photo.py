from __future__ import annotations

import asyncio
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.admin.live_metrics import finish_generation, start_generation
from app.bot.ui import ikb_rows
from app.bot.account.topup import TopUp
from app.infrastructure.db.base import async_session
from app.infrastructure.db.repositories.user_repo import UserRepo
from app.infrastructure.providers.klingai import KlingClient, KlingError
from app.settings import settings
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple
import re


async def _get_file_url(bot, file_id: str) -> str:
    file = await bot.get_file(file_id)
    if not settings.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")
    return f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file.file_path}"


class AnimatePhoto:
    slug = "flow.animate"

    def _preview_video_path(self) -> Path | None:
        candidates = [
            Path("pfoto/Оживить фото.mp4"),
            Path("pfoto/Оживить фото.MP4"),
        ]
        for path in candidates:
            if path.exists():
                return path
        return None

    def _actions(self, ctx):
        return ikb_rows(
            [
                [(ctx.t("buttons.change_format"), "nav:format.select")],
            ]
        )

    def _final_actions(self, ctx):
        buttons = [
            InlineKeyboardButton(text=ctx.t("buttons.try_more"), callback_data="nav:flow.animate"),
        ]
        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    def _paywall(self, ctx):
        rows = [[(title, f"topup_animate:{key}")] for key, title, _, _ in TopUp.ANIMATE_PACKAGES]
        view = ctx.reply(ctx.t("paywall.animate"), ikb_rows(rows), parse_mode="HTML", disable_preview=True)
        video_path = self._preview_video_path()
        if video_path and video_path.exists():
            try:
                view["video"] = video_path.read_bytes()
                view["video_filename"] = video_path.name
                view["video_caption"] = view.get("text")
                view["video_parse_mode"] = view.get("parse_mode")
            except Exception:
                pass
        return view

    async def render(self, ctx):
        snap = await ctx.ensure_snapshot()
        format_labels = {
            "9:16": ctx.t("format.vertical"),
            "16:9": ctx.t("format.horizontal"),
            "1:1": ctx.t("format.square"),
        }
        fmt = ctx.state.video_format
        fmt_label = format_labels.get(fmt, ctx.t("format.vertical"))
        total_balance = snap.get("animate_balance_tokens", 0)
        view = ctx.reply(
            ctx.t(
                "animate.intro",
                current_format=fmt,
                current_format_label=fmt_label,
                current_balance=total_balance,
            ),
            self._actions(ctx),
            parse_mode="HTML",
        )
        video_path = self._preview_video_path()
        if video_path and video_path.exists():
            try:
                view["video"] = video_path.read_bytes()
                view["video_filename"] = video_path.name
                view["video_caption"] = view.get("text")
                view["video_parse_mode"] = view.get("parse_mode")
            except Exception:
                pass
        return view

    async def handle(self, ctx, m: str):
        text = (m or "").strip()
        if not text:
            return self.slug

        if not ctx.state.animate_photo_file_id:
            return ctx.reply(ctx.t("animate.waiting_photo"), self._actions(ctx), parse_mode="HTML")

        ctx.state.animate_photo_prompt = text
        return await self._run_generation(ctx, message=ctx.state.animate_last_message)

    async def handle_photo(self, ctx, message: Message):
        if message.photo:
            ctx.state.animate_photo_file_id = message.photo[-1].file_id
            ctx.state.animate_last_message = message
        caption = (message.caption or "").strip()
        if caption:
            ctx.state.animate_photo_prompt = caption
            return await self._run_generation(ctx, message=message)

        try:
            sent = await message.answer(ctx.t("animate.photo_received"), parse_mode="HTML")
            ctx.state.animate_hint_message_id = sent.message_id
            return "__skip_render__"
        except Exception:
            ctx.state.animate_hint_message_id = None
            return ctx.reply(ctx.t("animate.photo_received"), None, parse_mode="HTML")

    async def handle_voice(self, ctx, message: Message):
        # В режиме оживления фото ожидаем текстовый промпт, а не голосовое
        return ctx.reply(ctx.t("animate.voice_not_supported"), None)

    async def on_callback(self, ctx, query):
        data = query.data or ""
        if data.startswith(("topup_animate:", "topup:")):
            return await TopUp().on_callback(ctx, query)
        if data == "run:animate":
            if ctx.state.animate_photo_file_id and ctx.state.animate_photo_prompt:
                return await self._run_generation(ctx, message=query.message)
            return self.slug
        if data.startswith("nav:"):
            return data.split("nav:", 1)[1]
        return None

    async def _run_generation(self, ctx, message: Message | None):
        if not ctx.state.animate_photo_file_id:
            return ctx.reply(ctx.t("animate.waiting_photo"), self._actions(ctx), parse_mode="HTML")
        if not ctx.state.animate_photo_prompt:
            return ctx.reply(ctx.t("animate.waiting_photo"), self._actions(ctx), parse_mode="HTML")

        try:
            if ctx.state.animate_hint_message_id and message and message.chat:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=ctx.state.animate_hint_message_id)
        except Exception:
            pass
        ctx.state.animate_hint_message_id = None

        snap = await ctx.ensure_snapshot(refresh=True)
        total_balance = snap.get("animate_balance_tokens", 0)
        if total_balance <= 0:
            return self._paywall(ctx)

        bot = message.bot if message else None
        if bot is None:
            return ctx.reply(ctx.t("animate.error_unavailable"), self._actions(ctx), parse_mode="HTML")

        # Сообщаем, что генерация началась, и обновляем статусы
        preparing_msg = None
        stop_event = asyncio.Event()
        progress_task = None
        stage_texts = [
            ctx.t("animate.preparing_stage1"),
            ctx.t("animate.preparing_stage2"),
            ctx.t("animate.preparing_stage3"),
        ]

        async def _progress_updates():
            nonlocal preparing_msg
            delays = [40, 40]  # сек между обновлениями
            dot_interval = 1.2

            def _with_dots(base: str, dots: int) -> str:
                if "..." in base:
                    return base.replace("...", "." * dots)
                return f"{base.rstrip('. ')}{'.' * dots}"

            try:
                loop = asyncio.get_event_loop()
                for idx, base_text in enumerate(stage_texts):
                    if stop_event.is_set():
                        return
                    dots = 3
                    rendered = _with_dots(base_text, dots)
                    if idx == 0:
                        try:
                            preparing_msg = await message.answer(rendered, parse_mode="HTML")
                        except Exception:
                            return
                    else:
                        try:
                            await preparing_msg.edit_text(rendered, parse_mode="HTML")
                        except Exception:
                            pass

                    stage_timeout = delays[idx] if idx < len(delays) else None
                    started = loop.time()

                    while True:
                        if stop_event.is_set():
                            return

                        if stage_timeout is not None:
                            elapsed = loop.time() - started
                            if elapsed >= stage_timeout:
                                break
                            timeout = min(dot_interval, max(stage_timeout - elapsed, 0))
                        else:
                            timeout = dot_interval

                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
                            return
                        except asyncio.TimeoutError:
                            pass

                        dots = (dots % 3) + 1
                        rendered = _with_dots(base_text, dots)
                        try:
                            await preparing_msg.edit_text(rendered, parse_mode="HTML")
                        except Exception:
                            pass

                if not stop_event.is_set():
                    await stop_event.wait()
            except Exception:
                pass

        try:
            progress_task = asyncio.create_task(_progress_updates())
        except Exception:
            pass

        def _is_progress_message(text: str | None) -> bool:
            if not text:
                return False
            normalized = text.replace(".", "")
            for base in stage_texts:
                base_norm = base.replace("...", "").replace(".", "")
                if base_norm.strip() and base_norm in normalized:
                    return True
            return False

        async def _stop_progress():
            stop_event.set()
            if progress_task:
                try:
                    await progress_task
                except Exception:
                    pass
            if preparing_msg:
                try:
                    if _is_progress_message(getattr(preparing_msg, "text", None)):
                        await bot.delete_message(chat_id=preparing_msg.chat.id, message_id=preparing_msg.message_id)
                except Exception:
                    pass

        try:
            photo_url = await _get_file_url(bot, ctx.state.animate_photo_file_id)
        except Exception:
            await _stop_progress()
            return ctx.reply("Не удалось получить фото, попробуйте снова.", self._actions(ctx), parse_mode="HTML")

        prompt_raw = ctx.state.animate_photo_prompt or ""

        def _sanitize_prompt(text: str) -> str:
            # вырезаем IPv4, чтобы не ловить блокировку "prompt not allowed because it contains IP"
            ipv4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
            return ipv4.sub("[ip]", text)

        prompt = _sanitize_prompt(prompt_raw[:500])
        aspect = ctx.state.video_format or "9:16"
        request_info = f"prompt={prompt[:120]} | aspect={aspect}"
        log_id = None
        try:
            async with async_session() as s:
                log_id = await UserRepo(s).start_generation(
                    telegram_id=ctx.user_id,
                    model="klingai",
                    request=request_info,
                    cost=None,
                    generation_type="animate_photo",
                )
                await s.commit()
        except Exception:
            log_id = None

        await bot.send_chat_action(ctx.user_id, "upload_video")

        client = None
        gen_token = None
        gen_status = "failed"
        delay_notice_task = None
        delay_notice_event = asyncio.Event()

        async def _delay_notice() -> None:
            try:
                await asyncio.wait_for(delay_notice_event.wait(), timeout=600)
            except asyncio.TimeoutError:
                try:
                    await bot.send_message(chat_id=ctx.user_id, text=ctx.t("animate.delay_notice"))
                except Exception:
                    pass
        try:
            client = KlingClient()
            gen_token = start_generation(ctx.user_id, "animate_photo", "klingai")
            gen = await client.create_video(
                prompt=prompt,
                image_url=photo_url,
                duration="5",
            )
            delay_notice_task = asyncio.create_task(_delay_notice())
            status = await client.poll_until_ready(gen.id, interval=5.0, attempts=360)
            if not status.video_url:
                raise KlingError("KlingAI не вернул ссылку на видео")
            video_bytes = await client.download_file(status.video_url)
            gen_status = "succeeded"
        except KlingError:
            return ctx.reply(ctx.t("animate.error_unavailable"), self._actions(ctx), parse_mode="HTML")
        except Exception:
            return ctx.reply("Не удалось собрать видео, попробуйте ещё раз.", self._actions(ctx), parse_mode="HTML")
        finally:
            delay_notice_event.set()
            if delay_notice_task:
                try:
                    await delay_notice_task
                except Exception:
                    pass
            if gen_token:
                finish_generation(gen_token)
            if log_id is not None:
                try:
                    async with async_session() as s:
                        await UserRepo(s).finish_generation(
                            generation_id=log_id,
                            status=gen_status,
                            cost=1 if gen_status == "succeeded" else 0,
                        )
                        await s.commit()
                except Exception:
                    pass
            await _stop_progress()
            if client:
                try:
                    await client.close()
                except Exception:
                    pass

        if gen_status == "succeeded":
            # списываем 1 генерацию
            try:
                async with async_session() as s:
                    await UserRepo(s).inc_balance(telegram_id=ctx.user_id, delta=-1, bucket="animate")
                    await s.commit()
                await ctx.ensure_snapshot(refresh=True)
            except Exception:
                pass

        filename = "result.mp4"

        def _target_size(aspect: str) -> Tuple[int, int]:
            if aspect == "16:9":
                return 960, 540
            if aspect == "1:1":
                return 540, 540
            return 540, 960  # 9:16

        def _add_silent_audio(data: bytes, out_ext: str = "mp4") -> bytes:
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as src, tempfile.NamedTemporaryFile(suffix=f".{out_ext}", delete=True) as dst:
                    src.write(data)
                    src.flush()
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i",
                        src.name,
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=44100",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-movflags",
                        "+faststart",
                        dst.name,
                    ]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if result.returncode != 0:
                        return data
                    dst.seek(0)
                    return dst.read()
            except Exception:
                return data

        def _force_aspect(data: bytes, aspect: str) -> bytes:
            try:
                w, h = _target_size(aspect)
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as src, tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as dst:
                    src.write(data)
                    src.flush()
                    vf = (
                        f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                        "setsar=1"
                    )
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i",
                        src.name,
                        "-vf",
                        vf,
                        "-metadata:s:v:0",
                        "rotate=0",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        dst.name,
                    ]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if result.returncode != 0:
                        return data
                    dst.seek(0)
                    return dst.read()
            except Exception:
                return data

        video_bytes_aspect = _force_aspect(video_bytes, aspect)
        video_bytes_mp4 = _add_silent_audio(video_bytes_aspect, out_ext="mp4")
        return {
            "video": video_bytes_mp4,
            "video_filename": filename,
            "video_caption": ctx.t("animate.ready_final"),
            "video_parse_mode": "HTML",
            "buttons": self._final_actions(ctx),
            "disable_preview": True,
        }
