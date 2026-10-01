# two.py
import asyncio
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from helpers import ask_user

SEMAPHORE = asyncio.Semaphore(15)

class ProcessCancelledException(Exception):
    pass

async def prompt_user(bot: Client, m: Message, editable: Message, text: str, user_id: int) -> str:
    cancel_notice = "\n\n<blockquote>❌ **Send `/cancel` at any time to abort this process.**</blockquote>"
    response = await ask_user(bot, m, editable, text + cancel_notice, user_id)
    if response is None or response.strip().lower() == "/cancel":
        await editable.edit("**Process Cancelled by User ❌**")
        raise ProcessCancelledException("User requested cancellation.")
    return response.strip()

async def process_cpwp(bot: Client, m: Message, user_id: int):
    editable = await m.reply_text("**Classplus Extractor Initialized ⏳**")
    try:
        async with aiohttp.ClientSession() as session:
            org_code = await prompt_user(bot, m, editable, "**Enter Classplus Org Code:**", user_id)
            phone = await prompt_user(bot, m, editable, "**Enter Mobile Number or Access Token:**", user_id)
            await editable.edit("**Classplus extraction module ready ✅**")
    except ProcessCancelledException:
        pass
    except Exception as e:
        logging.exception("Error in process_cpwp:")
        await editable.edit(f"**Error:** `{e}`")

def register_cpwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^cpwp$"))
    async def cpwp_callback(client: Client, callback_query):
        user_id = callback_query.from_user.id
        await callback_query.answer()
        asyncio.create_task(process_cpwp(client, callback_query.message, user_id))
