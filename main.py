import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from three import register_appxwp_handlers

logging.basicConfig(level=logging.INFO)

async def handle(request):
    return web.Response(text="Bot is running successfully!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

bot = Client(
    "nanex_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Register only Course Extractor handlers
register_appxwp_handlers(bot)

# Start Menu with Only Course Extractor Button
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Extract Course (Classx/Appx)", callback_data="appxwp")]
    ])
    
    welcome_text = (
        "👋 **Welcome to Nanex Course Extractor Bot!**\n\n"
        "Aap is bot ke madhyam se Classx aur Appx courses ko asani se extract kar sakte hain.\n\n"
        "Neeche diye gaye button par click karein:"
    )
    await message.reply_text(welcome_text, reply_markup=keyboard)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_web_server())
    print("Course Extractor Bot is starting...")
    bot.run()
