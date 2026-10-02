import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from three import register_appxwp_handlers
from leech import register_leech_handlers

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

# Register modules handlers
register_appxwp_handlers(bot)
register_leech_handlers(bot)

# Start Menu with Inline Buttons
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Extract Course (Classx/Appx)", callback_data="appxwp")],
        [InlineKeyboardButton("📤 Leech .txt File to Group", callback_data="start_leech")]
    ])
    
    welcome_text = (
        "👋 **Welcome to Nanex Bot!**\n\n"
        "Aap is bot ke madhyam se Classx courses extract kar sakte hain ya apni `.txt` file ko seedha Telegram group me leech/upload kar sakte hain.\n\n"
        "Neeche diye gaye buttons me se apna option chunein:"
    )
    await message.reply_text(welcome_text, reply_markup=keyboard)

@bot.on_callback_query(filters.regex("^start_leech$"))
async def leech_button_callback(client: Client, callback_query):
    await callback_query.answer()
    await callback_query.message.reply_text(
        "📥 **Leech Mode Activated!**\n\n"
        "Kripya apni generated **`.txt` file** ko is chat me document ki tarah bhej dein. Uske baad bot aapse Target Group ID puchega."
    )

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_web_server())
    print("Bot is starting with Button Menu...")
    bot.run()
    
