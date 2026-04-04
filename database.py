"""
Lucky Number — Database Models for Payments
============================================
SQLAlchemy async models + helper functions.
Replace the stubs in payments.py with these real implementations.
"""

import os
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Column, DateTime, Integer,
    Numeric, String, Boolean, select, update, insert
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///lucky.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ─────────────────────────────────────────────
#  MODELS
# ─────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True)
    telegram_id  = Column(BigInteger, unique=True, nullable=False, index=True)
    username     = Column(String(64), nullable=True)
    first_name   = Column(String(64), nullable=True)
    balance_usd  = Column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Transaction(Base):
    __tablename__ = "transactions"

    id           = Column(Integer, primary_key=True)
    telegram_id  = Column(BigInteger, nullable=False, index=True)
    tx_id        = Column(String(128), unique=True, nullable=False, index=True)
    type         = Column(String(16), nullable=False)   # "deposit" | "withdraw" | "bet" | "win"
    amount_usd   = Column(Numeric(12, 2), nullable=False)
    currency     = Column(String(8), default="USD")
    processed    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────
#  INIT DB
# ─────────────────────────────────────────────
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ─────────────────────────────────────────────
#  PAYMENT HELPERS  (replace stubs in payments.py)
# ─────────────────────────────────────────────
async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> User:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                balance_usd=Decimal("0"),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


async def get_user_balance(telegram_id: int) -> Decimal:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User.balance_usd).where(User.telegram_id == telegram_id)
        )
        balance = result.scalar_one_or_none()
        return balance or Decimal("0")


async def credit_user_balance(telegram_id: int, amount_usd: Decimal, tx_id: str):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Credit balance
            await session.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(balance_usd=User.balance_usd + amount_usd)
            )
            # Record transaction
            session.add(Transaction(
                telegram_id=telegram_id,
                tx_id=tx_id,
                type="deposit",
                amount_usd=amount_usd,
                currency="USD",
            ))


async def debit_user_balance(telegram_id: int, amount_usd: Decimal, tx_id: str) -> bool:
    """
    Deduct amount from balance (bet placement).
    Returns False if insufficient balance.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user or user.balance_usd < amount_usd:
                return False

            await session.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(balance_usd=User.balance_usd - amount_usd)
            )
            session.add(Transaction(
                telegram_id=telegram_id,
                tx_id=tx_id,
                type="bet",
                amount_usd=amount_usd,
                currency="USD",
            ))
            return True


async def credit_win(telegram_id: int, amount_usd: Decimal, tx_id: str):
    """Credit winnings to user balance."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(balance_usd=User.balance_usd + amount_usd)
            )
            session.add(Transaction(
                telegram_id=telegram_id,
                tx_id=tx_id,
                type="win",
                amount_usd=amount_usd,
                currency="USD",
            ))


async def is_duplicate_tx(tx_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction.id).where(Transaction.tx_id == tx_id)
        )
        return result.scalar_one_or_none() is not None
