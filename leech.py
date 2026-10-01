import os
import asyncio
import logging
import aiohttp
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

try:
    from helpers import ask_user
except ImportError:
    async def ask_user(*args, **kwargs):
        return None

LEECH_STATES = {}

async def download_file(url: str, save_path: str, status_msg: Message, title: str, idx: int, total_links: int, user_id: int) -> bool:
    """Handles both direct files (PDF/MP4) and streaming playlists (.m3u8 / .mpd via yt-dlp with SSL bypass)."""
    try:
        is_stream = any(ext in url.lower() for ext in ['.m3u8', '.mpd', 'playlist'])
        
        if is_stream:
            # yt-dlp options with nocheckcertificate to bypass expired SSL errors
            ydl_opts = {
                'outtmpl': save_path.replace('.mp4', ''),
                'format': 'best',
                'nopart': True,
                'quiet': True,
                'nocheckcertificate': True,  # Fixes certificate has expired error
            }
            if not save_path.endswith('.mp4'):
                ydl_opts['outtmpl'] = save_path + '.%(ext)s'

            await status_msg.edit(
                f"📥 **Downloading Stream (HLS/DASH):** `{idx}/{total_links}`\n"
                f"📌 **Title:** `{title}`\n"
                f"⏳ *Processing stream via yt-dlp...*",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏸️️ Pause", callback_data="leech_pause"),
                     InlineKeyboardButton("⏹️ Stop", callback_data="leech_stop")]
                ])
            )

            def run_ytdl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

            await asyncio.to_thread(run_ytdl)
            
            base_path = save_path.rsplit('.', 1)[0]
            for ext in ['.mp4', '.mkv', '.webm', '.ts']:
                full_p = base_path + ext
                if os.path.exists(full_p) and os.path.getsize(full_p) > 0:
                    if full_p != save_path:
                        os.rename(full_p, save_path)
                    return True
            return False

        else:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, timeout=300) as resp:
                    if resp.status == 200:
                        total_size = int(resp.headers.get("Content-Length", 0))
                        downloaded = 0
                        with open(save_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(1024 * 64):
                                if LEECH_STATES.get(user_id, {}).get("stopped"):
                                    return False
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    percent = (downloaded / total_size) * 100
                                    filled = int(percent // 10)
                                    bar = "▓" * filled + "░" * (10 - filled)
                                    mb_done = downloaded / (1024 * 1024)
                                    mb_total = total_size / (1024 * 1024)
                                    try:
                                        is_paused = LEECH_STATES.get(user_id, {}).get("paused", False)
                                        pause_btn_text = "▶️ Resume" if is_paused else "⏸ Pause"
                                        pause_callback = "leech_resume" if is_paused else "leech_pause"

                                        await status_msg.edit(
                                            f"📤 **Leeching:** `{idx}/{total_links}`\n"
                                            f"📌 **Title:** `{title}`\n"
                                            f"📊 **Downloading:** [{bar}] `{percent:.1f}%`\n"
                                            f"📦 `{mb_done:.1f} MB / {mb_total:.1f} MB`",
                                            reply_markup=InlineKeyboardMarkup([
                                                [InlineKeyboardButton(pause_btn_text, callback_data=pause_callback),
                                                 InlineKeyboardButton("⏹️ Stop", callback_data="leech_stop")]
                                            ])
                                        )
                                    except Exception:
                                        pass
                        return True
    except Exception as e:
        logging.error(f"Download failed for {url}: {e}")
    return False

async def process_leech_file(client: Client, message: Message, file_path: str, target_chat_id: int, user_id: int):
    LEECH_STATES[user_id] = {"paused": False, "stopped": False}
    
    status_msg = await message.reply_text(
        "📥 **Reading `.txt` file and starting leeching...**",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸️ Pause", callback_data="leech_pause"),
             InlineKeyboardButton("⏹️ Stop", callback_data="leech_stop")]
        ])
    )
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        total_links = len(lines)
        if total_links == 0:
            await status_msg.edit("⚠️ **Text file is empty!**")
            return

        success, fail = 0, 0
        for idx, line in enumerate(lines, 1):
            state = LEECH_STATES.get(user_id, {"paused": False, "stopped": False})
            if state.get("stopped"):
                await status_msg.edit("❌ **Leech Task Stopped Successfully!**", reply_markup=None)
                break

            while state.get("paused") and not state.get("stopped"):
                await asyncio.sleep(1)
                state = LEECH_STATES.get(user_id, {"paused": False, "stopped": False})
                if state.get("stopped"):
                    break

            if LEECH_STATES.get(user_id, {}).get("stopped"):
                await status_msg.edit("❌ **Leech Task Stopped Successfully!**", reply_markup=None)
                break

            line = line.strip()
            if not line or ":" not in line: continue
            
            parts = line.split(":", 1)
            title, url_part = parts[0].strip(), parts[1].strip()
            
            key = None
            if "*" in url_part:
                url_part, key = url_part.split("*", 1)
                
            url = url_part.strip()
            if not url.startswith("http"): continue

            is_video = any(ext in url.lower() for ext in ['.mp4', '.m3u8', '.mpd', 'video', 'playlist'])
            ext = ".mp4" if is_video else ".pdf"
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            local_filename = f"{safe_title}{ext}"

            downloaded_ok = await download_file(url, local_filename, status_msg, title, idx, total_links, user_id)
            if LEECH_STATES.get(user_id, {}).get("stopped"):
                if os.path.exists(local_filename): os.remove(local_filename)
                await status_msg.edit("❌ **Leech Task Stopped Successfully!**", reply_markup=None)
                break

            if downloaded_ok and os.path.exists(local_filename) and os.path.getsize(local_filename) > 0:
                try:
                    await status_msg.edit(
                        f"📤 **Leeching:** `{idx}/{total_links}`\n"
                        f"📌 **Title:** `{title}`\n"
                        f"📤 **Status:** Uploading to Telegram group...",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⏸️ Pause", callback_data="leech_pause"),
                             InlineKeyboardButton("⏹️️ Stop", callback_data="leech_stop")]
                        ])
                    )
                    caption = f"📁 **Title:** `{title}`" + (f"\n🔑 **Key:** `{key}`" if key else "")
                    if is_video:
                        await client.send_video(chat_id=target_chat_id, video=local_filename, caption=caption, supports_streaming=True)
                    else:
                        await client.send_document(chat_id=target_chat_id, document=local_filename, caption=caption)
                    success += 1
                except Exception as up_err:
                    logging.error(f"Upload failed: {up_err}")
                    fail += 1
                finally:
                    if os.path.exists(local_filename): os.remove(local_filename)
            else:
                fail += 1
            await asyncio.sleep(2)

        if not LEECH_STATES.get(user_id, {}).get("stopped"):
            await status_msg.edit(f"✅ **Leech Completed!**\nSuccess: `{success}` | Failed: `{fail}`", reply_markup=None)
            
    except Exception as e:
        logging.exception("Error in leech:")
        await status_msg.edit(f"❌ **Error:** `{e}`")
    finally:
        if user_id in LEECH_STATES:
            del LEECH_STATES[user_id]
        if os.path.exists(file_path):
            os.remove(file_path)

def register_leech_handlers(bot: Client):
    @bot.on_message(filters.document & filters.private)
    async def handle_document_upload(client: Client, message: Message):
        if not message.document.file_name.endswith(".txt"):
            return
            
        editable = await message.reply_text("📥 **Text file detected!**")
        user_id = message.from_user.id
        
        try:
            target_chat_input = await ask_user(
                client, message, editable,
                "**Enter Group ID or Channel ID where files should be uploaded (e.g. `-1001234567890`):**",
                user_id
            )
            if not target_chat_input or target_chat_input.strip().lower() == "/cancel":
                await editable.test("**Cancelled ❌**") # Keep code robust
                return
            
            target_chat_id = int(target_chat_input.strip())
            file_path = await message.download()
            asyncio.create_task(process_leech_file(client, message, file_path, target_chat_id, user_id))
        except Exception as e:
            logging.error(f"Error: {e}")

    @bot.on_callback_query(filters.regex("^leech_pause$"))
    async def pause_leech_callback(client: Client, callback_query: CallbackQuery):
        user_id = callback_query.from_user.id
        if user_id in LEECH_STATES:
            LEECH_STATES[user_id]["paused"] = True
            await callback_query.answer("⏸️ Leech process paused!")
        else:
            await callback_query.answer("No active leech task found.", show_alert=True)

    @bot.on_callback_query(filters.regex("^leech_resume$"))
    async def resume_leech_callback(client: Client, callback_query: CallbackQuery):
        user_id = callback_query.from_user.id
        if user_id in LEECH_STATES:
            LEECH_STATES[user_id]["paused"] = False
            await callback_query.answer("▶️ Leech process resumed!")
        else:
            await callback_query.answer("No active leech task found.", show_alert=True)

    @bot.on_callback_query(filters.regex("^leech_stop$"))
    async def stop_leech_callback(client: Client, callback_query: CallbackQuery):
        user_id = callback_query.from_user.id
        if user_id in LEECH_STATES:
            LEECH_STATES[user_id]["stopped"] = True
            LEECH_STATES[user_id]["paused"] = False
            await callback_query.answer("⏹️ Leech process stopped!")
        else:
            await callback_query.answer("No active leech task found.", show_alert=True)
            except Exception as up_err:
                    logging.error(f"Upload failed: {up_err}")
                    try:
                        await status_msg.edit(f"❌ **Upload Failed:** `{up_err}`")
                        await asyncio.sleep(3)
                    except Exception:
                        pass
                    fail += 1
