import os
import logging
import asyncio
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update, Video, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from moviepy.editor import VideoFileClip

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"

# Define keywords and media responses
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

# Dictionary to store pending verifications
pending_verifications = {}

# CAPTCHA logic
async def captcha_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        user = update.message.from_user
        chat_id = update.message.chat_id
        num1, num2 = random.randint(1, 10), random.randint(1, 10)
        correct_answer = num1 + num2
        pending_verifications[user.id] = correct_answer

        await application.bot.restrict_chat_member(
            chat_id, user.id,
            ChatPermissions(can_send_messages=False)
        )

        await update.message.reply_text(
            f"Welcome, {user.first_name}! Please solve this CAPTCHA within 120 seconds: {num1} + {num2} = ?"
        )
        await asyncio.sleep(120)
        
        if user.id in pending_verifications:
            del pending_verifications[user.id]
            await application.bot.kick_chat_member(chat_id, user.id)
            logger.info(f"User {user.id} failed CAPTCHA and was removed.")

async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat_id
    if user.id in pending_verifications:
        try:
            if int(update.message.text) == pending_verifications[user.id]:
                await application.bot.restrict_chat_member(
                    chat_id, user.id,
                    ChatPermissions(can_send_messages=True)
                )
                await update.message.reply_text("Verification successful! You may now chat.")
                del pending_verifications[user.id]
            else:
                await update.message.reply_text("Incorrect answer. Try again.")
        except ValueError:
            await update.message.reply_text("Please enter a valid number.")

# Handle text messages for keyword responses
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        message_text = update.message.text.lower()
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                if not os.path.exists(media_file):
                    await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                    return
                with open(media_file, 'rb') as media:
                    if media_file.endswith('.mp3'):
                        await update.message.reply_audio(audio=media)
                    elif media_file.endswith('.mp4'):
                        clip = VideoFileClip(media_file)
                        await update.message.reply_video(video=media, width=clip.size[0], height=clip.size[1], supports_streaming=True)
                        clip.close()
                    elif media_file.endswith('.jpg'):
                        await update.message.reply_photo(photo=media)
                    elif media_file.endswith('.gif'):
                        await update.message.reply_animation(animation=media)
                break

# Add handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\d+$'), verify_captcha))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, captcha_challenge))

# Webhook endpoint
@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        if not application.running:
            await application.initialize()
            await application.start()
        await application.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Startup event
@app.on_event("startup")
async def startup_event():
    try:
        await application.initialize()
        await application.start()
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

# Run the server
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
