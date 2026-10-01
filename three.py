# three.py
import asyncio
import json
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
    editable = await m.reply_text("**Classx / Appx Extractor Initialized ⏳**")
    try:
        async with aiohttp.ClientSession() as session:
            api_url = await prompt_user(bot, m, editable, "**Enter API Base URL:**\n*(Example: `https://sachinacademyapi.classx.co.in`)*:", user_id)
            token = await prompt_user(bot, m, editable, "**Enter Bearer Token or Auth Key:**", user_id)
            
            await editable.edit("**Testing Classx/Appx API endpoints... 🔍**")
            
            headers = {
                "Authorization": f"Bearer {token}",
                "auth-key": token,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            
            # Updated Classx & Appx course endpoints
            endpoints = [
                "/get_courses",
                "/get_user_courses",
                "/users/getCourses",
                "/v1/users/get-batches",
                "/api/v3/live-course/user-courses",
                "/v1/course/user-courses"
            ]
            
            base = api_url.rstrip('/')
            last_status = None
            last_text = ""
            data = None
            
            for ep in endpoints:
                try:
                    url = f"{base}{ep}"
                    async with session.get(url, headers=headers, timeout=10) as resp:
                        last_status = resp.status
                        last_text = await resp.text()
                        
                        # Skip if response is HTML page (404/error page)
                        if "<html" in last_text.lower() or "<!doctype" in last_text.lower():
                            continue
                            
                        if resp.status == 200:
                            try:
                                res_json = json.loads(last_text) if isinstance(last_text, str) else last_text
                                if res_json.get("data") or res_json.get("courses") or isinstance(res_json, list):
                                    data = res_json
                                    break
                            except Exception:
                                pass
                except Exception as e:
                    last_text = str(e)
                    continue
            
            if not data:
                await editable.edit(
                    f"⚠️ **Could not fetch courses automatically (Last Status: `{last_status}`).**\n\n"
                    f"Make sure your Base URL is correct (e.g., `https://sachinacademyapi.classx.co.in`) and your token/auth key is valid."
                )
                return
            
            batches = data.get("data") or data.get("courses") or data
            if isinstance(batches, dict):
                batches = batches.get("data", []) or batches.get("courses", [])
            
            if not batches:
                await editable.edit("**Connected successfully, but no courses/batches found in the account response.**")
                return
            
            keyboard = []
            for b in batches[:15]:
                title = b.get("title") or b.get("name") or b.get("courseName") or "Untitled Course"
                bid = b.get("_id") or b.get("id") or b.get("courseId")
                if bid:
                    keyboard.append([InlineKeyboardButton(str(title)[:35], callback_data=f"appx_batch_{bid}")])
            
            if not keyboard:
                await editable.edit("**Courses found, but could not parse course IDs.**")
                return
                
            reply_markup = InlineKeyboardMarkup(keyboard)
            await editable.edit(f"**Found {len(batches)} courses! Select one below to extract:**", reply_markup=reply_markup)
            
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
        await callback_query.message.edit_text(f"**Extracting contents for Course/Batch ID:** `{batch_id}`...\n\nGeneration of structured `.txt` download links in progress.")
