from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.infrastructure.db.base import async_session
from app.infrastructure.db.repositories.user_repo import UserRepo


@dataclass
class State:
    # текущее «окно» бота
    current_page: str = "start"
    # показывали ли экран запуска (картинка «На главную»)
    start_screen_shown: bool = False

    # базовые настройки
    lang: str | None = None
    email: str | None = None

    # сценарий «Живое фото»
    animate_photo_file_id: str | None = None
    animate_photo_prompt: str | None = None
    animate_last_message: Any | None = None
    animate_hint_message_id: int | None = None
    share_video_file_id: str | None = None
    share_video_caption: str | None = None
    share_video_parse_mode: str | None = None
    video_format: str = "9:16"
    format_back: str | None = None

    # одноразовые сообщения перед текстом страницы
    flashes: List[str] = field(default_factory=list)
    # временные данные для оформления платежа (ожидание email)
    pending_payment: Dict[str, Any] | None = None
    pending_payment_back: str | None = None

    # админский режим начисления генераций
    admin_paypfoto_user_id: int | None = None


class BotContext:
    """
    Контекст на время обработки одного апдейта.

    - `user_id` — Telegram ID пользователя
    - `state` — храним текущее «окно», выборы и т.д.
    - `snapshot` — лениво подгружаемые данные пользователя из БД
      (баланс, кол-во друзей, user_id). Вызвать `await ensure_snapshot()`
      до использования.
    """

    def __init__(self, user_id: int, state: State):
        self.user_id = user_id
        self.state = state
        self._user_snapshot: Optional[Dict[str, Any]] = None

    # ---------- Вспомогательные структуры ----------

    class _SnapshotDict(dict):
        """
        Safe dict for string formatting: пропускает неизвестные плейсхолдеры.
        """

        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    # ---------- UI-утилиты ----------

    def reply(
        self,
        text: str,
        buttons,
        *,
        parse_mode: str | None = None,
        photo: str | None = None,
        disable_preview: bool = False,
    ) -> Dict[str, Any]:
        """
        Возвращает словарь для роутера/раннера:
        {"text": "...", "buttons": <Reply/InlineKeyboard>}
        + предварительно выводит накопленные flashes.
        """
        if self.state.flashes:
            prefix = "\n".join(self.state.flashes) + "\n\n"
            self.state.flashes.clear()
            text = prefix + text
        snap = self._user_snapshot or {}
        text = text.format_map(self._SnapshotDict(snap))
        view = {"text": text, "buttons": buttons}
        if parse_mode:
            view["parse_mode"] = parse_mode
        if photo:
            view["photo"] = photo
        if disable_preview:
            view["disable_preview"] = True
        return view

    # ---------- I18N ----------

    @property
    def lang(self) -> str:
        from app.bot.i18n import DEFAULT_LANG

        return self.state.lang or DEFAULT_LANG

    def set_lang(self, code: str) -> None:
        self.state.lang = code

    def t(self, key: str, **kwargs) -> str:
        from app.bot.i18n import translate

        return translate(self.lang, key, **kwargs)

    def flash(self, text: str) -> None:
        """
        Добавляет одноразовое сообщение (экранируя фигурные скобки).
        """
        safe = (text or "").replace("{", "{{").replace("}", "}}")
        self.state.flashes.append(safe)

    # ---------- Пользовательский снапшот ----------

    @property
    def snapshot(self) -> Dict[str, Any]:
        """
        Быстрый доступ к кэшу пользовательских данных.
        Перед использованием вызови `await ensure_snapshot()`.
        """
        if self._user_snapshot is None:
            raise RuntimeError("Call await ctx.ensure_snapshot() before using ctx.snapshot")
        return self._user_snapshot

    async def ensure_snapshot(self, *, refresh: bool = False) -> Dict[str, Any]:
        """
        Лениво подтягивает (и кэширует на время апдейта) данные пользователя из БД.
        Гарантирует, что юзер существует в таблице users (создаст при первом обращении).
        Возвращает dict с балансами: animate_balance_tokens и legacy balance_tokens.
        """
        if refresh or self._user_snapshot is None:
            async with async_session() as s:
                repo = UserRepo(s)
                snap = await repo.snapshot(telegram_id=self.user_id)
                self._user_snapshot = snap
                # Синхронизируем email из БД (включая очистку, если его убрали)
                if "email" in snap:
                    self.state.email = snap.get("email")
        return self._user_snapshot
