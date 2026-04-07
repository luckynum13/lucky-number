"""
Lucky Number Bot — @Nomer_13bot
Railway deployment with FastAPI + python-telegram-bot
"""
import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, Bot
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = "https://luckynum13.github.io/lucky-number/"
SUPPORT_USERNAME = "LuckyNumberSupport"
CHANNEL_URL = "https://t.me/LuckyNumberChannel"

app = FastAPI()
bot = Bot(token=BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()


# ─── HELPERS ───

def fNum(v):
    """Format number with spaces: 1280000 -> '1 280 000'"""
    return f"{int(v):,}".replace(",", " ")

def fShort(v):
    """Short format: 1000000 -> '1 млн', 500000 -> '500 000'"""
    if v >= 1_000_000:
        m = v / 1_000_000
        return f"{int(m)} млн" if m == int(m) else f"{m:.1f} млн"
    return fNum(v)


def main_keyboard():
    """Main menu inline keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎮 Открыть игру",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [
            InlineKeyboardButton("💳 Пополнить", callback_data="deposit"),
            InlineKeyboardButton("💸 Вывести", callback_data="withdraw"),
        ],
        [InlineKeyboardButton(
            "👥 Играть с друзьями",
            web_app=WebAppInfo(url=WEBAPP_URL + "?action=create_private")
        )],
        [InlineKeyboardButton("📊 Мои результаты", callback_data="results")],
        [
            InlineKeyboardButton("📢 Наш канал", url=CHANNEL_URL),
            InlineKeyboardButton("📞 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"),
        ],
    ])


def quick_play_keyboard():
    """Quick keyboard for non-command messages"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎮 Открыть Lucky Number",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
    ])


def share_keyboard(code, nom, max_players):
    """Share buttons after creating a private room"""
    share_text = (
        f"🎰 Lucky Number\n\n"
        f"Ставка: {fNum(nom)} сўм · {max_players} игроков\n"
        f"Код: {code}\n\n"
        f"Присоединяйся!"
    )
    tg_share_url = (
        f"https://t.me/share/url"
        f"?url=https://t.me/Nomer_13bot"
        f"&text={share_text}"
    )
    wa_share_url = f"https://wa.me/?text={share_text}"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📲 Telegram", url=tg_share_url),
            InlineKeyboardButton("📲 WhatsApp", url=wa_share_url),
        ],
        [InlineKeyboardButton("🔗 Скопировать код", callback_data=f"copy_{code}")],
        [InlineKeyboardButton(
            "🎮 Открыть игру",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
    ])


# ─── HANDLERS ───

async def start_handler(update: Update, context):
    """Handle /start command — main welcome message"""
    user = update.effective_user
    name = user.first_name or user.username or "Игрок"

    welcome_text = (
        f"🎰 *Lucky Number*\n\n"
        f"Привет, {name}! 👋\n"
        f"Добро пожаловать в Lucky Number — "
        f"честная лотерея с моментальными выплатами!\n\n"
        f"─────────────────\n"
        f"✅ Честная игра\n"
        f"⚡ Моментальные выплаты\n"
        f"🔒 Безопасные платежи\n"
        f"─────────────────\n\n"
        f"💳 *Платежи:* P2P (UZcard, HUMO, Payme)\n"
        f"📥 Пополнение: комиссия 4%\n"
        f"📤 Вывод: комиссия 2% · от 2 до 24 ч\n\n"
        f"*Ставки:*\n"
        f"60 000 · 150 000 · 500 000\n"
        f"1 000 000 · 2 500 000 сўм\n\n"
        f"Выбери действие 👇"
    )

    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


async def help_handler(update: Update, context):
    """Handle /help command"""
    help_text = (
        "❓ *Как играть:*\n\n"
        "1️⃣ Выбери комнату и внеси ставку\n"
        "2️⃣ Получи случайный номер\n"
        "3️⃣ Жди, пока все места заполнятся\n"
        "4️⃣ Победители получают *×2* от ставки!\n\n"
        "Все номера открыты — система прозрачная.\n\n"
        "📞 Поддержка: @LuckyNumberSupport"
    )
    await update.message.reply_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=quick_play_keyboard()
    )


async def any_message_handler(update: Update, context):
    """Handle any text message — always give a play button"""
    user = update.effective_user
    name = user.first_name or user.username or "Игрок"

    await update.message.reply_text(
        f"Привет, {name}! 🎰\n"
        f"Нажми кнопку, чтобы начать игру!",
        reply_markup=quick_play_keyboard()
    )


async def callback_handler(update: Update, context):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "deposit":
        await query.message.reply_text(
            "💳 *Пополнение баланса*\n\n"
            "Способ: P2P (UZcard, HUMO, Payme)\n"
            "Комиссия: 4%\n"
            "Мин: 30 000 сўм\n"
            "Макс: 5 700 000 сўм\n\n"
            "Средства поступят мгновенно.\n\n"
            "Для пополнения откройте игру 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🎮 Открыть игру",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )],
            ])
        )

    elif data == "withdraw":
        await query.message.reply_text(
            "💸 *Вывод средств*\n\n"
            "Способ: P2P (UZcard, HUMO, Payme)\n"
            "Комиссия: 2%\n"
            "Мин: 30 000 сўм\n"
            "Макс: 5 700 000 сўм\n"
            "Срок: от 2 до 24 часов\n\n"
            "Средства поступят на вашу карту.\n\n"
            f"📞 Для вывода напишите: @{SUPPORT_USERNAME}",
            parse_mode="Markdown",
        )

    elif data == "results":
        await query.message.reply_text(
            "📊 *Мои результаты*\n\n"
            "Вся статистика доступна в игре — "
            "откройте вкладку «История» 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🎮 Открыть игру",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )],
            ])
        )

    elif data.startswith("copy_"):
        code = data.replace("copy_", "")
        await query.message.reply_text(
            f"📋 Код комнаты: `{code}`\n\n"
            f"Отправь этот код друзьям!",
            parse_mode="Markdown",
        )


# ─── REGISTER HANDLERS ───

application.add_handler(CommandHandler("start", start_handler))
application.add_handler(CommandHandler("play", start_handler))
application.add_handler(CommandHandler("help", help_handler))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    any_message_handler
))


# ─── FASTAPI ROUTES ───

@app.on_event("startup")
async def on_startup():
    """Set webhook on startup"""
    await application.initialize()
    await application.start()

    # Get Railway URL or use custom domain
    railway_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if railway_url:
        webhook_url = f"https://{railway_url}/webhook"
        await bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set: {webhook_url}")

        # Set menu button to open the webapp
        try:
            from telegram import MenuButtonWebApp
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🎰 Играть",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            )
            logger.info("Menu button set")
        except Exception as e:
            logger.warning(f"Could not set menu button: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()


@app.post("/webhook")
async def webhook(request: Request):
    """Process incoming Telegram updates"""
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        await application.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return JSONResponse({"ok": True})


@app.get("/")
async def root():
    return {"status": "Lucky Number Bot is running", "bot": "@Nomer_13bot"}


@app.get("/health")
async def health():
    return {"status": "ok"}
