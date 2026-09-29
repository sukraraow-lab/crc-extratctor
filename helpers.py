# ZeroTrace Bot — helpers.py
import logging
import re
from base64 import b64decode
from typing import Dict, Optional

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from pyrogram import Client, filters
from pyrogram.types import Message
from pyromod.exceptions import ListenerTimeout

from config import auth_users

log = logging.getLogger(__name__)


def is_authorized(user_id: int) -> bool:
    return bool(auth_users and user_id in auth_users)


async def ask_user(
    bot: Client,
    m: Message,
    editable: Message,
    text: str,
    user_id: int,
    timeout: int = 120,
) -> Optional[str]:
    await editable.edit(text)
    try:
        msg = await bot.listen(
            m.chat.id,
            filters.user(user_id),
            timeout=timeout,
        )
        val = (msg.text or "").strip()
        try:
            await msg.delete(True)
        except Exception:
            pass
        return val
    except ListenerTimeout:
        await editable.edit("**⏱ Timeout! You took too long to respond.**")
        return None
    except Exception as e:
        log.exception("Error during input listener:")
        await editable.edit(f"**Error:** `{e}`")
        return None


def extract_url_from_video_details(item: Dict) -> str:
    v_details = item.get("videoDetails") or {}
    url = (
        v_details.get("videoUrl")    or v_details.get("embedCode")   or
        v_details.get("mediaUrl")    or v_details.get("streamUrl")   or
        v_details.get("hlsUrl")      or v_details.get("mpdUrl")      or
        v_details.get("downloadUrl") or v_details.get("url")         or
        v_details.get("fileUrl")     or item.get("videoUrl")         or
        item.get("mediaUrl")         or item.get("streamUrl")        or
        item.get("hlsUrl")           or item.get("mpdUrl")           or
        item.get("url")              or ""
    )
    # unwrap iframe embed codes
    if url and ("<" in url or "iframe" in url.lower() or "src=" in url.lower()):
        match = re.search(r'src=["\'](https?://[^"\']+)["\']', url)
        if match:
            return match.group(1)
        match_any = re.search(r'https?://[^"\'\s<>]+', url)
        return match_any.group(0) if match_any else url
    return url


# ─── Appx AES decrypt ─────────────────────────────────────────────────────────

# Try newest key/IV pairs first; add new pairs at the top when Appx rotates keys.
_APPX_KEYS = [
    (b"appx20222023key1", b"appxiv1234567890"),  # rotation 2 (newest)
    (b"appxapikey123456", b"fedcba9876543210"),  # rotation 1
    (b"638udh3829162018", b"fedcba9876543210"),  # original
]


def appx_decrypt(enc: str) -> str:
    """
    Decrypt an Appx-encrypted URL string.
    Format: <base64-encoded-ciphertext>[:<ignored-suffix>]
    Returns the plaintext URL or "" on failure.
    """
    if not enc:
        return ""

    # Normalise: strip any suffix after ':', fix padding
    raw_b64 = enc.split(":")[0]
    # Add missing base64 padding
    raw_b64 += "=" * (-len(raw_b64) % 4)
    # Appx sometimes uses URL-safe base64
    raw_b64 = raw_b64.replace("-", "+").replace("_", "/")

    try:
        enc_bytes = b64decode(raw_b64)
    except Exception as e:
        log.debug("appx_decrypt: base64 decode failed for %r: %s", enc[:40], e)
        return ""

    if not enc_bytes:
        return ""

    for key, iv in _APPX_KEYS:
        try:
            cipher = AES.new(key, AES.MODE_CBC, iv)
            result = unpad(cipher.decrypt(enc_bytes), AES.block_size).decode("utf-8")
            if result:
                return result
        except Exception:
            continue

    log.warning("appx_decrypt: all keys failed for enc prefix %r", enc[:40])
    return ""
