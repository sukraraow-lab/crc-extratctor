import asyncio
import logging
import os
import signal
import threading

from pyrogram import Client, filters, idle
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
log = logging.getLogger(__name__)

# ─── FLASK HEALTH SERVER ──────────────────────────────────────────────────────

_flask_ready = threading.Event()

def _run_flask():
    port = int(os.environ.get("PORT", 8080))
    try:
        from flask import Flask
        app = Flask("zerotrace")

        @app.route("/")
        def _root():
            return "ZeroTrace running", 200

        @app.route("/health")
        def _health():
            return "ok", 200

        _flask_ready.set()
        app.run(host="0.0.0.0", port=port,
                use_reloader=False, threaded=True, debug=False)
    except Exception as exc:
        log.warning(f"Flask failed: {exc} — stdlib fallback")
        import http.server, socketserver

        class _H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ZeroTrace running")
            def do_HEAD(self):
                self.send_response(200)
                self.end_headers()
            def log_message(self, *a):
                pass

        _flask_ready.set()
        with socketserver.TCPServer(("", port), _H) as srv:
            srv.serve_forever()

# non-daemon so flask outlives SIGTERM to old instance
_flask_thread = threading.Thread(target=_run_flask, daemon=False)
_flask_thread.start()
_flask_ready.wait(timeout=15)
log.info("Flask health server ready.")

# ─── BOT ──────────────────────────────────────────────────────────────────────

bot = Client(
    "zerotrace_session",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token,
)


@bot.on_message(filters.command(["start"]))
async def cmd_start(client: Client, message: Message):
    await message.reply_text(
        "**⚡ ZeroTrace Bot Is Running... 🚀**\n\n"
        "**Use /help to see available extractors.**"
    )


@bot.on_message(filters.command(["help"]))
async def cmd_help(client: Client, message: Message):
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

# ─── RUN ──────────────────────────────────────────────────────────────────────

async def _main():
    log.info("Starting ZeroTrace bot...")
    await bot.start()
    log.info("Bot started — handlers active, listening for messages.")
    # idle() keeps the event loop running AND processes incoming updates
    # SIGTERM/SIGINT → idle() catches it and exits cleanly
    await idle()
    log.info("Stopping bot...")
    await bot.stop()
    log.info("Bot stopped cleanly.")

if __name__ == "__main__":
    asyncio.run(_main())
