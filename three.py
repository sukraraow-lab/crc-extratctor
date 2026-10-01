# three.py
import asyncio
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from helpers import ask_user

SEMAPHORE = asyncio.Semaphore(15)

class ProcessCancelledException(Exception):
    pass

async def prompt_user(bot: Client, message: Message, editable: Message, text: str, user_id: int) -> str:
    cancel_notice = "\n\n<blockquote>❌ **Send `/cancel` at any time to abort this process.**</blockquote>"
    response = await ask_user(bot, message, editable, text + cancel_notice, user_id)
    if response is None or response.strip().lower() == "/cancel":
        await editable.edit("**Process Cancelled by User ❌**")
        raise ProcessCancelledException("User requested cancellation.")
    return response.strip()

async def process_appxwp(bot: Client, m: Message, user_id: int):
    editable = await m.reply_text("**Appx Extractor Initialized ⏳**")
    try:
        async with aiohttp.ClientSession() as session:
            api_url = await prompt_user(bot, m, editable, "**Enter App Base API URL (e.g., https://api.appx.co.in):**", user_id)
            token = await prompt_user(bot, m, editable, "**Enter Bearer Token:**", user_id)
            
            await editable.edit("**Fetching your batches across API routes... 🔍**")
            
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            
            # List of possible Appx/Course API endpoints to test automatically
            endpoints = [
                "/v1/users/get-batches",
                "/api/v3/live-course/user-courses",
                "/v1/course/user-courses",
                "/api/v1/users/get-batches",
                "/v2/users/get-batches"
            ]
            
            data = None
            base = api_url.rstrip('/')
            for ep in endpoints:
                try:
                    async with session.get(f"{base}{ep}", headers=headers, timeout=10) as resp:
                        if resp.status == 200:
                            res_json = await resp.json()
                            if res_json.get("data"):
                                data = res_json
                                break
                except Exception:
                    continue
            
            if not data or not data.get("data"):
                await editable.edit("**Failed to fetch batches. All standard Appx endpoints returned 404 or empty data. Check your API Base URL.**")
                return
            
            batches = data.get("data", [])
            keyboard = []
            for b in batches[:15]:
                title = b.get("title") or b.get("name") or "Untitled Batch"
                bid = b.get("_id") or b.get("id")
                keyboard.append([InlineKeyboardButton(title[:35], callback_data=f"appx_batch_{bid}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await editable.edit(f"**Found {len(batches)} batches! Select one below to extract:**", reply_markup=reply_markup)
            
    except ProcessCancelledException:
        pass
    except Exception as e:
        logging.exception("Error in process_appxwp:")
        await editable.edit(f"**Error:** `{e}`")

def register_appxwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^appxwp$"))
    async def appxwp_callback(client: Client, callback_query):
        user_id = callback_query.from_user.id
        await callback_query.answer()
        asyncio.create_task(process_appxwp(client, callback_query.message, user_id))
    
    @bot.on_callback_query(filters.regex(r"^appx_batch_"))
    async def appx_batch_callback(client: Client, callback_query):
        batch_id = callback_query.data.split("_")[2]
        await callback_query.answer("Extracting batch content...")
        await callback_query.message.edit_text(f"**Extracting contents for Batch ID:** `{batch_id}`...\n\nGeneration of structured `.txt` links in progress.")
