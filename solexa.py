import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# Read the bot token from the environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Define the keywords and corresponding media files
keyword_responses = {
    "audio": "test.mp3",       # When someone says "audio", reply with this audio
    "video": "test.mp4",       # When someone says "video", reply with this video
    "profits": "PROFITS.jpg",  # When someone says "profits", reply with PROFITS.jpg
    "slut": "SLUT.jpg"         # When someone says "slut", reply with SLUT.jpg
}

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_text = update.message.text.lower()  # Convert message to lowercase for case-insensitive matching

        # Check if the message contains any of the keywords
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                logger.debug(f"Keyword '{keyword}' detected. Sending file: {media_file}")

                # Check if the file exists
                if not os.path.exists(media_file):
                    logger.error(f"File not found: {media_file}")
                    await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                    return

                # Send the corresponding media file
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

# Main function to start the bot
async def main():
    try:
        # Create the Application and pass it your bot's token
        application = Application.builder().token(TOKEN).build()

        # Add a message handler to respond to text messages
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Start the bot
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        logger.info("Bot is running...")
        print("Bot is running...")

        # Keep the bot running until manually stopped
        while True:
            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        print(f"Error starting bot: {e}")

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())