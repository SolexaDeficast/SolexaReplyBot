import os
import logging
import random
import json
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler, CommandHandler
)
from moviepy.editor import VideoFileClip  # For video aspect ratios

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"

if not TOKEN or not WEBHOOK_URL:
    logger.error("TELEGRAM_BOT_TOKEN or RENDER_EXTERNAL_URL not set in environment variables!")
    raise ValueError("Missing required environment variables.")

# Dictionary to track users' captcha attempts
captcha_attempts = {}

# Dictionary to store filters per group
FILTERS_FILE = "filters.json"

def load_filters():
    if os.path.exists(FILTERS_FILE):
        with open(FILTERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_filters(filters):
    with open(FILTERS_FILE, "w") as f:
        json.dump(filters, f)

filters_data = load_filters()

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

# Define the keywords and corresponding media files (unchanged paths)
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

            permissions = ChatPermissions(can_send_messages=False)
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            logger.info(f"User {username} restricted in supergroup.")

            question, options, correct_answer = generate_captcha()
            captcha_attempts[user_id] = {"answer": correct_answer, "attempts": 0, "chat_id": chat_id}

            keyboard = [
                [InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")]
                for opt in options
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

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

        # Check if the clicker is the new member
        if query.from_user.id != user_id:
            await query.answer("This CAPTCHA is only for the new member to answer!")
            return

        if user_id not in captcha_attempts:
            await query.answer("This verification has expired.")
            return

        correct_answer = captcha_attempts[user_id]["answer"]
        chat_id = captcha_attempts[user_id]["chat_id"]
        attempts = captcha_attempts[user_id]["attempts"]

        if answer == correct_answer:
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
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                await query.message.edit_text("❌ You failed verification 3 times and have been removed from the group.")
                del captcha_attempts[user_id]
                logger.info(f"User {user_id} failed verification and was removed.")
            else:
                await query.answer(f"❌ Incorrect answer. Attempts left: {3 - attempts}")
    except Exception as e:
        logger.error(f"Error handling captcha verification: {e}")

# Function to check if a message contains an exact word match
def contains_exact_word(text, word):
    words = text.lower().split()
    return word.lower() in words

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            chat_id = str(update.message.chat_id)
            raw_message_text = update.message.text
            message_text = raw_message_text.lstrip("/").lower()

            # Check for media keyword responses
            for keyword, media_file in keyword_responses.items():
                if contains_exact_word(message_text, keyword):
                    logger.info(f"Keyword '{keyword}' detected. Sending file: {media_file}")
                    if not os.path.exists(media_file):
                        logger.error(f"File not found: {media_file}")
                        await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                        return
                    with open(media_file, 'rb') as media:
                        if media_file.endswith('.mp3'):
                            await update.message.reply_audio(audio=media)
                        elif media_file.endswith('.mp4'):
                            video = VideoFileClip(media_file)
                            width, height = video.size
                            video.close()
                            await update.message.reply_video(
                                video=media,
                                supports_streaming=True,
                                width=width,
                                height=height
                            )
                        elif media_file.endswith('.jpg'):
                            await update.message.reply_photo(photo=media)
                        elif media_file.endswith('.gif'):
                            logger.info(f"Sending GIF: {media_file}")
                            await update.message.reply_animation(animation=media)
                    return  # Stop after first match

            # Check for text filters
            if chat_id in filters_data:
                for keyword, response in filters_data[chat_id].items():
                    if contains_exact_word(message_text, keyword):
                        await update.message.reply_text(response)
                        return  # Stop after first match
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

# Function to add a text filter
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addsolexafilter <keyword> <response>")
        return
    chat_id = str(update.message.chat_id)
    keyword = context.args[0].lower()
    response = " ".join(context.args[1:])
    if chat_id not in filters_data:
        filters_data[chat_id] = {}
    filters_data[chat_id][keyword] = response
    save_filters(filters_data)
    await update.message.reply_text(f"✅ Filter added: '{keyword}' → '{response}'")

# Function to list all filters
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    if chat_id not in filters_data or not filters_data[chat_id]:
        await update.message.reply_text("No filters have been added yet.")
        return
    filter_list = "\n".join([f"{key} → {value}" for key, value in filters_data[chat_id].items()])
    await update.message.reply_text(f"📜 Active Filters:\n{filter_list}")

# Function to remove a filter
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removesolexafilter <keyword>")
        return
    chat_id = str(update.message.chat_id)
    keyword = context.args[0].lower()
    if chat_id in filters_data and keyword in filters_data[chat_id]:
        del filters_data[chat_id][keyword]
        save_filters(filters_data)
        await update.message.reply_text(f"🗑️ Filter '{keyword}' removed.")
    else:
        await update.message.reply_text(f"❌ Filter '{keyword}' not found.")

# Add the handlers to the application
application.add_handler(MessageHandler(filters.TEXT, handle_message))  # Changed to catch all text
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"captcha_\d+_\d+"))
application.add_handler(CommandHandler("addsolexafilter", add_filter))
application.add_handler(CommandHandler("listsolexafilter", list_filters))
application.add_handler(CommandHandler("removesolexafilter", remove_filter))

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