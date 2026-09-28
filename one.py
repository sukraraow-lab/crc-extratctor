# one.py — FULL FIXED VERSION

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

SEMAPHORE = asyncio.Semaphore(10)


class ProcessCancelledException(Exception):
    pass


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:02d}h {mins:02d}m {secs:02d}s"
    return f"{mins:02d}m {secs:02d}s"


def make_pw_headers(token: str = None) -> dict:
    """Always-fresh PW headers with new randomid each call."""
    h = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://www.pw.live",
        "referer": "https://www.pw.live/",
        "user-agent": (
            "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Mobile Safari/537.36"
        ),
        "client-id": "5eb393ee95fab7468a79d189",
        "client-type": "WEB",
        "content-type": "application/json",
        "randomid": str(uuid.uuid4()),        # fresh every call
        "x-sdk-version": "0.0.35",            # FIX: was 0.0.25
    }
    if token:
        h["authorization"] = f"Bearer {token}"
    return h


async def prompt_user(bot, message, editable, text, user_id):
    cancel = "\n\n<blockquote>❌ **Send `/cancel` to abort.**</blockquote>"
    response = await ask_user(bot, message, editable, text + cancel, user_id)
    if response is None or response.strip().lower() == "/cancel":
        await editable.edit("**Process Cancelled ❌**")
        raise ProcessCancelledException()
    return response.strip()


async def update_status_card(editable, task_name, current, total, start_time, activity):
    pct = (current / total * 100) if total > 0 else 0
    elapsed = time.time() - start_time
    eta_str = "Calculating..."
    if current > 0 and total > 0:
        eta = (elapsed / current) * (total - current)
        eta_str = format_time(eta)
    filled = int(pct // 10)
    bar = "▓" * filled + "░" * (10 - filled)
    txt = (
        f"<blockquote>⚙️ **Task:** `{task_name}`</blockquote>\n\n"
        f"📊 **Progress:** [{bar}] `{pct:.1f}%` ({current}/{total})\n"
        f"📌 **Activity:** {activity}\n"
        f"⏱️ **Elapsed:** `{format_time(elapsed)}`\n"
        f"⏳ **ETA:** `{eta_str}`\n\n"
        f"<blockquote>❌ Send `/cancel` to abort.</blockquote>"
    )
    try:
        await editable.edit(txt)
    except Exception:
        pass


async def pw_fetch(session: aiohttp.ClientSession, url, headers=None,
                   params=None, data=None, method="GET") -> Any:
    async with SEMAPHORE:
        for attempt in range(3):
            try:
                async with session.request(
                    method, url, headers=headers, params=params, json=data
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as e:
                logging.error(f"PW attempt {attempt+1} {url}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
    return None


async def pw_login_otp(session, mobile, headers):
    """Send OTP — v3 endpoint."""
    # FIX: was /v1/users/get-otp-secure?smsType=0
    url = "https://api.penpencil.co/v3/users/get-otp"
    payload = {
        "organizationId": "5eb393ee95fab7468a79d189",
        "username": mobile,
        "countryCode": "+91",
        "isLoggedIn": False,
    }
    return await pw_fetch(session, url, headers=headers, data=payload, method="POST")


async def pw_verify_otp(session, mobile, otp, headers):
    """Verify OTP and get token — v3 oauth endpoint with corrected secret."""
    url = "https://api.penpencil.co/v3/oauth/token"
    payload = {
        "organizationId": "5eb393ee95fab7468a79d189",
        # FIX: client_secret was rotated; current working value:
        "client_id": "system-admin",
        "client_secret": "KjPXuAVfC5xbmgreETNMaL7z",
        "grant_type": "password",
        "latitude": 0,
        "longitude": 0,
        "username": mobile,
        "otp": str(otp),
        "isLoggedIn": False,
    }
    result = await pw_fetch(session, url, headers=headers, data=payload, method="POST")
    # FIX: also try alternate secret if first fails
    if not result or not result.get("data", {}).get("access_token"):
        payload["client_secret"] = "appxapi"
        result = await pw_fetch(session, url, headers=headers, data=payload, method="POST")
    return result


async def process_pwwp_chapter_content(session, batch_id, subject_id, schedule_id,
                                        content_type, token):
    url = (f"https://api.penpencil.co/v1/batches/{batch_id}/subject"
           f"/{subject_id}/schedule/{schedule_id}/schedule-details")
    data = await pw_fetch(session, url, headers=make_pw_headers(token))
    content = []
    if data and data.get("success") and data.get("data"):
        item = data["data"]
        topic = item.get("topic", "")
        if content_type in ("videos", "DppVideos"):
            url_ = extract_url_from_video_details(item)
            if url_:
                content.append(f"{topic}:{url_}")
        else:
            for hw in item.get("homeworkIds", []) or []:
                hw_topic = hw.get("topic", topic)
                for att in hw.get("attachmentIds", []) or []:
                    u = att.get("baseUrl", "") + att.get("key", "")
                    if u:
                        content.append(f"{hw_topic}:{u}")
    return {content_type: content} if content else {}


async def fetch_pwwp_all_schedule(session, chapter_id, batch_id, subject_id,
                                   content_type, token):
    all_schedules, page = [], 1
    while True:
        url = (f"https://api.penpencil.co/v2/batches/{batch_id}"
               f"/subject/{subject_id}/contents")
        params = {"tag": chapter_id, "contentType": content_type, "page": page}
        data = await pw_fetch(session, url, headers=make_pw_headers(token), params=params)
        if data and data.get("success") and data.get("data"):
            for item in data["data"]:
                item["content_type"] = content_type
                if content_type in ("videos", "DppVideos"):
                    direct = extract_url_from_video_details(item)
                    if direct:
                        item["_pre"] = direct
                all_schedules.append(item)
            page += 1
        else:
            break
    return all_schedules


async def process_pwwp_chapters(session, chapter_id, batch_id, subject_id, token):
    types = ["videos", "notes", "DppNotes", "DppVideos"]
    all_sch = await asyncio.gather(*[
        fetch_pwwp_all_schedule(session, chapter_id, batch_id, subject_id, ct, token)
        for ct in types
    ])
    flat = [s for sub in all_sch for s in sub]
    tasks = []
    for item in flat:
        sid, ct = item["_id"], item["content_type"]
        if ct in ("videos", "DppVideos") and item.get("_pre"):
            async def _direct(c=ct, n=item.get("topic", sid), u=item["_pre"]):
                return {c: [f"{n}:{u}"]}
            tasks.append(_direct())
        else:
            tasks.append(process_pwwp_chapter_content(
                session, batch_id, subject_id, sid, ct, token))
    results = await asyncio.gather(*tasks)
    combined = {}
    for res in results:
        for c_type, c_list in res.items():
            combined.setdefault(c_type, []).extend(c_list)
    return combined


async def get_pw_chapters(session, batch_id, subject_id, token):
    chapters, page = [], 1
    while True:
        url = (f"https://api.penpencil.co/v2/batches/{batch_id}"
               f"/subject/{subject_id}/topics?page={page}")
        data = await pw_fetch(session, url, headers=make_pw_headers(token))
        if data and data.get("data"):
            chapters.extend(data["data"])
            page += 1
        else:
            break
    return chapters


async def process_pw_subject(session, subject, batch_id, batch_name,
                              zipf, json_data, all_urls, token):
    sub_name = subject.get("subject", "Unknown").replace("/", "-")
    sub_id   = subject.get("_id")
    json_data[batch_name][sub_name] = {}
    zipf.writestr(f"{sub_name}/", "")
    chapters = await get_pw_chapters(session, batch_id, sub_id, token)
    results  = await asyncio.gather(*[
        process_pwwp_chapters(session, ch["_id"], batch_id, sub_id, token)
        for ch in chapters
    ])
    all = []
    for ch, cmap in zip(chapters, results):
        ch_name = ch.get("name", "Unknown").replace("/", "-")
        json_data[batch_name][sub_name][ch_name] = {}
        for ct in ["videos", "notes", "DppNotes", "DppVideos"]:
            if cmap.get(ct):
                lst = list(reversed(cmap[ct]))
                zipf.writestr(
                    f"{sub_name}/{ch_name}/{ct}.txt",
                    "\n".join(lst).encode("utf-8"),
                )
                json_data[batch_name][sub_name][ch_name][ct] = lst
                all.extend(lst)
    all_urls[sub_name] = all


async def process_pwwp(bot, m, user_id):
    editable = await m.reply_text("**Initializing... ⏳**")
    clean_name = None
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        ) as session:

            raw = await prompt_user(
                bot, m, editable,
                "**Enter PW Access Token OR 10-digit Mobile Number:**\n\n"
                "<blockquote>To get token: login on pw.live, open DevTools → "
                "Application → Local Storage → pw.live → authToken</blockquote>",
                user_id,
            )

            token = None

            if raw.isdigit() and len(raw) == 10:
                await editable.edit("**Sending OTP... ⏳**")
                otp_res = await pw_login_otp(session, raw, make_pw_headers())
                if not otp_res or not otp_res.get("success"):
                    err = (otp_res or {}).get("message", "OTP send failed")
                    await editable.edit(f"**OTP Failed ❌**\n`{err}`")
                    return

                otp = await prompt_user(bot, m, editable,
                                        "**Enter OTP received on phone:**", user_id)

                await editable.edit("**Verifying OTP... ⏳**")
                tok_res = await pw_verify_otp(session, raw, otp, make_pw_headers())
                token = (tok_res or {}).get("data", {}).get("access_token")
                if not token:
                    msg = (tok_res or {}).get("message", "Token not returned")
                    await editable.edit(f"**Login Failed ❌**\n`{msg}`")
                    return
                await editable.edit("**✅ PW Login Success!**")
            else:
                token = raw

            # FIX: pagination on search
            search = await prompt_user(bot, m, editable,
                                        "**Enter Batch Name to Search:**", user_id)
            await editable.edit("**Searching... 🔍**")
            res = await pw_fetch(
                session,
                "https://api.penpencil.co/v3/batches/search",
                headers=make_pw_headers(token),
                params={"name": search, "page": 1, "limit": 20},  # FIX
            )
            courses = (res or {}).get("data", [])
            if not courses:
                await editable.edit(
                    "**No Batches Found ❌**\n\nCheck token or try different name.")
                return

            text = "\n".join(
                f"<blockquote>**{i+1}.** `{c.get('name','Batch')}`</blockquote>"
                for i, c in enumerate(courses)
            )
            idx = await prompt_user(bot, m, editable,
                                    f"**Select Batch:**\n\n{text}", user_id)
            if not idx.isdigit() or not (1 <= int(idx) <= len(courses)):
                await editable.edit("**Invalid Selection ❌**")
                return

            course = courses[int(idx) - 1]
            batch_id   = course["_id"]
            batch_name = course.get("name", "Batch")
            clean_name = batch_name.replace("/", "-").replace("|", "-")

            mode = await prompt_user(
                bot, m, editable,
                "**Mode:**\n\n"
                "<blockquote>**1. Full Batch**</blockquote>\n"
                "<blockquote>**2. Today's Classes**</blockquote>",
                user_id,
            )
            if mode not in ("1", "2"):
                await editable.edit("**Invalid ❌**")
                return

            start = time.time()

            if mode == "1":
                await update_status_card(editable, batch_name, 0, 100, start,
                                         "Fetching batch details...")
                det = await pw_fetch(
                    session,
                    f"https://api.penpencil.co/v3/batches/{batch_id}/details",
                    headers=make_pw_headers(token),
                )
                subjects = (det or {}).get("data", {}).get("subjects", [])
                json_data, all_urls = {batch_name: {}}, {}
                zip_path = f"{clean_name}.zip"

                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for i, sub in enumerate(subjects):
                        sn = sub.get("subject", "?")
                        await update_status_card(
                            editable, batch_name, i, len(subjects), start,
                            f"Extracting: `{sn}`")
                        await process_pw_subject(
                            session, sub, batch_id, batch_name,
                            zipf, json_data, all_urls, token)

                await update_status_card(editable, batch_name,
                                          len(subjects), len(subjects), start,
                                          "Writing files...")

                with open(f"{clean_name}.json", "w", encoding="utf-8") as f:
                    json.dump(json_data, f, indent=4)
                with open(f"{clean_name}.txt", "w", encoding="utf-8") as f:
                    for urls in all_urls.values():
                        if urls:
                            f.write("\n".join(urls) + "\n")

            else:
                # today's schedule
                url = (f"https://api.penpencil.co/v1/batches"
                       f"/{batch_id}/todays-schedule")
                data = await pw_fetch(session, url, headers=make_pw_headers(token))
                lines = []
                for item in (data or {}).get("data", []):
                    sub_id = item.get("batchSubjectId")
                    sch_id = item.get("_id")
                    for ct in ["videos", "DppVideos"]:
                        det_url = (
                            f"https://api.penpencil.co/v1/batches/{batch_id}"
                            f"/subject/{sub_id}/schedule/{sch_id}/schedule-details"
                        )
                        det = await pw_fetch(
                            session, det_url, headers=make_pw_headers(token))
                        if det and det.get("data"):
                            v = extract_url_from_video_details(det["data"])
                            if v:
                                lines.append(
                                    f"{det['data'].get('topic','?')}:{v}\n")
                with open(f"{clean_name}.txt", "w") as f:
                    f.writelines(lines)

            caption = (f"**Batch:** `{batch_name}`\n"
                       f"**Time:** `{format_time(time.time()-start)}`")
            await editable.edit("📤 **Uploading...**")

            for ext in ["txt", "zip", "json"]:
                p = f"{clean_name}.{ext}"
                if os.path.exists(p) and os.path.getsize(p) > 0:
                    try:
                        with open(p, "rb") as f:
                            await m.reply_document(f, caption=caption,
                                                    file_name=f"{clean_name}.{ext}")
                    finally:
                        os.remove(p)
                elif os.path.exists(p):
                    os.remove(p)

            await editable.delete()

    except ProcessCancelledException:
        pass
    except Exception as e:
        logging.exception("PW error:")
        await editable.edit(f"**Error:** `{e}`")
    finally:
        if clean_name:
            for ext in ["txt", "zip", "json"]:
                p = f"{clean_name}.{ext}"
                if os.path.exists(p):
                    try: os.remove(p)
                    except: pass


def register_pwwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^pwwp$"))
    async def _(client, cq):
        await cq.answer()
        asyncio.create_task(process_pwwp(client, cq.message, cq.from_user.id))
