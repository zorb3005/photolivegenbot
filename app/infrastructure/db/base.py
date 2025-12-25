"""
Async SQLAlchemy setup.

Использование:
    from app.infrastructure.db.base import async_session, get_session

    # Явно:
    async with async_session() as s:
        ...

    # FastAPI:
    @router.get("/ping")
    async def ping(session=Depends(get_session)):
        await session.execute(text("select 1"))
        return {"ok": True}
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/motionportrait_bot_v2",
)

# Движок
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

# Фабрика сессий (то, что импортирует код)
async_session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

@asynccontextmanager
async def session_ctx() -> AsyncGenerator[AsyncSession, None]:
    """Контекстный менеджер с авто-commit/rollback."""
    session: AsyncSession = async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость для FastAPI: Depends(get_session)."""
    session: AsyncSession = async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

__all__ = ["engine", "async_session", "session_ctx", "get_session"]
