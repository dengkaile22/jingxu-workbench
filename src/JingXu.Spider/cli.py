"""
CLI interface for automated crawling and analysis.
"""
import os
import sys

# 嵌入式 Python 通过 ._pth 启用隔离模式，不自动把脚本目录加入 sys.path；
# 这里显式补上，保证随包运行时可导入 core 与 ecommerce_spider。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from datetime import datetime

from tabulate import tabulate

from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig, VideoProductItem
from core.config import AppConfig
from core.browser_manager import BrowserManager
from core.douyin_crawler import DouyinCrawler
from core.kuaishou_crawler import KuaishouCrawler
from core.analyzer import ProductAnalyzer
from core.exporter import DataExporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抖音与快手多账号短视频带货商品爬取与共性保留分析工具")
    parser.add_argument("--config", type=str, default="config.json", help="配置文件路径")
    parser.add_argument("--headless", action="store_true", default=False, help="启用无头模式后台运行")
    parser.add_argument("--days", type=int, default=None, help="按天数覆盖时间范围，如 --days 7")
    parser.add_argument("--time-mode", choices=["days", "range", "all"], default=None, help="时间模式：days / range / all")
    parser.add_argument("--start-date", type=str, default=None, help="自定义起始日期 YYYY-MM-DD（配合 --time-mode range）")
    parser.add_argument("--end-date", type=str, default=None, help="自定义结束日期 YYYY-MM-DD（配合 --time-mode range）")
    parser.add_argument("--min-accounts", type=int, default=None, help="跨账号保留门槛(至少在N个账号出现)，如 --min-accounts 2")
    parser.add_argument("--min-occurrences", type=int, default=None, help="总频次保留门槛(至少累计出现M次)")
    parser.add_argument("--filter-by", choices=["accounts", "total", "both"], default=None, help="过滤准则：accounts / total / both")
    parser.add_argument("--fuzzy-threshold", type=float, default=None, help="同款商品模糊合并相似度阈值 0.0~1.0")
    parser.add_argument("--max-scrolls", type=int, default=None, help="单账号最大滚动翻页次数")
    parser.add_argument("--profile-dir", type=str, default=None, help="浏览器登录态持久化目录")
    parser.add_argument("--browser-path", type=str, default=None, help="Chromium 内核浏览器可执行文件路径（缺省自动探测 Chrome/Edge）")
    parser.add_argument("--export-dir", type=str, default=None, help="报表导出目录")
    parser.add_argument("--export", type=str, default=None, help="导出Excel路径")
    parser.add_argument("--json-out", type=str, default=None, help="导出JSON结果路径(供外部系统解析)")
    parser.add_argument("--login", type=str, choices=["douyin", "kuaishou"], help="打开浏览器扫码登录指定的平台")
    return parser


def apply_overrides(app_config: AppConfig, args: argparse.Namespace) -> None:
    if args.days is not None:
        app_config.time_config.mode = "days"
        app_config.time_config.days = args.days

    if args.time_mode:
        app_config.time_config.mode = args.time_mode

    if args.start_date is not None:
        app_config.time_config.start_date = args.start_date

    if args.end_date is not None:
        app_config.time_config.end_date = args.end_date

    if args.min_accounts is not None:
        app_config.filter_config.min_account_count = args.min_accounts

    if args.min_occurrences is not None:
        app_config.filter_config.min_total_occurrences = args.min_occurrences

    if args.filter_by:
        app_config.filter_config.filter_by = args.filter_by

    if args.fuzzy_threshold is not None:
        app_config.filter_config.fuzzy_threshold = args.fuzzy_threshold

    if args.max_scrolls is not None:
        app_config.max_scrolls_per_account = args.max_scrolls

    if args.export_dir:
        app_config.export_dir = os.path.abspath(args.export_dir)

    if args.headless:
        app_config.headless = True


def run_login(args: argparse.Namespace) -> None:
    print(f"[*] 正在启动浏览器以登录 {args.login}...", flush=True)
    browser_manager = BrowserManager(
        headless=False,
        user_data_dir=args.profile_dir,
        browser_path=args.browser_path,
    )
    try:
        browser_manager.open_login_window(args.login)
        input(f"[*] 请在浏览器中完成 {args.login} 扫码或手机号登录，登录完成后在控制台按回车键结束: ")
    finally:
        browser_manager.close()
    print(f"[+] {args.login} 登录态与 Cookie 已持久保存！", flush=True)


def run_cli() -> None:
    args = build_parser().parse_args()

    if args.login:
        run_login(args)
        return

    config_path = os.path.abspath(args.config)
    app_config = AppConfig(config_path)
    apply_overrides(app_config, args)

    enabled_accounts = [acc for acc in app_config.accounts if acc.enabled]
    if not enabled_accounts:
        print("[-] 错误: 未发现任何启用的对标账号！请在配置中添加账号。", flush=True)
        sys.exit(1)

    print("=" * 60, flush=True)
    print("🎬 抖音 & 快手多账号短视频带货商品爬取系统 (CLI模式)", flush=True)
    print(f"[*] 待爬取账号数: {len(enabled_accounts)}", flush=True)
    print(f"[*] 时间配置: {app_config.time_config.mode} ({app_config.time_config.days}天) "
          f"{app_config.time_config.start_date} ~ {app_config.time_config.end_date}", flush=True)
    print(f"[*] 保留规则: 跨账号数 >= {app_config.filter_config.min_account_count}, "
          f"总频次 >= {app_config.filter_config.min_total_occurrences}, "
          f"过滤准则: {app_config.filter_config.filter_by}", flush=True)
    print(f"[*] 浏览器模式: {'无头后台运行' if app_config.headless else '可视窗口运行'}", flush=True)
    print("=" * 60, flush=True)

    browser_manager = BrowserManager(
        headless=app_config.headless,
        user_data_dir=args.profile_dir,
        browser_path=args.browser_path,
    )
    all_crawled_items = []

    try:
        douyin_crawler = DouyinCrawler(
            browser_manager=browser_manager,
            log_callback=lambda msg: print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
        )
        kuaishou_crawler = KuaishouCrawler(
            browser_manager=browser_manager,
            log_callback=lambda msg: print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
        )

        for idx, target in enumerate(enabled_accounts, 1):
            print(f"\n>>> [{idx}/{len(enabled_accounts)}] 正在爬取: {target.name or target.url_or_id} ({target.platform})", flush=True)
            if target.platform == "douyin":
                items = douyin_crawler.crawl_account(target, app_config.time_config, app_config.max_scrolls_per_account)
            elif target.platform == "kuaishou":
                items = kuaishou_crawler.crawl_account(target, app_config.time_config, app_config.max_scrolls_per_account)
            else:
                continue
            all_crawled_items.extend(items)

        print("\n" + "=" * 60, flush=True)
        print(f"[*] 爬取结束！累计抓取商品明细: {len(all_crawled_items)} 条，开始聚合保留相同项...", flush=True)

        analyzer = ProductAnalyzer(app_config.filter_config)
        retained, _ = analyzer.aggregate_and_filter(all_crawled_items)

        print(f"[+] 筛选出跨账号共同带货商品: {len(retained)} 款", flush=True)
        print("=" * 60, flush=True)

        if retained:
            table_rows = []
            for p in retained[:20]:
                table_rows.append([
                    p.product_name[:25],
                    p.platform,
                    p.account_count,
                    p.video_count,
                    ", ".join(p.accounts)[:20],
                    p.price_range
                ])
            print(tabulate(table_rows, headers=["商品名称", "平台", "账号数", "视频数", "涉及账号", "参考价格"], tablefmt="grid"), flush=True)
            if len(retained) > 20:
                print(f"... 还有 {len(retained) - 20} 款未显示在控制台", flush=True)

        export_file = args.export
        if not export_file:
            export_dir = app_config.export_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            os.makedirs(export_dir, exist_ok=True)
            export_file = os.path.join(export_dir, f"带货商品跨账号保留_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

        DataExporter.export_to_excel(export_file, retained, all_crawled_items, app_config.accounts)
        print(f"\n[✓] 完整数据报表已导出至: {export_file}", flush=True)

        if args.json_out:
            DataExporter.export_to_json(args.json_out, retained, all_crawled_items, excel_path=export_file)
            print(f"[✓] 结构化数据已输出至: {args.json_out}", flush=True)

    finally:
        browser_manager.close()


if __name__ == "__main__":
    run_cli()
