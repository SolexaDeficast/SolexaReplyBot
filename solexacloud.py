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

# Function to check if a message contains a keyword
def contains_keyword(text, keyword):
    text_lower = text.lower()
    keyword_lower = keyword.lower()
    return keyword_lower in text_lower

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            chat_id = str(update.message.chat_id)
            raw_message_text = update.message.text
            message_text = raw_message_text.lstrip("/").lower()
            logger.info(f"Processing message: '{raw_message_text}' -> '{message_text}'")

            # **Check for text filters first**
            if chat_id in filters_data:
                for keyword, response in filters_data[chat_id].items():
                    if contains_keyword(message_text, keyword):
                        logger.info(f"Filter triggered: '{keyword}' -> '{response}'")
                        await update.message.reply_text(response)
                        return  # Stop after first match

            # **Check for media keyword responses**
            for keyword, media_file in keyword_responses.items():
                if contains_keyword(message_text, keyword):
                    logger.info(f"Media keyword '{keyword}' detected. Sending file: {media_file}")
                    
                    if not os.path.exists(media_file):
                        logger.error(f"File not found: {media_file}")
                        await update.message.reply_text(f"❌ Sorry, the file '{media_file}' is missing.")
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
                            logger.info(f"Attempting to send GIF: {media_file}")
                            await update.message.reply_animation(animation=media)
                            logger.info(f"GIF sent successfully: {media_file}")

                    return  # Stop after first match

            logger.info(f"No match found for message: '{message_text}'")

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("⚠️ An error occurred while processing your request.")

# Function to add a text filter
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
        logger.info(f"Filter added for chat {chat_id}: '{keyword}' -> '{response}'")
    except Exception as e:
        logger.error(f"Error in add_filter: {e}")
        await update.message.reply_text("⚠️ Error adding filter!")

# Function to list all filters
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = str(update.message.chat_id)
        if chat_id not in filters_data or not filters_data[chat_id]:
            await update.message.reply_text("No filters have been added yet.")
            return
        filter_list = "\n".join([f"{key} → {value}" for key, value in filters_data[chat_id].items()])
        await update.message.reply_text(f"📜 Active Filters:\n{filter_list}")
    except Exception as e:
        logger.error(f"Error in list_filters: {e}")
        await update.message.reply_text("⚠️ Error listing filters!")

# Function to remove a filter
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Error in remove_filter: {e}")
        await update.message.reply_text("⚠️ Error removing filter!")

# Register handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CommandHandler("addsolexafilter", add_filter))
application.add_handler(CommandHandler("listsolexafilter", list_filters))
application.add_handler(CommandHandler("removesolexafilter", remove_filter))

