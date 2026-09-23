"""
Configuration loader and persister for crawler settings.
"""
import os
import json
from typing import List, Dict, Any
from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.json"
)

# Useful default accounts for instant testing
SAMPLE_ACCOUNTS = [
    {
        "platform": "douyin",
        "name": "交个朋友直播间",
        "url_or_id": "https://www.douyin.com/user/MS4wLjABAAAAw_06b_F43P6297l9YkU6S98sU7TfP-1Z_2W_8X7-3Y4",
        "enabled": True,
        "sec_uid": "",
        "user_id": "",
    },
    {
        "platform": "douyin",
        "name": "东方甄选",
        "url_or_id": "https://www.douyin.com/user/MS4wLjABAAAA4v-Z_WpT8P1-3X7sU8TfP-1Z_2W_8X7-3Y4",
        "enabled": True,
        "sec_uid": "",
        "user_id": "",
    },
    {
        "platform": "kuaishou",
        "name": "快手小店精选",
        "url_or_id": "https://www.kuaishou.com/profile/3x6df89v345",
        "enabled": False,
        "sec_uid": "",
        "user_id": "",
    }
]


class AppConfig:
    """Manages application settings, targets, and parameters."""

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.accounts: List[AccountTarget] = []
        self.time_config = TimeFilterConfig()
        self.filter_config = OccurrenceFilterConfig()
        self.headless: bool = False
        self.max_scrolls_per_account: int = 25
        self.export_dir: str = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data"
        )
        self.load()

    def load(self):
        """Load configuration from JSON file or initialize with defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)

                # Accounts
                raw_accounts = data.get("accounts", [])
                self.accounts = [AccountTarget.from_dict(acc) for acc in raw_accounts]

                # Time config
                t_data = data.get("time_config", {})
                self.time_config = TimeFilterConfig(
                    mode=t_data.get("mode", "days"),
                    days=t_data.get("days", 7),
                    start_date=t_data.get("start_date", ""),
                    end_date=t_data.get("end_date", ""),
                )

                # Occurrence filter config
                f_data = data.get("filter_config", {})
                self.filter_config = OccurrenceFilterConfig(
                    min_account_count=f_data.get("min_account_count", 2),
                    min_total_occurrences=f_data.get("min_total_occurrences", 1),
                    filter_by=f_data.get("filter_by", "accounts"),
                    enable_fuzzy_cluster=f_data.get("enable_fuzzy_cluster", True),
                    fuzzy_threshold=f_data.get("fuzzy_threshold", 0.75),
                )

                self.headless = data.get("headless", False)
                self.max_scrolls_per_account = data.get("max_scrolls_per_account", 25)
                self.export_dir = data.get("export_dir", self.export_dir)
                return
            except Exception as e:
                print(f"[配置] 加载配置文件失败: {e}")
                # 不静默回退到示例账号，避免在用户不知情的情况下爬取示例对标账号。
                self.accounts = []
                return

        # Defaults
        self.accounts = [AccountTarget.from_dict(acc) for acc in SAMPLE_ACCOUNTS]
        self.save()

    def save(self):
        """Save current configuration to JSON file."""
        data = {
            "accounts": [acc.to_dict() for acc in self.accounts],
            "time_config": {
                "mode": self.time_config.mode,
                "days": self.time_config.days,
                "start_date": self.time_config.start_date,
                "end_date": self.time_config.end_date,
            },
            "filter_config": {
                "min_account_count": self.filter_config.min_account_count,
                "min_total_occurrences": self.filter_config.min_total_occurrences,
                "filter_by": self.filter_config.filter_by,
                "enable_fuzzy_cluster": self.filter_config.enable_fuzzy_cluster,
                "fuzzy_threshold": self.filter_config.fuzzy_threshold,
            },
            "headless": self.headless,
            "max_scrolls_per_account": self.max_scrolls_per_account,
            "export_dir": self.export_dir,
        }
        try:
            config_dir = os.path.dirname(os.path.abspath(self.config_path))
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[配置] 保存配置失败: {e}")
