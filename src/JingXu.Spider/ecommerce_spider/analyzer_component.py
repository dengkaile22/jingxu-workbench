"""
Standalone Product Analyzer Component.
Can be used independently of crawlers to clean product titles,
cluster similar items, and retain identical products based on occurrence thresholds.
"""
from typing import List, Dict, Any, Union, Tuple, Optional
from datetime import datetime
import pandas as pd

from core.models import VideoProductItem, RetainedProduct, OccurrenceFilterConfig
from core.text_utils import clean_product_title, calculate_string_similarity, are_products_identical
from core.analyzer import ProductAnalyzer


class ProductAnalyzerComponent:
    """
    Independent component for e-commerce product title cleaning,
    clustering, and cross-account threshold retention analysis.
    """

    def __init__(
        self,
        min_account_count: int = 2,
        min_total_occurrences: int = 1,
        filter_by: str = "accounts",
        enable_fuzzy_cluster: bool = True,
        fuzzy_threshold: float = 0.75
    ):
        self.config = OccurrenceFilterConfig(
            min_account_count=min_account_count,
            min_total_occurrences=min_total_occurrences,
            filter_by=filter_by,
            enable_fuzzy_cluster=enable_fuzzy_cluster,
            fuzzy_threshold=fuzzy_threshold,
        )
        self._analyzer = ProductAnalyzer(self.config)

    def set_thresholds(
        self,
        min_account_count: Optional[int] = None,
        min_total_occurrences: Optional[int] = None,
        filter_by: Optional[str] = None,
        enable_fuzzy_cluster: Optional[bool] = None,
        fuzzy_threshold: Optional[float] = None
    ):
        """Update retention thresholds dynamically."""
        if min_account_count is not None:
            self.config.min_account_count = min_account_count
        if min_total_occurrences is not None:
            self.config.min_total_occurrences = min_total_occurrences
        if filter_by is not None:
            self.config.filter_by = filter_by
        if enable_fuzzy_cluster is not None:
            self.config.enable_fuzzy_cluster = enable_fuzzy_cluster
        if fuzzy_threshold is not None:
            self.config.fuzzy_threshold = fuzzy_threshold

        self._analyzer = ProductAnalyzer(self.config)

    @staticmethod
    def clean(title: str) -> str:
        """Strip promo words and normalize e-commerce product title."""
        return clean_product_title(title)

    @staticmethod
    def similarity(title1: str, title2: str) -> float:
        """Calculate similarity score (0.0 to 1.0) between two product titles."""
        return calculate_string_similarity(title1, title2)

    def analyze(
        self,
        items: List[Union[VideoProductItem, Dict[str, Any]]]
    ) -> Tuple[List[RetainedProduct], List[RetainedProduct]]:
        """
        Analyze a list of items and return:
          (retained_products, all_aggregated_products)
        Accepts either VideoProductItem objects or plain dicts.
        """
        standard_items: List[VideoProductItem] = []
        for it in items:
            if isinstance(it, VideoProductItem):
                standard_items.append(it)
            elif isinstance(it, dict):
                standard_items.append(VideoProductItem(
                    platform=it.get("platform") or it.get("平台") or "douyin",
                    account_name=it.get("account_name") or it.get("账号名称") or it.get("account") or "",
                    account_id=it.get("account_id") or it.get("账号ID") or "",
                    video_id=it.get("video_id") or it.get("视频ID") or "",
                    video_title=it.get("video_title") or it.get("视频标题") or "",
                    video_url=it.get("video_url") or it.get("视频链接") or "",
                    publish_time=it.get("publish_time") or 0,
                    publish_time_str=it.get("publish_time_str") or it.get("发布时间") or "",
                    product_id=it.get("product_id") or it.get("商品ID") or "",
                    product_name=it.get("product_name") or it.get("商品名称") or it.get("title") or "",
                    cleaned_name=it.get("cleaned_name") or it.get("清洗名称") or "",
                    price=str(it.get("price") or it.get("售价") or ""),
                    detail_url=it.get("detail_url") or it.get("商品链接") or "",
                ))

        return self._analyzer.aggregate_and_filter(standard_items)

    def filter_retained(
        self,
        items: List[Union[VideoProductItem, Dict[str, Any]]]
    ) -> List[RetainedProduct]:
        """Convenience method returning only the retained products."""
        retained, _ = self.analyze(items)
        return retained

    def to_dataframe(self, retained_products: List[RetainedProduct]) -> pd.DataFrame:
        """Convert retained products into a pandas DataFrame."""
        rows = [p.to_summary_dict() for p in retained_products]
        return pd.DataFrame(rows)
