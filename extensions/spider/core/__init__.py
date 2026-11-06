"""
Core module for Douyin & Kuaishou crawler and analyzer.
"""
from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig, VideoProductItem, RetainedProduct
from core.config import AppConfig
try:
    from core.browser_manager import BrowserManager
except ImportError:
    BrowserManager = None  # type: ignore[assignment, misc]

try:
    from core.douyin_crawler import DouyinCrawler
except ImportError:
    DouyinCrawler = None  # type: ignore[assignment, misc]

try:
    from core.kuaishou_crawler import KuaishouCrawler
except ImportError:
    KuaishouCrawler = None  # type: ignore[assignment, misc]

from core.analyzer import ProductAnalyzer
try:
    from core.exporter import DataExporter
except ImportError:
    DataExporter = None  # type: ignore[assignment, misc]

__all__ = [
    "AccountTarget",
    "TimeFilterConfig",
    "OccurrenceFilterConfig",
    "VideoProductItem",
    "RetainedProduct",
    "AppConfig",
    "BrowserManager",
    "DouyinCrawler",
    "KuaishouCrawler",
    "ProductAnalyzer",
    "DataExporter",
]
