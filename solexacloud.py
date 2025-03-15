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

def escape_markdown_v2(text):
    """
    Simple function to escape special characters for Telegram MarkdownV2.
    Used for text that doesn't contain any formatting.
    """
    if not text:
        return ""
    
    # These characters need to be escaped in MarkdownV2
    escape_chars = '_*[]()~`>#+-=|{}.!'
    
    # First, escape the backslash itself
    result = text.replace('\\', '\\\\')
    
    # Then escape all other special characters
    for char in escape_chars:
        result = result.replace(char, f'\\{char}')
    
    return result

def process_markdown_v2(text):
    """
    Process text with Markdown formatting, escaping special characters
    while preserving intended bold, italic, and links.
    """
    if not text:
        return ""
    
    # These are all the characters that need escaping in MarkdownV2
    special_chars = '_*[]()~`>#+-=|{}.!'
    
    # First pass: Escape all backslashes
    processed = text.replace('\\', '\\\\')
    
    # Second pass: Handle formatting elements and escape other special characters
    i = 0
    result = ""
    in_bold = False
    in_italic = False
    in_link_text = False
    in_link_url = False
    
    while i < len(processed):
        char = processed[i]
        next_char = processed[i + 1] if i + 1 < len(processed) else None
        
        # Handle bold markers (asterisks)
        if char == '*' and not in_link_text and not in_link_url:
            result += '*'
            in_bold = not in_bold
            i += 1
            continue
        
        # Handle italic markers (underscores)
        elif char == '_' and not in_link_text and not in_link_url:
            result += '_'
            in_italic = not in_italic
            i += 1
            continue
        
        # Handle link start
        elif char == '[' and not in_bold and not in_italic and not in_link_text and not in_link_url:
            result += '['
            in_link_text = True
            i += 1
            continue
        
        # Handle link text end
        elif char == ']' and in_link_text:
            result += ']'
            in_link_text = False
            # Check if followed by link URL
            if next_char == '(':
                result += '('
                in_link_url = True
                i += 2  # Skip the opening parenthesis
                continue
            else:
                i += 1
                continue
        
        # Handle link URL end
        elif char == ')' and in_link_url:
            result += ')'
            in_link_url = False
            i += 1
            continue
        
        # Handle regular characters
        else:
            # Only escape special characters if we're not inside formatting
            is_in_formatting = in_bold or in_italic or in_link_text or in_link_url
            
            if char in special_chars and not is_in_formatting:
                result += '\\' + char
            else:
                result += char
            i += 1
    
    return result

async def send_formatted_message(context, chat_id, text, message_type="text", file_id=None):
    """
    Send a message with MarkdownV2 formatting, with fallback to plain text.
    """
    try:
        # Process the text for MarkdownV2
        formatted_text = process_markdown_v2(text)
        
        # Send with MarkdownV2
        if message_type == "text":
            return await context.bot.send_message(chat_id, formatted_text, parse_mode='MarkdownV2')
        elif message_type == "photo":
            return await context.bot.send_photo(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
        elif message_type == "video":
            return await context.bot.send_video(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
        elif message_type == "animation":
            return await context.bot.send_animation(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
        elif message_type == "audio":
            return await context.bot.send_audio(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
        elif message_type == "voice":
            return await context.bot.send_voice(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Failed to send with MarkdownV2: {e}")
        logger.info(f"Falling back to plain text: {text}")
        
        # Fallback to plain text
        if message_type == "text":
            return await context.bot.send_message(chat_id, text, parse_mode=None)
        elif message_type == "photo":
            return await context.bot.send_photo(chat_id, file_id, caption=text, parse_mode=None)
        elif message_type == "video":
            return await context.bot.send_video(chat_id, file_id, caption=text, parse_mode=None)
        elif message_type == "animation":
            return await context.bot.send_animation(chat_id, file_id, caption=text, parse_mode=None)
        elif message_type == "audio":
            return await context.bot.send_audio(chat_id, file_id, caption=text, parse_mode=None)
        elif message_type == "voice":
            return await context.bot.send_voice(chat_id, file_id, caption=text, parse_mode=None)

async def send_welcome_message(context, chat_id, welcome_config, username):
    """
    Specialized function just for sending welcome messages with username substitution.
    This approach completely separates username substitution from the markdown processing.
    """
    try:
        # Get the type and file_id from the welcome config
        message_type = welcome_config.get("type", "text")
        file_id = welcome_config.get("file_id")
        
        # Get the raw text and do the username substitution
        raw_text = welcome_config.get("text", "")
        text_with_username = raw_text.replace("{username}", username)
        
        # Log the transformation
        logger.info(f"Original welcome text: {raw_text}")
        logger.info(f"After username replacement: {text_with_username}")
        
        # Use a direct approach based on message type
        try:
            formatted_text = process_markdown_v2(text_with_username)
            logger.info(f"Formatted for MarkdownV2: {formatted_text}")
            
            # Send with MarkdownV2
            if message_type == "text":
                return await context.bot.send_message(chat_id, formatted_text, parse_mode='MarkdownV2')
            elif message_type == "photo":
                return await context.bot.send_photo(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
            elif message_type == "video":
                return await context.bot.send_video(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
            elif message_type == "animation":
                return await context.bot.send_animation(chat_id, file_id, caption=formatted_text, parse_mode='MarkdownV2')
            else:
                # Default fallback
                return await context.bot.send_message(chat_id, formatted_text, parse_mode='MarkdownV2')
                
        except Exception as e:
            logger.error(f"Error sending welcome with MarkdownV2: {e}")
            logger.info("Falling back to plain text...")
            
            # Fallback to plain text
            if message_type == "text":
                return await context.bot.send_message(chat_id, text_with_username)
            elif message_type == "photo":
                return await context.bot.send_photo(chat_id, file_id, caption=text_with_username)
            elif message_type == "video":
                return await context.bot.send_video(chat_id, file_id, caption=text_with_username)
            elif message_type == "animation":
                return await context.bot.send_animation(chat_id, file_id, caption=text_with_username)
            else:
                # Default fallback
                return await context.bot.send_message(chat_id, text_with_username)
                
    except Exception as e:
        logger.error(f"Failed to send welcome message: {e}")
        return None

def adjust_entities(original_text, new_text, entities):
    """Adjust entity offsets after replacing {username} with a new username."""
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
    """
    Updated welcome function to also clean system messages if enabled.
    """
    try:
        chat_id = update.message.chat_id
        
        # Check if system message cleaning is enabled
        clean_system = chat_id in cleansystem_enabled and cleansystem_enabled[chat_id]
        
        # If system message cleaning is enabled, delete the system message
        if clean_system:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
                logger.info(f"Deleted system message {update.message.message_id} in chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to delete system message {update.message.message_id}: {e}")
        
        # Continue with the existing welcome logic
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
                    # Use our specialized welcome message function
                    msg = await send_welcome_message(context, chat_id, welcome_state[chat_id], username)
                    
                    # Store the message ID for later deletion if needed
                    if msg:
                        welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                        save_welcome_state()
                        logger.info(f"Welcome message sent successfully, message_id: {msg.message_id}")
    except Exception as e:
        logger.error(f"Error handling new member: {e}")

async def handle_system_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Simple handler for system messages (focusing on leave messages first).
    """
    try:
        # Skip if no message or if in a private chat
        if not update.message or update.message.chat.type == "private":
            return
            
        # Skip if this is a regular text message (not a system message)
        if update.message.text:
            return
            
        chat_id = update.message.chat_id
        
        # Check if system message cleaning is enabled
        if chat_id not in cleansystem_enabled or not cleansystem_enabled[chat_id]:
            return
        
        # Check if this is a "user left" message
        if hasattr(update.message, "left_chat_member") and update.message.left_chat_member:
            # Try to delete it
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
                logger.info(f"Deleted 'user left' message in chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to delete message: {e}")
                
    except Exception as e:
        logger.error(f"Error in handle_system_messages: {e}")
async def verify_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Updated captcha verification using the specialized welcome message sender.
    """
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
                # Clear old welcome messages first
                if "message_ids" in welcome_state[chat_id]:
                    for msg_id in welcome_state[chat_id]["message_ids"][:]:
                        try:
                            await context.bot.delete_message(chat_id, msg_id)
                            welcome_state[chat_id]["message_ids"].remove(msg_id)
                            logger.info(f"Successfully deleted old welcome message {msg_id}")
                        except Exception as e:
                            logger.error(f"Failed to delete welcome message {msg_id}: {e}")
                
                # Use our specialized welcome message function
                msg = await send_welcome_message(context, chat_id, welcome_state[chat_id], username)
                
                # Store the message ID for later deletion if needed
                if msg:
                    welcome_state[chat_id].setdefault("message_ids", []).append(msg.message_id)
                    save_welcome_state()
                    logger.info(f"Welcome message sent successfully, message_id: {msg.message_id}")
            else:
                msg = await context.bot.send_message(chat_id, "✅ Verified!")
                context.job_queue.run_once(lambda x: delete_message(x, chat_id, msg.message_id), 10)
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
    """
    Fixed message handler with proper markdown handling.
    """
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
                        
                        # Send the message with proper formatting
                        await send_formatted_message(
                            context, 
                            chat_id,
                            text,
                            message_type=media_type,
                            file_id=file_id
                        )
                    elif isinstance(response, str):
                        # Send the text response with proper formatting
                        await send_formatted_message(
                            context, 
                            chat_id,
                            response
                        )
                    return
                    
        # Handle keyword responses from the dictionary
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
    """
    Fixed command handler for filters with proper markdown handling.
    """
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
                        
                        # Send the message with proper formatting
                        await send_formatted_message(
                            context, 
                            chat_id,
                            text,
                            message_type=media_type,
                            file_id=file_id
                        )
                    elif isinstance(response, str):
                        # Send the text response with proper formatting
                        await send_formatted_message(
                            context, 
                            chat_id,
                            response
                        )
                    return
    except Exception as e:
        logger.error(f"Filter error: {e}")

async def cleansystem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command to toggle automatic deletion of system messages.
    Usage: /cleansystem ON|OFF|STATUS
    """
    if update.message.chat.type == "private":
        await update.message.reply_text("Group-only command ❌")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("No permission ❌")
        return
    
    chat_id = update.message.chat_id
    if not context.args:
        await update.message.reply_text("Usage: /cleansystem ON|OFF|STATUS")
        return
    
    action = context.args[0].upper()
    if action == "ON":
        cleansystem_enabled[chat_id] = True
        save_cleansystem_state()
        await update.message.reply_text("System message cleaning enabled ✅")
    elif action == "OFF":
        cleansystem_enabled[chat_id] = False
        save_cleansystem_state()
        await update.message.reply_text("System message cleaning disabled ✅")
    elif action == "STATUS":
        state = cleansystem_enabled.get(chat_id, False)
        status_text = "enabled" if state else "disabled"
        await update.message.reply_text(f"System message cleaning is currently {status_text}")
    else:
        await update.message.reply_text("Usage: /cleansystem ON|OFF|STATUS")

async def solexahelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Updated help command with proper markdown formatting.
    """
    # Restrict to admins only
    if update.message.chat.type == "private":
        await update.message.reply_text("Group-only command ❌")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("No permission ❌")
        return

    help_text = (
        "*🚀 SOLEXA Bot Help Menu 🚀*\n"
        "Here's a detailed guide to all commands and features available in the bot. "
        "Use these to manage your group effectively!\n\n"

        "*⚙️ Admin Commands*\n"
        "These commands are for group admins only.\n"
        "• `/ban @username` or reply: Bans a user from the group.\n"
        "• `/kick @username` or reply: Kicks a user (removes and allows rejoin).\n"
        "• `/mute10 @username` or reply: Mutes a user for 10 minutes.\n"
        "• `/mute30 @username` or reply: Mutes a user for 30 minutes.\n"
        "• `/mute1hr @username` or reply: Mutes a user for 1 hour.\n"
        "• `/unban @username` or reply: Unbans a user.\n"
        "• `/cleansystem ON|OFF|STATUS`: Toggles automatic deletion of system messages (join/leave/etc).\n\n"

        "*📝 Filters*\n"
        "Add custom responses triggered by keywords.\n"
        "• `/addsolexafilter keyword text`: Adds a text filter (admin-only).\n"
        "  Example: `/addsolexafilter hello Hi there!`\n"
        "• `/addsolexafilter keyword [text]`: Adds a media filter (admin-only, send with media).\n"
        "  Example: Send a photo with caption `/addsolexafilter meme LOL` (text optional).\n"
        "• `/listsolexafilters`: Lists all filters in the group (admin-only).\n"
        "• `/removesolexafilter keyword`: Removes a filter (admin-only).\n"
        "• *Trigger Filters*: Send `keyword` or `/keyword` to trigger the response.\n\n"

        "*🔒 Captcha*\n"
        "Protect your group from bots with a captcha for new members.\n"
        "• `/solexacaptcha ON|OFF|status`: Toggles or checks captcha status (admin-only, default: ON).\n"
        "  Example: `/solexacaptcha OFF` to disable.\n\n"

        "*👋 Welcome Messages*\n"
        "Set custom welcome messages for new members after captcha verification.\n"
        "• `/setsolexawelcome <message>`: Sets a text welcome message (admin-only).\n"
        "  Use `{username}` to include the user's name.\n"
        "  Example: `/setsolexawelcome Welcome {username}!`.\n"
        "• `/setsolexawelcome ON|OFF|status|preview`: Manages welcome message settings (admin-only).\n"
        "  Example: `/setsolexawelcome preview` to preview the message.\n"
        "• `/setsolexawelcome` with media: Sets a media welcome message (admin-only, send with media).\n"
        "  Example: Send a photo with caption `/setsolexawelcome Welcome {username}!`.\n\n"

        "*🧹 System Message Cleaning*\n"
        "Automatically delete system messages about users joining, leaving, etc.\n"
        "• `/cleansystem ON|OFF|STATUS`: Toggles or checks system message cleaning status (admin-only, default: OFF).\n"
        "  Example: `/cleansystem ON` to enable automatic cleaning.\n\n"

        "*🎉 General Features*\n"
        "• *Keyword Responses*: Predefined keywords like `profits`, `slut`, `launch cat` trigger media files.\n"
        "• *Formatting Support*: Use `*bold*`, `_italics_`, `[links](https://example.com)` in messages.\n\n"

        "*📧 Need Help?*\n"
        "Contact the bot admin for assistance. Enjoy using SOLEXA Bot! 🎉"
    )
    
    # Send the help message with proper formatting
    await send_formatted_message(context, update.effective_chat.id, help_text)

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
            
            # Use specialized welcome message function for preview
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
    else:
        text = args[1]
        entities = parse_markdown_entities(text)
        welcome_state[chat_id].update({"enabled": True, "type": "text", "file_id": None, "text": text, "entities": entities, "message_ids": []})
        save_welcome_state()
        await update.message.reply_text("Welcome text set ✅")

async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fixed media message handler for setting filters and welcome messages.
    """
    logger.info(f"Entered handle_media_message for update: {update.message}")
    if not update.message.caption:
        logger.info("Message skipped: No caption")
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
    if caption.startswith('/addsolexafilter'):
        # Logic from add_media_filter
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

    elif caption.startswith('/setsolexawelcome'):
        # Logic from setsolexawelcome_media
        args = caption.split(maxsplit=1)
        raw_caption = args[1] if len(args) > 1 else ""
        if chat_id not in welcome_state:
            welcome_state[chat_id] = {"enabled": False, "type": None, "file_id": None, "text": "", "entities": [], "message_ids": []}

        try:
            # Don't try to parse entities, just store the raw text
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
        except Exception as e:
            logger.error(f"Error setting media welcome message: {e}")
            await update.message.reply_text("Error setting welcome message ❌")
    else:
        logger.info("Message skipped: Caption does not start with /addsolexafilter or /setsolexawelcome")
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

# Add a diagnostic command for welcome messages
async def solexafixwelcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command to diagnose and fix formatting issues in welcome messages.
    Admin-only command that will clean up existing welcome messages.
    """
    if update.message.chat.type == "private":
        await update.message.reply_text("Group-only command ❌")
        return
    if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
        await update.message.reply_text("No permission ❌")
        return
        
    chat_id = update.message.chat_id
    if chat_id not in welcome_state or not welcome_state[chat_id]["enabled"]:
        await update.message.reply_text("No welcome message is currently set.")
        return
        
    # Get the current welcome message info
    ws = welcome_state[chat_id]
    
    # Show diagnostic info about the current welcome message
    await update.message.reply_text(
        f"Welcome message diagnostic info:\n"
        f"- Type: {ws['type']}\n"
        f"- Raw text: {ws['text']}\n"
        f"- Has entities: {'Yes' if ws.get('entities') else 'No'}\n"
        f"- Num entities: {len(ws.get('entities', []))}"
    )
    
    # Try to fix the welcome message
    original_text = ws["text"]
    username = update.message.from_user.username or update.message.from_user.first_name
    
    # Show preview of how it would look with this username
    sample_text = original_text.replace("{username}", username)
    await update.message.reply_text(f"Raw sample with your username:\n{sample_text}")
    
    # Show how the processed markdown would look
    processed_text = process_markdown_v2(sample_text)
    await update.message.reply_text(f"Processed markdown: \n{processed_text}")

def parse_markdown_entities(text):
    """
    Function to maintain compatibility with existing code.
    """
    # This is a placeholder to maintain compatibility
    # In the original code, this function might have been defined but not included in the snippet
    return []

# Handler registrations
application.add_handler(CommandHandler("solexahelp", solexahelp_command))
application.add_handler(CommandHandler("solexacaptcha", solexacaptcha_command))
application.add_handler(CommandHandler("setsolexawelcome", setsolexawelcome_command))
application.add_handler(CommandHandler("cleansystem", cleansystem_command))
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(CommandHandler("mute10", mute10))
application.add_handler(CommandHandler("mute30", mute30))
application.add_handler(CommandHandler("mute1hr", mute1hr))
application.add_handler(CommandHandler("unban", unban_user))
application.add_handler(CommandHandler("addsolexafilter", add_text_filter))
application.add_handler(CommandHandler("solexafixwelcome", solexafixwelcome_command))  # Add the diagnostic command

# Basic handler for all messages to catch system messages
application.add_handler(MessageHandler(filters.ALL, handle_system_messages))

# Combined handler for media messages
application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.ANIMATION | filters.VOICE, handle_media_message))
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
    load_cleansystem_state()  # Added this line to load system message cleaning state
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)