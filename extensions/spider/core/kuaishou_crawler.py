"""
Kuaishou account crawler using DrissionPage packet listener, SSR state extraction, and DOM fallback.
"""

import time
import json
import re
from datetime import datetime
from typing import List, Optional, Callable, Dict, Any, Set
import requests
from urllib.parse import urlsplit, parse_qs

from core.models import VideoProductItem, AccountTarget, TimeFilterConfig
from core.text_utils import clean_product_title, parse_chinese_count_str
from core.extraction import ExtractionDiagnostic, extract_products
from core.browser_manager import BrowserManager
from core.record_identity import deduplicate_items


KUAISHOU_LISTEN_TARGETS = [
    "graphql",
    "visionProfilePhotoList",
    "rest/wd/photo",
    "rest/v/profile/feed",
    "rest/v/profile/get",
]


def resolve_kuaishou_url_or_userid(input_str: str) -> str:
    """
    Parse Kuaishou input string (short link, full URL, or user_id) into user_id.
    """
    input_str = input_str.strip()
    if not input_str:
        return ""

    if re.fullmatch(r"[A-Za-z0-9_-]+", input_str):
        return input_str
    match = re.search(r"https?://[^\s]+", input_str)
    if not match:
        return ""
    input_str = match.group(0).rstrip(".,，。")
    parsed = urlsplit(input_str)
    if (parsed.hostname or "").lower() in {
        "v.kuaishou.com",
        "www.kuaishouapp.com",
        "kuaishouapp.com",
    }:
        try:
            match = re.search(r"https?://[a-zA-Z0-9\.\-]+/[a-zA-Z0-9_\-]+/?", input_str)
            target_short = match.group(0) if match else input_str
            resp = requests.get(
                target_short,
                allow_redirects=True,
                timeout=8,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
            input_str = resp.url
        except Exception:
            pass

    parsed = urlsplit(input_str)
    if (parsed.hostname or "").lower() not in {
        "www.kuaishou.com",
        "kuaishou.com",
        "www.kwai.com",
    }:
        return ""
    match = re.fullmatch(r"/profile/([A-Za-z0-9_-]+)/?", parsed.path)
    identities = set(parse_qs(parsed.query).get("userId", []))
    if match:
        identities.add(match.group(1))
    elif parsed.path not in ("", "/"):
        return ""
    if len(identities) == 1:
        identity = next(iter(identities))
        if re.fullmatch(r"[A-Za-z0-9_-]+", identity):
            return identity
    return ""


def _photo_timestamp(photo):
    raw = (
        photo.get("timestamp") or photo.get("create_time") or photo.get("postDate") or 0
    )
    if isinstance(raw, bool):
        return 0
    try:
        value = float(raw)
        seconds = (
            int(value / 1000 if value > 100_000_000_000 else value) if value > 0 else 0
        )
        if seconds:
            datetime.fromtimestamp(seconds)
        return seconds
    except (TypeError, ValueError, OverflowError):
        try:
            return int(
                datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
            )
        except (ValueError, OverflowError, OSError):
            return 0


def _photo_owner(photo):
    for field in ("_feed_author", "author", "user"):
        owner = photo.get(field)
        if isinstance(owner, dict):
            value = owner.get("id") or owner.get("userId") or owner.get("user_id")
            if value:
                return str(value)
    return str(
        photo.get("userId") or photo.get("user_id") or photo.get("authorId") or ""
    )


def _profile_list(payload):
    if not isinstance(payload, dict) or payload.get("errors"):
        return None
    # The current ks-web client uses REST profile feeds; legacy pages use
    # GraphQL. Both carry a result code and a cursor, with different wrappers.
    if payload.get("result") in (1, "1") and isinstance(payload.get("feeds"), list):
        result = dict(payload)
        if "pcursor" not in result and "cursor" in result:
            result["pcursor"] = result["cursor"]
        return result
    data = payload.get("data")
    result = (
        data.get("visionProfilePhotoList") if isinstance(data, dict) else None
    ) or payload.get("visionProfilePhotoList")
    if not isinstance(result, dict) or not isinstance(result.get("feeds"), list):
        return None
    if "result" in result and result["result"] not in (1, "1"):
        return None
    return result


def _at_end(result):
    cursor = str(result.get("pcursor") or "").lower()
    return result.get("hasMore") in (False, 0, "0", "false") or cursor in {
        "nomore",
        "no_more",
    }


def _feed_photos(feeds):
    photos = []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        photo = feed.get("photo") or feed
        if isinstance(photo, dict) and (
            photo.get("id") or photo.get("photoId") or photo.get("photo_id")
        ):
            photo = dict(photo)
            if "id" not in photo:
                photo["id"] = photo.get("photoId") or photo.get("photo_id")
            if isinstance(feed.get("author"), dict):
                photo["_feed_author"] = feed["author"]
            elif isinstance(feed.get("user"), dict):
                photo["_feed_author"] = feed["user"]
            photos.append(photo)
    return photos


def _find_photo_items_recursive(
    node: Any, result: List[Dict[str, Any]], max_depth: int = 8, depth: int = 0
) -> None:
    """Safely traverse nested JSON to find Kuaishou photo items or feed lists."""
    if depth > max_depth or not node:
        return
    if isinstance(node, dict):
        if ("photoId" in node or "id" in node) and (
            "caption" in node or "goodsInfo" in node or "counts" in node
        ):
            result.append(node)
            return
        if "feeds" in node and isinstance(node["feeds"], list):
            for feed in node["feeds"]:
                if isinstance(feed, dict):
                    p = feed.get("photo") or feed
                    if isinstance(p, dict) and ("id" in p or "photoId" in p):
                        result.append(p)
            return
        for val in node.values():
            if isinstance(val, (dict, list)):
                _find_photo_items_recursive(val, result, max_depth, depth + 1)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                _find_photo_items_recursive(item, result, max_depth, depth + 1)


def _extract_ssr_photo_list(page: Any) -> List[Dict[str, Any]]:
    """
    Extract initially loaded photo items from Kuaishou window state (__APOLLO_STATE__, __PAGE_DATA__).
    Allows grabbing the first 20-30 videos instantly without network wait.
    """
    if not hasattr(page, "run_js"):
        return []
    photos: List[Dict[str, Any]] = []
    try:
        apollo_str = page.run_js(
            "return (typeof window.__APOLLO_STATE__ !== 'undefined') ? JSON.stringify(window.__APOLLO_STATE__) : '';"
        )
        if apollo_str:
            try:
                apollo_data = json.loads(apollo_str)
                default_client = apollo_data.get("defaultClient") or apollo_data
                if isinstance(default_client, dict):
                    for k, v in default_client.items():
                        if k.startswith("Photo:") and isinstance(v, dict):
                            photos.append(v)
            except Exception:
                pass

        if not photos:
            page_data_str = page.run_js(
                "return (typeof window.__PAGE_DATA__ !== 'undefined') ? JSON.stringify(window.__PAGE_DATA__) : '';"
            )
            if page_data_str:
                try:
                    pdata = json.loads(page_data_str)
                    _find_photo_items_recursive(pdata, photos)
                except Exception:
                    pass
    except Exception:
        pass
    return photos


def _extract_kuaishou_dom_video_cards(page: Any) -> List[Dict[str, Any]]:
    """
    Extract video cards from DOM when GraphQL packets are missed or delayed.
    Finds <a> elements linking to /short-video/{photo_id} or /photo/{photo_id}.
    """
    if not hasattr(page, "eles"):
        return []
    cards: List[Dict[str, Any]] = []
    try:
        eles = page.eles("tag:a@href*=/short-video/") + page.eles("tag:a@href*=/photo/")
        for ele in eles:
            try:
                href = ele.attr("href") or ""
                m = re.search(r"/(?:short-video|photo)/([a-zA-Z0-9_\-]+)", href)
                if not m:
                    continue
                photo_id = m.group(1)
                text = ele.text or ""

                like_cnt = 0
                like_ele = ele.ele("@class*=like", timeout=0.1) or ele.ele(
                    "@class*=count", timeout=0.1
                )
                if like_ele and like_ele.text:
                    like_cnt = parse_chinese_count_str(like_ele.text)

                desc = ele.attr("title") or (text.split("\n")[0] if text else "")

                cards.append(
                    {
                        "id": photo_id,
                        "caption": desc,
                        "timestamp": 0,
                        "counts": {"likeCount": like_cnt},
                        "_from_dom": True,
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    return cards


def _smooth_scroll_down(page: Any, step_px: int = 700) -> None:
    """Progressively scroll page down to reliably trigger IntersectionObserver."""
    if hasattr(page, "run_js"):
        try:
            page.run_js(
                f"""(() => {{
                const candidates=[document.scrollingElement,...document.querySelectorAll('main,section,div')]
                    .filter(e=>e && e.scrollHeight>e.clientHeight+50 &&
                     (e===document.scrollingElement || /auto|scroll/.test(getComputedStyle(e).overflowY)));
                const node=candidates.sort((a,b)=>(b.scrollHeight-b.clientHeight)-(a.scrollHeight-a.clientHeight))[0];
                if(node) node.scrollBy({{top:{step_px},behavior:'auto'}});
            }})()""",
                timeout=3,
            )
            return
        except Exception:
            pass
    if hasattr(page, "scroll"):
        try:
            if hasattr(page.scroll, "down"):
                page.scroll.down(step_px)
            elif hasattr(page.scroll, "to_bottom"):
                page.scroll.to_bottom()
        except Exception:
            pass


def _trigger_scroll_jitter(page: Any) -> None:
    """Slight upward and downward jitter to shake stubborn IntersectionObservers."""
    if hasattr(page, "run_js"):
        try:
            page.run_js(
                "window.scrollBy({top: -220, behavior: 'smooth'}); window.scrollBy({top: 450, behavior: 'smooth'});"
            )
        except Exception:
            pass


def extract_kuaishou_products_from_photo(
    photo: Dict[str, Any], account_name: str, account_id: str
) -> List[VideoProductItem]:
    """Extract e-commerce goods from a single Kuaishou photo/video object."""
    photo_id = str(photo.get("id") or photo.get("photoId") or "")
    caption = str(photo.get("caption") or photo.get("title") or "")
    create_time = _photo_timestamp(photo)
    time_str = (
        datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")
        if create_time
        else ""
    )
    video_url = f"https://www.kuaishou.com/short-video/{photo_id}" if photo_id else ""
    author_name = (
        photo.get("userName") or photo.get("author", {}).get("name") or account_name
    )

    items, _ = extract_products(
        "kuaishou",
        photo,
        author_name,
        account_id,
        video_title=caption,
        video_url=video_url,
        publish_time=create_time,
        publish_time_str=time_str,
    )
    if items:
        return items

    return _extract_kuaishou_caption_product(photo, author_name, account_id)


def _kuaishou_photo_like_count(photo: Dict[str, Any]) -> int:
    """Read Kuaishou like counts from both GraphQL and legacy response shapes."""
    counts = photo.get("counts")
    candidates = []
    if isinstance(counts, dict):
        candidates.extend(
            counts.get(key)
            for key in (
                "likeCount",
                "likedCount",
                "like_count",
                "likeCountStr",
                "likedCountStr",
            )
        )
    candidates.extend(
        photo.get(key)
        for key in (
            "likeCount",
            "likedCount",
            "like_count",
            "realLikeCount",
            "digg_count",
        )
    )
    return next(
        (
            parsed
            for value in candidates
            if (parsed := parse_chinese_count_str(value)) > 0
        ),
        0,
    )


def _extract_kuaishou_caption_product(
    photo: Dict[str, Any],
    account_name: str,
    account_id: str,
) -> List[VideoProductItem]:
    """Fallback for Kuaishou cards that only expose a bracketed product name."""
    photo_id = str(photo.get("id") or photo.get("photoId") or "")
    caption = str(photo.get("caption") or photo.get("title") or "")
    create_time = _photo_timestamp(photo)
    time_str = (
        datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")
        if create_time
        else ""
    )
    video_url = f"https://www.kuaishou.com/short-video/{photo_id}" if photo_id else ""

    if caption:
        bracket_match = re.findall(r"【(.*?)】", caption)
        for b_name in bracket_match:
            b_clean = clean_product_title(b_name)
            if len(b_clean) >= 4 and not any(
                kw in b_clean for kw in ["视频", "关注", "直播", "感谢", "点赞"]
            ):
                like_count = _kuaishou_photo_like_count(photo)
                return [
                    VideoProductItem(
                        platform="kuaishou",
                        account_name=account_name,
                        account_id=account_id,
                        video_id=photo_id,
                        video_title=caption,
                        video_url=video_url,
                        publish_time=create_time,
                        publish_time_str=time_str,
                        product_id="",
                        product_name=b_name,
                        cleaned_name=b_clean,
                        price="",
                        detail_url="",
                        like_count=like_count,
                    )
                ]

    return []


def _fetch_kuaishou_graphql_api_via_browser(
    page: Any,
    user_id: str,
    pcursor: str = "",
) -> Optional[Dict[str, Any]]:
    """在 Chromium 页面上下文中直接通过 window.fetch 请求快手 GraphQL 接口。"""
    if not hasattr(page, "run_js"):
        return None

    js_code = f"""
    (async () => {{
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 10000);
        try {{
            const userId = {json.dumps(user_id)};
            const pcursor = {json.dumps(pcursor)};
            const payload = {{
                operationName: "visionProfilePhotoList",
                variables: {{
                    userId: userId,
                    pcursor: pcursor,
                    page: "profile"
                }},
                query: `fragment photoContent on PhotoEntity {{
  id
  duration
  caption
  originCaption
  likeCount
  viewCount
  realLikeCount
  commentCount
  timestamp
  postDate
  coverUrl
  photoUrl
  hasShopping
  goodsInfo
}}

query visionProfilePhotoList($pcursor: String, $userId: String, $page: String, $webPageArea: String) {{
  visionProfilePhotoList(pcursor: $pcursor, userId: $userId, page: $page, webPageArea: $webPageArea) {{
    result
    llsid
    webPageArea
    feeds {{
      type
      author {{
        id
        name
        following
        headerUrl
      }}
      photo {{
        ...photoContent
      }}
    }}
    pcursor
    hasMore
  }}
}}`
            }};
            const resp = await window.fetch('/graphql', {{
                method: 'POST',
                headers: {{
                    'content-type': 'application/json',
                    'accept': '*/*'
                }},
                body: JSON.stringify(payload),
                credentials: 'include',
                signal: controller.signal
            }});
            if (!resp.ok) {{
                return {{ ok: false, status: resp.status, error: `HTTP ${{resp.status}}` }};
            }}
            const data = await resp.json();
            return {{ ok: true, data: data }};
        }} catch (err) {{
            return {{ ok: false, error: err.message || String(err) }};
        }} finally {{
            clearTimeout(timer);
        }}
    }})()
    """
    try:
        res = page.run_js(js_code, as_expr=True)
        if isinstance(res, dict) and res.get("ok"):
            return res.get("data")
    except Exception:
        pass
    return None


class KuaishouCrawler:
    """Crawler for Kuaishou account short video e-commerce products."""

    def __init__(
        self,
        browser_manager: BrowserManager,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None,
    ):
        self.browser_manager = browser_manager
        self.log = log_callback or (lambda msg: None)
        self.progress = progress_callback or (lambda status, cur, tot: None)
        self.should_stop = stop_check or (lambda: False)
        # 每个视频的提取诊断，供上层汇总排查「为什么是 0 件」
        self.diagnostics: List[ExtractionDiagnostic] = []
        self.response_issues = []

    def crawl_account(
        self,
        target: AccountTarget,
        time_config: TimeFilterConfig,
        max_scrolls: int = 30,
    ) -> List[VideoProductItem]:
        """
        Crawl videos and e-commerce goods for a single Kuaishou account.
        Filters by time_config and stops scrolling when past start_date.
        """
        previous_diagnostics = list(self.diagnostics)
        target.scraped_videos = target.found_products = 0
        user_id = target.user_id or resolve_kuaishou_url_or_userid(target.url_or_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(user_id or "")):
            user_id = ""
        if not user_id:
            self.log(f"[快手] 无法从账号主页识别有效 user_id: {target.url_or_id}")
            target.status = "解析失败"
            return []

        target.user_id = user_id
        account_name = target.name or user_id[:12]
        self.log(f"[快手] 开始爬取账号: {account_name} (user_id: {user_id})")
        target.status = "爬取中"

        start_ts, end_ts = time_config.get_timestamps()
        profile_url = f"https://www.kuaishou.com/profile/{user_id}"

        page = self.browser_manager.get_page()

        # Listen to GraphQL queries and candidate endpoints
        try:
            page.listen.start(KUAISHOU_LISTEN_TARGETS)
        except Exception:
            try:
                page.listen.start("graphql")
            except Exception:
                pass

        self.log(f"[快手] 正在导航至主页: {profile_url}")
        try:
            page.get(profile_url, timeout=15)
        except TypeError:
            page.get(profile_url)
        except Exception as nav_err:
            self.log(f"[快手] 导航至主页异常: {nav_err}")
            target.status = "导航失败"
            return []
        current_url = getattr(page, "url", profile_url)
        parsed_current = urlsplit(current_url) if isinstance(current_url, str) else None
        visible_id = (
            re.fullmatch(r"/profile/([A-Za-z0-9_-]+)/?", parsed_current.path)
            if parsed_current
            else None
        )
        if parsed_current and (
            (parsed_current.hostname or "").lower()
            not in {"www.kuaishou.com", "kuaishou.com"}
            or not visible_id
            or visible_id.group(1) != user_id
        ):
            target.status = "主页身份未确认"
            self.log("[快手] 当前页面不是目标账号主页，已停止，避免混入其他账号作品。")
            return []
        # Close any overlay login modal if present
        try:
            close_btn = (
                page.ele(".login-dialog-close", timeout=1)
                or page.ele("@class^=close-icon", timeout=0.5)
                or page.ele("@class*=modal-close", timeout=0.5)
            )
            if close_btn:
                close_btn.click()
        except Exception:
            pass

        # Try to extract account nickname
        if not target.name or target.name == user_id[:12]:
            try:
                name_ele = page.ele(".user-name", timeout=1.5) or page.ele(
                    "tag:h1", timeout=1
                )
                if name_ele and name_ele.text:
                    account_name = name_ele.text.strip()
                    target.name = account_name
                    self.log(f"[快手] 获取到账号昵称: {account_name}")
            except Exception:
                pass

        all_products: List[VideoProductItem] = []
        seen_photo_ids: Set[str] = set()
        photo_snapshots = {}
        diagnostics_by_id = {}
        unknown_dates = set()
        wrong_owners = set()
        scroll_count = 0
        consecutive_old_videos = 0
        consecutive_empty_cycles = 0
        hit_time_limit = False

        def _finish(status):
            nonlocal all_products
            if self.should_stop():
                status = "已停止"
            all_products = deduplicate_items(all_products)
            self.diagnostics = previous_diagnostics + list(diagnostics_by_id.values())
            target.status = status
            target.scraped_videos = len(seen_photo_ids)
            target.found_products = len(all_products)
            if wrong_owners:
                if status == "已完成":
                    target.status = "部分完成：作品归属异常"
                self.response_issues.append(
                    {
                        "level": "warning",
                        "code": "account_identity_mismatch",
                        "message": "接口包含其他账号作品，已忽略并标记未完整抓取",
                        "suggestion": "确认当前页面是指定账号主页后重试",
                    }
                )
            if unknown_dates and (start_ts is not None or end_ts is not None):
                if status == "已完成":
                    target.status = "部分完成：有作品日期未确认"
                self.response_issues.append(
                    {
                        "level": "warning",
                        "code": "unknown_publish_time",
                        "message": f"{len(unknown_dates)} 个作品缺少日期，未纳入当前时间筛选",
                        "suggestion": "保留当前结果，稍后重试以补全日期",
                    }
                )
            return all_products

        def _process_photo_items(
            photo_list: List[Dict[str, Any]], *, ordered=False, trusted_scope=True
        ) -> int:
            nonlocal consecutive_old_videos, hit_time_limit
            new_count = 0
            for photo in photo_list:
                if not isinstance(photo, dict):
                    continue
                owner = _photo_owner(photo)
                if owner and owner != user_id:
                    wrong_owners.add(owner)
                    self.log("[快手] 已忽略不属于目标账号的作品。")
                    continue
                if not owner and not trusted_scope:
                    continue
                photo_id = str(photo.get("id") or photo.get("photoId") or "")
                if not photo_id:
                    continue
                previous = photo_snapshots.get(photo_id, {})
                merged = dict(previous)
                for key, value in photo.items():
                    if value not in (None, "", [], {}) and (
                        value != 0 or key not in merged
                    ):
                        merged[key] = value
                if previous == merged:
                    continue
                photo_snapshots[photo_id] = merged
                photo = merged
                already_seen = photo_id in seen_photo_ids
                seen_photo_ids.add(photo_id)
                new_count += 1
                create_time = _photo_timestamp(photo)
                if (start_ts is not None or end_ts is not None) and not create_time:
                    unknown_dates.add(photo_id)
                    continue
                unknown_dates.discard(photo_id)

                # Check end time
                if end_ts and create_time and create_time > end_ts:
                    continue

                # Check start time
                if start_ts and create_time and create_time < start_ts:
                    if (
                        ordered
                        and not already_seen
                        and not (
                            photo.get("isTop")
                            or photo.get("is_top")
                            or photo.get("isPinned")
                        )
                    ):
                        consecutive_old_videos += 1
                        if consecutive_old_videos >= 4:
                            hit_time_limit = True
                            break
                    continue
                else:
                    if ordered and not already_seen:
                        consecutive_old_videos = 0

                item_time_str = (
                    datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")
                    if create_time
                    else ""
                )
                item_video_url = (
                    f"https://www.kuaishou.com/short-video/{photo_id}"
                    if photo_id
                    else ""
                )

                items, diagnostic = extract_products(
                    "kuaishou",
                    photo,
                    account_name,
                    user_id,
                    video_title=str(photo.get("caption") or photo.get("title") or ""),
                    video_url=item_video_url,
                    publish_time=create_time,
                    publish_time_str=item_time_str,
                )
                if not items:
                    # The legacy bracketed-caption fallback must also run in the
                    # actual crawl path, not only through the standalone helper.
                    items = _extract_kuaishou_caption_product(
                        photo, account_name, user_id
                    )
                    if items:
                        diagnostic.extracted = len(items)
                        diagnostic.known_paths_hit.append("caption")
                        diagnostic.note = "根据视频文案中的商品标签回退提取"
                diagnostics_by_id[photo_id] = diagnostic
                all_products[:] = [
                    item for item in all_products if item.video_id != photo_id
                ]
                if not items:
                    self.log(
                        f"  [未提取到商品] {item_video_url} → {diagnostic.summary()}"
                    )
                else:
                    for it in items:
                        all_products.append(it)
                        self.log(
                            f"  [快手发现商品] {account_name} | {it.product_name} "
                            f"({it.price or '未知价'} | 点赞: {it.like_count}) | 视频: {it.video_title[:20]}..."
                        )
            checkpoint = getattr(self, "on_checkpoint", None)
            if callable(checkpoint):
                target.scraped_videos = len(seen_photo_ids)
                target.found_products = len(all_products)
                checkpoint(list(all_products))
            return new_count

        # ── Step 1: Extract initial posts from SSR / state if present ───────
        try:
            ssr_photos = _extract_ssr_photo_list(page)
            if ssr_photos:
                added = _process_photo_items(ssr_photos, trusted_scope=False)
                if added > 0:
                    self.log(f"[快手] SSR 首屏状态成功解析到 {added} 个作品")
        except Exception as ssr_err:
            self.log(f"[快手] SSR 状态解析跳过: {ssr_err}")

        # ── Step 1.5: Direct Chromium GraphQL API Fetching ──────────────────
        try:
            modern_client = (
                page.run_js(
                    "return [...document.querySelectorAll('script[src]')].some(e=>e.src.includes('/ks-web/'))",
                    timeout=3,
                )
                is True
            )
        except Exception:
            modern_client = False
        direct_api_completed = False
        api_pcursor = ""
        api_page_idx = 0
        while not modern_client and api_page_idx < max_scrolls:
            if self.should_stop():
                self.log(f"[快手] 收到用户终止信号，停止爬取 {account_name}")
                return _finish("已停止")

            graphql_data = _fetch_kuaishou_graphql_api_via_browser(
                page, user_id, pcursor=api_pcursor
            )
            if not graphql_data or not isinstance(graphql_data, dict):
                break

            profile_data = _profile_list(graphql_data)
            if profile_data is None:
                break

            feeds = profile_data.get("feeds") or []
            photo_list = _feed_photos(feeds)

            if not photo_list:
                if _at_end(profile_data):
                    direct_api_completed = True
                break

            new_in_page = _process_photo_items(photo_list, ordered=True)
            api_page_idx += 1
            previous_cursor = api_pcursor
            api_pcursor = str(profile_data.get("pcursor") or "")

            self.log(
                f"[快手 API] {account_name} 接口第 {api_page_idx} 页获取到 {len(photo_list)} 个作品 (新增 {new_in_page})，"
                f"累计发现商品 {len(all_products)} 件"
            )

            if hit_time_limit:
                self.log(f"[快手 API] {account_name} 视频时间已超出范围，停止翻页。")
                direct_api_completed = True
                break
            if _at_end(profile_data):
                self.log(f"[快手 API] {account_name} 已到达作品末尾(hasMore=false)。")
                direct_api_completed = True
                break
            if not api_pcursor or api_pcursor == previous_cursor:
                self.log("[快手] 翻页游标未推进，保留当前结果并标记未完整抓取。")
                break

            time.sleep(0.3)

        if direct_api_completed:
            self.log(
                f"[快手] {account_name} 爬取完成（浏览器直接 API 模式），"
                f"有效作品 {len(seen_photo_ids)} 个，提取商品 {len(all_products)} 件"
            )
            return _finish("已完成")

        # ── Step 2: Main scroll & network interception loop (Fallback) ───────
        fallback_completed = False
        while scroll_count + api_page_idx < max_scrolls:
            if self.should_stop():
                self.log(f"[快手] 收到用户终止信号，停止爬取 {account_name}")
                return _finish("已停止")

            # Wait for intercepted packet
            packet = None
            try:
                packet = page.listen.wait(timeout=3.5)
            except Exception:
                pass

            new_photos_in_batch = 0

            if packet and packet.response:
                try:
                    res_json = packet.response.body
                    if isinstance(res_json, str):
                        res_json = json.loads(res_json)

                    photo_list: List[Dict[str, Any]] = []
                    if isinstance(res_json, dict):
                        if res_json.get("result") in (
                            109,
                            "109",
                            152016,
                            "152016",
                            50,
                            "50",
                        ):
                            self.response_issues.append(
                                {
                                    "level": "error",
                                    "code": "kuaishou_login_required",
                                    "message": "快手接口要求登录或安全验证，已停止等待并保留现有数据。",
                                    "suggestion": "在快手登录窗口完成提示后重新抓取；缓存清理不会删除 Cookies。",
                                }
                            )
                            return _finish("需要登录或验证")
                        # Look for visionProfilePhotoList in GraphQL response
                        photo_list_data = _profile_list(res_json)
                        if photo_list_data is None:
                            raise ValueError("响应不是有效的目标主页作品列表")
                        feeds = photo_list_data.get("feeds") or []
                        photo_list = _feed_photos(feeds)
                    else:
                        raise ValueError("响应不是有效JSON对象")

                    new_photos_in_batch = _process_photo_items(photo_list, ordered=True)
                    self.log(
                        f"[快手] {account_name} 已处理 {len(seen_photo_ids)} 个视频，"
                        f"累计发现带货商品 {len(all_products)} 件"
                    )

                    if hit_time_limit:
                        self.log(
                            f"[快手] {account_name} 视频发布时间已超出指定起始日期，自动结束翻页。"
                        )
                        fallback_completed = True
                        break

                    if _at_end(photo_list_data):
                        self.log(f"[快手] {account_name} 已到达作品末尾(no_more)。")
                        fallback_completed = True
                        break

                except Exception as e:
                    self.log(f"[快手] 数据包解析异常: {e}")

            # If no network packet captured, check DOM fallback
            if new_photos_in_batch == 0:
                dom_cards = _extract_kuaishou_dom_video_cards(page)
                if dom_cards:
                    added_dom = _process_photo_items(dom_cards)
                    if added_dom > 0:
                        new_photos_in_batch += added_dom
                        self.log(f"[快手] DOM 回退检测抓取到 {added_dom} 个作品卡片")

            if new_photos_in_batch == 0:
                consecutive_empty_cycles += 1
                try:
                    captcha_ele = (
                        page.ele("@class*=captcha", timeout=0.3)
                        or page.ele("@class*=verify", timeout=0.3)
                        or page.ele("text=请完成安全验证", timeout=0.3)
                        or page.ele("text=滑动验证", timeout=0.3)
                    )
                    if captcha_ele:
                        self.log(
                            "[快手] ⚠ 检测到安全验证或滑块拦截，请在浏览器中完成验证..."
                        )
                except Exception:
                    pass

                if consecutive_empty_cycles >= 2:
                    _trigger_scroll_jitter(page)
                if consecutive_empty_cycles >= 5:
                    self.log(
                        f"[快手] {account_name} 连续多次未收到新数据包，结束该账号抓取。"
                    )
                    break
            else:
                consecutive_empty_cycles = 0

            # Progressive smooth scroll
            scroll_count += 1
            _smooth_scroll_down(page, step_px=750)

        if not fallback_completed:
            self.response_issues.append(
                {
                    "level": "warning",
                    "code": "crawl_incomplete",
                    "message": "快手未确认作品末尾，已保留当前结果",
                    "suggestion": "检查登录/验证状态或提高翻页上限后重试",
                }
            )
        self.log(
            f"[快手] 账号 {account_name} {'已确认末尾' if fallback_completed else '未完整抓取'}，扫描视频数: {len(seen_photo_ids)}, "
            f"提取带货商品: {len(all_products)}"
        )
        return _finish("已完成" if fallback_completed else "部分完成")
