import os
from decouple import config

API_ID_RAW = os.environ.get("API_ID", "").strip() or config("API_ID", default="").strip()
api_id = int(API_ID_RAW) if API_ID_RAW.isdigit() else 0

api_hash = os.environ.get("API_HASH", "").strip() or config("API_HASH", default="").strip()
bot_token = os.environ.get("BOT_TOKEN", "").strip() or config("BOT_TOKEN", default="").strip()

AUTH_USERS_RAW = os.environ.get("AUTH_USERS", "").strip() or config("AUTH_USERS", default="").strip()
auth_users = [int(x.strip()) for x in AUTH_USERS_RAW.split(",") if x.strip().isdigit()]

if not api_id:
    raise ValueError("Set valid API_ID environment variable or config setting!")
if not api_hash:
    raise ValueError("Set API_HASH environment variable or config setting!")
if not bot_token:
    raise ValueError("Set BOT_TOKEN environment variable or config setting!")
