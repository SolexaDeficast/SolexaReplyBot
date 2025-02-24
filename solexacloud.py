import os
import logging
import asyncio
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from moviepy.editor import VideoFileClip

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"

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

# Store pending verifications
pending_verifications = {}

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

# Function to handle text messages
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
            chat_id = update.message.chat_id
            user_id = member.id
            first_name = member.first_name
            num1, num2 = random.randint(1, 10), random.randint(1, 10)
            correct_answer = num1 + num2
            wrong_answers = random.sample([correct_answer + i for i in range(-3, 4) if i != 0], 3)
            options = [correct_answer] + wrong_answers
            random.shuffle(options)
            keyboard = [[InlineKeyboardButton(str(ans), callback_data=f"captcha:{user_id}:{ans}")] for ans in options]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.restrict_chat_member(chat_id, user_id, permissions={})
            await context.bot.send_message(chat_id, f"Welcome {first_name}! Solve this to verify: {num1} + {num2} = ?", reply_markup=reply_markup)
            pending_verifications[user_id] = correct_answer
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id, selected_answer = query.data.split(":")
    user_id = int(user_id)
    selected_answer = int(selected_answer)
    chat_id = query.message.chat_id
    if user_id in pending_verifications and pending_verifications[user_id] == selected_answer:
        await context.bot.restrict_chat_member(chat_id, user_id, can_send_messages=True)
        await query.message.edit_text("Verification successful! Welcome!")
        del pending_verifications[user_id]
    else:
        await query.message.edit_text("Incorrect answer. Please try again.")

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"^captcha:\d+:\d+"))

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
        logger.error(f"Error processing webhook update: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def startup_event():
    try:
        await application.initialize()
        await application.start()
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
