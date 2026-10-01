import asyncio
import json
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

try:
    from helpers import ask_user
except ImportError:
    async def ask_user(*args, **kwargs):
        return None

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
    editable = await m.reply_text("**Classx Extractor Initialized ⏳**")
    try:
        async with aiohttp.ClientSession() as session:
            api_url = await prompt_user(bot, m, editable, "**Enter API Base URL:**\n*(Example: `https://sachinacademyapi.classx.co.in`)*:", user_id)
            token = await prompt_user(bot, m, editable, "**Enter Auth Key / Bearer Token:**", user_id)
            uid = await prompt_user(bot, m, editable, "**Enter User ID (e.g. `333312`):**", user_id)
            course_id = await prompt_user(bot, m, editable, "**Enter Course ID (e.g. `281` from your browser URL):**", user_id)
            
            await editable.edit("**Fetching course content using Classx endpoints... 🔍**")
            
            headers = {
                "Authorization": f"Bearer {token}",
                "auth-key": token,
                "User-ID": uid,
                "client-service": "Appx",
                "source": "website",
                "Device-Type": "WEB",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            base = api_url.rstrip('/')
            endpoints = [
                f"/get/getposts?course_id={course_id}&start=-1",
                f"/get/course_by_id?id={course_id}",
                f"/get/allsubjectfrmlivecourseclass?courseid={course_id}&start=-1",
                f"/get/filtersbycourse?courseid={course_id}"
            ]
            
            data = None
            last_status = None
            
            for ep in endpoints:
                url = f"{base}{ep}"
                try:
                    async with session.get(url, headers=headers, timeout=10) as resp:
                        last_status = resp.status
                        text = await resp.text()
                        if resp.status == 200 and not ("<html" in text.lower() or "<!doctype" in text.lower()):
                            data = json.loads(text)
                            break
                except Exception:
                    pass
            
            if not data:
                await editable.edit(f"⚠️ **Failed to fetch course data (Status: `{last_status}`). Check your Course ID or Auth Key.**")
                return
            
            await editable.edit(f"✅ **Successfully connected and fetched course ID `{course_id}`!**\n\nCourse data loaded successfully. Ready for full extraction.")
            
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
