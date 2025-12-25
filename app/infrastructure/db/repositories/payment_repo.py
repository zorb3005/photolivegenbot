from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.payment import Payment


class PaymentRepo:
    """
    Репозиторий поверх таблицы public.payments (смотрит миграцию).
    Без зависимости от ORM-модели, чтобы не плодить слои.
    """

    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def create_pending(
        self,
        *,
        user_id: int,
        amount_tokens: int,
        rub_amount: Decimal | str | int,
        currency: str = "RUB",
        metadata: Optional[dict[str, Any]] = None,
    ) -> UUID:
        """
        Вставляет pending-платёж, возвращает UUID (id).
        """
        q = text(
            """
            INSERT INTO payments (user_id, amount_tokens, rub_amount, currency, status, metadata)
            VALUES (:user_id, :amount_tokens, :rub_amount, :currency, 'pending', COALESCE(CAST(:metadata AS jsonb), '{}'::jsonb))
            RETURNING id
            """
        )
        params = {
            "user_id": user_id,
            "amount_tokens": int(amount_tokens),
            "rub_amount": str(Decimal(rub_amount)),
            "currency": currency,
            "metadata": self._encode_metadata(metadata, default_empty=True),
        }
        res = await self.s.execute(q, params)
        return res.scalar_one()

    async def set_provider_id(self, *, id: UUID, payment_id: str) -> None:
        q = text(
            "UPDATE payments SET payment_id = :payment_id, updated_at = now() WHERE id = :id"
        )
        await self.s.execute(q, {"payment_id": payment_id, "id": id})

    async def set_status(
        self,
        *,
        payment_id: str,
        status: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        q = text(
            """
            UPDATE payments
               SET status = :status,
                   metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(CAST(:metadata AS jsonb), '{}'::jsonb),
                   completed_at = CASE
                                      WHEN payments.status <> 'succeeded' AND :status = 'succeeded' THEN now()
                                      WHEN :status <> 'succeeded' THEN NULL
                                      ELSE completed_at
                                   END,
                   updated_at = now()
             WHERE payment_id = :payment_id
            """
        )
        await self.s.execute(
            q,
            {
                "status": status,
                "metadata": self._encode_metadata(metadata),
                "payment_id": payment_id,
            },
        )

    async def mark_status(
        self,
        *,
        payment_id: str,
        status: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Backward-compatible alias. Prefer set_status().
        """
        await self.set_status(payment_id=payment_id, status=status, metadata=metadata)

    async def get_by_payment_id(self, payment_id: str) -> Optional[Payment]:
        q = text(
            """
            SELECT id, user_id, payment_id, amount_tokens, rub_amount, currency, status, metadata,
                   created_at, updated_at, completed_at
              FROM payments
             WHERE payment_id = :pid
             LIMIT 1
            """
        )
        res = await self.s.execute(q, {"pid": payment_id})
        row = res.mappings().first()
        return self._row_to_payment(row) if row else None

    async def by_payment_id(self, payment_id: str) -> Optional[Payment]:
        """
        Alias to align with older code paths that expect by_payment_id().
        """
        return await self.get_by_payment_id(payment_id)

    async def get_by_provider_id(self, payment_id: str) -> Optional[Payment]:
        """
        Former method name kept for compatibility.
        """
        return await self.get_by_payment_id(payment_id)

    async def list_by_statuses(
        self,
        statuses: list[str],
        limit: int = 100,
    ) -> list[Payment]:
        """
        Возвращает платежи с нужными статусами (например, pending / waiting_for_capture).
        """
        if not statuses:
            return []
        q = text(
            """
            SELECT id, user_id, payment_id, amount_tokens, rub_amount, currency, status, metadata,
                   created_at, updated_at, completed_at
              FROM payments
             WHERE status = ANY(:statuses)
             ORDER BY updated_at ASC
             LIMIT :limit
            """
        )
        res = await self.s.execute(q, {"statuses": statuses, "limit": limit})
        rows = res.mappings().all()
        return [self._row_to_payment(r) for r in rows if r]

    @staticmethod
    def _row_to_payment(row) -> Optional[Payment]:
        if row is None:
            return None

        data = dict(row)
        metadata = data.get("metadata") or {}

        return Payment(
            id=data["id"],
            user_id=int(data["user_id"]),
            payment_id=data.get("payment_id"),
            amount_tokens=int(data["amount_tokens"]),
            rub_amount=Decimal(str(data["rub_amount"])),
            currency=data["currency"],
            status=data["status"],
            metadata=dict(metadata),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            completed_at=data.get("completed_at"),
        )

    @staticmethod
    def _encode_metadata(
        metadata: Optional[dict[str, Any]],
        *,
        default_empty: bool = False,
    ) -> Optional[str]:
        if metadata is None:
            return "{}" if default_empty else None
        return json.dumps(metadata, ensure_ascii=False)
