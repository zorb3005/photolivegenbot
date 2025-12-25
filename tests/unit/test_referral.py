from dataclasses import replace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.models.user import Base, User
from app.infrastructure.db.repositories import user_repo as user_repo_module
from app.infrastructure.db.repositories.user_repo import UserRepo
from app.settings import settings as app_settings


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def override_referral_settings(monkeypatch):
    override = replace(
        app_settings,
        REFERRAL_INVITER_BONUS=300,
        REFERRAL_INVITEE_BONUS=150,
    )
    monkeypatch.setattr(user_repo_module, "settings", override)
    yield


@pytest.mark.asyncio
async def test_referral_bonus_applied_to_inviter_and_invitee(session):
    repo = UserRepo(session)
    inviter = User(telegram_id=101, internal_id=1, username="inviter", balance_tokens=0, friends_count=0)
    session.add(inviter)
    await session.commit()

    await repo.get_or_create(telegram_id=202, username="invitee", invited_by=inviter.telegram_id)
    await session.commit()

    inviter_db = await repo.get(inviter.telegram_id)
    invitee_db = await repo.get(202)

    assert inviter_db.balance_tokens == 300
    assert inviter_db.friends_count == 1
    assert invitee_db.balance_tokens == 150
    assert invitee_db.invited_by == inviter.telegram_id


@pytest.mark.asyncio
async def test_self_referral_is_ignored(session):
    repo = UserRepo(session)
    await repo.get_or_create(telegram_id=303, username="self", invited_by=303)
    await session.commit()

    user = await repo.get(303)
    assert user.invited_by is None
    assert user.balance_tokens == 0


@pytest.mark.asyncio
async def test_existing_user_not_processed_again(session):
    repo = UserRepo(session)
    inviter = User(telegram_id=404, internal_id=2, username="inviter", balance_tokens=0, friends_count=0)
    session.add(inviter)
    await session.commit()

    await repo.get_or_create(telegram_id=505, username="invitee", invited_by=inviter.telegram_id)
    await session.commit()
    first_snapshot = await repo.get(inviter.telegram_id)

    await repo.get_or_create(telegram_id=505, username="invitee", invited_by=inviter.telegram_id)
    await session.commit()
    second_snapshot = await repo.get(inviter.telegram_id)

    assert second_snapshot.balance_tokens == first_snapshot.balance_tokens
    assert second_snapshot.friends_count == first_snapshot.friends_count
