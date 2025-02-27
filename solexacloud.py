import os
import logging
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler
)

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"

# Dictionary to track users' captcha attempts
captcha_attempts = {}

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

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

# Function to generate a math captcha
def generate_captcha():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_answer = num1 + num2

    # Generate incorrect answers
    wrong_answers = set()
    while len(wrong_answers) < 3:
        wrong = random.randint(1, 20)
        if wrong != correct_answer:
            wrong_answers.add(wrong)

    options = list(wrong_answers) + [correct_answer]
    random.shuffle(options)

    return f"What is {num1} + {num2}?", options, correct_answer

# Function to handle new members
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for member in update.message.new_chat_members:
            chat_id = update.message.chat_id
            user_id = member.id
            username = member.first_name

            logger.info(f"New member detected: {username} (ID: {user_id}) in {update.message.chat.title}")

            # Restrict the new member's permissions
            permissions = ChatPermissions(
                can_send_messages=False
            )
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            logger.info(f"User {username} restricted in supergroup.")

            # Generate captcha question
            question, options, correct_answer = generate_captcha()
            captcha_attempts[user_id] = {"answer": correct_answer, "attempts": 0, "chat_id": chat_id}

            # Create inline keyboard
            keyboard = [
                [InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")]
                for opt in options
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send captcha message
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Welcome {username}! Please verify yourself.\n\n{question}",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

# Function to verify captcha response
async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        data = query.data.split("_")

        if len(data) != 3:
            return

        _, user_id, answer = data
        user_id = int(user_id)
        answer = int(answer)

        if user_id not in captcha_attempts:
            await query.answer("This verification has expired.")
            return

        correct_answer = captcha_attempts[user_id]["answer"]
        chat_id = captcha_attempts[user_id]["chat_id"]
        attempts = captcha_attempts[user_id]["attempts"]

        if answer == correct_answer:
            # Grant full permissions including GIFs and stickers
            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_other_messages=True,
                can_send_polls=True,
                can_add_web_page_previews=True
            )
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            await query.message.edit_text("✅ Verification successful! You may now participate in the chat.")
            del captcha_attempts[user_id]
            logger.info(f"User {user_id} successfully verified and unrestricted.")
        else:
            attempts += 1
            captcha_attempts[user_id]["attempts"] = attempts

            if attempts >= 3:
                # Remove the user from the group
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)  # Just removing, not banning
                await query.message.edit_text("❌ You failed verification 3 times and have been removed from the group.")
                del captcha_attempts[user_id]
                logger.info(f"User {user_id} failed verification and was removed.")
            else:
                await query.answer("❌ Incorrect answer. Please try again.")
    except Exception as e:
        logger.error(f"Error handling captcha verification: {e}")

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
                            await update.message.reply_video(
                                video=media,
                                supports_streaming=True,
                                width=1280,  # Ensuring correct width
                                height=720   # Ensuring correct height
                            )
                        elif media_file.endswith('.jpg'):
                            await update.message.reply_photo(photo=media)
                        elif media_file.endswith('.gif'):
                            await update.message.reply_animation(animation=media)
                    break  # Stop after first match
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

# Add the handlers to the application
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"captcha_\d+_\d+"))

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
        await application.initialize()
        await application.start()
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

# Ensure proper port binding for Render
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
