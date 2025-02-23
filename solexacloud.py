import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read the bot token from the environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Define the keywords and corresponding media files
keyword_responses = {
    "audio": "test.mp3",
    "secret": "secret.mp3",
    "video": "test.mp4",
    "profits": "PROFITS.jpg",
    "commercial": "commercial.mp4",
    "slut": "SLUT.jpg"
}

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_text = update.message.text.lower()  # Convert message to lowercase

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

# Function to set up the webhook
async def set_webhook(application: Application):
    webhook_url = os.getenv('RENDER_EXTERNAL_URL')
    if webhook_url:
        webhook_url += "/telegram"
    else:
        logger.warning("RENDER_EXTERNAL_URL is not set. Falling back to polling.")
        return

    current_webhook_info = await application.bot.get_webhook_info()
    if current_webhook_info.url == webhook_url:
        logger.info(f"Webhook is already set to: {webhook_url}")
        return

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

        if os.getenv('RENDER_EXTERNAL_URL'):
            await set_webhook(application)

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
            await application.initialize()
            await application.start()
            await application.updater.start_polling()

        logger.info("Bot is running...")
        print("Bot is running...")

        while True:
            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        print(f"Error starting bot: {e}")

if __name__ == '__main__':
    asyncio.run(main())
