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
    "pro fits": "PROFITS.jpg",
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"
}

# NEW - Persistent storage setup
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
                can_send_messages=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_other_messages=True,
                can_send_polls=True,
                can_add_web_page_previews=True
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

# NEW - Unified handler for all content types
async def handle_all_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat_id = message.chat_id
    text = message.text.lower() if message.text else ""
    caption = message.caption.lower() if message.caption else ""

    for input_text in [text, caption]:
        if chat_id in filters_dict:
            for keyword, actions in filters_dict.get(chat_id, {}).items():
                pattern = rf"(?:^|\s){re.escape(keyword)}(?:\s|$)"
                if re.search(pattern, input_text, re.IGNORECASE):
                    for action in actions:
                        try:
                            if action["type"] == "text":
                                await message.reply_text(action["content"])
                            else:
                                await send_media_action(message, action)
                        except Exception as e:
                            logger.error(f"Error sending action: {e}")
                            await message.reply_text(f"Error sending {action['type']}")
                    return

async def send_media_action(message: Message, action: dict):
    try:
        content = action["content"]
        if action["type"] == "video":
            await message.reply_video(video=content)
        elif action["type"] == "photo":
            await message.reply_photo(photo=content)
        elif action["type"] == "animation":
            await message.reply_animation(animation=content)
        elif action["type"] == "audio":
            await message.reply_audio(audio=content)
        elif action["type"] == "document":
            await message.reply_document(document=content)
    except Exception as e:
        logger.error(f"Media send error: {e}")
        raise

# MODIFIED add_filter function
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                # Extract keyword and text response
                keyword = context.args[0].lower() if context.args else None
                text_response = " ".join(context.args[1:]) if len(context.args) > 1 else None
                
                # Extract media
                media = None
                media_type = None
                message = update.message
                if message.video:
                    media = message.video.file_id
                    media_type = "video"
                elif message.photo:
                    media = message.photo[-1].file_id
                    media_type = "photo"
                elif message.animation:
                    media = message.animation.file_id
                    media_type = "animation"
                elif message.audio:
                    media = message.audio.file_id
                    media_type = "audio"
                elif message.document:
                    media = message.document.file_id
                    media_type = "document"
                
                # Validate input
                if not keyword or (not text_response and not media):
                    await update.message.reply_text("Usage: /addsolexafilter [keyword] [text] + optional media")
                    return
                
                # Build actions list
                actions = []
                if text_response:
                    actions.append({"type": "text", "content": text_response})
                if media:
                    actions.append({"type": media_type, "content": media})
                
                # Save to filters_dict
                chat_id = update.message.chat_id
                if chat_id not in filters_dict:
                    filters_dict[chat_id] = {}
                filters_dict[chat_id][keyword] = actions
                save_filters()
                
                await update.message.reply_text(f"Filter '{keyword}' added with {len(actions)} action(s) ✅")
                
            except Exception as e:
                logger.error(f"Error adding filter: {e}")
                await update.message.reply_text("An error occurred")
        else:
            await update.message.reply_text("No permission ❌")
    else:
        await update.message.reply_text("Group-only command ❌")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Features:\n"
        "- Keywords: audio/video/profits/etc → media files\n"
        "- New members must solve captcha\n"
        "- Admin commands: /ban, /kick, /mute10/30/1hr, /addsolexafilter, etc\n"
        "- Reply to messages to target users\n"
        "- Contact admin for help"
    )
    await update.message.reply_text(help_text)

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

async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            chat_id = update.message.chat_id
            filters_list = filters_dict.get(chat_id, {})
            if filters_list:
                response = "Filters:\n" + "\n".join([f"{k}: {v}" for k, v in filters_list.items()])
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
application.add_handler(MessageHandler(filters.ALL, handle_all_content))  # NEW handler
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