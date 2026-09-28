# helpers.py — PATCH appx_decrypt to try multiple known keys

def appx_decrypt(enc: str) -> str:
    if not enc:
        return ""
    # known key/iv pairs (newest first)
    KEYS = [
        (b"638udh3829162018", b"fedcba9876543210"),  # original
        (b"appxapikey123456", b"fedcba9876543210"),  # rotation 1
        (b"appx20222023key1", b"appxiv1234567890"),  # rotation 2
    ]
    try:
        enc_bytes = b64decode(enc.split(":")[0])
        if not enc_bytes:
            return ""
        for key, iv in KEYS:
            try:
                cipher = AES.new(key, AES.MODE_CBC, iv)
                result = unpad(cipher.decrypt(enc_bytes), AES.block_size).decode("utf-8")
                if result:
                    return result
            except Exception:
                continue
    except Exception:
        pass
    return ""
