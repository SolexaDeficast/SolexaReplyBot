import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Read the bot token from the environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Define the keywords and corresponding media files
keyword_responses = {
    "audio": "test.mp3",       # When someone says "audio", reply with this audio
    "secret": "secret.mp3",       # When someone says "secret", reply with this audio
    "video": "test.mp4",       # When someone says "video", reply with this video
    "profits": "PROFITS.jpg",  # When someone says "profits", reply with PROFITS.jpg
    "commercial": "commercial.mp4",  # When someone says "commercial", reply with commercial.mp4
    "slut": "SLUT.jpg"         # When someone says "slut", reply with SLUT.jpg
}

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_text = update.message.text.lower()  # Convert message to lowercase for case-insensitive matching

        # Check if the message contains any of the keywords
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                print(f"Keyword '{keyword}' detected. Sending file: {media_file}")

                # Check if the file exists
                if not os.path.exists(media_file):
                    print(f"File not found: {media_file}")
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
        print(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

# Function to set up the webhook
async def set_webhook(application: Application):
    # Get the Render-provided URL for your service
    webhook_url = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"
    await application.bot.set_webhook(url=webhook_url)
    print(f"Webhook set to: {webhook_url}")

# Main function to start the bot
async def main():
    try:
        # Create the Application and pass it your bot's token
        application = Application.builder().token(TOKEN).build()

        # Add a message handler to respond to text messages
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Set up the webhook
        await set_webhook(application)

        # Start the bot
        await application.initialize()
        await application.start()
        await application.updater.start_webhook(
            listen="0.0.0.0",  # Listen on all interfaces
            port=int(os.getenv('PORT', 8080)),  # Use the port provided by Render
            url_path="telegram"  # Path for the webhook
        )

        print("Bot is running...")
    except Exception as e:
        print(f"Error starting bot: {e}")

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())