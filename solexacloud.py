import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL')  # Ensure this is set in Render's environment

# Keyword responses
keyword_responses = {
    "audio": "test.mp3",
    "secret": "secret.mp3",
    "video": "test.mp4",
    "profits": "PROFITS.jpg",
    "commercial": "commercial.mp4",
    "slut": "SLUT.jpg"
}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming text messages."""
    try:
        message_text = update.message.text.lower()
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                logger.info(f"Keyword '{keyword}' detected. Sending file: {media_file}")

                if not os.path.exists(media_file):
                    logger.error(f"File not found: {media_file}")
                    await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                    return

                # Send media based on file type
                if media_file.endswith('.mp3'):
                    await update.message.reply_audio(audio=open(media_file, 'rb'))
                elif media_file.endswith('.mp4'):
                    await update.message.reply_video(video=open(media_file, 'rb'))
                elif media_file.endswith('.jpg'):
                    await update.message.reply_photo(photo=open(media_file, 'rb'))
                break
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

async def main():
    """Starts the bot using webhook or polling."""
    application = Application.builder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/telegram"
        logger.info(f"Starting bot with webhook: {webhook_url}")
        
        await application.bot.set_webhook(f"{os.getenv('RENDER_EXTERNAL_URL')}/telegram")

# Start webhook
await application.initialize()
await application.start()
await application.updater.start_webhook(
    listen="0.0.0.0",
    port=int(os.getenv("PORT", 10000)),
    url_path="telegram"
)

    else:
        logger.info("Starting bot with polling...")
        await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
