"""Detect an abnormal browser session and maintain caches during long crawls."""

from core.browser_manager import BROWSER_SESSION_ERRORS, BrowserSessionAbnormal, BrowserEnvironmentRotated
from core.record_identity import deduplicate_items
from core.text_utils import clean_product_title


SESSION_ERROR_MARKERS = (
    "访问异常", "异常访问", "异常请求", "请求异常", "网络环境异常",
    "当前访问存在风险", "访问过于频繁", "操作过于频繁", "访问频繁",
)
CACHE_MAINTENANCE_PAGES = 5
MAX_SESSION_RECOVERIES = 2


def check_browser_session(page):
    """Recognize an error page, without mistaking ordinary login for corruption."""
    try:
        title = getattr(page, "title", "")
        content = page.run_js("""return {
            text: document.body ? document.body.innerText : '',
            hasVideos: !!document.querySelector("a[href*='/video/'],a[href*='/short-video/']")
        };""")
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:
        return
    title = title if isinstance(title, str) else ""
    has_videos = isinstance(content, dict) and content.get("hasVideos") is True
    body = content.get("text", "") if isinstance(content, dict) else content
    body = body if isinstance(body, str) else ""
    # A normal author page can contain these words in a video caption. Error
    # pages have a short body or an explicit error title.
    if any(marker in title for marker in SESSION_ERROR_MARKERS) or (
        not has_videos and len(body) <= 2000 and any(marker in body for marker in SESSION_ERROR_MARKERS)
    ):
        raise BrowserSessionAbnormal("浏览器主页显示访问异常。")


def maintain_browser_cache(manager, page_index=0):
    """Rotate at a safe checkpoint; intermediate cache maintenance stays bounded."""
    rotate = getattr(manager, "rotate_if_due", None)
    if callable(rotate) and rotate():
        raise BrowserEnvironmentRotated("浏览器环境已更换，请从抓取位置继续。")
    clear = getattr(manager, "clear_runtime_cache", None)
    if callable(clear) and page_index % CACHE_MAINTENANCE_PAGES == 0:
        clear()


def mark_browser_page(manager):
    completed = getattr(manager, "mark_page_processed", None)
    if callable(completed):
        completed()


def recover_browser_session(manager, platform, log, should_stop):
    """Reset only the affected platform, leaving any acquired rows with the caller."""
    if should_stop():
        return False
    clear = getattr(manager, "clear_site_session", None)
    if not callable(clear):
        return False
    label = "抖音" if platform == "douyin" else "快手"
    log(f"[{label}] 主页出现访问异常，正在更换独立浏览器环境并加载保存的登录 Cookie。")
    try:
        cleared = clear(platform)
    except Exception:
        log(f"[{label}] 本次自动清理未完成，已保留取得的数据。")
        return False
    if not cleared or should_stop():
        return False
    log(f"[{label}] 新环境已启动，登录 Cookie 已加载，重新打开当前作者主页。")
    return True


def merge_crawl_items(retained, items):
    """Enrich observations seen again after recovery without counting them twice."""
    result = list(retained)
    by_id = {(item.video_id, item.product_id): item for item in result if item.product_id}
    by_name = {}
    for item in result:
        name = item.cleaned_name or clean_product_title(item.product_name)
        by_name.setdefault((item.video_id, name), []).append(item)
    for item in items:
        name = item.cleaned_name or clean_product_title(item.product_name)
        old = by_id.get((item.video_id, item.product_id)) if item.product_id else None
        if old is None and item.video_id and name:
            old = next((candidate for candidate in by_name.get((item.video_id, name), ())
                        if not candidate.product_id or not item.product_id
                        or candidate.product_id == item.product_id), None)
        if old is None:
            result.append(item)
            by_name.setdefault((item.video_id, name), []).append(item)
            old = item
        else:
            old.like_count = max(old.like_count, item.like_count)
            for field in ("product_id", "product_name", "cleaned_name", "price", "detail_url", "cover_url",
                          "publish_time", "publish_time_str", "video_title"):
                value = getattr(item, field)
                if value:
                    setattr(old, field, value)
        if old.product_id:
            by_id[(old.video_id, old.product_id)] = old
    return deduplicate_items(result)
