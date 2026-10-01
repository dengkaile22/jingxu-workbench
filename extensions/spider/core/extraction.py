"""带货商品提取：分层策略 + 全树扫描 + 可观测诊断。

为什么重写
----------
旧实现（``douyin_crawler.extract_douyin_products_from_aweme`` /
``kuaishou_crawler.extract_kuaishou_products_from_photo``）各自写死一份字段
路径清单，例如抖音只找 ``anchor_info`` / ``promotions`` / ``anchors``。一旦
平台改字段名，提取就静默返回空——实测表现正是「已处理 57 个视频，累计发现带货
商品 0 件」，而日志里看不出任何原因。

新实现分三层，逐层放宽，并且**始终产出诊断**：

1. **已知路径**：平台各自的候选路径登记表，逐条尝试并记录命中/为空；
2. **全树扫描**：递归遍历该视频的 JSON，找出所有"像商品"的节点
   （依据商品特征键，如 ``product_id`` / ``goods_id`` / ``promotion_id``），
   以覆盖平台改字段名或把商品挪到新位置的情况；
3. **候选评分**：对扫描结果按特征键数量、是否有标题、是否有价格打分，
   过滤掉明显误报（纯 ID、作者信息等）。

诊断记录会写进日志与 ``--json-out``，使「提取不到商品」变成可定位问题：
能看到扫描了多少节点、命中了哪些路径、哪些已知路径为空。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import VideoProductItem
from core.text_utils import clean_product_title, parse_chinese_count_str

# ── 商品特征键 ──────────────────────────────────────────────────────────────
# 出现这些键的字典"可能是商品"。用于全树扫描时筛选候选节点。
PRODUCT_ID_KEYS = (
    "product_id",
    "productId",
    "goods_id",
    "goodsId",
    "promotion_id",
    "promotionId",
    "item_id",
    "itemId",
    "commodity_id",
    "commodityId",
    "shop_product_id",
    "sku_id",
    "skuId",
)
PRODUCT_TITLE_KEYS = (
    "title",
    "name",
    "product_name",
    "productName",
    "goods_name",
    "goodsName",
    "goods_title",
    "item_title",
    "product_title",
    "commodity_name",
    "commodityName",
    "header",
)
PRODUCT_PRICE_KEYS = (
    "price",
    "price_str",
    "priceStr",
    "sale_price",
    "salePrice",
    "real_price",
    "realPrice",
    "coupon_price",
    "discount_price",
    "discountPrice",
    "min_price",
    "minPrice",
    "goods_price",
    "origin_price",
    "market_price",
)
PRODUCT_URL_KEYS = (
    "detail_url",
    "detailUrl",
    "jump_url",
    "jumpUrl",
    "url",
    "h5_url",
    "h5Url",
    "schema",
    "link",
    "open_url",
)

# 通用锚点标题：这些只是"这里有个商品位"的占位说明，不是商品名。
# 不排除的话，外层 anchor_info.title（值为「商品」）会被当成第二个商品，
# 制造出并不存在的条目。
GENERIC_ANCHOR_TITLES = frozenset(
    {
        "商品",
        "商品橱窗",
        "购物车",
        "小黄车",
        "商品详情",
        "橱窗",
        "商品卡",
        "宝贝",
        "去看看",
        "立即购买",
        "商品链接",
        "shop",
        "product",
        "goods",
        "commodity",
        "item",
    }
)


def _is_generic_anchor_title(title: str) -> bool:
    """判断标题是否只是通用占位说明而非真实商品名。"""
    text = (title or "").strip()
    if not text:
        return True
    return text.lower() in GENERIC_ANCHOR_TITLES


# 误报排除：这些键名出现时，节点更可能是视频/用户/统计信息而非商品
FALSE_POSITIVE_KEYS = frozenset(
    {
        "aweme_id",
        "sec_uid",
        "uid",
        "user_id",
        "author",
        "statistics",
        "video",
        "music",
        "cover",
        "share_info",
    }
)

# 需要跳过的子树：体积大且不可能含商品
SKIP_KEYS = frozenset({"video", "music", "cover", "statistics", "seo_info", "images"})


@dataclass
class ExtractionDiagnostic:
    """一次提取的过程记录，用于回答「为什么没提取到商品」。"""

    platform: str = ""
    video_id: str = ""
    known_paths_hit: list[str] = field(default_factory=list)
    known_paths_empty: list[str] = field(default_factory=list)
    scanned_nodes: int = 0
    scan_candidates: int = 0
    scan_matched_paths: list[str] = field(default_factory=list)
    extracted: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "videoId": self.video_id,
            "knownPathsHit": list(self.known_paths_hit),
            "knownPathsEmpty": list(self.known_paths_empty),
            "scannedNodes": self.scanned_nodes,
            "scanCandidates": self.scan_candidates,
            "scanMatchedPaths": list(self.scan_matched_paths),
            "extracted": self.extracted,
            "note": self.note,
        }

    def summary(self) -> str:
        """一行日志摘要，便于在运行日志里直接看到原因。"""
        parts = [f"命中路径 {self.known_paths_hit or '无'}"]
        if self.scan_matched_paths:
            parts.append(f"扫描命中 {self.scan_matched_paths}")
        if self.extracted == 0:
            parts.append(
                f"未提取到商品（已知路径均为空：{self.known_paths_empty or '无'}；"
                f"扫描 {self.scanned_nodes} 个节点、{self.scan_candidates} 个候选）"
            )
        else:
            parts.append(f"提取 {self.extracted} 件")
        if self.note:
            parts.append(self.note)
        return "；".join(parts)


# ── 已知路径登记表 ──────────────────────────────────────────────────────────

# 路径写法："a.b.c" 表示逐层取字典键；列表节点可自动展开或用 "a[0].b" 取指定元素。
DOUYIN_CANDIDATE_PATHS: tuple[str, ...] = (
    "anchor_info.extra",  # 旧版：extra 是 JSON 字符串，含商品详情
    "anchor_info",
    "anchors",
    "anchors[0]",
    "promotions",
    "promotions[0]",
    "aweme_anchor_info",
    "video_anchor",
    "anchor",
    "commerce_info",
    "commerce_info.anchor_info",
    "commerce_config_data",
    "anchor_info.extra_info",
    "goods_info",
    "goods_info.goods_list",
    "card_entries",
    "standard_bar_info",
    "search_impr",
    "interaction_stickers",
    "customized_stickers",
    "cha_list[0]",  # 挑战/话题位偶尔承载商品
    "promotion_info",
    "product_info",
)

KUAISHOU_CANDIDATE_PATHS: tuple[str, ...] = (
    "goodsInfo",
    "commodity",
    "productInfo",
    "goods_info",
    "goods_info.goods_list",
    "ext_params",
    "extParams",
    "anchor",
    "anchorInfo",
    "commerceInfo",
    "photo.goodsInfo",
    "atlas.goodsInfo",
    "shopInfo",
    "merchant",
    "product_list",
    "products",
)

PLATFORM_PATHS = {
    "douyin": DOUYIN_CANDIDATE_PATHS,
    "kuaishou": KUAISHOU_CANDIDATE_PATHS,
}


def _dig_nodes(node: Any, path: str) -> list[tuple[str, Any]]:
    """按路径取值，支持自动展开列表节点。
    例如 'promotions' 若是包含 3 个字典的列表，会展开成
    [('promotions[0]', d0), ('promotions[1]', d1), ('promotions[2]', d2)]。
    若指定明确索引如 'promotions[0]'，则只取指定索引。
    """
    results: list[tuple[str, Any]] = [("", node)]
    for raw_segment in path.split("."):
        next_results: list[tuple[str, Any]] = []
        segment = raw_segment
        index = None
        if "[" in segment and segment.endswith("]"):
            head, _, tail = segment.partition("[")
            segment = head
            try:
                index = int(tail[:-1])
            except ValueError:
                index = None

        for curr_path, current in results:
            if not isinstance(current, dict):
                continue
            if segment:
                if segment not in current:
                    continue
                val = current[segment]
                step_path = f"{curr_path}.{segment}" if curr_path else segment
            else:
                val = current
                step_path = curr_path

            if index is not None:
                if isinstance(val, (list, tuple)) and len(val) > index:
                    next_results.append((f"{step_path}[{index}]", val[index]))
            else:
                if isinstance(val, (list, tuple)):
                    for i, elem in enumerate(val):
                        next_results.append((f"{step_path}[{i}]", elem))
                else:
                    next_results.append((step_path, val))

        results = next_results
        if not results:
            break
    return results


def _dig(node: Any, path: str) -> tuple[bool, Any]:
    """按 ``a.b[0].c`` 形式的路径取值；返回（是否取到, 值）。"""
    nodes = _dig_nodes(node, path)
    if nodes:
        return True, nodes[0][1]
    return False, None


def _resolve_product_dict(val: Any) -> list[dict]:
    """尝试将值解析为一个或多个商品字典（支持嵌套 JSON 字符串、列表和子字典包装）。"""
    decoded = _maybe_json(val)
    if isinstance(decoded, (list, tuple)):
        res: list[dict] = []
        for x in decoded:
            res.extend(_resolve_product_dict(x))
        return res
    if not isinstance(decoded, dict):
        return []

    # 如果字典内含有嵌套的 JSON 字符串或商品子节点（如 anchors 里的 anchor_info / extra）
    for sub_key in (
        "anchor_info",
        "extra",
        "goods_info",
        "commodity",
        "product",
        "goods",
        "shop_info",
    ):
        sub_val = decoded.get(sub_key)
        if isinstance(sub_val, str) and sub_val.strip().startswith(("{", "[")):
            nested = _maybe_json(sub_val)
            if isinstance(nested, (dict, list, tuple)):
                return _resolve_product_dict(nested)
        elif isinstance(sub_val, dict) and any(
            k in sub_val for k in PRODUCT_TITLE_KEYS
        ):
            return [sub_val]

    return [decoded]


def _maybe_json(value: Any) -> Any:
    """有些字段把商品信息塞在 JSON 字符串里（如抖音 anchor_info.extra）。"""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return value


def _first_of(node: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in node and node[key] not in (None, "", [], {}):
            return node[key]
    return None


def _price_text(value: Any) -> str:
    """把价格字段规整成 ``¥x.xx`` 文本；识别分/元两种单位。"""
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("¥"):
            return text
        try:
            numeric = float(text)
        except ValueError:
            return text
        value = int(numeric) if numeric.is_integer() else numeric
    if isinstance(value, (int, float)):
        # 大于 1000 的整数按"分"处理（抖音常见分单位）
        if value > 1000 and float(value).is_integer():
            return f"¥{value / 100:.2f}"
        return f"¥{value:.2f}" if isinstance(value, float) else f"¥{value}"
    return str(value)


@dataclass
class _Candidate:
    """全树扫描得到的候选商品节点。"""

    path: str
    title: str = ""
    product_id: str = ""
    price: str = ""
    detail_url: str = ""
    score: int = 0


def _score_candidate(node: dict) -> int:
    """给候选节点打分：特征键越多越像商品。"""
    score = 0
    if _first_of(node, PRODUCT_TITLE_KEYS):
        score += 3
    if _first_of(node, PRODUCT_ID_KEYS):
        score += 2
    if _first_of(node, PRODUCT_PRICE_KEYS):
        score += 1
    if _first_of(node, PRODUCT_URL_KEYS):
        score += 1
    # 误报惩罚：明显是视频/用户信息
    if FALSE_POSITIVE_KEYS & set(node):
        score -= 2
    return score


def scan_candidates(
    node: Any,
    *,
    max_nodes: int = 20000,
    max_depth: int = 12,
) -> tuple[list[_Candidate], int]:
    """全树扫描，返回（候选列表, 扫描节点数）。

    只收集"像商品"的字典；``score`` 过低的不返回，避免把视频/用户信息当成商品。
    """
    candidates: list[_Candidate] = []
    scanned = 0
    stack: list[tuple[Any, str, int]] = [(node, "", 0)]

    while stack and scanned < max_nodes:
        current, path, depth = stack.pop()
        scanned += 1
        if depth > max_depth:
            continue

        if isinstance(current, dict):
            has_product_key = any(key in current for key in PRODUCT_ID_KEYS)
            has_title = any(key in current for key in PRODUCT_TITLE_KEYS)
            if has_product_key and has_title:
                score = _score_candidate(current)
                if score >= 3:
                    candidates.append(
                        _Candidate(
                            path=path or "$",
                            title=str(
                                _first_of(current, PRODUCT_TITLE_KEYS) or ""
                            ).strip(),
                            product_id=str(_first_of(current, PRODUCT_ID_KEYS) or ""),
                            price=_price_text(_first_of(current, PRODUCT_PRICE_KEYS)),
                            detail_url=str(_first_of(current, PRODUCT_URL_KEYS) or ""),
                            score=score,
                        )
                    )
            for key, value in current.items():
                if key in SKIP_KEYS:
                    continue
                if isinstance(value, (dict, list, tuple)):
                    stack.append((value, f"{path}.{key}" if path else key, depth + 1))
                elif isinstance(value, str):
                    decoded = _maybe_json(value)
                    if isinstance(decoded, (dict, list)):
                        stack.append((decoded, f"{path}.{key}", depth + 1))
        elif isinstance(current, (list, tuple)):
            for index, value in enumerate(current):
                if isinstance(value, (dict, list, tuple, str)):
                    stack.append((value, f"{path}[{index}]", depth + 1))

    return candidates, scanned


def _extract_like_count(platform_name: str, raw_node: dict) -> int:
    """从原始节点中提取点赞数/digg_count，支持中文/带单位计数。"""
    if not isinstance(raw_node, dict):
        return 0
    # 抖音 statistics 字典
    stats = raw_node.get("statistics")
    if isinstance(stats, dict):
        for k in (
            "digg_count",
            "like_count",
            "admire_count",
            "digg_count_str",
            "like_count_str",
        ):
            val = stats.get(k)
            if val not in (None, ""):
                parsed = parse_chinese_count_str(val)
                if parsed > 0:
                    return parsed
    # 快手 counts 字典
    counts = raw_node.get("counts")
    if isinstance(counts, dict):
        for k in (
            "likeCount",
            "likedCount",
            "like_count",
            "likeCountStr",
            "likedCountStr",
        ):
            val = counts.get(k)
            if val not in (None, ""):
                parsed = parse_chinese_count_str(val)
                if parsed > 0:
                    return parsed
    # 直接出现在根节点的键
    for k in (
        "digg_count",
        "like_count",
        "likeCount",
        "likedCount",
        "realLikeCount",
        "diggCount",
        "likes",
        "star_count",
        "digg_count_str",
        "like_count_str",
    ):
        val = raw_node.get(k)
        if val not in (None, ""):
            parsed = parse_chinese_count_str(val)
            if parsed > 0:
                return parsed
    return 0


def extract_products(
    platform: str,
    node: dict,
    account_name: str,
    account_id: str,
    *,
    video_title: str = "",
    video_url: str = "",
    publish_time: int = 0,
    publish_time_str: str = "",
    like_count: int = 0,
) -> tuple[list[VideoProductItem], ExtractionDiagnostic]:
    """从一条视频数据里提取带货商品。

    返回（商品列表, 诊断）。诊断无论成败都会产出，便于回答「为什么是 0 件」。
    """
    diagnostic = ExtractionDiagnostic(
        platform=platform,
        video_id=str(
            node.get("aweme_id")
            or node.get("photo_id")
            or node.get("photoId")
            or node.get("id")
            or ""
        ),
    )
    products: list[VideoProductItem] = []
    seen_keys: set[str] = set()

    if like_count <= 0:
        like_count = _extract_like_count(platform, node)

    def _add(title: str, product_id: str, price: str, detail_url: str) -> None:
        title = (title or "").strip()
        if not title:
            return
        key = product_id or title
        if key in seen_keys:
            return
        seen_keys.add(key)
        products.append(
            VideoProductItem(
                platform=platform,
                account_name=account_name,
                account_id=account_id,
                video_id=diagnostic.video_id,
                video_title=video_title,
                video_url=video_url,
                publish_time=publish_time,
                publish_time_str=publish_time_str,
                product_id=product_id,
                product_name=title,
                cleaned_name=clean_product_title(title),
                price=price,
                detail_url=detail_url,
                like_count=like_count,
            )
        )

    # ── 第一层：已知路径 ────────────────────────────────────────────────────
    for path in PLATFORM_PATHS.get(platform, ()):
        nodes = _dig_nodes(node, path)
        if not nodes:
            if path in node and node[path] in (None, "", [], {}):
                if path not in diagnostic.known_paths_empty:
                    diagnostic.known_paths_empty.append(path)
            continue

        for hit_path, raw_val in nodes:
            dicts = _resolve_product_dict(raw_val)
            if not dicts:
                if isinstance(raw_val, str) and not _is_generic_anchor_title(raw_val):
                    if path not in diagnostic.known_paths_hit:
                        diagnostic.known_paths_hit.append(path)
                    _add(raw_val, "", "", "")
                else:
                    if path not in diagnostic.known_paths_empty:
                        diagnostic.known_paths_empty.append(path)
                continue

            extracted_any = False
            for d in dicts:
                title = str(_first_of(d, PRODUCT_TITLE_KEYS) or "").strip()
                if not title and isinstance(raw_val, dict):
                    title = str(_first_of(raw_val, PRODUCT_TITLE_KEYS) or "").strip()

                if not title or _is_generic_anchor_title(title):
                    continue

                product_id = str(
                    _first_of(d, PRODUCT_ID_KEYS)
                    or (
                        isinstance(raw_val, dict)
                        and _first_of(raw_val, PRODUCT_ID_KEYS)
                    )
                    or ""
                )
                price = _price_text(
                    _first_of(d, PRODUCT_PRICE_KEYS)
                    or (
                        isinstance(raw_val, dict)
                        and _first_of(raw_val, PRODUCT_PRICE_KEYS)
                    )
                )
                detail_url = str(
                    _first_of(d, PRODUCT_URL_KEYS)
                    or (
                        isinstance(raw_val, dict)
                        and _first_of(raw_val, PRODUCT_URL_KEYS)
                    )
                    or ""
                )

                extracted_any = True
                _add(title, product_id, price, detail_url)

            if extracted_any:
                if path not in diagnostic.known_paths_hit:
                    diagnostic.known_paths_hit.append(path)
            else:
                if path not in diagnostic.known_paths_empty:
                    diagnostic.known_paths_empty.append(path)

    # ── 第二层：补充扫描新位置；用稳定商品键去重 ──
    candidates, scanned = scan_candidates(node)
    diagnostic.scanned_nodes = scanned
    # 过滤通用占位标题，避免把「商品」这种占位当成真实商品
    candidates = [
        item for item in candidates if not _is_generic_anchor_title(item.title)
    ]
    diagnostic.scan_candidates = len(candidates)
    # 按分数降序，优先高置信候选；最多取 5 件避免把无关节点当商品
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True)[:5]:
        diagnostic.scan_matched_paths.append(candidate.path)
        _add(
            candidate.title, candidate.product_id, candidate.price, candidate.detail_url
        )

    diagnostic.extracted = len(products)
    if not products:
        if diagnostic.scan_candidates == 0:
            # 整棵树里没有"商品 ID + 标题"同时出现的节点，基本可以判定没挂商品
            diagnostic.note = "未发现商品相关字段（该视频很可能确实没有挂商品）"
        else:
            diagnostic.note = "有候选节点但未能取出有效商品名，平台字段结构可能已变化"
    return products, diagnostic


def collect_diagnostics_summary(diagnostics: list[ExtractionDiagnostic]) -> dict:
    """汇总一批视频的诊断，供日志与 JSON 输出使用。"""
    total = len(diagnostics)
    with_products = sum(1 for item in diagnostics if item.extracted > 0)
    hit_paths: dict[str, int] = {}
    for item in diagnostics:
        for path in item.known_paths_hit:
            hit_paths[path] = hit_paths.get(path, 0) + 1
    return {
        "videosScanned": total,
        "videosWithProducts": with_products,
        "videosWithoutProducts": total - with_products,
        "knownPathHits": hit_paths,
        "scanMatched": sum(len(item.scan_matched_paths) for item in diagnostics),
    }
