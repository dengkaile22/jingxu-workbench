"""
Kuaishou account crawler using DrissionPage packet listener.
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
from core.extraction import ExtractionDiagnostic, extract_products
from core.browser_manager import BrowserManager


def resolve_kuaishou_url_or_userid(input_str: str) -> str:
    """
    Parse Kuaishou input string (short link, full URL, or user_id) into user_id.
    """
    input_str = input_str.strip()
    if not input_str:
        return ""

    if "v.kuaishou.com" in input_str or "kuaishouapp.com" in input_str:
        try:
            match = re.search(r"https?://[a-zA-Z0-9\.\-]+/[a-zA-Z0-9_\-]+/?", input_str)
            target_short = match.group(0) if match else input_str
            resp = requests.get(target_short, allow_redirects=True, timeout=8, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            input_str = resp.url
        except Exception:
            pass

    match = re.search(r"profile/([a-zA-Z0-9_\-]+)", input_str)
    if match:
        return match.group(1)

    match2 = re.search(r"userId=([a-zA-Z0-9_\-]+)", input_str)
    if match2:
        return match2.group(1)

    return input_str


def extract_kuaishou_products_from_photo(
    photo: Dict[str, Any],
    account_name: str,
    account_id: str
) -> List[VideoProductItem]:
    """Extract e-commerce goods from a single Kuaishou photo/video object."""
    products: List[VideoProductItem] = []

    photo_id = str(photo.get("id") or photo.get("photoId") or "")
    caption = photo.get("caption") or photo.get("title") or ""
    raw_ts = photo.get("timestamp") or 0
    # Kuaishou timestamp can be in milliseconds
    create_time = int(raw_ts / 1000) if raw_ts > 1e11 else int(raw_ts)
    time_str = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S") if create_time else ""
    video_url = f"https://www.kuaishou.com/short-video/{photo_id}" if photo_id else ""
    author_name = photo.get("userName") or photo.get("author", {}).get("name") or account_name

    # 1. Check goodsInfo / commodity / anchor / ext_params
    goods_info = photo.get("goodsInfo") or photo.get("commodity") or photo.get("productInfo")
    if goods_info and isinstance(goods_info, dict):
        p_title = goods_info.get("title") or goods_info.get("name") or ""
        p_id = str(goods_info.get("id") or goods_info.get("goodsId") or "")
        p_price = goods_info.get("price") or ""
        if p_title:
            products.append(VideoProductItem(
                platform="kuaishou",
                account_name=author_name,
                account_id=account_id,
                video_id=photo_id,
                video_title=caption,
                video_url=video_url,
                publish_time=create_time,
                publish_time_str=time_str,
                product_id=p_id,
                product_name=p_title,
                cleaned_name=clean_product_title(p_title),
                price=f"¥{p_price}" if p_price and not str(p_price).startswith("¥") else str(p_price),
                detail_url=goods_info.get("url") or "",
            ))

    # 2. Check ext_params JSON string
    ext_params_str = photo.get("ext_params")
    if ext_params_str and isinstance(ext_params_str, str):
        try:
            ext = json.loads(ext_params_str)
            p_title = ext.get("goods_name") or ext.get("product_name") or ext.get("title") or ""
            p_id = str(ext.get("goods_id") or ext.get("item_id") or "")
            p_price = ext.get("price") or ""
            if p_title and not any(p.product_name == p_title for p in products):
                products.append(VideoProductItem(
                    platform="kuaishou",
                    account_name=author_name,
                    account_id=account_id,
                    video_id=photo_id,
                    video_title=caption,
                    video_url=video_url,
                    publish_time=create_time,
                    publish_time_str=time_str,
                    product_id=p_id,
                    product_name=p_title,
                    cleaned_name=clean_product_title(p_title),
                    price=f"¥{p_price}" if p_price and not str(p_price).startswith("¥") else str(p_price),
                    detail_url=ext.get("jump_url") or "",
                ))
        except Exception:
            pass

    # 3. Check anchor tags in video
    anchor = photo.get("anchor") or photo.get("anchorInfo")
    if anchor and isinstance(anchor, dict):
        p_title = anchor.get("title") or anchor.get("name") or ""
        if p_title and not any(p.product_name == p_title for p in products):
            products.append(VideoProductItem(
                platform="kuaishou",
                account_name=author_name,
                account_id=account_id,
                video_id=photo_id,
                video_title=caption,
                video_url=video_url,
                publish_time=create_time,
                publish_time_str=time_str,
                product_id=str(anchor.get("id") or ""),
                product_name=p_title,
                cleaned_name=clean_product_title(p_title),
                price="",
                detail_url="",
            ))

    # 4. Check e-commerce shopping tags in caption (e.g. 【商品名】 or #商品名#)
    if not products and caption:
        bracket_match = re.findall(r"【(.*?)】", caption)
        for b_name in bracket_match:
            b_clean = clean_product_title(b_name)
            # Ensure it looks like a product title rather than pure promo slogan
            if len(b_clean) >= 4 and not any(kw in b_clean for kw in ["视频", "关注", "直播", "感谢", "点赞"]):
                products.append(VideoProductItem(
                    platform="kuaishou",
                    account_name=author_name,
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
                ))
                break

    return products


class KuaishouCrawler:
    """Crawler for Kuaishou account short video e-commerce products."""

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
        Crawl videos and e-commerce goods for a single Kuaishou account.
        Filters by time_config and stops scrolling when past start_date.
        """
        user_id = resolve_kuaishou_url_or_userid(target.url_or_id or target.user_id)
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

        # Listen to GraphQL queries
        packet_api = "graphql"
        try:
            page.listen.start(packet_api)
        except Exception:
            pass

        self.log(f"[快手] 正在导航至主页: {profile_url}")
        page.get(profile_url)
        time.sleep(2.5)

        # Close any overlay login modal if present
        try:
            close_btn = page.ele('.login-dialog-close', timeout=1) or page.ele('@class^=close-icon', timeout=0.5)
            if close_btn:
                close_btn.click()
        except Exception:
            pass

        # Try to extract account nickname
        if not target.name or target.name == user_id[:12]:
            try:
                name_ele = page.ele('.user-name', timeout=2) or page.ele('tag:h1', timeout=1)
                if name_ele and name_ele.text:
                    account_name = name_ele.text.strip()
                    target.name = account_name
                    self.log(f"[快手] 获取到账号昵称: {account_name}")
            except Exception:
                pass

        all_products: List[VideoProductItem] = []
        seen_photo_ids = set()
        scroll_count = 0
        consecutive_old_videos = 0
        hit_time_limit = False

        while scroll_count < max_scrolls:
            if self.should_stop():
                self.log(f"[快手] 收到用户终止信号，停止爬取 {account_name}")
                target.status = "已停止"
                break

            # Wait for intercepted GraphQL packet（监听已按 packet_api 过滤，wait 不接受 targets 参数）
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

                    # Look for visionProfilePhotoList in GraphQL response
                    data_obj = res_json.get("data") or {}
                    photo_list_data = data_obj.get("visionProfilePhotoList") or {}
                    feeds = photo_list_data.get("feeds") or []
                    pcursor = photo_list_data.get("pcursor") or ""

                    for feed in feeds:
                        photo = feed.get("photo") or feed
                        photo_id = str(photo.get("id") or photo.get("photoId") or "")
                        if not photo_id or photo_id in seen_photo_ids:
                            continue

                        seen_photo_ids.add(photo_id)

                        raw_ts = photo.get("timestamp") or 0
                        create_time = int(raw_ts / 1000) if raw_ts > 1e11 else int(raw_ts)

                        # Check end time
                        if end_ts and create_time > end_ts:
                            continue

                        # Check start time
                        if start_ts and create_time < start_ts:
                            consecutive_old_videos += 1
                            if consecutive_old_videos >= 4:
                                hit_time_limit = True
                                break
                            continue
                        else:
                            consecutive_old_videos = 0

                        # Video in valid time window, extract products
                        raw_ts = photo.get("timestamp") or 0
                        item_create_time = int(raw_ts / 1000) if raw_ts > 1e11 else int(raw_ts)
                        item_time_str = (
                            datetime.fromtimestamp(item_create_time).strftime("%Y-%m-%d %H:%M:%S")
                            if item_create_time
                            else ""
                        )
                        item_video_url = (
                            f"https://www.kuaishou.com/short-video/{photo_id}" if photo_id else ""
                        )
                        items, diagnostic = extract_products(
                            "kuaishou",
                            photo,
                            account_name,
                            user_id,
                            video_title=str(photo.get("caption") or photo.get("title") or ""),
                            video_url=item_video_url,
                            publish_time=item_create_time,
                            publish_time_str=item_time_str,
                        )
                        self.diagnostics.append(diagnostic)
                        if not items:
                            # 逐条记录未命中的原因，否则「0 件」永远无从排查
                            self.log(f"  [未提取到商品] {item_video_url} → {diagnostic.summary()}")
                        else:
                            for it in items:
                                all_products.append(it)
                                self.log(f"  [快手发现商品] {account_name} | {it.product_name} ({it.price or '未知价'}) | 视频: {it.video_title[:20]}...")

                    self.log(f"[快手] {account_name} 已处理 {len(seen_photo_ids)} 个视频，累计发现带货商品 {len(all_products)} 件")

                    if hit_time_limit:
                        self.log(f"[快手] {account_name} 视频发布时间已超出指定起始日期，自动结束翻页。")
                        break

                    if pcursor == "no_more":
                        self.log(f"[快手] {account_name} 已到达作品末尾(no_more)。")
                        break

                except Exception as e:
                    self.log(f"[快手] 数据包解析异常: {e}")

            # Scroll down
            scroll_count += 1
            page.scroll.to_bottom()
            time.sleep(2)

        target.status = "已完成"
        self.log(f"[快手] 账号 {account_name} 爬取完成！扫描视频数: {len(seen_photo_ids)}, 提取带货商品: {len(all_products)}")
        return all_products
