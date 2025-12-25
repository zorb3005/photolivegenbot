from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
import uuid
from typing import Dict, List


@dataclass(frozen=True)
class LiveGeneration:
    user_id: int
    generation_type: str
    provider: str
    started_at: datetime


_LOCK = Lock()
_last_seen: Dict[int, datetime] = {}
_generations: Dict[str, LiveGeneration] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def touch_user_activity(user_id: int | None) -> None:
    if not user_id:
        return
    with _LOCK:
        _last_seen[int(user_id)] = _now()


def get_online_user_ids(within_seconds: int = 60) -> List[int]:
    cutoff = _now() - timedelta(seconds=within_seconds)
    stale_cutoff = cutoff - timedelta(hours=6)
    with _LOCK:
        for uid, ts in list(_last_seen.items()):
            if ts < stale_cutoff:
                _last_seen.pop(uid, None)
        return [uid for uid, ts in _last_seen.items() if ts >= cutoff]


def start_generation(user_id: int, generation_type: str, provider: str) -> str:
    token = f"{user_id}:{uuid.uuid4().hex}"
    with _LOCK:
        _generations[token] = LiveGeneration(
            user_id=int(user_id),
            generation_type=str(generation_type or ""),
            provider=str(provider or ""),
            started_at=_now(),
        )
    return token


def finish_generation(token: str | None) -> None:
    if not token:
        return
    with _LOCK:
        _generations.pop(token, None)


def get_active_generations() -> List[LiveGeneration]:
    with _LOCK:
        return list(_generations.values())
