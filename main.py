import asyncio
import logging
import os
import signal
import sys
import threading

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

log = logging.getLogger(__name__)

# ─── FLASK HEALTH SERVER ──────────────────────────────────────────────────────
# Keeps render web-service health checks alive.
# Runs in a non-daemon thread so it survives SIGTERM to the bot loop.

_flask_started = threading.Event()


def _run_flask():
    port = int(os.environ.get("PORT", 8080))
    try:
        from flask import Flask
        app = Flask("zerotrace")

        @app.route("/")
        def _root():
            return "ZeroTrace running ✅", 200

        @app.route("/health")
        def _health():
            return "ok", 200

        _flask_started.set()
        # threaded=True keeps it responsive while bot is busy
        app.run(host="0.0.0.0", port=port,
                use_reloader=False, threaded=True, debug=False)
    except Exception as exc:
        log.warning(f"Flask failed: {exc} — falling back to stdlib")
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

        _flask_started.set()
        with socketserver.TCPServer(("", port), _H) as srv:
            srv.serve_forever()


# Start flask in a NON-daemon thread — stays up even when bot loop restarts
_flask_thread = threading.Thread(target=_run_flask, daemon=False)
_flask_thread.start()
_flask_started.wait(timeout=15)
log.info("Flask health server ready.")


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
async def help_cmd(client: Client, message: Message):
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


# ─── SIGTERM HANDLER ─────────────────────────────────────────────────────────
# Render sends SIGTERM during rolling deploys to the OLD instance.
# Default behaviour: Python raises SystemExit which kills bot.run() immediately.
# Fix: catch SIGTERM, log it, then let the bot finish gracefully.
# Flask thread stays alive (non-daemon) so render health check keeps passing
# on the NEW instance while the old one drains.

_shutdown = asyncio.Event()


def _handle_sigterm(*_):
    log.warning("SIGTERM received — initiating graceful shutdown...")
    # Signal the asyncio loop to stop
    loop = asyncio.get_event_loop()
    loop.call_soon_threadsafe(_shutdown.set)


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT,  _handle_sigterm)


async def _main():
    log.info("Starting ZeroTrace bot...")
    await bot.start()
    log.info("Bot started. Waiting for shutdown signal...")

    # Block here until SIGTERM/SIGINT received
    await _shutdown.wait()

    log.info("Shutdown signal received. Stopping bot gracefully...")
    await bot.stop()
    log.info("Bot stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(_main())
