import os
import logging
import random
import asyncio
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, Video, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
)
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler, CommandHandler,
    filters, ContextTypes
)
from moviepy.editor import VideoFileClip  # Library for getting video metadata

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"  # Ensure this is set in Render

# Define keyword responses
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

# Dictionary to store pending captcha challenges
pending_captchas = {}

# Function to generate a math captcha
def generate_captcha():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_answer = num1 + num2
    options = [correct_answer, correct_answer + random.randint(1, 3), correct_answer - random.randint(1, 3), correct_answer + random.randint(4, 6)]
    random.shuffle(options)
    return f"{num1} + {num2} = ?", correct_answer, options

# Function to handle new members joining
async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message and update.message.new_chat_members:
            for member in update.message.new_chat_members:
                user_id = member.id
                chat_id = update.message.chat.id
                username = member.username or member.first_name

                logger.info(f"New member detected: {username} (ID: {user_id}) in {update.message.chat.title}")

                # Restrict the new member (Mute them)
                await context.bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(can_send_messages=False)
                )

                # Generate and store captcha
                question, correct_answer, options = generate_captcha()
                pending_captchas[user_id] = (correct_answer, chat_id)

                # Create answer buttons
                buttons = [
                    [InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")]
                    for opt in options
                ]
                reply_markup = InlineKeyboardMarkup(buttons)

                # Send verification message
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Welcome {username}! Please verify yourself by solving this captcha:\n\n{question}",
                    reply_markup=reply_markup
                )
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

# Function to verify captcha
async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        if not query:
            return

        _, user_id, selected_answer = query.data.split("_")
        user_id = int(user_id)
        selected_answer = int(selected_answer)

        if user_id in pending_captchas:
            correct_answer, chat_id = pending_captchas[user_id]

            if selected_answer == correct_answer:
                # Unrestrict the user
                await context.bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )

                await query.edit_message_text("✅ Verification successful! You can now participate in the chat.")
                del pending_captchas[user_id]
            else:
                # Retry if incorrect
                question, new_correct_answer, new_options = generate_captcha()
                pending_captchas[user_id] = (new_correct_answer, chat_id)

                new_buttons = [
                    [InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")]
                    for opt in new_options
                ]
                new_reply_markup = InlineKeyboardMarkup(new_buttons)

                await query.edit_message_text(
                    text=f"❌ Incorrect answer. Please try again:\n\n{question}",
                    reply_markup=new_reply_markup
                )
    except Exception as e:
        logger.error(f"Error handling captcha verification: {e}")

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

# Add handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern="^captcha_"))

# Webhook endpoint for Telegram updates
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

# Startup event to set webhook
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

# Ensure proper port binding for Render
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
