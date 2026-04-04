"""
Lucky Number Bot — Database Models for Payments
"""

import os
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Column, DateTime, Integer,
    Numeric, String, Boolean, select, update
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Use /tmp which always exists on any server
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////tmp/lucky.db")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username    = Column(String(64), nullable=True)
    first_name  = Column(String(64), nullable=True)
    balance_usd = Column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Transaction(Base):
    __tablename__ = "transactions"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    tx_id       = Column(String(128), unique=True, nullable=False, index=True)
    type        = Column(String(16), nullable=False)
    amount_usd  = Column(Numeric(12, 2), nullable=False)
    currency    = Column(String(8), default="USD")
    processed   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


async def init_db():
    import os as _os
    _os.makedirs("/tmp", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(telegram_id, username=None, first_name=None):
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


async def get_user_balance(telegram_id):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User.balance_usd).where(User.telegram_id == telegram_id)
        )
        balance = result.scalar_one_or_none()
        return balance or Decimal("0")


async def credit_user_balance(telegram_id, amount_usd, tx_id):
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
                type="deposit",
                amount_usd=amount_usd,
            ))


async def debit_user_balance(telegram_id, amount_usd, tx_id):
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
            ))
            return True


async def credit_win(telegram_id, amount_usd, tx_id):
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
            ))


async def is_duplicate_tx(tx_id):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction.id).where(Transaction.tx_id == tx_id)
        )
        return result.scalar_one_or_none() is not None
