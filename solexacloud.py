import os
import logging
import asyncio
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackContext

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"

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

# Store CAPTCHA challenges
pending_captchas = {}

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

# Function to handle text messages (Keyword Replies & CAPTCHA Checks)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        chat_id = update.message.chat.id

        # If user has a pending CAPTCHA, check their response
        if user_id in pending_captchas:
            if update.message.text.strip() == str(pending_captchas[user_id]["answer"]):
                await update.message.reply_text("✅ Verification successful! You can now chat.")
                del pending_captchas[user_id]  # Remove from pending list

                # Check if the chat is a supergroup before unrestricting
                chat = await context.bot.get_chat(chat_id)
                if chat.type == "supergroup":
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions=ChatPermissions(can_send_messages=True)
                    )
            else:
                await update.message.reply_text("❌ Incorrect answer. Try again.")
            return  # Stop further processing

        # Handle keyword-based media sending
        message_text = update.message.text.lower()
        for keyword, media_file in keyword_responses.items():
            if keyword in message_text:
                logger.info(f"Keyword '{keyword}' detected. Sending file: {media_file}")

                if not os.path.exists(media_file):
                    logger.error(f"File not found: {media_file}")
                    await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                    return

                with open(media_file, 'rb') as media:
                    if media_file.endswith('.mp3'):
                        await update.message.reply_audio(audio=media)
                    elif media_file.endswith('.mp4'):
                        await update.message.reply_video(video=media, supports_streaming=True)
                    elif media_file.endswith('.jpg'):
                        await update.message.reply_photo(photo=media)
                    elif media_file.endswith('.gif'):
                        await update.message.reply_animation(animation=media)
                break
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

# Function to handle new members joining
async def handle_new_members(update: Update, context: CallbackContext):
    try:
        chat_id = update.message.chat.id
        chat = await context.bot.get_chat(chat_id)  # Get chat info
        chat_type = chat.type  # Get chat type
        logger.info(f"Group Type: {chat_type} | Chat Title: {chat.title}")

        for user in update.message.new_chat_members:
            user_id = user.id
            username = user.username or user.full_name

            logger.info(f"New member detected: {username} (ID: {user_id}) in {chat.title}")

            # Generate a CAPTCHA math question
            num1 = random.randint(1, 10)
            num2 = random.randint(1, 10)
            answer = num1 + num2
            pending_captchas[user_id] = {"chat_id": chat_id, "answer": answer}

            # Only restrict if it's a supergroup
            if chat_type == "supergroup":
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions=ChatPermissions(can_send_messages=False)
                    )
                    logger.info(f"User {username} restricted in supergroup.")
                except Exception as e:
                    logger.error(f"Could not restrict user {user_id}: {e}")
            else:
                logger.warning(f"Cannot restrict {username}. {chat.title} is a basic group.")

            # Send CAPTCHA message
            await update.message.reply_text(
                f"🚨 Welcome {username}! Please verify you are human.\nSolve this to chat: **{num1} + {num2} = ?**\n(Reply with the correct answer within 120 seconds.)",
                parse_mode="Markdown"
            )

            # If the group is not a supergroup, notify admins
            if chat_type != "supergroup":
                await update.message.reply_text(
                    "⚠️ This group is a **basic group**. CAPTCHA will work, but users won't be restricted.\nTo enable full verification, upgrade to a **supergroup**!"
                )

            # Set a timeout to remove the user if they fail to respond
            context.job_queue.run_once(kick_unverified_user, 120, chat_id=chat_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Error handling new member event: {e}")

# Function to kick users who fail the CAPTCHA
async def kick_unverified_user(context: CallbackContext):
    job = context.job
    user_id = job.user_id
    chat_id = job.chat_id

    if user_id in pending_captchas:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            del pending_captchas[user_id]
            logger.info(f"User {user_id} removed for failing CAPTCHA.")
        except Exception as e:
            logger.error(f"Error removing user {user_id}: {e}")

# Add handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))

# Webhook endpoint to receive Telegram updates
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

# Startup event for setting webhook
@app.on_event("startup")
async def startup_event():
    try:
        logger.info("Starting bot initialization...")

        await application.initialize()
        await application.start()

        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to: {WEBHOOK_URL}")

        logger.info("Bot is fully running...")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

# Ensure proper port binding for Render
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
