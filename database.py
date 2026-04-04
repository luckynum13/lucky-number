"""
Lucky Number Bot — In-Memory Database
Simple in-memory storage, no file system needed.
"""

from decimal import Decimal
from datetime import datetime

# In-memory storage
USERS = {}        # telegram_id -> dict
TRANSACTIONS = {} # tx_id -> dict


async def init_db():
    pass  # Nothing to initialize


async def get_or_create_user(telegram_id, username=None, first_name=None):
    if telegram_id not in USERS:
        USERS[telegram_id] = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "balance_usd": Decimal("0"),
            "created_at": datetime.utcnow(),
        }
    return USERS[telegram_id]


async def get_user_balance(telegram_id):
    user = USERS.get(telegram_id)
    return user["balance_usd"] if user else Decimal("0")


async def credit_user_balance(telegram_id, amount_usd, tx_id):
    await get_or_create_user(telegram_id)
    USERS[telegram_id]["balance_usd"] += Decimal(str(amount_usd))
    TRANSACTIONS[tx_id] = {"type": "deposit", "amount": amount_usd}


async def debit_user_balance(telegram_id, amount_usd, tx_id):
    user = USERS.get(telegram_id)
    if not user or user["balance_usd"] < Decimal(str(amount_usd)):
        return False
    USERS[telegram_id]["balance_usd"] -= Decimal(str(amount_usd))
    TRANSACTIONS[tx_id] = {"type": "bet", "amount": amount_usd}
    return True


async def credit_win(telegram_id, amount_usd, tx_id):
    await get_or_create_user(telegram_id)
    USERS[telegram_id]["balance_usd"] += Decimal(str(amount_usd))
    TRANSACTIONS[tx_id] = {"type": "win", "amount": amount_usd}


async def is_duplicate_tx(tx_id):
    return tx_id in TRANSACTIONS
