from __future__ import annotations

from datetime import datetime

from uuid import UUID

from sqlalchemy import BigInteger, Integer, Text, TIMESTAMP, Boolean, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """
    Пользователь бота. Храним по telegram_id (bigint) — это и есть PK.
    """
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    internal_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
    )
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)

    balance_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    animate_balance_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avatar_balance_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    friends_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invited_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    referred_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment: Mapped[str] = mapped_column(Text, nullable=False, default="lead")
    clone_unlimited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    free_tier_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )

    def __repr__(self) -> str:  # для удобной отладки
        return f"<User id={self.telegram_id} balance={self.balance_tokens}>"


class UserSource(Base):
    __tablename__ = "user_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    source_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )


class SegmentHistory(Base):
    __tablename__ = "segment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )


class ReferralBonus(Base):
    __tablename__ = "referral_bonuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    referrer_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="SET NULL")
    )
    referred_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE")
    )
    bonus_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deposit_rub_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deposit_token_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pay_id: Mapped[UUID | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )


class GenerationHistory(Base):
    __tablename__ = "generation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    request: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_type: Mapped[str | None] = mapped_column(Text, nullable=True)
