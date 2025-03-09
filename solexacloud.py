import os
import logging
import json
import random
import re
from datetime import timedelta
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
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

# Dictionaries for state management
user_id_cache = {}  # {chat_id: {"username": user_id}}
keyword_responses = {
    "PutMP3TriggerKeywordHere": "PUTmp3FILEnameHere.mp3",
    "PutVideoTriggerKeywordHere": "PutMp4FileNameHere.mp4",
    "profits": "PROFITS.jpg",
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"
}
FILTERS_FILE = "/data/filters.json"
filters_dict = {}
CLEANSERVICE_FILE = "/data/cleanservice.json"
cleanservice_state = {}  # {chat_id: {'enabled': True/False, 'delay': int}}
WELCOME_FILE = "/data/welcome.json"
welcome_dict = {}  # {chat_id: {'enabled': True/False, 'type': str, 'file_id': str or None, 'text': str}}
last_welcome_msg = {}  # {chat_id: message_id}
CAPTCHA_FILE = "/data/captcha.json"
captcha_state = {}  # {chat_id: True/False}
BLACKLIST_FILE = "/data/blacklist.json"
blacklist_dict = {}  # {chat_id: {'terms': set(), 'users': {user_id: offense_count}}}

def ensure_file_exists(file_path, default_content):
    if not os.path.exists(file_path):
        try:
            with open(file_path, 'w') as f:
                json.dump(default_content, f)
            logger.info(f"Created default file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to create {file_path}: {e}")

def load_state(file_path, state_dict, default_factory=lambda: {}):
    ensure_file_exists(file_path, {})
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            if not data:  # Apply default_factory if the file is empty
                logger.info(f"{file_path} is empty, applying default_factory")
                state_dict.clear()
                state_dict.update(default_factory())
            else:
                for chat_id, value in data.items():
                    chat_id = int(chat_id)
                    if file_path == BLACKLIST_FILE:
                        value['terms'] = set(value['terms'])
                        value['users'] = {int(k): v for k, v in value['users'].items()}
                    state_dict[chat_id] = value
        logger.info(f"Loaded {file_path}: {repr(state_dict)}")
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
        state_dict.clear()
        state_dict.update(default_factory())

def save_state(file_path, state_dict):
    try:
        with open(file_path, 'w') as f:
            serializable = {str(k): v for k, v in state_dict.items()}
            if file_path == BLACKLIST_FILE:
                for chat_id in serializable:
                    serializable[chat_id]['terms'] = list(serializable[chat_id]['terms'])
            json.dump(serializable, f)
        logger.info(f"Saved {file_path}: {repr(state_dict)}")
    except Exception as e:
        logger.error(f"Error saving {file_path}: {e}")

def load_filters(): 
    load_state(FILTERS_FILE, filters_dict)
    logger.info(f"Filters loaded: {repr(filters_dict)}")
def save_filters(): save_state(FILTERS_FILE, filters_dict)
def load_cleanservice(): 
    load_state(CLEANSERVICE_FILE, cleanservice_state, lambda: {-1002280396764: {'enabled': False, 'delay': 15} if not filters_dict else {chat_id: {'enabled': False, 'delay': 15} for chat_id in filters_dict.keys()}))
def save_cleanservice(): save_state(CLEANSERVICE_FILE, cleanservice_state)
def load_welcome(): 
    load_state(WELCOME_FILE, welcome_dict, lambda: {-1002280396764: {'enabled': False, 'type': 'text', 'file_id': None, 'text': ''} if not filters_dict else {chat_id: {'enabled': False, 'type': 'text', 'file_id': None, 'text': ''} for chat_id in filters_dict.keys()}))
def save_welcome(): save_state(WELCOME_FILE, welcome_dict)
def load_captcha(): 
    load_state(CAPTCHA_FILE, captcha_state, lambda: {-1002280396764: True if not filters_dict else {chat_id: True for chat_id in filters_dict.keys()}))
def save_captcha(): save_state(CAPTCHA_FILE, captcha_state)
def load_blacklist(): 
    load_state(BLACKLIST_FILE, blacklist_dict, lambda: {-1002280396764: {'terms': set(), 'users': {}} if not filters_dict else {chat_id: {'terms': set(), 'users': {}} for chat_id in filters_dict.keys()}))
def save_blacklist(): save_state(BLACKLIST_FILE, blacklist_dict)

def escape_markdown_v2(text):
    reserved_chars = r"[-()~`>#+|=|{}.!]"
    patterns = [r'(\[.*?\]\(.*?\))', r'(\*\*[^\*]*\*\*)', r'(__[^_]*__)']
    combined_pattern = '|'.join(patterns) + f'|({reserved_chars})'
    def replace_func(match):
        for i in range(1, 4):
            if match.group(i): return match.group(i)
        return '\\' + match.group(4)
    escaped_text = re.sub(combined_pattern, replace_func, text)
    logger.info(f"Escaped text: {repr(escaped_text)}")
    return escaped_text

def escape_pipe(text):
    escaped_text = text.replace('|', r'\|')
    logger.info(f"Escaped pipe: {repr(escaped_text)}")
    return escaped_text

def apply_entities_to_caption(caption, entities):
    if not entities or not caption: return caption
    result = list(caption)
    offset_shift = 0
    for entity in sorted(entities, key=lambda e: e.offset):
        start = entity.offset + offset_shift
        end = start + entity.length
        if start >= len(result) or end > len(result):
            logger.warning(f"Entity out of bounds: {entity}, caption length: {len(result)}")
            continue
        entity_text = ''.join(result[start:end])
        if entity.type == "bold": new_text = f"*{entity_text}*"
        elif entity.type == "italic": new_text = f"_{entity_text}_"
        elif entity.type == "url" and entity.url: new_text = f"[{entity_text}]({entity.url})"
        else: new_text = entity_text
        del result[start:end]
        result[start:start] = list(new_text)
        offset_shift += len(new_text) - entity.length
    final_text = ''.join(result)
    logger.info(f"Text with entities: {repr(final_text)}")
    return final_text

def generate_captcha():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    correct_answer = num1 + num2
    wrong_answers = set()
    while len(wrong_answers) < 3:
        wrong = random.randint(1, 20)
        if wrong != correct_answer: wrong_answers.add(wrong)
    options = list(wrong_answers) + [correct_answer]
    random.shuffle(options)
    return f"What is {num1} + {num2}?", options, correct_answer

async def is_admin(user_id, chat_id, context):
    try:
        admins = [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]
        is_admin = user_id in admins
        logger.info(f"Admin check for {user_id} in {chat_id}: {is_admin}")
        return is_admin
    except Exception as e:
        logger.error(f"Failed to check admin status for {user_id} in {chat_id}: {e}")
        return False

async def resolve_user(chat_id: int, target_user: str, context: ContextTypes.DEFAULT_TYPE) -> int or None:
    try:
        if target_user.startswith("@"):
            username = target_user[1:].lower()
            logger.info(f"Resolving @{username} in {chat_id}")
            if chat_id in user_id_cache and username in user_id_cache[chat_id]:
                return user_id_cache[chat_id][username]
            logger.warning(f"@{username} not in cache for {chat_id}")
            return None
        user_id = int(target_user)
        logger.info(f"Using user ID: {user_id}")
        return user_id
    except Exception as e:
        logger.error(f"Error resolving user: {e}")
        return None

async def get_user_id_from_reply(update: Update) -> int or None:
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user.id
    return None

async def delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id, message_id)
        logger.info(f"Deleted message {message_id} in {chat_id}")
    except Exception as e:
        logger.error(f"Error deleting {message_id} in {chat_id}: {e}")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.message.chat_id
        for member in update.message.new_chat_members:
            user_id = member.id
            username = member.username or member.first_name
            logger.info(f"New member: {username} (ID: {user_id}) in {chat_id}")
            if chat_id not in user_id_cache: user_id_cache[chat_id] = {}
            if member.username: user_id_cache[chat_id][member.username.lower()] = user_id
            permissions = ChatPermissions(can_send_messages=False)
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            # Cleanup previous welcome
            if chat_id in last_welcome_msg:
                await delete_message(context, chat_id, last_welcome_msg[chat_id])
            # Send welcome
            if chat_id not in welcome_dict:
                welcome_dict[chat_id] = {'enabled': False, 'type': 'text', 'file_id': None, 'text': ''}
                logger.info(f"Initialized welcome_dict for {chat_id}: {welcome_dict[chat_id]}")
            if welcome_dict[chat_id]['enabled']:
                welcome = welcome_dict[chat_id]
                text = welcome['text'].replace('{username}', username) if welcome['text'] else ""
                text = escape_pipe(text)
                if welcome['type'] == 'text':
                    msg = await context.bot.send_message(chat_id, text, parse_mode='MarkdownV2')
                elif welcome['type'] == 'photo':
                    msg = await context.bot.send_photo(chat_id, welcome['file_id'], caption=text, parse_mode='MarkdownV2')
                elif welcome['type'] == 'video':
                    msg = await context.bot.send_video(chat_id, welcome['file_id'], caption=text, parse_mode='MarkdownV2', supports_streaming=True)
                elif welcome['type'] == 'animation':
                    msg = await context.bot.send_animation(chat_id, welcome['file_id'], caption=text, parse_mode='MarkdownV2')
                last_welcome_msg[chat_id] = msg.message_id
            # Captcha
            if chat_id not in captcha_state:
                captcha_state[chat_id] = True
                logger.info(f"Initialized captcha_state for {chat_id}: {captcha_state[chat_id]}")
            if captcha_state[chat_id]:
                question, options, correct_answer = generate_captcha()
                captcha_attempts[user_id] = {"answer": correct_answer, "attempts": 0, "chat_id": chat_id}
                keyboard = [[InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")] for opt in options]
                reply_markup = InlineKeyboardMarkup(keyboard)
                welcome_text = f"Welcome {username}! Please verify yourself.\n\n{question}"
                msg = await context.bot.send_message(chat_id, welcome_text, reply_markup=reply_markup)
                last_welcome_msg[chat_id] = msg.message_id
            else:
                logger.info(f"Captcha disabled, unrestricting {user_id}")
                await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions(
                    can_send_messages=True, can_send_photos=True, can_send_videos=True,
                    can_send_other_messages=True, can_send_polls=True, can_add_web_page_previews=True
                ))
    except Exception as e:
        logger.error(f"Error in welcome_new_member: {e}")

async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data.split("_")
        if len(data) != 3: return
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
        attempts = captcha_attempts[target_user_id]["attempts"]
        if answer == correct_answer:
            permissions = ChatPermissions(
                can_send_messages=True, can_send_photos=True, can_send_videos=True,
                can_send_other_messages=True, can_send_polls=True, can_add_web_page_previews=True
            )
            await context.bot.restrict_chat_member(chat_id, target_user_id, permissions)
            await query.message.edit_text("✅ Verified!")
            if chat_id in cleanservice_state and cleanservice_state[chat_id]['enabled']:
                delay = cleanservice_state[chat_id]['delay']
                context.job_queue.run_once(delete_message, delay, data=(chat_id, query.message.message_id))
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
        if not update.message or not update.message.text: return
        chat_id = update.message.chat_id
        user = update.message.from_user
        if user.username:
            if chat_id not in user_id_cache: user_id_cache[chat_id] = {}
            user_id_cache[chat_id][user.username.lower()] = user.id
        # Blacklist check
        if chat_id not in blacklist_dict:
            blacklist_dict[chat_id] = {'terms': set(), 'users': {}}
            logger.info(f"Initialized blacklist_dict for {chat_id}: {blacklist_dict[chat_id]}")
        if blacklist_dict[chat_id]['terms']:
            message_text = update.message.text.lower()
            for term in blacklist_dict[chat_id]['terms']:
                if term in message_text:
                    user_id = user.id
                    if chat_id not in blacklist_dict[chat_id]['users']: blacklist_dict[chat_id]['users'] = {}
                    offenses = blacklist_dict[chat_id]['users'].get(user_id, 0)
                    offenses += 1
                    blacklist_dict[chat_id]['users'][user_id] = offenses
                    save_blacklist()
                    warning = "Solexa has a 0 tolerance policy for FUD, spam, and nonsense. Please message an admin if you feel that you've been muted erroneously."
                    if offenses == 1:
                        await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False), until_date=update.message.date + timedelta(minutes=10))
                        await update.message.reply_text(f"{warning}\nMuted for 10 minutes. Next offense: 30-minute mute.")
                        logger.info(f"Muted {user_id} for 10m, offense 1, term: {term}")
                    elif offenses == 2:
                        await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False), until_date=update.message.date + timedelta(minutes=30))
                        await update.message.reply_text(f"{warning}\nMuted for 30 minutes. Next offense: Kick.")
                        logger.info(f"Muted {user_id} for 30m, offense 2, term: {term}")
                    else:
                        await context.bot.ban_chat_member(chat_id, user_id)
                        await context.bot.unban_chat_member(chat_id, user_id)
                        await update.message.reply_text(f"{warning}\nKicked from group.")
                        del blacklist_dict[chat_id]['users'][user_id]
                        save_blacklist()
                        logger.info(f"Kicked {user_id}, offense 3, term: {term}")
                    return
        # Filter handling
        message_text = update.message.text.strip().lower()
        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if message_text == keyword or message_text == f"/{keyword}":
                    if isinstance(response, dict) and 'type' in response and 'file_id' in response:
                        media_type = response['type']
                        file_id = response['file_id']
                        text = response.get('text', '')
                        escaped_text = escape_pipe(text)
                        logger.info(f"Triggering filter: {keyword} with {media_type}, caption: {repr(escaped_text)}")
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
                        await update.message.reply_text(response, parse_mode='MarkdownV2')
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
        if not update.message or not update.message.text: return
        message_text = update.message.text.strip().lower()
        chat_id = update.message.chat_id
        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if message_text == f"/{keyword}":
                    if isinstance(response, dict) and 'type' in response and 'file_id' in response:
                        media_type = response['type']
                        file_id = response['file_id']
                        text = response.get('text', '')
                        escaped_text = escape_pipe(text)
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
                        await update.message.reply_text(response, parse_mode='MarkdownV2')
                    return
    except Exception as e:
        logger.error(f"Filter error: {e}")

async def solexacleanservice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /solexacleanservice in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if chat_id not in cleanservice_state:
            cleanservice_state[chat_id] = {'enabled': False, 'delay': 15}
            logger.info(f"Initialized cleanservice_state for {chat_id}: {cleanservice_state[chat_id]}")
            save_cleanservice()
        if not context.args:
            await update.message.reply_text("Usage: /solexacleanservice on [seconds] | off | status")
            return
        action = context.args[0].lower()
        if action == 'on':
            delay = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 15
            if delay < 1 or delay > 3600:
                await update.message.reply_text("Delay must be between 1 and 3600 seconds")
                return
            cleanservice_state[chat_id] = {'enabled': True, 'delay': delay}
            await update.message.reply_text(f"Cleanservice ON, delay: {delay} seconds ✅")
        elif action == 'off':
            cleanservice_state[chat_id]['enabled'] = False
            await update.message.reply_text("Cleanservice OFF ✅")
        elif action == 'status':
            state = cleanservice_state[chat_id]
            status = "ON" if state['enabled'] else "OFF"
            await update.message.reply_text(f"Cleanservice: {status}, delay: {state['delay']} seconds")
        else:
            await update.message.reply_text("Usage: /solexacleanservice on [seconds] | off | status")
        save_cleanservice()
    except Exception as e:
        logger.error(f"Error in /solexacleanservice: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def setsolexawelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /setsolexawelcome in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if chat_id not in welcome_dict:
            welcome_dict[chat_id] = {'enabled': False, 'type': 'text', 'file_id': None, 'text': ''}
            logger.info(f"Initialized welcome_dict for {chat_id}: {welcome_dict[chat_id]}")
            save_welcome()
        if not context.args:
            await update.message.reply_text("Usage: /setsolexawelcome on | off | set [text]")
            return
        action = context.args[0].lower()
        if action == 'on':
            welcome_dict[chat_id]['enabled'] = True
            await update.message.reply_text("Welcome message ON ✅")
        elif action == 'off':
            welcome_dict[chat_id]['enabled'] = False
            await update.message.reply_text("Welcome message OFF ✅")
        elif action == 'set':
            if len(context.args) < 2 and not (update.message.photo or update.message.video or update.message.animation):
                await update.message.reply_text("Usage: /setsolexawelcome set [text] or send media with caption")
                return
            if update.message.photo or update.message.video or update.message.animation:
                caption = update.message.caption or ""
                args = caption.split(maxsplit=2)
                if len(args) < 2 or args[0].lower() != '/setsolexawelcome' or args[1].lower() != 'set':
                    await update.message.reply_text("Caption must start with '/setsolexawelcome set'")
                    return
                raw_text = args[2] if len(args) > 2 else ""
                entities = update.message.caption_entities or []
                command_length = len("/setsolexawelcome set") + 1
                adjusted_entities = [
                    MessageEntity(type=e.type, offset=e.offset - command_length, length=e.length, url=e.url)
                    for e in entities if e.offset >= command_length
                ]
                response_text = apply_entities_to_caption(raw_text, adjusted_entities)
                response_text = escape_markdown_v2(response_text)
                if update.message.photo:
                    welcome_dict[chat_id] = {'enabled': True, 'type': 'photo', 'file_id': update.message.photo[-1].file_id, 'text': response_text}
                    await update.message.reply_text(f"Photo welcome set ✅")
                elif update.message.video:
                    welcome_dict[chat_id] = {'enabled': True, 'type': 'video', 'file_id': update.message.video.file_id, 'text': response_text}
                    await update.message.reply_text(f"Video welcome set ✅")
                elif update.message.animation:
                    welcome_dict[chat_id] = {'enabled': True, 'type': 'animation', 'file_id': update.message.animation.file_id, 'text': response_text}
                    await update.message.reply_text(f"GIF welcome set ✅")
            else:
                text = " ".join(context.args[1:])
                welcome_dict[chat_id] = {'enabled': True, 'type': 'text', 'file_id': None, 'text': escape_markdown_v2(text)}
                await update.message.reply_text("Text welcome set ✅")
        save_welcome()
    except Exception as e:
        logger.error(f"Error in /setsolexawelcome: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def showsolexawelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    logger.info(f"Processing /showsolexawelcome in {chat_id}")
    try:
        if not await is_admin(user_id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if chat_id not in welcome_dict:
            welcome_dict[chat_id] = {'enabled': False, 'type': 'text', 'file_id': None, 'text': ''}
            logger.info(f"Initialized welcome_dict for {chat_id}: {welcome_dict[chat_id]}")
            save_welcome()
        if not welcome_dict[chat_id]['enabled']:
            await update.message.reply_text("No welcome message set or enabled")
            return
        welcome = welcome_dict[chat_id]
        text = welcome['text'].replace('{username}', update.message.from_user.username or "You") if welcome['text'] else ""
        text = escape_pipe(text)
        if welcome['type'] == 'text':
            await context.bot.send_message(user_id, text, parse_mode='MarkdownV2')
        elif welcome['type'] == 'photo':
            await context.bot.send_photo(user_id, welcome['file_id'], caption=text, parse_mode='MarkdownV2')
        elif welcome['type'] == 'video':
            await context.bot.send_video(user_id, welcome['file_id'], caption=text, parse_mode='MarkdownV2', supports_streaming=True)
        elif welcome['type'] == 'animation':
            await context.bot.send_animation(user_id, welcome['file_id'], caption=text, parse_mode='MarkdownV2')
        await update.message.reply_text("Welcome message preview sent to your DM ✅")
    except Exception as e:
        logger.error(f"Error in /showsolexawelcome: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def setcaptcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /setcaptcha in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if chat_id not in captcha_state:
            captcha_state[chat_id] = True
            logger.info(f"Initialized captcha_state for {chat_id}: {captcha_state[chat_id]}")
            save_captcha()
        if not context.args:
            await update.message.reply_text("Usage: /setcaptcha on | off | status")
            return
        action = context.args[0].lower()
        if action == 'on':
            captcha_state[chat_id] = True
            await update.message.reply_text("Captcha ON ✅")
        elif action == 'off':
            captcha_state[chat_id] = False
            await update.message.reply_text("Captcha OFF ✅")
        elif action == 'status':
            status = "ON" if captcha_state[chat_id] else "OFF"
            await update.message.reply_text(f"Captcha: {status}")
        save_captcha()
    except Exception as e:
        logger.error(f"Error in /setcaptcha: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def testfilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    logger.info(f"Processing /testfilter in {chat_id}")
    try:
        if not await is_admin(user_id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if not context.args:
            await update.message.reply_text("Usage: /testfilter keyword")
            return
        keyword = context.args[0].lower()
        if chat_id not in filters_dict or keyword not in filters_dict[chat_id]:
            await update.message.reply_text("Filter not found ❌")
            return
        response = filters_dict[chat_id][keyword]
        if isinstance(response, dict) and 'type' in response and 'file_id' in response:
            media_type = response['type']
            file_id = response['file_id']
            text = response.get('text', '')
            escaped_text = escape_pipe(text)
            if media_type == 'photo':
                await context.bot.send_photo(user_id, file_id, caption=escaped_text, parse_mode='MarkdownV2')
            elif media_type == 'video':
                await context.bot.send_video(user_id, file_id, caption=escaped_text, parse_mode='MarkdownV2', supports_streaming=True)
            elif media_type == 'audio':
                await context.bot.send_audio(user_id, file_id, caption=escaped_text, parse_mode='MarkdownV2')
            elif media_type == 'animation':
                await context.bot.send_animation(user_id, file_id, caption=escaped_text, parse_mode='MarkdownV2')
            elif media_type == 'voice':
                await context.bot.send_voice(user_id, file_id, caption=escaped_text, parse_mode='MarkdownV2')
        elif isinstance(response, str):
            await context.bot.send_message(user_id, response, parse_mode='MarkdownV2')
        await update.message.reply_text(f"Filter '{keyword}' preview sent to your DM ✅")
    except Exception as e:
        logger.error(f"Error in /testfilter: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def addsolexablacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /addsolexablacklist in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if chat_id not in blacklist_dict:
            blacklist_dict[chat_id] = {'terms': set(), 'users': {}}
            logger.info(f"Initialized blacklist_dict for {chat_id}: {blacklist_dict[chat_id]}")
            save_blacklist()
        if not context.args:
            await update.message.reply_text("Usage: /addsolexablacklist keyword")
            return
        keyword = context.args[0].lower()
        blacklist_dict[chat_id]['terms'].add(keyword)
        save_blacklist()
        await update.message.reply_text(f"Blacklist term '{keyword}' added ✅")
    except Exception as e:
        logger.error(f"Error in /addsolexablacklist: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def removesolexablacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /removesolexablacklist in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if chat_id not in blacklist_dict:
            blacklist_dict[chat_id] = {'terms': set(), 'users': {}}
            logger.info(f"Initialized blacklist_dict for {chat_id}: {blacklist_dict[chat_id]}")
            save_blacklist()
        if not context.args:
            await update.message.reply_text("Usage: /removesolexablacklist keyword")
            return
        keyword = context.args[0].lower()
        if keyword in blacklist_dict[chat_id]['terms']:
            blacklist_dict[chat_id]['terms'].remove(keyword)
            save_blacklist()
            await update.message.reply_text(f"Blacklist term '{keyword}' removed ✅")
        else:
            await update.message.reply_text("Term not found ❌")
    except Exception as e:
        logger.error(f"Error in /removesolexablacklist: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def viewsolexablacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /viewsolexablacklist in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if chat_id not in blacklist_dict:
            blacklist_dict[chat_id] = {'terms': set(), 'users': {}}
            logger.info(f"Initialized blacklist_dict for {chat_id}: {blacklist_dict[chat_id]}")
            save_blacklist()
        if not blacklist_dict[chat_id]['terms']:
            await update.message.reply_text("No blacklist terms set")
            return
        terms = ", ".join(sorted(blacklist_dict[chat_id]['terms']))
        await update.message.reply_text(f"Blacklist terms: {terms}")
    except Exception as e:
        logger.error(f"Error in /viewsolexablacklist: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def solexaunmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /solexaunmute in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        if not context.args and not update.message.reply_to_message:
            await update.message.reply_text("Usage: /solexaunmute @username or reply to a message")
            return
        target_user = context.args[0] if context.args else None
        if not target_user:
            user_id = await get_user_id_from_reply(update)
        else:
            user_id = await resolve_user(chat_id, target_user, context)
        if not user_id:
            await update.message.reply_text(f"Error: User not found. They need to send a message first or reply to their message.")
            return
        permissions = ChatPermissions(
            can_send_messages=True, can_send_photos=True, can_send_videos=True,
            can_send_other_messages=True, can_send_polls=True, can_add_web_page_previews=True
        )
        await context.bot.restrict_chat_member(chat_id, user_id, permissions)
        await update.message.reply_text(f"User unmuted ✅")
    except Exception as e:
        logger.error(f"Error in /solexaunmute: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /adminhelp in {chat_id}")
    try:
        if not await is_admin(update.message.from_user.id, chat_id, context):
            await update.message.reply_text("No permission ❌")
            return
        keyboard = [
            [InlineKeyboardButton("Commands", callback_data="adminhelp_commands")],
            [InlineKeyboardButton("Filters", callback_data="adminhelp_filters")],
            [InlineKeyboardButton("Settings", callback_data="adminhelp_settings")],
            [InlineKeyboardButton("Formatting", callback_data="adminhelp_formatting")]
        ]
        await update.message.reply_text("Admin Help Menu: Choose a section", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error in /adminhelp: {e}")
        await update.message.reply_text("An error occurred. Check logs.")

async def adminhelp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    logger.info(f"Processing adminhelp callback in {chat_id}")
    try:
        if not await is_admin(query.from_user.id, chat_id, context):
            await query.answer("No permission ❌", show_alert=True)
            return
        section = query.data.split("_")[1]
        if section == "commands":
            text = (
                "*Admin Commands:*\n"
                "- /ban @user - Ban a user (or reply)\n"
                "- /kick @user - Kick a user (or reply)\n"
                "- /mute10 @user - Mute for 10 mins (or reply)\n"
                "- /mute30 @user - Mute for 30 mins (or reply)\n"
                "- /mute1hr @user - Mute for 1 hour (or reply)\n"
                "- /unban @user - Unban a user (or reply)\n"
                "- /solexaunmute @user - Unmute a user (or reply)"
            )
        elif section == "filters":
            text = (
                "*Filters:*\n"
                "- /addsolexafilter keyword text - Add text filter\n"
                "- Send media with '/addsolexafilter keyword [text]' - Add media filter\n"
                "- /listsolexafilters - List filters\n"
                "- /removesolexafilter keyword - Remove filter\n"
                "- /testfilter keyword - Preview filter in DM"
            )
        elif section == "settings":
            text = (
                "*Settings:*\n"
                "- /solexacleanservice on [seconds] - Clean 'Verified' messages\n"
                "- /solexacleanservice off | status - Toggle or check\n"
                "- /setsolexawelcome on | off - Toggle welcome\n"
                "- /setsolexawelcome set [text] - Set text welcome\n"
                "- Media with '/setsolexawelcome set [text]' - Set media welcome\n"
                "- /showsolexawelcome - Preview welcome in DM\n"
                "- /setcaptcha on | off | status - Toggle captcha\n"
                "- /addsolexablacklist keyword - Add blacklist term\n"
                "- /removesolexablacklist keyword - Remove term\n"
                "- /viewsolexablacklist - List terms"
            )
        elif section == "formatting":
            text = (
                "*Formatting:*\n"
                "- *text* - Bold\n"
                "- _text_ - Italics\n"
                "- [text](url) - Hyperlink\n"
                "- Use \\| for | character"
            )
        keyboard = [[InlineKeyboardButton("Back", callback_data="adminhelp_back")]]
        await query.edit_message_text(text, parse_mode='MarkdownV2', reply_markup=InlineKeyboardMarkup(keyboard))
        await query.answer()
    except Exception as e:
        logger.error(f"Error in adminhelp callback: {e}")
        await query.answer("An error occurred. Check logs.", show_alert=True)

async def adminhelp_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    logger.info(f"Processing adminhelp back in {chat_id}")
    try:
        if not await is_admin(query.from_user.id, chat_id, context):
            await query.answer("No permission ❌", show_alert=True)
            return
        keyboard = [
            [InlineKeyboardButton("Commands", callback_data="adminhelp_commands")],
            [InlineKeyboardButton("Filters", callback_data="adminhelp_filters")],
            [InlineKeyboardButton("Settings", callback_data="adminhelp_settings")],
            [InlineKeyboardButton("Formatting", callback_data="adminhelp_formatting")]
        ]
        await query.edit_message_text("Admin Help Menu: Choose a section", reply_markup=InlineKeyboardMarkup(keyboard))
        await query.answer()
    except Exception as e:
        logger.error(f"Error in adminhelp back: {e}")
        await query.answer("An error occurred. Check logs.", show_alert=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Features:\n"
        "- Keywords: audio/video/profits/etc → media files\n"
        "- New members must solve captcha\n"
        "- Admin commands: /ban, /kick, /mute10/30/1hr, /addsolexafilter, /unban, etc\n"
        "- Use /addsolexafilter keyword [text] or send media with caption '/addsolexafilter keyword [text]'\n"
        "- Supports *bold*, _italics_, [hyperlinks](https://example.com), and links (use single * and _ for filters)\n"
        "- Filters trigger only on standalone keywords (e.g., 'x' or '/x')\n"
        "- Reply to messages to target users or use /command @username (user must have sent a message recently)\n"
        "- Contact admin for help"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
        try:
            target_user = context.args[0] if context.args else None
            user_id = await get_user_id_from_reply(update) if not target_user else await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User not found. They need to send a message first or reply to their message.")
                return
            await context.bot.ban_chat_member(update.message.chat_id, user_id)
            await update.message.reply_text(f"User {target_user or 'replied-to'} banned ✅")
        except IndexError:
            await update.message.reply_text("Usage: /ban @username or reply to a user")
    else:
        await update.message.reply_text("Group-only command or no permission ❌")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
        try:
            target_user = context.args[0] if context.args else None
            user_id = await get_user_id_from_reply(update) if not target_user else await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User not found. They need to send a message first or reply to their message.")
                return
            await context.bot.ban_chat_member(update.message.chat_id, user_id)
            await context.bot.unban_chat_member(update.message.chat_id, user_id, only_if_banned=True)
            await update.message.reply_text(f"User {target_user or 'replied-to'} kicked ✅")
        except IndexError:
            await update.message.reply_text("Usage: /kick @username or reply to a user")
    else:
        await update.message.reply_text("Group-only command or no permission ❌")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: timedelta):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
        try:
            target_user = context.args[0] if context.args else None
            user_id = await get_user_id_from_reply(update) if not target_user else await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User not found. They need to send a message first or reply to their message.")
                return
            permissions = ChatPermissions(can_send_messages=False)
            until = update.message.date + duration
            await context.bot.restrict_chat_member(update.message.chat_id, user_id, permissions, until_date=until)
            await update.message.reply_text(f"User {target_user or 'replied-to'} muted for {int(duration.total_seconds()/60)} minutes ✅")
        except IndexError:
            await update.message.reply_text(f"Usage: /mute{int(duration.total_seconds()/60)} @username or reply to a user")
    else:
        await update.message.reply_text("Group-only command or no permission ❌")

async def mute10(update: Update, context: ContextTypes.DEFAULT_TYPE): await mute_user(update, context, timedelta(minutes=10))
async def mute30(update: Update, context: ContextTypes.DEFAULT_TYPE): await mute_user(update, context, timedelta(minutes=30))
async def mute1hr(update: Update, context: ContextTypes.DEFAULT_TYPE): await mute_user(update, context, timedelta(hours=1))

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
        try:
            target_user = context.args[0] if context.args else None
            user_id = await get_user_id_from_reply(update) if not target_user else await resolve_user(update.message.chat_id, target_user, context)
            if not user_id:
                await update.message.reply_text(f"Error: User not found. They need to send a message first or reply to their message.")
                return
            await context.bot.unban_chat_member(update.message.chat_id, user_id)
            await update.message.reply_text(f"User {target_user or 'replied-to'} unbanned ✅")
        except IndexError:
            await update.message.reply_text("Usage: /unban @username or reply to a user")
    else:
        await update.message.reply_text("Group-only command or no permission ❌")

async def add_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
        chat_id = update.message.chat_id
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /addsolexafilter keyword text")
            return
        keyword = context.args[0].lower()
        response_text = " ".join(context.args[1:])
        response_text = escape_markdown_v2(response_text)
        if chat_id not in filters_dict: filters_dict[chat_id] = {}
        filters_dict[chat_id][keyword] = response_text
        save_filters()
        await update.message.reply_text(f"Text filter '{keyword}' added ✅")
    else:
        await update.message.reply_text("Group-only command or no permission ❌")

async def add_media_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
        chat_id = update.message.chat_id
        if not update.message.caption or not update.message.caption.startswith('/addsolexafilter'): return
        caption = update.message.caption
        args = caption.split(maxsplit=2)
        if len(args) < 2:
            await update.message.reply_text("Usage: Send media with caption '/addsolexafilter keyword [text]'")
            return
        keyword = args[1].lower()
        raw_text = args[2] if len(args) > 2 else ""
        entities = update.message.caption_entities or []
        command_length = len(f"/addsolexafilter {keyword}") + 1
        adjusted_entities = [
            MessageEntity(type=e.type, offset=e.offset - command_length, length=e.length, url=e.url)
            for e in entities if e.offset >= command_length
        ]
        response_text = apply_entities_to_caption(raw_text, adjusted_entities)
        response_text = escape_markdown_v2(response_text)
        if chat_id not in filters_dict: filters_dict[chat_id] = {}
        if update.message.photo:
            filters_dict[chat_id][keyword] = {'type': 'photo', 'file_id': update.message.photo[-1].file_id, 'text': response_text}
            await update.message.reply_text(f"Photo filter '{keyword}' added ✅")
        elif update.message.video:
            filters_dict[chat_id][keyword] = {'type': 'video', 'file_id': update.message.video.file_id, 'text': response_text}
            await update.message.reply_text(f"Video filter '{keyword}' added ✅")
        elif update.message.audio:
            filters_dict[chat_id][keyword] = {'type': 'audio', 'file_id': update.message.audio.file_id, 'text': response_text}
            await update.message.reply_text(f"Audio filter '{keyword}' added ✅")
        elif update.message.animation:
            filters_dict[chat_id][keyword] = {'type': 'animation', 'file_id': update.message.animation.file_id, 'text': response_text}
            await update.message.reply_text(f"GIF filter '{keyword}' added ✅")
        elif update.message.voice:
            filters_dict[chat_id][keyword] = {'type': 'voice', 'file_id': update.message.voice.file_id, 'text': response_text}
            await update.message.reply_text(f"Voice filter '{keyword}' added ✅")
        else:
            await update.message.reply_text("No supported media type detected")
            return
        save_filters()
    else:
        await update.message.reply_text("Group-only command or no permission ❌")

async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
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
        await update.message.reply_text("Group-only command or no permission ❌")

async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" and await is_admin(update.message.from_user.id, update.message.chat_id, context):
        chat_id = update.message.chat_id
        if not context.args:
            await update.message.reply_text("Usage: /removesolexafilter keyword")
            return
        keyword = context.args[0].lower()
        if chat_id in filters_dict and keyword in filters_dict[chat_id]:
            del filters_dict[chat_id][keyword]
            save_filters()
            await update.message.reply_text(f"Filter '{keyword}' removed ✅")
        else:
            await update.message.reply_text("Filter not found ❌")
    else:
        await update.message.reply_text("Group-only command or no permission ❌")

application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(CommandHandler("mute10", mute10))
application.add_handler(CommandHandler("mute30", mute30))
application.add_handler(CommandHandler("mute1hr", mute1hr))
application.add_handler(CommandHandler("unban", unban_user))
application.add_handler(CommandHandler("solexaunmute", solexaunmute))
application.add_handler(CommandHandler("addsolexafilter", add_text_filter))
application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.ANIMATION | filters.VOICE, add_media_filter))
application.add_handler(CommandHandler("listsolexafilters", list_filters))
application.add_handler(CommandHandler("removesolexafilter", remove_filter))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.COMMAND, handle_command_as_filter))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"^captcha_\d+_\d+$"))
application.add_handler(CommandHandler("solexacleanservice", solexacleanservice))
application.add_handler(CommandHandler("setsolexawelcome", setsolexawelcome))
application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION, setsolexawelcome))
application.add_handler(CommandHandler("showsolexawelcome", showsolexawelcome))
application.add_handler(CommandHandler("setcaptcha", setcaptcha))
application.add_handler(CommandHandler("testfilter", testfilter))
application.add_handler(CommandHandler("addsolexablacklist", addsolexablacklist))
application.add_handler(CommandHandler("removesolexablacklist", removesolexablacklist))
application.add_handler(CommandHandler("viewsolexablacklist", viewsolexablacklist))
application.add_handler(CommandHandler("adminhelp", adminhelp))
application.add_handler(CallbackQueryHandler(adminhelp_callback, pattern=r"^adminhelp_.*$"))
application.add_handler(CallbackQueryHandler(adminhelp_back, pattern=r"^adminhelp_back$"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_file_exists(FILTERS_FILE, {})
    ensure_file_exists(CLEANSERVICE_FILE, {})
    ensure_file_exists(WELCOME_FILE, {})
    ensure_file_exists(CAPTCHA_FILE, {})
    ensure_file_exists(BLACKLIST_FILE, {})
    load_filters()
    load_cleanservice()
    load_welcome()
    load_captcha()
    load_blacklist()
    logger.info(f"Starting application with webhook: {WEBHOOK_URL}")
    logger.info(f"Final state - filters: {filters_dict}, cleanservice: {cleanservice_state}, welcome: {welcome_dict}, captcha: {captcha_state}, blacklist: {blacklist_dict}")
    await application.initialize()
    await application.start()
    current_webhook = await application.bot.get_webhook_info()
    if current_webhook.url != WEBHOOK_URL:
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")
    else:
        logger.info(f"Webhook already set to {WEBHOOK_URL}")
    yield
    await application.stop()

app.router.lifespan = lifespan

@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    logger.info(f"Received update: {json.dumps(data, indent=2)}")
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)