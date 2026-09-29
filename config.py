# ZeroTrace Bot — @ZeroTrace
import os


def _require_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise ValueError(f"Required environment variable not set: {key}")
    return val


def _parse_api_id() -> int:
    raw = os.environ.get("API_ID", "").strip()
    if not raw:
        raise ValueError("Required environment variable not set: API_ID")
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"API_ID must be a number, got: {raw!r}")


api_id    = _parse_api_id()
api_hash  = _require_env("API_HASH")
bot_token = _require_env("BOT_TOKEN")

_raw_auth = os.environ.get("AUTH_USERS", "").strip()
auth_users: list[int] = [
    int(x.strip())
    for x in _raw_auth.split(",")
    if x.strip().isdigit()
]
if not auth_users:
    raise ValueError(
        "AUTH_USERS env var missing or has no valid numeric IDs. "
        "Example: AUTH_USERS=123456789"
    )
