from __future__ import annotations

from aiogram.types import CallbackQuery
from datetime import datetime, timedelta

from app.bot.ui import ikb_rows
from app.bot.account.email_prompt import EmailForReceipt
from app.bot.context import BotContext, State
from app.settings import settings


class TopUp:
    slug = "account.topup"

    PACKAGES = [
        ("1", "✨ Купить 1 генерацию — 250 ₽", 250, 1),
        ("3", "Купить 3 + 1 фото 🎁 — 699 ₽", 699, 4),
        ("5", "Купить 5 + 2 фото 🎁 — 999 ₽", 999, 7),
        ("20", "Купить 20 + 5 фото 🎁 — 3499 ₽", 3499, 25),
    ]
    ANIMATE_PACKAGES = [
        ("1", "✨ Оживить 1 фото — 250 ₽", 250, 1),
        ("3", "Купить 3 + 1 фото 🎁 — 699 ₽", 699, 4),
        ("5", "Купить 5 + 2 фото 🎁 — 999 ₽", 999, 7),
        ("20", "Купить 20 + 5 фото 🎁 — 3499 ₽", 3499, 25),
    ]

    @classmethod
    def _packages_by_prefix(cls, prefix: str):
        if prefix == "topup_animate":
            return cls.ANIMATE_PACKAGES
        return cls.PACKAGES

    async def render(self, ctx):
        snap = await ctx.ensure_snapshot()
        rows = [[(title, f"topup:{key}")] for key, title, _, _ in self.PACKAGES]
        rows.append([(ctx.t("buttons.back"), "nav:account.cabinet")])
        return ctx.reply(
            ctx.t("topup.prompt", balance=snap.get("animate_balance_tokens", 0)),
            ikb_rows(rows),
            parse_mode="HTML",
        )

    async def handle(self, ctx, m: str):
        choice = (m or "").strip()
        low = choice.lower()

        if choice == ctx.t("buttons.back") or "назад" in low:
            return "account.cabinet"

        for key, title, rub, tokens in self.PACKAGES:
            if key in low or title.lower() in low:
                return await self._create_invoice(
                    ctx,
                    plan_key=key,
                    title=title,
                    rub=rub,
                    tokens=tokens,
                    bucket="animate",
                    attach_animate_context=False,
                )

        return self.slug

    async def on_callback(self, ctx, query: CallbackQuery):
        data = query.data or ""
        if data.startswith(("topup:", "topup_animate:")):
            prefix, key = data.split(":", 1)
            packages = self._packages_by_prefix(prefix)
            bucket = "animate"
            attach_animate_context = prefix == "topup_animate"
            for pkg_key, title, rub, tokens in packages:
                if key == pkg_key:
                    await query.answer()
                    return await self._create_invoice(
                        ctx,
                        plan_key=pkg_key,
                        title=title,
                        rub=rub,
                        tokens=tokens,
                        bucket=bucket,
                        attach_animate_context=attach_animate_context,
                    )
        return None

    async def _create_invoice(
        self,
        ctx,
        *,
        plan_key: str,
        title: str,
        rub: int,
        tokens: int,
        bucket: str | None = None,
        attach_animate_context: bool = False,
    ):
        email = ctx.state.email or (ctx.snapshot.get("email"))
        metadata = {"generation_type": bucket} if bucket else None
        if attach_animate_context and bucket == "animate":
            metadata = metadata or {}
            photo_id = ctx.state.animate_photo_file_id
            prompt_raw = (ctx.state.animate_photo_prompt or "").strip()
            if photo_id:
                metadata["animate_photo_file_id"] = photo_id
            if prompt_raw:
                metadata["animate_photo_prompt"] = prompt_raw[:500]
        payload = {
            "amount_tokens": tokens,
            "rub_amount": rub,
            "description": title,
            "return_url": f"{settings.BASE_URL.rstrip('/')}/payments/return",
            "metadata": metadata,
            "kind": "topup",
            "remember_payment": True,
            "back_to": "account.cabinet",
            "plan_title": title,
            "package_key": plan_key,
        }
        # Если пользователь оплачивает в сценарии оживления — даём бонус +1 генерацию при оплате в течение 30 минут.
        if bucket == "animate":
            deadline = datetime.utcnow() + timedelta(minutes=30)
            bonus_meta = {
                "bonus_if_paid_before": deadline.isoformat(),
                "bonus_bucket": bucket,
                "bonus_tokens": 1,
            }
            payload["metadata"] = {**(metadata or {}), **bonus_meta}
        else:
            payload["metadata"] = metadata

        if not email:
            ctx.state.pending_payment = payload
            return EmailForReceipt.prompt(ctx, back_to=payload["back_to"])

        return await EmailForReceipt.finalize_now(ctx, payload=payload, email=email)


# ===== Регистрация callback-хэндлеров для пополнения =====

async def topup_callbacks(dp, state_storage):
    """
    Регистрируем обработчики callback_data:
      - open_url:<http-url>  -> показываем ссылочную кнопку
      - check_payment:<pid>  -> проверка статуса в YooKassa и синхронизация с БД
    """
    from aiogram import F
    from app.bot.admin.live_metrics import touch_user_activity
    from app.infrastructure.providers.payments.base import PaymentProvider
    from app.infrastructure.db.repositories.payment_repo import PaymentRepo
    from app.infrastructure.db.base import async_session

    @dp.callback_query(F.data.startswith("check_payment:"))
    async def _check(cq: CallbackQuery):
        touch_user_activity(getattr(cq.from_user, "id", None))
        pid = cq.data.split("check_payment:", 1)[1]

        # живой статус из YooKassa + обновим БД
        prov = PaymentProvider()
        try:
            data = await prov.fetch_payment(pid)
        except Exception as exc:
            await cq.message.answer(f"Не удалось получить статус платежа, попробуйте позже.\nОшибка: {exc}", parse_mode="Markdown")
            await cq.answer()
            return

        status = data.get("status", "pending")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if metadata is None:
            metadata = {}
        metadata["_test"] = bool(data.get("test"))

        success_meta: dict | None = None
        async with async_session() as s:
            repo = PaymentRepo(s)
            before = await repo.get_by_payment_id(pid)
            await repo.set_status(payment_id=pid, status=status, metadata=metadata)

            if status == "succeeded":
                payment = await repo.get_by_payment_id(pid)
                if payment and (before is None or before.status != "succeeded"):
                    meta = payment.metadata or {}
                    success_meta = meta
                    product = meta.get("product")

                    from app.infrastructure.db.repositories.user_repo import UserRepo

                    now = datetime.utcnow()
                    bonus_tokens = 0
                    bonus_bucket = meta.get("bonus_bucket")
                    bonus_deadline_raw = meta.get("bonus_if_paid_before")
                    try:
                        if bonus_deadline_raw:
                            bonus_deadline = datetime.fromisoformat(str(bonus_deadline_raw))
                            if now <= bonus_deadline:
                                bonus_tokens = int(meta.get("bonus_tokens", 1))
                    except Exception:
                        bonus_tokens = 0

                    tokens = int(payment.amount_tokens or 0)
                    if tokens <= 0:
                        tokens = int(payment.rub_amount) * 10
                    bucket = meta.get("generation_type") or "animate"
                    if bucket != "animate":
                        bucket = "animate"
                    await UserRepo(s).inc_balance(telegram_id=int(payment.user_id), delta=tokens, bucket=bucket)
                    if bonus_tokens > 0:
                        await UserRepo(s).inc_balance(
                            telegram_id=int(payment.user_id),
                            delta=bonus_tokens,
                            bucket=bonus_bucket or bucket,
                        )
                    # Реферальный бонус: 10% токенов другу за каждую оплату приглашённого
                    try:
                        user = await UserRepo(s).get(int(payment.user_id))
                        inviter_id = int(user.invited_by) if user and user.invited_by else None
                        if inviter_id:
                            inviter_bonus = max(1, int(tokens * 0.1))
                            await UserRepo(s).inc_balance(
                                telegram_id=inviter_id,
                                delta=inviter_bonus,
                                bucket="animate",
                            )
                            await UserRepo(s)._log_referral_bonus(
                                ref_id=user.referred_id if user else None,
                                referrer_user_id=inviter_id,
                                referred_user_id=int(payment.user_id),
                                bonus_type="deposit",
                                amount=inviter_bonus,
                                pay_id=payment.id,
                                deposit_rub_amount=int(payment.rub_amount),
                                deposit_token_amount=tokens,
                            )
                    except Exception:
                        pass
            await s.commit()

        st = state_storage.setdefault(cq.from_user.id, State())
        ctx = BotContext(user_id=cq.from_user.id, state=st)
        await ctx.ensure_snapshot(refresh=True)

        async def _animate_success(meta: dict | None = None):
            st.current_page = "flow.animate"
            balance = ctx.snapshot.get("animate_balance_tokens", 0)
            meta = meta or {}
            prompt_raw = (
                ctx.state.animate_photo_prompt
                or meta.get("animate_photo_prompt")
                or "Добавьте текст для анимации."
            )
            prompt = prompt_raw.replace("{", "{{").replace("}", "}}")
            buttons = ikb_rows(
                [[(ctx.t("buttons.try_again"), "nav:flow.animate"), (ctx.t("buttons.run_generation"), "run:animate")]]
            )
            photo_id = ctx.state.animate_photo_file_id or meta.get("animate_photo_file_id")
            text = ctx.t("paywall.animate_success", balance=balance, prompt=prompt)
            if photo_id:
                await cq.message.answer_photo(photo_id, caption=text, reply_markup=buttons, parse_mode="HTML")
                return
            await cq.message.answer(text, reply_markup=buttons, parse_mode="HTML")

        if status == "succeeded":
            meta = success_meta or metadata or {}
            has_pending = bool(
                ctx.state.animate_photo_file_id
                or ctx.state.animate_photo_prompt
                or meta.get("animate_photo_file_id")
                or meta.get("animate_photo_prompt")
            )
            if has_pending:
                try:
                    await _animate_success(meta)
                except Exception as exc:
                    await cq.message.answer(
                        f"Статус платежа `{pid}`: *{status}*\n\n✅ Платёж прошёл. Баланс пополнен.\n\n(Не удалось показать итоговый блок: {exc})",
                        parse_mode="Markdown",
                    )
            else:
                await cq.message.answer(
                    f"Статус платежа `{pid}`: *{status}*\n\n✅ Платёж прошёл. Баланс пополнен.",
                    parse_mode="Markdown",
                )
        elif status == "canceled":
            msg = f"Статус платежа `{pid}`: *{status}*\n\n❌ Платёж отменён."
            await cq.message.answer(msg, parse_mode="Markdown")
        else:
            msg = f"Статус платежа `{pid}`: *{status}*\n\n⏳ Ещё не оплачен. Проверьте позже."
            await cq.message.answer(msg, parse_mode="Markdown")

        await cq.answer()
