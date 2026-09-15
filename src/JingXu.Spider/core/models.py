"""
Data models for Douyin & Kuaishou crawler and product analyzer.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class AccountTarget:
    """Target account for crawling."""
    platform: str            # 'douyin' or 'kuaishou'
    url_or_id: str           # User profile link, sec_uid, or user id
    name: str = ""           # User alias or nickname
    enabled: bool = True     # Whether to crawl this account
    sec_uid: str = ""        # For Douyin
    user_id: str = ""        # For Kuaishou
    status: str = "就绪"     # Current crawl status (就绪, 爬取中, 完成, 失败)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "url_or_id": self.url_or_id,
            "name": self.name,
            "enabled": self.enabled,
            "sec_uid": self.sec_uid,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountTarget":
        return cls(
            platform=data.get("platform", "douyin"),
            url_or_id=data.get("url_or_id", ""),
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            sec_uid=data.get("sec_uid", ""),
            user_id=data.get("user_id", ""),
        )


@dataclass
class TimeFilterConfig:
    """Time filter configuration for short videos."""
    mode: str = "days"       # 'days', 'range', 'all'
    days: int = 7            # Recent N days
    start_date: str = ""     # YYYY-MM-DD
    end_date: str = ""       # YYYY-MM-DD

    def get_timestamps(self) -> tuple[Optional[float], Optional[float]]:
        """Return (start_ts, end_ts) in seconds."""
        now = datetime.now()
        if self.mode == "all":
            return None, None
        elif self.mode == "days":
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            from datetime import timedelta
            start_dt = start_dt - timedelta(days=self.days)
            return start_dt.timestamp(), now.timestamp()
        elif self.mode == "range":
            start_ts = None
            end_ts = None
            if self.start_date:
                s_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
                start_ts = s_dt.timestamp()
            if self.end_date:
                e_dt = datetime.strptime(self.end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                end_ts = e_dt.timestamp()
            return start_ts, end_ts
        return None, None


@dataclass
class OccurrenceFilterConfig:
    """Retention filter threshold for identical products."""
    min_account_count: int = 2        # Must appear in at least N distinct target accounts (跨账号相同商品)
    min_total_occurrences: int = 1    # Must appear in at least M total videos
    filter_by: str = "accounts"       # 'accounts' (跨账号数), 'total' (总频次), 'both' (两者均满足)
    enable_fuzzy_cluster: bool = True # Merge slightly different titles of the same product
    fuzzy_threshold: float = 0.75     # Similarity threshold (0.0 ~ 1.0)


@dataclass
class VideoProductItem:
    """Single e-commerce product instance found in a video."""
    platform: str                    # 'douyin' or 'kuaishou'
    account_name: str                # Author/Account name
    account_id: str                  # Sec-uid or user_id
    video_id: str                    # Aweme ID or Photo ID
    video_title: str                 # Video title/description
    video_url: str                   # Video watch link
    publish_time: int                # Unix timestamp (seconds)
    publish_time_str: str            # YYYY-MM-DD HH:MM:SS
    product_id: str                  # Commodity ID
    product_name: str                # Raw product title
    cleaned_name: str = ""           # Cleaned product title without promo noise
    price: str = ""                  # Price string if available
    cover_url: str = ""              # Product image cover
    detail_url: str = ""             # Product e-commerce link

    def to_dict(self) -> Dict[str, Any]:
        return {
            "平台": self.platform,
            "账号名称": self.account_name,
            "账号ID": self.account_id,
            "视频ID": self.video_id,
            "视频标题": self.video_title,
            "视频链接": self.video_url,
            "发布时间": self.publish_time_str,
            "商品ID": self.product_id,
            "商品原始名称": self.product_name,
            "清洗后名称": self.cleaned_name,
            "售价": self.price,
            "商品链接": self.detail_url,
        }


@dataclass
class RetainedProduct:
    """Aggregated identical product across accounts."""
    product_name: str                                  # Representative product name
    cleaned_name: str                                  # Normalized product name
    platform: str                                      # 'douyin', 'kuaishou', or 'all'
    account_count: int = 0                             # Number of distinct accounts
    accounts: List[str] = field(default_factory=list)  # List of distinct account names
    video_count: int = 0                               # Total videos featuring this product
    items: List[VideoProductItem] = field(default_factory=list) # Raw items
    price_range: str = ""                              # e.g. "¥29.9 - ¥39.9"
    sample_video_url: str = ""                         # Link to one of the videos

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "商品名称": self.product_name,
            "清洗名称": self.cleaned_name,
            "涉及平台": self.platform,
            "带货账号数": self.account_count,
            "带货视频数": self.video_count,
            "对标账号明细": ", ".join(self.accounts),
            "参考价格": self.price_range,
            "示例视频链接": self.sample_video_url,
        }
