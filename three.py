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
        api_url = await prompt_user(bot, m, editable, "**Enter API Base URL:**\n*(Example: `https://sachinacademyapi.classx.co.in`)*:", user_id)
        token = await prompt_user(bot, m, editable, "**Enter Auth Key / Token:**", user_id)
        uid = await prompt_user(bot, m, editable, "**Enter User ID (e.g. `333312`):**", user_id)
        course_id = await prompt_user(bot, m, editable, "**Enter Course ID (e.g. `281`):**", user_id)
        
        await editable.edit("**Authenticating & fetching course content... 🔍**")
        
        token = token.strip().strip('"').strip("'")
        
        headers_options = [
            {"auth-key": token, "User-ID": uid, "client-service": "Appx", "source": "website", "Device-Type": "WEB", "User-Agent": "Mozilla/5.0"},
            {"Authorization": f"Bearer {token}", "User-ID": uid, "client-service": "Appx", "source": "website", "Device-Type": "WEB", "User-Agent": "Mozilla/5.0"},
            {"Authorization": token, "User-ID": uid, "client-service": "Appx", "source": "website", "Device-Type": "WEB", "User-Agent": "Mozilla/5.0"}
        ]
        
        base = api_url.rstrip('/')
        endpoints = [
            f"/get/getposts?course_id={course_id}&start=-1",
            f"/get/course_by_id?id={course_id}",
            f"/get/allsubjectfrmlivecourseclass?courseid={course_id}&start=-1"
        ]
        
        data = None
        last_status = 401
        
        # Safely managed connector to prevent file descriptor -1 errors
        connector = aiohttp.TCPConnector(force_close=True, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            for headers in headers_options:
                headers.update({"Accept": "application/json", "Content-Type": "application/json"})
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
                if data:
                    break
        
        if not data:
            await editable.edit(f"⚠️ **Authentication Failed (Status: `{last_status}`).**\n\nStatus `401` means your **Auth Key/Token** or **User ID** is incorrect or expired.")
            return
        
        await editable.edit(f"✅ **Successfully authenticated and fetched course ID `{course_id}`!**\n\nCourse data loaded successfully. Ready for full extraction.")
        
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
