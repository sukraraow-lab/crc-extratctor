import os
import asyncio
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

try:
    from helpers import ask_user
except ImportError:
    async def ask_user(*args, **kwargs):
        return None

async def download_file(url: str, save_path: str) -> bool:
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, timeout=300) as resp:
                if resp.status == 200:
                    with open(save_path, "wb") as f:
                        while True:
                            chunk = await resp.content.read(1024 * 64)
                            if not chunk: break
                            f.write(chunk)
                    return True
    except Exception as e:
        logging.error(f"Download failed: {e}")
    return False

async def process_leech_file(client: Client, message: Message, file_path: str, target_chat_id: int):
    status_msg = await message.reply_text("📥 **Reading `.txt` file and starting leeching...**")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        total_links = len(lines)
        if total_links == 0:
            await status_msg.edit("⚠️ **Text file is empty!**")
            return

        success, fail = 0, 0
        for idx, line in enumerate(lines, 1):
            line = line.strip()
            if not line or ":" not in line: continue
            
            parts = line.split(":", 1)
            title, url_part = parts[0].strip(), parts[1].strip()
            
            key = None
            if "*" in url_part:
                url_part, key = url_part.split("*", 1)
                
            url = url_part.strip()
            if not url.startswith("http"): continue

            is_video = any(ext in url.lower() for ext in ['.mp4', '.m3u8', '.mpd', 'video'])
            ext = ".mp4" if is_video else ".pdf"
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            local_filename = f"{safe_title}{ext}"

            await status_msg.edit(f"📤 **Leeching:** `{idx}/{total_links}`\n📌 `{safe_title}`")

            if await download_file(url, local_filename):
                try:
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

        await status_msg.edit(f"✅ **Leech Completed!**\nSuccess: `{success}` | Failed: `{fail}`")
    except Exception as e:
        logging.exception("Error in leech:")
        await status_msg.edit(f"❌ **Error:** `{e}`")
    finally:
        if os.path.exists(file_path): os.remove(file_path)

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
                await editable.edit("**Cancelled ❌**")
                return
            
            target_chat_id = int(target_chat_input.strip())
            file_path = await message.download()
            asyncio.create_task(process_leech_file(client, message, file_path, target_chat_id))
        except Exception as e:
            logging.error(f"Error: {e}")
