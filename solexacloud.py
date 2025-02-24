import os
import logging
import asyncio
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from moviepy.editor import VideoFileClip  # Library for getting video metadata

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
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"
}

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

# Store pending CAPTCHA challenges {user_id: answer}
pending_captchas = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            message_text = update.message.text.lower()
            user_id = update.message.from_user.id

            # CAPTCHA validation check
            if user_id in pending_captchas:
                correct_answer = pending_captchas[user_id]
                if message_text == str(correct_answer):
                    await update.message.reply_text("✅ Verification successful! You can now chat.")
                    await context.bot.restrict_chat_member(
                        update.message.chat.id, user_id,
                        can_send_messages=True, can_send_media_messages=True,
                        can_send_other_messages=True, can_add_web_page_previews=True
                    )
                    del pending_captchas[user_id]
                else:
                    await update.message.reply_text("❌ Incorrect answer. Try again!")
                return  # Stop further processing

            # Check for keywords
            for keyword, media_file in keyword_responses.items():
                if keyword in message_text:
                    logger.info(f"Keyword '{keyword}' detected. Sending file: {media_file}")

                    if not os.path.exists(media_file):
                        logger.error(f"File not found: {media_file}")
                        await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                        return

                    with open(media_file, 'rb') as media:
                        if media_file.endswith('.mp3'):
                            await update.message.reply_audio(audio=media)
                        elif media_file.endswith('.mp4'):
                            clip = VideoFileClip(media_file)
                            width, height = clip.size
                            await update.message.reply_video(video=media, width=width, height=height, supports_streaming=True)
                            clip.close()
                        elif media_file.endswith('.jpg'):
                            await update.message.reply_photo(photo=media)
                        elif media_file.endswith('.gif'):
                            await update.message.reply_animation(animation=media)
                    break
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for member in update.message.new_chat_members:
            user_id = member.id
            chat_id = update.message.chat.id
            username = member.first_name

            # Generate a math CAPTCHA
            num1, num2 = random.randint(1, 10), random.randint(1, 10)
            correct_answer = num1 + num2
            pending_captchas[user_id] = correct_answer

            # Restrict user
            await context.bot.restrict_chat_member(chat_id, user_id, can_send_messages=False)
            logger.info(f"User {username} restricted in supergroup.")

            # Send CAPTCHA challenge
            await update.message.reply_text(
                f"👋 Welcome {username}! Before you can chat, please solve this:",
            )
            await update.message.reply_text(
                f"❓ {num1} + {num2} = ? (Reply with the answer)",
            )
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

# Handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))

@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)

        if not application.running:
            logger.warning("Application is not running. Initializing now...")
            await application.initialize()
            await application.start()

        await application.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def startup_event():
    try:
        logger.info("Starting bot initialization...")

        await application.initialize()
        await application.start()
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to: {WEBHOOK_URL}")

        logger.info("Bot is fully running...")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
