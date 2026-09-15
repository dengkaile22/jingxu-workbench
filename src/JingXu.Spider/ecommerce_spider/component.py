"""
High-level Python SDK Component for crawling and analyzing Douyin & Kuaishou e-commerce products.
"""
import os
from typing import List, Tuple, Optional, Callable, Dict, Any
from datetime import datetime

from core.models import (
    AccountTarget,
    TimeFilterConfig,
    OccurrenceFilterConfig,
    VideoProductItem,
    RetainedProduct,
)
from core.browser_manager import BrowserManager
from core.douyin_crawler import DouyinCrawler
from core.kuaishou_crawler import KuaishouCrawler
from core.analyzer import ProductAnalyzer
from core.exporter import DataExporter


class EcommerceCrawlerComponent:
    """
    High-level reusable component for Douyin & Kuaishou e-commerce video product crawling,
    time filtering, and cross-account threshold retention.

    Example:
        crawler = EcommerceCrawlerComponent(headless=True)
        crawler.add_account("douyin", "https://www.douyin.com/user/...", name="对标账号A")
        crawler.add_account("kuaishou", "https://www.kuaishou.com/profile/...", name="对标账号B")
        crawler.set_time_filter(days=7)
        crawler.set_retention_rule(min_account_count=2)
        retained, all_items = crawler.run()
        crawler.export_excel("results.xlsx")
    """

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        min_account_count: int = 2,
        min_total_occurrences: int = 1,
        enable_fuzzy_cluster: bool = True
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.accounts: List[AccountTarget] = []
        self.time_config = TimeFilterConfig(mode="days", days=7)
        self.filter_config = OccurrenceFilterConfig(
            min_account_count=min_account_count,
            min_total_occurrences=min_total_occurrences,
            enable_fuzzy_cluster=enable_fuzzy_cluster,
        )

        self.retained_products: List[RetainedProduct] = []
        self.all_items: List[VideoProductItem] = []
        self._browser_manager: Optional[BrowserManager] = None

    def add_account(self, platform: str, url: str, name: str = "", enabled: bool = True) -> "EcommerceCrawlerComponent":
        """Add a target account to crawl."""
        target = AccountTarget(
            platform=platform.lower().strip(),
            url_or_id=url.strip(),
            name=name.strip(),
            enabled=enabled
        )
        self.accounts.append(target)
        return self

    def clear_accounts(self) -> "EcommerceCrawlerComponent":
        """Clear all target accounts."""
        self.accounts.clear()
        return self

    def set_time_filter(
        self,
        days: Optional[int] = None,
        mode: str = "days",
        start_date: str = "",
        end_date: str = ""
    ) -> "EcommerceCrawlerComponent":
        """
        Configure video publish time filter.
        Args:
            days: Last N days (e.g. 7)
            mode: 'days', 'range', or 'all'
            start_date: 'YYYY-MM-DD'
            end_date: 'YYYY-MM-DD'
        """
        if days is not None:
            self.time_config.mode = "days"
            self.time_config.days = days
        else:
            self.time_config.mode = mode
            self.time_config.start_date = start_date
            self.time_config.end_date = end_date
        return self

    def set_retention_rule(
        self,
        min_account_count: int = 2,
        min_total_occurrences: int = 1,
        filter_by: str = "accounts",
        enable_fuzzy: bool = True,
        fuzzy_threshold: float = 0.75
    ) -> "EcommerceCrawlerComponent":
        """
        Configure cross-account product retention thresholds.
        Args:
            min_account_count: Minimum distinct accounts featuring this product (default 2)
            min_total_occurrences: Minimum total video appearances (default 1)
            filter_by: 'accounts', 'total', or 'both'
            enable_fuzzy: Enable title cleaning & fuzzy clustering
            fuzzy_threshold: Similarity score threshold (0.0 to 1.0)
        """
        self.filter_config.min_account_count = min_account_count
        self.filter_config.min_total_occurrences = min_total_occurrences
        self.filter_config.filter_by = filter_by
        self.filter_config.enable_fuzzy_cluster = enable_fuzzy
        self.filter_config.fuzzy_threshold = fuzzy_threshold
        return self

    def open_login_browser(self, platform: str = "douyin") -> str:
        """Open a visible browser for user to scan login QR code."""
        bm = BrowserManager(headless=False, user_data_dir=self.user_data_dir)
        return bm.open_login_window(platform)

    def run(
        self,
        max_scrolls: int = 25,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None
    ) -> Tuple[List[RetainedProduct], List[VideoProductItem]]:
        """
        Execute the crawl and cross-account retention analysis.
        Returns:
            (retained_products, all_crawled_items)
        """
        log = on_log or (lambda msg: None)
        progress = on_progress or (lambda cur, tot, stat: None)
        should_stop = stop_check or (lambda: False)

        enabled_accounts = [acc for acc in self.accounts if acc.enabled]
        tot = len(enabled_accounts)
        if tot == 0:
            log("[-] 没有配置任何启用的对标账号！")
            return [], []

        log(f"[*] 启动爬虫组件，待爬取账号数: {tot}")
        self.all_items.clear()
        self.retained_products.clear()

        bm = BrowserManager(headless=self.headless, user_data_dir=self.user_data_dir)
        self._browser_manager = bm

        try:
            douyin_crawler = DouyinCrawler(
                browser_manager=bm,
                log_callback=log,
                progress_callback=lambda stat, c, t: progress(c, t, stat),
                stop_check=should_stop
            )
            kuaishou_crawler = KuaishouCrawler(
                browser_manager=bm,
                log_callback=log,
                progress_callback=lambda stat, c, t: progress(c, t, stat),
                stop_check=should_stop
            )

            for idx, target in enumerate(enabled_accounts, 1):
                if should_stop():
                    log("[*] 用户终止任务")
                    break

                progress(idx - 1, tot, f"爬取中 ({idx}/{tot}): {target.name or target.url_or_id}")
                items: List[VideoProductItem] = []

                if target.platform == "douyin":
                    items = douyin_crawler.crawl_account(target, self.time_config, max_scrolls=max_scrolls)
                elif target.platform == "kuaishou":
                    items = kuaishou_crawler.crawl_account(target, self.time_config, max_scrolls=max_scrolls)
                else:
                    log(f"[-] 不支持的平台类型: {target.platform}")
                    continue

                self.all_items.extend(items)

            progress(tot, tot, "正在执行跨账号商品保留分析...")
            analyzer = ProductAnalyzer(self.filter_config)
            self.retained_products, _ = analyzer.aggregate_and_filter(self.all_items)
            log(f"[✓] 分析完成！获得跨账号保留商品 {len(self.retained_products)} 款")

            return self.retained_products, self.all_items

        finally:
            bm.close()
            self._browser_manager = None

    def export_excel(self, file_path: str) -> str:
        """Export retained and raw items to Excel."""
        return DataExporter.export_to_excel(
            file_path=file_path,
            retained_products=self.retained_products,
            all_items=self.all_items,
            accounts=self.accounts
        )

    def export_csv(self, file_path: str) -> str:
        """Export retained products to CSV."""
        return DataExporter.export_to_csv(file_path, self.retained_products)

    def export_json(self, file_path: str) -> str:
        """Export full crawl and retained products data to JSON."""
        return DataExporter.export_to_json(file_path, self.retained_products, self.all_items)
