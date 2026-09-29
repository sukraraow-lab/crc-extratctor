import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

from helpers import ask_user, appx_decrypt, extract_url_from_video_details, is_authorized

SEMAPHORE = asyncio.Semaphore(10)
APPX_APIS_FILE = "appxapis.json"

_appx_apis: Optional[List[Dict]] = None


class ProcessCancelledException(Exception):
    pass


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def format_time(s: float) -> str:
    s = int(s)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}h {m:02d}m {s:02d}s" if h else f"{m:02d}m {s:02d}s"


async def prompt_user(bot, message, editable, text, user_id):
    r = await ask_user(
        bot, message, editable,
        text + "\n\n<blockquote>❌ Send `/cancel` to abort.</blockquote>",
        user_id,
    )
    if r is None or r.strip().lower() == "/cancel":
        await editable.edit("**Cancelled ❌**")
        raise ProcessCancelledException()
    return r.strip()


async def update_status(editable, task, cur, tot, start, activity):
    pct = (cur / tot * 100) if tot else 0
    el  = time.time() - start
    eta = format_time((el / cur) * (tot - cur)) if cur > 0 else "Calculating..."
    bar = "▓" * int(pct // 10) + "░" * (10 - int(pct // 10))
    try:
        await editable.edit(
            f"<blockquote>⚙️ **Task:** `{task}`</blockquote>\n\n"
            f"📊 [{bar}] `{pct:.1f}%` ({cur}/{tot})\n"
            f"📌 {activity}\n"
            f"⏱️ `{format_time(el)}` elapsed | ⏳ ETA `{eta}`\n\n"
            f"<blockquote>❌ Send `/cancel` to abort.</blockquote>"
        )
    except Exception:
        pass


# ─── APPX API LIST ────────────────────────────────────────────────────────────

def load_appx_apis() -> List[Dict]:
    global _appx_apis
    if _appx_apis is None:
        try:
            with open(APPX_APIS_FILE, "r", encoding="utf-8") as f:
                _appx_apis = json.load(f)
        except Exception as e:
            logging.error(f"Failed to load appxapis.json: {e}")
            _appx_apis = []
    return _appx_apis


def search_appx_apis(query: str) -> List[Dict]:
    apis = load_appx_apis()
    q = query.lower().strip()
    return [
        a for a in apis
        if q in a.get("name", "").lower() or q in a.get("api", "").lower()
    ]


def resolve_api_url(api_entry: Dict) -> str:
    url = api_entry.get("api", "").rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    return url


# ─── HTTP HELPERS ─────────────────────────────────────────────────────────────

APPX_BASE_HEADERS = {
    "Client-Service": "Appx",
    "Auth-Key": "appxapi",
    "source": "website",
    "Content-Type": "application/x-www-form-urlencoded",
}


async def fetch_appx(
    session: aiohttp.ClientSession,
    url: str,
    method: str = "GET",
    headers: dict = None,
    data: dict = None,
    params: dict = None,
    retry: int = 3,
) -> Optional[Any]:
    h = dict(APPX_BASE_HEADERS)
    if headers:
        h.update(headers)
    async with SEMAPHORE:
        for attempt in range(retry):
            try:
                if method == "POST":
                    async with session.post(url, headers=h, data=data,
                                            params=params) as resp:
                        ct = resp.content_type or ""
                        text = await resp.text()
                        if "json" in ct:
                            return json.loads(text)
                        # some appx apps return JSON without content-type header
                        try:
                            return json.loads(text)
                        except Exception:
                            return {"_raw": text, "status": resp.status}
                else:
                    async with session.get(url, headers=h,
                                           params=params) as resp:
                        ct = resp.content_type or ""
                        text = await resp.text()
                        if "json" in ct:
                            return json.loads(text)
                        try:
                            return json.loads(text)
                        except Exception:
                            return {"_raw": text, "status": resp.status}
            except Exception as e:
                logging.error(f"appx fetch attempt {attempt+1} {url}: {e}")
                if attempt < retry - 1:
                    await asyncio.sleep(2 ** attempt)
    return None


# ─── LOGIN ───────────────────────────────────────────────────────────────────

async def resolve_api_and_app_name(
    bot, m, editable, app_input: str, user_id: int
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve app name to API URL. Supports direct URL or name search."""
    if app_input.startswith("http"):
        return app_input.rstrip("/"), app_input

    results = search_appx_apis(app_input)
    if not results:
        await editable.edit(
            f"**No Appx app found for:** `{app_input}`\n\n"
            f"Try entering the direct API URL (e.g. `https://appname.classx.co.in`)"
        )
        return None, None

    if len(results) == 1:
        return resolve_api_url(results[0]), results[0]["name"]

    text = "\n".join(
        f"<blockquote>**{i+1}.** `{a['name']}`</blockquote>"
        for i, a in enumerate(results[:20])
    )
    idx = await prompt_user(
        bot, m, editable,
        f"**Multiple apps found. Select:**\n\n{text}",
        user_id,
    )
    if not idx.isdigit() or not (1 <= int(idx) <= len(results[:20])):
        await editable.edit("**Invalid selection ❌**")
        return None, None

    chosen = results[int(idx) - 1]
    return resolve_api_url(chosen), chosen["name"]


async def login_appx_user(
    session: aiohttp.ClientSession,
    bot, m, editable, user_id: int
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (api_url, token, app_name) or (None, None, None) on failure."""

    app_input = await prompt_user(
        bot, m, editable,
        "**Enter App Name to search OR direct API URL:**\n\n"
        "<blockquote>Examples:\n"
        "• `Khan Sir`\n"
        "• `https://myapp.classx.co.in`</blockquote>",
        user_id,
    )

    api, app_name = await resolve_api_and_app_name(
        bot, m, editable, app_input, user_id)
    if not api:
        return None, None, None

    auth_mode = await prompt_user(
        bot, m, editable,
        f"**App:** `{app_name}`\n\n"
        "**Auth Mode:**\n"
        "<blockquote>**1.** Mobile + Password</blockquote>\n"
        "<blockquote>**2.** Paste existing token directly</blockquote>",
        user_id,
    )

    if auth_mode == "2":
        token = await prompt_user(bot, m, editable, "**Paste your token:**", user_id)
        return api, token, app_name

    mobile   = await prompt_user(bot, m, editable, "**Enter Mobile Number:**", user_id)
    password = await prompt_user(bot, m, editable, "**Enter Password:**", user_id)

    await editable.edit("🔑 **Authenticating...**")

    login_data = {"email": mobile, "password": password}

    # try multiple login endpoint patterns — different appx-based platforms use different paths
    login_endpoints = [
        f"{api}/post/userlogin",
        f"{api}/api/v1/userlogin",
        f"{api}/api/userlogin",
        f"{api}/user/login",
        f"{api}/api/v2/userlogin",
    ]

    res = None
    for endpoint in login_endpoints:
        try:
            r = await fetch_appx(session, endpoint, method="POST", data=login_data)
            if r and (r.get("status") == 200 or r.get("success")) and r.get("data"):
                res = r
                break
        except Exception:
            continue

    if not res or not res.get("data"):
        msg = (res or {}).get("message", "All login endpoints failed.")
        await editable.edit(f"**Login Failed ❌**\n`{msg}`")
        return None, None, None

    data  = res["data"]
    token = (
        data.get("token") or data.get("jwt_token") or
        data.get("user_token") or data.get("authToken") or
        data.get("auth_token")
    )

    if not token:
        await editable.edit("**Login ok but no token returned ❌**")
        return None, None, None

    await bot.send_message(
        m.chat.id,
        f"🔑 **Appx Token Generated!**\n\n"
        f"**App:** `{app_name}`\n"
        f"**Mobile:** `{mobile}`\n"
        f"**Token:**\n`{token}`\n\n"
        f"<blockquote>Copy and save this token for future use.</blockquote>",
    )
    return api, token, app_name


# ─── CONTENT EXTRACTION ───────────────────────────────────────────────────────

def make_appx_auth_headers(token: str) -> dict:
    return {
        "Client-Service": "Appx",
        "Auth-Key": "appxapi",
        "Authorization": token,
        "Content-Type": "application/json",
    }


async def get_appx_subjects(
    session: aiohttp.ClientSession, api: str, token: str
) -> List[Dict]:
    res = await fetch_appx(
        session,
        f"{api}/api/v1/getsubjectforcourse",
        headers=make_appx_auth_headers(token),
    )
    if res and res.get("data"):
        return res["data"]
    # fallback endpoint
    res2 = await fetch_appx(
        session,
        f"{api}/post/getsubjects",
        headers=make_appx_auth_headers(token),
    )
    return (res2 or {}).get("data", [])


async def get_appx_topics(
    session: aiohttp.ClientSession,
    api: str,
    token: str,
    subject_id: str,
) -> List[Dict]:
    for endpoint in [
        f"{api}/api/v1/getfoldersbysubject",
        f"{api}/post/getfolders",
    ]:
        res = await fetch_appx(
            session, endpoint,
            headers=make_appx_auth_headers(token),
            params={"subject_id": subject_id},
        )
        if res and res.get("data"):
            return res["data"]
    return []


async def get_appx_content(
    session: aiohttp.ClientSession,
    api: str,
    token: str,
    folder_id: str,
    subject_id: str,
) -> List[Dict]:
    for endpoint, params in [
        (f"{api}/api/v1/getvideosbyfolder",
         {"folder_wise_course": "0", "folder_id": folder_id,
          "subject_id": subject_id}),
        (f"{api}/post/getvideos",
         {"folder_id": folder_id, "subject_id": subject_id}),
        (f"{api}/api/v1/getvideosbyfolder",
         {"folder_wise_course": "1", "folder_id": folder_id,
          "subject_id": subject_id}),
    ]:
        res = await fetch_appx(
            session, endpoint,
            headers=make_appx_auth_headers(token),
            params=params,
        )
        if res and res.get("data"):
            return res["data"]
    return []


def resolve_appx_url(item: Dict) -> str:
    """Extract and decrypt video/pdf URL from an appx content item."""
    # try video_url fields first
    raw = (
        item.get("video_url") or item.get("videoUrl") or
        item.get("pdf_url") or item.get("pdfUrl") or
        item.get("file_url") or item.get("url") or ""
    )
    if not raw:
        return ""

    # try decrypt — if result is a valid URL use it, else fall back to raw
    decrypted = appx_decrypt(raw)
    if decrypted and decrypted.startswith("http"):
        return decrypted

    if raw.startswith("http"):
        return raw

    return ""


async def extract_appx_all(
    session: aiohttp.ClientSession,
    api: str,
    token: str,
    editable,
    start: float,
) -> List[str]:
    lines: List[str] = []

    subjects = await get_appx_subjects(session, api, token)
    if not subjects:
        return lines

    for si, sub in enumerate(subjects):
        sub_id   = str(sub.get("id") or sub.get("subject_id") or "")
        sub_name = sub.get("subject") or sub.get("name") or f"Subject_{si+1}"

        await update_status(editable, sub_name, si, len(subjects), start,
                            f"Scanning subjects...")

        topics = await get_appx_topics(session, api, token, sub_id)
        if not topics:
            # subject may directly have content with no topic folders
            items = await get_appx_content(session, api, token, "0", sub_id)
            for item in items:
                url = resolve_appx_url(item)
                title = item.get("title") or item.get("video_title") or "Unknown"
                if url:
                    lines.append(f"{title}:{url}\n")
            continue

        for ti, topic in enumerate(topics):
            folder_id  = str(topic.get("id") or topic.get("folder_id") or "0")
            topic_name = topic.get("folder") or topic.get("name") or f"Topic_{ti+1}"

            await update_status(editable, sub_name, ti, len(topics), start,
                                f"📂 `{topic_name[:40]}`")

            items = await get_appx_content(
                session, api, token, folder_id, sub_id)

            for item in items:
                url   = resolve_appx_url(item)
                title = (item.get("title") or item.get("video_title")
                         or item.get("pdf_title") or "Unknown")
                if url:
                    lines.append(f"{topic_name} | {title}:{url}\n")

    return lines


# ─── MAIN PROCESS ─────────────────────────────────────────────────────────────

async def process_appxwp(bot, m, user_id):
    editable = await m.reply_text("**Initializing Appx Extractor... ⏳**")
    file_path = None

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            connector=aiohttp.TCPConnector(limit=500),
        ) as session:

            api, token, app_name = await login_appx_user(
                session, bot, m, editable, user_id)
            if not api or not token:
                return

            await editable.edit(f"**✅ Logged in to `{app_name}`\nExtracting content... ⏳**")

            start     = time.time()
            lines     = await extract_appx_all(session, api, token, editable, start)

            if not lines:
                await editable.edit(
                    "**No content found ❌**\n\n"
                    "Token may be expired or this app has no accessible content.")
                return

            safe_name = re.sub(r'[\\/*?:"<>|]', "-", app_name)
            file_path = f"{safe_name}.txt"

            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            await editable.delete()

            cap = (
                f"**App:** `{app_name}`\n"
                f"📄 **Total URLs:** `{len(lines)}`\n"
                f"⏱️ **Time:** `{format_time(time.time() - start)}`"
            )
            with open(file_path, "rb") as f:
                await m.reply_document(f, caption=cap,
                                        file_name=f"{safe_name}.txt")

    except ProcessCancelledException:
        pass
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


# ─── HANDLER REGISTRATION ─────────────────────────────────────────────────────

def register_appxwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^appxwp$"))
    async def _(client, cq):
        await cq.answer()
        asyncio.create_task(process_appxwp(client, cq.message, cq.from_user.id))
