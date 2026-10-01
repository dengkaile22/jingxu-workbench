"""Resolve Douyin account inputs to a verified, stable SecUID.

Share tokens and public Douyin handles are not SecUIDs.  Resolution must fail
explicitly when a stable identity cannot be established; otherwise duplicate
shares can be crawled twice, or an unrelated page can be crawled as the target.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from core.browser_manager import BROWSER_SESSION_ERRORS

import requests


class AccountResolutionError(ValueError):
    """The supplied account could not be mapped unambiguously to a SecUID."""


_SEC_UID_RE = re.compile(r"MS4wLjABAAAA[A-Za-z0-9_-]+")
_HANDLE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_URL_RE = re.compile(r"https?://[^\s<>\"'，。；、）】]+", re.IGNORECASE)
_USER_SEARCH_TARGETS = [
    "aweme/v1/web/discover/search",
    "aweme/v1/web/search/user",
    "web/search/user",
    "user/search",
]
_BLOCKED_MARKERS = (
    "验证码", "安全验证", "请完成验证", "滑块验证", "拖动滑块",
    "访问过于频繁", "操作过于频繁", "请先登录", "登录后搜索", "登录后查看",
)


def _input_target(raw: str) -> str:
    value = (raw or "").strip()
    match = _URL_RE.search(value)
    if match:
        return match.group(0).rstrip(".,;)]}")
    return value


def _is_douyin_host(host: str | None) -> bool:
    value = (host or "").lower()
    return any(value == root or value.endswith("." + root) for root in ("douyin.com", "iesdouyin.com"))


def _valid_sec_uid(value: Any) -> str:
    if isinstance(value, str) and _SEC_UID_RE.fullmatch(value.strip()):
        return value.strip()
    return ""


def extract_douyin_sec_uid(raw: str) -> str:
    """Extract only a valid SecUID from a direct ID or official profile URL.

    This function performs no network request.  Unresolved short links, public
    handles, arbitrary URLs, and malformed profile IDs return an empty string.
    """
    target = _input_target(raw)
    direct = _valid_sec_uid(target)
    if direct:
        return direct
    try:
        parsed = urlsplit(target)
        if parsed.scheme.lower() not in ("http", "https") or not _is_douyin_host(parsed.hostname):
            return ""
        path = unquote(parsed.path)
        path_match = re.fullmatch(r"/(?:share/)?user/([^/]+)/?", path)
        path_identity = _valid_sec_uid(path_match.group(1)) if path_match else ""
        if path != "/" and not re.fullmatch(r"/(?:share/)?user(?:/[^/]+)?/?", path):
            return ""
        # Sharing clients also encode the profile identity in a query parameter.
        # Older mobile profiles use a numeric path ID and keep SecUID in the
        # query.  Never trust this parameter on a video/search/short-token URL.
        query = parse_qs(parsed.query)
        identities = {
            identity
            for key in ("sec_uid", "sec_user_id")
            for value in query.get(key, [])
            if (identity := _valid_sec_uid(value))
        }
        if path_identity:
            identities.add(path_identity)
        return next(iter(identities)) if len(identities) == 1 else ""
    except (TypeError, ValueError):
        return ""


def _decode_payload(payload: Any) -> Any:
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = bytes(payload).decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
    if not isinstance(payload, str):
        return payload
    value = html.unescape(payload.strip())
    if value.startswith(("%7B", "%7b", "%5B", "%5b")):
        value = unquote(value)
    if not value.startswith(("{", "[")):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def extract_douyin_user_matches(payload: Any, unique_id: str) -> set[str]:
    """Find SecUIDs paired with the exact public handle in structured data.

    Nicknames, partial handle matches, and SecUIDs from unrelated search hits
    never count.  Repeated copies of the same user count as one identity.
    """
    matches: set[str] = set()

    def visit(node: Any, depth: int = 0) -> None:
        if depth > 24:
            return
        if isinstance(node, (str, bytes, bytearray)):
            node = _decode_payload(node)
        if isinstance(node, dict):
            handle = node.get("unique_id", node.get("uniqueId"))
            if isinstance(handle, str) and handle.strip() == unique_id:
                for key in ("sec_uid", "sec_user_id", "secUid", "secUserId"):
                    identity = _valid_sec_uid(node.get(key))
                    if identity:
                        matches.add(identity)
            for value in node.values():
                if isinstance(value, (dict, list, str, bytes, bytearray)):
                    visit(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                visit(value, depth + 1)

    visit(payload)
    return matches


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attributes = dict(attrs)
        if attributes.get("id") in (
            "RENDER_DATA", "__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE", "__NEXT_DATA__",
        ) or attributes.get("type") == "application/json":
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._parts is not None:
            self.payloads.append("".join(self._parts))
            self._parts = None


def _page_payloads(page: Any) -> list[Any]:
    payloads: list[Any] = []
    if hasattr(page, "run_js"):
        try:
            values = page.run_js("""
                const payloads = [];
                for (const id of ['RENDER_DATA', '__UNIVERSAL_DATA_FOR_REHYDRATION__',
                                  'SIGI_STATE', '__NEXT_DATA__']) {
                    const value = document.getElementById(id)?.textContent;
                    if (value) payloads.push(value);
                }
                for (const key of ['_ROUTER_DATA', '__INITIAL_STATE__', 'SIGI_STATE']) {
                    if (window[key]) payloads.push(window[key]);
                }
                return payloads;
            """)
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:  # noqa: BLE001 - Browser JS is optional; HTML SSR remains a fallback.
            values = []
        if isinstance(values, list):
            payloads.extend(values)
        elif isinstance(values, (dict, str, bytes, bytearray)):
            payloads.append(values)
    try:
        source = page.html
        if isinstance(source, str) and source:
            parser = _ScriptCollector()
            parser.feed(source)
            payloads.extend(parser.payloads)
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:  # noqa: BLE001 - A disconnected browser may still have supplied JS data.
        return payloads
    return payloads


def _page_url(page: Any) -> str:
    try:
        value = page.url
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:  # noqa: BLE001 - Browser transport errors make the current URL unverified.
        return ""
    return value if isinstance(value, str) else ""


def _check_page_access(page: Any) -> None:
    try:
        body = page.run_js("return document.body ? document.body.innerText : '';")
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:  # noqa: BLE001 - Body text is optional; URL and title also detect gates.
        body = ""
    text = body if isinstance(body, str) else ""
    try:
        title = page.title
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:  # noqa: BLE001 - Title is optional; body text and URL remain available.
        title = ""
    if isinstance(title, str):
        text += "\n" + title
    try:
        path = urlsplit(_page_url(page)).path.lower()
    except ValueError:
        path = ""
    if any(marker in path for marker in ("/captcha", "/verify", "/passport", "/login")):
        raise AccountResolutionError("账号解析遇到登录或验证页面，请完成登录/验证后重试。")
    if any(marker in text for marker in _BLOCKED_MARKERS):
        raise AccountResolutionError("账号解析遇到登录或验证码提示，请完成登录/验证后重试。")


def _navigate(page: Any, url: str) -> None:
    try:
        try:
            result = page.get(url, timeout=15)
        except TypeError:
            result = page.get(url)
        if result is False:
            raise AccountResolutionError("账号解析页面加载失败，请检查网络后重试。")
    except AccountResolutionError:
        raise
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:  # noqa: BLE001 - Translate transport-specific errors without logging URL tokens.
        raise AccountResolutionError("账号解析页面加载失败，请检查网络后重试。") from None


def _resolve_share_link(target: str, page: Any, log: Callable[[str], None]) -> str:
    try:
        response = requests.get(
            target,
            allow_redirects=True,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
    except requests.RequestException:
        response = None
    if response is not None and getattr(response, "status_code", 200) < 400:
        identity = extract_douyin_sec_uid(response.url)
        if identity:
            return identity
    if page is None:
        raise AccountResolutionError("分享短链未解析出有效账号，请使用主页链接或 Sec-UID，或登录后重试。")
    log("[抖音] 分享短链普通请求未解析成功，正在使用浏览器确认账号。")
    _navigate(page, target)
    _check_page_access(page)
    identity = extract_douyin_sec_uid(_page_url(page))
    if not identity:
        raise AccountResolutionError("分享短链未跳转到有效的抖音账号主页，请重新复制账号主页分享链接。")
    return identity


def _check_search_location(page: Any, handle: str) -> None:
    try:
        parsed = urlsplit(_page_url(page))
        expected_page = (
            parsed.scheme.lower() in ("http", "https")
            and _is_douyin_host(parsed.hostname)
            and unquote(parsed.path).rstrip("/") == f"/search/{handle}"
            and parse_qs(parsed.query).get("type") == ["user"]
        )
    except ValueError:
        expected_page = False
    if not expected_page:
        raise AccountResolutionError("抖音号搜索未打开预期的用户搜索页面，请登录后重试。")


def _resolve_public_handle(handle: str, page: Any, log: Callable[[str], None]) -> str:
    if page is None:
        raise AccountResolutionError("抖音号需要通过已登录浏览器搜索确认，请登录后重试或提供主页链接 / Sec-UID。")
    log(f"[抖音] 正在按抖音号精确查找账号：{handle}")
    listener = getattr(page, "listen", None)
    listener_started = False
    if listener is not None:
        try:
            listener.start(_USER_SEARCH_TARGETS)
            listener_started = True
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:  # noqa: BLE001 - Packet capture is optional; structured page data is enough.
            listener_started = False
    try:
        _navigate(page, f"https://www.douyin.com/search/{quote(handle, safe='')}?type=user")
        _check_page_access(page)
        _check_search_location(page, handle)
        matches: set[str] = set()
        for payload in _page_payloads(page):
            matches.update(extract_douyin_user_matches(payload, handle))
        if listener_started:
            # Search responses may arrive after navigation.  Bound the wait,
            # and inspect every captured response before accepting a match.
            for _ in range(3):
                try:
                    packet = listener.wait(timeout=1)
                except BROWSER_SESSION_ERRORS:
                    raise
                except Exception:  # noqa: BLE001 - Listener transport failure leaves SSR as fallback.
                    break
                if not packet:
                    continue
                packets = packet if isinstance(packet, (list, tuple)) else [packet]
                for item in packets:
                    try:
                        payload = item.response.body
                    except BROWSER_SESSION_ERRORS:
                        raise
                    except Exception:  # noqa: BLE001 - An unreadable optional packet cannot prove identity.
                        payload = None
                    matches.update(extract_douyin_user_matches(payload, handle))
        _check_page_access(page)
        _check_search_location(page, handle)
        # Late SSR data can also become available while waiting for packets.
        for payload in _page_payloads(page):
            matches.update(extract_douyin_user_matches(payload, handle))
        if len(matches) > 1:
            raise AccountResolutionError("搜索返回多个匹配该抖音号的账号，无法可靠确认身份，请提供账号主页链接 / Sec-UID。")
        if not matches:
            raise AccountResolutionError("未找到抖音号完全匹配且包含有效 Sec-UID 的账号，请确认抖音号或提供主页链接。")
        return next(iter(matches))
    finally:
        if listener_started:
            try:
                listener.stop()
            except Exception:  # noqa: BLE001 - Cleanup cannot mask a verified identity or primary error.
                log("[抖音] 账号搜索监听清理失败，后续抓取将重新初始化监听。")


def resolve_douyin_identity(raw: str, page: Any = None, log: Callable[[str], None] | None = None) -> str:
    """Resolve an input to one validated SecUID, or raise AccountResolutionError.

    Direct IDs/profile URLs need no browser.  Short shares follow redirects,
    with the supplied browser as fallback.  Public handles use exact
    ``unique_id`` matches from that browser's user-search data.
    """
    target = _input_target(raw)
    if not target:
        raise AccountResolutionError("账号为空，请输入抖音号、账号主页链接或 Sec-UID。")
    identity = extract_douyin_sec_uid(target)
    if identity:
        return identity
    callback = log or (lambda _message: None)
    try:
        parsed = urlsplit(target)
    except ValueError:
        raise AccountResolutionError("账号链接格式无效，请重新复制账号主页链接。") from None
    if parsed.scheme or parsed.netloc:
        if (
            parsed.scheme.lower() in ("http", "https")
            and (parsed.hostname or "").lower() == "v.douyin.com"
            and re.fullmatch(r"/[A-Za-z0-9_-]+/?", parsed.path)
        ):
            return _resolve_share_link(target, page, callback)
        raise AccountResolutionError("链接中没有有效的抖音账号 Sec-UID，请提供账号主页链接。")
    handle = re.sub(r"^抖音号\s*[:：]\s*", "", target).lstrip("@").strip()
    if target.startswith("MS4w") or not _HANDLE_RE.fullmatch(handle):
        raise AccountResolutionError("账号标识格式无效，请输入抖音号、账号主页链接或有效的 Sec-UID。")
    return _resolve_public_handle(handle, page, callback)
