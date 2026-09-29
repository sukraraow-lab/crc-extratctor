# three.py — Appx Without Purchase Extractor
# Credit: VJ_Bots / ZeroTrace

import asyncio
import json
import logging
import os
import re
import time
from base64 import b64decode
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from pyromod.exceptions import ListenerTimeout

from helpers import ask_user, appx_decrypt, is_authorized
from config import auth_users

SEMAPHORE = asyncio.Semaphore(10)


class ProcessCancelledException(Exception):
    pass


# ─── UTILS ────────────────────────────────────────────────────────────────────

def format_time(seconds: float) -> str:
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:02d}h {mins:02d}m {secs:02d}s"
    return f"{mins:02d}m {secs:02d}s"


# ─── APPX API LIST ────────────────────────────────────────────────────────────

_appx_apis: Optional[List[Dict]] = None


def load_appx_apis() -> List[Dict]:
    global _appx_apis
    if _appx_apis is None:
        for fname in ["appxapis.json", "threeapis.json"]:
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    _appx_apis = json.load(f)
                    return _appx_apis
            except Exception:
                continue
        _appx_apis = []
    return _appx_apis


def search_appx(query: str) -> List[Dict]:
    q = query.lower().strip()
    return [
        a for a in load_appx_apis()
        if q in a.get("name", "").lower() or q in a.get("api", "").lower()
    ][:20]


def clean_api_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    return url


# ─── HTTP ─────────────────────────────────────────────────────────────────────

APPX_HEADERS = {
    "Client-Service": "Appx",
    "Auth-Key": "appxapi",
    "source": "website",
    "Content-Type": "application/x-www-form-urlencoded",
}


async def appx_get(
    session: aiohttp.ClientSession,
    url: str,
    token: str = "",
    params: dict = None,
) -> Optional[Any]:
    h = dict(APPX_HEADERS)
    if token:
        h["Authorization"] = token
    async with SEMAPHORE:
        for attempt in range(3):
            try:
                async with session.get(
                    url, headers=h, params=params, timeout=aiohttp.ClientTimeout(total=30)
                ) as r:
                    text = await r.text()
                    try:
                        return json.loads(text)
                    except Exception:
                        return None
            except Exception as e:
                logging.error(f"appx_get attempt {attempt+1} {url}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
    return None


async def appx_post(
    session: aiohttp.ClientSession,
    url: str,
    data: dict,
    token: str = "",
) -> Optional[Any]:
    h = dict(APPX_HEADERS)
    if token:
        h["Authorization"] = token
    async with SEMAPHORE:
        for attempt in range(3):
            try:
                async with session.post(
                    url, headers=h, data=data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as r:
                    text = await r.text()
                    try:
                        return json.loads(text)
                    except Exception:
                        return {"_raw": text, "_status": r.status}
            except Exception as e:
                logging.error(f"appx_post attempt {attempt+1} {url}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
    return None


# ─── LOGIN ────────────────────────────────────────────────────────────────────

async def appx_login(
    session: aiohttp.ClientSession,
    api: str,
    mobile: str,
    password: str,
) -> Optional[str]:
    """Try all known login endpoints, return token or None."""
    login_data = {"email": mobile, "password": password}
    endpoints = [
        f"{api}/post/userlogin",
        f"{api}/api/v1/userlogin",
        f"{api}/api/userlogin",
        f"{api}/user/login",
        f"{api}/api/v2/userlogin",
    ]
    for endpoint in endpoints:
        try:
            res = await appx_post(session, endpoint, login_data)
            if not res:
                continue
            status = res.get("status") or res.get("_status", 0)
            data = res.get("data") or res.get("user") or {}
            if (str(status) == "200" or res.get("success")) and data:
                token = (
                    data.get("token") or data.get("jwt_token") or
                    data.get("user_token") or data.get("authToken") or
                    data.get("auth_token") or
                    res.get("token") or res.get("jwt_token")
                )
                if token:
                    return str(token)
        except Exception as e:
            logging.error(f"login endpoint {endpoint}: {e}")
            continue
    return None


# ─── CONTENT ─────────────────────────────────────────────────────────────────

def resolve_url(item: Dict) -> str:
    """Extract + decrypt video/pdf URL from an appx content item."""
    raw = (
        item.get("video_url") or item.get("videoUrl") or
        item.get("pdf_url") or item.get("pdfUrl") or
        item.get("file_url") or item.get("url") or
        item.get("video_url_hls") or item.get("videoUrlHls") or ""
    )
    if not raw:
        return ""
    # try decrypt
    decrypted = appx_decrypt(raw)
    if decrypted and decrypted.startswith("http"):
        return decrypted
    if raw.startswith("http"):
        return raw
    return ""


async def get_subjects(
    session: aiohttp.ClientSession, api: str, token: str
) -> List[Dict]:
    for endpoint in [
        f"{api}/api/v1/getsubjectforcourse",
        f"{api}/post/getsubjects",
        f"{api}/api/v2/getsubjectforcourse",
    ]:
        res = await appx_get(session, endpoint, token=token)
        if res and res.get("data"):
            return res["data"]
    return []


async def get_folders(
    session: aiohttp.ClientSession,
    api: str,
    token: str,
    subject_id: str,
) -> List[Dict]:
    for endpoint in [
        f"{api}/api/v1/getfoldersbysubject",
        f"{api}/post/getfolders",
        f"{api}/api/v2/getfoldersbysubject",
    ]:
        res = await appx_get(
            session, endpoint, token=token,
            params={"subject_id": subject_id}
        )
        if res and res.get("data"):
            return res["data"]
    return []


async def get_videos(
    session: aiohttp.ClientSession,
    api: str,
    token: str,
    folder_id: str,
    subject_id: str,
    folder_wise: str = "0",
) -> List[Dict]:
    """Try all known video fetch endpoints and param combos."""
    combos = [
        (f"{api}/api/v1/getvideosbyfolder",
         {"folder_wise_course": folder_wise, "folder_id": folder_id, "subject_id": subject_id}),
        (f"{api}/api/v1/getvideosbyfolder",
         {"folder_wise_course": "0", "folder_id": folder_id, "subject_id": subject_id}),
        (f"{api}/api/v1/getvideosbyfolder",
         {"folder_wise_course": "1", "folder_id": folder_id, "subject_id": subject_id}),
        (f"{api}/post/getvideos",
         {"folder_id": folder_id, "subject_id": subject_id}),
        (f"{api}/api/v2/getvideosbyfolder",
         {"folder_wise_course": "0", "folder_id": folder_id, "subject_id": subject_id}),
    ]
    for endpoint, params in combos:
        res = await appx_get(session, endpoint, token=token, params=params)
        if res and res.get("data"):
            return res["data"]
    return []


async def extract_all_content(
    session: aiohttp.ClientSession,
    api: str,
    token: str,
    editable,
    start: float,
) -> List[str]:
    lines: List[str] = []
    subjects = await get_subjects(session, api, token)

    if not subjects:
        return lines

    for si, sub in enumerate(subjects):
        sub_id   = str(sub.get("id") or sub.get("subject_id") or "")
        sub_name = (sub.get("subject") or sub.get("name") or f"Subject_{si+1}").strip()

        try:
            pct = int((si / len(subjects)) * 100)
            bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
            await editable.edit(
                f"<blockquote>📚 **Extracting:** `{sub_name}`</blockquote>\n\n"
                f"📊 [{bar}] `{pct}%` ({si}/{len(subjects)})\n"
                f"⏱️ `{format_time(time.time() - start)}` elapsed"
            )
        except Exception:
            pass

        folders = await get_folders(session, api, token, sub_id)

        if not folders:
            # subject may have content directly, no folders
            items = await get_videos(session, api, token, "0", sub_id, "0")
            for item in items:
                url   = resolve_url(item)
                title = (item.get("title") or item.get("video_title")
                         or item.get("pdf_title") or "Unknown")
                if url:
                    lines.append(f"{sub_name} | {title}:{url}\n")
            continue

        for fi, folder in enumerate(folders):
            folder_id   = str(folder.get("id") or folder.get("folder_id") or "0")
            folder_name = (folder.get("folder") or folder.get("name") or f"Folder_{fi+1}").strip()

            items = await get_videos(session, api, token, folder_id, sub_id)
            for item in items:
                url   = resolve_url(item)
                title = (item.get("title") or item.get("video_title")
                         or item.get("pdf_title") or "Unknown")
                if url:
                    lines.append(f"{sub_name} | {folder_name} | {title}:{url}\n")

    return lines


# ─── MAIN PROCESS ────────────────────────────────────────────────────────────

async def process_appxwp(bot: Client, m: Message, user_id: int):
    editable = await m.reply_text("**📒 Appx Extractor**\n\nInitializing... ⏳")
    file_path = None

    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=500),
            timeout=aiohttp.ClientTimeout(total=60),
        ) as session:

            # ── Step 1: app selection ─────────────────────────────────────
            await editable.edit(
                "**Enter App Name to search OR direct API URL:**\n\n"
                "<blockquote>Examples:\n"
                "• `Sachin` or `Khan Sir`\n"
                "• `https://sachinsir.classx.co.in`</blockquote>\n\n"
                "<blockquote>❌ Send `/cancel` to abort.</blockquote>"
            )

            try:
                inp = await bot.listen(m.chat.id, filters=filters.user(user_id), timeout=120)
                app_input = (inp.text or "").strip()
                await inp.delete(True)
            except ListenerTimeout:
                await editable.edit("**⏱ Timeout.**")
                return

            if app_input.lower() == "/cancel":
                await editable.edit("**Cancelled ❌**")
                return

            # resolve API URL
            if app_input.startswith("http"):
                api      = clean_api_url(app_input)
                app_name = api
            else:
                results = search_appx(app_input)
                if not results:
                    await editable.edit(
                        f"**No app found for:** `{app_input}`\n\n"
                        "Try the direct API URL instead."
                    )
                    return

                if len(results) == 1:
                    api      = clean_api_url(results[0]["api"])
                    app_name = results[0]["name"]
                else:
                    text = "\n".join(
                        f"<blockquote>**{i+1}.** `{a['name']}`</blockquote>"
                        for i, a in enumerate(results)
                    )
                    await editable.edit(
                        f"**Multiple apps found — choose one:**\n\n{text}\n\n"
                        "<blockquote>❌ `/cancel` to abort.</blockquote>"
                    )
                    try:
                        inp = await bot.listen(m.chat.id, filters=filters.user(user_id), timeout=120)
                        idx = (inp.text or "").strip()
                        await inp.delete(True)
                    except ListenerTimeout:
                        await editable.edit("**⏱ Timeout.**")
                        return
                    if idx.lower() == "/cancel":
                        await editable.edit("**Cancelled ❌**")
                        return
                    if not idx.isdigit() or not (1 <= int(idx) <= len(results)):
                        await editable.edit("**Invalid selection ❌**")
                        return
                    chosen   = results[int(idx) - 1]
                    api      = clean_api_url(chosen["api"])
                    app_name = chosen["name"]

            # ── Step 2: auth mode ─────────────────────────────────────────
            await editable.edit(
                f"**App:** `{app_name}`\n\n"
                "**Choose auth mode:**\n"
                "<blockquote>**1.** Mobile + Password (auto login)</blockquote>\n"
                "<blockquote>**2.** Paste existing token</blockquote>\n\n"
                "<blockquote>❌ `/cancel` to abort.</blockquote>"
            )
            try:
                inp = await bot.listen(m.chat.id, filters=filters.user(user_id), timeout=120)
                mode = (inp.text or "").strip()
                await inp.delete(True)
            except ListenerTimeout:
                await editable.edit("**⏱ Timeout.**")
                return

            if mode.lower() == "/cancel":
                await editable.edit("**Cancelled ❌**")
                return

            token = None

            if mode == "2":
                await editable.edit(
                    "**Paste your token:**\n\n"
                    "<blockquote>❌ `/cancel` to abort.</blockquote>"
                )
                try:
                    inp = await bot.listen(m.chat.id, filters=filters.user(user_id), timeout=120)
                    token = (inp.text or "").strip()
                    await inp.delete(True)
                except ListenerTimeout:
                    await editable.edit("**⏱ Timeout.**")
                    return
            else:
                # mode 1: mobile + password
                await editable.edit(
                    "**Enter Mobile Number:**\n\n"
                    "<blockquote>❌ `/cancel` to abort.</blockquote>"
                )
                try:
                    inp = await bot.listen(m.chat.id, filters=filters.user(user_id), timeout=120)
                    mobile = (inp.text or "").strip()
                    await inp.delete(True)
                except ListenerTimeout:
                    await editable.edit("**⏱ Timeout.**")
                    return

                if mobile.lower() == "/cancel":
                    await editable.edit("**Cancelled ❌**")
                    return

                await editable.edit(
                    "**Enter Password:**\n\n"
                    "<blockquote>❌ `/cancel` to abort.</blockquote>"
                )
                try:
                    inp = await bot.listen(m.chat.id, filters=filters.user(user_id), timeout=120)
                    password = (inp.text or "").strip()
                    await inp.delete(True)
                except ListenerTimeout:
                    await editable.edit("**⏱ Timeout.**")
                    return

                if password.lower() == "/cancel":
                    await editable.edit("**Cancelled ❌**")
                    return

                await editable.edit("🔑 **Authenticating...**")
                token = await appx_login(session, api, mobile, password)

                if not token:
                    await editable.edit(
                        "**Login Failed ❌**\n\n"
                        "All endpoints tried. Check mobile/password or try token mode."
                    )
                    return

                await bot.send_message(
                    m.chat.id,
                    f"🔑 **Appx Token Generated!**\n\n"
                    f"**App:** `{app_name}`\n"
                    f"**Mobile:** `{mobile}`\n"
                    f"**Token:**\n`{token}`\n\n"
                    f"<blockquote>Copy and save this token for future use.</blockquote>"
                )

            # ── Step 3: extract ───────────────────────────────────────────
            await editable.edit(
                f"**✅ Logged in**\n"
                f"**App:** `{app_name}`\n\n"
                "🔄 **Extracting content...** ⏳"
            )

            start = time.time()
            lines = await extract_all_content(session, api, token, editable, start)

            if not lines:
                await editable.edit(
                    "**No content found ❌**\n\n"
                    "Token may be expired, wrong app, or this app has no accessible content.\n"
                    "Try: different API URL or fresh token."
                )
                return

            safe = re.sub(r'[\\/*?:"<>|]', "-", app_name)
            file_path = f"{safe}.txt"

            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            elapsed = format_time(time.time() - start)
            try:
                await editable.delete()
            except Exception:
                pass

            caption = (
                f"**App:** `{app_name}`\n"
                f"📄 **Total URLs:** `{len(lines)}`\n"
                f"⏱️ **Time:** `{elapsed}`"
            )
            with open(file_path, "rb") as f:
                await m.reply_document(f, caption=caption, file_name=f"{safe}.txt")

    except Exception as e:
        logging.exception("Appx error:")
        try:
            await editable.edit(f"**Error:** `{e}`")
        except Exception:
            pass
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# ─── HANDLER ─────────────────────────────────────────────────────────────────

def register_appxwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^appxwp$"))
    async def appxwp_cb(client: Client, cq):
        await cq.answer()
        user_id = cq.from_user.id
        if auth_users and user_id not in auth_users:
            await cq.message.reply_text("**You are not authorized.**")
            return
        asyncio.create_task(process_appxwp(client, cq.message, user_id))
