import os
import traceback
import asyncio
import yt_dlp
from pyrogram import Client, filters

# 1. Render Environment Variables se values uthana
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))  # Aapke target channel ki ID (-100xxxxxxxxx)

if not API_ID or not API_HASH or not SESSION_STRING or not CHANNEL_ID:
    print("❌ Error: Missing environment variables in Render!")

# Pyrogram Client Initialize karna
app = Client(
    "unified_leech_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# 2. Extractor / Link Processing Logic (Yahan aap apne extractor ka logic rakh sakte hain)
def extract_links_from_txt(file_path):
    """
    Yeh function .txt file ko read karta hai aur valid links nikal kar list banata hai.
    Agar aapke paas ClassX ka koi apna custom extractor function hai, toh aap use yahan jod sakte hain.
    """
    links = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Comments (#) ya khaali lines ko chhod kar links uthayega
            if line and not line.startswith("#"):
                links.append(line)
    return links

# 3. Download, Upload & Error Reporting Function
async def process_single_link(client, link, target_channel):
    file_path = None
    try:
        print(f"\n🔄 [PROCESSING] Link: {link}")
        
        # yt-dlp options (RAM optimization ke sath)
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'format': 'best[height<=720]',
            'nopart': True,
            'nocheckcertificate': True,
        }
        
        os.makedirs('downloads', exist_ok=True)
        
        print("📥 Downloading video with yt-dlp...")
        def run_ytdl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(link, download=True)
                filename = ydl.prepare_filename(info)
                return filename

        loop = asyncio.get_running_loop()
        file_path = await loop.run_in_executor(None, run_ytdl)
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("Download failed: File not found (Link might be expired/404).")
            
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"✅ Download Successful! Size: {file_size_mb:.2f} MB")

        # Upload to Telegram Channel
        print("🚀 Uploading to Telegram channel...")
        caption = f"📥 **Downloaded via Bot**\n🔗 `{link}`"
        
        await client.send_video(
            chat_id=target_channel,
            video=file_path,
            caption=caption,
            supports_streaming=True
        )
        print("✅ Upload Successful!")

    except Exception as e:
        error_msg = str(e)
        print(f"\n❌ [FAILED] Task failed for link: {link}")
        print(f"🔴 Error: {error_msg}")
        traceback.print_exc()
        
        # 🔔 Error ko seedha aapke Telegram channel par bhejne ke liye
        error_text = f"❌ **Leech / Download Failed!**\n\n🔗 **Link:** `{link}`\n🔴 **Error:** `{error_msg[:300]}`"
        try:
            await client.send_message(chat_id=target_channel, text=error_text)
        except Exception as tg_err:
            print(f"⚠️ Failed to send error to Telegram channel: {tg_err}")
            
    finally:
        # Local file cleanup (Storage full hone se bachane ke liye)
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"🧹 Cleaned up local file: {file_path}")
            except Exception as cleanup_err:
                print(f"⚠️ Cleanup warning: {cleanup_err}")
        print(f"--------------------------------------------------\n")

# 4. Telegram Bot Handlers
@app.on_message(filters.command("start"))
async def start_command(client, message):
    await message.reply("🤖 **Unified Extractor & Leech Bot is Online!**\nSend a `.txt` file containing links or a single link.")

@app.on_message(filters.document)
async def document_handler(client, message):
    if message.document.file_name and message.document.file_name.endswith(".txt"):
        await message.reply("📂 Processing `.txt` file...")
        downloaded_txt = await message.download()
        
        # Extractor function se links nikalna
        links = extract_links_from_txt(downloaded_txt)
        os.remove(downloaded_txt)
        
        await message.reply(f"🔍 Extracted {len(links)} links. Queue started...")
        
        for link in links:
            await process_single_link(client, link, CHANNEL_ID)
            await asyncio.sleep(2)  # Links ke beech gap
            
        await message.reply("✅ **All links processed from the file!**")

@app.on_message(filters.text & ~filters.command("start"))
async def text_link_handler(client, message):
    link = message.text.strip()
    if link.startswith("http"):
        await message.reply("🔄 Processing single link...")
        await process_single_link(client, link, CHANNEL_ID)
    else:
        await message.reply("⚠️ Please send a valid HTTP link or `.txt` file.")

# Bot Start
if __name__ == "__main__":
    print("🚀 Starting Unified Bot...")
    app.run()
