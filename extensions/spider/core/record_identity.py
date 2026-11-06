"""Stable account and video-product identities used by analysis and exports."""

from __future__ import annotations

import re
import math
from dataclasses import replace
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from core.models import AccountTarget, VideoProductItem


def sanitize_items(items, on_issue=None) -> list[VideoProductItem]:
    """Isolate malformed observations before identity, sorting or export operations."""
    from core.text_utils import parse_chinese_count_str

    result = []
    text_fields = (
        "platform", "account_name", "account_id", "video_id", "video_title",
        "video_url", "publish_time_str", "product_id", "product_name",
        "cleaned_name", "price", "cover_url", "detail_url",
    )
    try:
        observations = iter(items or ())
    except TypeError:
        if on_issue:
            on_issue("已忽略格式无效的商品记录集合")
        return []
    for item in observations:
        if not isinstance(item, VideoProductItem):
            if on_issue:
                on_issue("已忽略一条格式无效的商品记录")
            continue
        invalid = False
        values = {}
        for key in text_fields:
            value = getattr(item, key)
            if isinstance(value, (str, int, float)):
                text = str(value)
                if text.isascii():
                    values[key] = text.strip()
                else:
                    encoded = text.encode("utf-8", errors="replace").decode("utf-8")
                    invalid = invalid or encoded != text
                    values[key] = encoded.strip()
            else:
                values[key] = ""
                invalid = invalid or value is not None
        values["platform"] = values["platform"].lower()
        if values["platform"] not in ("douyin", "kuaishou") or not isinstance(item.product_name, str) or not values["product_name"]:
            if on_issue:
                on_issue("已忽略缺少平台或商品标题的记录")
            continue
        try:
            timestamp = float(item.publish_time or 0)
            if not math.isfinite(timestamp) or timestamp < 0:
                timestamp = 0
                invalid = True
            if timestamp > 100_000_000_000:
                timestamp /= 1000
            # A timestamp outside datetime's range cannot be used for date filters.
            from datetime import datetime
            if timestamp:
                datetime.fromtimestamp(timestamp)
            values["publish_time"] = int(timestamp)
        except (TypeError, ValueError, OverflowError, OSError):
            values["publish_time"] = 0
            invalid = True
        likes = parse_chinese_count_str(item.like_count)
        values["like_count"] = likes if 0 <= likes <= 9_007_199_254_740_991 else 0
        invalid = invalid or likes < 0 or likes > 9_007_199_254_740_991
        changed = any(getattr(item, key) != value for key, value in values.items())
        result.append(replace(item, **values) if changed else item)
        if invalid and on_issue:
            on_issue("已修正一条商品记录的异常字段")
    return result


def stable_id_for(account: AccountTarget) -> str:
    platform = account.platform.strip().lower()
    resolved = account.sec_uid if platform == "douyin" else account.user_id
    if resolved:
        return resolved.strip()
    raw = account.url_or_id.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if platform == "douyin":
        if re.fullmatch(r"MS4wLjABAAAA[A-Za-z0-9_-]+", raw):
            return raw
        if (parsed.hostname or "").lower() in {"www.douyin.com", "douyin.com", "www.iesdouyin.com"}:
            match = re.fullmatch(r"/user/(MS4wLjABAAAA[A-Za-z0-9_-]+)/?", parsed.path)
            if match:
                return match.group(1)
    elif platform == "kuaishou":
        if (parsed.hostname or "").lower() in {"www.kuaishou.com", "kuaishou.com", "www.kwai.com"}:
            match = re.fullmatch(r"/profile/([A-Za-z0-9_-]+)/?", parsed.path)
            identities = set(parse_qs(parsed.query).get("userId", []))
            if match:
                identities.add(match.group(1))
            if len(identities) == 1:
                identity = next(iter(identities))
                if re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                    return identity
    return ""


def stable_account_key(account: AccountTarget) -> tuple[str, str]:
    platform = account.platform.strip().lower()
    resolved = stable_id_for(account)
    if resolved:
        return platform, f"id:{resolved}"
    raw = account.url_or_id.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return platform, f"input:{raw}"
    if parsed.scheme and parsed.netloc:
        query = urlencode(sorted(
            (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() != "from"
        ))
        raw = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))
    return platform, f"input:{raw}"


def account_profile_url(account: AccountTarget) -> str:
    resolved = stable_id_for(account)
    if not resolved:
        return account.url_or_id
    if account.platform == "douyin":
        return f"https://www.douyin.com/user/{resolved}"
    return f"https://www.kuaishou.com/profile/{resolved}"


def deduplicate_accounts(accounts: list[AccountTarget]) -> list[AccountTarget]:
    selected: dict[tuple[str, str], AccountTarget] = {}
    for account in accounts:
        key = stable_account_key(account)
        previous = selected.get(key)
        if previous is None or (not previous.enabled and account.enabled):
            selected[key] = account
    return list(selected.values())


def _item_quality(entry: VideoProductItem) -> tuple[int, bool, bool]:
    return entry.like_count, bool(entry.publish_time), bool(entry.price)


def deduplicate_items(items: list[VideoProductItem]) -> list[VideoProductItem]:
    result: list[VideoProductItem] = []
    positions: dict[tuple[str, str, str, str], int] = {}
    for item in sanitize_items(items):
        video = item.video_id or item.video_url
        # Without a video identity, two observations cannot safely be called duplicates.
        if not video:
            result.append(item)
            continue
        key = (
            item.platform, item.account_id or f"name:{item.account_name}", video,
            item.product_id or item.cleaned_name or item.product_name,
        )
        if key not in positions:
            positions[key] = len(result)
            result.append(item)
        else:
            position = positions[key]
            if _item_quality(item) > _item_quality(result[position]):
                result[position] = item
    return result
