import os
import logging
import asyncio
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"  # Ensure this is set in Render

# Define the keywords and corresponding media files
keyword_responses = {
    "audio": "test.mp3",
    "secret": "secret.mp3",
    "video": "test.mp4",
    "profits": "PROFITS.jpg",
    "commercial": "commercial.mp4",
    "slut": "SLUT.jpg"
}

# Initialize FastAPI app
app = FastAPI()

# Initialize the Telegram bot application
application = Application.builder().token(TOKEN).build()

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            message_text = update.message.text.lower()

            # Check for keywords
            for keyword, media_file in keyword_responses.items():
                if keyword in message_text:
                    logger.info(f"Keyword '{keyword}' detected. Sending file: {media_file}")

                    # Check if the file exists
                    if not os.path.exists(media_file):
                        logger.error(f"File not found: {media_file}")
                        await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                        return

                    # Send appropriate media
                    with open(media_file, 'rb') as media:
                        if media_file.endswith('.mp3'):
                            await update.message.reply_audio(audio=media)
                        elif media_file.endswith('.mp4'):
                            await update.message.reply_video(video=media)
                        elif media_file.endswith('.jpg'):
                            await update.message.reply_photo(photo=media)
                    break  # Stop after first match
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

# Add the message handler to the application
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Webhook endpoint to receive Telegram updates
@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)

        # Ensure the bot application is initialized before processing updates
        if not application.running:
            logger.warning("Application is not running. Initializing now...")
            await application.initialize()
            await application.start()

        await application.process_update(update)
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")

# Function to start the bot
async def start_bot():
    try:
        logger.info("Starting bot initialization...")

        # Initialize and start the bot
        await application.initialize()
        await application.start()

        # Set webhook
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to: {WEBHOOK_URL}")

        logger.info("Bot is fully running...")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

# Ensure FastAPI and Telegram bot run together properly
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_bot())  # Start bot as background task
