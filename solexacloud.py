import os
import logging
import asyncio
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from moviepy.editor import VideoFileClip  # Library for getting video metadata
from random import randint
from telegram.helpers import escape_markdown

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

# Store pending captchas
pending_captchas = {}

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            message_text = update.message.text.lower()
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
                            clip = VideoFileClip(media_file)  # Get video metadata
                            width, height = clip.size
                            await update.message.reply_video(video=media, width=width, height=height, supports_streaming=True)
                            clip.close()
                        elif media_file.endswith('.jpg'):
                            await update.message.reply_photo(photo=media)
                        elif media_file.endswith('.gif'):
                            await update.message.reply_animation(animation=media)
                    break  # Stop after first match
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for member in update.message.new_chat_members:
            chat_id = update.message.chat.id
            user_id = member.id
            username = member.full_name
            
            # Restrict user from sending messages
            await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions())
            logger.info(f"User {username} restricted in supergroup.")
            
            # Generate simple math CAPTCHA
            num1, num2 = randint(1, 10), randint(1, 10)
            answer = num1 + num2
            pending_captchas[user_id] = (chat_id, answer)
            
            # Escape Markdown characters
            escaped_username = escape_markdown(username, version=2)
            captcha_question = escape_markdown(f"{num1} + {num2} = ?", version=2)
            
            # Send CAPTCHA message
            await update.message.reply_text(
                f"🚨 Welcome {escaped_username}! Please verify you are human.\n"
                f"Solve this to chat: *{captcha_question}*\n"
                f"(Reply with the correct answer within 120 seconds.)",
                parse_mode="MarkdownV2"
            )
            
            # Set timeout to remove user if they fail
            await asyncio.sleep(120)
            if user_id in pending_captchas:
                await context.bot.ban_chat_member(chat_id, user_id)
                del pending_captchas[user_id]
                logger.info(f"User {username} removed due to failed CAPTCHA.")
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        if user_id in pending_captchas:
            chat_id, correct_answer = pending_captchas[user_id]
            if update.message.text.strip() == str(correct_answer):
                await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=True))
                await update.message.reply_text("✅ Verification successful! You can now chat.")
                del pending_captchas[user_id]
                logger.info(f"User {user_id} successfully verified.")
            else:
                await update.message.reply_text("❌ Incorrect answer. Try again.")
    except Exception as e:
        logger.error(f"Error verifying CAPTCHA: {e}")

# Handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, verify_captcha))

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
