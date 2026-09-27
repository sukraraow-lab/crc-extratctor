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
    port = int(os.environ.get("PORT", 8080))
    try:
        from flask import Flask
        app = Flask(__name__)
        @app.route("/")
        def health():
            return "ZeroTrace Bot running", 200
        app.run(host="0.0.0.0", port=port)
    except Exception:
        import http.server, socketserver
        handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("", port), handler) as httpd:
            httpd.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

bot = Client("zerotrace_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)


@bot.on_message(filters.command(["start"]))
async def start(bot: Client, message: Message):
    await message.reply_text("**⚡ ZeroTrace Bot Is Running... 🚀**\n\n**Use /help to see available extractors & instructions.**")

@bot.on_message(filters.command(["help"]))
async def help(bot: Client, message: Message):
    help_text = (
        "**📖 ZeroTrace — Course Extractor 📖**\n\n"
        "<blockquote>Extracts course content (videos, PDFs, images, notes) from supported platforms and generates `.txt` files with stream links.</blockquote>\n\n"
        "--------------------------------------------------\n"
        "**🚀 1. Physics Wallah**\n"
        "<blockquote>• Extracts free preview & purchased batch content via PW Auth Token.</blockquote>\n\n"
        "**📘 2. Classplus**\n"
        "<blockquote>• Extracts via ORG Code + Phone/OTP or Access Token. Supports m3u8, DRM, JW Player, PDFs, images.</blockquote>\n\n"
        "**📒 3. Appx**\n"
        "<blockquote>• Extracts via App Key/Token or credentials. Recursive folder scraping.</blockquote>\n"
        "--------------------------------------------------\n\n"
        "**👇 Choose your platform:**"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 Physics Wallah 🚀", callback_data="pwwp")],
        [InlineKeyboardButton("📘 Classplus 📘", callback_data="cpwp")],
        [InlineKeyboardButton("📒 Appx 📒", callback_data="appxwp")]
    ]
    await message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard))


register_pwwp_handlers(bot)
register_cpwp_handlers(bot)
register_appxwp_handlers(bot)

if __name__ == "__main__":
    bot.run()
