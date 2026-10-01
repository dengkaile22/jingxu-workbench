"""Stable account and video-product identities used by analysis and exports."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from core.models import AccountTarget, VideoProductItem


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


def deduplicate_items(items: list[VideoProductItem]) -> list[VideoProductItem]:
    result: list[VideoProductItem] = []
    positions: dict[tuple[str, str, str, str], int] = {}
    for item in items:
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
            previous = result[position]
            def quality(entry):
                return entry.like_count, bool(entry.publish_time), bool(entry.price)
            if quality(item) > quality(previous):
                result[position] = item
    return result
