"""选品结果表与 .NET 的列对齐。

.NET 结果表有八列：商品名称 / 清洗归一名称 / 平台 / 对标账号数 / 带货视频数 /
带货达人明细 / 参考售价 / 示例视频链接。

Python 原来只有四列（商品 / 跨账号数 / 出现次数 / 价格区间），**丢掉了**
「对标账号明细」与「示例视频链接」——恰恰是做选品判断时最需要的两条：
哪些账号在带货、以及点进去看一条实例。

数据其实一直都在：爬虫 ``RetainedProduct.to_summary_dict()`` 输出八个中文键，
只是界面没往里读。本文件守住「八个字段都要展示 + 键名兜底」。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jingxu.ui.spider_page import (  # noqa: E402
    RESULT_CHECK_COLUMN,
    RESULT_COLUMNS,
    RESULT_NAME_COLUMN,
    _entry_columns,
)


# ── 列集合 ──────────────────────────────────────────────────────────────────


def test_result_columns_cover_dotnet_fields() -> None:
    """八列都要在（首列是本版新增的勾选列）。"""
    for name in (
        "商品",
        "清洗名称",
        "平台",
        "跨账号数",
        "出现次数",
        "对标账号明细",
        "价格区间",
        "示例视频链接",
    ):
        assert name in RESULT_COLUMNS, f"结果表缺少「{name}」列（当前：{RESULT_COLUMNS}）"

    assert len(RESULT_COLUMNS) == 9
    assert RESULT_COLUMNS[RESULT_CHECK_COLUMN] == "选"
    assert RESULT_COLUMNS[RESULT_NAME_COLUMN] == "商品"


# ── 字段映射：中文键（爬虫 to_summary_dict 的原样输出） ──────────────────────


def test_maps_spider_summary_keys() -> None:
    """爬虫 ``RetainedProduct.to_summary_dict()`` 的中文键必须全部读到。"""
    entry = {
        "商品名称": "纯棉短袖T恤",
        "清洗名称": "短袖t恤",
        "涉及平台": "douyin",
        "带货账号数": 3,
        "带货视频数": 7,
        "对标账号明细": "小A、小B、小C",
        "参考价格": "¥29.9 - ¥39.9",
        "示例视频链接": "https://www.douyin.com/video/123",
    }

    assert _entry_columns(entry) == (
        "纯棉短袖T恤",
        "短袖t恤",
        "douyin",
        "3",
        "7",
        "小A、小B、小C",
        "¥29.9 - ¥39.9",
        "https://www.douyin.com/video/123",
    )


def test_accounts_list_is_joined() -> None:
    """「对标账号明细」在 JSON 里是数组时拼成顿号分隔。"""
    columns = _entry_columns({"accounts": ["小A", "小B"], "video_count": 2})

    assert columns[5] == "小A、小B"


# ── 字段映射：英文别名兜底 ──────────────────────────────────────────────────


def test_maps_snake_case_aliases() -> None:
    entry = {
        "product_name": "耳机",
        "cleaned_name": "耳机",
        "platform": "kuaishou",
        "account_count": 2,
        "video_count": 5,
        "price_range": "¥9.9",
        "sample_video_url": "https://v.kuaishou.com/abc",
    }
    columns = _entry_columns(entry)

    assert columns[0] == "耳机"
    assert columns[3] == "2"
    assert columns[4] == "5"
    assert columns[6] == "¥9.9"
    assert columns[7] == "https://v.kuaishou.com/abc"


def test_maps_camel_case_aliases() -> None:
    entry = {
        "productName": "水杯",
        "cleanedName": "水杯",
        "accountCount": 4,
        "videoCount": 9,
        "priceRange": "¥19.9",
        "sampleVideoUrl": "https://example.com/v",
    }
    columns = _entry_columns(entry)

    assert columns[0] == "水杯"
    assert columns[3] == "4"
    assert columns[4] == "9"
    assert columns[7] == "https://example.com/v"


def test_falls_back_to_total_occurrences_for_video_count() -> None:
    """旧字段 ``total_occurrences`` 仍要能填进「带货视频数」列。"""
    assert _entry_columns({"name": "x", "total_occurrences": 6})[4] == "6"


def test_missing_values_show_dash() -> None:
    """缺失显示破折号，便于分辨"没有"与"取不到"。"""
    columns = _entry_columns({})

    assert len(columns) == len(RESULT_COLUMNS) - 1
    assert set(columns) == {"—"}


def test_zero_counts_are_not_treated_as_missing() -> None:
    """0 是有效值（真实计数），不能被当成"没有"而显示破折号。"""
    columns = _entry_columns({"name": "x", "account_count": 0, "video_count": 0})

    assert columns[3] == "0"
    assert columns[4] == "0"


def test_empty_list_is_treated_as_missing() -> None:
    assert _entry_columns({"name": "x", "accounts": []})[5] == "—"
