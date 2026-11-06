"""Acceptance checks for 选品功能问题.docx, from selection through workbook/UI."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import datetime, timedelta
from zipfile import ZipFile

import pytest
from core.analyzer import ProductAnalyzer
from core.exporter import DataExporter
from core.extraction import extract_products
from core.models import (
    AccountTarget,
    OccurrenceFilterConfig,
    TimeFilterConfig,
    VideoProductItem,
)
from core.report_tasks import ReportTask, analyze_reports, crawl_time_filter
from jingxu.infrastructure import spider as service
from jingxu.ui.spider_page import RESULT_IMAGE_COLUMN, SpiderPage
from openpyxl import load_workbook
from PIL import Image
from PySide6.QtWidgets import QApplication

NOW = datetime(2026, 10, 2, 12)


def item(
    video,
    *,
    title="天然茶籽洗衣液500ml",
    account="a",
    platform="douyin",
    likes=100,
    age=1,
    cover="",
):
    published = NOW - timedelta(days=age)
    return VideoProductItem(
        platform,
        f"账号{account}",
        account,
        video,
        "商品介绍",
        f"https://www.{platform}.com/video/{video}",
        int(published.timestamp()),
        published.isoformat(sep=" "),
        "product",
        title,
        like_count=likes,
        cover_url=cover,
    )


def task(mode, *, days=7, threshold=1):
    config = OccurrenceFilterConfig(filter_by=mode, enable_fuzzy_cluster=False)
    setattr(
        config,
        {
            "likes": "min_like_count",
            "total": "min_total_occurrences",
            "accounts": "min_account_count",
        }[mode],
        threshold,
    )
    return ReportTask(TimeFilterConfig(mode="days", days=days), config)


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (96, 64), "green").save(stream, format="PNG")
    return stream.getvalue()


def test_likes_filters_videos_before_cleaning_and_counting():
    source = [
        item("low", title="【爆款】天然茶籽洗衣液500ml", account="b", likes=1),
        item("high", likes=900),
        item("highest", title="天然茶籽洗衣液500ml 全国包邮", likes=1500),
    ]
    result = analyze_reports(source, [task("likes", threshold=500)], now=NOW)[
        0
    ].products
    assert len(result) == 1
    product = result[0]
    assert {entry.video_id for entry in product.items} == {"high", "highest"}
    assert product.video_count == 2 and product.account_count == 1
    assert product.product_name == source[2].product_name
    assert product.sample_video_url.endswith("highest")
    assert product.sample_video_like_count == product.max_like_count == 1500
    assert product.sample_video_date == "2026-10-01"
    retained, all_products = ProductAnalyzer(task("likes", threshold=500).filter_config).aggregate_and_filter(source)
    assert all(entry.video_id != "low" for entry in retained[0].items)
    assert any(entry.video_id == "low" for product in all_products for entry in product.items)


@pytest.mark.parametrize(
    "mode,threshold,expected",
    [("total", 3, ["多次商品"]), ("accounts", 2, ["跨账号商品"])],
)
def test_frequency_and_account_thresholds_are_independent(mode, threshold, expected):
    source = [item(str(index), title="多次商品") for index in range(3)]
    source += [
        item("a", title="跨账号商品", account="a", likes=30),
        item("b", title="跨账号商品", account="b", likes=500),
    ]
    products = analyze_reports(source, [task(mode, threshold=threshold)], now=NOW)[
        0
    ].products
    assert [product.product_name for product in products] == expected
    assert products[0].sample_video_like_count == max(
        entry.like_count for entry in products[0].items
    )


@pytest.mark.parametrize(
    "mode,metric",
    [
        ("likes", "sample_video_like_count"),
        ("total", "video_count"),
        ("accounts", "account_count"),
    ],
)
def test_each_report_sorts_by_its_own_metric(mode, metric):
    source = [
        item(f"a{i}", title="高频商品", account=str(i % 2), likes=20) for i in range(4)
    ]
    source += [
        item("b", title="高赞商品", likes=1000),
        item("c1", title="多账号商品", account="c"),
        item("c2", title="多账号商品", account="d"),
        item("c3", title="多账号商品", account="e"),
    ]
    products = analyze_reports(source, [task(mode)], now=NOW)[0].products
    values = [getattr(product, metric) for product in products]
    assert values == sorted(values, reverse=True)


def test_independent_time_ranges_do_not_leak_records_into_other_reports():
    source = [
        item("new", likes=900, age=1),
        item("old", account="b", age=20),
        item("older", age=60),
    ]
    reports = analyze_reports(
        source,
        [
            task("likes", days=3, threshold=500),
            task("total", days=30, threshold=2),
            task("accounts", days=90, threshold=2),
        ],
        now=NOW,
    )
    assert [report.task.name for report in reports] == [
        "按点赞量",
        "按总频次",
        "按跨账号数",
    ]
    assert [{entry.video_id for entry in report.items} for report in reports] == [
        {"new"},
        {"new", "old"},
        {"new", "old", "older"},
    ]
    assert [report.products[0].video_count for report in reports] == [1, 2, 3]
    start, end = crawl_time_filter(
        [report.task for report in reports], now=NOW
    ).get_timestamps()
    assert start <= source[-1].publish_time and end >= source[0].publish_time


def test_unbounded_task_does_not_truncate_other_task_crawl_scope():
    unbounded = task("accounts")
    unbounded.time_config.mode = "all"
    assert crawl_time_filter([task("likes"), unbounded], NOW).get_timestamps() == (
        None,
        None,
    )


@pytest.mark.parametrize("fuzzy", [False, True])
def test_platforms_never_supply_each_others_accounts_or_frequency(fuzzy):
    config = task("accounts", threshold=2)
    config.filter_config.enable_fuzzy_cluster = fuzzy
    source = [item("d", account="a"), item("k", account="b", platform="kuaishou")]
    assert analyze_reports(source, [config], now=NOW)[0].products == []
    source.append(item("d2", account="c"))
    result = analyze_reports(source, [config], now=NOW)[0].products
    assert (
        len(result) == 1
        and result[0].platform == "douyin"
        and result[0].account_count == 2
    )


def test_same_name_uses_stable_account_id_instead_of_nickname():
    source = [
        replace(item("a"), account_name="同一个昵称"),
        replace(item("b", account="b"), account_name="同一个昵称"),
    ]
    product = analyze_reports(source, [task("accounts", threshold=2)], now=NOW)[
        0
    ].products[0]
    assert product.account_count == 2


def test_missing_date_cannot_bypass_any_restricted_report():
    unknown = replace(item("unknown"), publish_time=0, publish_time_str="bad date")
    assert analyze_reports([unknown], [task("likes")], now=NOW)[0].products == []


@pytest.mark.parametrize(
    "platform,wrapper", [("douyin", "promotions"), ("kuaishou", "goodsInfo")]
)
def test_product_image_is_extracted_without_using_the_video_cover(platform, wrapper):
    product = {
        "product_id": "p",
        "productId": "p",
        "title": "天然茶籽洗衣液",
        "image": {"url_list": ["https://images.invalid/product.png"]},
    }
    node = {
        "id": "v",
        wrapper: [product] if platform == "douyin" else product,
        "cover": {"url_list": ["https://images.invalid/video.png"]},
    }
    records, _ = extract_products(platform, node, "账号", "id")
    assert (
        len(records) == 1
        and records[0].cover_url == "https://images.invalid/product.png"
    )
    assert records[0].to_dict()["商品主图"] == records[0].cover_url
    assert (
        ProductAnalyzer(OccurrenceFilterConfig(min_account_count=1))
        .aggregate_and_filter(records)[0][0]
        .to_summary_dict()["商品主图"]
        == records[0].cover_url
    )


def test_malformed_records_do_not_destroy_valid_analysis_or_json_export(tmp_path):
    warnings = []
    source = [
        None,
        {},
        item("ok", likes="1.2万"),
        replace(item("bad-date"), publish_time="not a timestamp"),
        replace(item("bad-title"), product_name={}),
        replace(item("nan"), like_count=float("nan")),
        replace(item("too-large"), like_count=10 ** 500),
        replace(item("unicode"), product_name="商品\ud800名"),
    ]
    reports = analyze_reports(
        source, [task("likes", threshold=500)], now=NOW, on_issue=warnings.append
    )
    assert warnings and len(reports[0].products) == 1
    assert reports[0].products[0].sample_video_like_count == 12000
    destination = tmp_path / "result.json"
    DataExporter.export_to_json(
        str(destination), reports[0].products, source, reports=reports
    )
    data = json.loads(destination.read_text(encoding="utf-8"))
    assert data["retained_products"][0]["示例视频点赞量"] == 12000
    assert data["reports"][0]["filter_by"] == "likes"


def test_workbook_has_separate_named_reports_platforms_metrics_and_embedded_image(
    monkeypatch, tmp_path
):
    url = "https://images.invalid/product.png"
    source = [
        item("d1", likes=900, cover=url),
        item("d2", account="b", likes=50),
        item(
            "k",
            platform="kuaishou",
            likes=800,
            title="另一个商品",
            cover="https://images.invalid/broken.png",
        ),
    ]
    reports = analyze_reports(
        source,
        [
            task("likes", threshold=500),
            task("total", threshold=2),
            task("accounts", threshold=2),
        ],
        now=NOW,
    )
    monkeypatch.setattr(
        "core.exporter.load_product_images",
        lambda urls: {
            url: image_bytes(),
            "https://images.invalid/broken.png": b"invalid image",
        },
    )
    destination = tmp_path / "reports.xlsx"
    DataExporter.export_to_excel(
        str(destination),
        [p for report in reports for p in report.products],
        source,
        [AccountTarget("douyin", "a", name="账号a", status="已完成")],
        reports=reports,
    )
    workbook = load_workbook(destination)
    try:
        for report in reports:
            for platform, label in (("douyin", "抖音"), ("kuaishou", "快手")):
                sheet = workbook[f"{report.task.name}·{label}"]
                rows, headers = list(sheet.values), list(next(sheet.values))
                assert "商品主图" in headers and "示例视频点赞量" in headers
                assert ("共同带货账号数" in headers) == (
                    report.task.filter_config.filter_by == "accounts"
                )
                assert ("带货视频总数" in headers) == (
                    report.task.filter_config.filter_by == "total"
                )
                assert all(
                    row[headers.index("涉及平台")] == platform for row in rows[1:]
                )
                assert len(rows) - 1 == len(
                    [p for p in report.products if p.platform == platform]
                )
        assert len(workbook["按点赞量·抖音"]._images) == 1
        assert len(workbook["按点赞量·快手"]._images) == 0
        assert (
            workbook["筛选任务设置"].max_row == 4
            and "对标账号爬取统计" in workbook.sheetnames
        )
    finally:
        workbook.close()
    with ZipFile(destination) as archive:
        assert any(name.startswith("xl/media/") for name in archive.namelist())


def test_single_report_does_not_export_other_criteria(monkeypatch, tmp_path):
    monkeypatch.setattr("core.exporter.load_product_images", lambda urls: {})
    source = [item("d")]
    reports = analyze_reports(source, [task("likes")], now=NOW)
    destination = tmp_path / "single.xlsx"
    DataExporter.export_to_excel(
        str(destination), reports[0].products, source, reports=reports
    )
    with ZipFile(destination) as archive:
        xml = archive.read("xl/workbook.xml").decode()
        assert "按点赞量" in xml and "按总频次" not in xml and "按跨账号数" not in xml


def test_configuration_round_trip_keeps_per_task_time_and_threshold(tmp_path):
    from core.config import AppConfig

    filters = service.SpiderFilters(filter_by="likes", min_likes=600, days=3)
    tasks = (
        filters,
        replace(filters, filter_by="total", min_occurrences=5, days=30),
        replace(
            filters,
            filter_by="accounts",
            min_accounts=3,
            time_mode="range",
            start_date="2026-07-01",
            end_date="2026-09-30",
        ),
    )
    config = service.SpiderConfig(
        accounts=(service.SpiderAccount("douyin", "a"),),
        filters=filters,
        report_tasks=tasks,
    )
    assert service.SpiderConfig.from_dict(config.to_dict()) == config
    path = tmp_path / "config.json"
    path.write_text(json.dumps(service._cli_config_document(config)), encoding="utf-8")
    extension = AppConfig(str(path))
    assert extension.filter_config.min_like_count == 600
    assert [t.time_config.days for t in extension.report_tasks] == [3, 30, 3]
    assert extension.report_tasks[1].filter_config.min_total_occurrences == 5
    assert extension.report_tasks[2].time_config.start_date == "2026-07-01"
    extension.save()
    assert len(AppConfig(str(path)).report_tasks) == 3


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["selection-acceptance"])


def page(tmp_path):
    return SpiderPage(
        store=service.SpiderConfigStore(tmp_path / "config.json"),
        check_environment=lambda: service.SpiderEnvironment(
            available=True, message="ok"
        ),
    )


def test_hidden_selection_page_does_not_fetch_images_during_video_work(qapp, monkeypatch, tmp_path):
    import time
    requests = []
    def fetch(url):
        requests.append(url)
        return image_bytes()
    monkeypatch.setattr(service, "fetch_product_cover", fetch)
    view = page(tmp_path)
    url = "https://images.invalid/product.png"
    try:
        view._request_cover(url)
        assert requests == [] and url in view._deferred_covers
        view.show()
        deadline = time.monotonic() + 3
        while url not in view._cover_cache and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        assert requests == [url] and view._cover_cache[url] == image_bytes()
    finally:
        view.close()


def test_valid_title_whitespace_does_not_mark_crawl_incomplete():
    from core.extraction import safe_extract_products
    records, diagnostic = safe_extract_products("douyin", {"id": "v", "promotions": [{"product_id": "p", "title": "洗衣液"}]},
                                                "正常账号", "id", video_title="正常文案\n")
    assert len(records) == 1 and records[0].video_title == "正常文案"
    assert diagnostic.data_error is False


def test_ui_collects_independent_tasks_and_quick_time_presets(qapp, tmp_path):
    view = page(tmp_path)
    try:
        for widgets in view._task_widgets.values():
            widgets["enabled"].setChecked(True)
        assert not hasattr(view, "_time_mode") and not hasattr(view, "_filter_by")
        likes, total, accounts = (
            view._task_widgets[mode] for mode in ("likes", "total", "accounts")
        )
        likes["preset"].setCurrentIndex(likes["preset"].findData("3"))
        total["preset"].setCurrentIndex(total["preset"].findData("30"))
        accounts["preset"].setCurrentIndex(accounts["preset"].findData("range"))
        accounts["start"].setText("2026-07-01")
        accounts["end"].setText("2026-09-30")
        likes["threshold"].setValue(500)
        view._persist()
        assert [t.days for t in view._config.report_tasks[:2]] == [3, 30]
        assert view._config.report_tasks[2].start_date == "2026-07-01"
        assert view._config.report_tasks[0].min_likes == 500
        total["enabled"].setChecked(False)
        accounts["enabled"].setChecked(False)
        assert len(view._collect_report_tasks()) == 1
    finally:
        view.shutdown()


def test_ui_displays_only_chosen_report_platform_and_correct_thumbnail(
    qapp, monkeypatch, tmp_path
):
    monkeypatch.setattr(service, "fetch_product_cover", lambda url: image_bytes())
    records = [
        item("d", likes=900, cover="https://images.invalid/product.png"),
        item("k", platform="kuaishou", likes=900),
    ]
    reports = analyze_reports(
        records, [task("likes", threshold=500), task("accounts", threshold=2)], now=NOW
    )
    result = service.SpiderRunResult(
        True,
        "完成",
        retained=tuple(p.to_summary_dict() for p in reports[0].products),
        reports=tuple(report.to_dict() for report in reports),
    )
    view = page(tmp_path)
    try:
        view._on_run_finished(result)
        assert view._results_table.rowCount() == 2
        assert view._results_table.horizontalHeader().visualIndex(RESULT_IMAGE_COLUMN) == 1
        view._result_platform.setCurrentIndex(view._result_platform.findData("douyin"))
        assert view._results_table.rowCount() == 1
        view._on_cover_ready("https://images.invalid/product.png", image_bytes())
        assert not view._results_table.item(0, RESULT_IMAGE_COLUMN).icon().isNull()
        assert (
            view._cell_url(0, RESULT_IMAGE_COLUMN)
            == "https://images.invalid/product.png"
        )
        assert view._results_table.isColumnHidden(
            5
        ) and view._results_table.isColumnHidden(6)
        view._result_report.setCurrentIndex(1)
        assert view._results_table.rowCount() == 0 and view._selected_urls() == ()
        assert not view._send_button.isEnabled()
    finally:
        view.shutdown()


def test_result_persistence_keeps_report_tabs_and_tolerates_bad_diagnostic_counts(
    tmp_path,
):
    result = service.parse_result_payload(
        {
            "retained_products": [],
            "reports": [{"name": "按点赞量", "filter_by": "likes"}],
            "diagnostics": {
                "extraction": {
                    "videosScanned": "invalid",
                    "videosWithProducts": float("inf"),
                }
            },
        }
    )
    assert (
        result.diagnostics.videos_scanned
        == result.diagnostics.videos_with_products
        == 0
    )
    store = service.SpiderConfigStore(tmp_path / "config.json")
    store.save_result(result)
    assert store.load_result().reports == result.reports
