"""
QThread background worker for crawling Douyin & Kuaishou accounts.
"""
from typing import List, Tuple
from PySide6.QtCore import QThread, Signal

from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig, VideoProductItem, RetainedProduct
from core.browser_manager import BrowserManager
from core.douyin_crawler import DouyinCrawler
from core.kuaishou_crawler import KuaishouCrawler
from core.analyzer import ProductAnalyzer


class CrawlWorker(QThread):
    """Background worker that orchestrates crawling across accounts."""

    log_signal = Signal(str)
    progress_signal = Signal(int, int, str)               # current_idx, total_accounts, status_text
    product_found_signal = Signal(object)                 # VideoProductItem
    account_status_signal = Signal(int, str)              # account_index, status_text
    finished_signal = Signal(list, list)                  # retained_products, all_items
    error_signal = Signal(str)

    def __init__(
        self,
        accounts: List[AccountTarget],
        time_config: TimeFilterConfig,
        filter_config: OccurrenceFilterConfig,
        headless: bool = False,
        max_scrolls: int = 25
    ):
        super().__init__()
        self.accounts = accounts
        self.time_config = time_config
        self.filter_config = filter_config
        self.headless = headless
        self.max_scrolls = max_scrolls
        self._is_stopped = False
        self.browser_manager: BrowserManager = None

    def stop(self):
        """Request stop of crawl job."""
        self._is_stopped = True
        self.log_signal.emit("[系统] 正在请求终止爬虫...")
        if self.browser_manager:
            self.browser_manager.close()

    def run(self):
        """Execution entry point for thread."""
        enabled_accounts = [(idx, acc) for idx, acc in enumerate(self.accounts) if acc.enabled]
        total_accounts = len(enabled_accounts)

        if total_accounts == 0:
            self.error_signal.emit("没有勾选任何启用的对标账号！请先勾选或添加账号。")
            return

        self.log_signal.emit(f"=== 开始执行爬取任务，共 {total_accounts} 个对标账号 ===")
        self.progress_signal.emit(0, total_accounts, "正在启动浏览器...")

        all_crawled_items: List[VideoProductItem] = []

        try:
            self.browser_manager = BrowserManager(headless=self.headless)

            douyin_crawler = DouyinCrawler(
                browser_manager=self.browser_manager,
                log_callback=lambda msg: self.log_signal.emit(msg),
                progress_callback=lambda status, c, t: self.progress_signal.emit(c, t, status),
                stop_check=lambda: self._is_stopped,
            )

            kuaishou_crawler = KuaishouCrawler(
                browser_manager=self.browser_manager,
                log_callback=lambda msg: self.log_signal.emit(msg),
                progress_callback=lambda status, c, t: self.progress_signal.emit(c, t, status),
                stop_check=lambda: self._is_stopped,
            )

            for step_idx, (orig_idx, target) in enumerate(enabled_accounts, 1):
                if self._is_stopped:
                    self.log_signal.emit("[系统] 任务已由用户手动终止。")
                    self.account_status_signal.emit(orig_idx, "已停止")
                    break

                acc_name = target.name or target.url_or_id
                self.progress_signal.emit(step_idx - 1, total_accounts, f"正在爬取 ({step_idx}/{total_accounts}): {acc_name}")
                self.account_status_signal.emit(orig_idx, "爬取中")

                items: List[VideoProductItem] = []
                if target.platform == "douyin":
                    items = douyin_crawler.crawl_account(target, self.time_config, max_scrolls=self.max_scrolls)
                elif target.platform == "kuaishou":
                    items = kuaishou_crawler.crawl_account(target, self.time_config, max_scrolls=self.max_scrolls)
                else:
                    self.log_signal.emit(f"[未知平台] 跳过账号: {acc_name} (平台: {target.platform})")
                    self.account_status_signal.emit(orig_idx, "平台未知")
                    continue

                for it in items:
                    all_crawled_items.append(it)
                    self.product_found_signal.emit(it)

                self.account_status_signal.emit(orig_idx, f"完成(抓取{len(items)}件)")

            self.progress_signal.emit(total_accounts, total_accounts, "正在进行跨账号相同商品聚类分析与保留筛选...")
            self.log_signal.emit(f"=== 爬取阶段结束，累计捕获带货商品记录 {len(all_crawled_items)} 条，正在按规则保留相同项 ===")

            # Run analysis and threshold filtering
            analyzer = ProductAnalyzer(self.filter_config)
            retained_products, _ = analyzer.aggregate_and_filter(all_crawled_items)

            self.log_signal.emit(
                f"=== 分析完成！跨账号共性保留商品: {len(retained_products)} 款 "
                f"(门槛: 涉及账号数 >= {self.filter_config.min_account_count}, 总频次 >= {self.filter_config.min_total_occurrences}) ==="
            )

            self.finished_signal.emit(retained_products, all_crawled_items)

        except Exception as e:
            self.log_signal.emit(f"[错误] 爬虫运行异常: {e}")
            self.error_signal.emit(str(e))
        finally:
            if self.browser_manager:
                self.browser_manager.close()
