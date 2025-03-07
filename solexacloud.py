import os
import logging
import json
import random
import re
from datetime import timedelta
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, User
)
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler, CommandHandler
)
from telegram.error import BadRequest, Forbidden

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"
captcha_attempts = {}

app = FastAPI()
application = Application.builder().token(TOKEN).build()

keyword_responses = {
    "PutMP3TriggerKeywordHere": "PUTmp3FILEnameHere.mp3",
    "PutVideoTriggerKeywordHere": "PutMp4FileNameHere.mp4",
    "profits": "PROFITS.jpg",
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"
}

# Persistent storage setup
FILTERS_FILE = "/data/filters.json"
filters_dict = {}

def load_filters():
    global filters_dict
    try:
        if os.path.exists(FILTERS_FILE):
            with open(FILTERS_FILE, 'r') as f:
                data = json.load(f)
                # Convert string keys back to integers
                filters_dict = {int(chat_id): {k: v for k, v in filters.items()} 
                               for chat_id, filters in data.items()}
        else:
            filters_dict = {}
    except Exception as e:
        logger.error(f"Error loading filters: {e}")
        filters_dict = {}

def save_filters():
    try:
        with open(FILTERS_FILE, 'w') as f:
            # Convert integer keys to strings for JSON
            serializable = {str(chat_id): filters 
                           for chat_id, filters in filters_dict.items()}
            json.dump(serializable, f)
    except Exception as e:
        logger.error(f"Error saving filters: {e}")

async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                keyword = context.args[0].lower()
                response_text = " ".join(context.args[1:]) if len(context.args) > 1 else None
                chat_id = update.message.chat_id

                # Extract media if present
                media_info = None
                if update.message.photo:
                    media_info = {"type": "photo", "file_id": update.message.photo[-1].file_id}
                elif update.message.video:
                    media_info = {"type": "video", "file_id": update.message.video.file_id}
                elif update.message.audio:
                    media_info = {"type": "audio", "file_id": update.message.audio.file_id}
                elif update.message.animation:
                    media_info = {"type": "animation", "file_id": update.message.animation.file_id}

                # Create filter entry
                filter_entry = {"text": response_text, "media": media_info}

                if chat_id not in filters_dict:
                    filters_dict[chat_id] = {}
                filters_dict[chat_id][keyword] = filter_entry
                save_filters()

                await update.message.reply_text(f"Filter '{keyword}' added ✅")
            except IndexError:
                await update.message.reply_text("Usage: /addsolexafilter keyword [response_text] (optional media)")
        else:
            await update.message.reply_text("No permission ❌")
    else:
        await update.message.reply_text("Group-only command ❌")

async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            chat_id = update.message.chat_id
            filters_list = filters_dict.get(chat_id, {})
            if filters_list:
                response = "Filters:\n"
                for keyword, filter_data in filters_list.items():
                    if isinstance(filter_data, str):  # Backward compatibility for old filters
                        response += f"{keyword}: text='{filter_data}'\n"
                    elif isinstance(filter_data, dict):  # New-style filters
                        response += f"{keyword}: "
                        if filter_data.get("text"):
                            response += f"text='{filter_data['text']}' "
                        if filter_data.get("media"):
                            response += f"media={filter_data['media']['type']}"
                        response += "\n"
                await update.message.reply_text(response)
            else:
                await update.message.reply_text("No filters set")
        else:
            await update.message.reply_text("No permission ❌")
    else:
        await update.message.reply_text("Group-only command ❌")

async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                keyword = context.args[0].lower()
                chat_id = update.message.chat_id
                if chat_id in filters_dict and keyword in filters_dict[chat_id]:
                    del filters_dict[chat_id][keyword]
                    save_filters()
                    await update.message.reply_text(f"Filter '{keyword}' removed ✅")
                else:
                    await update.message.reply_text("Filter not found ❌")
            except IndexError:
                await update.message.reply_text("Usage: /removesolexafilter keyword")
        else:
            await update.message.reply_text("No permission ❌")
    else:
        await update.message.reply_text("Group-only command ❌")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return
        message_text = update.message.text.lower()
        chat_id = update.message.chat_id

        # Check dynamic filters
        if chat_id in filters_dict:
            for keyword, filter_data in filters_dict[chat_id].items():
                if re.search(rf"(?:^|\s){re.escape('/' + keyword)}(?:\s|$)|\b{re.escape(keyword)}\b", message_text):
                    # Handle old-style filters (strings)
                    if isinstance(filter_data, str):
                        await update.message.reply_text(filter_data)
                        return

                    # Handle new-style filters (dictionaries)
                    if isinstance(filter_data, dict):
                        # Send text response if present
                        if filter_data.get("text"):
                            await update.message.reply_text(filter_data["text"])

                        # Send media response if present
                        media = filter_data.get("media")
                        if media:
                            media_type = media["type"]
                            file_id = media["file_id"]
                            if media_type == "photo":
                                await update.message.reply_photo(photo=file_id)
                            elif media_type == "video":
                                await update.message.reply_video(video=file_id)
                            elif media_type == "audio":
                                await update.message.reply_audio(audio=file_id)
                            elif media_type == "animation":
                                await update.message.reply_animation(animation=file_id)
                        return

        # Check static keyword responses
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                if not os.path.exists(media_file):
                    await update.message.reply_text(f"File missing: {media_file}")
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
        logger.error(f"Message error: {e}")

# HANDLERS
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(CommandHandler("mute10", mute10))
application.add_handler(CommandHandler("mute30", mute30))
application.add_handler(CommandHandler("mute1hr", mute1hr))
application.add_handler(CommandHandler("addsolexafilter", add_filter))
application.add_handler(CommandHandler("listsolexafilters", list_filters))
application.add_handler(CommandHandler("removesolexafilter", remove_filter))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"^captcha_\d+_\d+$"))

# FASTAPI WEBHOOK
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.on_event("startup")
async def startup():
    load_filters()
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)