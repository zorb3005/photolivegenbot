from __future__ import annotations

from typing import Dict, Set

from sqlalchemy import select, update, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.user import User
from app.settings import settings


class UserRepo:
    def __init__(self, s: AsyncSession):
        self.s = s

    # ---------- CRUD ----------

    async def get(self, telegram_id: int) -> User | None:
        res = await self.s.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return res.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None = None,
        email: str | None = None,
        *,
        invited_by: int | None = None,
        referred_id: int | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        segment: str | None = None,
        return_created: bool = False,
    ) -> User | tuple[User, bool]:
        u = await self.get(telegram_id)
        if u:
            updates: Dict[str, object] = {}
            if username is not None and username != u.username:
                updates["username"] = username
            if email is not None and email != u.email:
                updates["email"] = email
            if first_name is not None and first_name != u.first_name:
                updates["first_name"] = first_name
            if last_name is not None and last_name != u.last_name:
                updates["last_name"] = last_name
            if updates:
                updates["updated_at"] = func.now()
                await self.s.execute(
                    update(User)
                    .where(User.telegram_id == telegram_id)
                    .values(**updates)
                )
                for key, val in updates.items():
                    setattr(u, key, val)
                await self.s.flush()
            return (u, False) if return_created else u

        ref_id = invited_by if invited_by and invited_by != telegram_id else None
        ref_internal_id = referred_id if ref_id else None

        internal_id = await self._allocate_internal_id()

        u = User(
            telegram_id=telegram_id,
            internal_id=internal_id,
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            balance_tokens=0,
            animate_balance_tokens=0,
            avatar_balance_tokens=0,
            friends_count=0,
            invited_by=ref_id,
            referred_id=ref_internal_id,
            segment=segment or "lead",
        )
        self.s.add(u)
        try:
            await self.s.flush()
        except IntegrityError:
            # Конкурентный insert того же пользователя — откатываем и возвращаем существующую запись
            await self.s.rollback()
            existing = await self.get(telegram_id)
            if existing:
                return (existing, False) if return_created else existing
            raise

        await self._append_segment_history(telegram_id=telegram_id, segment=u.segment)

        if ref_id:
            await self._apply_referral_bonus(
                inviter_id=ref_id,
                invitee_id=telegram_id,
                inviter_internal_id=ref_internal_id,
            )

        return (u, True) if return_created else u

    async def inc_balance(self, *, telegram_id: int, delta: int, bucket: str | None = None) -> int:
        """
        Атомично увеличивает баланс и возвращает новое значение выбранного кошелька.
        bucket: None | "animate" | "avatar" — если None, используется legacy balance_tokens.
        """
        await self.get_or_create(telegram_id)

        if bucket == "animate":
            column = User.animate_balance_tokens
        elif bucket == "avatar":
            column = User.avatar_balance_tokens
        else:
            column = User.balance_tokens

        column_name = column.key
        res = await self.s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(
                **{
                    column_name: column + delta,
                    "updated_at": func.now(),
                }
            )
            .returning(column)
        )
        new_val = res.scalar_one()
        await self.s.flush()
        return int(new_val)

    # ---------- Snapshot для интерфейсов ----------

    async def snapshot(self, *, telegram_id: int) -> Dict[str, int]:
        """
        Компактный слепок для подстановки в тексты бота.
        Возвращает:
          - user_id           (telegram_id)
          - balance_tokens    (int)
          - friends_count     (int)
        """
        u = await self.get_or_create(telegram_id)

        friends = int(u.friends_count or 0)
        res = await self.s.execute(
            text(
                """
                SELECT COUNT(DISTINCT referred_user_id)
                  FROM referral_bonuses
                 WHERE referrer_user_id = :uid
                """
            ),
            {"uid": telegram_id},
        )
        friends = max(friends, int(res.scalar() or 0))

        balance_common = int(u.balance_tokens or 0)
        balance_animate = int(getattr(u, "animate_balance_tokens", 0) or 0)
        balance_avatar = int(getattr(u, "avatar_balance_tokens", 0) or 0)
        total_balance = balance_common + balance_animate + balance_avatar

        # Суммарные и последние рефералки
        res = await self.s.execute(
            text(
                """
                SELECT COALESCE(SUM(amount), 0)
                  FROM referral_bonuses
                 WHERE referrer_user_id = :uid
                """
            ),
            {"uid": telegram_id},
        )
        referral_total = int(res.scalar() or 0)

        res = await self.s.execute(
            text(
                """
                SELECT rb.referred_user_id, u.username, u.internal_id
                  FROM referral_bonuses rb
                  LEFT JOIN users u ON u.telegram_id = rb.referred_user_id
                 WHERE rb.referrer_user_id = :uid
                 ORDER BY rb.id DESC
                 LIMIT 3
                """
            ),
            {"uid": telegram_id},
        )
        rows = res.mappings().all()
        recent_refs = []
        for row in rows:
            username = row.get("username")
            internal_id = row.get("internal_id")
            if username:
                recent_refs.append(f"@{username}")
            elif internal_id:
                recent_refs.append(f"ID {internal_id}")
            else:
                recent_refs.append(str(row.get("referred_user_id") or ""))
        recent_refs_text = "\n".join(recent_refs)

        return {
            "user_id": u.telegram_id,
            "internal_id": int(u.internal_id),
            "balance_tokens": total_balance,
            "balance_common": balance_common,
            "animate_balance_tokens": balance_animate,
            "avatar_balance_tokens": balance_avatar,
            "friends_count": friends,
            "email": u.email,
            "clone_unlimited": bool(u.clone_unlimited),
            "free_tier_used": bool(u.free_tier_used),
            "segment": u.segment,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "invited_by": u.invited_by,
            "referred_id": u.referred_id,
            "recent_refs": recent_refs_text,
            "invitee_bonus": referral_total,
        }

    async def set_clone_unlimited(self, *, telegram_id: int, value: bool) -> None:
        await self.s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(clone_unlimited=value, updated_at=func.now())
        )
        await self.s.flush()

    async def set_free_tier_used(self, *, telegram_id: int, value: bool) -> None:
        await self.s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(free_tier_used=value, updated_at=func.now())
        )
        await self.s.flush()

    async def get_by_internal_id(self, internal_id: int) -> User | None:
        res = await self.s.execute(
            select(User).where(User.internal_id == internal_id)
        )
        return res.scalar_one_or_none()

    async def _allocate_internal_id(self) -> int:
        try:
            res = await self.s.execute(text("SELECT nextval('users_internal_id_seq')"))
            val = res.scalar_one_or_none()
            if val is not None:
                return int(val)
        except Exception:
            pass

        res = await self.s.execute(select(func.max(User.internal_id)))
        max_val = res.scalar()
        return int(max_val or 0) + 1

    async def _apply_referral_bonus(
        self,
        *,
        inviter_id: int,
        invitee_id: int,
        inviter_internal_id: int | None = None,
    ) -> None:
        if inviter_id == invitee_id:
            return

        inviter_bonus = int(settings.REFERRAL_INVITER_BONUS or 0)
        invitee_bonus = int(settings.REFERRAL_INVITEE_BONUS or 0)

        if inviter_bonus:
            await self.inc_balance(telegram_id=inviter_id, delta=inviter_bonus, bucket="animate")
            await self.s.execute(
                update(User)
                .where(User.telegram_id == inviter_id)
                .values(friends_count=User.friends_count + 1, updated_at=func.now())
            )
            await self._log_referral_bonus(
                ref_id=inviter_internal_id,
                referrer_user_id=inviter_id,
                referred_user_id=invitee_id,
                bonus_type="deposit",
                amount=inviter_bonus,
            )

        if invitee_bonus:
            await self.inc_balance(telegram_id=invitee_id, delta=invitee_bonus, bucket="animate")
            await self._log_referral_bonus(
                ref_id=inviter_internal_id,
                referrer_user_id=inviter_id,
                referred_user_id=invitee_id,
                bonus_type="generation",
                amount=invitee_bonus,
            )

    async def set_email(self, *, telegram_id: int, email: str | None) -> None:
        await self.s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(email=email, updated_at=func.now())
        )
        await self.s.flush()

    async def record_source(
        self,
        *,
        telegram_id: int,
        source_key: str | None,
        source_value: str | None,
    ) -> None:
        if not source_key and not source_value:
            return
        await self.s.execute(
            text(
                """
                INSERT INTO user_sources (user_id, source_key, source_value)
                VALUES (:user_id, :source_key, :source_value)
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {"user_id": telegram_id, "source_key": source_key, "source_value": source_value},
        )
        await self.s.flush()

    async def set_segment(
        self,
        *,
        telegram_id: int,
        segment: str,
        allowed_from: Set[str] | None = None,
    ) -> str | None:
        """
        Устанавливает сегмент и пишет историю, если сегмент меняется.
        Если allowed_from задан, переход возможен только из перечисленных сегментов.
        """
        res = await self.s.execute(
            select(User.segment).where(User.telegram_id == telegram_id)
        )
        current = res.scalar_one_or_none()

        if current is None:
            await self.get_or_create(telegram_id=telegram_id, segment=segment)
            await self._append_segment_history(telegram_id=telegram_id, segment=segment)
            return segment

        normalized_current = current.lower()
        if normalized_current in {"ban", "banned"}:
            return current

        if segment == current:
            return current

        if allowed_from:
            normalized_allowed = {seg.lower() for seg in allowed_from}
            if normalized_current not in normalized_allowed:
                return current

        normalized_target = segment.lower()
        if normalized_target in {"ban", "banned"}:
            segment = normalized_target

        await self.s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(segment=segment, updated_at=func.now())
        )
        await self._append_segment_history(telegram_id=telegram_id, segment=segment)
        await self.s.flush()
        return segment

    async def log_generation(
        self,
        *,
        telegram_id: int,
        model: str | None,
        request: str | None,
        cost: int | None,
        status: str,
        generation_type: str | None = None,
    ) -> None:
        safe_request = request or ""
        if len(safe_request) > 4000:
            safe_request = safe_request[:4000]
        await self.s.execute(
            text(
                """
                INSERT INTO generation_history (user_id, model, request, cost, status, generation_type)
                VALUES (:user_id, :model, :request, :cost, :status, :generation_type)
                """
            ),
            {
                "user_id": telegram_id,
                "model": model,
                "request": safe_request,
                "cost": cost,
                "status": status,
                "generation_type": generation_type,
            },
        )
        await self.s.flush()

    async def start_generation(
        self,
        *,
        telegram_id: int,
        model: str | None,
        request: str | None,
        cost: int | None,
        generation_type: str | None = None,
    ) -> int:
        safe_request = request or ""
        if len(safe_request) > 4000:
            safe_request = safe_request[:4000]
        res = await self.s.execute(
            text(
                """
                INSERT INTO generation_history (user_id, model, request, cost, status, generation_type)
                VALUES (:user_id, :model, :request, :cost, :status, :generation_type)
                RETURNING id
                """
            ),
            {
                "user_id": telegram_id,
                "model": model,
                "request": safe_request,
                "cost": cost,
                "status": "started",
                "generation_type": generation_type,
            },
        )
        await self.s.flush()
        return int(res.scalar_one())

    async def finish_generation(
        self,
        *,
        generation_id: int,
        status: str,
        cost: int | None = None,
    ) -> None:
        await self.s.execute(
            text(
                """
                UPDATE generation_history
                   SET status = :status,
                       cost = COALESCE(:cost, cost)
                 WHERE id = :id
                """
            ),
            {"id": generation_id, "status": status, "cost": cost},
        )
        await self.s.flush()

    async def _append_segment_history(self, *, telegram_id: int, segment: str) -> None:
        await self.s.execute(
            text(
                """
                INSERT INTO segment_history (user_id, segment)
                VALUES (:user_id, :segment)
                """
            ),
            {"user_id": telegram_id, "segment": segment},
        )

    async def _log_referral_bonus(
        self,
        *,
        ref_id: int | None,
        referrer_user_id: int | None,
        referred_user_id: int,
        bonus_type: str,
        amount: int,
        pay_id=None,
        deposit_rub_amount: int | None = None,
        deposit_token_amount: int | None = None,
    ) -> None:
        await self.s.execute(
            text(
                """
                INSERT INTO referral_bonuses
                    (ref_id, referrer_user_id, referred_user_id, bonus_type, amount, deposit_rub_amount, deposit_token_amount, pay_id)
                VALUES
                    (:ref_id, :referrer_user_id, :referred_user_id, :bonus_type, :amount, :deposit_rub_amount, :deposit_token_amount, :pay_id)
                """
            ),
            {
                "ref_id": ref_id,
                "referrer_user_id": referrer_user_id,
                "referred_user_id": referred_user_id,
                "bonus_type": bonus_type,
                "amount": amount,
                "deposit_rub_amount": deposit_rub_amount,
                "deposit_token_amount": deposit_token_amount,
                "pay_id": pay_id,
            },
        )
        await self.s.flush()
