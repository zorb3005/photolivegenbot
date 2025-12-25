from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.infrastructure.db.repositories.payment_repo import PaymentRepo
from app.infrastructure.db.repositories.user_repo import UserRepo
from app.infrastructure.providers.payments.base import PaymentProvider


@dataclass
class CreateInvoiceInput:
    user_id: int
    amount_tokens: int
    rub_amount: int
    description: str
    return_url: str
    customer_email: str
    metadata: dict | None = None


@dataclass
class CreateInvoiceOutput:
    payment_uuid: UUID
    payment_id: str
    confirmation_url: str


class CreateInvoice:
    """
    Создаёт платёж в YooKassa, затем фиксирует pending-запись в БД и проставляет payment_id.
    """

    def __init__(self, session) -> None:
        self.session = session
        self.repo = PaymentRepo(session)
        self.provider = PaymentProvider()

    async def __call__(self, data: CreateInvoiceInput) -> CreateInvoiceOutput:
        # 1) Создаём локальную pending-запись
        await UserRepo(self.session).get_or_create(telegram_id=data.user_id)
        metadata = {"user_id": data.user_id, "amount_tokens": data.amount_tokens}
        if data.metadata:
            metadata.update(data.metadata)
        # фиксируем ключевые налоговые атрибуты, чтобы не зависеть от ответа YooKassa
        metadata.setdefault("vat_code", 1)
        metadata.setdefault("payment_mode", "full_payment")
        metadata.setdefault("payment_subject", "payment")
        metadata["customer_email"] = data.customer_email
        payment_uuid = await self.repo.create_pending(
            user_id=data.user_id,
            amount_tokens=data.amount_tokens,
            rub_amount=data.rub_amount,
            currency="RUB",
            metadata=metadata,
        )
        await self.session.flush()

        # Добавляем идентификатор телеграм-юзера в описание для быстрой фильтрации в YooKassa
        descr = data.description or ""
        descr = f"{descr} | uid={data.user_id}".strip()
        descr = descr[:128]

        # 2) Создаём платёж в YooKassa
        yk = await self.provider.create_payment(
            rub_amount=data.rub_amount,
            description=descr,
            return_url=data.return_url,
            customer_email=data.customer_email,
            metadata={"payment_uuid": str(payment_uuid), "user_id": data.user_id, **metadata},
        )
        payment_id = yk["id"]
        confirmation_url = yk["confirmation"]["confirmation_url"]

        # 3) Обновляем локальную запись провайдерским id
        await self.repo.set_provider_id(id=payment_uuid, payment_id=payment_id)

        return CreateInvoiceOutput(
            payment_uuid=payment_uuid,
            payment_id=payment_id,
            confirmation_url=confirmation_url,
        )
