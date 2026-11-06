"""Portable login cookies, kept outside every disposable browser environment."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit


COOKIE_ROOTS = ("douyin.com", "iesdouyin.com", "kuaishou.com", "kwai.com")
# These cookies identify a browser environment or a short-lived verification
# attempt. The site creates new values in each fresh environment.
ENVIRONMENT_COOKIE_NAMES = frozenset({
    "mstoken", "ttwid", "s_v_web_id", "verifyfp", "verify_fp",
    "__ac_nonce", "__ac_signature", "__ac_referer",
})


class CookieStoreError(RuntimeError):
    """Safe error messages never include cookie values."""


def linked(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def normalize_login_cookies(payload, *, roots=None, now=None):
    roots = COOKIE_ROOTS if roots is None else tuple(roots)
    now = time.time() if now is None else now
    if isinstance(payload, dict):
        payload = payload.get("cookies")
    if not isinstance(payload, list):
        raise CookieStoreError("Cookie 文件格式无效，请重新扫码或导入有效 Cookie。")
    result = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        domain = str(raw.get("domain") or urlsplit(str(raw.get("url") or "")).hostname or "").lower()
        host = domain.lstrip(".")
        if not any(host == root or host.endswith("." + root) for root in roots):
            continue
        name, value = raw.get("name"), raw.get("value")
        if not isinstance(name, str) or not name or not isinstance(value, str):
            continue
        if name.casefold() in ENVIRONMENT_COOKIE_NAMES or any(char in name + value for char in "\r\n\x00"):
            continue
        path = str(raw.get("path") or "/")
        if not path.startswith("/") or any(char in path for char in "\r\n\x00"):
            continue
        cookie = {"name": name, "value": value, "path": path,
                  "secure": bool(raw.get("secure")), "httpOnly": bool(raw.get("httpOnly"))}
        if raw.get("hostOnly") or "url" in raw and not raw.get("domain"):
            cookie["url"] = f"{'https' if cookie['secure'] else 'http'}://{host}{path}"
        else:
            cookie["domain"] = domain
        expiry = raw.get("expires", raw.get("expirationDate"))
        if not raw.get("session") and expiry is not None:
            try:
                expiry = float(expiry)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(expiry) or expiry <= now:
                continue
            cookie["expires"] = expiry
        same_site = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}.get(str(raw.get("sameSite") or "").casefold())
        if same_site:
            cookie["sameSite"] = same_site
            if same_site == "None":
                cookie["secure"] = True
        partition = raw.get("partitionKey")
        if isinstance(partition, dict) and isinstance(partition.get("topLevelSite"), str):
            cookie["partitionKey"] = {"topLevelSite": partition["topLevelSite"],
                                      "hasCrossSiteAncestor": bool(partition.get("hasCrossSiteAncestor"))}
        key = (host, path, name, json.dumps(cookie.get("partitionKey"), sort_keys=True))
        result[key] = cookie
    return [result[key] for key in sorted(result)]


class CookieStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.path = self.directory / "cookies.json"
        self._source_hash = ""

    def load(self):
        if linked(self.path):
            raise CookieStoreError("Cookie 文件不能是链接，请检查选品数据目录。")
        if not self.path.is_file():
            return []
        try:
            document = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self._source_hash = str(document.get("importSha256") or "")
            return normalize_login_cookies(document)
        except (OSError, ValueError, AttributeError, TypeError):
            raise CookieStoreError("保存的 Cookie 无法读取，请重新扫码或导入有效 Cookie。") from None

    def save(self, cookies):
        cookies = normalize_login_cookies(cookies)
        self.directory.mkdir(parents=True, exist_ok=True)
        if linked(self.path):
            raise CookieStoreError("Cookie 文件不能是链接，请检查选品数据目录。")
        document = {"schemaVersion": 1, "savedAt": time.time(), "importSha256": self._source_hash, "cookies": cookies}
        # Avoid repeatedly writing identical credentials during background saves.
        if self.path.is_file():
            try:
                previous = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if previous.get("cookies") == cookies and previous.get("importSha256", "") == self._source_hash:
                    return len(cookies)
            except (OSError, ValueError, AttributeError):
                pass
        fd, temporary = tempfile.mkstemp(prefix=".cookies-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return len(cookies)

    def seed_import(self, source=None):
        source = Path(source or os.environ.get("JINGXU_SPIDER_COOKIES") or self.directory.parent / "cookies-import.json")
        existing = self.load()
        if not source.is_file():
            return existing
        try:
            raw = source.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest == self._source_hash:
                return existing
            cookies = normalize_login_cookies(json.loads(raw.decode("utf-8-sig")))
        except (OSError, UnicodeError, ValueError):
            raise CookieStoreError("导入 Cookie 文件无法读取，请检查文件格式。") from None
        if not cookies:
            raise CookieStoreError("导入文件没有有效登录 Cookie，请重新扫码或重新导出 Cookie。")
        self._source_hash = digest
        self.save(cookies)
        return cookies

    def restore(self, page):
        cookies = self.seed_import()
        if cookies:
            page.run_cdp("Network.setCookies", cookies=cookies)
        return len(cookies)

    def capture(self, page):
        response = page.run_cdp("Network.getAllCookies", _timeout=3)
        if not isinstance(response, dict) or not isinstance(response.get("cookies"), list):
            raise CookieStoreError("浏览器未返回有效 Cookie，已保留上次保存的登录资料。")
        return self.save(response["cookies"])
