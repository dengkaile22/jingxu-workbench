"""跨账号「相同商品」判定与保留门槛（直接驱动真实爬虫分析器）。

核心需求：抖音/快手多账号短视频带货商品名称爬取，**保留相同项**。
判定成败取决于两件事，这里都用真实分析器验证，不做替身：

1. 同名判定——不同账号标题里的营销词（【爆款】、包邮、拍1发2…）必须被归一化，
   再按相似度合并，否则同一商品永远凑不够「跨账号」门槛；
2. 门槛语义——「跨账号数」与「总频次」是两个独立条件，必须能区分开。

分析器来自 ``src/JingXu.Workbench.Py/JingXu.Spider``（选品爬虫本体）。与它自身的测试目录不同，
这里是从工作台视角做的端到端契约测试，因此放在本套件中。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from jingxu.infrastructure.spider import spider_directory

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _spider_root() -> Path | None:
    """定位爬虫源码目录（优先环境变量/仓库布局）。"""
    directory = spider_directory()
    if directory is not None:
        return directory
    fallback = _REPO_ROOT / "src" / "JingXu.Workbench.Py" / "JingXu.Spider"
    return fallback if (fallback / "cli.py").is_file() else None


_SPIDER_ROOT = _spider_root()
if _SPIDER_ROOT is not None and str(_SPIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPIDER_ROOT))

pytestmark = pytest.mark.skipif(
    _SPIDER_ROOT is None, reason="未找到选品爬虫源码（src/JingXu.Workbench.Py/JingXu.Spider）"
)


def _analyzer(**config_overrides):  # noqa: ANN202
    from core.analyzer import ProductAnalyzer
    from core.config import OccurrenceFilterConfig

    return ProductAnalyzer(OccurrenceFilterConfig(**config_overrides))


def _item(name: str, account: str, *, platform: str = "douyin", video_id: str = ""):  # noqa: ANN202
    from core.models import VideoProductItem

    vid = video_id or f"{account}-{abs(hash(name)) % 10000}"
    return VideoProductItem(
        platform=platform,
        account_name=account,
        account_id=f"uid-{account}",
        video_id=vid,
        video_title=f"{name} 带货视频",
        video_url=f"https://example.com/video/{vid}",
        publish_time=1758153600,
        publish_time_str="2026-09-18 12:00:00",
        product_id=f"pid-{account}-{abs(hash(name)) % 10000}",
        product_name=name,
    )


# ── 标题归一化：不归一化就永远凑不够跨账号门槛 ──────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("【官方正品 包邮】超能植翠低泡洗衣液3kg 拍1发2", "超能植翠低泡洗衣液3kg"),
        ("氨基酸护发素 顺滑修复 主播力荐 现货速发", "氨基酸护发素 顺滑修复"),
    ],
)
def test_marketing_noise_is_cleaned(raw: str, expected: str) -> None:
    from core.text_utils import clean_product_title

    assert clean_product_title(raw) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("生姜防脱洗发水500ml", "【爆款】生姜防脱洗发水 500ml 控油"),
        ("超能植翠低泡洗衣液3kg", "超能植翠低泡洗衣液 3kg 官方正品"),
        ("氨基酸护发素", "氨基酸护发素 顺滑修复"),
    ],
)
def test_same_product_across_accounts_is_matched(left: str, right: str) -> None:
    """同一商品在不同账号的标题写法不同，必须判为同款（阈值 0.75）。"""
    from core.text_utils import calculate_string_similarity

    assert calculate_string_similarity(left, right) >= 0.75


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("生姜防脱洗发水500ml", "男士控油洗面奶100g"),
        ("防晒霜SPF50+", "防晒喷雾SPF50+"),
    ],
)
def test_different_products_are_not_merged(left: str, right: str) -> None:
    """不同商品不得被合并——误合并会制造虚假的「跨账号相同项」。"""
    from core.text_utils import calculate_string_similarity

    assert calculate_string_similarity(left, right) < 0.75


# ── 聚类 + 保留门槛 ─────────────────────────────────────────────────────────


def _cross_account_items() -> list:
    """3 个账号、10 条记录：两款跨账号商品 + 两款单账号商品。"""
    return [
        # 生姜洗发水：3 账号 4 条（标题写法各异）
        _item("生姜防脱洗发水500ml", "账号A", video_id="a1"),
        _item("【爆款】生姜防脱洗发水 500ml 控油", "账号A", video_id="a2"),
        _item("生姜防脱洗发水 500ml 官方正品", "账号B", video_id="b1"),
        _item("生姜防脱洗发水500ml 买一送一", "账号C", platform="kuaishou", video_id="c1"),
        # 洗衣液：3 账号 3 条
        _item("超能植翠低泡洗衣液3kg", "账号A", video_id="a3"),
        _item("超能植翠低泡洗衣液 3kg 包邮", "账号B", video_id="b2"),
        _item("超能植翠低泡洗衣液3kg 特惠", "账号C", platform="kuaishou", video_id="c2"),
        # 护发素：仅账号A 2 条
        _item("氨基酸护发素 顺滑修复", "账号A", video_id="a4"),
        _item("氨基酸护发素 顺滑修复 主播力荐", "账号A", video_id="a5"),
        # 洗面奶：仅账号B 1 条
        _item("男士控油洗面奶100g", "账号B", video_id="b3"),
    ]


def test_fuzzy_clustering_merges_variants() -> None:
    """开启模糊合并：10 条 → 4 款（同款的不同写法归并）。"""
    _, aggregated = _analyzer(
        min_account_count=1, min_total_occurrences=1, filter_by="accounts"
    ).aggregate_and_filter(_cross_account_items())
    assert len(aggregated) == 4


def test_disabling_fuzzy_clustering_splits_variants() -> None:
    """关闭模糊合并：同款的不同写法各自成款，跨账号门槛因此失效——
    这正是「保留相同项」必须依赖归一化+相似度的原因。"""
    retained, aggregated = _analyzer(
        min_account_count=2, min_total_occurrences=1,
        filter_by="accounts", enable_fuzzy_cluster=False,
    ).aggregate_and_filter(_cross_account_items())
    assert len(aggregated) == 8
    assert len(retained) == 1


def test_cross_account_retention_counts_distinct_accounts() -> None:
    """默认门槛（≥2 个账号）只保留真正的跨账号商品，并给出账号明细。"""
    retained, _ = _analyzer(
        min_account_count=2, min_total_occurrences=1, filter_by="accounts"
    ).aggregate_and_filter(_cross_account_items())

    names = [product.cleaned_name for product in retained]
    assert len(retained) == 2
    assert any("生姜防脱洗发水" in name for name in names)
    assert any("洗衣液" in name for name in names)

    shampoo = next(p for p in retained if "生姜防脱洗发水" in p.cleaned_name)
    assert shampoo.account_count == 3
    assert shampoo.video_count == 4
    assert set(shampoo.accounts) == {"账号A", "账号B", "账号C"}


def test_single_account_products_are_excluded() -> None:
    """只在 1 个账号出现的商品不得保留（哪怕反复出现多次）。"""
    retained, _ = _analyzer(
        min_account_count=2, min_total_occurrences=1, filter_by="accounts"
    ).aggregate_and_filter(_cross_account_items())

    assert all(product.account_count >= 2 for product in retained)


def test_cross_platform_products_are_merged() -> None:
    """同一商品跨抖音与快手也要合并，并标注为跨平台。"""
    retained, _ = _analyzer(
        min_account_count=2, min_total_occurrences=1, filter_by="accounts"
    ).aggregate_and_filter(_cross_account_items())

    shampoo = next(p for p in retained if "生姜防脱洗发水" in p.cleaned_name)
    assert "douyin" in shampoo.platform and "kuaishou" in shampoo.platform


def test_account_threshold_and_frequency_threshold_are_independent() -> None:
    """两种门槛语义必须可区分：「多账号低频」与「单账号高频」各归各的。

    这是需求 3 的关键——若两者等价，界面上分设「跨账号数」与「总频次」
    就没有意义。
    """
    items = [
        # 单账号推 4 次：账号数 1、频次 4
        _item("玻尿酸原液精华30ml", "账号A", video_id="d1"),
        _item("玻尿酸原液精华30ml", "账号A", video_id="d2"),
        _item("玻尿酸原液精华30ml", "账号A", video_id="d3"),
        _item("玻尿酸原液精华30ml", "账号A", video_id="d4"),
        # 两账号各 1 次：账号数 2、频次 2
        _item("烟酰胺身体乳400ml", "账号A", video_id="e1"),
        _item("烟酰胺身体乳400ml", "账号B", video_id="e2"),
    ]

    by_accounts, _ = _analyzer(
        min_account_count=2, min_total_occurrences=1, filter_by="accounts"
    ).aggregate_and_filter(items)
    by_total, _ = _analyzer(
        min_account_count=1, min_total_occurrences=4, filter_by="total"
    ).aggregate_and_filter(items)
    by_both, _ = _analyzer(
        min_account_count=2, min_total_occurrences=4, filter_by="both"
    ).aggregate_and_filter(items)

    assert [p.cleaned_name for p in by_accounts] == ["烟酰胺身体乳400ml"]
    assert [p.cleaned_name for p in by_total] == ["玻尿酸原液精华30ml"]
    # 没有任何商品同时满足两个条件
    assert by_both == []


def test_results_sorted_by_account_then_frequency() -> None:
    """结果按「账号数 → 频次」降序，跨账号最多的排最前。"""
    retained, _ = _analyzer(
        min_account_count=1, min_total_occurrences=1, filter_by="accounts"
    ).aggregate_and_filter(_cross_account_items())

    keys = [(p.account_count, p.video_count) for p in retained]
    assert keys == sorted(keys, reverse=True)


def test_identical_precheck_helper() -> None:
    from core.text_utils import are_products_identical

    assert are_products_identical("生姜防脱洗发水500ml", "生姜防脱洗发水 500ml 控油") is True
    assert are_products_identical("生姜防脱洗发水500ml", "男士控油洗面奶100g") is False
