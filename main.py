# main.py
import logging
import os
import threading
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyromod import listen

from config import api_id, api_hash, bot_token
from one import register_pwwp_handlers
from two import register_cpwp_handlers
from three import register_appxwp_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def run_web():
    # Render assigns the port dynamically via environmental variable PORT (defaults to 10000)
    port = int(os.environ.get("PORT", 10000))
    try:
        from flask import Flask
        app = Flask(__name__)
        @app.route("/")
        def health():
            return "Bot is alive and running", 200
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        logging.error(f"Flask server failed to start: {e}")

# Start the web health check server in a background thread immediately
threading.Thread(target=run_web, daemon=True).start()

bot = Client("techvjbot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

@bot.on_message(filters.command(["start"]))
async def start(bot: Client, message: Message):
    await message.reply_text("**🎉 Bot Is Running... 🚀**\n\n**🧑‍💻 Use /help to see available extractors & instructions.**")

@bot.on_message(filters.command(["help"]))
async def help(bot: Client, message: Message):
    help_text = (
        "**📖 HOW THIS BOT WORKS & WHAT IT EXTRACTS 📖**\n\n"
        "<blockquote>This bot extracts course content from supported education platforms and generates structured `.txt` files.</blockquote>\n\n"
        "**👇 Choose your platform below to start extracting:**"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 Physics Wallah 🚀", callback_data="pwwp")],
        [InlineKeyboardButton("📘 Classplus 📘", callback_data="cpwp")],
        [InlineKeyboardButton("📒 Classx / Appx 📒", callback_data="appxwp")]
    ]
    await message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard))

register_pwwp_handlers(bot)
register_cpwp_handlers(bot)
register_appxwp_handlers(bot)

if __name__ == "__main__":
    bot.run()
