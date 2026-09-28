# three.py — PATCH login_appx_user — try both endpoints

async def login_appx_user(session, bot, m, editable, user_id):
    app_input = await prompt_user(bot, m, editable,
                                   "**Enter App Name or API URL:**", user_id)
    api, app_name = await resolve_api_and_app_name(bot, m, editable, app_input, user_id)
    if not api or not app_name:
        return None, None, None

    mobile   = await prompt_user(bot, m, editable, "**Enter Mobile Number:**", user_id)
    password = await prompt_user(bot, m, editable, "**Enter Password:**", user_id)

    await editable.edit("🔑 **Authenticating...**")

    base_headers = {
        "Client-Service": "Appx",
        "Auth-Key": "appxapi",
        "source": "website",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    login_data = {"email": mobile, "password": password}

    # FIX: try multiple login endpoints
    login_endpoints = [
        f"{api}/post/userlogin",
        f"{api}/api/v1/userlogin",
        f"{api}/api/userlogin",
        f"{api}/user/login",
    ]

    res = None
    for endpoint in login_endpoints:
        try:
            res = await fetch_appx_html_to_json(
                session, endpoint, headers=base_headers, data=login_data)
            if res and res.get("status") == 200 and res.get("data"):
                break
            res = None
        except Exception:
            continue

    if not res or res.get("status") != 200 or not res.get("data"):
        msg = (res or {}).get("message", "All login endpoints failed.")
        await editable.edit(f"**Login Failed ❌**\n`{msg}`")
        return None, None, None

    data  = res["data"]
    token = (data.get("token") or data.get("jwt_token")
             or data.get("user_token") or data.get("authToken"))
    if not token:
        await editable.edit("**Login ok but token missing ❌**")
        return None, None, None

    await bot.send_message(
        m.chat.id,
        f"🔑 **Appx Token Generated!**\n\n"
        f"**App:** `{app_name}`\n"
        f"**Mobile:** `{mobile}`\n"
        f"**Token:**\n`{token}`\n\n"
        f"<blockquote>Tap to copy — save it for future use.</blockquote>",
    )
    return api, token, app_name
