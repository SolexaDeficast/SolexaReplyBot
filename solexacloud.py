import os
import logging
import asyncio
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL") + "/telegram"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize the bot properly
application = Application.builder().token(TOKEN).build()

async def start(update: Update, context):
    await update.message.reply_text("Hello! I am your bot.")

# Register handlers BEFORE processing updates
application.add_handler(CommandHandler("start", start))

@app.post("/telegram")
async def webhook(request: Request):
    """Handle incoming Telegram updates."""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.update_queue.put(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}")
    return {"status": "ok"}

async def start_bot():
    """Set the webhook and start the bot."""
    await application.initialize()  # FIX: Ensure Application is initialized
    await application.bot.delete_webhook()
    await application.bot.set_webhook(WEBHOOK_URL)
    await application.start()  # FIX: Properly start the bot
    logger.info(f"Webhook set to: {WEBHOOK_URL}")
    logger.info("Bot is running...")

if __name__ == "__main__":
    asyncio.run(start_bot())
