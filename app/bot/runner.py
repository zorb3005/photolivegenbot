from __future__ import annotations

import asyncio
import os
import zlib
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineQuery,
    InlineQueryResultCachedVideo,
    BufferedInputFile,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from dotenv import load_dotenv
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.bot.context import BotContext, State
from app.bot.admin.dashboard import fetch_admin_stats, render_stats_message
from app.bot.admin.live_metrics import touch_user_activity
from app.bot.router import route, PAGE_INDEX
from app.bot.account.topup import topup_callbacks
from app.infrastructure.db.base import async_session, engine
from app.infrastructure.db.repositories.user_repo import UserRepo
from app.settings import settings

SKIP_RENDER = "__skip_render__"

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

dp = Dispatcher()
user_states: dict[int, State] = {}

def _bot_lock_key() -> int:
    token = BOT_TOKEN or settings.BOT_TOKEN or ""
    seed = f"live-photo-bot:{token}"
    return zlib.crc32(seed.encode())

async def _acquire_bot_lock() -> AsyncConnection | None:
    conn: AsyncConnection | None = None
    try:
        conn = await engine.connect()
        res = await conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _bot_lock_key()})
        if res.scalar():
            return conn
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to acquire bot lock: %s", exc)
    if conn:
        await conn.close()
    return None

async def _release_bot_lock(conn: AsyncConnection) -> None:
    try:
        await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _bot_lock_key()})
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to release bot lock: %s", exc)
    finally:
        await conn.close()

def _is_admin(user_id: int) -> bool:
    admin_ids = settings.ADMIN_IDS or settings.HARDCODED_ADMIN_IDS
    return bool(admin_ids) and int(user_id) in admin_ids

def _is_hard_admin(user_id: int) -> bool:
    admin_ids = settings.HARDCODED_ADMIN_IDS
    return bool(admin_ids) and int(user_id) in admin_ids


def _touch_user(user_id: int | None) -> None:
    try:
        touch_user_activity(user_id)
    except Exception:
        pass

async def _ensure_user(
    user_id: int,
    username: str | None = None,
    *,
    invited_by: int | None = None,
    source_key: str | None = None,
    source_value: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> None:
    async with async_session() as s:
        repo = UserRepo(s)
        inviter_telegram_id = None
        inviter_internal_id = None
        if invited_by:
            inviter = await repo.get_by_internal_id(invited_by)
            if inviter and inviter.telegram_id != user_id:
                inviter_telegram_id = inviter.telegram_id
                inviter_internal_id = inviter.internal_id

        await repo.get_or_create(
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            invited_by=inviter_telegram_id,
            referred_id=inviter_internal_id,
            segment="lead",
            return_created=True,
        )
        if source_key or source_value:
            await repo.record_source(
                telegram_id=user_id,
                source_key=source_key,
                source_value=source_value,
            )
        await s.commit()

async def _mark_ban(user_id: int) -> None:
    async with async_session() as s:
        repo = UserRepo(s)
        await repo.set_segment(telegram_id=user_id, segment="ban")
        await s.commit()

def _parse_start_payload(text: str | None) -> tuple[int | None, str | None, str | None]:
    if not text:
        return None, None, None
    payload = ""
    if " " in text:
        payload = text.split(" ", 1)[1].strip()
    elif text.startswith("/start="):
        payload = text.split("/start=", 1)[1].strip()
    elif text.startswith("/start"):
        payload = text[len("/start"):].lstrip(" =")
    else:
        payload = text.strip()

    if not payload:
        return None, None, None

    normalized = payload.replace("\n", " ").strip().lstrip("=")
    normalized = normalized.replace("-", "_")

    parts = [p for p in normalized.split("_") if p]
    if not parts:
        return None, None, None

    ref_id = None
    source_key = None
    source_value = None

    start_idx = 0
    first = parts[0]
    if first == "ref" and len(parts) >= 2:
        # payload вида ref_<id>_source
        try:
            ref_id = int(parts[1])
        except ValueError:
            ref_id = None
        start_idx = 2
    elif first.startswith("ref"):
        # payload вида ref123 или ref123_source
        ref_val = first[3:]
        try:
            ref_id = int(ref_val)
        except ValueError:
            ref_id = None
        start_idx = 1

    if start_idx < len(parts):
        source_key = parts[start_idx]
        if start_idx + 1 < len(parts):
            source_value = "_".join(parts[start_idx + 1 :])

    return ref_id, source_key, source_value


def ctx_for(m: Message) -> BotContext:
    st = user_states.setdefault(m.from_user.id, State())
    return BotContext(user_id=m.from_user.id, state=st)


def _menu_shortcut(ctx: BotContext, text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    mapping = {
        ctx.t("buttons.animate_photo"): "flow.animate",
        ctx.t("buttons.cabinet"): "account.cabinet",
        ctx.t("buttons.topup"): "account.topup",
        ctx.t("buttons.referral"): "account.referral",
        ctx.t("buttons.our_bots"): "our_bots",
        ctx.t("buttons.support"): "support",
    }
    for label, slug in mapping.items():
        if text == label:
            return slug
    low = text.lower()
    if "кабинет" in low or "личн" in low:
        return "account.cabinet"
    if "ожив" in low or "фото" in low:
        return "flow.animate"
    if "оплат" in low or "попол" in low or "баланс" in low:
        return "account.topup"
    if "поддерж" in low:
        return "support"
    if "бот" in low:
        return "our_bots"
    if "друг" in low or "рефера" in low:
        return "account.referral"
    return None


async def send_view(msg: Message | CallbackQuery, view: dict):
    text = view.get("text")
    buttons = view.get("buttons")  # reply keyboard
    inline_buttons = view.get("inline_buttons") or view.get("photo_buttons")
    buttons_placeholder = view.get("buttons_placeholder")
    parse_mode = view.get("parse_mode")
    photo_path = view.get("photo")
    disable_preview = bool(view.get("disable_preview"))
    video_caption = view.get("video_caption")
    video_parse_mode = view.get("video_parse_mode") or parse_mode
    use_video_caption = bool(view.get("video") and video_caption)
    if use_video_caption:
        # Не отправляем отдельное текстовое сообщение, используем caption у видео
        text = None
    photo_sent = False

    target = None
    if isinstance(msg, CallbackQuery):
        target = msg.message
    else:
        target = msg

    reply_kb = isinstance(buttons, ReplyKeyboardMarkup)
    user_id = None
    try:
        if hasattr(msg, "from_user") and getattr(msg, "from_user"):
            user_id = getattr(msg, "from_user").id
        elif hasattr(msg, "message") and getattr(msg, "message"):
            user = getattr(msg.message, "from_user", None)
            user_id = getattr(user, "id", None)
    except Exception:
        user_id = None

    async def _send_text():
        if parse_mode:
            await target.answer(
                text,
                reply_markup=buttons,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_preview,
            )
        else:
            await target.answer(text, reply_markup=buttons, disable_web_page_preview=disable_preview)

    async def _send_photo(path: str, caption: str | None = None, include_markup: bool = False, buttons=None):
        try:
            data = Path(path).read_bytes()
        except Exception:
            return

        def _reply_markup():
            if include_markup:
                return buttons
            return None

        if isinstance(msg, CallbackQuery):
            file = BufferedInputFile(data, filename=Path(path).name)
            media = InputMediaPhoto(media=file, caption=caption, parse_mode=parse_mode)
            kwargs: dict[str, object] = {}
            markup = _reply_markup()
            if markup is not None:
                kwargs["reply_markup"] = markup
            try:
                await target.edit_media(media, **kwargs)
            except TelegramBadRequest:
                # если не можем отредактировать (например, исходное сообщение без фото), отправляем новое и удаляем старое
                file = BufferedInputFile(data, filename=Path(path).name)
                sent = await target.answer_photo(
                    file,
                    caption=caption,
                    parse_mode=parse_mode,
                    reply_markup=_reply_markup(),
                )
                try:
                    await target.delete()
                except TelegramBadRequest:
                    pass
                return sent
        else:
            file = BufferedInputFile(data, filename=Path(path).name)
            await target.answer_photo(
                file,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=_reply_markup(),
            )

    try:
        if photo_path:
            caption = text
            include_markup = text is not None
            if isinstance(msg, CallbackQuery) and reply_kb:
                try:
                    data = Path(photo_path).read_bytes()
                    file = BufferedInputFile(data, filename=Path(photo_path).name)
                    await target.answer_photo(file, caption=caption, parse_mode=parse_mode, reply_markup=buttons)
                    photo_sent = True
                    text = None
                    return
                except Exception:
                    photo_sent = False
            try:
                await _send_photo(photo_path, caption=caption, include_markup=include_markup, buttons=inline_buttons or buttons)
                photo_sent = True
                if text is not None:
                    text = None
            except Exception:
                # если фото не ушло, продолжим и хотя бы отправим текст
                photo_sent = False

        if text is not None:
            if isinstance(msg, CallbackQuery):
                if reply_kb:
                    await target.answer(text, reply_markup=buttons, parse_mode=parse_mode)
                    return
                try:
                    await target.edit_text(
                        text,
                        reply_markup=buttons,
                        parse_mode=parse_mode,
                        disable_web_page_preview=disable_preview,
                    )
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        await _send_text()
            else:
                await _send_text()

        audio = view.get("audio")
        if audio:
            filename = view.get("audio_filename", "speech.mp3")
            file = BufferedInputFile(audio, filename=filename)
            if isinstance(msg, CallbackQuery):
                await target.answer_audio(file)
            else:
                await target.answer_audio(file)

        video = view.get("video")
        video_as_document = bool(view.get("video_as_document"))
        if video:
            filename = view.get("video_filename", "video.mp4")
            resp = None
            async def _send_video(as_document: bool):
                file = BufferedInputFile(video, filename=filename)
                if as_document:
                    return await target.answer_document(
                        file,
                        caption=video_caption if use_video_caption else None,
                        parse_mode=video_parse_mode if use_video_caption else None,
                        reply_markup=buttons,
                    )
                return await target.answer_video(
                    file,
                    caption=video_caption if use_video_caption else None,
                    parse_mode=video_parse_mode if use_video_caption else None,
                    reply_markup=buttons,
                )

            try:
                resp = await _send_video(video_as_document)
            except TelegramBadRequest as exc:
                if not video_as_document:
                    try:
                        resp = await _send_video(True)
                    except TelegramBadRequest as exc2:
                        logging.warning("Failed to send video for user %s: %s", user_id, exc2)
                        if text is None:
                            await target.answer("Не удалось отправить видео. Попробуйте ещё раз чуть позже.")
                        return
                else:
                    logging.warning("Failed to send video for user %s: %s", user_id, exc)
                    if text is None:
                        await target.answer("Не удалось отправить видео. Попробуйте ещё раз чуть позже.")
                    return
            # сохраним file_id и при необходимости обновим кнопку "Поделиться"
            try:
                if user_id and resp and getattr(resp, "video", None):
                    st = user_states.get(int(user_id))
                    if st:
                        st.share_video_file_id = resp.video.file_id
                        st.share_video_caption = video_caption if use_video_caption else None
                        st.share_video_parse_mode = video_parse_mode if use_video_caption else None
                    # Если была inline-кнопка share, обновим её, чтобы она содержала file_id
                    if resp.reply_markup and isinstance(resp.reply_markup, InlineKeyboardMarkup):
                        new_keyboard = []
                        updated = False
                        for row in resp.reply_markup.inline_keyboard:
                            new_row = []
                            for btn in row:
                                if isinstance(btn, InlineKeyboardButton) and (
                                    btn.switch_inline_query is not None
                                    or btn.switch_inline_query_current_chat is not None
                                ):
                                    new_row.append(
                                        InlineKeyboardButton(
                                            text=btn.text,
                                            switch_inline_query=f"share:{resp.video.file_id}",
                                        )
                                    )
                                    updated = True
                                else:
                                    new_row.append(btn)
                            new_keyboard.append(new_row)
                        if updated:
                            try:
                                await target.bot.edit_message_reply_markup(
                                    chat_id=resp.chat.id,
                                    message_id=resp.message_id,
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard),
                                )
                            except TelegramBadRequest:
                                pass
            except Exception:
                pass
    except TelegramForbiddenError:
        if user_id:
            try:
                await _mark_ban(int(user_id))
            except Exception:
                pass


@dp.message(CommandStart())
async def start(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    ref_id, source_key, source_value = _parse_start_payload(m.text)

    await _ensure_user(
        m.from_user.id,
        m.from_user.username,
        invited_by=ref_id,
        source_key=source_key,
        source_value=source_value,
        first_name=getattr(m.from_user, "first_name", None),
        last_name=getattr(m.from_user, "last_name", None),
    )

    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "start"

    ctx = ctx_for(m)
    # Для явного /start сразу отдаём стартовый экран с обложкой
    start_page = PAGE_INDEX["start"]
    view = await start_page.render(ctx)
    await send_view(m, view)

@dp.message(Command("photo"))
async def photo_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    await _ensure_user(m.from_user.id, m.from_user.username)
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "flow.animate"
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(Command("balance"))
async def balance_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    await _ensure_user(m.from_user.id, m.from_user.username)
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "account.cabinet"
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(Command("payment"))
async def payment_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    await _ensure_user(m.from_user.id, m.from_user.username)
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "account.topup"
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(Command("cabinet"))
async def cabinet_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    await _ensure_user(m.from_user.id, m.from_user.username)
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "account.cabinet"
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(Command("pay"))
async def pay_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    await _ensure_user(m.from_user.id, m.from_user.username)
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "account.topup"
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(Command("help"))
async def help_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    await _ensure_user(m.from_user.id, m.from_user.username)
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "support"
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(Command("support"))
async def support_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    await _ensure_user(m.from_user.id, m.from_user.username)
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "support"
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    if not _is_admin(m.from_user.id):
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="Закрыть", callback_data="admin:close")],
        ]
    )
    await m.answer("Выберите действие:", reply_markup=kb)

@dp.message(Command("paypfoto"))
async def paypfoto_cmd(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    if not _is_hard_admin(m.from_user.id):
        return
    st = user_states.setdefault(m.from_user.id, State())
    st.current_page = "admin.paypfoto"
    st.admin_paypfoto_user_id = None
    ctx = ctx_for(m)
    view = await route(ctx, "")
    await send_view(m, view)

@dp.message(F.text)
async def on_text(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    ctx = ctx_for(m)
    # Игнорируем любые команды (aiogram Command-хендлеры уже их обрабатывают), чтобы не озвучивать слэш-текст
    if m.text and m.text.strip().startswith("/"):
        return
    shortcut = _menu_shortcut(ctx, m.text)
    if shortcut:
        ctx.state.current_page = shortcut
        view = await route(ctx, "")
        await send_view(m, view)
        return
    view = await route(ctx, m.text or "")
    await send_view(m, view)

@dp.message(F.photo)
async def on_photo(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    ctx = ctx_for(m)
    page = PAGE_INDEX.get(ctx.state.current_page, PAGE_INDEX["start"])
    if hasattr(page, "handle_photo"):
        result = await page.handle_photo(ctx, m)
        if isinstance(result, dict):
            await send_view(m, result)
            return
        if result == SKIP_RENDER:
            return
        if result:
            ctx.state.current_page = result
        view = await route(ctx, "")
        await send_view(m, view)
        return
    await m.answer("Сейчас я ожидаю сообщение или выберите действие на стартовом экране.")


@dp.message(F.voice | F.audio)
async def on_voice(m: Message):
    _touch_user(getattr(m.from_user, "id", None))
    ctx = ctx_for(m)
    page = PAGE_INDEX.get(ctx.state.current_page, PAGE_INDEX["start"])
    if hasattr(page, "handle_voice"):
        result = await page.handle_voice(ctx, m)
        if isinstance(result, dict):
            await send_view(m, result)
            return
        if result:
            ctx.state.current_page = result
        view = await route(ctx, "")
        await send_view(m, view)
        return
    await m.answer("Отправьте фото или выберите действие на стартовом экране.")

@dp.callback_query(F.data.startswith("nav:"))
async def nav_cb(q: CallbackQuery):
    _touch_user(getattr(q.from_user, "id", None))
    try:
        await q.answer()
    except Exception:
        pass
    st = user_states.setdefault(q.from_user.id, State())
    ctx = BotContext(user_id=q.from_user.id, state=st)
    await ctx.ensure_snapshot()
    origin = st.current_page
    target = q.data.split("nav:", 1)[1]
    if target == "format.select":
        st.format_back = origin if origin != "format.select" else st.format_back
    ctx.state.current_page = target if target in PAGE_INDEX else "start"
    view = await route(ctx, "")
    await send_view(q, view)


@dp.callback_query(~F.data.startswith("check_payment:") & ~F.data.startswith("nav:"))
async def on_cb(q: CallbackQuery):
    _touch_user(getattr(q.from_user, "id", None))
    try:
        await q.answer()
    except Exception:
        pass
    if q.data and q.data.startswith("admin:"):
        if not _is_admin(q.from_user.id):
            return
        action = q.data.split("admin:", 1)[1]
        if action == "stats":
            try:
                stats = await fetch_admin_stats()
                text = render_stats_message(stats)
            except Exception as exc:  # noqa: BLE001
                logging.warning("Failed to fetch admin stats: %s", exc)
                text = "Не удалось загрузить статистику, попробуйте позже."
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")],
                    [InlineKeyboardButton(text="Закрыть", callback_data="admin:close")],
                ]
            )
            try:
                await q.message.edit_text(text, reply_markup=kb)
            except TelegramBadRequest:
                await q.message.answer(text, reply_markup=kb)
            await q.answer()
            return
        if action in {"menu", "back"}:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
                    [InlineKeyboardButton(text="Закрыть", callback_data="admin:close")],
                ]
            )
            try:
                await q.message.edit_text("Выберите действие:", reply_markup=kb)
            except TelegramBadRequest:
                await q.message.answer("Выберите действие:", reply_markup=kb)
            await q.answer()
            return
        if action == "close":
            try:
                await q.message.delete()
            except TelegramBadRequest:
                try:
                    await q.message.edit_reply_markup(None)
                except TelegramBadRequest:
                    pass
            await q.answer()
            return

    st = user_states.setdefault(q.from_user.id, State())
    ctx = BotContext(user_id=q.from_user.id, state=st)
    await ctx.ensure_snapshot()
    page = PAGE_INDEX.get(ctx.state.current_page, PAGE_INDEX["start"])

    if hasattr(page, "on_callback"):
        result = await page.on_callback(ctx, q)
        if isinstance(result, dict):
            await send_view(q, result)
            return
        if result:
            ctx.state.current_page = result
        render_page = PAGE_INDEX[ctx.state.current_page]
        await ctx.ensure_snapshot(refresh=True)
        view = await render_page.render(ctx)
        try:
            await send_view(q, view)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        return

    try:
        await q.answer("Действие недоступно", show_alert=False)
    except TelegramBadRequest:
        pass


@dp.inline_query()
async def inline_share(query: InlineQuery):
    _touch_user(getattr(query.from_user, "id", None))
    st = user_states.get(query.from_user.id)
    file_id = None
    caption = None
    parse_mode = None
    q = query.query or ""
    if q.startswith("share:"):
        file_id = q.split("share:", 1)[1].strip()
    if not file_id and st:
        file_id = st.share_video_file_id
        caption = st.share_video_caption
        parse_mode = st.share_video_parse_mode
    if not file_id:
        await query.answer([], cache_time=1, is_personal=True)
        return
    results = [
        InlineQueryResultCachedVideo(
            id="share-video",
            video_file_id=file_id,
            title="Поделиться видео",
            description="Отправить готовый ролик",
            caption=caption,
            parse_mode=parse_mode,
        )
    ]
    await query.answer(results, cache_time=1, is_personal=True)

logging.basicConfig(level=logging.INFO)

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    bot = Bot(BOT_TOKEN)
    lock_conn = await _acquire_bot_lock()
    if not lock_conn:
        logging.error("Another bot instance is already running. Exiting to avoid getUpdates conflict.")
        await bot.session.close()
        return
    # очищаем глобальное меню команд, чтобы скрыть подсказки /start, /photo и т.д.
    try:
        await bot.delete_my_commands()
    except Exception:
        pass

    asyncio.create_task(_payment_status_watcher(bot))

    await topup_callbacks(dp, user_states)

    try:
        await dp.start_polling(bot, handle_as_tasks=True)
    finally:
        await _release_bot_lock(lock_conn)
        # Корректно закрываем HTTP-сессию бота при остановке, чтобы избежать утечек
        await bot.session.close()

async def _payment_status_watcher(bot: Bot) -> None:
    """
    Фоновый воркер: берёт платежи в статусах pending/waiting_for_capture, проверяет их в YooKassa
    и при смене статуса триггерит ApplyWebhook, чтобы отправить уведомление.
    """
    import httpx
    from app.infrastructure.providers.payments.base import PaymentProvider
    from app.infrastructure.db.repositories.payment_repo import PaymentRepo
    from app.application.usecases.payments.apply_webhook import ApplyWebhook

    prov = None
    try:
        prov = PaymentProvider()
    except Exception as exc:  # noqa: BLE001
        logging.warning("payment_status_watcher disabled: payment provider init failed: %s", exc)
        return

    while True:
        try:
            async with async_session() as s:
                repo = PaymentRepo(s)
                pending = await repo.list_by_statuses(["pending", "waiting_for_capture"], limit=100)
                if not pending:
                    await asyncio.sleep(15)
                    continue

                for p in pending:
                    if not p.payment_id:
                        continue
                    try:
                        data = await prov.fetch_payment(p.payment_id)
                    except httpx.HTTPStatusError as exc:
                        if exc.response is not None and exc.response.status_code == 404:
                            # Платёж не существует (скорее всего старый id из другой витрины) — не спамим warn
                            logging.info("payment_status_watcher: skip unknown pid=%s (404)", p.payment_id)
                        else:
                            logging.warning("payment_status_watcher: fetch failed pid=%s err=%s", p.payment_id, exc)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        logging.warning("payment_status_watcher: fetch failed pid=%s err=%s", p.payment_id, exc)
                        continue

                    status = (data or {}).get("status")
                    if not status or status == p.status:
                        continue

                    event = {"event": f"payment.{status}", "object": data}
                    try:
                        await ApplyWebhook(s)(event)
                        await s.commit()
                    except Exception as exc:  # noqa: BLE001
                        logging.warning("payment_status_watcher: ApplyWebhook failed pid=%s err=%s", p.payment_id, exc)
                await asyncio.sleep(5)
        except Exception as exc:  # noqa: BLE001
            logging.warning("payment_status_watcher error: %s", exc)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
