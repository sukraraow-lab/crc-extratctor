import asyncio
import json
import logging
import os
import time
import uuid
import zipfile
from typing import Any, Dict, List, Optional
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

from helpers import ask_user, extract_url_from_video_details, is_authorized

SEMAPHORE = asyncio.Semaphore(15)

class ProcessCancelledException(Exception):
    pass

def format_time(seconds: float) -> str:
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:02d}h {mins:02d}m {secs:02d}s"
    return f"{mins:02d}m {secs:02d}s"

async def prompt_user(bot: Client, message: Message, editable: Message, text: str, user_id: int) -> str:
    cancel_notice = "\n\n<blockquote>❌ **Send `/cancel` at any time to abort this process.**</blockquote>"
    response = await ask_user(bot, message, editable, text + cancel_notice, user_id)
    if response is None or response.strip().lower() == "/cancel":
        await editable.edit("**Process Cancelled by User ❌**")
        raise ProcessCancelledException("User requested cancellation.")
    return response.strip()

async def update_status_card(editable: Message, task_name: str, current: int, total: int, start_time: float, activity: str):
    percentage = (current / total * 100) if total > 0 else 0
    elapsed = time.time() - start_time
    eta = (elapsed / current * (total - current)) if current > 0 and total > 0 else 0
    filled_blocks = int(percentage // 10)
    progress_bar = "▓" * filled_blocks + "░" * (10 - filled_blocks)
    status_text = (
        f"<blockquote>⚙️ **Processing Task:** `{task_name}`</blockquote>\n\n"
        f"📊 **Progress:** [{progress_bar}] `{percentage:.1f}%` ({current}/{total})\n"
        f"📌 **Current Activity:** {activity}\n"
        f"⏱️ **Time Elapsed:** `{format_time(elapsed)}`\n"
        f"⏳ **Time Left (ETA):** `{format_time(eta)}`\n\n"
        f"<blockquote>❌ **Send `/cancel` to abort.**</blockquote>"
    )
    try:
        await editable.edit(status_text)
    except Exception:
        pass

async def fetch_pwwp_data(session: aiohttp.ClientSession, url: str, headers: Dict = None, params: Dict = None, data: Dict = None, method: str = "GET") -> Any:
    async with SEMAPHORE:
        for attempt in range(3):
            try:
                async with session.request(method, url, headers=headers, params=params, json=data) as response:
                    response.raise_for_status()
                    return await response.json()
            except Exception:
                pass
            await asyncio.sleep(2 ** attempt)
        return None

async def process_pwwp(bot: Client, m: Message, user_id: int):
    api_headers = {
        "accept": "*/*", "origin": "https://www.pw.live", "referer": "https://www.pw.live/",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/148.0.0.0 Safari/537.36",
        "client-id": "5eb393ee95fab7468a79d189", "client-type": "WEB", "content-type": "application/json",
        "randomid": str(uuid.uuid4()), "x-sdk-version": "0.0.25",
    }
    editable = await m.reply_text("**Wait initializing process... ⏳**")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            access_token = await prompt_user(bot, m, editable, "**Enter Your PW Account Access Token:**", user_id)
            auth_headers = {**api_headers, "authorization": f"Bearer {access_token}"}
            batch_search = await prompt_user(bot, m, editable, "**Enter Batch Name to Search:**", user_id)
            
            courses_res = await fetch_pwwp_data(session, "https://api.penpencil.co/v3/batches/search", headers=auth_headers, params={"name": batch_search})
            courses = courses_res.get("data", []) if courses_res else []
            if not courses:
                await editable.edit("**No Batches Found! ❌ Check your Access Token.**")
                return
            
            text_list = "\n".join([f"<blockquote>**{i+1}.** `{c.get('name', 'Batch')}`</blockquote>" for i, c in enumerate(courses)])
            idx_str = await prompt_user(bot, m, editable, f"**Select Course Index:**\n\n{text_list}", user_id)
            selected_course = courses[int(idx_str) - 1]
            batch_id, batch_name = selected_course["_id"], selected_course.get("name", "Batch")
            clean_name = batch_name.replace('/', '-').replace('|', '-')
            
            b_details = await fetch_pwwp_data(session, f"https://api.penpencil.co/v3/batches/{batch_id}/details", headers=auth_headers)
            subjects = b_details.get("data", {}).get("subjects", []) if b_details else []
            
            all_urls = []
            for sub in subjects:
                sub_name = sub.get("subject", "Unknown")
                all_urls.append(f"Subject: {sub_name}")
            
            output_file = f"{clean_name}.txt"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("\n".join(all_urls))
            
            with open(output_file, "rb") as doc:
                await m.reply_document(doc, caption=f"**Batch:** `{batch_name}`")
            os.remove(output_file)
            await editable.delete()
    except Exception as e:
        await editable.edit(f"**Error:** `{e}`")

def register_pwwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^pwwp$"))
    async def pwwp_callback(client: Client, callback_query):
        user_id = callback_query.from_user.id
        await callback_query.answer()
        asyncio.create_task(process_pwwp(client, callback_query.message, user_id))
