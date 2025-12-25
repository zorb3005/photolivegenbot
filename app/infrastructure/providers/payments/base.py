from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any, Optional
import logging

import httpx

# Берём переменные окружения напрямую, чтобы не зависеть от конкретной формы app.settings
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID") or os.getenv("YK_SHOP_ID", "")
YOOKASSA_API_KEY = os.getenv("YOOKASSA_API_KEY") or os.getenv("YK_SECRET_KEY", "")
YOOKASSA_API_URL = (os.getenv("YK_API_URL") or "https://api.yookassa.ru/v3").rstrip("/")

logger = logging.getLogger("payments.yookassa")


class PaymentProvider:
    """
    Минималистичный клиент YooKassa на httpx.
    Нет SDK — только HTTP.
    """

    def __init__(self) -> None:
        if not YOOKASSA_SHOP_ID or not YOOKASSA_API_KEY:
            raise RuntimeError("YOOKASSA_SHOP_ID/YOOKASSA_API_KEY не заданы в .env")

        raw = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_API_KEY}".encode()
        self._auth_header = "Basic " + base64.b64encode(raw).decode()

    async def create_payment(
        self,
        *,
        rub_amount: int | float | str,
        description: str,
        return_url: str,
        customer_email: str,
        metadata: Optional[dict[str, Any]] = None,
        capture: bool = True,
        idempotence_key: Optional[str] = None,
    ) -> dict:
        """
        Создание платежа в YooKassa.
        Возвращает JSON YooKassa (там будет id и confirmation.confirmation_url).
        """
        if not customer_email:
            raise ValueError("customer_email is required for YooKassa receipt")
        amount_str = f"{float(rub_amount):.2f}"
        payload = {
            "amount": {"value": amount_str, "currency": "RUB"},
            "capture": capture,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description,
            "metadata": metadata or {},
            # Минимальный чек: без НДС, одна позиция и технический email
            "receipt": {
                "customer": {"email": customer_email},
                "items": [
                    {
                        "description": (description or "Оплата в боте")[:128],
                        "quantity": "1.0",
                        "amount": {"value": amount_str, "currency": "RUB"},
                        # Налоговые реквизиты для чека
                        "vat_code": 1,  # 1 = без НДС
                        "payment_subject": "payment",
                        "payment_mode": "full_payment",
                    }
                ],
            },
        }
        headers = {
            "Authorization": self._auth_header,
            "Idempotence-Key": idempotence_key or str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        url = f"{YOOKASSA_API_URL}/payments"
        safe_meta = list((metadata or {}).keys())
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as cli:
                r = await cli.post(url, headers=headers, content=json.dumps(payload))
                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError as e:  # логируем тело ответа, чтобы видеть причину 400/401
                    logger.error(
                        "YooKassa HTTP error %s: %s | body=%s | amount=%s | meta_keys=%s",
                        r.status_code,
                        url,
                        r.text,
                        amount_str,
                        safe_meta,
                    )
                    raise httpx.HTTPStatusError(f"{e} | body={r.text}", request=e.request, response=e.response)
                return r.json()
        except httpx.RequestError as e:
            logger.error(
                "YooKassa request failed: %s | amount=%s | meta_keys=%s | err=%s",
                url,
                amount_str,
                safe_meta,
                e,
                exc_info=True,
            )
            raise

    async def fetch_payment(self, payment_id: str) -> dict:
        """
        Получить платеж по id из YooKassa (например, чтобы проверить статус).
        """
        headers = {"Authorization": self._auth_header}
        url = f"{YOOKASSA_API_URL}/payments/{payment_id}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as cli:
                r = await cli.get(url, headers=headers)
                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        # Удобный лог для “битых”/чужих payment_id без ошибки уровня ERROR
                        logger.info(
                            "YooKassa fetch 404 pid=%s url=%s body=%s",
                            payment_id,
                            url,
                            exc.response.text,
                        )
                        raise
                    logger.error(
                        "YooKassa fetch failed %s: %s | body=%s",
                        payment_id,
                        exc,
                        r.text,
                    )
                    raise httpx.HTTPStatusError(f"{exc} | body={r.text}", request=exc.request, response=exc.response)
                return r.json()
        except httpx.RequestError as exc:
            logger.error("YooKassa fetch request error pid=%s url=%s err=%r", payment_id, url, exc, exc_info=True)
            raise
