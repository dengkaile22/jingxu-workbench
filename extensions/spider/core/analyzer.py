"""
Product aggregator, cross-account identical item detection, and threshold filtering.
"""

from typing import List, Tuple, Optional
from collections import defaultdict
from datetime import datetime
import re
from core.models import VideoProductItem, RetainedProduct, OccurrenceFilterConfig
from core.text_utils import (
    clean_product_title,
    calculate_string_similarity,
    prepared_title,
)
from core.record_identity import deduplicate_items


def parse_price(price_str: str) -> float:
    """Extract numeric price from price string."""
    if not price_str:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)", price_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def _sample_video_date(item: Optional[VideoProductItem]) -> str:
    """Return the example video's local publication date as YYYY-MM-DD."""
    if item is None:
        return ""
    value = (item.publish_time_str or "").strip()
    if value:
        try:
            return (
                datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
            )
        except ValueError:
            # Some source payloads only provide a date, while others append a label.
            match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
            if match:
                return match.group(1)
    timestamp = item.publish_time
    if timestamp:
        seconds = timestamp / 1000 if timestamp > 100_000_000_000 else timestamp
        try:
            return datetime.fromtimestamp(seconds).date().isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return ""


class ProductAnalyzer:
    """Analyzes crawled product items and identifies cross-account identical products."""

    def __init__(self, filter_config: OccurrenceFilterConfig):
        self.config = filter_config

    def group_products(
        self, items: List[VideoProductItem]
    ) -> List[List[VideoProductItem]]:
        """
        Group items by product identity.
        If enable_fuzzy_cluster is False: exact cleaned_name grouping.
        If enable_fuzzy_cluster is True: fuzzy similarity clustering with centroid/greedy grouping.
        """
        if not items:
            return []

        # Ensure cleaned_name is populated
        for item in items:
            if not item.cleaned_name:
                item.cleaned_name = clean_product_title(item.product_name)

        if not self.config.enable_fuzzy_cluster:
            # Each platform has its own product pool and retention thresholds.
            groups_dict = defaultdict(list)
            for item in items:
                groups_dict[(item.platform, item.cleaned_name)].append(item)
            return list(groups_dict.values())

        # Fuzzy clustering: incremental greedy clustering
        clusters: List[List[VideoProductItem]] = []
        cluster_reps: List[str] = []  # Representative cleaned names for each cluster
        gram_index = defaultdict(lambda: defaultdict(set))
        empty_grams = defaultdict(set)
        platform_clusters = defaultdict(set)

        def update_index(platform, index, name, *, remove=False):
            _, grams = prepared_title(name)
            buckets = (
                [gram_index[platform][gram] for gram in grams]
                if grams
                else [empty_grams[platform]]
            )
            for bucket in buckets:
                bucket.discard(index) if remove else bucket.add(index)

        for item in items:
            name = item.cleaned_name or item.product_name
            best_idx = -1
            best_sim = 0.0

            _, grams = prepared_title(name)
            if self.config.fuzzy_threshold > 0.50005 and grams:
                candidates = set(empty_grams[item.platform])
                for gram in grams:
                    candidates.update(gram_index[item.platform].get(gram, ()))
            else:
                candidates = platform_clusters[item.platform]
            for idx in sorted(candidates):
                rep = cluster_reps[idx]
                sim = calculate_string_similarity(
                    name, rep, minimum=max(self.config.fuzzy_threshold, best_sim)
                )
                if sim >= self.config.fuzzy_threshold and sim > best_sim:
                    best_sim = sim
                    best_idx = idx

            if best_idx >= 0:
                clusters[best_idx].append(item)
                # If current item's cleaned name is shorter/cleaner, update rep
                if len(name) < len(cluster_reps[best_idx]) and len(name) >= 4:
                    update_index(
                        item.platform, best_idx, cluster_reps[best_idx], remove=True
                    )
                    cluster_reps[best_idx] = name
                    update_index(item.platform, best_idx, name)
            else:
                index = len(clusters)
                clusters.append([item])
                cluster_reps.append(name)
                platform_clusters[item.platform].add(index)
                update_index(item.platform, index, name)

        return clusters

    def aggregate_and_filter(
        self, items: List[VideoProductItem]
    ) -> Tuple[List[RetainedProduct], List[RetainedProduct]]:
        """
        Aggregate all items, apply threshold filter.
        Returns:
            (retained_products, all_aggregated_products)
        """
        clusters = self.group_products(deduplicate_items(items))
        aggregated: List[RetainedProduct] = []

        for cluster in clusters:
            if not cluster:
                continue

            # Pick best representative product name (most frequent or cleanest)
            name_counts = defaultdict(int)
            for it in cluster:
                name_counts[it.product_name] += 1
            best_raw_name = max(name_counts.items(), key=lambda x: x[1])[0]

            cleaned_name = cluster[0].cleaned_name or clean_product_title(best_raw_name)

            # Platforms
            platforms = list(set(it.platform for it in cluster))
            if len(platforms) > 1:
                platform_str = "跨平台(" + "+".join(platforms) + ")"
            elif platforms:
                platform_str = platforms[0]
            else:
                platform_str = "未知"

            # Unique accounts
            account_names = {}
            for it in cluster:
                identity = it.account_id or (
                    f"name:{it.account_name}" if it.account_name else ""
                )
                if identity:
                    account_names.setdefault(identity, it.account_name or it.account_id)
            accounts = list(account_names.values())
            account_count = len(account_names)

            # Unique videos
            video_ids = list(
                dict.fromkeys(it.video_id for it in cluster if it.video_id)
            )
            video_count = len(video_ids) if video_ids else len(cluster)

            # Prices
            prices = [parse_price(it.price) for it in cluster if it.price]
            prices = [p for p in prices if p > 0]
            if prices:
                min_p, max_p = min(prices), max(prices)
                if min_p == max_p:
                    price_range = f"¥{min_p:.2f}"
                else:
                    price_range = f"¥{min_p:.2f} - ¥{max_p:.2f}"
            else:
                price_range = "暂无"

            # Example link, likes, and date must all come from the same video.
            best_items = sorted(cluster, key=lambda it: it.like_count, reverse=True)
            sample_video = next((it for it in best_items if it.video_url), None)
            sample_video_url = sample_video.video_url if sample_video else ""
            sample_video_like_count = sample_video.like_count if sample_video else 0
            sample_video_date = _sample_video_date(sample_video)

            max_like_count = max((it.like_count for it in cluster), default=0)

            retained = RetainedProduct(
                product_name=best_raw_name,
                cleaned_name=cleaned_name,
                platform=platform_str,
                account_count=account_count,
                accounts=accounts,
                video_count=video_count,
                items=cluster,
                price_range=price_range,
                sample_video_url=sample_video_url,
                max_like_count=max_like_count,
                sample_video_like_count=sample_video_like_count,
                sample_video_date=sample_video_date,
            )
            aggregated.append(retained)

        # Apply user retention criteria
        filtered: List[RetainedProduct] = []
        min_likes = getattr(self.config, "min_like_count", 0)
        for p in aggregated:
            meets_account_req = p.account_count >= self.config.min_account_count
            meets_total_req = p.video_count >= self.config.min_total_occurrences
            meets_likes_req = p.max_like_count >= min_likes

            if self.config.filter_by == "accounts":
                keep = meets_account_req
            elif self.config.filter_by == "likes":
                keep = meets_likes_req
            elif self.config.filter_by == "total":
                keep = meets_total_req
            elif self.config.filter_by == "both":
                keep = meets_account_req and meets_total_req
            else:
                keep = meets_account_req

            if keep:
                filtered.append(p)

        # Sort by the selected filtering criterion first, then by the other two metrics.
        # Keep the workbook's visible metric order aligned with the chosen filter mode.
        sort_metrics = {
            "accounts": ("account_count", "video_count", "sample_video_like_count"),
            "total": ("video_count", "account_count", "sample_video_like_count"),
            "likes": ("sample_video_like_count", "account_count", "video_count"),
            # Both thresholds are required; account reach is the primary rank, then frequency.
            "both": ("account_count", "video_count", "sample_video_like_count"),
        }.get(
            self.config.filter_by,
            ("account_count", "video_count", "sample_video_like_count"),
        )

        def sort_products(products: List[RetainedProduct]) -> None:
            products.sort(
                key=lambda product: tuple(
                    getattr(product, metric) for metric in sort_metrics
                ),
                reverse=True,
            )

        sort_products(filtered)
        sort_products(aggregated)

        return filtered, aggregated
