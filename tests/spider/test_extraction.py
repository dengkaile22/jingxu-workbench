"""带货商品提取：分层策略、全树扫描与诊断。

这些用例覆盖重写的动因——旧实现只认死字段清单，平台一改字段就静默返回 0 件，
且日志里看不出原因。这里保证：

1. 已知路径能命中（含「商品信息塞在 JSON 字符串里」这种历史写法）；
2. 字段被挪到**全新位置**时，全树扫描能救回来；
3. 确实没挂商品时不误报，且诊断说得清「为什么是 0」。
"""

from __future__ import annotations

import json

import pytest

from core.extraction import (
    ExtractionDiagnostic,
    collect_diagnostics_summary,
    extract_products,
    scan_candidates,
)

VIDEO_ID = "7123456789"
TS = 1758153600


def _douyin_legacy() -> dict:
    """旧版抖音：商品塞在 anchor_info.extra 的 JSON 字符串里。"""
    return {
        "aweme_id": VIDEO_ID,
        "desc": "秋冬必备",
        "create_time": TS,
        "anchor_info": {
            "title": "商品",
            "extra": json.dumps(
                {
                    "title": "生姜防脱洗发水500ml",
                    "product_id": "3600123",
                    "price": 3990,
                    "detail_url": "https://haohuo.jinritemai.com/x",
                },
                ensure_ascii=False,
            ),
        },
    }


def _douyin_moved() -> dict:
    """字段被挪到全新位置：已知路径全空，只能靠全树扫描。"""
    return {
        "aweme_id": VIDEO_ID,
        "desc": "新品上架",
        "create_time": TS,
        "some_new_module": {
            "nested": {
                "shopping_card": {
                    "product_id": "99001",
                    "title": "氨基酸护发素",
                    "price": 29.9,
                }
            }
        },
    }


def _douyin_plain() -> dict:
    """确实没挂商品的普通视频。"""
    return {
        "aweme_id": VIDEO_ID,
        "desc": "纯生活记录",
        "create_time": TS,
        "author": {"nickname": "小王", "uid": "123"},
        "statistics": {"digg_count": 10},
    }


# ── 第一层：已知路径 ────────────────────────────────────────────────────────


def test_extracts_from_json_string_field() -> None:
    items, diagnostic = extract_products("douyin", _douyin_legacy(), "测试号", "uid-1")

    assert len(items) == 1
    assert items[0].product_name == "生姜防脱洗发水500ml"
    assert items[0].product_id == "3600123"
    assert items[0].price == "¥39.90"  # 分单位转元
    assert items[0].platform == "douyin"
    assert "anchor_info.extra" in diagnostic.known_paths_hit


def test_generic_anchor_title_is_not_a_product() -> None:
    """外层 anchor_info.title 是「商品」这类占位说明，不能当成第二个商品。

    实测踩过：anchor_info 与 anchor_info.extra 都命中，结果多出一条名为
    「商品」的假数据。
    """
    node = {
        "aweme_id": VIDEO_ID,
        "anchor_info": {
            "title": "商品",
            "extra": json.dumps({"title": "真实商品名", "product_id": "1"}, ensure_ascii=False),
        },
    }
    items, _ = extract_products("douyin", node, "号", "uid")
    assert [item.product_name for item in items] == ["真实商品名"]


@pytest.mark.parametrize("placeholder", ["商品", "购物车", "小黄车", "去看看", "立即购买", "shop"])
def test_only_generic_placeholder_yields_nothing(placeholder: str) -> None:
    node = {"aweme_id": VIDEO_ID, "anchor_info": {"title": placeholder}}
    items, diagnostic = extract_products("douyin", node, "号", "uid")
    assert items == []
    assert diagnostic.extracted == 0


def test_extracted_item_carries_video_context() -> None:
    items, _ = extract_products(
        "douyin",
        _douyin_legacy(),
        "测试号",
        "uid-1",
        video_title="视频标题",
        video_url="https://www.douyin.com/video/7123456789",
        publish_time=TS,
        publish_time_str="2026-09-18 00:00:00",
    )
    assert items[0].video_title == "视频标题"
    assert items[0].video_url.endswith(VIDEO_ID)
    assert items[0].publish_time == TS


def test_cleaned_name_strips_marketing_noise() -> None:
    node = {
        "aweme_id": VIDEO_ID,
        "anchor_info": {"extra": json.dumps({"title": "【爆款】洗发水 拍1发2"}, ensure_ascii=False)},
    }
    items, _ = extract_products("douyin", node, "号", "uid")
    assert items[0].cleaned_name == "洗发水"


# ── 第二层：全树扫描 ────────────────────────────────────────────────────────


def test_scan_recovers_moved_fields() -> None:
    """平台改字段名/挪位置时，旧实现会静默返回 0 件；扫描必须救回来。"""
    items, diagnostic = extract_products("douyin", _douyin_moved(), "测试号", "uid-1")

    assert len(items) == 1
    assert items[0].product_name == "氨基酸护发素"
    assert diagnostic.known_paths_hit == []
    assert any("shopping_card" in path for path in diagnostic.scan_matched_paths)


def test_scan_does_not_flag_plain_video() -> None:
    """没有商品字段时不得误报。"""
    items, diagnostic = extract_products("douyin", _douyin_plain(), "测试号", "uid-1")

    assert items == []
    assert diagnostic.scan_candidates == 0
    assert "没有挂商品" in diagnostic.note


def test_scan_skips_large_irrelevant_subtrees() -> None:
    """video/music/statistics 等大子树应被跳过，避免把封面当商品。"""
    node = {
        "aweme_id": VIDEO_ID,
        "video": {"cover": {"url_list": ["a"]}, "product_id": "should-not-match", "title": "x"},
        "music": {"title": "bgm", "product_id": "nope"},
    }
    candidates, _ = scan_candidates(node)
    assert all("video." not in item.path and "music." not in item.path for item in candidates)


def test_scan_respects_node_budget() -> None:
    """超大对象不能把界面卡死。"""
    deep: dict = {"product_id": "p", "title": "t"}
    for _ in range(50):
        deep = {"child": deep}
    _, scanned = scan_candidates(deep, max_nodes=5)
    assert scanned <= 6


def test_deduplicates_same_product_from_multiple_paths() -> None:
    node = {
        "aweme_id": VIDEO_ID,
        "anchor_info": {"product_id": "same", "title": "重复商品"},
        "promotions": [{"product_id": "same", "title": "重复商品"}],
    }
    items, _ = extract_products("douyin", node, "号", "uid")
    assert len(items) == 1


# ── 快手 ────────────────────────────────────────────────────────────────────


def test_extracts_kuaishou_goods_info() -> None:
    node = {
        "id": "3xabc",
        "caption": "快手带货",
        "timestamp": TS * 1000,
        "goodsInfo": {"goodsId": "g-1", "title": "牛奶巧巧同款", "price": "39.9"},
    }
    items, diagnostic = extract_products("kuaishou", node, "号", "uid")

    assert len(items) == 1
    assert items[0].product_name == "牛奶巧巧同款"
    assert items[0].price == "¥39.90"
    assert "goodsInfo" in diagnostic.known_paths_hit


def test_kuaishou_scan_recovers_moved_fields() -> None:
    node = {
        "id": "3xabc",
        "caption": "x",
        "newAnchorArea": {"card": {"goods_id": "g-9", "name": "护发素"}},
    }
    items, diagnostic = extract_products("kuaishou", node, "号", "uid")
    assert len(items) == 1
    assert items[0].product_name == "护发素"
    assert diagnostic.scan_matched_paths


# ── 诊断 ────────────────────────────────────────────────────────────────────


def test_diagnostic_records_empty_known_paths() -> None:
    """诊断要能说明「已知路径试过但都为空」，这是排查的关键信息。"""
    node = {"aweme_id": VIDEO_ID, "anchor_info": {}, "promotions": []}
    _, diagnostic = extract_products("douyin", node, "号", "uid")
    assert isinstance(diagnostic, ExtractionDiagnostic)
    assert diagnostic.extracted == 0
    assert isinstance(diagnostic.known_paths_empty, list)


def test_diagnostic_summary_mentions_counts_when_empty() -> None:
    _, diagnostic = extract_products("douyin", _douyin_plain(), "号", "uid")
    summary = diagnostic.summary()
    assert "未提取到商品" in summary
    assert "扫描" in summary


def test_diagnostic_to_dict_is_json_serialisable() -> None:
    _, diagnostic = extract_products("douyin", _douyin_legacy(), "号", "uid")
    payload = json.dumps(diagnostic.to_dict(), ensure_ascii=False)
    assert "knownPathsHit" in payload


def test_collect_summary_counts_videos_with_and_without_products() -> None:
    _, with_product = extract_products("douyin", _douyin_legacy(), "号", "uid")
    _, without = extract_products("douyin", _douyin_plain(), "号", "uid")

    summary = collect_diagnostics_summary([with_product, without, without])
    assert summary["videosScanned"] == 3
    assert summary["videosWithProducts"] == 1
    assert summary["videosWithoutProducts"] == 2
    assert summary["knownPathHits"].get("anchor_info.extra") == 1


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (3990, "¥39.90"),      # 整数且 >1000：按"分"处理（抖音常见）
        (29.9, "¥29.90"),      # 浮点：按"元"处理
        (12, "¥12"),           # 小整数：按"元"处理，不加小数位
        ("39.9", "¥39.90"),    # 字符串数字：规整为两位小数
        ("¥12.5", "¥12.5"),    # 已带货币符号：原样保留
        ("", ""),              # 空值
    ],
)
def test_price_normalisation(price, expected) -> None:  # noqa: ANN001
    # 标题必须用真实商品名：通用占位（如「商品」）会被 _is_generic_anchor_title 过滤
    node = {"aweme_id": VIDEO_ID, "anchor_info": {"title": "洗发水", "price": price}}
    items, _ = extract_products("douyin", node, "号", "uid")
    assert items[0].price == expected


def test_extract_products_extracts_like_count() -> None:
    # 抖音 statistics.digg_count
    node_dy = {
        "aweme_id": "12345",
        "statistics": {"digg_count": 8888},
        "anchor_info": {"title": "纯棉T恤", "price": "29.9"},
    }
    items_dy, _ = extract_products("douyin", node_dy, "抖音号", "uid1")
    assert len(items_dy) == 1
    assert items_dy[0].like_count == 8888

    # 快手 counts.likeCount
    node_ks = {
        "photo_id": "67890",
        "counts": {"likeCount": 6666},
        "caption": "快手好物",
        "product_id": "ks-1",
        "title": "保温水杯",
    }
    items_ks, _ = extract_products("kuaishou", node_ks, "快手号", "uid2")
    assert len(items_ks) == 1
    assert items_ks[0].like_count == 6666


def test_parse_chinese_count_str() -> None:
    from core.text_utils import parse_chinese_count_str

    assert parse_chinese_count_str("1.2万") == 12000
    assert parse_chinese_count_str("3.5w") == 35000
    assert parse_chinese_count_str("3500w") == 35000000
    assert parse_chinese_count_str("1000+") == 1000
    assert parse_chinese_count_str("1,234") == 1234
    assert parse_chinese_count_str("获赞 8.6万") == 86000
    assert parse_chinese_count_str(999) == 999
    assert parse_chinese_count_str("1.5亿") == 150000000
    assert parse_chinese_count_str("") == 0
    assert parse_chinese_count_str(None) == 0


def test_extract_products_multi_product_promotions() -> None:
    """单个视频挂载多件商品时，必须全部提取，不能只取首件。"""
    node = {
        "aweme_id": "789012",
        "desc": "好物合集推荐",
        "promotions": [
            {"promotion_id": "p-1", "title": "洁面乳100g", "price": 2990},
            {"promotion_id": "p-2", "title": "保湿水200ml", "price": 4990},
            {"promotion_id": "p-3", "title": "修护面霜50g", "price": 6990},
        ],
    }
    items, diagnostic = extract_products("douyin", node, "博主A", "uid-A")
    assert len(items) == 3
    assert [it.product_name for it in items] == ["洁面乳100g", "保湿水200ml", "修护面霜50g"]
    assert [it.price for it in items] == ["¥29.90", "¥49.90", "¥69.90"]
    assert "promotions" in diagnostic.known_paths_hit


def test_extract_products_multi_product_anchors() -> None:
    """抖音 anchors 列表中多个商品包装 JSON 字符串时能全部提取。"""
    node = {
        "aweme_id": "789013",
        "anchors": [
            {
                "anchor_info": json.dumps({"title": "无糖乌龙茶500ml*15瓶", "product_id": "tea-1", "price": 39.9}),
            },
            {
                "anchor_info": json.dumps({"title": "茉莉花茶500ml*15瓶", "product_id": "tea-2", "price": 39.9}),
            },
        ],
    }
    items, diagnostic = extract_products("douyin", node, "博主B", "uid-B")
    assert len(items) == 2
    assert items[0].product_name == "无糖乌龙茶500ml*15瓶"
    assert items[1].product_name == "茉莉花茶500ml*15瓶"


def test_extract_products_chinese_like_count_str() -> None:
    """点赞数为带单位字符串（如 '2.3万'）时能正确解析为整数。"""
    node = {
        "aweme_id": "789014",
        "statistics": {"digg_count_str": "2.3万"},
        "anchor_info": {"title": "纯棉浴巾", "price": 19.9},
    }
    items, _ = extract_products("douyin", node, "博主C", "uid-C")
    assert len(items) == 1
    assert items[0].like_count == 23000
