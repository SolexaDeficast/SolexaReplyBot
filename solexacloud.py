import os
import logging
import random
import re  # Import regex for exact word matching
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, User
)
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler, CommandHandler
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

# Dictionary to store chat-specific filters
filters_dict = {}

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

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_text = update.message.text.lower()
        chat_id = update.message.chat_id

        # Check if the message matches any filters using exact word matching or command-like format
        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if re.search(rf"\b{re.escape(keyword)}\b|^{re.escape('/' + keyword)}$", message_text):
                    await update.message.reply_text(response)
                    return

        # Check if the message matches any predefined keywords
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                if not os.path.exists(media_file):
                    await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                    return

                with open(media_file, 'rb') as media:
                    if media_file.endswith('.mp3'):
                        await update.message.reply_audio(audio=media)
                    elif media_file.endswith('.mp4'):
                        await update.message.reply_video(video=media, supports_streaming=True, width=1280, height=720)
                    elif media_file.endswith('.jpg'):
                        await update.message.reply_photo(photo=media)
                    elif media_file.endswith('.gif'):
                        await update.message.reply_animation(animation=media)
                break
    except Exception as e:
        logger.error(f"Error handling message: {e}")

# Function to resolve user ID from username
async def get_user_id_from_username(context: ContextTypes.DEFAULT_TYPE, chat_id: int, username: str):
    try:
        members = await context.bot.get_chat_administrators(chat_id)
        for member in members:
            if member.user.username and member.user.username.lower() == username.lower():
                return member.user.id

        # If user is not an admin, check all chat members
        chat_members = await context.bot.get_chat(chat_id)
        users = chat_members.get_members()
        for user in users:
            if user.user.username and user.user.username.lower() == username.lower():
                return user.user.id

    except Exception as e:
        logger.error(f"Error resolving username @{username}: {e}")
    return None

# Function to ban a user (admin only)
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type == "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                target_user = context.args[0]
                chat_id = update.message.chat_id

                if target_user.startswith("@"):
                    target_user = target_user[1:]
                    user_id = await get_user_id_from_username(context, chat_id, target_user)
                    if not user_id:
                        await update.message.reply_text(f"Error: Could not find user @{target_user} in this chat.")
                        return
                else:
                    user_id = int(target_user)

                await context.bot.ban_chat_member(chat_id, user_id)
                await update.message.reply_text(f"User @{target_user} has been banned.")
            except (IndexError, ValueError):
                await update.message.reply_text("Usage: /ban <username> or /ban <user_id>")
        else:
            await update.message.reply_text("You do not have permission to use this command.")
    else:
        await update.message.reply_text("This command can only be used in group chats.")

# Function to kick a user (admin only)
async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type == "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                target_user = context.args[0]
                chat_id = update.message.chat_id

                if target_user.startswith("@"):
                    target_user = target_user[1:]
                    user_id = await get_user_id_from_username(context, chat_id, target_user)
                    if not user_id:
                        await update.message.reply_text(f"Error: Could not find user @{target_user} in this chat.")
                        return
                else:
                    user_id = int(target_user)

                await context.bot.unban_chat_member(chat_id, user_id)
                await update.message.reply_text(f"User @{target_user} has been kicked.")
            except (IndexError, ValueError):
                await update.message.reply_text("Usage: /kick <username> or /kick <user_id>")
        else:
            await update.message.reply_text("You do not have permission to use this command.")
    else:
        await update.message.reply_text("This command can only be used in group chats.")

# Add handlers for all commands and messages
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Webhook handler
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

# Startup event
@app.on_event("startup")
async def startup_event():
    await application.initialize()
    await application.start()
    await application.bot.delete_webhook()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
