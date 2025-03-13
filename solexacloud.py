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
                await context.bot.send_message(chat_id=chat_id, text=f"Welcome {username}! Please verify yourself.\n\n{question}", reply_markup=reply_markup)
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
                new_message_id = None  # Temporary storage for the new message ID
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
                    new_message_id = msg.message_id  # Capture the new message ID
                    logger.info(f"Welcome message sent successfully, message_id: {new_message_id}")
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
                    new_message_id = msg.message_id  # Capture the new message ID in fallback
                    logger.info(f"Fallback welcome message sent, message_id: {new_message_id}")

                # Clear old welcome messages *before* adding the new one
                if "message_ids" in welcome_state[chat_id]:
                    for msg_id in welcome_state[chat_id]["message_ids"][:]:
                        try:
                            await context.bot.delete_message(chat_id, msg_id)
                            welcome_state[chat_id]["message_ids"].remove(msg_id)
                            logger.info(f"Successfully deleted old welcome message {msg_id}")
                        except Exception as e:
                            logger.error(f"Failed to delete welcome message {msg_id}: {e}")
                
                # Now add the new message ID to the list
                if new_message_id:
                    welcome_state[chat_id].setdefault("message_ids", []).append(new_message_id)
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
                        escaped_text = escape_markdown_v2(text)
                        if media_type == 'photo':
                            await update.message.reply_photo(photo=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                        elif media_type == 'video':
                            await update.message.reply_video(video=file_id, caption=escaped_text, parse_mode='MarkdownV2', supports_streaming=True)
                        elif media_type == 'audio':
                            await update.message.reply_audio(audio=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                        elif media_type == 'animation':
                            await update.message.reply_animation(animation=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                        elif media_type == 'voice':
                            await update.message.reply_voice(voice=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                    elif isinstance(response, str):
                        escaped_text = escape_markdown_v2(response)
                        await update.message.reply_text(escaped_text, parse_mode='MarkdownV2')
                    return
        for keyword, media_file in keyword_responses.items():
            if message_text == keyword:
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
                        escaped_text = escape_markdown_v2(text)
                        if media_type == 'photo':
                            await update.message.reply_photo(photo=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                        elif media_type == 'video':
                            await update.message.reply_video(video=file_id, caption=escaped_text, parse_mode='MarkdownV2', supports_streaming=True)
                        elif media_type == 'audio':
                            await update.message.reply_audio(audio=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                        elif media_type == 'animation':
                            await update.message.reply_animation(animation=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                        elif media_type == 'voice':
                            await update.message.reply_voice(voice=file_id, caption=escaped_text, parse_mode='MarkdownV2')
                    elif isinstance(response, str):
                        escaped_text = escape_markdown_v2(response)
                        await update.message.reply_text(escaped_text, parse_mode='MarkdownV2')
                    return
    except Exception as e:
        logger.error(f"Filter error: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Features:\n"
        "- Keywords: audio/video/profits/etc → media files\n"
        "- New members must solve captcha (toggle with /solexacaptcha ON|OFF)\n"
        "- Custom welcome message after verification (set with /setsolexawelcome <message> or media, use {username})\n"
        "- Admin commands: /ban, /kick, /mute10/30/1hr, /addsolexafilter, /unban, etc\n"
        "- Use /addsolexafilter keyword [text] or send media with caption '/addsolexafilter keyword [text]'\n"
        "- Supports *bold*, _italics_, [hyperlinks](https://example.com), and links\n"
        "- Contact admin for help"
    )
    escaped_help_text = escape_markdown_v2(help_text)
    await update.message.reply_text(escaped_help_text, parse_mode='MarkdownV2')

async def solexacaptcha_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await update.message.reply_text("Group-only command ❌")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("No permission ❌")
        return
    chat_id = update.message.chat_id
    if not context.args:
        await update.message.reply_text("Usage: /solexacaptcha ON|OFF|status")
        return
    action = context.args[0].upper()
    if action == "ON":
        captcha_enabled[chat_id] = True
        save_captcha_state()
        await update.message.reply_text("Captcha enabled ✅")
    elif action == "OFF":
        captcha_enabled[chat_id] = False
        save_captcha_state()
        await update.message.reply_text("Captcha disabled ✅")
    elif action == "STATUS":
        state = captcha_enabled.get(chat_id, True)
        status_text = "enabled" if state else "disabled"
        await update.message.reply_text(f"Captcha is currently {status_text}")
    else:
        await update.message.reply_text("Usage: /solexacaptcha ON|OFF|status")

async def setsolexawelcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await update.message.reply_text("Group-only command ❌")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("No permission ❌")
        return
    chat_id = update.message.chat_id
    if chat_id not in welcome_state:
        welcome_state[chat_id] = {"enabled": False, "type": None, "file_id": None, "text": "", "entities": [], "message_ids": []}

    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("Usage: /setsolexawelcome <message> or ON|OFF|status|preview")
        return
    subcommand = args[1].split()[0].upper() if len(args[1].split()) > 0 else args[1].upper()
    if subcommand in ["ON", "OFF", "STATUS", "PREVIEW"]:
        if subcommand == "ON":
            welcome_state[chat_id]["enabled"] = True
            save_welcome_state()
            await update.message.reply_text("Welcome message enabled ✅")
        elif subcommand == "OFF":
            welcome_state[chat_id]["enabled"] = False
            save_welcome_state()
            await update.message.reply_text("Welcome message disabled ✅")
        elif subcommand == "STATUS":
            enabled = welcome_state[chat_id]["enabled"]
            type_ = welcome_state[chat_id]["type"] or "not set"
            text = welcome_state[chat_id]["text"] or "no text"
            await update.message.reply_text(f"Welcome is {'enabled' if enabled else 'disabled'}, type: {type_}, text: {text}")
        elif subcommand == "PREVIEW":
            if not welcome_state[chat_id]["enabled"] or not welcome_state[chat_id]["type"]:
                await update.message.reply_text("No welcome message set")
                return
            ws = welcome_state[chat_id]
            text = ws["text"].replace("{username}", update.message.from_user.username or update.message.from_user.first_name)
            escaped_text = escape_markdown_v2(text)
            try:
                logger.info(f"Sending preview with MarkdownV2: {repr(escaped_text)}")
                if ws["type"] == "text":
                    msg = await context.bot.send_message(chat_id, escaped_text, parse_mode='MarkdownV2')
                elif ws["type"] == "photo":
                    msg = await context.bot.send_photo(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                elif ws["type"] == "video":
                    msg = await context.bot.send_video(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                elif ws["type"] == "animation":
                    msg = await context.bot.send_animation(chat_id, ws["file_id"], caption=escaped_text, parse_mode='MarkdownV2')
                logger.info(f"Preview sent successfully, message_id: {msg.message_id}")
            except Exception as e:
                logger.error(f"Failed to send preview with MarkdownV2: {e}")
                logger.info(f"Falling back to plain text: {text}")
                if ws["type"] == "text":
                    msg = await context.bot.send_message(chat_id, text, parse_mode=None)
                elif ws["type"] == "photo":
                    msg = await context.bot.send_photo(chat_id, ws["file_id"], caption=text, parse_mode=None)
                elif ws["type"] == "video":
                    msg = await context.bot.send_video(chat_id, ws["file_id"], caption=text, parse_mode=None)
                elif ws["type"] == "animation":
                    msg = await context.bot.send_animation(chat_id, ws["file_id"], caption=text, parse_mode=None)
                logger.info(f"Fallback preview sent, message_id: {msg.message_id}")
    else:
        text = args[1]
        welcome_state[chat_id].update({"enabled": True, "type": "text", "file_id": None, "text": text, "entities": [], "message_ids": []})
        save_welcome_state()
        await update.message.reply_text("Welcome text set ✅")

async def setsolexawelcome_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.caption or not update.message.caption.startswith('/setsolexawelcome'):
        return
    if update.message.chat.type == "private":
        await update.message.reply_text("Group-only command ❌")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("No permission ❌")
        return
    chat_id = update.message.chat_id
    if chat_id not in welcome_state:
        welcome_state[chat_id] = {"enabled": False, "type": None, "file_id": None, "text": "", "entities": [], "message_ids": []}

    args = update.message.caption.split(maxsplit=1)
    raw_caption = args[1] if len(args) > 1 else ""
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
        await update.message.reply_text("Unsupported media type")
        return
    save_welcome_state()
    await update.message.reply_text(f"{welcome_state[chat_id]['type'].capitalize()} welcome set ✅")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User {target_user} not found.")
                return
            await context.bot.ban_chat_member(update.message.chat_id, user_id)
            await update.message.reply_text(f"User {target_user} banned ✅")
        except IndexError:
            await update.message.reply_text("Usage: /ban @username or reply to a user")
    else:
        await update.message.reply_text("No permission ❌")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User {target_user} not found.")
                return
            await context.bot.ban_chat_member(update.message.chat_id, user_id)
            await context.bot.unban_chat_member(update.message.chat_id, user_id, only_if_banned=True)
            await update.message.reply_text(f"User {target_user} kicked ✅")
        except IndexError:
            await update.message.reply_text("Usage: /kick @username or reply to a user")
    else:
        await update.message.reply_text("No permission ❌")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: timedelta):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User {target_user} not found.")
                return
            permissions = ChatPermissions(can_send_messages=False)
            until = update.message.date + duration
            await context.bot.restrict_chat_member(update.message.chat_id, user_id, permissions, until_date=until)
            await update.message.reply_text(f"User {target_user} muted for {int(duration.total_seconds()/60)} minutes ✅")
        except IndexError:
            await update.message.reply_text(f"Usage: /mute10 @username or reply to a user")
    else:
        await update.message.reply_text("No permission ❌")

async def mute10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(minutes=10))

async def mute30(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(minutes=30))

async def mute1hr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(hours=1))

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        try:
            target_user = context.args[0] if context.args else None
            if not target_user:
                user_id = await get_user_id_from_reply(update)
            else:
                user_id = await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User {target_user} not found.")
                return
            await context.bot.unban_chat_member(update.message.chat_id, user_id)
            await update.message.reply_text(f"User {target_user} unbanned ✅")
        except IndexError:
            await update.message.reply_text("Usage: /unban @username or reply to a user")
    else:
        await update.message.reply_text("No permission ❌")

async def add_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        chat_id = update.message.chat_id
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /addsolexafilter keyword text")
            return
        keyword = context.args[0].lower()
        response_text = " ".join(context.args[1:])
        if chat_id not in filters_dict:
            filters_dict[chat_id] = {}
        filters_dict[chat_id][keyword] = response_text
        save_filters()
        await update.message.reply_text(f"Text filter '{keyword}' added ✅")
    else:
        await update.message.reply_text("No permission ❌")

async def add_media_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Entered add_media_filter for update: {update.message}")
    if not update.message.caption or not update.message.caption.startswith('/addsolexafilter'):
        logger.info("Message skipped: No caption or not starting with /addsolexafilter")
        return

    if update.message.chat.type == "private":
        await update.message.reply_text("Group-only command ❌")
        return
    chat_id = update.message.chat_id
    try:
        admins = await update.effective_chat.get_administrators()
        logger.info(f"Checking admin status for user {update.message.from_user.id}")
        if update.message.from_user.id not in [admin.user.id for admin in admins]:
            await update.message.reply_text("No permission ❌")
            logger.info(f"User {update.message.from_user.id} lacks admin permission")
            return
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        await update.message.reply_text("Error checking permissions ❌")
        return

    caption = update.message.caption
    args = caption.split(maxsplit=2)
    logger.info(f"Caption split: {args}")
    if len(args) < 2:
        await update.message.reply_text("Usage: Send media with caption '/addsolexafilter keyword [text]'")
        logger.info("Invalid caption format: Too few arguments")
        return
    keyword = args[1].lower()
    raw_text = args[2] if len(args) > 2 else ""
    logger.info(f"Keyword: {keyword}, Text: {raw_text}")

    if chat_id not in filters_dict:
        filters_dict[chat_id] = {}
        logger.info(f"Initialized filters_dict for chat {chat_id}")

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
            await update.message.reply_text(f"{media_type.capitalize()} filter '{keyword}' added ✅")
            logger.info(f"Added {media_type} filter: {keyword}")
        else:
            await update.message.reply_text("No supported media type detected")
            logger.info("No supported media type found in message")
            return

        save_filters()
        logger.info(f"Filters saved after adding {keyword}")
    except Exception as e:
        logger.error(f"Error adding media filter: {e}")
        await update.message.reply_text("Error adding filter ❌")

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
            await update.message.reply_text(f"Filters:\n{chr(10).join(filter_texts)}")
        else:
            await update.message.reply_text("No filters set")
    else:
        await update.message.reply_text("No permission ❌")

async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
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

application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("solexacaptcha", solexacaptcha_command))
application.add_handler(CommandHandler("setsolexawelcome", setsolexawelcome_command))
application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION, setsolexawelcome_media))
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(CommandHandler("mute10", mute10))
application.add_handler(CommandHandler("mute30", mute30))
application.add_handler(CommandHandler("mute1hr", mute1hr))
application.add_handler(CommandHandler("unban", unban_user))
application.add_handler(CommandHandler("addsolexafilter", add_text_filter))
application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.ANIMATION | filters.VOICE | filters.Document, add_media_filter))
application.add_handler(CommandHandler("listsolexafilters", list_filters))
application.add_handler(CommandHandler("removesolexafilter", remove_filter))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
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
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)