import os
import logging
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler
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

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        for member in update.message.new_chat_members:
            chat_id = update.message.chat_id
            user_id = member.id
            username = member.first_name

            logger.info(f"New member detected: {username} (ID: {user_id}) in {update.message.chat.title}")

            permissions = ChatPermissions(
                can_send_messages=False
            )
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            logger.info(f"User {username} restricted in supergroup.")

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
        data = query.data.split("_")

        if len(data) != 3:
            return

        _, user_id, answer = data
        user_id = int(user_id)
        answer = int(answer)

        if query.from_user.id != user_id:
            await query.answer("You are not authorized to answer this CAPTCHA.", show_alert=True)
            return

        if user_id not in captcha_attempts:
            await query.answer("This verification has expired.")
            return

        correct_answer = captcha_attempts[user_id]["answer"]
        chat_id = captcha_attempts[user_id]["chat_id"]
        attempts = captcha_attempts[user_id]["attempts"]

        if answer == correct_answer:
            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_other_messages=True,
                can_send_polls=True,
                can_add_web_page_previews=True
            )
            await context.bot.restrict_chat_member(chat_id, user_id, permissions)
            await query.message.edit_text("✅ Verification successful! You may now participate in the chat.")
            del captcha_attempts[user_id]
            logger.info(f"User {user_id} successfully verified and unrestricted.")
        else:
            attempts += 1
            captcha_attempts[user_id]["attempts"] = attempts

            if attempts >= 3:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                await query.message.edit_text("❌ You failed verification 3 times and have been removed from the group.")
                del captcha_attempts[user_id]
                logger.info(f"User {user_id} failed verification and was removed.")
            else:
                await query.answer("❌ Incorrect answer. Please try again.")
    except Exception as e:
        logger.error(f"Error handling captcha verification: {e}")

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(CallbackQueryHandler(verify_captcha, pattern=r"captcha_\d+_\d+"))

@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)

        if not application.running:
            logger.warning("Application is not running. Initializing now...")
            await application.initialize()
            await application.start()

        await application.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def startup_event():
    try:
        await application.initialize()
        await application.start()
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
