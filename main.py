import os
from pyrogram import Client, filters
from leech import process_leech  # leech.py se function import karna

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = -1001234567890  # Apne channel ki real ID yahan dalein

# Pyrogram Client initialize karna
app = Client(
    "my_leech_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply("Bot is online and ready to leech!")

@app.on_message(filters.text & ~filters.command("start"))
async def link_handler(client, message):
    link = message.text.strip()
    await message.reply("📥 Downloading started...")
    
    # leech.py ke function ko call karna
    await process_leech(app, link, CHANNEL_ID)

# Bot ko run karna
if __name__ == "__main__":
    print("Bot started...")
    app.run()
