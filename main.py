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
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "")   # e.g. https://your-app.fly.dev
PORT         = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set!")

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
