import os
import logging
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
    "audio": "test.mp3",
    "secret": "secret.mp3",
    "video": "test.mp4",
    "profits": "PROFITS.jpg",
    "commercial": "commercial.mp4",
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"
}

filters_dict = {}

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
            # Preserve the @ symbol for API compatibility
            user = await context.bot.get_chat_member(chat_id, target_user)
            return user.user.id
        else:
            return int(target_user)
    except Exception as e:
        logger.error(f"Error resolving user {target_user}: {e}")
        return None

async def get_user_id_from_reply(update: Update) -> int or None:
    """Get user ID from the message being replied to"""
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user.id
    return None

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for member in update.message.new_chat_members:
            chat_id = update.message.chat_id
            user_id = member.id
            username = member.first_name

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
            try:
                permissions.can_read_all_group_messages = True
            except AttributeError:
                logger.warning("Attribute error")

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
        if not update.message.text:
            return  # Skip non-text messages
        
        message_text = update.message.text.lower()
        chat_id = update.message.chat_id

        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if re.search(rf"(?:^|\s){re.escape('/' + keyword)}(?:\s|$)|\b{re.escape(keyword)}\b", message_text):
                    await update.message.reply_text(response)
                    return

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

async def handle_command_as_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.text:
            return  # Skip non-text messages
        
        message_text = update.message.text.lower()
        chat_id = update.message.chat_id

        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                if re.match(rf"^{re.escape('/' + keyword)}$", message_text):
                    await update.message.reply_text(response)
                    return
    except Exception as e:
        logger.error(f"Filter error: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Features:\n"
        "- Keywords: audio/video/profits/etc → media files\n"
        "- New members must solve captcha\n"
        "- Admin commands: /ban, /kick, /mute10/30/1hr, /addsolexafilter, etc\n"
        "- Reply to a message to target users for commands\n"
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

                # Proper kick: ban then unban
                await context.bot.ban_chat_member(update.message.chat_id, user_id)
                await context.bot.unban_chat_member(update.message.chat_id, user_id)
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

async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                keyword = context.args[0].lower()
                response = " ".join(context.args[1:])
                chat_id = update.message.chat_id

                if chat_id not in filters_dict:
                    filters_dict[chat_id] = {}

                filters_dict[chat_id][keyword] = response
                await update.message.reply_text(f"Filter '{keyword}' added ✅")
            except IndexError:
                await update.message.reply_text("Usage: /addsolexafilter keyword response")
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
                await update.message.reply_text(f"Filters:\n{chr(10).join([f'{k}: {v}' for k, v in filters_list.items()])}")
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
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.COMMAND, handle_command_as_filter))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"captcha_\d+_\d+"))

# FASTAPI WEBHOOK
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.on_event("startup")
async def startup():
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)