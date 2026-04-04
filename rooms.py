"""
Lucky Number Bot — Room & Game Logic
"""

import os
import random
import logging
from decimal import Decimal

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from database import (
    get_user_balance,
    debit_user_balance,
    credit_win,
    is_duplicate_tx,
    get_or_create_user,
)

logger = logging.getLogger(__name__)

PUBLIC_NOMINALS  = [5, 10, 20, 50, 100]
PRIVATE_NOMINALS = [20, 50, 100, 200, 300, 400, 500]
PLAYER_COUNTS    = [3, 5, 7, 10]
ROOM_CONFIG = {
    3:  {"winners": 1},
    5:  {"winners": 2},
    7:  {"winners": 3},
    10: {"winners": 4},
}

# In-memory rooms storage
ROOMS = {}


def calc_room(nominal, players):
    cfg = ROOM_CONFIG[players]
    pot = nominal * players
    each_prize = nominal * 2
    platform_fee = pot - (each_prize * cfg["winners"])
    return {"pot": pot, "each_prize": each_prize,
            "platform_fee": platform_fee, "winners": cfg["winners"]}


def fisher_yates(lst):
    arr = lst[:]
    for i in range(len(arr) - 1, 0, -1):
        j = random.randint(0, i)
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def gen_code():
    return ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))


async def run_game_draw(room_id, bot):
    room = ROOMS.get(room_id)
    if not room or room.get("game_started"):
        return
    room["game_started"] = True

    players = room["players"]
    shuffled = fisher_yates(players)
    winners = shuffled[:room["winners"]]
    winner_ids = [w["telegram_id"] for w in winners]

    for w in winners:
        tx_id = f"win_{room_id}_{w['telegram_id']}_{w['number']}"
        if not await is_duplicate_tx(tx_id):
            await credit_win(
                telegram_id=w["telegram_id"],
                amount_usd=Decimal(str(room["each_prize"])),
                tx_id=tx_id,
            )

    for p in players:
        is_winner = p["telegram_id"] in winner_ids
        try:
            if is_winner:
                await bot.send_message(
                    chat_id=p["telegram_id"],
                    text=f"🎉 *YOU WON!*\n\nYour number *{p['number']}* won!\n"
                         f"💰 *+${room['each_prize']}* added to your balance!\n\n"
                         f"Use /balance to check · /play to play again 🎰",
                    parse_mode="Markdown",
                )
            else:
                winner_nums = ', '.join(str(w['number']) for w in winners)
                await bot.send_message(
                    chat_id=p["telegram_id"],
                    text=f"😢 *Better luck next time!*\n\n"
                         f"Your number: *{p['number']}*\n"
                         f"🏆 Winners: *{winner_nums}*\n\n"
                         f"Use /play to try again! 🎰",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(f"Could not notify {p['telegram_id']}: {e}")

    del ROOMS[room_id]


async def cmd_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["🎲 *Public Rooms:*\n"]
    for nominal in PUBLIC_NOMINALS:
        for players in PLAYER_COUNTS:
            c = calc_room(nominal, players)
            lines.append(f"• *${nominal}* · {players} players · "
                         f"{c['winners']} winner(s) → ${c['each_prize']} each")
    lines.append("\n🎰 Use /play to open the game!")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_create_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "Usage: /create <amount> <players>\nExample: /create 50 5\n\n"
            f"Amounts: {', '.join(f'${n}' for n in PRIVATE_NOMINALS)}\n"
            f"Players: {', '.join(str(p) for p in PLAYER_COUNTS)}"
        )
        return

    try:
        nominal = int(args[0])
        players = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid numbers.")
        return

    if nominal not in PRIVATE_NOMINALS:
        await update.message.reply_text(f"❌ Invalid amount.")
        return
    if players not in PLAYER_COUNTS:
        await update.message.reply_text(f"❌ Invalid player count.")
        return

    balance = await get_user_balance(update.effective_user.id)
    if balance < nominal:
        await update.message.reply_text(
            f"❌ Insufficient balance.\nYou have: ${balance}\n"
            f"Required: ${nominal}\n\nUse /deposit to add funds."
        )
        return

    calc = calc_room(nominal, players)
    code = gen_code()
    room_id = f"prv_{code}"

    tx_id = f"bet_{room_id}_{update.effective_user.id}"
    success = await debit_user_balance(
        telegram_id=update.effective_user.id,
        amount_usd=Decimal(str(nominal)),
        tx_id=tx_id,
    )
    if not success:
        await update.message.reply_text("❌ Payment failed.")
        return

    ROOMS[room_id] = {
        "id": room_id,
        "type": "private",
        "nominal": nominal,
        "max_players": players,
        "winners": calc["winners"],
        "each_prize": calc["each_prize"],
        "platform_fee": calc["platform_fee"],
        "pot": calc["pot"],
        "invite_code": code,
        "creator_id": update.effective_user.id,
        "players": [{"telegram_id": update.effective_user.id, "number": 1}],
        "game_started": False,
    }

    await update.message.reply_text(
        f"✅ *Private room created!*\n\n"
        f"💰 Bet: *${nominal}* · 👥 Players: *{players}*\n"
        f"🏆 {calc['winners']} winner(s) → *${calc['each_prize']}* each\n\n"
        f"🔑 Invite code: `{code}`\n\n"
        f"Friends join with: /join {code}",
        parse_mode="Markdown",
    )


async def cmd_join_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /join <code>")
        return

    code = args[0].upper()
    telegram_id = update.effective_user.id
    room = next((r for r in ROOMS.values() if r.get("invite_code") == code), None)

    if not room:
        await update.message.reply_text("❌ Room not found.")
        return

    if room["game_started"] or len(room["players"]) >= room["max_players"]:
        await update.message.reply_text("❌ Room is full or game already started.")
        return

    balance = await get_user_balance(telegram_id)
    if balance < room["nominal"]:
        await update.message.reply_text(
            f"❌ Insufficient balance.\nRequired: ${room['nominal']}\n\n"
            f"Use /deposit to add funds."
        )
        return

    taken = [p["number"] for p in room["players"]]
    available = [n for n in range(1, room["max_players"] + 1) if n not in taken]
    number = random.choice(available)

    tx_id = f"bet_{room['id']}_{telegram_id}_{number}"
    success = await debit_user_balance(
        telegram_id=telegram_id,
        amount_usd=Decimal(str(room["nominal"])),
        tx_id=tx_id,
    )
    if not success:
        await update.message.reply_text("❌ Payment failed.")
        return

    room["players"].append({"telegram_id": telegram_id, "number": number})
    new_count = len(room["players"])

    await update.message.reply_text(
        f"✅ *You joined!*\n\n"
        f"🎲 Your number: *{number}*\n"
        f"👥 Players: *{new_count}/{room['max_players']}*\n\n"
        f"{'🎰 Room full — drawing now!' if new_count == room['max_players'] else '⏳ Waiting for players...'}",
        parse_mode="Markdown",
    )

    if new_count == room["max_players"]:
        import asyncio
        asyncio.create_task(run_game_draw(room["id"], context.bot))


def setup_room_handlers(application: Application):
    application.add_handler(CommandHandler("rooms",  cmd_rooms))
    application.add_handler(CommandHandler("create", cmd_create_private))
    application.add_handler(CommandHandler("join",   cmd_join_private))
    logger.info("Room handlers registered")
