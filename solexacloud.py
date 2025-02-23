import os
import logging
import asyncio
import random
from fastapi import FastAPI, Request
import uvicorn
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes, ChatMemberHandler

# Enable detailed logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL') + "/telegram"  # Ensure this is set in Render

# Dictionary to store pending CAPTCHA challenges
pending_captchas = {}

# Define the keywords and corresponding media files
keyword_responses = {
    "audio": "test.mp3",
    "secret": "secret.mp3",
    "video": "test.mp4",
    "profits": "PROFITS.jpg",
    "commercial": "commercial.mp4",
    "slut": "SLUT.jpg",
    "launch cat": "launchcat.gif"  # New GIF support
}

# Initialize FastAPI
app = FastAPI()

# Initialize Telegram bot
application = Application.builder().token(TOKEN).build()

# Function to handle new chat members (Captcha System)
async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        user_id = member.id
        chat_id = update.message.chat.id
        
        # Generate a simple math problem
        num1, num2 = random.randint(1, 10), random.randint(1, 10)
        answer = num1 + num2
        pending_captchas[user_id] = (answer, chat_id)
        
        # Restrict user until they solve the CAPTCHA
        await context.bot.restrict_chat_member(
            chat_id, user_id, ChatPermissions(can_send_messages=False)
        )
        
        # Send the math CAPTCHA question
        await context.bot.send_message(
            chat_id, text=f"@{member.username or member.full_name}, welcome!\nPlease solve this CAPTCHA within 120 seconds: {num1} + {num2} = ?"
        )
        
        # Wait 120 seconds before checking
        await asyncio.sleep(120)
        
        # If user hasn't verified, kick them
        if user_id in pending_captchas:
            await context.bot.ban_chat_member(chat_id, user_id)
            del pending_captchas[user_id]

# Function to handle CAPTCHA responses
async def handle_captcha_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    
    if user_id in pending_captchas:
        correct_answer, expected_chat_id = pending_captchas[user_id]
        
        # Ensure the message is in the right chat
        if chat_id != expected_chat_id:
            return
        
        # Check if the answer is correct
        if update.message.text.strip() == str(correct_answer):
            await context.bot.restrict_chat_member(
                chat_id, user_id, ChatPermissions(can_send_messages=True)
            )
            await update.message.reply_text("✅ Verified! You can now chat.")
            del pending_captchas[user_id]
        else:
            await update.message.reply_text("❌ Incorrect answer. Try again!")

# Function to handle text messages (Keyword Replies)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            message_text = update.message.text.lower()

            # Check for keywords
            for keyword, media_file in keyword_responses.items():
                if keyword in message_text:
                    logger.info(f"Keyword '{keyword}' detected. Sending file: {media_file}")
                    
                    # Check if the file exists
                    if not os.path.exists(media_file):
                        logger.error(f"File not found: {media_file}")
                        await update.message.reply_text(f"Sorry, the file '{media_file}' is missing.")
                        return
                    
                    # Send appropriate media
                    with open(media_file, 'rb') as media:
                        if media_file.endswith('.mp3'):
                            await update.message.reply_audio(audio=media)
                        elif media_file.endswith('.mp4'):
                            await update.message.reply_video(video=media)
                        elif media_file.endswith('.jpg'):
                            await update.message.reply_photo(photo=media)
                        elif media_file.endswith('.gif'):
                            await update.message.reply_animation(animation=media)
                    break  # Stop after first match
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

# Add handlers to the bot
application.add_handler(ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_captcha_response))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Webhook endpoint to receive Telegram updates
@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)

        # Ensure bot application is initialized before processing updates
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
