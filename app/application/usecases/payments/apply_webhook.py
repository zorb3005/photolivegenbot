from __future__ import annotations

import httpx
import logging
from decimal import Decimal

from app.infrastructure.db.repositories.payment_repo import PaymentRepo
from app.infrastructure.db.repositories.user_repo import UserRepo
from app.bot.i18n import DEFAULT_LANG, translate
from app.bot.ui import ikb_rows
from app.settings import settings


class ApplyWebhook:
    """
    Обработчик вебхуков YooKassa.
    - обновляет статус платежа в БД;
    - при 'succeeded' начисляет токены пользователю
      (примерная формула, адаптирывать под свою экономику).
    - при 'canceled' присылает уведомление пользователю.
    """

    def __init__(self, session):
        self.session = session
        self.repo = PaymentRepo(session)
        self.log = logging.getLogger("webhooks.yookassa")

    async def __call__(self, event: dict) -> None:
        obj = event.get("object") or {}
        event_name = (event.get("event") or "").lower()

        # Отдельно обрабатываем вебхуки возврата
        if event_name.startswith("refund."):
            await self._handle_refund(obj)
            return

        pid = obj.get("id")
        status = obj.get("status")
        if not pid or not status:
            return

        before = await self.repo.get_by_payment_id(pid)

        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        if metadata is None:
            metadata = {}
        metadata["_test"] = bool(obj.get("test"))
        await self.repo.set_status(payment_id=pid, status=status, metadata=metadata)

        if status == "succeeded":
            payment = await self.repo.get_by_payment_id(pid)
            if not payment:
                return

            if before and before.status == "succeeded":
                return

            notify_tg: int | None = None
            meta = payment.metadata or {}
            notify_payload = None
            try:
                product = meta.get("product")
                urepo = UserRepo(self.session)

                if product == "clone":
                    await urepo.set_clone_unlimited(telegram_id=int(payment.user_id), value=True)
                else:
                    tokens = int(payment.amount_tokens or 0)
                    if tokens <= 0:
                        tokens = int(payment.rub_amount) * 10
                    bucket = meta.get("generation_type") or "animate"
                    if bucket != "animate":
                        bucket = "animate"
                    await urepo.inc_balance(telegram_id=int(payment.user_id), delta=tokens, bucket=bucket)
                    has_pending = bool(
                        meta.get("animate_photo_file_id") or meta.get("animate_photo_prompt")
                    )
                    if has_pending:
                        snap = await urepo.snapshot(telegram_id=int(payment.user_id))
                        balance = snap.get("animate_balance_tokens", 0)
                        prompt_raw = meta.get("animate_photo_prompt") or "Добавьте текст для анимации."
                        prompt = str(prompt_raw).replace("{", "{{").replace("}", "}}")
                        text = translate(DEFAULT_LANG, "paywall.animate_success", balance=balance, prompt=prompt)
                        buttons = ikb_rows(
                            [[
                                (translate(DEFAULT_LANG, "buttons.try_again"), "nav:flow.animate"),
                                (translate(DEFAULT_LANG, "buttons.run_generation"), "run:animate"),
                            ]]
                        )
                        notify_payload = {
                            "text": text,
                            "photo_id": meta.get("animate_photo_file_id"),
                            "parse_mode": "HTML",
                            "reply_markup": buttons.model_dump(),
                        }
                await urepo.set_segment(
                    telegram_id=int(payment.user_id),
                    segment="client",
                    allowed_from={"lead", "qual"},
                )
                notify_tg = int(payment.user_id)
            except Exception:
                notify_tg = None

            if notify_tg and notify_payload:
                await self._notify_with_payload(
                    notify_tg,
                    text=notify_payload["text"],
                    parse_mode=notify_payload["parse_mode"],
                    reply_markup=notify_payload["reply_markup"],
                    photo_id=notify_payload.get("photo_id"),
                )
            elif notify_tg:
                amount = self._format_amount(obj.get("amount"))
                text = (
                    "✅ Платёж подтверждён\n\n"
                    f"🆔 ID платежа: `{pid}`\n"
                )
                if amount:
                    text += f"💳 Сумма: {amount}\n"
                if meta.get("product") == "clone":
                    text += "\n🎉 Средства списаны, доступ к клону активирован."
                else:
                    text += "\n💰 Баланс пополнен."
                await self._notify(notify_tg, text)
        elif status == "canceled":
            # отправляем пользователю уведомление, но только если статус реально изменился
            if before and before.status == "canceled":
                return
            tg_id = (metadata or {}).get("user_id")
            if not tg_id and before:
                tg_id = before.user_id
            if tg_id:
                reason = ""
                cancel = obj.get("cancellation_details")
                if isinstance(cancel, dict):
                    r = cancel.get("reason") or cancel.get("party")
                    if r:
                        reason = str(r).replace("_", " ")
                await self._safe_notify_cancel(int(tg_id), pid, reason.strip())
        elif status == "waiting_for_capture":
            # Состояние «получен, но требует подтверждения» — уведомим пользователя
            tg_id = (metadata or {}).get("user_id")
            if not tg_id and before:
                tg_id = before.user_id
            if tg_id:
                amount = self._format_amount(obj.get("amount"))
                text = (
                    "⏳ Платёж получен, ожидает подтверждения.\n\n"
                    f"🆔 ID платежа: `{pid}`\n"
                )
                if amount:
                    text += f"💳 Сумма: {amount}\n\n"
                text += "Как только платёж подтвердится, вы получите уведомление."
                await self._notify(int(tg_id), text)

    async def _safe_notify_cancel(self, tg_id: int, payment_id: str, reason: str = ""):
        if not settings.BOT_TOKEN:
            self.log.warning("Skip cancel notify: BOT_TOKEN not configured")
            return
        text = (
            "❌ Платёж не удался\n\n"
            f"💳 ID платежа: `{payment_id}`\n"
        )
        if reason:
            text += f"⚠️ Причина: {reason}\n\n"
        else:
            text += "⚠️ Платёж отменён\n\n"
        text += "Попробуйте создать новый платёж или обратитесь в поддержку."

        await self._notify(tg_id, text)

    async def _notify(self, tg_id: int, text: str, *, parse_mode: str = "Markdown") -> None:
        if not settings.BOT_TOKEN:
            self.log.warning("Skip notify: BOT_TOKEN not configured")
            return
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
        # Позволяем работать с самоподписанными сертификатами/корневым CA,
        # чтобы уведомления не падали из-за MITM/корпоративного прокси.
        verify_target = settings.TELEGRAM_CA_BUNDLE or settings.TELEGRAM_VERIFY_SSL
        try:
            async with httpx.AsyncClient(timeout=10, verify=verify_target) as cli:
                resp = await cli.post(
                    url,
                    json={
                        "chat_id": tg_id,
                        "text": text,
                        "parse_mode": parse_mode,
                    },
                )
                if resp.status_code == 403:
                    await self._mark_banned(tg_id)
        except Exception as e:
            self.log.warning("Failed to send notify tg_id=%s err=%s", tg_id, e)

    async def _notify_with_payload(
        self,
        tg_id: int,
        *,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
        photo_id: str | None = None,
    ) -> None:
        if not settings.BOT_TOKEN:
            self.log.warning("Skip notify: BOT_TOKEN not configured")
            return
        verify_target = settings.TELEGRAM_CA_BUNDLE or settings.TELEGRAM_VERIFY_SSL
        try:
            async with httpx.AsyncClient(timeout=10, verify=verify_target) as cli:
                if photo_id:
                    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendPhoto"
                    payload = {
                        "chat_id": tg_id,
                        "photo": photo_id,
                        "caption": text,
                        "parse_mode": parse_mode,
                    }
                    if reply_markup:
                        payload["reply_markup"] = reply_markup
                    resp = await cli.post(url, json=payload)
                    if resp.status_code == 200:
                        return
                url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
                payload = {
                    "chat_id": tg_id,
                    "text": text,
                    "parse_mode": parse_mode,
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                resp = await cli.post(url, json=payload)
                if resp.status_code == 403:
                    await self._mark_banned(tg_id)
        except Exception as e:
            self.log.warning("Failed to send notify tg_id=%s err=%s", tg_id, e)

    def _format_amount(self, amount: dict | None) -> str | None:
        if not amount or not isinstance(amount, dict):
            return None
        value = amount.get("value")
        currency = amount.get("currency") or "RUB"
        try:
            dec = Decimal(str(value))
            return f"{dec.quantize(Decimal('0.01'))} {currency}"
        except Exception:
            return None

    async def _handle_refund(self, refund_obj: dict) -> None:
        """
        Уведомляем о успешном возврате средств.
        """
        payment_id = refund_obj.get("payment_id")
        status = refund_obj.get("status")
        if status != "succeeded" or not payment_id:
            return

        payment = await self.repo.get_by_payment_id(payment_id)
        if not payment:
            return

        tg_id = payment.user_id
        amount = self._format_amount(refund_obj.get("amount"))
        text = (
            "↩️ Возврат средств выполнен\n\n"
            f"🆔 ID платежа: `{payment_id}`\n"
        )
        if amount:
            text += f"💸 Сумма возврата: {amount}\n\n"
        text += "Если возврат инициирован вами, средства скоро поступят на счёт."
        await self._notify(int(tg_id), text)

    async def _mark_banned(self, tg_id: int) -> None:
        try:
            urepo = UserRepo(self.session)
            await urepo.set_segment(telegram_id=int(tg_id), segment="ban")
        except Exception:
            pass
