import os
import logging
import asyncio
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL_PATH = "/telegram"
WEBHOOK_URL = f"{os.getenv('EXTERNAL_URL')}{WEBHOOK_URL_PATH}"

app = FastAPI()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

@app.post(WEBHOOK_URL_PATH)
async def receive_update(request: Request):
    """Handle incoming Telegram updates."""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return {"status": "error", "message": str(e)}

async def start_bot():
    """Set up webhook and start the bot."""
    logger.info(f"Setting webhook to {WEBHOOK_URL}")
    await application.bot.set_webhook(WEBHOOK_URL)
    logger.info("Webhook set successfully!")

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running...")

def start_command(update: Update, context: CallbackContext):
    """Respond to /start command."""
    update.message.reply_text("Hello! I am your bot.")

def handle_message(update: Update, context: CallbackContext):
    """Handle text messages."""
    text = update.message.text
    update.message.reply_text(f"You said: {text}")

if __name__ == "__main__":
    # Run the FastAPI app and start the bot
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
