"""Regressions for actual Douyin account-feed product pictures missing in Excel."""
from __future__ import annotations

import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image
from openpyxl import load_workbook

from core.extraction import extract_products
from core.analyzer import ProductAnalyzer
from core.models import OccurrenceFilterConfig, TimeFilterConfig
from core.report_tasks import ReportTask, analyze_reports
from core.exporter import DataExporter
from ecommerce_spider.analyzer_component import ProductAnalyzerComponent


def actual_payload():
    path = Path(__file__).parent / "fixtures/douyin_elastic_product_image.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_actual_account_feed_elastic_images_reaches_product_model():
    node = actual_payload()
    product = json.loads(node["anchor_info"]["extra"])[0]
    records, diagnostic = extract_products("douyin", node, "账号", "uid")
    assert len(records) == 1
    assert records[0].cover_url == product["elastic_images"][0]["url_list"][0]
    assert "anchor_info.extra" in diagnostic.known_paths_hit
    assert records[0].to_dict()["商品主图"] == records[0].cover_url


@pytest.mark.parametrize("key", ["elastic_images", "elasticImages"])
def test_product_image_has_priority_over_generic_cover_or_cart_icon(key):
    url = "https://images.invalid/product.webp"
    node = {"id": "video", "video": {"cover": {"url_list": ["https://images.invalid/video.jpg"]}},
            "anchor_info": {"icon": {"url_list": ["https://images.invalid/cart.png"]},
                            "extra": json.dumps([{"product_id": "p", "title": "商品标题", key: [{"uri": "ecom-relative-key", "url_list": [url]}],
                                                 "cover": "https://images.invalid/generic.png"}])}}
    records, _ = extract_products("douyin", node, "账号", "uid")
    assert len(records) == 1 and records[0].cover_url == url


def test_reanalyzing_exported_json_keeps_product_image():
    records, _ = extract_products("douyin", actual_payload(), "账号", "uid")
    analyzer = ProductAnalyzerComponent(min_account_count=1, enable_fuzzy_cluster=False)
    retained, _ = analyzer.analyze([record.to_dict() for record in records])
    assert retained[0].cover_url == records[0].cover_url
    assert retained[0].to_summary_dict()["商品主图"] == records[0].cover_url


@pytest.mark.parametrize("field", ["cover_url", "coverUrl", "商品主图"])
def test_sdk_image_aliases_survive_dictionary_import(field):
    records, _ = extract_products("douyin", actual_payload(), "账号", "uid")
    payload = records[0].to_dict()
    url = payload.pop("商品主图")
    payload[field] = url
    retained, _ = ProductAnalyzerComponent(min_account_count=1).analyze([payload])
    assert retained[0].cover_url == url


def test_actual_feed_picture_is_embedded_before_product_name(monkeypatch, tmp_path):
    source = actual_payload()
    records, _ = extract_products("douyin", source, "账号", "uid")
    config = OccurrenceFilterConfig(filter_by="total", min_total_occurrences=1, enable_fuzzy_cluster=False)
    reports = analyze_reports(records, [ReportTask(TimeFilterConfig(mode="all"), config)])
    buffer = io.BytesIO()
    Image.new("RGB", (100, 80), "green").save(buffer, format="WEBP")
    monkeypatch.setattr("core.exporter.load_product_images", lambda urls: {records[0].cover_url: buffer.getvalue()})
    path = tmp_path / "report.xlsx"
    DataExporter.export_to_excel(str(path), reports[0].products, records, reports=reports)
    workbook = load_workbook(path)
    try:
        sheet = workbook["按总频次·抖音"]
        assert sheet["A1"].value == "序号"
        assert sheet["B1"].value == "商品主图"
        assert sheet["C1"].value == "商品名称"
        assert sheet["B2"].value == records[0].cover_url
        assert sheet["B2"].number_format == ";;;"
        assert sheet.column_dimensions["B"].width == 14
        assert len(sheet._images) == 1 and sheet.row_dimensions[2].height >= 58
        anchor = sheet._images[0].anchor._from
        assert (anchor.col, anchor.row) == (1, 1)
    finally:
        workbook.close()
    with ZipFile(path) as archive:
        media = [name for name in archive.namelist() if name.startswith("xl/media/")]
        assert len(media) == 1
        assert Image.open(io.BytesIO(archive.read(media[0]))).format == "PNG"
