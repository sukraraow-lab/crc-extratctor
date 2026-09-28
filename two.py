# BUG 1: api-version header — ClassPlus silently returns empty on wrong version
# OLD: "api-version": "35"  → returns 200 but empty data
# NEW: "api-version": "52"  for OTP flow, "22" for content (was correct for content)

# BUG 2: OTP generate endpoint payload — orgId type must be int, was sometimes str
# FIX: always cast int(org_id)

# BUG 3: org lookup URL
# OLD: /v2/orgs/{org_code}  — deprecated, returns 404 on new orgs
# NEW: /v2/orgs/code/{org_code}

# BUG 4: OTP verify — sessionId field missing causes silent failure
# FIX: include sessionId from otp generate response

# BUG 5: hash extraction regex — site structure changed
# OLD: r'["\']hash["\']\s*:\s*["\']([^"\']+)["\']'
# NEW: try multiple patterns + fallback to meta tag

import asyncio
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from helpers import ask_user, is_authorized


class ProcessCancelledException(Exception):
    pass


def format_time(s):
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


async def update_status_card(editable, task, cur, tot, start, activity):
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


SEMAPHORE = asyncio.Semaphore(10)

CP_HEADERS = {
    "accept-encoding": "gzip",
    "accept-language": "EN",
    "api-version": "52",           # FIX: was 35
    "app-version": "1.4.71.1",
    "build-number": "52",          # FIX: match api-version
    "connection": "Keep-Alive",
    "content-type": "application/json",
    "device-details": "Xiaomi_Redmi 7_SDK-32",
    "device-id": "cc4473819ba3ee7f51f560f801574304",
    "host": "api.classplusapp.com",
    "region": "IN",
    "user-agent": "Mobile-Android",
    "webengage-luid": "00000187-6fe4-5d41-a530-26186858be4c",
}


def cp_headers(token: str = None, api_ver: str = "52") -> dict:
    h = dict(CP_HEADERS)
    h["api-version"]  = api_ver
    h["build-number"] = api_ver
    if token:
        h["x-access-token"] = token
    return h


def extract_hash_from_html(html: str) -> Optional[str]:
    """Try multiple patterns — site structure changed."""
    patterns = [
        r'["\']hash["\']\s*:\s*["\']([a-zA-Z0-9_\-]{20,})["\']',
        r'"hash"\s*:\s*"([a-zA-Z0-9_\-]{20,})"',
        r"'hash'\s*:\s*'([a-zA-Z0-9_\-]{20,})'",
        r'data-hash=["\']([a-zA-Z0-9_\-]{20,})["\']',
        r'HASH["\s:=]+["\']([a-zA-Z0-9_\-]{20,})["\']',
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            return m.group(1)
    return None


async def fetch_signed_url(url_val, name, session, headers):
    async with SEMAPHORE:
        try:
            async with session.get(
                "https://api.classplusapp.com/cams/uploader/video/jw-signed-url",
                params={"url": url_val},
                headers=headers,
            ) as resp:
                if resp.status == 200:
                    d = await resp.json()
                    return d.get("url") or d.get("drmUrls", {}).get("manifestUrl")
        except Exception as e:
            logging.error(f"signed url error {name}: {e}")
    return None


async def process_cp_url(url_val, name, session, headers):
    try:
        signed = await fetch_signed_url(url_val, name, session, headers)
        if not signed:
            return None
        if ("testbook.com" in url_val or "classplusapp.com/drm" in url_val
                or "media-cdn.classplusapp.com/drm" in url_val):
            return f"{name}:{url_val}\n"
        async with SEMAPHORE:
            async with session.get(signed) as r:
                r.raise_for_status()
                return f"{name}:{signed}\n"
    except Exception:
        return None


async def get_course_content(session, headers, batch_token, editable,
                              start_time, folder_id=0, retry=0, stats=None):
    if stats is None:
        stats = {"processed": 0, "total": 1}
    fetched, results = set(), []
    v_count = p_count = i_count = 0
    content_tasks, folder_tasks = [], []

    try:
        async with SEMAPHORE:
            async with session.get(
                f"https://api.classplusapp.com/v2/course/preview/content/list/{batch_token}",
                params={"folderId": folder_id, "limit": 9999999999},
                headers=headers,
            ) as res:
                res.raise_for_status()
                contents = (await res.json()).get("data", [])

        stats["total"] += len(contents)
        for item in contents:
            stats["processed"] += 1
            if stats["processed"] % 5 == 0:
                await update_status_card(
                    editable, "Scanning", stats["processed"], stats["total"],
                    start_time, f"Scanning: `{item.get('name','?')[:30]}`")

            if item.get("contentType") == 1:
                folder_tasks.append((
                    item["id"],
                    asyncio.create_task(get_course_content(
                        session, headers, batch_token, editable,
                        start_time, folder_id=item["id"], stats=stats))
                ))
                continue

            name    = item.get("name", "")
            url_val = item.get("url") or item.get("thumbnailUrl")
            if not url_val:
                continue

            # URL pattern fixes (identical to VJ original — these are correct)
            if "media-cdn.classplusapp.com/tencent/" in url_val:
                url_val = url_val.rsplit("/", 1)[0] + "/master.m3u8"
            elif "media-cdn.classplusapp.com" in url_val and url_val.endswith(".jpg"):
                identifier = url_val.split("/")[-3]
                url_val = (f"https://media-cdn.classplusapp.com/"
                           f"alisg-cdn-a.classplusapp.com/{identifier}/master.m3u8")
            elif "tencdn.classplusapp.com" in url_val and url_val.endswith(".jpg"):
                identifier = url_val.split("/")[-2]
                url_val = (f"https://media-cdn.classplusapp.com/"
                           f"tencent/{identifier}/master.m3u8")
            elif ("cpvideocdn.testbook.com" in url_val and url_val.endswith(".png")):
                match = re.search(r"/streams/([a-f0-9]{24})/", url_val)
                vid = match.group(1) if match else url_val.split("/")[-2]
                url_val = f"https://cpvod.testbook.com/{vid}/playlist.m3u8"
            elif ("media-cdn.classplusapp.com/drm/" in url_val
                  and url_val.endswith(".png")):
                vid = url_val.split("/")[-3]
                url_val = f"https://media-cdn.classplusapp.com/drm/{vid}/playlist.m3u8"
            elif ("https://media-cdn.classplusapp.com" in url_val
                  and any(x in url_val for x in ("cc/", "lc/", "uc/", "dy/"))
                  and url_val.endswith(".png")):
                url_val = url_val.replace("thumbnail.png", "master.m3u8")
            elif ("https://tb-video.classplusapp.com" in url_val
                  and url_val.endswith(".jpg")):
                vid = url_val.split("/")[-1].split(".")[0]
                url_val = f"https://tb-video.classplusapp.com/{vid}/master.m3u8"

            if url_val.endswith(("master.m3u8", "playlist.m3u8")) \
                    and url_val not in fetched:
                fetched.add(url_val)
                content_tasks.append(
                    asyncio.create_task(
                        process_cp_url(url_val, name, session, headers)))
            else:
                u = item.get("url")
                if u:
                    fetched.add(u)
                    results.append(f"{name}:{u}\n")
                    if u.endswith(".pdf"):
                        p_count += 1
                    else:
                        i_count += 1

    except Exception as e:
        if retry < 3:
            await asyncio.sleep(2 ** retry)
            return await get_course_content(
                session, headers, batch_token, editable,
                start_time, folder_id, retry + 1, stats)
        return [], 0, 0, 0

    for r in await asyncio.gather(*content_tasks, return_exceptions=True):
        if isinstance(r, Exception) or not r:
            continue
        results.append(r)
        v_count += 1

    for _, ft in folder_tasks:
        try:
            nr, nv, np, ni = await ft
            results.extend(nr)
            v_count += nv
            p_count += np
            i_count += ni
        except Exception as e:
            logging.error(f"folder task error: {e}")

    return results, v_count, p_count, i_count


async def process_cpwp(bot, m, user_id):
    connector = aiohttp.TCPConnector(limit=1000)
    async with aiohttp.ClientSession(connector=connector) as session:
        editable = file_path = None
        try:
            editable = await m.reply_text("**Processing ClassPlus... ⏳**")

            org_code = (await prompt_user(
                bot, m, editable,
                "**Enter ORG Code of your ClassPlus app:**\n"
                "<blockquote>Example: `allen`, `pwallenclasses`, `vedantu`</blockquote>",
                user_id,
            )).lower().strip()

            raw = await prompt_user(
                bot, m, editable,
                "**Enter Access Token OR 10-digit Mobile Number:**",
                user_id,
            )

            token = None

            if raw.isdigit() and len(raw) == 10:
                # FIX: org lookup endpoint
                await editable.edit("**Fetching org info... ⏳**")
                async with session.get(
                    f"https://api.classplusapp.com/v2/orgs/code/{org_code}",  # FIX
                    headers=cp_headers(),
                ) as r:
                    if r.status != 200:
                        # fallback to old endpoint
                        async with session.get(
                            f"https://api.classplusapp.com/v2/orgs/{org_code}",
                            headers=cp_headers(),
                        ) as r2:
                            if r2.status != 200:
                                await editable.edit("**Invalid Org Code ❌**")
                                return
                            org_data = await r2.json()
                    else:
                        org_data = await r.json()

                org_id = (org_data.get("data", {}).get("orgId")
                          or org_data.get("data", {}).get("id"))
                if not org_id:
                    await editable.edit("**Could not resolve Org ID ❌**")
                    return

                await editable.edit("**Sending OTP... ⏳**")
                otp_payload = {
                    "countryExt": "91",
                    "mobile": raw,
                    "orgId": int(org_id),      # FIX: must be int
                    "orgCode": org_code,
                }
                async with session.post(
                    "https://api.classplusapp.com/v2/otp/generate",
                    json=otp_payload,
                    headers=cp_headers(api_ver="52"),
                ) as r:
                    if r.status != 200:
                        await editable.edit(
                            f"**OTP Send Failed ❌**\n`{await r.text()}`")
                        return
                    otp_data   = await r.json()
                    session_id = otp_data.get("data", {}).get("sessionId", "")

                otp = await prompt_user(bot, m, editable,
                                        "**Enter OTP received on phone:**", user_id)

                await editable.edit("**Verifying OTP... ⏳**")
                verify_payload = {
                    "otp": otp.strip(),
                    "countryExt": "91",
                    "sessionId": str(session_id),   # FIX: required field
                    "orgId": int(org_id),
                    "fingerprintId": CP_HEADERS["device-id"],
                    "mobile": raw,
                }
                async with session.post(
                    "https://api.classplusapp.com/v2/users/verify",
                    json=verify_payload,
                    headers=cp_headers(api_ver="52"),
                ) as r:
                    vj = await r.json()
                    if r.status != 200 or vj.get("status") == "failure":
                        await editable.edit(
                            f"**Verify Failed ❌**\n`{vj.get('message','?')}`")
                        return
                    token = (vj.get("data", {}).get("token")
                             or vj.get("data", {}).get("user", {}).get("token")
                             or vj.get("token"))
                    if not token:
                        await editable.edit("**Token not found in response ❌**")
                        return
                    await editable.edit(
                        f"**✅ ClassPlus Login Success!**\n\n`{token}`\n\n"
                        "<blockquote>Save this token for future use.</blockquote>")
                    editable = await m.reply_text("**Processing...**")
            else:
                token = raw

            # get hash
            hash_headers = {
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"https://{org_code}.courses.store/?mainCategory=0",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
                ),
            }
            async with session.get(
                f"https://{org_code}.courses.store", headers=hash_headers
            ) as r:
                html = await r.text()

            # FIX: multi-pattern hash extraction
            h = extract_hash_from_html(html)
            if not h:
                await editable.edit("**No App Found For Org Code ❌**")
                return

            # fetch courses
            async with session.get(
                f"https://api.classplusapp.com/v2/course/preview/similar/{h}?limit=20",
                headers=cp_headers(token, api_ver="22"),
            ) as r:
                if r.status != 200:
                    await editable.edit(f"**Course Fetch Error ❌**\n`{await r.text()}`")
                    return
                courses = (await r.json()).get("data", {}).get("coursesData", [])

            if not courses:
                await editable.edit("**No courses found ❌**")
                return

            text = "".join(
                f"<blockquote>**{i+1}.** `{c['name']} ₹{c.get('finalPrice',0)}`</blockquote>\n"
                for i, c in enumerate(courses)
            )
            choice = await prompt_user(
                bot, m, editable,
                f"**Select course index OR enter name to search:**\n\n{text}",
                user_id,
            )

            if choice.isdigit() and 1 <= int(choice) <= len(courses):
                course = courses[int(choice) - 1]
            else:
                async with session.get(
                    f"https://api.classplusapp.com/v2/course/preview/similar"
                    f"/{h}?search={choice}",
                    headers=cp_headers(token, api_ver="22"),
                ) as r:
                    sc = (await r.json()).get("data", {}).get("coursesData", [])
                if not sc:
                    await editable.edit("**No course matches search ❌**")
                    return
                text2 = "".join(
                    f"<blockquote>**{i+1}.** `{c['name']} ₹{c.get('finalPrice',0)}`</blockquote>\n"
                    for i, c in enumerate(sc)
                )
                idx2 = await prompt_user(bot, m, editable,
                                          f"**Select:**\n\n{text2}", user_id)
                if not idx2.isdigit() or not (1 <= int(idx2) <= len(sc)):
                    await editable.edit("**Invalid ❌**")
                    return
                course = sc[int(idx2) - 1]

            cid   = course["id"]
            cname = course["name"]
            clean = re.sub(r'[\\/*?:"<>|]', "-", cname)
            file_path = f"{clean}.txt"

            async with session.get(
                "https://api.classplusapp.com/v2/course/preview/org/info",
                params={"courseId": cid},
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "region": "IN",
                    "accept-language": "EN",
                    "Api-Version": "22",
                    "x-access-token": token,
                    "tutorWebsiteDomain": f"https://{org_code}.courses.store",
                },
            ) as r:
                if r.status != 200:
                    await editable.edit(f"**Info Error ❌**\n`{await r.text()}`")
                    return
                info     = await r.json()
                bt       = info["data"]["hash"]
                app_name = info["data"]["name"]

            start = time.time()
            content, vc, pc, ic = await get_course_content(
                session, cp_headers(token, api_ver="22"), bt, editable, start)

            if not content:
                await editable.edit("**No content found ❌**")
                return

            with open(file_path, "w", encoding="utf-8") as f:
                f.write("".join(content))

            await editable.delete()
            cap = (f"**App:** `{app_name} ({org_code})`\n"
                   f"**Batch:** `{cname}`\n"
                   f"🎬 `{vc}` | 📁 `{pc}` | 🖼 `{ic}`\n"
                   f"**Time:** `{format_time(time.time()-start)}`")
            with open(file_path, "rb") as f:
                await m.reply_document(f, caption=cap, file_name=f"{clean}.txt")

        except ProcessCancelledException:
            pass
        except Exception as e:
            logging.exception("CP error:")
            if editable:
                await editable.edit(f"**Error:** `{e}`")
        finally:
            if file_path and os.path.exists(file_path):
                try: os.remove(file_path)
                except: pass


def register_cpwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^cpwp$"))
    async def _(client, cq):
        await cq.answer()
        asyncio.create_task(process_cpwp(client, cq.message, cq.from_user.id))
