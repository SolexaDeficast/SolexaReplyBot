import os
import logging
import asyncio
import fastapi
import uvicorn
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Enable detailed logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Read the bot token from the environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# Define the keywords and corresponding media files
keyword_responses = {
    "audio": "test.mp3",
    "secret": "secret.mp3",
    "video": "test.mp4",
    "profits": "PROFITS.jpg",
    "commercial": "commercial.mp4",
    "slut": "SLUT.jpg"
}

# FastAPI for keeping the Render service alive
app = fastapi.FastAPI()

@app.get("/")
def read_root():
    return {"status": "Bot is running"}

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_text = update.message.text.lower()
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                logger.info(f"Keyword '{keyword}' detected. Sending file: {media_file}")

                if not os.path.exists(media_file):
                    logger.error(f"File not found: {media_file}")
                    await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                    return

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

# Function to set up the webhook with retry logic
async def set_webhook(application: Application):
    if not RENDER_EXTERNAL_URL:
        logger.warning("RENDER_EXTERNAL_URL is not set. Falling back to polling.")
        return

    webhook_url = f"{RENDER_EXTERNAL_URL}/telegram"
    
    # Check if the webhook is already set
    current_webhook_info = await application.bot.get_webhook_info()
    if current_webhook_info.url == webhook_url:
        logger.info(f"Webhook is already set to: {webhook_url}")
        return

    # Try setting the webhook
    try:
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")

# Main function to start the bot
async def main():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        if RENDER_EXTERNAL_URL:
            await set_webhook(application)
            await application.initialize()
            await application.start()
        else:
            logger.info("Starting bot with polling...")
            await application.initialize()
            await application.start()
            await application.updater.start_polling()

        logger.info("Bot is running...")

        # Start FastAPI web server to keep Render alive
        config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
        server = uvicorn.Server(config)
        await server.serve()

    except Exception as e:
        logger.error(f"Error starting bot: {e}")

if __name__ == '__main__':
    asyncio.run(main())
