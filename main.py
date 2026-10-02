import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client

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

register_appxwp_handlers(bot)
register_leech_handlers(bot)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_web_server())
    print("Bot is starting...")
    bot.run()
