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
                filters_dict = {}
                for chat_id, filters in data.items():
                    chat_id = int(chat_id)
                    filters_dict[chat_id] = {}
                    for k, v in filters.items():
                        if isinstance(v, str):
                            filters_dict[chat_id][k] = v
                        elif isinstance(v, dict) and 'type' in v and 'file_id' in v:
                            filters_dict[chat_id][k] = v
                        else:
                            logger.warning(f"Invalid filter format for {k} in chat {chat_id}, skipping")
        else:
            filters_dict = {}
        logger.info(f"Filters loaded: {repr(filters_dict)}")
    except Exception as e:
        logger.error(f"Error loading filters: {e}")
        filters_dict = {}

def save_filters():
    try:
        with open(FILTERS_FILE, 'w') as f:
            serializable = {str(chat_id): filters 
                           for chat_id, filters in filters_dict.items()}
            json.dump(serializable, f)
        logger.info(f"Filters saved: {repr(filters_dict)}")
    except Exception as e:
        logger.error(f"Error saving filters: {e}")

def escape_markdown_v2(text):
    """Escape all reserved MarkdownV2 characters, ensuring ! is always escaped."""
    reserved_chars = r"[-()~`>#+|=|{}.!]"
    # Preserve existing Markdown patterns
    patterns = [
        r'(\[.*?\]\(.*?\))',    # Hyperlinks: [text](url)
        r'(\*\*[^\*]*\*\*)',    # Bold: **text**
        r'(__[^_]*__)',         # Italics: __text__
    ]
    combined_pattern = '|'.join(patterns) + f'|({reserved_chars})'
    
    def replace_func(match):
        for i in range(1, 4):
            if match.group(i):
                return match.group(i)
        char = match.group(4)
        return '\\' + char  # Force escape of !
    
    escaped_text = re.sub(combined_pattern, replace_func, text)
    logger.info(f"Escaped text: {repr(escaped_text)}")
    return escaped_text

def apply_entities_to_caption(caption, entities):
    """Reconstruct MarkdownV2 text with precise entity wrapping."""
    if not entities or not caption:
        return caption
    
    result = list(caption)
    offset_shift = 0
    
    for entity in sorted(entities, key=lambda e: e.offset):
        start = entity.offset + offset_shift
        end = start + entity.length
        
        if start >= len(result) or end > len(result):
            logger.warning(f"Entity out of bounds: {entity}, caption length: {len(result)}")
            continue
            
        entity_text = ''.join(result[start:end])
        if entity.type == "bold":
            new_text = f"**{entity_text}**"
        elif entity.type == "italic":
            new_text = f"__{entity_text}__"
        elif entity.type == "url" and entity.url:
            new_text = f"[{entity_text}]({entity.url})"
        else:
            new_text = entity_text
            
        # Replace the entity text with formatted version
        del result[start:end]
        result[start:start] = list(new_text)
        offset_shift += len(new_text) - entity.length
        
    final_text = ''.join(result)
    logger.info(f"Text after applying entities: {repr(final_text)}")
    return final_text

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
            logger.info(f"Resolving username: @{username} in chat {chat_id}")
            try:
                async for member in context.bot.get_chat_members(chat_id):
                    member_username = member.user.username
                    if member_username and member_username.lower() == username:
                        logger.info(f"Found user @{username} with ID {member.user.id}")
                        return member.user.id
                logger.warning(f"User @{username} not found in member list")
                return None
            except Forbidden:
                logger.error("Bot lacks permission to view member list")
                return None
            except Exception as e:
                logger.error(f"Error searching members: {e}")
                return None
        else:
            user_id = int(target_user)
            logger.info(f"Using provided user ID: {user_id}")
            return user_id
    except ValueError:
        logger.error(f"Invalid user format: {target_user}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error resolving user: {e}")
        return None

async def get_user_id_from_reply(update: Update) -> int or None:
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user.id
    return None

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for member in update.message.new_chat_members:
            chat_id = update.message.chat_id
            user_id = member.id
            username = member.username or member.first_name
            logger.info(f"New member detected: {username} (ID: {user_id}) in {update.message.chat.title}")
            permissions = ChatPermissions(can_send_messages=False)
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            question, options, correct_answer = generate_captcha()
            captcha_attempts[user_id] = {"answer": correct_answer, "attempts": 0, "chat_id": chat_id}
            keyboard = [[InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")] for opt in options]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=chat_id, text=f"Welcome {username}! Please verify yourself.\n\n{question}", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

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
        attempts = captcha_attempts[target_user_id]["attempts"]
        if answer == correct_answer:
            permissions = ChatPermissions(
                can_send_messages=True, can_send_photos=True, can_send_videos=True,
                can_send_other_messages=True, can_send_polls=True, can_add_web_page_previews=True
            )
            await context.bot.restrict_chat_member(chat_id, target_user_id, permissions)
            await query.message.edit_text("✅ Verified!")
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
        message_text = update.message.text.strip().lower()
        chat_id = update.message.chat_id
        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if message_text == keyword or message_text == f"/{keyword}":
                    if isinstance(response, dict) and 'type' in response and 'file_id' in response:
                        media_type = response['type']
                        file_id = response['file_id']
                        text = response.get('text', '')
                        logger.info(f"Triggering media filter: {keyword} with {media_type}, raw caption: {repr(text)}")
                        if media_type == 'photo':
                            try:
                                await update.message.reply_photo(photo=file_id, caption=text, parse_mode='MarkdownV2')
                            except BadRequest as e:
                                logger.error(f"Failed to send photo with caption: {e}")
                                await update.message.reply_text(f"Error: {str(e)}")
                        elif media_type == 'video':
                            await update.message.reply_video(video=file_id, caption=text, parse_mode='MarkdownV2', supports_streaming=True)
                        elif media_type == 'audio':
                            await update.message.reply_audio(audio=file_id, caption=text, parse_mode='MarkdownV2')
                        elif media_type == 'animation':
                            await update.message.reply_animation(animation=file_id, caption=text, parse_mode='MarkdownV2')
                    elif isinstance(response, str):
                        logger.info(f"Triggering text filter: {keyword}, raw text: {repr(response)}")
                        await update.message.reply_text(response, parse_mode='MarkdownV2')
                    else:
                        logger.warning(f"Invalid response format for {keyword}")
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
                        logger.info(f"Command filter: {keyword} with {media_type}, raw caption: {repr(text)}")
                        if media_type == 'photo':
                            await update.message.reply_photo(photo=file_id, caption=text, parse_mode='MarkdownV2')
                        elif media_type == 'video':
                            await update.message.reply_video(video=file_id, caption=text, parse_mode='MarkdownV2', supports_streaming=True)
                        elif media_type == 'audio':
                            await update.message.reply_audio(audio=file_id, caption=text, parse_mode='MarkdownV2')
                        elif media_type == 'animation':
                            await update.message.reply_animation(animation=file_id, caption=text, parse_mode='MarkdownV2')
                    elif isinstance(response, str):
                        logger.info(f"Command text filter: {keyword}, raw text: {repr(response)}")
                        await update.message.reply_text(response, parse_mode='MarkdownV2')
                    else:
                        logger.warning(f"Invalid command response format for {keyword}")
                    return
    except Exception as e:
        logger.error(f"Filter error: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Features:\n"
        "- Keywords: audio/video/profits/etc → media files\n"
        "- New members must solve captcha\n"
        "- Admin commands: /ban, /kick, /mute10/30/1hr, /addsolexafilter, etc\n"
        "- Use /addsolexafilter keyword [text] or send media with caption '/addsolexafilter keyword [text]'\n"
        "- Supports **bold**, __italics__, [hyperlinks](https://example.com), and links\n"
        "- Filters trigger only on standalone keywords (e.g., 'x' or '/x')\n"
        "- Reply to messages to target users\n"
        "- Contact admin for help"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                target_user = context.args[0] if context.args else None
                if not target_user:
                    user_id = await get_user_id_from_reply(update)
                    if not user_id:
                        await update.message.reply_text("Error: Specify a username or reply to a message")
                        return
                else:
                    user_id = await resolve_user(update.message.chat_id, target_user, context)
                if not user_id:
                    await update.message.reply_text(f"Error: User {target_user} not found")
                    return
                await context.bot.ban_chat_member(update.message.chat_id, user_id)
                await update.message.reply_text(f"User {target_user} banned ✅")
            except IndexError:
                await update.message.reply_text("Usage: /ban @username or reply to a user")
        else:
            await update.message.reply_text("No permission ❌")
    else:
        await update.message.reply_text("Group-only command ❌")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                target_user = context.args[0] if context.args else None
                if not target_user:
                    user_id = await get_user_id_from_reply(update)
                    if not user_id:
                        await update.message.reply_text("Error: Specify a username or reply to a message")
                        return
                else:
                    user_id = await resolve_user(update.message.chat_id, target_user, context)
                if not user_id:
                    await update.message.reply_text(f"Error: User {target_user} not found")
                    return
                await context.bot.ban_chat_member(update.message.chat_id, user_id)
                await context.bot.unban_chat_member(update.message.chat_id, user_id, only_if_banned=True)
                await update.message.reply_text("User kicked ✅")
            except IndexError:
                await update.message.reply_text("Usage: /kick @username or reply to a user")
        else:
            await update.message.reply_text("No permission ❌")
    else:
        await update.message.reply_text("Group-only command ❌")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: timedelta):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                target_user = context.args[0] if context.args else None
                if not target_user:
                    user_id = await get_user_id_from_reply(update)
                    if not user_id:
                        await update.message.reply_text("Error: Specify a username or reply to a message")
                        return
                else:
                    user_id = await resolve_user(update.message.chat_id, target_user, context)
                if not user_id:
                    await update.message.reply_text(f"Error: User {target_user} not found")
                    return
                permissions = ChatPermissions(can_send_messages=False)
                until = update.message.date + duration
                await context.bot.restrict_chat_member(update.message.chat_id, user_id, permissions, until_date=until)
                await update.message.reply_text(f"Muted for {int(duration.total_seconds()/60)} minutes ✅")
            except IndexError:
                await update.message.reply_text(f"Usage: /mute10 @username or reply to a user")
        else:
            await update.message.reply_text("No permission ❌")
    else:
        await update.message.reply_text("Group-only command ❌")

async def mute10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(minutes=10))

async def mute30(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(minutes=30))

async def mute1hr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mute_user(update, context, timedelta(hours=1))

async def add_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            await update.message.reply_text("No permission ❌")
            return
        chat_id = update.message.chat_id
        logger.info(f"Processing /addsolexafilter (text) in chat {chat_id}")
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /addsolexafilter keyword text")
            logger.warning("Insufficient arguments for text filter")
            return
        keyword = context.args[0].lower()
        response_text = " ".join(context.args[1:])
        response_text = escape_markdown_v2(response_text)
        if chat_id not in filters_dict:
            filters_dict[chat_id] = {}
        filters_dict[chat_id][keyword] = response_text
        save_filters()
        await update.message.reply_text(f"Text filter '{keyword}' added ✅")
        logger.info(f"Added text filter '{keyword}' with text: {repr(response_text)}")
    else:
        await update.message.reply_text("Group-only command ❌")

async def add_media_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        chat_id = update.message.chat_id
        logger.info(f"Processing media message in chat {chat_id}")
        if not update.message.caption or not update.message.caption.startswith('/addsolexafilter'):
            return
        if update.message.from_user.id not in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            await update.message.reply_text("No permission ❌")
            return
        caption = update.message.caption
        args = caption.split(maxsplit=2)
        if len(args) < 2:
            await update.message.reply_text("Usage: Send media with caption '/addsolexafilter keyword [text]'")
            logger.warning("Insufficient arguments in media caption")
            return
        keyword = args[1].lower()
        raw_text = args[2] if len(args) > 2 else ""
        entities = update.message.caption_entities or []
        # Adjust entity offsets correctly
        command_prefix = f"/addsolexafilter {keyword}"
        command_length = len(command_prefix) + 1  # +1 for the space after keyword
        adjusted_entities = []
        for e in entities:
            if e.offset < command_length:
                continue
            new_offset = e.offset - command_length
            if new_offset + e.length > len(raw_text):
                logger.warning(f"Adjusting entity due to length exceeding raw text: {e}, raw_text length: {len(raw_text)}")
                new_length = len(raw_text) - new_offset
                if new_length <= 0:
                    continue
                adjusted_entity = MessageEntity(
                    type=e.type,
                    offset=new_offset,
                    length=new_length,
                    url=e.url
                )
            else:
                adjusted_entity = MessageEntity(
                    type=e.type,
                    offset=new_offset,
                    length=e.length,
                    url=e.url
                )
            adjusted_entities.append(adjusted_entity)
        logger.info(f"Adjusted entities: {adjusted_entities}")
        response_text = apply_entities_to_caption(raw_text, adjusted_entities)
        response_text = escape_markdown_v2(response_text)  # Re-escape after applying entities
        if chat_id not in filters_dict:
            filters_dict[chat_id] = {}
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            filters_dict[chat_id][keyword] = {'type': 'photo', 'file_id': file_id, 'text': response_text}
            try:
                await update.message.reply_text(f"Photo filter '{keyword}' added ✅")
                logger.info(f"Added photo filter '{keyword}' with file_id {file_id} and text: {repr(response_text)}")
            except BadRequest as e:
                logger.error(f"Failed to send confirmation message: {e}")
                await update.message.reply_text(f"Filter set, but failed to send confirmation: {str(e)}")
        elif update.message.video:
            file_id = update.message.video.file_id
            filters_dict[chat_id][keyword] = {'type': 'video', 'file_id': file_id, 'text': response_text}
            await update.message.reply_text(f"Video filter '{keyword}' added ✅")
            logger.info(f"Added video filter '{keyword}' with file_id {file_id} and text: {repr(response_text)}")
        elif update.message.audio:
            file_id = update.message.audio.file_id
            filters_dict[chat_id][keyword] = {'type': 'audio', 'file_id': file_id, 'text': response_text}
            await update.message.reply_text(f"Audio filter '{keyword}' added ✅")
            logger.info(f"Added audio filter '{keyword}' with file_id {file_id} and text: {repr(response_text)}")
        elif update.message.animation:
            file_id = update.message.animation.file_id
            filters_dict[chat_id][keyword] = {'type': 'animation', 'file_id': file_id, 'text': response_text}
            await update.message.reply_text(f"GIF filter '{keyword}' added ✅")
            logger.info(f"Added GIF filter '{keyword}' with file_id {file_id} and text: {repr(response_text)}")
        else:
            await update.message.reply_text("No supported media type detected")
            logger.warning("No supported media type in message")
            return
        save_filters()
    else:
        await update.message.reply_text("Group-only command ❌")

async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
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

application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(CommandHandler("mute10", mute10))
application.add_handler(CommandHandler("mute30", mute30))
application.add_handler(CommandHandler("mute1hr", mute1hr))
application.add_handler(CommandHandler("addsolexafilter", add_text_filter))
application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.ANIMATION, add_media_filter))
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
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)