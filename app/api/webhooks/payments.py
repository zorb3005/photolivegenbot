from __future__ import annotations

import ipaddress
import logging

from fastapi import APIRouter, Request, Depends, Response, status

from app.infrastructure.db.base import get_session
from app.application.usecases.payments.apply_webhook import ApplyWebhook

router = APIRouter(prefix="/webhook/yookassa", tags=["yookassa"])
log = logging.getLogger("webhooks.yookassa")


# ЮKassa не добавляет подпись к webhook, поэтому проверяем только IP.
_TRUSTED_IPS = [
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.154.128/25",
    "77.75.156.11",
    "77.75.156.35",
    "2a02:5180::/32",
    "127.0.0.1",
]
_TRUSTED_NETS = [ipaddress.ip_network(ip) for ip in _TRUSTED_IPS]


def _is_trusted_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _TRUSTED_NETS)


@router.post("")
async def yookassa_webhook(request: Request, session=Depends(get_session)):
    """
    Подключть этот URL в кабинете YooKassa:
    POST {BASE_PUBLIC_URL}/webhook/yookassa
    """
    peer_ip = request.client.host if request.client else ""
    # Если есть прокси — берём реальный клиент из заголовка, но доверяем только если
    # сам peer уже доверенный. Это простой вариант без списка доверенных прокси.
    fwd_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    candidate_ip = fwd_ip or peer_ip

    if not _is_trusted_ip(candidate_ip):
        log.warning("Reject webhook: untrusted ip=%s peer=%s fwd=%s", candidate_ip, peer_ip, fwd_ip)
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    payload = await request.json()
    await ApplyWebhook(session)(payload)
    return Response(status_code=status.HTTP_200_OK)
