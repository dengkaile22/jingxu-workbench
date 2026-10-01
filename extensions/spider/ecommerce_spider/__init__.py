"""
Ecommerce Spider Component Library for Douyin & Kuaishou.
Provides high-level Python SDK, standalone product analyzer, and embeddable PySide6 UI widget.
"""
from core.models import (
    AccountTarget,
    TimeFilterConfig,
    OccurrenceFilterConfig,
    VideoProductItem,
    RetainedProduct,
)
from core.text_utils import (
    clean_product_title,
    calculate_string_similarity,
    are_products_identical,
    parse_chinese_count_str,
)
from core.exporter import DataExporter
from ecommerce_spider.analyzer_component import ProductAnalyzerComponent
from ecommerce_spider.component import EcommerceCrawlerComponent

# Optional UI widget export (available if PySide6 is installed)
try:
    from ecommerce_spider.widget import EcommerceCrawlerWidget
    __ui_available__ = True
except ImportError:
    EcommerceCrawlerWidget = None
    __ui_available__ = False

__version__ = "1.0.0"

__all__ = [
    # Main Components
    "EcommerceCrawlerComponent",
    "ProductAnalyzerComponent",
    "EcommerceCrawlerWidget",
    # Data Models
    "AccountTarget",
    "TimeFilterConfig",
    "OccurrenceFilterConfig",
    "VideoProductItem",
    "RetainedProduct",
    # Core Utilities
    "clean_product_title",
    "calculate_string_similarity",
    "are_products_identical",
    "parse_chinese_count_str",
    "DataExporter",
]
