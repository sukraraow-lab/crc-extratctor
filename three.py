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
    editable = await m.reply_text("**Classx Auto-Unlocker Initialized ⏳**")
    try:
        api_url = await prompt_user(bot, m, editable, "**Enter API Base URL:**\n*(Example: `https://sachinacademyapi.classx.co.in`)*:", user_id)
        token = await prompt_user(bot, m, editable, "**Enter Auth Key / Token:**", user_id)
        uid = await prompt_user(bot, m, editable, "**Enter User ID (e.g. `333312`):**", user_id)
        course_id = await prompt_user(bot, m, editable, "**Enter Course ID (e.g. `281`):**", user_id)
        
        await editable.edit("**Testing client-service & auth variations automatically... 🔍**")
        
        token = token.strip().strip('"').strip("'")
        base = api_url.rstrip('/')
        url = f"{base}/get/getposts?course_id={course_id}&start=-1"
        
        # Possible client-service identifiers used by Classx/Appx backends
        client_services = ["classx", "Appx", "sachinacademy", "SachinAcademy", "appx"]
        
        data = None
        
        connector = aiohttp.TCPConnector(force_close=True, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            for cs in client_services:
                # Variant 1: auth-key header
                headers_v1 = {
                    "auth-key": token,
                    "User-ID": uid,
                    "client-service": cs,
                    "source": "website",
                    "Device-Type": "WEB",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json"
                }
                try:
                    async with session.get(url, headers=headers_v1, timeout=8) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            res = json.loads(text)
                            if isinstance(res, dict) and res.get("status") != 401:
                                data = res
                                break
                except Exception:
                    pass

                # Variant 2: Bearer token + auth-key
                headers_v2 = {
                    "Authorization": f"Bearer {token}",
                    "auth-key": token,
                    "User-ID": uid,
                    "client-service": cs,
                    "source": "website",
                    "Device-Type": "WEB",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json"
                }
                try:
                    async with session.get(url, headers=headers_v2, timeout=8) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            res = json.loads(text)
                            if isinstance(res, dict) and res.get("status") != 401:
                                data = res
                                break
                except Exception:
                    pass
                
                if data:
                    break

        if not data:
            await editable.edit(
                f"❌ **401 Unauthorized across all client-service variants.**\n\n"
                f"💡 Kripya ensure karein ki aapne jo `auth-key` dala hai wo bilkul fresh hai aur `User-ID` (`333312`) sahi hai."
            )
            return
        
        await editable.edit(f"✅ **Bypass Successful! Course ID `{course_id}` loaded successfully.**\n\nData extracted successfully. Ready for full extraction.")
        
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
