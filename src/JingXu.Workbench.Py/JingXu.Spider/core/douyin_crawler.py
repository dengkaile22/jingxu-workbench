"""
Douyin account crawler using DrissionPage packet listener.
"""
import os
import time
import json
import re
from datetime import datetime
from typing import List, Optional, Callable, Dict, Any
import requests

from core.models import VideoProductItem, AccountTarget, TimeFilterConfig
from core.text_utils import clean_product_title
from core.browser_manager import BrowserManager
from core.extraction import ExtractionDiagnostic, extract_products


def resolve_douyin_url_or_secuid(input_str: str) -> str:
    """
    Parse Douyin input string (short link, full URL, or sec_uid) into sec_uid.
    """
    input_str = input_str.strip()
    if not input_str:
        return ""

    # Check if it is a short link like https://v.douyin.com/xxx/
    if "v.douyin.com" in input_str:
        try:
            match = re.search(r"https?://v\.douyin\.com/[a-zA-Z0-9_\-]+/?", input_str)
            target_short = match.group(0) if match else input_str
            resp = requests.get(target_short, allow_redirects=True, timeout=8, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            input_str = resp.url
        except Exception:
            pass

    # Match sec_user_id or sec_uid in URL
    match = re.search(r"user/([a-zA-Z0-9_\-]+)", input_str)
    if match:
        return match.group(1)

    match2 = re.search(r"sec_uid=([a-zA-Z0-9_\-]+)", input_str)
    if match2:
        return match2.group(1)

    # If it starts with MS4wLjABAAAA, it's directly a sec_uid
    if input_str.startswith("MS4wLjABAAAA"):
        return input_str

    return input_str


def extract_douyin_products_from_aweme(
    item: Dict[str, Any],
    account_name: str,
    account_id: str
) -> List[VideoProductItem]:
    """Extract e-commerce goods from a single Douyin aweme item."""
    products: List[VideoProductItem] = []

    aweme_id = str(item.get("aweme_id") or "")
    desc = item.get("desc") or ""
    create_time = item.get("create_time") or 0
    time_str = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S") if create_time else ""
    video_url = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""
    author_nickname = item.get("author", {}).get("nickname") or account_name

    # 1. Check anchor_info (小黄车/商品锚点)
    anchor_info = item.get("anchor_info") or {}
    if anchor_info:
        anchor_title = anchor_info.get("title") or ""
        anchor_name = anchor_info.get("name") or ""
        extra_str = anchor_info.get("extra") or ""
        product_title = ""
        product_id = ""
        price_str = ""
        detail_url = ""

        if extra_str:
            try:
                extra_data = json.loads(extra_str)
                product_title = extra_data.get("title") or extra_data.get("name") or ""
                product_id = str(extra_data.get("product_id") or extra_data.get("promotion_id") or "")
                price_val = extra_data.get("price")
                if price_val:
                    if isinstance(price_val, (int, float)) and price_val > 100:
                        price_str = f"¥{price_val / 100:.2f}"
                    else:
                        price_str = f"¥{price_val}"
                detail_url = extra_data.get("detail_url") or extra_data.get("jump_url") or ""
            except Exception:
                pass

        if not product_title:
            product_title = anchor_name or anchor_title

        if product_title:
            cleaned = clean_product_title(product_title)
            products.append(VideoProductItem(
                platform="douyin",
                account_name=author_nickname,
                account_id=account_id,
                video_id=aweme_id,
                video_title=desc,
                video_url=video_url,
                publish_time=create_time,
                publish_time_str=time_str,
                product_id=product_id,
                product_name=product_title,
                cleaned_name=cleaned,
                price=price_str,
                detail_url=detail_url,
            ))

    # 2. Check promotions
    promotions = item.get("promotions") or []
    for promo in promotions:
        p_title = promo.get("title") or promo.get("name") or ""
        if not p_title:
            continue
        p_id = str(promo.get("goods_id") or promo.get("promotion_id") or "")
        p_price = promo.get("price")
        price_str = ""
        if p_price:
            if isinstance(p_price, (int, float)) and p_price > 100:
                price_str = f"¥{p_price / 100:.2f}"
            else:
                price_str = f"¥{p_price}"

        # Avoid duplicate if anchor_info already captured it
        if not any(p.product_id == p_id or p.product_name == p_title for p in products):
            products.append(VideoProductItem(
                platform="douyin",
                account_name=author_nickname,
                account_id=account_id,
                video_id=aweme_id,
                video_title=desc,
                video_url=video_url,
                publish_time=create_time,
                publish_time_str=time_str,
                product_id=p_id,
                product_name=p_title,
                cleaned_name=clean_product_title(p_title),
                price=price_str,
                detail_url=promo.get("detail_url") or promo.get("jump_url") or "",
            ))

    # 3. Check anchors list
    anchors = item.get("anchors") or []
    for anc in anchors:
        anc_info = anc.get("anchor_info")
        if isinstance(anc_info, str) and anc_info:
            try:
                anc_dict = json.loads(anc_info)
                anc_title = anc_dict.get("title") or anc_dict.get("name") or ""
                if anc_title and not any(p.product_name == anc_title for p in products):
                    products.append(VideoProductItem(
                        platform="douyin",
                        account_name=author_nickname,
                        account_id=account_id,
                        video_id=aweme_id,
                        video_title=desc,
                        video_url=video_url,
                        publish_time=create_time,
                        publish_time_str=time_str,
                        product_id=str(anc_dict.get("product_id") or ""),
                        product_name=anc_title,
                        cleaned_name=clean_product_title(anc_title),
                        price="",
                        detail_url="",
                    ))
            except Exception:
                pass

    return products


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

    def crawl_account(
        self,
        target: AccountTarget,
        time_config: TimeFilterConfig,
        max_scrolls: int = 30
    ) -> List[VideoProductItem]:
        """
        Crawl videos and e-commerce goods for a single Douyin account.
        Filters by time_config and stops scrolling when past start_date.
        """
        sec_uid = resolve_douyin_url_or_secuid(target.url_or_id or target.sec_uid)
        if not sec_uid:
            self.log(f"[抖音] 无法从账号主页识别有效 sec_uid: {target.url_or_id}")
            target.status = "解析失败"
            return []

        target.sec_uid = sec_uid
        account_name = target.name or sec_uid[:12]
        self.log(f"[抖音] 开始爬取账号: {account_name} (sec_uid: {sec_uid})")
        target.status = "爬取中"

        start_ts, end_ts = time_config.get_timestamps()
        profile_url = f"https://www.douyin.com/user/{sec_uid}"

        page = self.browser_manager.get_page()

        # Start CDP listening for post list packet
        packet_api = "aweme/v1/web/aweme/post"
        try:
            page.listen.start(packet_api)
        except Exception:
            pass

        self.log(f"[抖音] 正在导航至主页: {profile_url}")
        page.get(profile_url)
        time.sleep(2)

        # Close any overlay login modal if present
        try:
            close_btn = page.ele('.login-guide-close', timeout=1.5) or page.ele('@class^=login-close', timeout=0.5)
            if close_btn:
                close_btn.click()
        except Exception:
            pass

        # Try to extract account nickname from page if not set
        if not target.name or target.name == sec_uid[:12]:
            try:
                name_ele = page.ele('tag:h1', timeout=2) or page.ele('@class^=account-name', timeout=1)
                if name_ele and name_ele.text:
                    account_name = name_ele.text.strip()
                    target.name = account_name
                    self.log(f"[抖音] 获取到账号昵称: {account_name}")
            except Exception:
                pass

        all_products: List[VideoProductItem] = []
        seen_aweme_ids = set()
        scroll_count = 0
        consecutive_old_videos = 0
        hit_time_limit = False

        while scroll_count < max_scrolls:
            if self.should_stop():
                self.log(f"[抖音] 收到用户终止信号，停止爬取 {account_name}")
                target.status = "已停止"
                break

            # Wait for intercepted packet（监听已按 packet_api 过滤，wait 不接受 targets 参数）
            packet = None
            try:
                packet = page.listen.wait(timeout=6)
            except Exception:
                pass

            if packet and packet.response:
                try:
                    res_json = packet.response.body
                    if isinstance(res_json, str):
                        res_json = json.loads(res_json)

                    aweme_list = res_json.get("aweme_list") or []
                    has_more = res_json.get("has_more", 0)

                    new_videos_in_batch = 0
                    for aweme in aweme_list:
                        aweme_id = str(aweme.get("aweme_id") or "")
                        if not aweme_id or aweme_id in seen_aweme_ids:
                            continue

                        seen_aweme_ids.add(aweme_id)
                        new_videos_in_batch += 1

                        create_time = aweme.get("create_time") or 0
                        is_top = aweme.get("is_top") or 0

                        # Check end time
                        if end_ts and create_time > end_ts:
                            continue

                        # Check start time
                        if start_ts and create_time < start_ts:
                            if not is_top:
                                consecutive_old_videos += 1
                                # If we encounter 4 consecutive non-top videos older than start_ts, stop!
                                if consecutive_old_videos >= 4:
                                    hit_time_limit = True
                                    break
                            continue
                        else:
                            if not is_top:
                                consecutive_old_videos = 0

                        # Video is in valid time window, extract products
                        item_time_str = (
                            datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")
                            if create_time
                            else ""
                        )
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
                        self.diagnostics.append(diagnostic)
                        if not items:
                            # 逐条记录未命中的原因，否则「0 件」永远无从排查
                            self.log(f"  [未提取到商品] {item_video_url} → {diagnostic.summary()}")
                        else:
                            for it in items:
                                all_products.append(it)
                                self.log(f"  [发现商品] {account_name} | {it.product_name} ({it.price or '未知价'}) | 视频: {it.video_title[:20]}...")

                    self.log(f"[抖音] {account_name} 已处理 {len(seen_aweme_ids)} 个视频，累计发现带货商品 {len(all_products)} 件")

                    if hit_time_limit:
                        self.log(f"[抖音] {account_name} 视频发布时间已超出指定起始日期，自动结束翻页。")
                        break

                    if not has_more:
                        self.log(f"[抖音] {account_name} 已到达视频末尾(has_more=0)。")
                        break

                except Exception as e:
                    self.log(f"[抖音] 数据包解析异常: {e}")

            # Scroll down to load next page
            scroll_count += 1
            page.scroll.to_bottom()
            time.sleep(1.8)

        target.status = "已完成"
        self.log(f"[抖音] 账号 {account_name} 爬取完成！扫描视频数: {len(seen_aweme_ids)}, 提取带货商品: {len(all_products)}")
        return all_products
