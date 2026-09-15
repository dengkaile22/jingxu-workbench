"""
Product aggregator, cross-account identical item detection, and threshold filtering.
"""
from typing import List, Dict, Tuple
from collections import defaultdict
import re
from core.models import VideoProductItem, RetainedProduct, OccurrenceFilterConfig
from core.text_utils import clean_product_title, are_products_identical, calculate_string_similarity


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


class ProductAnalyzer:
    """Analyzes crawled product items and identifies cross-account identical products."""

    def __init__(self, filter_config: OccurrenceFilterConfig):
        self.config = filter_config

    def group_products(self, items: List[VideoProductItem]) -> List[List[VideoProductItem]]:
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
            # Group strictly by cleaned_name
            groups_dict = defaultdict(list)
            for item in items:
                groups_dict[item.cleaned_name].append(item)
            return list(groups_dict.values())

        # Fuzzy clustering: incremental greedy clustering
        clusters: List[List[VideoProductItem]] = []
        cluster_reps: List[str] = []  # Representative cleaned names for each cluster

        for item in items:
            name = item.cleaned_name or item.product_name
            matched = False
            best_idx = -1
            best_sim = 0.0

            for idx, rep in enumerate(cluster_reps):
                sim = calculate_string_similarity(name, rep)
                if sim >= self.config.fuzzy_threshold and sim > best_sim:
                    best_sim = sim
                    best_idx = idx

            if best_idx >= 0:
                clusters[best_idx].append(item)
                # If current item's cleaned name is shorter/cleaner, update rep
                if len(name) < len(cluster_reps[best_idx]) and len(name) >= 4:
                    cluster_reps[best_idx] = name
            else:
                clusters.append([item])
                cluster_reps.append(name)

        return clusters

    def aggregate_and_filter(self, items: List[VideoProductItem]) -> Tuple[List[RetainedProduct], List[RetainedProduct]]:
        """
        Aggregate all items, apply threshold filter.
        Returns:
            (retained_products, all_aggregated_products)
        """
        clusters = self.group_products(items)
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
            accounts = list(dict.fromkeys(it.account_name for it in cluster if it.account_name))
            account_count = len(accounts)

            # Unique videos
            video_ids = list(dict.fromkeys(it.video_id for it in cluster if it.video_id))
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

            # Sample video URL
            sample_video_url = ""
            for it in cluster:
                if it.video_url:
                    sample_video_url = it.video_url
                    break

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
            )
            aggregated.append(retained)

        # Apply user retention criteria
        filtered: List[RetainedProduct] = []
        for p in aggregated:
            meets_account_req = p.account_count >= self.config.min_account_count
            meets_total_req = p.video_count >= self.config.min_total_occurrences

            if self.config.filter_by == "accounts":
                keep = meets_account_req
            elif self.config.filter_by == "total":
                keep = meets_total_req
            elif self.config.filter_by == "both":
                keep = meets_account_req and meets_total_req
            else:
                keep = meets_account_req

            if keep:
                filtered.append(p)

        # Sort: first by account_count descending, then video_count descending
        filtered.sort(key=lambda x: (x.account_count, x.video_count), reverse=True)
        aggregated.sort(key=lambda x: (x.account_count, x.video_count), reverse=True)

        return filtered, aggregated
