import os
import logging
import asyncio
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes

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

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

# Dictionary to store pending verifications
pending_captchas = {}

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
                            await update.message.reply_video(video=media, supports_streaming=True)
                        elif media_file.endswith('.jpg'):
                            await update.message.reply_photo(photo=media)
                        elif media_file.endswith('.gif'):
                            await update.message.reply_animation(animation=media)
                    break
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Function to generate a math question captcha
def generate_captcha():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_answer = num1 + num2
    incorrect_answers = [correct_answer + 1, correct_answer - 1, correct_answer + 2]
    options = [correct_answer] + incorrect_answers
    random.shuffle(options)
    
    return f"What is {num1} + {num2}?", options, correct_answer

# Function to handle new members joining
async def welcome_and_restrict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for member in update.message.new_chat_members:
            chat_id = update.message.chat.id
            user_id = member.id
            username = member.first_name

            logger.info(f"New member detected: {username} (ID: {user_id}) in {update.message.chat.title}")

            # Restrict new member
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False)
            )

            # Generate captcha
            question, options, correct_answer = generate_captcha()
            pending_captchas[user_id] = correct_answer

            # Create inline buttons
            keyboard = [
                [InlineKeyboardButton(str(option), callback_data=f"captcha_{user_id}_{option}")]
                for option in options
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"Welcome {username}! Please solve this captcha to verify yourself:\n\n{question}",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_and_restrict))

# Function to verify captcha
async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        _, user_id, answer = query.data.split("_")
        user_id = int(user_id)
        answer = int(answer)
        chat_id = query.message.chat.id

        if user_id not in pending_captchas:
            await query.answer("Verification session expired.")
            return

        if answer == pending_captchas[user_id]:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_polls=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_voice_notes=True,
                    can_send_video_notes=True,
                    can_send_documents=True,
                    can_add_web_page_previews=True
                )
            )
            await query.message.edit_text("✅ Verification successful! You are now unrestricted.")
            del pending_captchas[user_id]
        else:
            await query.answer("❌ Incorrect answer. Please try again.", show_alert=True)
    except Exception as e:
        logger.error(f"Error handling captcha verification: {e}")

application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"^captcha_\d+_\d+$"))

# Webhook endpoint to receive Telegram updates
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

# Startup event for setting webhook
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
