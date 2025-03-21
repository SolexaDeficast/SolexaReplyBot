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
CLEANSYSTEM_STATE_FILE = "/data/cleansystem_state.json"
cleansystem_enabled = {}
AUTODELETE_CONFIG_FILE = "/data/autodelete_config.json"
autodelete_config = {
    "admin": 30, "error": 15, "captcha": 30, "captcha_prompt": 120, "welcome": 0, "filter": 0, "system": 0
}
WELCOME_AUTODELETE_STATE_FILE = "/data/welcome_autodelete_state.json"
welcome_auto_delete = {}
CHAT_IDS_FILE = "/data/chat_ids.json"
chat_ids_map = {}  # Maps tags (e.g., "#room1") to chat_ids

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

def load_cleansystem_state():
    global cleansystem_enabled
    try:
        if os.path.exists(CLEANSYSTEM_STATE_FILE):
            with open(CLEANSYSTEM_STATE_FILE, 'r') as f:
                data = json.load(f)
                cleansystem_enabled = {int(chat_id): bool(state) for chat_id, state in data.items()}
        else:
            cleansystem_enabled = {}
        logger.info(f"Clean system state loaded: {repr(cleansystem_enabled)}")
    except Exception as e:
        logger.error(f"Error loading clean system state: {e}")
        cleansystem_enabled = {}

def save_cleansystem_state():
    try:
        with open(CLEANSYSTEM_STATE_FILE, 'w') as f:
            json.dump({str(chat_id): state for chat_id, state in cleansystem_enabled.items()}, f)
        logger.info(f"Clean system state saved: {repr(cleansystem_enabled)}")
    except Exception as e:
        logger.error(f"Error saving clean system state: {e}")

def load_autodelete_config():
    global autodelete_config
    default_config = {
        "admin": 30, "error": 15, "captcha": 30, "captcha_prompt": 120, "welcome": 0, "filter": 0, "system": 0
    }
    try:
        if os.path.exists(AUTODELETE_CONFIG_FILE):
            with open(AUTODELETE_CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                autodelete_config = {**default_config, **loaded_config}
        else:
            autodelete_config = default_config.copy()
        logger.info(f"Auto-delete config loaded: {repr(autodelete_config)}")
    except Exception as e:
        logger.error(f"Error loading auto-delete config: {e}")
        autodelete_config = default_config.copy()

def save_autodelete_config():
    try:
        with open(AUTODELETE_CONFIG_FILE, 'w') as f:
            json.dump(autodelete_config, f)
        logger.info(f"Auto-delete config saved: {repr(autodelete_config)}")
    except Exception as e:
        logger.error(f"Error saving auto-delete config: {e}")

def load_welcome_autodelete_state():
    global welcome_auto_delete
    try:
        if os.path.exists(WELCOME_AUTODELETE_STATE_FILE):
            with open(WELCOME_AUTODELETE_STATE_FILE, 'r') as f:
                data = json.load(f)
                welcome_auto_delete = {int(chat_id): bool(state) for chat_id, state in data.items()}
        else:
            welcome_auto_delete = {}
        logger.info(f"Welcome auto-delete state loaded: {repr(welcome_auto_delete)}")
    except Exception as e:
        logger.error(f"Error loading welcome auto-delete state: {e}")
        welcome_auto_delete = {}

def save_welcome_autodelete_state():
    try:
        with open(WELCOME_AUTODELETE_STATE_FILE, 'w') as f:
            json.dump({str(chat_id): state for chat_id, state in welcome_auto_delete.items()}, f)
        logger.info(f"Welcome auto-delete state saved: {repr(welcome_auto_delete)}")
    except Exception as e:
        logger.error(f"Error saving welcome auto-delete state: {e}")

def load_chat_ids():
    global chat_ids_map
    try:
        if os.path.exists(CHAT_IDS_FILE):
            with open(CHAT_IDS_FILE, 'r') as f:
                data = json.load(f)
                chat_ids_map = {tag: int(chat_id) for tag, chat_id in data.items()}
        else:
            chat_ids_map = {
                "#solexamain": -1002280396764,
                "#trusted": -1002213872502,
                "#bottest": -1002408047628
            }
            save_chat_ids()
        logger.info(f"Chat IDs loaded: {repr(chat_ids_map)}")
    except Exception as e:
        logger.error(f"Error loading chat IDs: {e}")
        chat_ids_map = {
            "#solexamain": -1002280396764,
            "#trusted": -1002213872502,
            "#bottest": -1002408047628
        }
        save_chat_ids()

def save_chat_ids():
    try:
        with open(CHAT_IDS_FILE, 'w') as f:
            json.dump(chat_ids_map, f)
        logger.info(f"Chat IDs saved: {repr(chat_ids_map)}")
    except Exception as e:
        logger.error(f"Error saving chat IDs: {e}")

def escape_markdown_v2(text):
    if not text:
        return ""
    escape_chars = '_*[]()~`>#+-=|{}.!'
    result = text.replace('\\', '\\\\')
    for char in escape_chars:
        result = result.replace(char, f'\\{char}')
    return result

def process_markdown_v2(text):
    if not text:
        return ""
    special_chars = '_*[]()~`>#+-=|{}.!'
    processed = text.replace('\\', '\\\\')
    i = 0
    result = ""
    in_bold = False
    in_italic = False
    in_link_text = False
    in_link_url = False
    while i < len(processed):
        char = processed[i]
        next_char = processed[i + 1] if i + 1 < len(processed) else None
        if char == '*' and not in_link_text and not in_link_url:
            result += '*'
            in_bold = not in_bold
            i += 1
            continue
        elif char == '_' and not in_link_text and not in_link_url:
            result += '_'
            in_italic = not in_italic
            i += 1
            continue
        elif char == '[' and not in_bold and not in_italic and not in_link_text and not in_link_url:
            result += '['
            in_link_text = True
            i += 1
            continue
        elif char == ']' and in_link_text:
            result += ']'
            in_link_text = False
            if next_char == '(':
                result += '('
                in_link_url = True
                i += 2
                continue
            else:
                i += 1
                continue
        elif char == ')' and in_link_url:
            result += ')'
            in_link_url = False
            i += 1
            continue
        else:
            is_in_formatting = in_bold or in_italic or in_link_text or in_link_url
            if char in special_chars and not is_in_formatting:
                result += '\\' + char
            else:
                result += char
            i += 1
    return result

async def send_and_delete(context, chat_id, text, timeout_category="admin"):
    timeout = autodelete_config.get(timeout_category, 0)
    msg = await context.bot.send_message(chat_id, text)
    if timeout > 0:
        context.job_queue.run_once(lambda x: delete_message(x, chat_id, msg.message_id), timeout)
    return msg

async def send_formatted_and_delete(context, chat_id, text, timeout_category="admin", message_type="text", file_id=None, reply_markup=None):
    timeout = autodelete_config.get(timeout_category, 0)
    msg = await send_formatted_message(context, chat_id, text, message_type, file_id, reply_markup)
    if timeout > 0 and msg:
        context.job_queue.run_once(lambda x: delete_message(x, chat_id, msg.message_id), timeout)
    return msg

async def send_formatted_message(context, chat_id, text, message_type="text", file_id=None, reply_markup=None):
    try:
        formatted_text = process_markdown_v2(text)
        if message_type == "text":
            return await context.bot.send_message(chat_id, formatted_text, parse_mode='MarkdownV2', reply_markup=reply_markup)
        elif message_type == "photo":
            return await context.bot.send_photo(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2', reply_markup=reply_markup)
        elif message_type == "video":
            return await context.bot.send_video(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2', reply_markup=reply_markup)
        elif message_type == "animation":
            return await context.bot.send_animation(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2', reply_markup=reply_markup)
        elif message_type == "audio":
            return await context.bot.send_audio(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2', reply_markup=reply_markup)
        elif message_type == "voice":
            return await context.bot.send_voice(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2', reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to send with MarkdownV2: {e}")
        logger.info(f"Falling back to plain text: {text}")
        if message_type == "text":
            return await context.bot.send_message(chat_id, text, parse_mode=None, reply_markup=reply_markup)
        elif message_type == "photo":
            return await context.bot.send_photo(chat_id, file_id, caption=text, parse_mode=None, reply_markup=reply_markup)
        elif message_type == "video":
            return await context.bot.send_video(chat_id, file_id, caption=text, parse_mode=None, reply_markup=reply_markup)
        elif message_type == "animation":
            return await context.bot.send_animation(chat_id, file_id, caption=text, parse_mode=None, reply_markup=reply_markup)
        elif message_type == "audio":
            return await context.bot.send_audio(chat_id, file_id, caption=text, parse_mode=None, reply_markup=reply_markup)
        elif message_type == "voice":
            return await context.bot.send_voice(chat_id, file_id, caption=text, parse_mode=None, reply_markup=reply_markup)

async def send_welcome_message(context, chat_id, welcome_config, username):
    try:
        message_type = welcome_config.get("type", "text")
        file_id = welcome_config.get("file_id")
        raw_text = welcome_config.get("text", "")
        text_with_username = raw_text.replace("{username}", username)
        logger.info(f"Original welcome text: {raw_text}")
        logger.info(f"After username replacement: {text_with_username}")
        timeout = autodelete_config.get("welcome", 0)
        try:
            formatted_text = process_markdown_v2(text_with_username)
            logger.info(f"Formatted for MarkdownV2: {formatted_text}")
            if message_type == "text":
                msg = await context.bot.send_message(chat_id, formatted_text, parse_mode='MarkdownV2')
            elif message_type == "photo":
                msg = await context.bot.send_photo(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
            elif message_type == "video":
                msg = await context.bot.send_video(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
            elif message_type == "animation":
                msg = await context.bot.send_animation(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
            else:
                msg = await context.bot.send_message(chat_id, formatted_text, parse_mode='MarkdownV2')
            if timeout > 0 and msg:
                context.job_queue.run_once(lambda x: delete_message(x, chat_id, msg.message_id), timeout)
            return msg
        except Exception as e:
            logger.error(f"Error sending welcome with MarkdownV2: {e}")
            logger.info("Falling back to plain text...")
            if message_type == "text":
                msg = await context.bot.send_message(chat_id, text_with_username)
            elif message_type == "photo":
                msg = await context.bot.send_photo(chat_id, file_id, caption=text_with_username)
            elif message_type == "video":
                msg = await context.bot.send_video(chat_id, file_id, caption=text_with_username)
            elif message_type == "animation":
                msg = await context.bot.send_animation(chat_id, file_id, caption=text_with_username)
            else:
                msg = await context.bot.send_message(chat_id, text_with_username)
            if timeout > 0 and msg:
                context.job_queue.run_once(lambda x: delete_message(x, chat_id, msg.message_id), timeout)
            return msg
    except Exception as e:
        logger.error(f"Failed to send welcome message: {e}")
        return None

def adjust_entities(original_text, new_text, entities):
    if not entities or "{username}" not in original_text:
        return entities
    username_len = len("{username}")
    username_start = original_text.index("{username}")
    new_username = new_text[username_start:username_start + (len(new_text) - len(original_text) + username_len)]
    offset_diff = len(new_username) - username_len
    adjusted_entities = []
    for entity in entities:
        new_offset = entity.offset
        if entity.offset > username_start:
            new_offset += offset_diff
        new_length = entity.length
        if username_start <= entity.offset < username_start + username_len:
            new_length += offset_diff
        adjusted_entity = MessageEntity(
            type=entity.type,
            offset=new_offset,
            length=new_length,
            url=entity.url if entity.type == MessageEntity.TEXT_LINK else None
        )
        adjusted_entities.append(adjusted_entity)
    return adjusted_entities

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
        clean_system = chat_id in cleansystem_enabled and cleansystem_enabled[chat_id]
        if clean_system:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
                logger.info(f"Deleted system message {update.message.message_id} in chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to delete system message {update.message.message_id}: {e}")
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
                await send_formatted_and_delete(context, chat_id, f"Welcome {username}! Please verify yourself.\n\n{question}", "captcha_prompt", reply_markup=reply_markup)
            else:
                if chat_id in welcome_state and welcome_state[chat_id]["enabled"]:
                    if chat_id in welcome_auto_delete and welcome_auto_delete[chat_id]:
                        if "message_ids" in welcome_state[chat_id]:
                            for msg_id in welcome_state[chat_id]["message_ids"][:]:
                                try:
                                    await context.bot.delete_message(chat_id, msg_id)
                                    welcome_state[chat_id]["message_ids"].remove(msg_id)
                                    logger.info(f"Auto-deleted old welcome message {msg_id}")
                                except Exception as e:
                                    logger.error(f"Failed to auto-delete welcome message {msg_id}: {e}")
                    msg = await send_welcome_message(context, chat_id, welcome_state[chat_id], username)
                    if msg:
                        welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                        save_welcome_state()
                        logger.info(f"Welcome message sent successfully, message_id: {msg.message_id}")
    except Exception as e:
        logger.error(f"Error handling new member: {e}")

async def handle_system_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or update.message.chat.type == "private":
            return
        chat_id = update.message.chat_id
        if chat_id not in cleansystem_enabled or not cleansystem_enabled[chat_id]:
            return
        if update.message.text or update.message.caption:
            return
        if update.message.photo or update.message.video or update.message.animation or update.message.document:
            return
        if hasattr(update.message, "new_chat_members") and update.message.new_chat_members:
            return
        is_system_message = False
        if hasattr(update.message, "left_chat_member") and update.message.left_chat_member:
            is_system_message = True
        if (hasattr(update.message, "new_chat_title") and update.message.new_chat_title) or \
           (hasattr(update.message, "new_chat_photo") and update.message.new_chat_photo) or \
           (hasattr(update.message, "delete_chat_photo") and update.message.delete_chat_photo) or \
           (hasattr(update.message, "pinned_message") and update.message.pinned_message):
            is_system_message = True
        if not update.message.text and not update.message.caption:
            if not update.message.photo and \
               not update.message.video and \
               not update.message.audio and \
               not update.message.voice and \
               not update.message.document and \
               not update.message.sticker and \
               not update.message.animation:
                is_system_message = True
        if is_system_message:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
                logger.info(f"Deleted system message {update.message.message_id} in chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to delete system message: {e}")
    except Exception as e:
        logger.error(f"Error in handle_system_messages: {e}")

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
                if chat_id in welcome_auto_delete and welcome_auto_delete[chat_id]:
                    if "message_ids" in welcome_state[chat_id]:
                        for msg_id in welcome_state[chat_id]["message_ids"][:]:
                            try:
                                await context.bot.delete_message(chat_id, msg_id)
                                welcome_state[chat_id]["message_ids"].remove(msg_id)
                                logger.info(f"Auto-deleted old welcome message {msg_id}")
                            except Exception as e:
                                logger.error(f"Failed to auto-delete welcome message {msg_id}: {e}")
                msg = await send_welcome_message(context, chat_id, welcome_state[chat_id], username)
                if msg:
                    welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                    save_welcome_state()
                    logger.info(f"Welcome message sent successfully, message_id: {msg.message_id}")
            else:
                await send_and_delete(context, chat_id, "✅ Verified!", "captcha")
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return
        chat_id = update.message.chat_id
        user = update.message.from_user
        if user.username:
            if chat_id not in user_id_cache:
                user_id_cache[chat_id] = {}
            user_id_cache[chat_id][user.username.lower()] = user.id
        message_text = update.message.text.strip().lower()
        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if message_text == keyword or message_text == f"/{keyword}":
                    if isinstance(response, dict) and 'type' in response and 'file_id' in response:
                        media_type = response['type']
                        file_id = response['file_id']
                        text = response.get('text', '')
                        await send_formatted_and_delete(context, chat_id, text, "filter", media_type, file_id)
                    elif isinstance(response, str):
                        await send_formatted_and_delete(context, chat_id, response, "filter")
                    return
        for keyword, media_file in keyword_responses.items():
            if message_text == keyword:
                if not os.path.exists(media_file):
                    await send_and_delete(context, chat_id, f"File missing: {media_file}", "error")
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

async def handle_command_as_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return
        message_text = update.message.text.strip().lower()
        chat_id = update.message.chat_id
        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if message_text == f"/{keyword}":
                    if isinstance(response, dict) and 'type' in response and 'file_id' in response:
                        media_type = response['type']
                        file_id = response['file_id']
                        text = response.get('text', '')
                        await send_formatted_and_delete(context, chat_id, text, "filter", media_type, file_id)
                    elif isinstance(response, str):
                        await send_formatted_and_delete(context, chat_id, response, "filter")
                    return
    except Exception as e:
        logger.error(f"Filter error: {e}")

async def cleansystem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    chat_id = update.message.chat_id
    if not context.args:
        await send_and_delete(context, chat_id, "Usage: /cleansystem ON|OFF|STATUS", "admin")
        return
    action = context.args[0].upper()
    if action == "ON":
        cleansystem_enabled[chat_id] = True
        save_cleansystem_state()
        await send_and_delete(context, chat_id, "System message cleaning enabled ✅", "system")
    elif action == "OFF":
        cleansystem_enabled[chat_id] = False
        save_cleansystem_state()
        await send_and_delete(context, chat_id, "System message cleaning disabled ✅", "system")
    elif action == "STATUS":
        state = cleansystem_enabled.get(chat_id, False)
        status_text = "enabled" if state else "disabled"
        await send_and_delete(context, chat_id, f"System message cleaning is currently {status_text}", "admin")
    else:
        await send_and_delete(context, chat_id, "Usage: /cleansystem ON|OFF|STATUS", "admin")

async def solexaautodelete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    chat_id = update.message.chat_id
    if not context.args:
        status = "\n".join([f"{cat}: {val}s" for cat, val in autodelete_config.items()])
        await send_and_delete(context, chat_id, f"Auto-delete settings:\n{status}\n\nUse: /solexaautodelete [category] [seconds]", "admin")
        return
    if len(context.args) < 2:
        await send_and_delete(context, chat_id, "Usage: /solexaautodelete [category] [seconds]\nCategories: admin, error, captcha, captcha_prompt, welcome, filter, system", "admin")
        return
    category = context.args[0].lower()
    if category not in autodelete_config:
        await send_and_delete(context, chat_id, "Invalid category. Use: admin, error, captcha, captcha_prompt, welcome, filter, system", "error")
        return
    try:
        seconds = int(context.args[1])
        if seconds < 0:
            await send_and_delete(context, chat_id, "Seconds must be 0 or positive", "error")
            return
        autodelete_config[category] = seconds
        save_autodelete_config()
        status = "disabled" if seconds == 0 else f"set to {seconds}s"
        await send_and_delete(context, chat_id, f"Auto-delete for {category} {status} ✅", "admin")
    except ValueError:
        await send_and_delete(context, chat_id, "Seconds must be a number", "error")

async def solexahelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    help_text = (
        "*🚀 SOLEXA Bot Help Menu 🚀*\n"
        "Here's a detailed guide to all commands and features available in the bot.\n\n"
        "*⚙️ Admin Commands*\n"
        "• `/ban @username` or reply: Bans a user.\n"
        "• `/kick @username` or reply: Kicks a user.\n"
        "• `/mute10 @username` or reply: Mutes for 10 minutes.\n"
        "• `/mute30 @username` or reply: Mutes for 30 minutes.\n"
        "• `/mute1hr @username` or reply: Mutes for 1 hour.\n"
        "• `/unmute @username` or reply: Unmutes a user.\n"
        "• `/unban @username` or reply: Unbans a user.\n"
        "• `/cleansystem ON|OFF|STATUS`: Toggle system message cleaning.\n\n"
        "*🧹 Auto-Delete Settings*\n"
        "• `/solexaautodelete`: Show current settings.\n"
        "• `/solexaautodelete [category] [seconds]`: Set timeout (0 = disable).\n"
        "  Categories: `admin`, `error`, `captcha`, `captcha_prompt`, `welcome`, `filter`, `system`\n"
        "  Example: `/solexaautodelete captcha_prompt 120` (CAPTCHA prompt: 120s, others: 30s).\n\n"
        "*📝 Filters*\n"
        "• `/addsolexafilter keyword text`: Add text filter.\n"
        "• `/addsolexafilter keyword [text]`: Add media filter (with media).\n"
        "• `/listsolexafilters`: List filters (admin only).\n"
        "• `/solexafilters`: Show filter keywords (all members).\n"
        "• `/removesolexafilter keyword`: Remove filter.\n\n"
        "*🔒 Captcha*\n"
        "• `/solexacaptcha ON|OFF|status`: Toggle captcha.\n\n"
        "*👋 Welcome Messages*\n"
        "• `/setsolexawelcome <message>`: Set text welcome.\n"
        "• `/setsolexawelcome ON|OFF|status|preview`: Manage welcome.\n"
        "• `/setsolexawelcome` with media: Set media welcome.\n"
        "• `/setsolexawelcomeautodelete ON|OFF|STATUS`: Toggle auto-delete of old welcome messages on new joins.\n\n"
        "*📢 Broadcast*\n"
        "• `/solexabroadcast #tag1 #tag2 Message`: Broadcast to tagged chats (e.g., #solexamain, #trusted, #bottest).\n"
        "  Supports text or media with caption.\n\n"
        "*🎉 General Features*\n"
        "• Keywords like `profits`, `slut`, `launch cat` trigger media.\n"
        "• Use `*bold*`, `_italics_`, `[links](https://example.com)` for formatting.\n\n"
        "*📧 Need Help?*\n"
        "Contact the bot admin. Enjoy! 🎉"
    )
    await send_formatted_and_delete(context, update.effective_chat.id, help_text, "admin")

async def solexacaptcha_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    chat_id = update.message.chat_id
    if not context.args:
        await send_and_delete(context, chat_id, "Usage: /solexacaptcha ON|OFF|status", "admin")
        return
    action = context.args[0].upper()
    if action == "ON":
        captcha_enabled[chat_id] = True
        save_captcha_state()
        await send_and_delete(context, chat_id, "Captcha enabled ✅", "admin")
    elif action == "OFF":
        captcha_enabled[chat_id] = False
        save_captcha_state()
        await send_and_delete(context, chat_id, "Captcha disabled ✅", "admin")
    elif action == "STATUS":
        state = captcha_enabled.get(chat_id, True)
        status_text = "enabled" if state else "disabled"
        await send_and_delete(context, chat_id, f"Captcha is currently {status_text}", "admin")
    else:
        await send_and_delete(context, chat_id, "Usage: /solexacaptcha ON|OFF|status", "admin")

async def setsolexawelcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    chat_id = update.message.chat_id
    if chat_id not in welcome_state:
        welcome_state[chat_id] = {"enabled": False, "type": None, "file_id": None, "text": "", "entities": [], "message_ids": []}
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await send_and_delete(context, chat_id, "Usage: /setsolexawelcome <message> or ON|OFF|status|preview", "admin")
        return
    subcommand = args[1].split()[0].upper() if len(args[1].split()) > 0 else args[1].upper()
    if subcommand in ["ON", "OFF", "STATUS", "PREVIEW"]:
        if subcommand == "ON":
            welcome_state[chat_id]["enabled"] = True
            save_welcome_state()
            await send_and_delete(context, chat_id, "Welcome message enabled ✅", "admin")
        elif subcommand == "OFF":
            welcome_state[chat_id]["enabled"] = False
            save_welcome_state()
            await send_and_delete(context, chat_id, "Welcome message disabled ✅", "admin")
        elif subcommand == "STATUS":
            enabled = welcome_state[chat_id]["enabled"]
            type_ = welcome_state[chat_id]["type"] or "not set"
            text = welcome_state[chat_id]["text"] or "no text"
            await send_and_delete(context, chat_id, f"Welcome is {'enabled' if enabled else 'disabled'}, type: {type_}, text: {text}", "admin")
        elif subcommand == "PREVIEW":
            if not welcome_state[chat_id]["enabled"] or not welcome_state[chat_id]["type"]:
                await send_and_delete(context, chat_id, "No welcome message set", "admin")
                return
            try:
                msg = await send_welcome_message(
                    context,
                    chat_id,
                    welcome_state[chat_id],
                    update.message.from_user.username or update.message.from_user.first_name
                )
                logger.info(f"Preview sent successfully, message_id: {msg.message_id}")
            except Exception as e:
                logger.error(f"Failed to send preview: {e}")
                await send_and_delete(context, chat_id, "Failed to send preview ❌", "error")
    else:
        text = args[1]
        entities = parse_markdown_entities(text)
        welcome_state[chat_id].update({"enabled": True, "type": "text", "file_id": None, "text": text, "entities": entities, "message_ids": []})
        save_welcome_state()
        await send_and_delete(context, chat_id, "Welcome text set ✅", "admin")

async def setsolexawelcome_autodelete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    chat_id = update.message.chat_id
    if not context.args:
        await send_and_delete(context, chat_id, "Usage: /setsolexawelcomeautodelete ON|OFF|STATUS", "admin")
        return
    action = context.args[0].upper()
    if action == "ON":
        welcome_auto_delete[chat_id] = True
        save_welcome_autodelete_state()
        await send_and_delete(context, chat_id, "Welcome message auto-delete enabled ✅", "admin")
    elif action == "OFF":
        welcome_auto_delete[chat_id] = False
        save_welcome_autodelete_state()
        await send_and_delete(context, chat_id, "Welcome message auto-delete disabled ✅", "admin")
    elif action == "STATUS":
        state = welcome_auto_delete.get(chat_id, False)
        status_text = "enabled" if state else "disabled"
        await send_and_delete(context, chat_id, f"Welcome message auto-delete is currently {status_text}", "admin")
    else:
        await send_and_delete(context, chat_id, "Usage: /setsolexawelcomeautodelete ON|OFF|STATUS", "admin")

async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Entered handle_media_message for update: {update.message}")
    if not update.message.caption:
        logger.info("Message skipped: No caption")
        return
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    chat_id = update.message.chat_id
    try:
        admins = await update.effective_chat.get_administrators()
        if update.message.from_user.id not in [admin.user.id for admin in admins]:
            await send_and_delete(context, chat_id, "No permission ❌", "error")
            return
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        await send_and_delete(context, chat_id, "Error checking permissions ❌", "error")
        return
    caption = update.message.caption
    if caption.startswith('/addsolexafilter'):
        args = caption.split(maxsplit=2)
        if len(args) < 2:
            await send_and_delete(context, chat_id, "Usage: Send media with caption '/addsolexafilter keyword [text]'", "admin")
            return
        keyword = args[1].lower()
        raw_text = args[2] if len(args) > 2 else ""
        if chat_id not in filters_dict:
            filters_dict[chat_id] = {}
        try:
            media_type = None
            file_id = None
            if update.message.photo:
                media_type = 'photo'
                file_id = update.message.photo[-1].file_id
            elif update.message.video:
                media_type = 'video'
                file_id = update.message.video.file_id
            elif update.message.audio:
                media_type = 'audio'
                file_id = update.message.audio.file_id
            elif update.message.animation:
                media_type = 'animation'
                file_id = update.message.animation.file_id
            elif update.message.voice:
                media_type = 'voice'
                file_id = update.message.voice.file_id
            elif update.message.document:
                mime_type = update.message.document.mime_type
                if mime_type.startswith('video/'):
                    media_type = 'video'
                    file_id = update.message.document.file_id
                elif mime_type.startswith('image/'):
                    media_type = 'photo'
                    file_id = update.message.document.file_id
                elif mime_type.startswith('audio/'):
                    media_type = 'audio'
                    file_id = update.message.document.file_id
            if media_type and file_id:
                filters_dict[chat_id][keyword] = {'type': media_type, 'file_id': file_id, 'text': raw_text}
                await send_and_delete(context, chat_id, f"{media_type.capitalize()} filter '{keyword}' added ✅", "admin")
                save_filters()
            else:
                await send_and_delete(context, chat_id, "No supported media type detected", "error")
        except Exception as e:
            logger.error(f"Error adding media filter: {e}")
            await send_and_delete(context, chat_id, "Error adding filter ❌", "error")
    elif caption.startswith('/setsolexawelcome'):
        args = caption.split(maxsplit=1)
        raw_caption = args[1] if len(args) > 1 else ""
        if chat_id not in welcome_state:
            welcome_state[chat_id] = {"enabled": False, "type": None, "file_id": None, "text": "", "entities": [], "message_ids": []}
        try:
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                welcome_state[chat_id].update({"enabled": True, "type": "photo", "file_id": file_id, "text": raw_caption, "entities": [], "message_ids": []})
            elif update.message.video:
                file_id = update.message.video.file_id
                welcome_state[chat_id].update({"enabled": True, "type": "video", "file_id": file_id, "text": raw_caption, "entities": [], "message_ids": []})
            elif update.message.animation:
                file_id = update.message.animation.file_id
                welcome_state[chat_id].update({"enabled": True, "type": "animation", "file_id": file_id, "text": raw_caption, "entities": [], "message_ids": []})
            else:
                await send_and_delete(context, chat_id, "Unsupported media type", "error")
                return
            save_welcome_state()
            await send_and_delete(context, chat_id, f"{welcome_state[chat_id]['type'].capitalize()} welcome set ✅", "admin")
        except Exception as e:
            logger.error(f"Error setting media welcome message: {e}")
            await send_and_delete(context, chat_id, "Error setting welcome message ❌", "error")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
                if user_id:
                    target_user = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await send_and_delete(context, update.message.chat_id, f"Error: User {target_user} not found.", "error")
                return
            await context.bot.ban_chat_member(update.message.chat_id, user_id)
            await send_and_delete(context, update.message.chat_id, f"User {target_user} banned ✅", "admin")
        except IndexError:
            await send_and_delete(context, update.message.chat_id, "Usage: /ban @username or reply to a user", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
                if user_id:
                    target_user = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await send_and_delete(context, update.message.chat_id, f"Error: User {target_user} not found.", "error")
                return
            await context.bot.ban_chat_member(update.message.chat_id, user_id)
            await context.bot.unban_chat_member(update.message.chat_id, user_id, only_if_banned=True)
            await send_and_delete(context, update.message.chat_id, f"User {target_user} kicked ✅", "admin")
        except IndexError:
            await send_and_delete(context, update.message.chat_id, "Usage: /kick @username or reply to a user", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: timedelta):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
                if user_id:
                    target_user = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await send_and_delete(context, update.message.chat_id, f"Error: User {target_user} not found.", "error")
                return
            permissions = ChatPermissions(can_send_messages=False)
            until = update.message.date + duration
            await context.bot.restrict_chat_member(update.message.chat_id, user_id, permissions, until_date=until)
            await send_and_delete(context, update.message.chat_id, f"User {target_user} muted for {int(duration.total_seconds()/60)} minutes ✅", "admin")
        except IndexError:
            await send_and_delete(context, update.message.chat_id, f"Usage: /mute10 @username or reply to a user", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def mute10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(minutes=10))

async def mute30(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(minutes=30))

async def mute1hr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(hours=1))

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
                if user_id:
                    target_user = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await send_and_delete(context, update.message.chat_id, f"Error: User {target_user} not found.", "error")
                return
            permissions = ChatPermissions(
                can_send_messages=True, can_send_photos=True, can_send_videos=True,
                can_send_other_messages=True, can_send_polls=True, can_add_web_page_previews=True
            )
            await context.bot.restrict_chat_member(update.message.chat_id, user_id, permissions)
            await send_and_delete(context, update.message.chat_id, f"User {target_user} unmuted ✅", "admin")
        except IndexError:
            await send_and_delete(context, update.message.chat_id, "Usage: /unmute @username or reply to a user", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
                if user_id:
                    target_user = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await send_and_delete(context, update.message.chat_id, f"Error: User {target_user} not found.", "error")
                return
            await context.bot.unban_chat_member(update.message.chat_id, user_id)
            await send_and_delete(context, update.message.chat_id, f"User {target_user} unbanned ✅", "admin")
        except IndexError:
            await send_and_delete(context, update.message.chat_id, "Usage: /unban @username or reply to a user", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def add_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        chat_id = update.message.chat_id
        if not context.args or len(context.args) < 2:
            await send_and_delete(context, chat_id, "Usage: /addsolexafilter keyword text", "admin")
            return
        keyword = context.args[0].lower()
        response_text = " ".join(context.args[1:])
        if chat_id not in filters_dict:
            filters_dict[chat_id] = {}
        filters_dict[chat_id][keyword] = response_text
        save_filters()
        await send_and_delete(context, chat_id, f"Text filter '{keyword}' added ✅", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        chat_id = update.message.chat_id
        filters_list = filters_dict.get(chat_id, {})
        if filters_list:
            filter_texts = []
            for k, v in filters_list.items():
                if isinstance(v, dict) and 'type' in v:
                    text_part = f" - {v['text']}" if v.get('text') else ""
                    filter_texts.append(f"{k}: [{v['type']}]{text_part}")
                elif isinstance(v, str):
                    filter_texts.append(f"{k}: {v}")
                else:
                    filter_texts.append(f"{k}: [invalid format]")
            await send_and_delete(context, chat_id, f"Filters:\n{chr(10).join(filter_texts)}", "admin")
        else:
            await send_and_delete(context, chat_id, "No filters set", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def solexafilters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    chat_id = update.message.chat_id
    filters_list = filters_dict.get(chat_id, {})
    if filters_list:
        filter_keywords = sorted(filters_list.keys())
        filter_text = "*Available Filters:*\n" + "\n".join(f"/{keyword}" for keyword in filter_keywords)
        await send_formatted_and_delete(context, chat_id, filter_text, "admin")
    else:
        await send_and_delete(context, chat_id, "No filters available in this group.", "filter")

async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            keyword = context.args[0].lower()
            chat_id = update.message.chat_id
            if chat_id in filters_dict and keyword in filters_dict[chat_id]:
                del filters_dict[chat_id][keyword]
                save_filters()
                await send_and_delete(context, chat_id, f"Filter '{keyword}' removed ✅", "admin")
            else:
                await send_and_delete(context, chat_id, "Filter not found ❌", "error")
        except IndexError:
            await send_and_delete(context, update.message.chat_id, "Usage: /removesolexafilter keyword", "admin")
    else:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")

async def solexafixwelcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    chat_id = update.message.chat_id
    if chat_id not in welcome_state or not welcome_state[chat_id]["enabled"]:
        await send_and_delete(context, chat_id, "No welcome message is currently set.", "admin")
        return
    ws = welcome_state[chat_id]
    await send_and_delete(context, chat_id,
        f"Welcome message diagnostic info:\n"
        f"- Type: {ws['type']}\n"
        f"- Raw text: {ws['text']}\n"
        f"- Has entities: {'Yes' if ws.get('entities') else 'No'}\n"
        f"- Num entities: {len(ws.get('entities', []))}", "admin")
    original_text = ws["text"]
    username = update.message.from_user.username or update.message.from_user.first_name
    sample_text = original_text.replace("{username}", username)
    await send_and_delete(context, chat_id, f"Raw sample with your username:\n{sample_text}", "admin")
    processed_text = process_markdown_v2(sample_text)
    await send_and_delete(context, chat_id, f"Processed markdown: \n{processed_text}", "admin")

async def solexabroadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await send_and_delete(context, update.message.chat_id, "Group-only command ❌", "error")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await send_and_delete(context, update.message.chat_id, "No permission ❌", "error")
        return
    chat_id = update.message.chat_id
    
    # Check if message has text or caption
    message_text = update.message.text or update.message.caption or ""
    if not message_text.startswith('/solexabroadcast'):
        await send_and_delete(context, chat_id, "Usage: /solexabroadcast #chat1 #chat2 Message here\nAvailable tags: #solexamain, #trusted, #bottest", "admin")
        return
    
    args = message_text.split()
    if len(args) < 2:
        await send_and_delete(context, chat_id, "Usage: /solexabroadcast #chat1 #chat2 Message here\nAvailable tags: #solexamain, #trusted, #bottest", "admin")
        return
    
    # Extract target tags and message
    target_tags = [arg for arg in args[1:] if arg.startswith("#")]
    message_start_idx = len(target_tags) + 1  # After command and tags
    broadcast_content = " ".join(args[message_start_idx:]) if message_start_idx < len(args) else ""
    
    if not target_tags:
        await send_and_delete(context, chat_id, "Please specify at least one chat tag (e.g., #solexamain)", "admin")
        return

    # Determine media type and file_id if present
    media_type = None
    file_id = None
    if update.message.photo:
        media_type = "photo"
        file_id = update.message.photo[-1].file_id
    elif update.message.video:
        media_type = "video"
        file_id = update.message.video.file_id
    elif update.message.animation:
        media_type = "animation"
        file_id = update.message.animation.file_id
    elif update.message.audio:
        media_type = "audio"
        file_id = update.message.audio.file_id
    elif update.message.voice:
        media_type = "voice"
        file_id = update.message.voice.file_id
    elif update.message.document:
        mime_type = update.message.document.mime_type
        if mime_type.startswith('video/'):
            media_type = 'video'
            file_id = update.message.document.file_id
        elif mime_type.startswith('image/'):
            media_type = 'photo'
            file_id = update.message.document.file_id
        elif mime_type.startswith('audio/'):
            media_type = 'audio'
            file_id = update.message.document.file_id

    # Validate targets
    valid_targets = []
    for tag in target_tags:
        if tag in chat_ids_map:
            valid_targets.append(chat_ids_map[tag])
        else:
            await send_and_delete(context, chat_id, f"Chat tag {tag} not found in Solexa's rooms", "error")
    
    if not valid_targets:
        await send_and_delete(context, chat_id, "No valid chat targets specified", "error")
        return

    # Broadcast the message (no "Solexa says:" prefix)
    failed_chats = []
    for target_chat_id in valid_targets:
        try:
            await send_formatted_and_delete(
                context,
                target_chat_id,
                broadcast_content,
                "system",
                message_type=media_type or "text",
                file_id=file_id
            )
            logger.info(f"Broadcast sent to {target_chat_id}")
        except Exception as e:
            logger.error(f"Failed to broadcast to {target_chat_id}: {e}")
            failed_chats.append(target_chat_id)
    
    # Report success/failure
    if failed_chats:
        await send_and_delete(context, chat_id, f"Broadcast sent, but failed for chats: {', '.join(map(str, failed_chats))}", "admin")
    else:
        await send_and_delete(context, chat_id, "Broadcast sent to all specified chats ✅", "admin")

def parse_markdown_entities(text):
    return []

application.add_handler(CommandHandler("solexahelp", solexahelp_command))
application.add_handler(CommandHandler("solexacaptcha", solexacaptcha_command))
application.add_handler(CommandHandler("setsolexawelcome", setsolexawelcome_command))
application.add_handler(CommandHandler("setsolexawelcomeautodelete", setsolexawelcome_autodelete_command))
application.add_handler(CommandHandler("cleansystem", cleansystem_command))
application.add_handler(CommandHandler("solexaautodelete", solexaautodelete_command))
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(CommandHandler("mute10", mute10))
application.add_handler(CommandHandler("mute30", mute30))
application.add_handler(CommandHandler("mute1hr", mute1hr))
application.add_handler(CommandHandler("unmute", unmute_user))
application.add_handler(CommandHandler("unban", unban_user))
application.add_handler(CommandHandler("addsolexafilter", add_text_filter))
application.add_handler(CommandHandler("listsolexafilters", list_filters))
application.add_handler(CommandHandler("solexafilters", solexafilters_command))
application.add_handler(CommandHandler("removesolexafilter", remove_filter))
application.add_handler(CommandHandler("solexafixwelcome", solexafixwelcome_command))
application.add_handler(CommandHandler("solexabroadcast", solexabroadcast_command))

application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.ANIMATION | filters.VOICE, handle_media_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(MessageHandler(
    ~filters.TEXT & ~filters.COMMAND & ~filters.PHOTO & ~filters.VIDEO & 
    ~filters.AUDIO & ~filters.VOICE & ~filters.ANIMATION & ~filters.StatusUpdate.NEW_CHAT_MEMBERS,
    handle_system_messages
))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.COMMAND, handle_command_as_filter))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"^captcha_\d+_\d+$"))

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
    load_cleansystem_state()
    load_autodelete_config()
    load_welcome_autodelete_state()
    load_chat_ids()
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)