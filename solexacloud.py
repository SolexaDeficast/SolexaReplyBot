import os
import logging
import random
import re  # Import regex for exact word matching
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, User
)
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler, CommandHandler
)

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"

# Dictionary to track users' captcha attempts
captcha_attempts = {}

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

# Define the keywords and corresponding media files
keyword_responses = {
    "audio": "test.mp3",
    "secret": "secret.mp3",
    "video": "test.mp4",
    "profits": "PROFITS.jpg",
    "commercial": "commercial.mp4",
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"
}

# Dictionary to store chat-specific filters
filters_dict = {}

# Function to generate a math captcha
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

# Function to handle new members
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

# Function to verify captcha response
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
            await query.answer("❌ You are not authorized to answer this captcha.", show_alert=True)
            return

        if target_user_id not in captcha_attempts:
            await query.answer("This verification has expired.")
            return

        correct_answer = captcha_attempts[target_user_id]["answer"]
        chat_id = captcha_attempts[target_user_id]["chat_id"]
        attempts = captcha_attempts[target_user_id]["attempts"]

        if answer == correct_answer:
            # Fully restore permissions
            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_other_messages=True,
                can_send_polls=True,
                can_add_web_page_previews=True
            )
            try:
                # Attempt to enable full chat history access
                permissions.can_read_all_group_messages = True
            except AttributeError:
                logger.warning("The 'can_read_all_group_messages' attribute is not supported in this version.")

            await context.bot.restrict_chat_member(chat_id, target_user_id, permissions)
            await query.message.edit_text("✅ Verification successful! You may now participate in the chat.")
            del captcha_attempts[target_user_id]
        else:
            attempts += 1
            captcha_attempts[target_user_id]["attempts"] = attempts

            if attempts >= 3:
                await context.bot.ban_chat_member(chat_id, target_user_id)
                await context.bot.unban_chat_member(chat_id, target_user_id)
                await query.message.edit_text("❌ You failed verification 3 times and have been removed from the group.")
                del captcha_attempts[target_user_id]
            else:
                await query.answer("❌ Incorrect answer. Please try again.")
    except Exception as e:
        logger.error(f"Error handling captcha verification: {e}")

# Function to handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_text = update.message.text.lower()
        chat_id = update.message.chat_id

        # Check if the message matches any filters using exact word matching or command-like format
        if chat_id in filters_dict:
            for keyword, response in filters_dict[chat_id].items():
                # Match exact word or command-like format
                if re.search(rf"\b{re.escape(keyword)}\b", message_text) or re.fullmatch(rf"/{re.escape(keyword)}", message_text):
                    await update.message.reply_text(response)
                    return

        # Check if the message matches any predefined keywords
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                if not os.path.exists(media_file):
                    await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
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
        logger.error(f"Error handling message: {e}")

# Function to handle the /help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Welcome to the bot! Here are some available features:\n\n"
        "- Type keywords like 'audio', 'video', 'profits', etc., to get corresponding media.\n"
        "- New members must solve a captcha to join the chat.\n"
        "- Admins can use commands like /ban, /kick, /addsolexafilter, /listsolexafilters, /removesolexafilter to manage the group.\n"
        "- For more information, contact the bot administrator."
    )
    await update.message.reply_text(help_text)

# Function to ban a user (admin only)
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type == "private":  # Ensure this is a group chat
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                target_user = context.args[0]
                chat_id = update.message.chat_id

                # Resolve user ID from mention or direct ID
                if target_user.startswith("@"):
                    target_user = target_user[1:]
                    try:
                        user = await context.bot.get_chat_member(chat_id, target_user)
                        user_id = user.user.id
                    except Exception as e:
                        await update.message.reply_text(f"Error: {e}. User @{target_user} may not exist in this chat.")
                        return
                else:
                    user_id = int(target_user)

                await context.bot.ban_chat_member(chat_id, user_id)
                await update.message.reply_text(f"User {target_user} has been banned.")
            except (IndexError, ValueError):
                await update.message.reply_text("Usage: /ban <username> or /ban <user_id>")
        else:
            await update.message.reply_text("You do not have permission to use this command.")
    else:
        await update.message.reply_text("This command can only be used in group chats.")

# Function to kick a user (admin only)
async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type == "private":  # Ensure this is a group chat
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                target_user = context.args[0]
                chat_id = update.message.chat_id

                # Resolve user ID from mention or direct ID
                if target_user.startswith("@"):
                    target_user = target_user[1:]
                    try:
                        user = await context.bot.get_chat_member(chat_id, target_user)
                        user_id = user.user.id
                    except Exception as e:
                        await update.message.reply_text(f"Error: {e}. User @{target_user} may not exist in this chat.")
                        return
                else:
                    user_id = int(target_user)

                await context.bot.unban_chat_member(chat_id, user_id)
                await update.message.reply_text(f"User {target_user} has been kicked.")
            except (IndexError, ValueError):
                await update.message.reply_text("Usage: /kick <username> or /kick <user_id>")
        else:
            await update.message.reply_text("You do not have permission to use this command.")
    else:
        await update.message.reply_text("This command can only be used in group chats.")

# Function to add a filter (admin only)
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type == "private":  # Ensure this is a group chat
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                keyword = context.args[0].lower()
                response = " ".join(context.args[1:])
                chat_id = update.message.chat_id

                if chat_id not in filters_dict:
                    filters_dict[chat_id] = {}

                filters_dict[chat_id][keyword] = response
                await update.message.reply_text(f"Filter '{keyword}' added successfully.")
            except IndexError:
                await update.message.reply_text("Usage: /addsolexafilter <keyword> <response>")
        else:
            await update.message.reply_text("You do not have permission to use this command.")
    else:
        await update.message.reply_text("This command can only be used in group chats.")

# Function to list all filters (admin only)
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type == "private":  # Ensure this is a group chat
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            chat_id = update.message.chat_id
            if chat_id in filters_dict and filters_dict[chat_id]:
                filter_list = "\n".join([f"{k}: {v}" for k, v in filters_dict[chat_id].items()])
                await update.message.reply_text(f"Filters in this chat:\n{filter_list}")
            else:
                await update.message.reply_text("No filters have been added to this chat.")
        else:
            await update.message.reply_text("You do not have permission to use this command.")
    else:
        await update.message.reply_text("This command can only be used in group chats.")

# Function to remove a filter (admin only)
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type == "private":  # Ensure this is a group chat
        if update.message.from_user.id in [admin.user.id for admin in await update.effective_chat.get_administrators()]:
            try:
                keyword = context.args[0].lower()
                chat_id = update.message.chat_id

                if chat_id in filters_dict and keyword in filters_dict[chat_id]:
                    del filters_dict[chat_id][keyword]
                    await update.message.reply_text(f"Filter '{keyword}' removed successfully.")
                else:
                    await update.message.reply_text(f"Filter '{keyword}' does not exist.")
            except IndexError:
                await update.message.reply_text("Usage: /removesolexafilter <keyword>")
        else:
            await update.message.reply_text("You do not have permission to use this command.")
    else:
        await update.message.reply_text("This command can only be used in group chats.")

# Add handlers for all commands and messages
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("ban", ban_user))
application.add_handler(CommandHandler("kick", kick_user))
application.add_handler(CommandHandler("addsolexafilter", add_filter))
application.add_handler(CommandHandler("listsolexafilters", list_filters))
application.add_handler(CommandHandler("removesolexafilter", remove_filter))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"captcha_\d+_\d+"))

# Webhook handler
@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

# Startup event
@app.on_event("startup")
async def startup_event():
    await application.initialize()
    await application.start()
    await application.bot.delete_webhook()
    await application.bot.set_webhook(WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)