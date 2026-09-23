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
from core.extraction import collect_diagnostics_summary
from core.diagnostics import (
    LOGIN_URLS,
    build_diagnostics_payload,
    describe_login_state,
    detect_login_state_in_text,
    format_issues,
    load_login_state,
    record_login_state,
    run_diagnosis,
    run_preflight,
)


def login_states_snapshot(profile_dir) -> dict:  # noqa: ANN001
    """读取各平台登录态记录（供诊断输出）。"""
    return {platform: load_login_state(profile_dir).get(platform, {}) for platform in LOGIN_URLS}


def _probe_login_state(crawler) -> str:  # noqa: ANN001
    """从浏览器当前页面文本判断登录态：``ok`` / ``required`` / ``risk``。

    Chromium 不支持低成本地「读取 cookie 判断是否登录」，因此改用**行为证据**：
    站点若把访客当未登录处理，页面上会出现登录引导或验证码文案。这比解析
    cookie 数据库可靠，也不需要额外依赖。
    """
    try:
        page = crawler.browser_manager.get_page()
        text = page.ele("tag:body", timeout=1).text or ""
    except Exception:  # noqa: BLE001 - 探测失败不影响抓取
        return "ok"
    return detect_login_state_in_text(text)
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

    # ── 运行前自检：把「跑不起来」变成可读结论 ──────────────────────────────
    preflight = run_preflight(
        headless=app_config.headless,
        profile_dir=args.profile_dir,
        browser_path=args.browser_path,
    )
    for platform in LOGIN_URLS:
        print(f"[*] {platform} 登录态: {describe_login_state(platform, args.profile_dir)}", flush=True)
    if preflight.issues:
        print(format_issues(preflight.issues), flush=True)
    if not preflight.ok:
        blocker_text = "\n".join(item.line() for item in preflight.blockers)
        print("\n[-] 环境检查未通过，已停止运行：", flush=True)
        print(blocker_text, flush=True)
        # 仍然写出诊断，便于工作台界面展示原因
        if args.json_out:
            DataExporter.export_to_json(
                args.json_out,
                [],
                [],
                diagnostics=build_diagnostics_payload(
                    preflight=preflight,
                    login_states=login_states_snapshot(args.profile_dir),
                    extraction_summary={},
                    issues=preflight.issues,
                ),
            )
        sys.exit(2)

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
                crawler = douyin_crawler
            elif target.platform == "kuaishou":
                crawler = kuaishou_crawler
            else:
                continue

            items = crawler.crawl_account(target, app_config.time_config, app_config.max_scrolls_per_account)
            all_crawled_items.extend(items)

            # 登录态行为证据：从页面文本判断站点是否把访客当未登录/触发风控，
            # 记录到 login_state.json，供界面提示「是否需要重新扫码」。
            state = _probe_login_state(crawler)
            if state != "ok":
                record_login_state(target.platform, state, profile_dir=args.profile_dir)
                print(f"[!] {target.platform} 登录态异常（{state}）：{describe_login_state(target.platform, args.profile_dir)}", flush=True)
            elif items:
                record_login_state(target.platform, "ok", profile_dir=args.profile_dir)

        print("\n" + "=" * 60, flush=True)
        print(f"[*] 爬取结束！累计抓取商品明细: {len(all_crawled_items)} 条，开始聚合保留相同项...", flush=True)

        analyzer = ProductAnalyzer(app_config.filter_config)
        retained, _ = analyzer.aggregate_and_filter(all_crawled_items)

        # ── 运行后诊断：解释「为什么没抓到」 ────────────────────────────────
        all_diagnostics = list(douyin_crawler.diagnostics) + list(kuaishou_crawler.diagnostics)
        extraction_summary = collect_diagnostics_summary(all_diagnostics)
        login_states = [
            (load_login_state(args.profile_dir).get(target.platform) or {}).get("status", "")
            for target in enabled_accounts
        ]
        issues = run_diagnosis(
            videos_scanned=extraction_summary.get("videosScanned", 0),
            items_found=len(all_crawled_items),
            retained=len(retained),
            diagnostics={
                "scannedNodes": sum(item.scanned_nodes for item in all_diagnostics),
                "scanCandidates": sum(item.scan_candidates for item in all_diagnostics),
            },
            login_states=login_states,
        )
        if issues:
            print("\n[*] 诊断：", flush=True)
            print(format_issues(issues), flush=True)
        print(f"[*] 提取统计：扫描 {extraction_summary.get('videosScanned', 0)} 个视频，"
              f"其中 {extraction_summary.get('videosWithProducts', 0)} 个含商品", flush=True)

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
            DataExporter.export_to_json(
                args.json_out,
                retained,
                all_crawled_items,
                excel_path=export_file,
                diagnostics=build_diagnostics_payload(
                    preflight=preflight,
                    login_states=login_states_snapshot(args.profile_dir),
                    extraction_summary=extraction_summary,
                    issues=issues,
                ),
            )
            print(f"[✓] 结构化数据已输出至: {args.json_out}", flush=True)

    finally:
        browser_manager.close()


if __name__ == "__main__":
    run_cli()
