import os
import logging
import json
import random
import re
from datetime import timedelta
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, User, MessageEntity
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
user_id_cache = {}
CAPTCHA_STATE_FILE = "/data/captcha_state.json"
captcha_enabled = {}
WELCOME_STATE_FILE = "/data/welcome_state.json"
welcome_state = {}
keyword_responses = {
    "PutMP3TriggerKeywordHere": "PUTmp3FILEnameHere.mp3",
    "PutVideoTriggerKeywordHere": "PutMp4FileNameHere.mp4",
    "profits": "PROFITS.jpg",
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"
}
FILTERS_FILE = "/data/filters.json"
filters_dict = {}

def load_filters():
    global filters_dict
    try:
        if os.path.exists(FILTERS_FILE):
            with open(FILTERS_FILE, 'r') as f:
                data = json.load(f)
                filters_dict = {int(chat_id): filters for chat_id, filters in data.items()}
        else:
            filters_dict = {}
        logger.info(f"Filters loaded: {repr(filters_dict)}")
    except Exception as e:
        logger.error(f"Error loading filters: {e}")
        filters_dict = {}

def save_filters():
    try:
        with open(FILTERS_FILE, 'w') as f:
            json.dump({str(chat_id): filters for chat_id, filters in filters_dict.items()}, f)
        logger.info(f"Filters saved: {repr(filters_dict)}")
    except Exception as e:
        logger.error(f"Error saving filters: {e}")

def load_captcha_state():
    global captcha_enabled
    try:
        if os.path.exists(CAPTCHA_STATE_FILE):
            with open(CAPTCHA_STATE_FILE, 'r') as f:
                data = json.load(f)
                captcha_enabled = {int(chat_id): bool(state) for chat_id, state in data.items()}
        else:
            captcha_enabled = {}
        logger.info(f"Captcha state loaded: {repr(captcha_enabled)}")
    except Exception as e:
        logger.error(f"Error loading captcha state: {e}")
        captcha_enabled = {}

def save_captcha_state():
    try:
        with open(CAPTCHA_STATE_FILE, 'w') as f:
            json.dump({str(chat_id): state for chat_id, state in captcha_enabled.items()}, f)
        logger.info(f"Captcha state saved: {repr(captcha_enabled)}")
    except Exception as e:
        logger.error(f"Error saving captcha state: {e}")

def load_welcome_state():
    global welcome_state
    try:
        if os.path.exists(WELCOME_STATE_FILE):
            with open(WELCOME_STATE_FILE, 'r') as f:
                data = json.load(f)
                welcome_state = {int(chat_id): v for chat_id, v in data.items()}
                for chat_id, state in welcome_state.items():
                    if "entities" in state and isinstance(state["entities"], list):
                        welcome_state[chat_id]["entities"] = [MessageEntity(**entity) for entity in state["entities"]]
        else:
            welcome_state = {}
        logger.info(f"Welcome state loaded: {repr(welcome_state)}")
    except Exception as e:
        logger.error(f"Error loading welcome state: {e}")
        welcome_state = {}

def save_welcome_state():
    try:
        serialized_state = {}
        for chat_id, state in welcome_state.items():
            serialized_state[str(chat_id)] = state.copy()
            if "entities" in serialized_state[str(chat_id)] and serialized_state[str(chat_id)]["entities"]:
                serialized_state[str(chat_id)]["entities"] = [entity.to_dict() for entity in state["entities"]]
        with open(WELCOME_STATE_FILE, 'w') as f:
            json.dump(serialized_state, f)
        logger.info(f"Welcome state saved: {repr(welcome_state)}")
    except Exception as e:
        logger.error(f"Error saving welcome state: {e}")

# Refined escape_markdown_v2 function
def escape_markdown_v2(text):
    """
    Escape special characters for Telegram MarkdownV2, preserving * and _ for bold/italic.
    Special characters to escape: ` > # + - = | { } . ! \ , except * and _
    """
    special_chars = r'([`>#+\-=|{}\.!\\,])'  # Exclude * and _ from escaping
    escaped_text = re.sub(special_chars, r'\\\1', text)
    logger.info(f"Raw MarkdownV2 text: {repr(text)}")
    logger.info(f"Escaped MarkdownV2 text: {repr(escaped_text)}")
    return escaped_text

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

async def resolve_user(chat_id: int, target_user: str, context: ContextTypes.DEFAULT_TYPE) -> int or None:
    try:
        if target_user.startswith("@"):
            username = target_user[1:].lower()
            if chat_id in user_id_cache and username in user_id_cache[chat_id]:
                return user_id_cache[chat_id][username]
            return None
        else:
            return int(target_user)
    except ValueError:
        logger.error(f"Invalid user format: {target_user}")
        return None

async def get_user_id_from_reply(update: Update) -> int or None:
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user.id
    return None

async def delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Deleted message {message_id} in chat {chat_id}")
    except Exception as e:
        logger.error(f"Failed to delete message {message_id}: {e}")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.message.chat_id
        if chat_id not in captcha_enabled:
            captcha_enabled[chat_id] = True
            save_captcha_state()
        captcha_active = captcha_enabled[chat_id]
        for member in update.message.new_chat_members:
            user_id = member.id
            username = member.username or member.first_name
            logger.info(f"New member: {username} (ID: {user_id}) in {update.message.chat.title}")
            if chat_id not in user_id_cache:
                user_id_cache[chat_id] = {}
            if member.username:
                user_id_cache[chat_id][member.username.lower()] = user_id
            if captcha_active:
                permissions = ChatPermissions(can_send_messages=False)
                await context.bot.restrict_chat_member(chat_id, user_id, permissions)
                question, options, correct_answer = generate_captcha()
                captcha_attempts[user_id] = {"answer": correct_answer, "attempts": 0, "chat_id": chat_id, "username": username}
                keyboard = [[InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")] for opt in options]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(chat_id=chat_id, text=f"Welcome {username}! Please verify yourself.\n{question}", reply_markup=reply_markup)
            else:
                if chat_id in welcome_state and welcome_state[chat_id]["enabled"]:
                    ws = welcome_state[chat_id]
                    text = ws["text"].replace("{username}", username)
                    escaped_text = escape_markdown_v2(text)
                    try:
                        logger.info(f"Sending welcome with MarkdownV2: {repr(escaped_text)}")
                        if ws["type"] == "text":
                            msg = await context.bot.send_message(chat_id, escaped_text, parse_mode='MarkdownV2')
                        elif ws["type"] == "photo":
                            msg = await context.bot.send_photo(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                        elif ws["type"] == "video":
                            msg = await context.bot.send_video(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                        elif ws["type"] == "animation":
                            msg = await context.bot.send_animation(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                        welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                        save_welcome_state()
                        logger.info(f"Welcome message sent successfully, message_id: {msg.message_id}")
                    except Exception as e:
                        logger.error(f"Failed to send welcome with MarkdownV2: {e}")
                        logger.info(f"Falling back to plain text: {text}")
                        if ws["type"] == "text":
                            msg = await context.bot.send_message(chat_id, text, parse_mode=None)
                        elif ws["type"] == "photo":
                            msg = await context.bot.send_photo(chat_id, ws["file_id"], caption=text, parse_mode=None)
                        elif ws["type"] == "video":
                            msg = await context.bot.send_video(chat_id, ws["file_id"], caption=text, parse_mode=None)
                        elif ws["type"] == "animation":
                            msg = await context.bot.send_animation(chat_id, ws["file_id"], caption=text, parse_mode=None)
                        welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                        save_welcome_state()
                        logger.info(f"Fallback welcome message sent, message_id: {msg.message_id}")
    except Exception as e:
        logger.error(f"Error handling new member: {e}")

async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data.split("_")
        if len(data) != 3:
            return
        _, target_user_id, answer = data
        target_user_id = int(target_user_id)
        answer = int(answer)
        if user_id != target_user_id:
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        if target_user_id not in captcha_attempts:
            await query.answer("Expired")
            return
        correct_answer = captcha_attempts[target_user_id]["answer"]
        chat_id = captcha_attempts[target_user_id]["chat_id"]
        username = captcha_attempts[target_user_id]["username"]
        attempts = captcha_attempts[target_user_id]["attempts"]
        if answer == correct_answer:
            permissions = ChatPermissions(
                can_send_messages=True, can_send_photos=True, can_send_videos=True,
                can_send_other_messages=True, can_send_polls=True, can_add_web_page_previews=True
            )
            await context.bot.restrict_chat_member(chat_id, target_user_id, permissions)
            await query.message.delete()
            if chat_id in welcome_state and welcome_state[chat_id]["enabled"]:
                ws = welcome_state[chat_id]
                text = ws["text"].replace("{username}", username)
                escaped_text = escape_markdown_v2(text)
                try:
                    logger.info(f"Sending welcome with MarkdownV2: {repr(escaped_text)}")
                    if ws["type"] == "text":
                        msg = await context.bot.send_message(chat_id, escaped_text, parse_mode='MarkdownV2')
                    elif ws["type"] == "photo":
                        msg = await context.bot.send_photo(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                    elif ws["type"] == "video":
                        msg = await context.bot.send_video(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                    elif ws["type"] == "animation":
                        msg = await context.bot.send_animation(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                    welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                    save_welcome_state()
                    logger.info(f"Welcome message sent successfully, message_id: {msg.message_id}")
                except Exception as e:
                    logger.error(f"Failed to send welcome with MarkdownV2: {e}")
                    logger.info(f"Falling back to plain text: {text}")
                    if ws["type"] == "text":
                        msg = await context.bot.send_message(chat_id, text, parse_mode=None)
                    elif ws["type"] == "photo":
                        msg = await context.bot.send_photo(chat_id, ws["file_id"], caption=text, parse_mode=None)
                    elif ws["type"] == "video":
                        msg = await context.bot.send_video(chat_id, ws["file_id"], caption=text, parse_mode=None)
                    elif ws["type"] == "animation":
                        msg = await context.bot.send_animation(chat_id, ws["file_id"], caption=text, parse_mode=None)
                    welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                    save_welcome_state()
                    logger.info(f"Fallback welcome message sent, message_id: {msg.message_id}")
                # Clear old welcome messages
                if "message_ids" in welcome_state[chat_id]:
                    for msg_id in welcome_state[chat_id]["message_ids"][:]:
                        try:
                            await context.bot.delete_message(chat_id, msg_id)
                            welcome_state[chat_id]["message_ids"].remove(msg_id)
                            logger.info(f"Successfully deleted old welcome message {msg_id}")
                        except Exception as e:
                            logger.error(f"Failed to delete welcome message {msg_id}: {e}")
                    save_welcome_state()
            else:
                msg = await context.bot.send_message(chat_id, "✅ Verified!")
                context.job_queue.run_once(lambda x: delete_message(x, chat_id, msg.message_id), 10, context=context)
            del captcha_attempts[target_user_id]
        else:
            attempts += 1
            captcha_attempts[target_user_id]["attempts"] = attempts
            if attempts >= 3:
                await context.bot.ban_chat_member(chat_id, target_user_id)
                await context.bot.unban_chat_member(chat_id, target_user_id)
                await query.message.edit_text("❌ Removed after 3 failed attempts")
                del captcha_attempts[target_user_id]
            else:
                await query.answer("❌ Incorrect answer")
    except Exception as e:
        logger.error(f"Captcha error: {e}")

# Remaining functions remain unchanged...

@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    logger.info(f"Received update: {json.dumps(data, indent=2)}")
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.on_event("startup")
async def startup():
    load_filters()
    load_captcha_state()
    load_welcome_state()
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)