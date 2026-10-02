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

from helpers import appx_decrypt, ask_user, is_authorized

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
    full_text = text + cancel_notice
    response = await ask_user(bot, message, editable, full_text, user_id)
    if response is None or response.strip().lower() == "/cancel":
        await editable.edit("**Process Cancelled by User ❌**")
        raise ProcessCancelledException("User requested cancellation.")
    return response.strip()

async def update_status_card(editable: Message, task_name: str, current: int, total: int, start_time: float, activity: str):
    percentage = (current / total * 100) if total > 0 else 0
    elapsed = time.time() - start_time
    
    if current > 0 and total > 0:
        avg_time_per_unit = elapsed / current
        remaining_units = total - current
        eta = avg_time_per_unit * remaining_units
        eta_str = format_time(eta)
    else:
        eta_str = "Calculating..."

    filled_blocks = int(percentage // 10)
    progress_bar = "▓" * filled_blocks + "░" * (10 - filled_blocks)

    status_text = (
        f"<blockquote>⚙️ **Processing Task:** `{task_name}`</blockquote>\n\n"
        f"📊 **Progress:** [{progress_bar}] `{percentage:.1f}%` ({current}/{total})\n"
        f"📌 **Current Activity:** {activity}\n"
        f"⏱️ **Time Elapsed:** `{format_time(elapsed)}`\n"
        f"⏳ **Time Left (ETA):** `{eta_str}`\n\n"
        f"<blockquote>❌ **Send `/cancel` to abort.**</blockquote>"
    )
    try:
        await editable.edit(status_text)
    except Exception:
        pass

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

                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    match = re.search(r'\{"status":', text, re.DOTALL)
                    if match:
                        json_str = text[match.start():]
                        open_brace_count, close_brace_count, json_end = 0, 0, -1
                        for i, char in enumerate(json_str):
                            if char == '{': open_brace_count += 1
                            elif char == '}': close_brace_count += 1
                            if open_brace_count > 0 and open_brace_count == close_brace_count:
                                json_end = i + 1
                                break
                        if json_end != -1:
                            return json.loads(json_str[:json_end])
            except aiohttp.ClientError as e:
                logging.error(f"Appx Attempt {attempt + 1} failed for {url}: {e}")
            except Exception as e:
                logging.exception(f"Appx Unexpected error for {url}: {e}")
            if attempt < 2:
                await asyncio.sleep(1.5 ** attempt)
        return None

def extract_user_id_from_jwt(token: str) -> str:
    try:
        parts = token.split(".")
        if len(parts) == 3:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
            data = json.loads(payload_json)
            return str(data.get("id") or data.get("user_id") or data.get("sub") or "0")
    except Exception as e:
        logging.warning(f"Failed to parse user-id from token: {e}")
    return "0"

def find_appx_matching_apis(search_api: List[str], appxapis_file="threeapis.json") -> List[Dict]:
    matched_apis = []
    try:
        with open(appxapis_file, 'r') as f:
            api_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Error reading appxapis file: {e}")
        return matched_apis

    for item in api_data:
        for term in search_api:
            term = term.strip().lower()
            if term in item["name"].lower() or term in item["api"].lower():
                matched_apis.append(item)

    unique_apis, seen_apis = [], set()
    for item in matched_apis:
        if item["api"] not in seen_apis:
            unique_apis.append(item)
            seen_apis.add(item["api"])
    return unique_apis

async def resolve_api_and_app_name(bot: Client, m: Message, editable: Message, raw_input_text: str, user_id: int):
    raw_input_text = raw_input_text.strip()
    if raw_input_text.startswith(("http://", "https://")):
        clean_url = raw_input_text.replace("https://", "").replace("http://", "").rstrip("/")
        api_url = f"https://{clean_url}"
        return api_url, api_url

    search_terms = [term.strip() for term in raw_input_text.split()]
    matches = find_appx_matching_apis(search_terms)

    if not matches:
        await editable.edit("**No matches found! Enter Correct App Starting Word ❌**")
        return None, None

    # Safe length check to avoid MESSAGE_TOO_LONG
    if len(matches) > 35:
        matches = matches[:35]
        truncated_note = "\n\n⚠️ *Too many matches, showing first 35.*"
    else:
        truncated_note = ""

    text = "".join(f"<blockquote>**{cnt + 1}.** `{item['name']}:{item['api']}`</blockquote>\n" for cnt, item in enumerate(matches))
    selection_text = await prompt_user(bot, m, editable, f"**Select Index Number Of App API:**\n\n{text}{truncated_note}", user_id)

    if selection_text.isdigit() and 1 <= int(selection_text) <= len(matches):
        selected_item = matches[int(selection_text) - 1]
        return selected_item['api'], selected_item['name']
    else:
        await editable.edit("**Error: Wrong Index Number ❌**")
        return None, None

async def login_appx_user(session: aiohttp.ClientSession, bot: Client, m: Message, editable: Message, user_id: int):
    app_input = await prompt_user(bot, m, editable, "**Enter App Name or API URL to login:**", user_id)
    api, app_name = await resolve_api_and_app_name(bot, m, editable, app_input, user_id)
    if not api or not app_name:
        return None, None, None

    mobile = await prompt_user(bot, m, editable, "**Enter Mobile Number:**", user_id)
    password = await prompt_user(bot, m, editable, "**Enter Password:**", user_id)

    await editable.edit("🔑 **Authenticating with Appx servers...**")
    headers = {"Client-Service": "Appx", "Auth-Key": "appxapi", "source": "website", "Content-Type": "application/x-www-form-urlencoded"}
    res = await fetch_appx_html_to_json(session, f"{api}/post/userlogin", headers=headers, data={"email": mobile, "password": password})

    if not res or res.get("status") != 200 or not res.get("data"):
        msg = res.get("message", "Invalid credentials.") if res else "No response."
        await editable.edit(f"**Login Failed! ❌**\n`Reason: {msg}`")
        return None, None, None

    token = res["data"].get("token") or res["data"].get("jwt_token") or res["data"].get("user_token")
    if not token:
        await editable.edit("**Login successful, but token missing! ❌**")
        return None, None, None

    await bot.send_message(chat_id=m.chat.id, text=f"🔑 **Token Generated:**\n`{token}`")
    return api, token, app_name

async def fetch_appx_video_id_details_v2(session: aiohttp.ClientSession, api: str, selected_batch_id: str, video_id: str, ytFlag: str, headers: Dict, folder_wise_course: Any, user_id: int) -> List[str]:
    try:
        headers_noauth = {k: v for k, v in headers.items() if k.lower() not in ('authorization', 'user-id')}
        res = await fetch_appx_html_to_json(session, f"{api}/get/fetchVideoDetailsById?course_id={selected_batch_id}&folder_wise_course={folder_wise_course}&ytflag={ytFlag}&video_id={video_id}", headers)
        if not res or res.get('status') != 200:
            res = await fetch_appx_html_to_json(session, f"{api}/get/fetchVideoDetailsById?course_id={selected_batch_id}&folder_wise_course={folder_wise_course}&ytflag={ytFlag}&video_id={video_id}", headers_noauth)

        output = []
        if res and res.get('data'):
            data = res.get('data')
            Title = data.get("Title", f"Video {video_id}")
            direct_video_url = data.get('video_url') or data.get('videoUrl') or data.get('hls_url') or data.get('hlsUrl') or data.get('stream_url') or data.get('media_url') or data.get('url') or ""
            
            if direct_video_url:
                output.append(f"{Title}:{direct_video_url}\n")
            else:
                res_drm = await fetch_appx_html_to_json(session, f"{api}/get/get_mpd_drm_links?videoid={video_id}&folder_wise_course={folder_wise_course}", headers)
                if not res_drm or res_drm.get('status') != 200:
                    res_drm = await fetch_appx_html_to_json(session, f"{api}/get/get_mpd_drm_links?videoid={video_id}&folder_wise_course={folder_wise_course}", headers_noauth)
                if res_drm and res_drm.get('data'):
                    for item in res_drm.get('data', []):
                        val = item.get("path") or item.get("url")
                        if val:
                            try:
                                decrypted = appx_decrypt(val)
                                if decrypted and decrypted.startswith('http'):
                                    output.append(f"{Title}:{decrypted}\n")
                                    break
                            except Exception:
                                pass

            pdf_link = appx_decrypt(data.get("pdf_link", "")) if data.get("pdf_link", "") and appx_decrypt(data.get("pdf_link", "")).endswith(".pdf") else None
            if pdf_link:
                key = appx_decrypt(data.get("pdf_encryption_key", "")) if data.get("is_pdf_encrypted") == "1" else None
                output.append(f"{Title}:{pdf_link}*{key}\n" if key else f"{Title}:{pdf_link}\n")
        return output
    except Exception as e:
        return [f"Error: {e}\n"]

async def fetch_appx_folder_contents_v2(session: aiohttp.ClientSession, api: str, selected_batch_id: str, folder_id: str, headers: Dict, folder_wise_course: Any, user_id: int) -> List[str]:
    try:
        res = await fetch_appx_html_to_json(session, f"{api}/get/folder_contentsv2?course_id={selected_batch_id}&parent_id={folder_id}", headers)
        tasks, output = [], []
        if res and "data" in res:
            for item in res["data"]:
                if item.get("material_type") == "VIDEO":
                    tasks.append(fetch_appx_video_id_details_v2(session, api, selected_batch_id, item.get("id"), item.get("ytFlag"), headers, folder_wise_course, user_id))
                elif item.get("material_type") == "FOLDER":
                    tasks.append(fetch_appx_folder_contents_v2(session, api, selected_batch_id, item.get("id"), headers, folder_wise_course, user_id))
        if tasks:
            for r in await asyncio.gather(*tasks):
                output.extend(r)
        return output
    except Exception as e:
        return [f"Error: {e}\n"]

async def process_folder_wise_course_0(session: aiohttp.ClientSession, api: str, selected_batch_id: str, headers: Dict, user_id: int) -> List[str]:
    res = await fetch_appx_html_to_json(session, f"{api}/get/allsubjectfrmlivecourseclass?courseid={selected_batch_id}&start=-1", headers)
    all_outputs = []
    if res and "data" in res:
        for subject in res["data"]:
            res2 = await fetch_appx_html_to_json(session, f"{api}/get/alltopicfrmlivecourseclass?courseid={selected_batch_id}&subjectid={subject.get('subjectid')}&start=-1", headers)
            if res2 and "data" in res2:
                for topic in res2["data"]:
                    res3 = await fetch_appx_html_to_json(session, f"{api}/get/livecourseclassbycoursesubtopconceptapiv3?topicid={topic.get('topicid')}&start=-1&courseid={selected_batch_id}&subjectid={subject.get('subjectid')}", headers)
                    if res3 and "data" in res3:
                        for item in res3["data"]:
                            Title = item.get("Title")
                            if item.get("material_type") in ("PDF", "TEST"):
                                pl = appx_decrypt(item.get("pdf_link", "")) if item.get("pdf_link", "") else None
                                if pl and pl.endswith(".pdf"):
                                    all_outputs.append(f"{Title}:{pl}\n")
                            elif item.get("material_type") == "VIDEO":
                                v_url = item.get('video_url') or item.get('url')
                                if v_url and v_url.startswith("http"):
                                    all_outputs.append(f"{Title}:{v_url}\n")
    return all_outputs

async def process_folder_wise_course_1(session: aiohttp.ClientSession, api: str, selected_batch_id: str, headers: Dict, user_id: int) -> List[str]:
    res = await fetch_appx_html_to_json(session, f"{api}/get/folder_contentsv2?course_id={selected_batch_id}&parent_id=-1", headers)
    all_outputs = []
    if res and "data" in res:
        for item in res["data"]:
            if item.get("material_type") == "PDF":
                pl = appx_decrypt(item.get("pdf_link", ""))
                if pl and pl.endswith(".pdf"):
                    all_outputs.append(f"{item.get('Title')}:{pl}\n")
    return all_outputs

async def process_appxwp(bot: Client, m: Message, user_id: int):
    editable = await m.reply_text("**Wait initializing process... ⏳**")
    clean_file_name = None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            auth_prompt = "**Select Appx Authentication Option:**\n\n**1. 🔑 Login with Credentials**\n**2. 🎫 Enter JWT/Access Token**"
            auth_mode = await prompt_user(bot, m, editable, auth_prompt, user_id)

            api, token, selected_app_name = None, None, None
            if auth_mode == "1":
                api, token, selected_app_name = await login_appx_user(session, bot, m, editable, user_id)
                if not api or not token: return
            else:
                first_input = await prompt_user(bot, m, editable, "**Enter App Name, API Url, or JWT Token:**", user_id)
                if first_input.count('.') == 2 and len(first_input) > 100:
                    token = first_input
                    second_input = await prompt_user(bot, m, editable, "**Now enter App Name or API URL:**", user_id)
                    api, selected_app_name = await resolve_api_and_app_name(bot, m, editable, second_input, user_id)
                else:
                    api, selected_app_name = await resolve_api_and_app_name(bot, m, editable, first_input, user_id)

            if not api or not selected_app_name: return

            extracted_jwt_userid = extract_user_id_from_jwt(token) if token else "0"
            headers = {"Client-Service": "Appx", "Auth-Key": "appxapi", "source": "website"}
            if token:
                headers['Authorization'] = token
                headers['User-ID'] = extracted_jwt_userid

            await editable.edit("**Fetching Available Courses... 🔍**")
            res1 = await fetch_appx_html_to_json(session, f"{api}/get/courselist", headers)
            res2 = await fetch_appx_html_to_json(session, f"{api}/get/courselistnewv2", headers)
            courses = (res1.get("data", []) if res1 else []) + (res2.get("data", []) if res2 else [])

            if not courses:
                await editable.edit("**Did not find any course! ❌**")
                return

            # Safe length check to avoid MESSAGE_TOO_LONG for courses list
            total_courses = len(courses)
            if total_courses > 35:
                courses_display = courses[:35]
                truncated_note = f"\n\n⚠️ *Showing first 35 courses out of {total_courses}.*"
            else:
                courses_display = courses
                truncated_note = ""

            text = "".join(f"<blockquote>**{cnt + 1}.** `{c.get('course_name', 'Course')} 💵₹{c.get('price', '0')}`</blockquote>\n" for cnt, c in enumerate(courses_display))
            selection_course = await prompt_user(bot, m, editable, f"**Send index number of the course:**\n\n{text}{truncated_note}", user_id)

            if selection_course.isdigit() and 1 <= int(selection_course) <= len(courses_display):
                course = courses_display[int(selection_course) - 1]
                selected_batch_id, selected_batch_name = course['id'], course.get('course_name', 'Batch')
                clean_file_name = f"{user_id}_{selected_batch_name.replace('/', '-')[:200]}"
            else:
                await editable.edit("**Invalid Selection Index! ❌**")
                return

            start_time = time.time()
            all_outputs = await process_folder_wise_course_0(session, api, selected_batch_id, headers, user_id)
            if not all_outputs:
                all_outputs = await process_folder_wise_course_1(session, api, selected_batch_id, headers, user_id)

            if all_outputs:
                output_txt_path = f"{clean_file_name}.txt"
                with open(output_txt_path, 'w', encoding='utf-8') as f:
                    f.writelines(all_outputs)

                caption = f"**App:** `{selected_app_name}`\n**Batch:** `{selected_batch_name}`"
                with open(output_txt_path, "rb") as doc:
                    await m.reply_document(doc, caption=caption, file_name=f"{selected_batch_name}.txt")
                await editable.delete()
                os.remove(output_txt_path)
            else:
                await editable.edit("**Didn't Find Any Content In The Course! ❌**")
    except ProcessCancelledException:
        pass
    except Exception as e:
        logging.exception("Error in process_appxwp:")
        await editable.edit(f"**Error : {e}**")

def register_appxwp_handlers(bot: Client):
    @bot.on_callback_query(filters.regex("^appxwp$"))
    async def appxwp_callback(client: Client, callback_query):
        await callback_query.answer()
        asyncio.create_task(process_appxwp(client, callback_query.message, callback_query.from_user.id))
