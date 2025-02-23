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

# Initialize the bot
application = Application.builder().token(TOKEN).build()

@app.post("/telegram")
async def webhook(request: Request):
    """Handle incoming Telegram updates."""
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return {"status": "ok"}

async def start_bot():
    """Set the webhook and start the bot."""
    await application.bot.delete_webhook()
    await application.bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to: {WEBHOOK_URL}")
    logger.info("Bot is running...")

# Define a simple command
async def start(update: Update, context):
    await update.message.reply_text("Hello! I am your bot.")

application.add_handler(CommandHandler("start", start))

if __name__ == "__main__":
    asyncio.run(start_bot())
