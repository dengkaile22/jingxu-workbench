"""
Douyin account crawler using DrissionPage packet listener, SSR extraction, and DOM fallback.
"""
import time
import json
import re
import urllib.parse
from datetime import datetime
from typing import List, Optional, Callable, Dict, Any, Set

from core.models import VideoProductItem, AccountTarget, TimeFilterConfig
from core.text_utils import clean_product_title, parse_chinese_count_str
from core.browser_manager import BrowserManager, BROWSER_SESSION_ERRORS, BrowserSessionStopped
from core.record_identity import deduplicate_items
from core.extraction import ExtractionDiagnostic, extract_products
from core.account_identity import AccountResolutionError, extract_douyin_sec_uid, resolve_douyin_identity


DOUYIN_LISTEN_TARGETS = [
    "aweme/v1/web/aweme/post",
    "web/aweme/post",
    "aweme/post",
    "web/tab/feed",
    "aweme/v1/web/tab/feed",
]


def resolve_douyin_url_or_secuid(input_str: str) -> str:
    """Compatibility wrapper; never treat a public Douyin handle as a SecUID."""
    try:
        return resolve_douyin_identity(input_str)
    except AccountResolutionError:
        return ""


class DouyinResponseError(ValueError):
    """A safe, actionable response diagnostic without response text or tokens."""

    def __init__(self, code: str, message: str, suggestion: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion


def _decode_douyin_response(body: Any, status: Any = 200, failed: bool = False) -> Dict[str, Any]:
    """Validate both intercepted and directly fetched responses before extraction."""
    if failed:
        raise DouyinResponseError(
            "network_error", "抖音视频请求未成功返回。", "请检查网络连接，稍后重试。"
        )
    if status is not None:
        try:
            http_status = int(status)
        except (TypeError, ValueError):
            http_status = 0
        if not 200 <= http_status < 300:
            raise DouyinResponseError(
                "http_error", f"抖音视频接口返回 HTTP {http_status}。",
                "请检查抖音登录或验证状态，稍后重试。",
            )
    if isinstance(body, (bytes, bytearray)):
        try:
            body = bytes(body).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise DouyinResponseError(
                "invalid_encoding", "抖音视频响应的文本编码无法识别。", "稍后重试获取视频数据。"
            ) from None
    if body is None or (isinstance(body, str) and not body.strip()):
        raise DouyinResponseError(
            "empty_response", "抖音视频接口未返回有效内容。",
            "可能是临时网络问题或需要验证；请检查抖音页面后重试。",
        )
    if isinstance(body, str):
        text = body.lstrip("\ufeff \r\n\t")
        if text.startswith("<"):
            raise DouyinResponseError(
                "html_response", "抖音视频接口返回网页，未取得视频数据。",
                "请在抖音页面检查登录或安全验证，再重试。",
            )
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            raise DouyinResponseError(
                "invalid_json", "抖音视频接口返回的内容不是有效数据。", "请检查抖音页面并稍后重试。"
            ) from None
    if not isinstance(body, dict):
        raise DouyinResponseError(
            "invalid_payload", "抖音视频响应的结构无法识别。", "稍后重试；若持续出现请反馈日志。"
        )
    business_status = body.get("status_code", 0)
    if business_status not in (None, 0, "0"):
        # Do not echo status_msg: platform responses may contain private identifiers.
        raise DouyinResponseError(
            "business_error", "抖音视频接口报告请求未成功。",
            "请检查账号权限、登录或安全验证，稍后重试。",
        )
    awemes: List[Dict[str, Any]] = []
    _find_aweme_items_recursive(body, awemes)
    if "aweme_list" not in body and not awemes:
        raise DouyinResponseError(
            "missing_video_list", "抖音视频响应缺少视频列表。",
            "请检查抖音页面并稍后重试；当前抓取可能不完整。",
        )
    if "aweme_list" in body and not isinstance(body["aweme_list"], list):
        raise DouyinResponseError(
            "invalid_video_list", "抖音返回的视频列表格式异常。", "稍后重试获取视频数据。"
        )
    return body


def _verify_douyin_profile(page: Any, sec_uid: str) -> None:
    """Reject failed redirects without echoing URLs, response content, or tokens."""
    current_url = getattr(page, "url", "")
    if isinstance(current_url, str) and current_url:
        try:
            parsed = urllib.parse.urlsplit(current_url)
        except ValueError:
            raise DouyinResponseError(
                "wrong_profile", "抖音主页地址无法识别。", "请检查账号主页链接后重试。"
            ) from None
        if any(marker in parsed.path.lower() for marker in ("/captcha", "/verify", "/passport", "/login")):
            raise DouyinResponseError(
                "profile_verification", "抖音主页跳转到了登录或验证页面。", "请先完成登录或安全验证，再重新抓取。"
            )
        actual_identity = extract_douyin_sec_uid(current_url)
        if actual_identity != sec_uid:
            raise DouyinResponseError(
                "wrong_profile", "未能打开指定抖音账号的主页。", "已停止抓取，请检查账号主页链接后重试。"
            )
    if hasattr(page, "run_js"):
        try:
            body = page.run_js("return document.body ? document.body.innerText : '';")
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            body = ""
        if isinstance(body, str) and any(marker in body for marker in (
            "安全验证", "请完成验证", "滑块验证", "拖动滑块", "访问过于频繁", "操作过于频繁",
            "请先登录", "登录后查看",
        )):
            raise DouyinResponseError(
                "profile_verification", "抖音主页提示需要登录、验证或稍后重试。",
                "请检查抖音页面并完成提示要求后重新抓取。",
            )


def _find_aweme_items_recursive(node: Any, result: List[Dict[str, Any]], max_depth: int = 8, depth: int = 0) -> None:
    """Safely traverse nested JSON to find aweme objects or aweme_list arrays."""
    if depth > max_depth or not node:
        return
    if isinstance(node, dict):
        if "aweme_id" in node and ("desc" in node or "author" in node or "anchor_info" in node or "statistics" in node):
            result.append(node)
            return
        if "aweme_list" in node and isinstance(node["aweme_list"], list):
            for item in node["aweme_list"]:
                if isinstance(item, dict) and "aweme_id" in item:
                    result.append(item)
            return
        for val in node.values():
            if isinstance(val, (dict, list)):
                _find_aweme_items_recursive(val, result, max_depth, depth + 1)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                _find_aweme_items_recursive(item, result, max_depth, depth + 1)


def _extract_ssr_aweme_list(page: Any) -> List[Dict[str, Any]]:
    """
    Extract initially rendered aweme list from page SSR script tags or JS globals.
    This guarantees capturing the first batch of posts even before network listener catches packets.
    """
    if not hasattr(page, "run_js"):
        return []
    aweme_list: List[Dict[str, Any]] = []
    try:
        # 1. Check RENDER_DATA tag
        render_data_str = page.run_js(
            "return document.getElementById('RENDER_DATA')?.textContent || '';"
        )
        if render_data_str:
            try:
                unquoted = urllib.parse.unquote(render_data_str)
                data_obj = json.loads(unquoted)
                _find_aweme_items_recursive(data_obj, aweme_list)
            except Exception:
                pass

        # 2. Check __UNIVERSAL_DATA_FOR_REHYDRATION__ tag
        if not aweme_list:
            rehyd_str = page.run_js(
                "return document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent || '';"
            )
            if rehyd_str:
                try:
                    data_obj = json.loads(rehyd_str)
                    _find_aweme_items_recursive(data_obj, aweme_list)
                except Exception:
                    pass

        # 3. Check window._ROUTER_DATA
        if not aweme_list:
            router_obj = page.run_js(
                "return (typeof window._ROUTER_DATA !== 'undefined') ? JSON.stringify(window._ROUTER_DATA) : '';"
            )
            if router_obj:
                try:
                    data_obj = json.loads(router_obj)
                    _find_aweme_items_recursive(data_obj, aweme_list)
                except Exception:
                    pass
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:
        pass

    return aweme_list


def _extract_douyin_dom_video_cards(page: Any) -> List[Dict[str, Any]]:
    """
    Extract video cards directly from rendered DOM when network packets are missed or delayed.
    Finds <a> elements linking to /video/{aweme_id}.
    """
    if not hasattr(page, "eles"):
        return []
    cards: List[Dict[str, Any]] = []
    try:
        eles = page.eles("tag:a@href*=/video/")
        for ele in eles:
            try:
                href = ele.attr("href") or ""
                m = re.search(r"/video/(\d+)", href)
                if not m:
                    continue
                aweme_id = m.group(1)
                text = ele.text or ""

                # Try to find like count badge
                like_cnt = 0
                like_ele = ele.ele("@class*=like", timeout=0.1) or ele.ele("tag:span", timeout=0.1)
                if like_ele and like_ele.text:
                    like_cnt = parse_chinese_count_str(like_ele.text)

                # Check if this card has an e-commerce / shopping cart badge
                has_cart = False
                cart_ele = (
                    ele.ele("@class*=cart", timeout=0.1)
                    or ele.ele("@class*=shop", timeout=0.1)
                    or ele.ele("@class*=goods", timeout=0.1)
                    or ele.ele("tag:svg", timeout=0.1)
                )
                if cart_ele:
                    has_cart = True

                desc = ele.attr("title") or (text.split("\n")[0] if text else "")

                cards.append({
                    "aweme_id": aweme_id,
                    "desc": desc,
                    "create_time": 0,
                    "statistics": {"digg_count": like_cnt},
                    "_has_cart_indicator": has_cart,
                    "_from_dom": True,
                })
            except BROWSER_SESSION_ERRORS:
                raise
            except Exception:
                continue
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:
        pass
    return cards


def _smooth_scroll_down(page: Any, step_px: int = 700) -> None:
    """Progressively scroll page down to reliably trigger IntersectionObserver."""
    if hasattr(page, "run_js"):
        try:
            page.run_js(f"window.scrollBy({{top: {step_px}, behavior: 'smooth'}});")
            return
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            pass
    if hasattr(page, "scroll"):
        try:
            if hasattr(page.scroll, "down"):
                page.scroll.down(step_px)
            elif hasattr(page.scroll, "to_bottom"):
                page.scroll.to_bottom()
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            pass


def _trigger_scroll_jitter(page: Any) -> None:
    """Slight upward and downward jitter to shake stubborn IntersectionObservers."""
    if hasattr(page, "run_js"):
        try:
            page.run_js("window.scrollBy({top: -220, behavior: 'smooth'}); window.scrollBy({top: 450, behavior: 'smooth'});")
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            pass


def extract_douyin_products_from_aweme(
    item: Dict[str, Any],
    account_name: str,
    account_id: str
) -> List[VideoProductItem]:
    """Extract e-commerce goods from a single Douyin aweme item using unified extraction pipeline."""
    aweme_id = str(item.get("aweme_id") or "")
    desc = str(item.get("desc") or "")
    create_time = item.get("create_time") or 0
    time_str = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S") if create_time else ""
    video_url = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""
    author_nickname = item.get("author", {}).get("nickname") or account_name

    items, _ = extract_products(
        "douyin",
        item,
        author_nickname,
        account_id,
        video_title=desc,
        video_url=video_url,
        publish_time=create_time,
        publish_time_str=time_str,
    )
    return items


def _fetch_douyin_post_api_via_browser(
    page: Any,
    sec_uid: str,
    max_cursor: int = 0,
    count: int = 20,
    issue_callback: Optional[Callable[[DouyinResponseError], None]] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch in the existing page context and validate without logging private data."""
    if not hasattr(page, "run_js"):
        return None

    js_code = f"""
    (async () => {{
        try {{
            const secUid = {json.dumps(sec_uid)};
            const cursor = {max_cursor};
            const count = {count};
            const params = new URLSearchParams({{
                device_platform: 'webapp',
                aid: '6383',
                channel: 'channel_pc_web',
                sec_user_id: secUid,
                max_cursor: String(cursor),
                count: String(count),
                locate_item_id: '',
                locate_query: 'false',
                show_live: '1',
                publish_video_strategy_type: '2',
                pc_client_type: '1',
                version_code: '170400',
                version_name: '17.4.0',
                cookie_enabled: 'true',
                screen_width: String(window.innerWidth || 1920),
                screen_height: String(window.innerHeight || 1080),
                browser_language: 'zh-CN',
                browser_platform: 'Win32',
                browser_name: 'Chrome',
                browser_version: '126.0.0.0',
                browser_online: 'true',
                engine_name: 'Blink',
                engine_version: '126.0.0.0',
                os_name: 'Windows',
                os_version: '10',
                cpu_core_num: '8',
                device_memory: '8',
                platform: 'PC',
                downlink: '10',
                effective_type: '4g',
                round_trip_time: '50'
            }});
            const url = `/aweme/v1/web/aweme/post/?${{params.toString()}}`;
            const resp = await window.fetch(url, {{
                headers: {{
                    'accept': 'application/json, text/plain, */*',
                    'accept-language': 'zh-CN,zh;q=0.9',
                }},
                referrer: window.location.href,
                credentials: 'include'
            }});
            if (!resp.ok) {{
                return {{ ok: false, status: resp.status, code: 'http_error' }};
            }}
            return {{ ok: true, status: resp.status, body: await resp.text() }};
        }} catch (err) {{
            return {{ ok: false, code: 'network_error' }};
        }}
    }})()
    """
    try:
        res = page.run_js(js_code, as_expr=True)
        if isinstance(res, dict):
            if res.get("ok"):
                return _decode_douyin_response(res.get("body", res.get("data")), res.get("status", 200))
            if res.get("code") == "http_error" or res.get("status") is not None:
                _decode_douyin_response(None, res.get("status", 0))
        raise DouyinResponseError(
            "network_error", "浏览器未能获取抖音视频接口数据。", "请检查网络和抖音页面，稍后重试。"
        )
    except DouyinResponseError as issue:
        if issue_callback:
            issue_callback(issue)
    except BROWSER_SESSION_ERRORS:
        raise
    except Exception:
        if issue_callback:
            issue_callback(DouyinResponseError(
                "browser_request_error", "浏览器视频请求未能执行。", "请检查抖音页面并重新抓取。"
            ))
    return None


class DouyinCrawler:
    """Crawler for Douyin account short video e-commerce products."""

    def __init__(
        self,
        browser_manager: BrowserManager,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None
    ):
        self.browser_manager = browser_manager
        self.log = log_callback or (lambda msg: None)
        self.progress = progress_callback or (lambda status, cur, tot: None)
        self.should_stop = stop_check or (lambda: False)
        # 每个视频的提取诊断，供上层汇总排查「为什么是 0 件」
        self.diagnostics: List[ExtractionDiagnostic] = []
        self.response_issues: List[Dict[str, str]] = []
        self._seen_accounts: Set[str] = set()

    def _record_issue(self, issue: DouyinResponseError) -> None:
        diagnostic = {
            "level": "warning", "code": issue.code,
            "message": issue.message, "suggestion": issue.suggestion,
        }
        # Keep repeated retry failures readable while preserving each error kind.
        if not self.response_issues or self.response_issues[-1] != diagnostic:
            self.response_issues.append(diagnostic)
            self.log(f"[抖音] {issue.message} {issue.suggestion}")

    def crawl_account(
        self,
        target: AccountTarget,
        time_config: TimeFilterConfig,
        max_scrolls: int = 30
    ) -> List[VideoProductItem]:
        """Recover one unexpected disconnect while retaining confirmed records."""
        retained: List[VideoProductItem] = []
        self.partial_items = []
        target.scraped_videos = 0
        target.found_products = 0
        checkpoint = getattr(self, "on_checkpoint", None)
        self._active_video_ids: Set[str] = set()
        diagnostics_start = len(self.diagnostics)

        def save(items):
            nonlocal retained
            # A retry can replace an SSR title-only product with a full ID.
            # Reconcile that enrichment without counting it as another product.
            by_id = {(item.video_id, item.product_id): item for item in retained if item.product_id}
            by_name = {}
            for item in retained:
                name = item.cleaned_name or clean_product_title(item.product_name)
                by_name.setdefault((item.video_id, name), []).append(item)
            for item in items:
                name = item.cleaned_name or clean_product_title(item.product_name)
                existing = by_id.get((item.video_id, item.product_id)) if item.product_id else None
                if existing is None and item.video_id and name:
                    existing = next((candidate for candidate in by_name.get((item.video_id, name), ())
                                     if not candidate.product_id or not item.product_id
                                     or candidate.product_id == item.product_id), None)
                if existing is None:
                    retained.append(item)
                    by_name.setdefault((item.video_id, name), []).append(item)
                    existing = item
                else:
                    existing.like_count = max(existing.like_count, item.like_count)
                    for field in ("product_id", "product_name", "cleaned_name", "price", "detail_url", "cover_url",
                                  "publish_time", "publish_time_str", "video_title"):
                        value = getattr(item, field)
                        if value:
                            setattr(existing, field, value)
                if existing.product_id:
                    by_id[(existing.video_id, existing.product_id)] = existing
            retained = deduplicate_items(retained)
            target.scraped_videos = len(self._active_video_ids)
            target.found_products = len(retained)
            if callable(checkpoint):
                checkpoint(list(retained))

        self.on_checkpoint = save
        try:
            for attempt in range(2):
                if self.should_stop():
                    target.status = "已停止"
                    break
                try:
                    save(self._crawl_account_once(
                        target, time_config, max_scrolls, force_new=bool(attempt)
                    ))
                    break
                except BROWSER_SESSION_ERRORS as error:
                    if isinstance(error, BrowserSessionStopped) or self.should_stop():
                        target.status = "已停止"
                        break
                    if attempt == 0:
                        self._seen_accounts.discard(target.sec_uid)
                        self.log("[抖音] 页面连接已断开，保留已抓数据并尝试恢复一次；Cookies 与登录资料保留。")
                    else:
                        self._record_issue(DouyinResponseError(
                            "page_disconnected", "抖音页面连接断开，恢复后仍未能继续抓取。",
                            "已保留取得的数据并继续其他账号；请检查浏览器或网络后重试该账号。",
                        ))
                        target.status = "部分完成" if retained else "抓取失败"
                except Exception:
                    # Let the CLI isolate unexpected failures, with access to
                    # confirmed rows even if recovery/startup itself fails.
                    self.partial_items = list(retained)
                    raise
            # Retrying from the profile re-observes videos; count each once.
            merged_diagnostics = {}
            for diagnostic in self.diagnostics[diagnostics_start:]:
                old = merged_diagnostics.get(diagnostic.video_id)
                if old is None or diagnostic.extracted >= old.extracted:
                    merged_diagnostics[diagnostic.video_id] = diagnostic
            self.diagnostics[diagnostics_start:] = merged_diagnostics.values()
            target.scraped_videos = len(self._active_video_ids)
            target.found_products = len(retained)
            self.partial_items = list(retained)
            return retained
        finally:
            self.on_checkpoint = checkpoint

    def _crawl_account_once(
        self, target: AccountTarget, time_config: TimeFilterConfig, max_scrolls: int,
        *, force_new: bool = False,
    ) -> List[VideoProductItem]:
        """
        Crawl videos and e-commerce goods for a single Douyin account.
        Filters by time_config and stops scrolling when past start_date.
        """
        target.scraped_videos = 0
        target.found_products = 0
        page = self.browser_manager.get_page(force_new=True) if force_new else self.browser_manager.get_page()
        if self.should_stop():
            target.status = "已停止"
            return []
        try:
            sec_uid = resolve_douyin_identity(target.sec_uid or target.url_or_id, page=page, log=self.log)
        except AccountResolutionError as error:
            self.log(f"[抖音] 账号解析失败：{error}")
            target.status = "解析失败"
            return []

        target.sec_uid = sec_uid
        if sec_uid in self._seen_accounts:
            target.status = "重复账号，已跳过"
            self.log("[抖音] 检测到同一账号的重复入口，已跳过，避免重复计数。")
            return []
        self._seen_accounts.add(sec_uid)
        account_name = target.name or sec_uid[:12]
        self.log(f"[抖音] 开始爬取账号: {account_name}")
        target.status = "爬取中"

        start_ts, end_ts = time_config.get_timestamps()
        profile_url = f"https://www.douyin.com/user/{sec_uid}"

        # Start CDP listening with multiple endpoint candidates
        try:
            page.listen.start(DOUYIN_LISTEN_TARGETS)
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            try:
                page.listen.start("aweme/v1/web/aweme/post")
            except BROWSER_SESSION_ERRORS:
                raise
            except Exception:
                pass

        self.log(f"[抖音] 正在导航至主页: {profile_url}")
        try:
            try:
                navigation_result = page.get(profile_url, timeout=15)
            except TypeError:
                navigation_result = page.get(profile_url)
            if navigation_result is False:
                raise DouyinResponseError(
                    "navigation_error", "抖音账号主页加载失败。", "请检查网络后重试。"
                )
        except DouyinResponseError as issue:
            self._record_issue(issue)
            target.status = "抓取失败"
            return []
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            self._record_issue(DouyinResponseError(
                "navigation_error", "抖音账号主页打开异常。", "请检查网络或登录状态。"
            ))
            target.status = "抓取失败"
            return []

        time.sleep(1.8)

        # Close any overlay login modal if present
        try:
            close_btn = (
                page.ele(".login-guide-close", timeout=1)
                or page.ele("@class^=login-close", timeout=0.5)
                or page.ele("@class*=modal-close", timeout=0.5)
            )
            if close_btn:
                close_btn.click()
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            pass

        try:
            _verify_douyin_profile(page, sec_uid)
        except DouyinResponseError as issue:
            self._record_issue(issue)
            target.status = "抓取失败"
            return []

        # Try to extract account nickname from page if not set
        if not target.name or target.name == sec_uid[:12]:
            try:
                name_ele = page.ele("tag:h1", timeout=1.5) or page.ele("@class^=account-name", timeout=1)
                if name_ele and name_ele.text:
                    account_name = name_ele.text.strip()
                    target.name = account_name
                    self.log(f"[抖音] 获取到账号昵称: {account_name}")
            except BROWSER_SESSION_ERRORS:
                raise
            except Exception:
                pass

        all_products: List[VideoProductItem] = []
        seen_aweme_ids: Set[str] = set()
        scroll_count = 0
        consecutive_old_videos = 0
        consecutive_empty_cycles = 0
        hit_time_limit = False
        dom_seen_ids: Set[str] = set()
        pending_time_ids: Set[str] = set()
        time_checked_ids: Set[str] = set()
        diagnostic_indices: Dict[str, int] = {}
        product_indices: Dict[tuple[str, str], int] = {}
        product_name_indices: Dict[tuple[str, str], int] = {}

        def _finish(status: str) -> List[VideoProductItem]:
            target.status = status
            target.scraped_videos = len(seen_aweme_ids)
            target.found_products = len(all_products)
            self.log(
                f"[抖音] {account_name} {status}：扫描视频 {target.scraped_videos} 个，"
                f"提取带货商品 {target.found_products} 件。"
            )
            return all_products

        def _finish_complete() -> List[VideoProductItem]:
            if pending_time_ids:
                self._record_issue(DouyinResponseError(
                    "incomplete_video_data", "已到本次抓取边界，但部分视频仍缺少必要的发布时间。",
                    "已保留可确认符合条件的数据；请重新抓取以补全时间筛选结果。",
                ))
                return _finish("部分完成")
            return _finish("已完成")

        def _matching_awemes(aweme_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            matches = []
            for aweme in aweme_list:
                if not isinstance(aweme, dict):
                    continue
                author = aweme.get("author")
                author_sec_uid = author.get("sec_uid") if isinstance(author, dict) else None
                if author_sec_uid and str(author_sec_uid) != sec_uid:
                    self._record_issue(DouyinResponseError(
                        "wrong_account", "已忽略不属于当前账号的视频响应。",
                        "页面可能返回了其他账号或推荐内容，已避免混入选品结果。",
                    ))
                    continue
                matches.append(aweme)
            return matches

        def _payload_awemes(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
            awemes: List[Dict[str, Any]] = []
            if isinstance(payload.get("aweme_list"), list):
                awemes = payload["aweme_list"]
            else:
                _find_aweme_items_recursive(payload, awemes)
            matches = _matching_awemes(awemes)
            if awemes and not matches:
                raise DouyinResponseError(
                    "wrong_account", "本次视频响应不属于当前账号。", "已忽略该响应并继续等待当前账号数据。"
                )
            return matches

        def _process_aweme_items(aweme_list: List[Dict[str, Any]]) -> int:
            nonlocal consecutive_old_videos, hit_time_limit
            new_count = 0
            for aweme in _matching_awemes(aweme_list):
                aweme_id = str(aweme.get("aweme_id") or "")
                if not aweme_id:
                    continue
                first_visit = aweme_id not in seen_aweme_ids
                seen_aweme_ids.add(aweme_id)
                self._active_video_ids.add(aweme_id)
                if first_visit:
                    new_count += 1

                try:
                    create_time = int(aweme.get("create_time") or 0)
                except (TypeError, ValueError):
                    create_time = 0
                is_top = aweme.get("is_top") or 0

                if (start_ts or end_ts) and not create_time:
                    if aweme_id in time_checked_ids:
                        continue
                    pending_time_ids.add(aweme_id)
                    self._record_issue(DouyinResponseError(
                        "missing_publish_time", "部分视频缺少发布时间，已暂不纳入时间筛选结果。",
                        "请重新抓取以获取完整视频信息。",
                    ))
                    continue
                pending_time_ids.discard(aweme_id)

                # Check end time
                if end_ts and create_time and create_time > end_ts:
                    time_checked_ids.add(aweme_id)
                    continue

                # Check start time
                if start_ts and create_time and create_time < start_ts:
                    if not is_top and aweme_id not in time_checked_ids:
                        consecutive_old_videos += 1
                        time_checked_ids.add(aweme_id)
                        if consecutive_old_videos >= 4:
                            hit_time_limit = True
                            break
                    continue
                else:
                    if not is_top and aweme_id not in time_checked_ids:
                        consecutive_old_videos = 0

                try:
                    item_time_str = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S") if create_time else ""
                except (OSError, OverflowError, ValueError):
                    pending_time_ids.add(aweme_id)
                    self._record_issue(DouyinResponseError(
                        "invalid_publish_time", "部分视频的发布时间无效，已忽略该视频。", "请重新抓取完整数据。"
                    ))
                    continue
                time_checked_ids.add(aweme_id)
                item_video_url = (
                    f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""
                )

                items, diagnostic = extract_products(
                    "douyin",
                    aweme,
                    account_name,
                    sec_uid,
                    video_title=str(aweme.get("desc") or ""),
                    video_url=item_video_url,
                    publish_time=create_time,
                    publish_time_str=item_time_str,
                )
                if aweme_id not in diagnostic_indices:
                    diagnostic_indices[aweme_id] = len(self.diagnostics)
                    self.diagnostics.append(diagnostic)
                else:
                    diagnostic_index = diagnostic_indices[aweme_id]
                    if diagnostic.extracted >= self.diagnostics[diagnostic_index].extracted:
                        self.diagnostics[diagnostic_index] = diagnostic
                if not items:
                    self.log(f"  [未提取到商品] {item_video_url} → {diagnostic.summary()}")
                else:
                    for it in items:
                        product_identity = (aweme_id, it.product_id or it.cleaned_name or clean_product_title(it.product_name))
                        name_identity = (aweme_id, it.cleaned_name or clean_product_title(it.product_name))
                        item_index = product_indices.get(product_identity)
                        if item_index is None:
                            candidate_index = product_name_indices.get(name_identity)
                            if candidate_index is not None:
                                candidate = all_products[candidate_index]
                                if not candidate.product_id or not it.product_id or candidate.product_id == it.product_id:
                                    item_index = candidate_index
                        if item_index is not None:
                            existing = all_products[item_index]
                            existing.like_count = max(existing.like_count, it.like_count)
                            for field in ("product_id", "product_name", "cleaned_name", "price", "detail_url", "cover_url", "publish_time", "publish_time_str", "video_title"):
                                value = getattr(it, field)
                                if value:
                                    setattr(existing, field, value)
                            product_indices[product_identity] = item_index
                            product_name_indices[name_identity] = item_index
                            continue
                        item_index = len(all_products)
                        all_products.append(it)
                        product_indices[product_identity] = item_index
                        product_name_indices[name_identity] = item_index
                        if not first_visit:
                            new_count += 1
                        self.log(
                            f"  [发现商品] {account_name} | {it.product_name} "
                            f"({it.price or '未知价'} | 点赞: {it.like_count}) | 视频: {it.video_title[:20]}..."
                        )
            checkpoint = getattr(self, 'on_checkpoint', None)
            if callable(checkpoint):
                target.scraped_videos = len(seen_aweme_ids)
                target.found_products = len(all_products)
                checkpoint(list(all_products))
            return new_count

        # ── Step 1: Extract initial posts from SSR if present ───────────────
        try:
            ssr_awemes = _extract_ssr_aweme_list(page)
            if ssr_awemes:
                added = _process_aweme_items(ssr_awemes)
                if added > 0:
                    self.log(f"[抖音] SSR 首屏成功解析到 {added} 个视频")
        except BROWSER_SESSION_ERRORS:
            raise
        except Exception:
            self._record_issue(DouyinResponseError(
                "ssr_read_error", "账号首屏视频数据读取失败。", "正在等待视频接口数据恢复。"
            ))
        if hit_time_limit:
            return _finish_complete()

        # Direct requests retry the same cursor at most three times. A successful
        # first page never proves completeness if a later request fails.
        api_cursor = 0
        api_page_idx = 0
        page_limit = max(0, int(max_scrolls))
        while api_page_idx < page_limit:
            if self.should_stop():
                return _finish("已停止")
            api_payload = None
            aweme_list: List[Dict[str, Any]] = []
            for attempt in range(3):
                if self.should_stop():
                    return _finish("已停止")
                api_payload = _fetch_douyin_post_api_via_browser(
                    page, sec_uid, max_cursor=api_cursor, count=20,
                    issue_callback=self._record_issue,
                )
                if api_payload is not None:
                    try:
                        aweme_list = _payload_awemes(api_payload)
                        break
                    except DouyinResponseError as issue:
                        self._record_issue(issue)
                        api_payload = None
                if not hasattr(page, "run_js"):
                    break
                if attempt < 2:
                    time.sleep(0.3)
            if api_payload is None:
                break

            new_in_page = _process_aweme_items(aweme_list)
            api_page_idx += 1
            self.log(
                f"[抖音 API] {account_name} 第 {api_page_idx} 页：视频 {len(aweme_list)} 个，"
                f"新增 {new_in_page} 个，累计商品 {len(all_products)} 件。"
            )
            if hit_time_limit or api_payload.get("has_more") in (0, "0", False):
                return _finish_complete()
            next_cursor = api_payload.get("max_cursor")
            if not aweme_list or next_cursor in (None, "", 0, "0") or str(next_cursor) == str(api_cursor):
                self._record_issue(DouyinResponseError(
                    "pagination_stalled", "抖音视频翻页未继续，尚未确认到达末尾。",
                    "正在等待页面数据；若未恢复，将保留已抓结果并标记未完整抓取。",
                ))
                break
            try:
                api_cursor = int(next_cursor)
            except (TypeError, ValueError):
                self._record_issue(DouyinResponseError(
                    "invalid_cursor", "抖音视频翻页位置无效。", "正在等待页面数据，请稍后重试完整抓取。"
                ))
                break
            time.sleep(0.3)

        # Listen for recovery, including successful data that arrives after a DOM
        # card. DOM discovery has its own IDs and cannot replace complete records.
        consecutive_invalid_responses = 0
        remaining_pages = page_limit - api_page_idx
        while scroll_count < remaining_pages:
            if self.should_stop():
                return _finish("已停止")
            packet = None
            try:
                packet = page.listen.wait(timeout=3.5)
            except BROWSER_SESSION_ERRORS:
                raise
            except Exception:
                self._record_issue(DouyinResponseError(
                    "listener_error", "等待抖音视频数据时出现异常。", "请检查抖音页面或网络连接。"
                ))
            new_videos_in_batch = 0
            if packet:
                try:
                    if getattr(packet, "is_failed", False):
                        _decode_douyin_response(None, failed=True)
                    response = packet.response
                    res_json = _decode_douyin_response(
                        response.body, status=getattr(response, "status", None)
                    )
                    aweme_list = _payload_awemes(res_json)
                    consecutive_invalid_responses = 0
                    new_videos_in_batch = _process_aweme_items(aweme_list)
                    if hit_time_limit or res_json.get("has_more") in (0, "0", False):
                        return _finish_complete()
                except DouyinResponseError as issue:
                    self._record_issue(issue)
                    consecutive_invalid_responses += 1
                except BROWSER_SESSION_ERRORS:
                    raise
                except Exception:
                    self._record_issue(DouyinResponseError(
                        "packet_read_error", "抖音视频响应读取失败。", "请检查网络并稍后重试。"
                    ))
                    consecutive_invalid_responses += 1

            if new_videos_in_batch == 0:
                dom_cards = _extract_douyin_dom_video_cards(page)
                new_dom_ids = {
                    str(card.get("aweme_id")) for card in dom_cards if card.get("aweme_id")
                } - dom_seen_ids
                if new_dom_ids:
                    dom_seen_ids.update(new_dom_ids)
                    self.log(f"[抖音] 页面发现 {len(new_dom_ids)} 个视频卡片，等待完整视频及商品数据。")

            if new_videos_in_batch == 0:
                consecutive_empty_cycles += 1
                if consecutive_empty_cycles % 2 == 0:
                    _trigger_scroll_jitter(page)
            else:
                consecutive_empty_cycles = 0
            if consecutive_invalid_responses >= 3:
                self._record_issue(DouyinResponseError(
                    "response_retry_limit", "抖音视频数据连续三次无效，已结束本次重试。",
                    "请检查登录、验证或网络后重新抓取；已获取的数据会保留。",
                ))
                break
            if consecutive_empty_cycles >= 5:
                self._record_issue(DouyinResponseError(
                    "no_new_videos", "连续多次未获取到新视频，尚未确认账号视频末尾。",
                    "已保留当前数据，请重新抓取以确认完整结果。",
                ))
                break
            scroll_count += 1
            _smooth_scroll_down(page, step_px=750)
            time.sleep(1.2)

        if scroll_count >= remaining_pages:
            self._record_issue(DouyinResponseError(
                "page_limit", "已达到本次视频翻页上限，尚未确认账号视频末尾。",
                "可增加抓取上限后重新抓取，已获取的数据会保留。",
            ))
        return _finish("部分完成" if seen_aweme_ids else "抓取失败")
