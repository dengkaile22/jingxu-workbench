"""Import user-supplied Cookie Editor JSON into the existing Chromium profile.
Credentials stay in the user's login directory and are never logged or exported.
"""

from __future__ import annotations
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path

ALLOWED_DOMAINS = {"douyin.com", "www.douyin.com", "kuaishou.com", "www.kuaishou.com"}


def normalize_cookies(payload, *, now=None):
    now = time.time() if now is None else now
    if isinstance(payload, dict):
        payload = payload.get("cookies")
    if not isinstance(payload, list):
        raise ValueError("Cookie 文件必须是导出的 JSON 列表。")
    result = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip().lower()
        name = item.get("name")
        value = item.get("value")
        if (
            domain.lstrip(".") not in ALLOWED_DOMAINS
            or not isinstance(name, str)
            or not name
            or not isinstance(value, str)
        ):
            continue
        if any(c in name + value for c in "\r\n\x00"):
            continue
        cookie = {
            "name": name,
            "value": value,
            "path": item.get("path") or "/",
            "secure": bool(item.get("secure")),
            "httpOnly": bool(item.get("httpOnly")),
        }
        if item.get("hostOnly"):
            cookie["url"] = f"https://{domain.lstrip('.')}/"
        else:
            cookie["domain"] = domain
        same_site = {
            "no_restriction": "None",
            "none": "None",
            "lax": "Lax",
            "strict": "Strict",
        }.get(str(item.get("sameSite") or "").lower())
        if same_site:
            cookie["sameSite"] = same_site
            if same_site == "None":
                cookie["secure"] = True
        expiry = item.get("expirationDate", item.get("expires"))
        if not item.get("session") and expiry is not None:
            try:
                expiry = float(expiry)
                if not math.isfinite(expiry) or expiry <= now:
                    continue
                cookie["expires"] = expiry
            except (TypeError, ValueError):
                continue
        result.append(cookie)
    return result


def import_cookie_file(page, profile_directory, source=None):
    profile = Path(profile_directory).resolve()
    source = Path(
        source
        or os.environ.get("JINGXU_SPIDER_COOKIES")
        or profile.parent / "cookies-import.json"
    )
    if not source.is_file():
        return 0
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    marker = profile / ".jingxu-cookie-import.json"
    try:
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if saved.get("sha256") == digest:
            return 0
    except (OSError, ValueError, AttributeError):
        pass
    cookies = normalize_cookies(json.loads(raw.decode("utf-8-sig")))
    if not cookies:
        raise ValueError("Cookie 文件中没有有效的抖音或快手登录 Cookie。")
    page.run_cdp("Network.setCookies", cookies=cookies)
    # Reapply only when the user's import file changes. Otherwise a later login
    # must not be overwritten by the older imported credentials on each startup.
    fd, temp = tempfile.mkstemp(prefix=".cookie-import-", suffix=".tmp", dir=profile)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"sha256": digest, "count": len(cookies)}, stream)
        os.replace(temp, marker)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return len(cookies)
