import os
import threading
import traceback
import asyncio
import yt_dlp
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters

# --- 1. DUMMY WEB SERVER FOR RENDER PORT 8080 (WITH HEAD METHOD SUPPORT) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running and alive!")
        
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    print(f"🌐 Dummy web server started on port {port}")
    server.serve_forever()

# Server ko background thread me start karna taaki Render port happy rahe
threading.Thread(target=run_web_server, daemon=True).start()


# --- 2. CREDENTIALS & SESSION CONFIGURATION ---
API_ID = 33956574
API_HASH = "0bcd4b744ec2ab732c4135001e4e1299"
SESSION_STRING = "AQIGIt4Ah4GLfjgUwKzwRWmJEoxs49GR9tIhnFpsFvaG4rGT67Vwl6dmdajtWdha0vAjvMNwX3l8_RsMx9TFSJU6tKa58sfzusCe8bfLKfaMNoJXloIBr-doEB2aC9tAzjvfY5veQt_Y1IHcmSD-EDYmCnPQDsTOoPvDbteQQhkOBZyGeA_-gurAeMyM2JMWjjTuRWvayZOBuvA5DhHvt9YWRrcotG86eZeu-uXock7Bz0dz2Kq5PS8KxY9duDQTDrZtpjTqJ5LNXd96_UZI9lCdPP9T9t625PwGpr40mF7YgnwWV18AM5gFdHyJeh2OOwLdUicL8mTm8YLjWC7WtFixxlrGLgAAAAHLCvarAA"
CHANNEL_ID = -1003869611917  # Aapke target channel ki ID

# Pyrogram Client Initialize karna
app = Client(
    "unified_leech_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)


# --- 3. EXRACTOR LOGIC (.txt FILE READER) ---
def extract_links_from_txt(file_path):
    """
    Yeh function .txt file ko read karta hai aur valid links nikal kar list banata hai.
    """
    links = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Comments (#) ya khaali lines ko chhod kar links uthayega
            if line and not line.startswith("#"):
                links.append(line)
    return links


# --- 4. DOWNLOAD, UPLOAD & ERROR REPORTING FUNCTION ---
async def process_single_link(client, link, target_channel):
    file_path = None
    try:
        print(f"\n🔄 [PROCESSING] Link: {link}")
        
        # yt-dlp options (RAM optimization & quality control)
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


# --- 5. TELEGRAM BOT HANDLERS ---
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


# --- 6. BOT RUNNER ---
if __name__ == "__main__":
    print("🚀 Starting Unified Bot...")
    app.run()
