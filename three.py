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
    editable = await m.reply_text("**Classx Ultimate Extractor Initialized ⏳**")
    try:
        api_url = await prompt_user(bot, m, editable, "**Enter API Base URL:**\n*(Example: `https://sachinacademyapi.classx.co.in`)*:", user_id)
        token = await prompt_user(bot, m, editable, "**Enter Auth Key / Token:**", user_id)
        uid = await prompt_user(bot, m, editable, "**Enter User ID (e.g. `333312`):**", user_id)
        course_id = await prompt_user(bot, m, editable, "**Enter Course ID (e.g. `281`):**", user_id)
        
        await editable.edit("**Smart-testing all Classx header variations... 🔍**")
        
        token = token.strip().strip('"').strip("'")
        base = api_url.rstrip('/')
        
        # Expanded variations for Classx / Appx backends
        header_variants = [
            {"auth-key": token, "User-ID": uid, "client-service": "classx", "source": "website", "Device-Type": "WEB"},
            {"auth-key": token, "User-ID": uid, "client-service": "Appx", "source": "website", "Device-Type": "WEB"},
            {"auth-key": token, "User-ID": uid, "client-service": "classx"},
            {"Authorization": f"Bearer {token}", "auth-key": token, "User-ID": uid, "client-service": "classx"},
            {"Authorization": token, "auth-key": token, "User-ID": uid, "client-service": "Appx"}
        ]
        
        endpoints = [
            f"/get/getposts?course_id={course_id}&start=-1",
            f"/get/course_by_id?id={course_id}",
            f"/get/allsubjectfrmlivecourseclass?courseid={course_id}&start=-1"
        ]
        
        data = None
        last_resp_text = ""
        
        connector = aiohttp.TCPConnector(force_close=True, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            for base_headers in header_variants:
                base_headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                })
                
                for ep in endpoints:
                    url = f"{base}{ep}"
                    try:
                        async with session.get(url, headers=base_headers, timeout=8) as resp:
                            last_resp_text = await resp.text()
                            if resp.status == 200 and not ("<html" in last_resp_text.lower() or "<!doctype" in last_resp_text.lower()):
                                try:
                                    res_json = json.loads(last_resp_text)
                                    if isinstance(res_json, dict) and res_json.get("status") == 401:
                                        continue
                                    data = res_json
                                    break
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if data:
                    break
        
        if not data:
            await editable.edit(
                f"⚠️ **Still getting 401 Unauthorized.**\n\n"
                f"Last Server Response:\n`{last_resp_text[:300]}`\n\n"
                f"💡 **Important Check:** Make sure you copy the exact value from the `auth-key` header in your browser's Network tab, not just a random cookie or login password."
            )
            return
        
        await editable.edit(f"✅ **Authentication Successful! Course ID `{course_id}` loaded successfully.**\n\nData extracted. Ready for full extraction.")
        
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
