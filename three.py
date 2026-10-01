import asyncio
import base64
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

from helpers import appx_decrypt, ask_user

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

async def fetch_appx_html_to_json(session: aiohttp.ClientSession, url: str, headers: Dict = None, data: Any = None) -> Any:
    async with SEMAPHORE:
        for attempt in range(3):
            try:
                if data:
                    async with session.post(url, headers=headers, data=data) as response:
                        text = await response.text()
                else:
                    async with session.get(url, headers=headers) as response:
                        text = await response.text()
                return json.loads(text)
            except Exception:
                pass
            await asyncio.sleep(1.5 ** attempt)
        return None

async def process_appxwp(bot: Client, m: Message, user_id: int):
    editable = await m.reply_text("**Appx Extractor Initialized ⏳**")
    try:
        async with aiohttp.ClientSession() as session:
            api_url = await prompt_user(bot, m, editable, "**Enter App Base API URL:**", user_id)
            token = await prompt_user(bot, m, editable, "**Enter Bearer Token:**", user_id)
            await editable.edit("**Appx extraction module ready ✅**")
    except ProcessCancelledException:
        pass
    except Exception as e:
        await editable.edit(f"**Error:** `{e}`")

def register_appxwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^appxwp$"))
    async def appxwp_callback(client: Client, callback_query):
        user_id = callback_query.from_user.id
        await callback_query.answer()
        asyncio.create_task(process_appxwp(client, callback_query.message, user_id))
```[cite: 10]

---

### 7. Deployment Configuration Files

#### `requirements.txt`
```text
kurigram
requests
cloudscraper
beautifulsoup4==4.12.2
bs4==0.0.2
aiohttp
aiofiles
yt-dlp
pycryptodome==3.20.0
PySocks==1.7.1
websockets==12.0
psutil
colorama
pyaes==1.6.1
soupsieve==2.5
python-decouple==3.8
Flask==3.0.3
gunicorn==22.0.0
pyromod==3.1.6
```[cite: 8]

#### `Procfile`
```text
web: python main.py
```[cite: 6]

#### `railway.json`
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -r requirements.txt"
  },
  "deploy": {
    "startCommand": "python main.py",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```[cite: 7]
