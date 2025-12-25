from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

import httpx

from app.settings import settings


class KlingError(Exception):
    pass


@dataclass
class KlingGeneration:
    id: str
    state: str
    video_url: Optional[str] = None
    failure_reason: Optional[str] = None


class KlingClient:
    """
    Минимальный async-клиент для KlingAI image->video.
    """

    def __init__(self) -> None:
        if not settings.KLINGAI_ACCESS_KEY:
            raise KlingError("KLINGAI_ACCESS_KEY не задан")
        if not settings.KLINGAI_SECRET_KEY:
            raise KlingError("KLINGAI_SECRET_KEY не задан")
        if not settings.KLINGAI_BASE_URL:
            raise KlingError("KLINGAI_BASE_URL не задан")
        self._base = settings.KLINGAI_BASE_URL.rstrip("/")
        self._access_key = settings.KLINGAI_ACCESS_KEY
        self._secret_key = settings.KLINGAI_SECRET_KEY
        self._token: str | None = None
        self._token_exp: int | None = None
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(30.0, connect=10.0)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    def _b64url(self, raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def _encode_jwt_token(self) -> tuple[str, int]:
        now = int(time.time())
        headers = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self._access_key,
            "exp": now + 1800,
            "nbf": now - 5,
        }
        header_b64 = self._b64url(json.dumps(headers, separators=(",", ":")).encode("utf-8"))
        payload_b64 = self._b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = hmac.new(self._secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        token = f"{header_b64}.{payload_b64}.{self._b64url(signature)}"
        return token, payload["exp"]

    def _auth_header(self) -> str:
        now = int(time.time())
        if not self._token or not self._token_exp or now >= self._token_exp - 60:
            self._token, self._token_exp = self._encode_jwt_token()
        return f"Bearer {self._token}"

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        headers = {**self._headers, "Authorization": self._auth_header()}
        try:
            resp = await self._client.request(method, url, headers=headers, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise KlingError(f"KlingAI запрос не удался: {exc}") from exc

        if resp.status_code >= 400:
            raise KlingError(f"KlingAI {resp.status_code}: {resp.text}")
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise KlingError(f"Не удалось разобрать ответ KlingAI: {exc}") from exc
        if isinstance(payload, dict):
            code = payload.get("code")
            if code not in (None, 0, "0"):
                message = payload.get("message") or "KlingAI ошибка"
                raise KlingError(f"KlingAI code {code}: {message}")
        return payload

    def _normalize_duration(self, duration: str | int) -> str:
        raw = str(duration or "").strip().lower()
        if raw.endswith("s"):
            raw = raw[:-1]
        try:
            value = int(float(raw))
        except ValueError:
            value = 5
        if value not in (5, 10):
            value = 5
        return str(value)

    async def create_video(
        self,
        *,
        prompt: str,
        image_url: str,
        model_name: str | None = "kling-v1",
        mode: str = "std",
        duration: str = "5",
    ) -> KlingGeneration:
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "image": image_url,
            "duration": self._normalize_duration(duration),
        }
        if model_name:
            payload["model_name"] = model_name
        if mode:
            payload["mode"] = mode
        data = await self._request("POST", "/v1/videos/image2video", json=payload)
        data_block = data.get("data") if isinstance(data, dict) else {}
        gen_id = data_block.get("task_id")
        if not gen_id:
            raise KlingError("KlingAI не вернул generation id")
        state = data_block.get("task_status") or "submitted"
        return KlingGeneration(id=str(gen_id), state=str(state))

    async def get_status(self, generation_id: str) -> KlingGeneration:
        data = await self._request("GET", f"/v1/videos/image2video/{generation_id}")
        data_block = data.get("data") if isinstance(data, dict) else {}
        result = data_block.get("task_result") or {}
        videos = result.get("videos") or []
        video_url = None
        if videos and isinstance(videos, list):
            first = videos[0] or {}
            if isinstance(first, dict):
                video_url = first.get("url")
        return KlingGeneration(
            id=str(data_block.get("task_id") or generation_id),
            state=str(data_block.get("task_status") or "unknown"),
            video_url=video_url,
            failure_reason=data_block.get("task_status_msg"),
        )

    async def poll_until_ready(self, generation_id: str, *, interval: float = 3.0, attempts: int = 200) -> KlingGeneration:
        last = None
        for _ in range(attempts):
            last = await self.get_status(generation_id)
            state = (last.state or "").lower()
            if state in {"completed", "succeeded", "succeed"} and last.video_url:
                return last
            if state in {"failed", "error"}:
                raise KlingError(last.failure_reason or "Generation failed")
            await asyncio.sleep(interval)

        if last and last.video_url:
            return last
        raise KlingError(f"Превышено время ожидания генерации в KlingAI (generation_id={generation_id})")

    async def download_file(self, url: str) -> bytes:
        try:
            resp = await self._client.get(url, timeout=httpx.Timeout(120.0))
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001
            raise KlingError(f"Не удалось скачать файл из KlingAI: {exc}") from exc
