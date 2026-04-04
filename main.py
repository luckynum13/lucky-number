"""
Lucky Number Bot — Main Entry Point
=====================================
Запуск: python main.py
"""

import os
import logging
import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from database import init_db, get_or_create_user, get_user_balance
from payments import setup_payment_handlers
from rooms import setup_room_handlers

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN", "8716061480:AAGCDc5OadCagPtSOvo_IvedhvMNgQ7uQCs")
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "https://lucky-number.fly.dev")
PORT         = int(os.getenv("PORT", "8080"))

# ─────────────────────────────────────────────
#  FASTAPI APP
# ─────────────────────────────────────────────
app = FastAPI(title="Lucky Number Bot")

# Bot application (global)
bot_app: Application = None


# ─────────────────────────────────────────────
#  BOT COMMANDS
# ─────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — welcome message + register user
    """
    user = update.effective_user
    await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    balance = await get_user_balance(user.id)

    await update.message.reply_text(
        f"🎰 *Welcome to Lucky Number!*\n\n"
        f"Hello, {user.first_name}!\n\n"
        f"💰 Your balance: *${balance}*\n\n"
        f"*How to play:*\n"
        f"• Join a room by paying the entry fee\n"
        f"• Get a random number\n"
        f"• When the room fills up — the draw happens\n"
        f"• Winners get 2× their bet!\n\n"
        f"*Commands:*\n"
        f"/play — open the game\n"
        f"/balance — check your balance\n"
        f"/deposit — add funds\n"
        f"/withdraw — withdraw winnings\n"
        f"/help — how to play",
        parse_mode="Markdown",
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /balance — show current balance
    """
    user = update.effective_user
    balance = await get_user_balance(user.id)

    await update.message.reply_text(
        f"💰 *Your balance:* ${balance}\n\n"
        f"Use /deposit to add funds\n"
        f"Use /play to join a game",
        parse_mode="Markdown",
    )


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /play — send Mini App link
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    mini_app_url = os.getenv("MINI_APP_URL", "https://your-github-username.github.io/lucky-number")

    keyboard = [[
        InlineKeyboardButton(
            text="🎰 Open Lucky Number",
            web_app=WebAppInfo(url=mini_app_url)
        )
    ]]

    await update.message.reply_text(
        "🎰 *Lucky Number*\n\nTap the button to open the game!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎰 *Lucky Number — How to Play*\n\n"
        "*Public rooms:* $5 / $10 / $20 / $50 / $100\n"
        "*Private rooms:* $20 to $500\n\n"
        "*Prize structure:*\n"
        "• 3 players → 1 winner gets 2× bet\n"
        "• 5 players → 2 winners get 2× bet each\n"
        "• 7 players → 3 winners get 2× bet each\n"
        "• 10 players → 4 winners get 2× bet each\n\n"
        "*You pay in local currency (AZN/RUB/KZT)*\n"
        "*Balance shown in USD*\n\n"
        "Support: @LuckyNumberSupport",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  TELEGRAM WEBHOOK ENDPOINT
# ─────────────────────────────────────────────
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Telegram sends all updates here.
    """
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return JSONResponse({"status": "ok"})


@app.get("/health")
# ─────────────────────────────────────────────
#  MINI APP API
# ─────────────────────────────────────────────
from rooms import ROOMS, calc_room, fisher_yates, PUBLIC_NOMINALS, PLAYER_COUNTS, PRIVATE_NOMINALS
import random as _random
@app.get("/api/me")
async def api_me(telegram_id: int):
    user = await get_or_create_user(telegram_id)
    balance = await get_user_balance(telegram_id)
    return {"telegram_id": telegram_id, "balance": float(balance)}

@app.get("/api/rooms")
async def api_rooms():
    public = []
    for nominal in PUBLIC_NOMINALS:
        for players in PLAYER_COUNTS:
            room_id = f"pub_{nominal}_{players}"
            if room_id not in ROOMS:
                calc = calc_room(nominal, players)
                ROOMS[room_id] = {
                    "id": room_id, "type": "public",
                    "nominal": nominal, "max_players": players,
                    "winners": calc["winners"], "each_prize": calc["each_prize"],
                    "platform_fee": calc["platform_fee"], "pot": calc["pot"],
                    "players": [], "game_started": False,
                }
            r = ROOMS[room_id]
            public.append({
                "id": r["id"], "nominal": r["nominal"],
                "max_players": r["max_players"], "winners": r["winners"],
                "each_prize": r["each_prize"], "platform_fee": r["platform_fee"],
                "pot": r["pot"], "player_count": len(r["players"]),
                "game_started": r["game_started"],
                "my_numbers": [],
            })
    return {"rooms": public}

@app.post("/api/join")
async def api_join(request: Request):
    data = await request.json()
    telegram_id = data.get("telegram_id")
    room_id = data.get("room_id")
    room = ROOMS.get(room_id)
    if not room:
        return JSONResponse({"ok": False, "error": "Room not found"}, status_code=404)
    if room["game_started"]:
        return JSONResponse({"ok": False, "error": "Game already started"}, status_code=400)
    if len(room["players"]) >= room["max_players"]:
        return JSONResponse({"ok": False, "error": "Room is full"}, status_code=400)
    from decimal import Decimal
    balance = await get_user_balance(telegram_id)
    if balance < room["nominal"]:
        return JSONResponse({"ok": False, "error": "Insufficient balance"}, status_code=400)
    taken = [p["number"] for p in room["players"]]
    available = [n for n in range(1, room["max_players"] + 1) if n not in taken]
    number = _random.choice(available)
    tx_id = f"bet_{room_id}_{telegram_id}_{number}"
    from database import debit_user_balance, is_duplicate_tx
    if await is_duplicate_tx(tx_id):
        return JSONResponse({"ok": False, "error": "Already joined"}, status_code=400)
    success = await debit_user_balance(telegram_id, Decimal(str(room["nominal"])), tx_id)
    if not success:
        return JSONResponse({"ok": False, "error": "Payment failed"}, status_code=400)
    room["players"].append({"telegram_id": telegram_id, "number": number})
    new_balance = await get_user_balance(telegram_id)
    if len(room["players"]) == room["max_players"] and not room["game_started"]:
        import asyncio
        from rooms import run_game_draw
        asyncio.create_task(run_game_draw(room_id, bot_app.bot))
    return {"ok": True, "number": number, "balance": float(new_balance),
            "player_count": len(room["players"])}

@app.post("/api/create-private")
async def api_create_private(request: Request):
    data = await request.json()
    telegram_id = data.get("telegram_id")
    nominal = data.get("nominal")
    players = data.get("players")
    from decimal import Decimal
    balance = await get_user_balance(telegram_id)
    if balance < nominal:
        return JSONResponse({"ok": False, "error": "Insufficient balance"}, status_code=400)
    calc = calc_room(nominal, players)
    import random as rnd
    code = ''.join(rnd.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
    room_id = f"prv_{code}"
    tx_id = f"bet_{room_id}_{telegram_id}"
    from database import debit_user_balance
    success = await debit_user_balance(telegram_id, Decimal(str(nominal)), tx_id)
    if not success:
        return JSONResponse({"ok": False, "error": "Payment failed"}, status_code=400)
    ROOMS[room_id] = {
        "id": room_id, "type": "private",
        "nominal": nominal, "max_players": players,
        "winners": calc["winners"], "each_prize": calc["each_prize"],
        "platform_fee": calc["platform_fee"], "pot": calc["pot"],
        "invite_code": code, "creator_id": telegram_id,
        "players": [{"telegram_id": telegram_id, "number": 1}],
        "game_started": False,
    }
    new_balance = await get_user_balance(telegram_id)
    return {"ok": True, "invite_code": code, "room_id": room_id, "balance": float(new_balance)}

@app.post("/api/join-private")
async def api_join_private(request: Request):
    data = await request.json()
    telegram_id = data.get("telegram_id")
    code = data.get("invite_code", "").upper()
    room = next((r for r in ROOMS.values() if r.get("invite_code") == code), None)
    if not room:
        return JSONResponse({"ok": False, "error": "Room not found"}, status_code=404)
    if room["game_started"] or len(room["players"]) >= room["max_players"]:
        return JSONResponse({"ok": False, "error": "Room is full"}, status_code=400)
    from decimal import Decimal
    balance = await get_user_balance(telegram_id)
    if balance < room["nominal"]:
        return JSONResponse({"ok": False, "error": "Insufficient balance"}, status_code=400)
    taken = [p["number"] for p in room["players"]]
    available = [n for n in range(1, room["max_players"] + 1) if n not in taken]
    number = _random.choice(available)
    tx_id = f"bet_{room['id']}_{telegram_id}_{number}"
    from database import debit_user_balance
    success = await debit_user_balance(telegram_id, Decimal(str(room["nominal"])), tx_id)
    if not success:
        return JSONResponse({"ok": False, "error": "Payment failed"}, status_code=400)
    room["players"].append({"telegram_id": telegram_id, "number": number})
    new_balance = await get_user_balance(telegram_id)
    if len(room["players"]) == room["max_players"]:
        import asyncio
        from rooms import run_game_draw
        asyncio.create_task(run_game_draw(room["id"], bot_app.bot))
    return {"ok": True, "number": number, "balance": float(new_balance),
            "invite_code": code, "player_count": len(room["players"])}

@app.get("/api/private-rooms")
async def api_private_rooms(telegram_id: int):
    rooms = []
    for r in ROOMS.values():
        if r.get("type") == "private":
            is_member = any(p["telegram_id"] == telegram_id for p in r["players"])
            if is_member or r.get("creator_id") == telegram_id:
                rooms.append({
                    "id": r["id"], "nominal": r["nominal"],
                    "max_players": r["max_players"], "winners": r["winners"],
                    "each_prize": r["each_prize"], "invite_code": r.get("invite_code"),
                    "player_count": len(r["players"]), "game_started": r["game_started"],
                })
    return {"rooms": rooms}
async def health():
    return {"status": "ok", "service": "Lucky Number Bot"}


# ─────────────────────────────────────────────
#  SMART GLOCAL WEBHOOK ENDPOINT
# ─────────────────────────────────────────────
@app.post("/webhook/smart-glocal")
async def smart_glocal_webhook(request: Request):
    """
    Smart Glocal payment notifications.
    Imported from payments.py
    """
    from payments import smart_glocal_webhook as sg_handler
    return await sg_handler(request)


# ─────────────────────────────────────────────
#  STARTUP / SHUTDOWN
# ─────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global bot_app

    # Init database
    await init_db()
    logger.info("Database initialized")

    # Build bot application
    bot_app = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    bot_app.add_handler(CommandHandler("start",   cmd_start))
    bot_app.add_handler(CommandHandler("balance", cmd_balance))
    bot_app.add_handler(CommandHandler("play",    cmd_play))
    bot_app.add_handler(CommandHandler("help",    cmd_help))

    # Register payment handlers (from payments.py)
    setup_payment_handlers(bot_app)

    # Register room handlers (from rooms.py)
    setup_room_handlers(bot_app)

    # Initialize bot
    await bot_app.initialize()
    await bot_app.start()

    # Set Telegram webhook
    webhook_url = f"{WEBHOOK_URL}/webhook/telegram"
    await bot_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
    )
    logger.info(f"Webhook set: {webhook_url}")


@app.on_event("shutdown")
async def shutdown():
    if bot_app:
        await bot_app.stop()
        await bot_app.shutdown()
    logger.info("Bot stopped")


# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
