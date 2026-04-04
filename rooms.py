"""
Lucky Number Bot — Room & Game Logic
======================================
Handles room creation, joining, game draw via Telegram bot commands.
The Mini App (index.html) handles the UI — this file handles
server-side validation and notifications.
"""

import os
import uuid
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from database import (
    AsyncSessionLocal,
    User, Transaction,
    get_user_balance,
    debit_user_balance,
    credit_win,
    is_duplicate_tx,
)
from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, select, update
from sqlalchemy.orm import DeclarativeBase
from database import Base

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  ROOM CONFIG
# ─────────────────────────────────────────────
PUBLIC_NOMINALS  = [5, 10, 20, 50, 100]       # USD
PRIVATE_NOMINALS = [20, 50, 100, 200, 300, 400, 500]  # USD
PLAYER_COUNTS    = [3, 5, 7, 10]

ROOM_CONFIG = {
    3:  {"winners": 1, "platform_mult": 1},
    5:  {"winners": 2, "platform_mult": 1},
    7:  {"winners": 3, "platform_mult": 1},
    10: {"winners": 4, "platform_mult": 2},
}


def calc_room(nominal: int, players: int) -> dict:
    cfg = ROOM_CONFIG[players]
    pot          = nominal * players
    each_prize   = nominal * 2
    platform_fee = pot - (each_prize * cfg["winners"])
    return {
        "pot": pot,
        "each_prize": each_prize,
        "platform_fee": platform_fee,
        "winners": cfg["winners"],
    }


# ─────────────────────────────────────────────
#  ROOM MODEL
# ─────────────────────────────────────────────
class Room(Base):
    __tablename__ = "rooms"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_type    = Column(String(10), nullable=False)   # "public" | "private"
    nominal_usd  = Column(Integer, nullable=False)
    max_players  = Column(Integer, nullable=False)
    winners      = Column(Integer, nullable=False)
    each_prize   = Column(Numeric(12,2), nullable=False)
    platform_fee = Column(Numeric(12,2), nullable=False)
    pot          = Column(Numeric(12,2), nullable=False)
    invite_code  = Column(String(8), nullable=True, unique=True)
    creator_id   = Column(Integer, nullable=True)
    is_active    = Column(Boolean, default=True)
    game_started = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow)


class RoomPlayer(Base):
    __tablename__ = "room_players"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    room_id     = Column(String(36), nullable=False, index=True)
    telegram_id = Column(Integer, nullable=False)
    number      = Column(Integer, nullable=False)
    joined_at   = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────
#  FISHER-YATES SHUFFLE
# ─────────────────────────────────────────────
import random

def fisher_yates_shuffle(lst: list) -> list:
    arr = lst[:]
    for i in range(len(arr) - 1, 0, -1):
        j = random.randint(0, i)
        arr[i], arr[j] = arr[j], arr[i]
    return arr


# ─────────────────────────────────────────────
#  GAME DRAW (server-side)
# ─────────────────────────────────────────────
async def run_game_draw(room_id: str, bot) -> dict:
    """
    Run the actual draw server-side.
    Called when room is full.
    Returns draw result.
    """
    async with AsyncSessionLocal() as session:
        # Load room
        result = await session.execute(
            select(Room).where(Room.id == room_id)
        )
        room = result.scalar_one_or_none()
        if not room or room.game_started:
            return {"error": "Room not found or game already started"}

        # Mark game as started
        await session.execute(
            update(Room).where(Room.id == room_id)
            .values(game_started=True, is_active=False)
        )

        # Load players
        players_result = await session.execute(
            select(RoomPlayer).where(RoomPlayer.room_id == room_id)
        )
        players = players_result.scalars().all()

        if len(players) < room.max_players:
            return {"error": "Room not full yet"}

        await session.commit()

    # Fisher-Yates shuffle for fair draw
    shuffled = fisher_yates_shuffle(players)
    winner_players = shuffled[:room.winners]
    winner_ids = [w.telegram_id for w in winner_players]

    # Credit winners
    for winner in winner_players:
        tx_id = f"win_{room_id}_{winner.telegram_id}_{winner.number}"
        if not await is_duplicate_tx(tx_id):
            await credit_win(
                telegram_id=winner.telegram_id,
                amount_usd=Decimal(str(room.each_prize)),
                tx_id=tx_id,
            )

    # Notify all players
    async with AsyncSessionLocal() as session:
        players_result = await session.execute(
            select(RoomPlayer).where(RoomPlayer.room_id == room_id)
        )
        all_players = players_result.scalars().all()

    for player in all_players:
        is_winner = player.telegram_id in winner_ids
        try:
            if is_winner:
                await bot.send_message(
                    chat_id=player.telegram_id,
                    text=(
                        f"🎉 *YOU WON!*\n\n"
                        f"Your number *{player.number}* won!\n"
                        f"💰 *+${room.each_prize}* added to your balance!\n\n"
                        f"Use /balance to check your balance\n"
                        f"Use /play to play again 🎰"
                    ),
                    parse_mode="Markdown",
                )
            else:
                winner_numbers = [str(w.number) for w in winner_players]
                await bot.send_message(
                    chat_id=player.telegram_id,
                    text=(
                        f"😢 *Better luck next time!*\n\n"
                        f"Your number was *{player.number}*\n"
                        f"🏆 Winning numbers: *{', '.join(winner_numbers)}*\n\n"
                        f"Use /play to try again! 🎰"
                    ),
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(f"Could not notify player {player.telegram_id}: {e}")

    return {
        "room_id": room_id,
        "winners": [{"telegram_id": w.telegram_id, "number": w.number} for w in winner_players],
        "prize_each": float(room.each_prize),
        "platform_fee": float(room.platform_fee),
    }


# ─────────────────────────────────────────────
#  BOT ROOM COMMANDS
# ─────────────────────────────────────────────
async def cmd_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rooms — show available public rooms
    """
    lines = ["🎲 *Available Public Rooms:*\n"]
    for nominal in PUBLIC_NOMINALS:
        for players in PLAYER_COUNTS:
            calc = calc_room(nominal, players)
            lines.append(
                f"• *${nominal}* · {players} players · "
                f"{calc['winners']} winner(s) → ${calc['each_prize']} each"
            )

    lines.append("\n🎰 Use /play to open the game!")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_create_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /create — create a private room
    Usage: /create 50 5
    (nominal=50, players=5)
    """
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "Usage: /create <amount> <players>\n"
            "Example: /create 50 5\n\n"
            f"Amounts: {', '.join(f'${n}' for n in PRIVATE_NOMINALS)}\n"
            f"Players: {', '.join(str(p) for p in PLAYER_COUNTS)}"
        )
        return

    try:
        nominal = int(args[0])
        players = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid numbers. Example: /create 50 5")
        return

    if nominal not in PRIVATE_NOMINALS:
        await update.message.reply_text(
            f"❌ Invalid amount. Choose from: {', '.join(f'${n}' for n in PRIVATE_NOMINALS)}"
        )
        return

    if players not in PLAYER_COUNTS:
        await update.message.reply_text(
            f"❌ Invalid player count. Choose from: {', '.join(str(p) for p in PLAYER_COUNTS)}"
        )
        return

    # Check balance
    balance = await get_user_balance(update.effective_user.id)
    if balance < nominal:
        await update.message.reply_text(
            f"❌ Insufficient balance.\n"
            f"You have: ${balance}\n"
            f"Required: ${nominal}\n\n"
            f"Use /deposit to add funds."
        )
        return

    # Create room
    calc = calc_room(nominal, players)
    invite_code = str(uuid.uuid4())[:6].upper()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            room = Room(
                room_type="private",
                nominal_usd=nominal,
                max_players=players,
                winners=calc["winners"],
                each_prize=Decimal(str(calc["each_prize"])),
                platform_fee=Decimal(str(calc["platform_fee"])),
                pot=Decimal(str(calc["pot"])),
                invite_code=invite_code,
                creator_id=update.effective_user.id,
            )
            session.add(room)
            room_id = room.id

    # Auto-join creator
    success = await debit_user_balance(
        telegram_id=update.effective_user.id,
        amount_usd=Decimal(str(nominal)),
        tx_id=f"bet_{room_id}_{update.effective_user.id}",
    )

    if success:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(RoomPlayer(
                    room_id=room_id,
                    telegram_id=update.effective_user.id,
                    number=1,
                ))

    await update.message.reply_text(
        f"✅ *Private room created!*\n\n"
        f"💰 Bet: *${nominal}*\n"
        f"👥 Players: *{players}*\n"
        f"🏆 {calc['winners']} winner(s) → *${calc['each_prize']}* each\n\n"
        f"🔑 Invite code: `{invite_code}`\n\n"
        f"Share this code with friends!\n"
        f"They join with: /join {invite_code}",
        parse_mode="Markdown",
    )


async def cmd_join_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /join <code> — join a private room by invite code
    """
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /join <invite_code>\nExample: /join ABC123")
        return

    invite_code = args[0].upper()
    telegram_id = update.effective_user.id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Room).where(
                Room.invite_code == invite_code,
                Room.is_active == True,
                Room.game_started == False,
            )
        )
        room = result.scalar_one_or_none()

    if not room:
        await update.message.reply_text("❌ Room not found or already closed.")
        return

    # Check balance
    balance = await get_user_balance(telegram_id)
    if balance < room.nominal_usd:
        await update.message.reply_text(
            f"❌ Insufficient balance.\n"
            f"You have: ${balance}\n"
            f"Required: ${room.nominal_usd}\n\n"
            f"Use /deposit to add funds."
        )
        return

    # Check current players
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RoomPlayer).where(RoomPlayer.room_id == room.id)
        )
        current_players = result.scalars().all()

    if len(current_players) >= room.max_players:
        await update.message.reply_text("❌ Room is full!")
        return

    # Assign number
    taken = [p.number for p in current_players]
    available = [n for n in range(1, room.max_players + 1) if n not in taken]
    number = random.choice(available)

    # Debit balance
    tx_id = f"bet_{room.id}_{telegram_id}_{number}"
    success = await debit_user_balance(
        telegram_id=telegram_id,
        amount_usd=Decimal(str(room.nominal_usd)),
        tx_id=tx_id,
    )

    if not success:
        await update.message.reply_text("❌ Failed to process payment. Try again.")
        return

    # Add player
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(RoomPlayer(
                room_id=room.id,
                telegram_id=telegram_id,
                number=number,
            ))

    new_count = len(current_players) + 1

    await update.message.reply_text(
        f"✅ *You joined!*\n\n"
        f"🎲 Your number: *{number}*\n"
        f"👥 Players: *{new_count}/{room.max_players}*\n"
        f"🏆 {room.winners} winner(s) → *${room.each_prize}* each\n\n"
        f"{'🎰 Room is full — drawing now!' if new_count == room.max_players else '⏳ Waiting for more players...'}",
        parse_mode="Markdown",
    )

    # Start game if room is full
    if new_count == room.max_players:
        from telegram.ext import Application
        bot = context.bot
        import asyncio
        asyncio.create_task(run_game_draw(room.id, bot))


# ─────────────────────────────────────────────
#  SETUP
# ─────────────────────────────────────────────
def setup_room_handlers(application: Application):
    application.add_handler(CommandHandler("rooms",  cmd_rooms))
    application.add_handler(CommandHandler("create", cmd_create_private))
    application.add_handler(CommandHandler("join",   cmd_join_private))
    logger.info("Room handlers registered")
