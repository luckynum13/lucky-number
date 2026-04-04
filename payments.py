"""
Lucky Number — Smart Glocal Payment Integration
================================================
Handles: deposit via Telegram Payments + Smart Glocal
         withdraw notifications
         Smart Glocal webhook (payment_finished)

Environment variables needed:
  BOT_TOKEN          — Telegram bot token from BotFather
  SMART_GLOCAL_TOKEN — provider_token from BotFather after connecting Smart Glocal
  WEBHOOK_SECRET     — any random string to verify Smart Glocal webhooks
  DATABASE_URL       — your DB connection string
"""

import os
import hmac
import hashlib
import logging
from decimal import Decimal

from fastapi import APIRouter, Request, HTTPException
from telegram import Bot, LabeledPrice, Update
from telegram.ext import (
    Application,
    CommandHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN           = os.getenv("BOT_TOKEN", "")
SMART_GLOCAL_TOKEN  = os.getenv("SMART_GLOCAL_TOKEN", "")  # from BotFather
WEBHOOK_SECRET      = os.getenv("WEBHOOK_SECRET", "change_me")

# Deposit options in USD (amount shown to player)
DEPOSIT_OPTIONS_USD = [5, 10, 20, 50, 100]

# AZN is pegged to USD — Smart Glocal handles conversion automatically
# Telegram Payments amount is always in cents (USD × 100)

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  DATABASE HELPERS  (adapt to your ORM/DB)
# ─────────────────────────────────────────────
async def get_user_balance(telegram_id: int) -> Decimal:
    """Return user's balance in USD."""
    # TODO: replace with your DB query
    # Example (SQLAlchemy async):
    #   result = await db.execute(
    #       select(User.balance_usd).where(User.telegram_id == telegram_id)
    #   )
    #   return result.scalar_one_or_none() or Decimal("0")
    raise NotImplementedError


async def credit_user_balance(telegram_id: int, amount_usd: Decimal, tx_id: str):
    """Add amount_usd to user balance, record transaction."""
    # TODO: replace with your DB logic
    # Example:
    #   async with db.begin():
    #       await db.execute(
    #           update(User)
    #           .where(User.telegram_id == telegram_id)
    #           .values(balance_usd=User.balance_usd + amount_usd)
    #       )
    #       await db.execute(
    #           insert(Transaction).values(
    #               telegram_id=telegram_id,
    #               amount_usd=amount_usd,
    #               tx_id=tx_id,
    #               type="deposit"
    #           )
    #       )
    raise NotImplementedError


async def is_duplicate_tx(tx_id: str) -> bool:
    """Check if transaction already processed (idempotency)."""
    # TODO: check your transactions table
    raise NotImplementedError


# ─────────────────────────────────────────────
#  BOT HANDLERS
# ─────────────────────────────────────────────
async def cmd_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /deposit — shows deposit options as inline buttons.
    Called when user taps 'Deposit' in Mini App or sends /deposit.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Build inline keyboard with deposit amounts
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = [
        [InlineKeyboardButton(f"${amt}", callback_data=f"deposit_{amt}")]
        for amt in DEPOSIT_OPTIONS_USD
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "💳 *Choose deposit amount:*\n\n"
        "You pay in your local currency (AZN/RUB/KZT).\n"
        "Your balance is credited in USD.",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def handle_deposit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    User tapped a deposit amount button → send invoice.
    """
    query = update.callback_query
    await query.answer()

    amount_usd = int(query.data.split("_")[1])
    telegram_id = query.from_user.id
    chat_id = query.message.chat_id

    await send_deposit_invoice(
        bot=context.bot,
        chat_id=chat_id,
        telegram_id=telegram_id,
        amount_usd=amount_usd,
    )


async def send_deposit_invoice(
    bot: Bot,
    chat_id: int,
    telegram_id: int,
    amount_usd: int,
):
    """
    Send a Telegram payment invoice via Smart Glocal.

    Smart Glocal accepts EUR base, but via Telegram Payments
    you can send USD — conversion happens automatically on their side.

    amount in Telegram is always in CENTS:
      $10  → 1000
      $50  → 5000
      $100 → 10000
    """
    amount_cents = amount_usd * 100  # USD → cents

    await bot.send_invoice(
        chat_id=chat_id,

        # Invoice title and description shown to user
        title=f"Lucky Number — Deposit ${amount_usd}",
        description=(
            f"Top up your Lucky Number balance by ${amount_usd}.\n"
            f"You pay in your local currency at current rate."
        ),

        # payload — we store user's telegram_id so we know
        # who to credit when payment succeeds
        payload=f"deposit:{telegram_id}:{amount_usd}",

        # Smart Glocal provider token from BotFather
        provider_token=SMART_GLOCAL_TOKEN,

        # Currency — USD (Smart Glocal converts AZN→EUR internally)
        currency="USD",

        # Prices array — amount in cents
        prices=[LabeledPrice(label=f"Deposit ${amount_usd}", amount=amount_cents)],

        # Optional: provider_data for Smart Glocal extra fields
        provider_data={
            # Smart Glocal uses this as customer reference
            "customer_reference": str(telegram_id),
        },

        # UX options
        need_phone_number=False,
        need_email=False,
        need_name=False,
        send_phone_number_to_provider=False,
        send_email_to_provider=False,

        # Allow saving card for recurring deposits (optional)
        # is_flexible=False,
    )

    logger.info(
        f"Invoice sent: user={telegram_id} amount=${amount_usd}"
    )


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Telegram calls this before charging the user.
    We MUST respond within 10 seconds with ok=True or ok=False.

    This is our last chance to validate the order before money moves.
    """
    query = update.pre_checkout_query

    try:
        # Parse payload
        parts = query.invoice_payload.split(":")
        if parts[0] != "deposit" or len(parts) != 3:
            raise ValueError("Invalid payload format")

        telegram_id = int(parts[1])
        amount_usd  = int(parts[2])

        # Basic validation
        if amount_usd not in DEPOSIT_OPTIONS_USD:
            raise ValueError(f"Invalid amount: {amount_usd}")

        if query.from_user.id != telegram_id:
            raise ValueError("User ID mismatch")

        # All good — approve payment
        await query.answer(ok=True)
        logger.info(f"PreCheckout approved: user={telegram_id} amount=${amount_usd}")

    except Exception as e:
        logger.error(f"PreCheckout rejected: {e}")
        await query.answer(
            ok=False,
            error_message="Payment validation failed. Please try again."
        )


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called when Telegram confirms payment was successful.
    This is the FINAL confirmation — safe to credit balance here.

    Note: Smart Glocal will ALSO send payment_finished webhook —
    use EITHER this OR the webhook, not both, to avoid double-crediting.
    We use this handler as primary (simpler) and webhook as backup.
    """
    payment = update.message.successful_payment
    telegram_id = update.effective_user.id

    # Parse payload
    parts = payment.invoice_payload.split(":")
    amount_usd  = Decimal(parts[2])
    tx_id       = payment.provider_payment_charge_id  # Smart Glocal transaction ID

    # Idempotency check — prevent double credit
    if await is_duplicate_tx(tx_id):
        logger.warning(f"Duplicate tx ignored: {tx_id}")
        return

    # Credit user balance
    await credit_user_balance(
        telegram_id=telegram_id,
        amount_usd=amount_usd,
        tx_id=tx_id,
    )

    logger.info(
        f"Payment successful: user={telegram_id} "
        f"amount=${amount_usd} tx={tx_id}"
    )

    # Notify user in bot
    await update.message.reply_text(
        f"✅ *Payment confirmed!*\n\n"
        f"💰 *+${amount_usd}* added to your Lucky Number balance.\n"
        f"Transaction ID: `{tx_id}`\n\n"
        f"Open the game to start playing! 🎰",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  SMART GLOCAL WEBHOOK  (FastAPI route)
# ─────────────────────────────────────────────
@router.post("/webhook/smart-glocal")
async def smart_glocal_webhook(request: Request):
    """
    Smart Glocal sends payment_finished webhook to this endpoint.
    We use it as a BACKUP to successful_payment_handler above.

    Setup: tell your Smart Glocal account manager to send webhooks to:
    https://yourdomain.com/webhook/smart-glocal
    """
    # Verify webhook signature
    signature = request.headers.get("X-PARTNER-SIGN", "")
    body = await request.body()

    expected_sig = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        logger.warning("Invalid Smart Glocal webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = await request.json()
    webhook_type = data.get("type")

    if webhook_type == "payment_finished":
        await handle_payment_finished(data)

    # Must return 200 OK to Smart Glocal
    return {"status": "ok"}


async def handle_payment_finished(data: dict):
    """
    Process payment_finished webhook from Smart Glocal.
    Used as backup in case Telegram's SuccessfulPayment message was missed.
    """
    session = data.get("session", {})
    session_status = session.get("status")

    # Only process accepted (successful) payments
    if session_status != "accepted":
        logger.info(f"Non-accepted payment_finished: status={session_status}")
        return

    # Get payment details (API v2 format)
    payments = session.get("acquiring_payments", [])
    for payment in payments:
        if payment.get("status") != "succeeded":
            continue

        tx_id        = payment.get("id")
        customer_ref = payment.get("customer", {}).get("reference", "")
        amount_data  = payment.get("amount_details", {})
        amount_cents = amount_data.get("amount", 0)
        currency     = amount_data.get("currency", "usd").upper()

        # Convert cents to USD
        amount_usd = Decimal(amount_cents) / 100

        try:
            telegram_id = int(customer_ref)
        except (ValueError, TypeError):
            logger.error(f"Invalid customer reference: {customer_ref}")
            continue

        # Idempotency — skip if already processed via SuccessfulPayment handler
        if await is_duplicate_tx(tx_id):
            logger.info(f"Webhook: tx already processed: {tx_id}")
            continue

        # Credit balance
        await credit_user_balance(
            telegram_id=telegram_id,
            amount_usd=amount_usd,
            tx_id=tx_id,
        )

        logger.info(
            f"Webhook credited: user={telegram_id} "
            f"amount=${amount_usd} tx={tx_id} currency={currency}"
        )


# ─────────────────────────────────────────────
#  WITHDRAW HANDLER
# ─────────────────────────────────────────────
async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /withdraw — manual process via support for now.
    Smart Glocal payouts API can be added later for automation.
    """
    telegram_id = update.effective_user.id

    try:
        balance = await get_user_balance(telegram_id)
    except NotImplementedError:
        balance = Decimal("0")

    await update.message.reply_text(
        f"💸 *Withdraw funds*\n\n"
        f"Your balance: *${balance}*\n\n"
        f"To withdraw, contact support:\n"
        f"👉 @LuckyNumberSupport\n\n"
        f"Minimum withdrawal: *$10*\n"
        f"Processed within 24 hours.",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  BOT APPLICATION SETUP
# ─────────────────────────────────────────────
def setup_payment_handlers(application: Application):
    """
    Call this from your main bot setup to register all payment handlers.

    Example in main.py:
        from payments import setup_payment_handlers
        setup_payment_handlers(application)
    """
    from telegram.ext import CallbackQueryHandler

    application.add_handler(CommandHandler("deposit", cmd_deposit))
    application.add_handler(CommandHandler("withdraw", cmd_withdraw))

    # Callback for deposit amount buttons
    application.add_handler(
        CallbackQueryHandler(handle_deposit_callback, pattern=r"^deposit_\d+$")
    )

    # CRITICAL: PreCheckout must be answered within 10 seconds
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))

    # Successful payment confirmation from Telegram
    application.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler)
    )

    logger.info("Payment handlers registered")
