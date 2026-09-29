import asyncio
import logging
import os
import threading
import time

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyromod import listen

from config import api_id, api_hash, bot_token
from one   import register_pwwp_handlers
from two   import register_cpwp_handlers
from three import register_appxwp_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ─── WEB HEALTH SERVER ────────────────────────────────────────────────────────
# Render kills worker processes if they don't bind a port when type=web.
# We use type=worker in Procfile, but keep this server anyway as a safety net.

_web_ready = threading.Event()

def run_web():
    port = int(os.environ.get("PORT", 8080))
    try:
        from flask import Flask
        app = Flask(__name__)

        @app.route("/")
        def health():
            return "ZeroTrace Bot running ✅", 200

        @app.route("/health")
        def healthz():
            return "ok", 200

        # signal ready before blocking
        _web_ready.set()
        app.run(host="0.0.0.0", port=port, use_reloader=False)
    except Exception as e:
        logging.warning(f"Flask failed ({e}), falling back to stdlib server")
        import http.server
        import socketserver

        class QuietHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ZeroTrace Bot running")
            def log_message(self, *args):
                pass

        _web_ready.set()
        with socketserver.TCPServer(("", port), QuietHandler) as httpd:
            httpd.serve_forever()

# start web in background, wait until port is bound before starting bot
_web_thread = threading.Thread(target=run_web, daemon=True)
_web_thread.start()
_web_ready.wait(timeout=10)   # give Flask up to 10s to bind port

# ─── BOT ──────────────────────────────────────────────────────────────────────

bot = Client(
    "zerotrace_session",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token,
)


@bot.on_message(filters.command(["start"]))
async def start(client: Client, message: Message):
    await message.reply_text(
        "**⚡ ZeroTrace Bot Is Running... 🚀**\n\n"
        "**Use /help to see available extractors.**"
    )


@bot.on_message(filters.command(["help"]))
async def help(client: Client, message: Message):
    help_text = (
        "**📖 ZeroTrace — Course Extractor 📖**\n\n"
        "<blockquote>Extracts course content (videos, PDFs, notes) from supported "
        "platforms and generates `.txt` files with stream links.</blockquote>\n\n"
        "──────────────────────────\n"
        "**🚀 Physics Wallah**\n"
        "<blockquote>Free + purchased batches via PW Auth Token or OTP login.</blockquote>\n\n"
        "**📘 Classplus**\n"
        "<blockquote>ORG Code + Phone/OTP or Access Token. "
        "m3u8, DRM, JW Player, PDFs, images.</blockquote>\n\n"
        "**📒 Appx**\n"
        "<blockquote>App name search or direct API URL. "
        "Credentials or token. Recursive folder scraping.</blockquote>\n"
        "──────────────────────────\n\n"
        "**👇 Choose your platform:**"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 Physics Wallah 🚀", callback_data="pwwp")],
        [InlineKeyboardButton("📘 Classplus 📘",      callback_data="cpwp")],
        [InlineKeyboardButton("📒 Appx 📒",           callback_data="appxwp")],
    ]
    await message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


register_pwwp_handlers(bot)
register_cpwp_handlers(bot)
register_appxwp_handlers(bot)

if __name__ == "__main__":
    logging.info("Starting ZeroTrace bot...")
    bot.run()
