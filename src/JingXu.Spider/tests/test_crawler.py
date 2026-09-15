"""
Unit tests for Douyin & Kuaishou crawler, text cleaner, and cross-account analyzer.
"""
import os
import unittest
from datetime import datetime, timedelta

from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig, VideoProductItem, RetainedProduct
from core.text_utils import clean_product_title, calculate_string_similarity, are_products_identical
from core.analyzer import ProductAnalyzer
from core.exporter import DataExporter
from core.douyin_crawler import resolve_douyin_url_or_secuid, extract_douyin_products_from_aweme
from core.kuaishou_crawler import resolve_kuaishou_url_or_userid, extract_kuaishou_products_from_photo


class TestCrawlerCore(unittest.TestCase):

    def test_text_cleaning(self):
        """Test noise removal from e-commerce product titles."""
        cases = [
            ("【官方正品 包邮】超能植翠洗衣液3kg 拍1发2", "超能植翠洗衣液3kg"),
            ("[爆款热销] 欧莱雅玻尿酸洗发水500ml 买一送一", "欧莱雅玻尿酸洗发水500ml"),
            ("（限时特惠）农夫山泉饮用水550ml*24瓶 顺丰包邮", "农夫山泉饮用水550ml*24瓶"),
            ("拍1件起 飞科电动剃须刀全身水洗FS372 假一赔十", "飞科电动剃须刀全身水洗FS372"),
            ("【买二送三】老北京足贴艾草养生贴", "老北京足贴艾草养生贴"),
        ]
        for raw, expected in cases:
            cleaned = clean_product_title(raw)
            self.assertEqual(cleaned, expected, f"Failed for {raw} -> got '{cleaned}'")

    def test_product_similarity(self):
        """Test similarity matching between slightly varied titles of the same product."""
        t1 = "超能植翠低泡洗衣液3kg"
        t2 = "超能植翠低泡洗衣液3kg瓶装家庭特惠"
        self.assertTrue(are_products_identical(t1, t2, threshold=0.75))

        t3 = "海飞丝去屑洗发水400ml"
        t4 = "清扬男士去屑洗发露400ml"
        self.assertFalse(are_products_identical(t3, t4, threshold=0.75))

    def test_time_filter_config(self):
        """Test timestamp calculation for time filter."""
        # Days mode
        cfg = TimeFilterConfig(mode="days", days=7)
        s_ts, e_ts = cfg.get_timestamps()
        self.assertIsNotNone(s_ts)
        self.assertIsNotNone(e_ts)
        diff_days = (e_ts - s_ts) / 86400
        self.assertAlmostEqual(diff_days, 7, delta=1)

        # Range mode
        cfg2 = TimeFilterConfig(mode="range", start_date="2026-03-01", end_date="2026-03-10")
        s_ts2, e_ts2 = cfg2.get_timestamps()
        self.assertIsNotNone(s_ts2)
        self.assertIsNotNone(e_ts2)
        self.assertTrue(s_ts2 < e_ts2)

        # All mode
        cfg3 = TimeFilterConfig(mode="all")
        s_ts3, e_ts3 = cfg3.get_timestamps()
        self.assertIsNone(s_ts3)
        self.assertIsNone(e_ts3)

    def test_cross_account_retention_filter(self):
        """
        Test the core requirement:
        Multiple accounts with identical products, filtered by custom threshold.
        """
        items = [
            # Product A appears in Account 1 and Account 2 (2 accounts -> should be retained if min_accounts=2)
            VideoProductItem("douyin", "账号A", "uid1", "v1", "视频1", "http://v1", 1700000000, "2026-03-01", "p1", "【官方正品】超能植翠洗衣液3kg", "", "¥39.9", "", ""),
            VideoProductItem("douyin", "账号B", "uid2", "v2", "视频2", "http://v2", 1700001000, "2026-03-02", "p1", "超能植翠洗衣液3kg瓶装", "", "¥38.9", "", ""),
            VideoProductItem("douyin", "账号B", "uid2", "v3", "视频3", "http://v3", 1700002000, "2026-03-03", "p1", "超能植翠洗衣液3kg促销装", "", "¥39.0", "", ""),

            # Product B appears only in Account B (1 account, 3 videos)
            VideoProductItem("douyin", "账号B", "uid2", "v4", "视频4", "http://v4", 1700003000, "2026-03-04", "p2", "独家定制高档保温杯", "", "¥99.0", "", ""),
            VideoProductItem("douyin", "账号B", "uid2", "v5", "视频5", "http://v5", 1700004000, "2026-03-05", "p2", "独家定制高档保温杯带茶漏", "", "¥99.0", "", ""),

            # Product C appears in Account C and Account A (2 accounts)
            VideoProductItem("kuaishou", "账号C", "uid3", "v6", "视频6", "http://v6", 1700005000, "2026-03-06", "p3", "水光盈润补水面膜20片", "", "¥29.9", "", ""),
            VideoProductItem("douyin", "账号A", "uid1", "v7", "视频7", "http://v7", 1700006000, "2026-03-07", "p3", "【买一送一】水光盈润补水面膜20片", "", "¥29.9", "", ""),
        ]

        # Scenario 1: min_account_count = 2 (Keep only products featured in >= 2 distinct accounts)
        cfg = OccurrenceFilterConfig(min_account_count=2, filter_by="accounts", enable_fuzzy_cluster=True)
        analyzer = ProductAnalyzer(cfg)
        retained, all_agg = analyzer.aggregate_and_filter(items)

        # Product A and Product C have 2 accounts -> retained. Product B has 1 account -> excluded.
        self.assertEqual(len(retained), 2)
        retained_names = [r.cleaned_name for r in retained]
        self.assertIn("超能植翠洗衣液3kg", retained_names)
        self.assertIn("水光盈润补水面膜20片", retained_names)
        self.assertNotIn("独家定制高档保温杯", retained_names)

        # Check account details
        p_a = next(r for r in retained if r.cleaned_name == "超能植翠洗衣液3kg")
        self.assertEqual(p_a.account_count, 2)
        self.assertEqual(set(p_a.accounts), {"账号A", "账号B"})
        self.assertEqual(p_a.video_count, 3)

        # Scenario 2: min_account_count = 3 (None should be retained since max account_count is 2)
        cfg_strict = OccurrenceFilterConfig(min_account_count=3, filter_by="accounts", enable_fuzzy_cluster=True)
        analyzer_strict = ProductAnalyzer(cfg_strict)
        retained_strict, _ = analyzer_strict.aggregate_and_filter(items)
        self.assertEqual(len(retained_strict), 0)

        # Scenario 3: total occurrences >= 3
        cfg_total = OccurrenceFilterConfig(min_total_occurrences=3, filter_by="total", enable_fuzzy_cluster=True)
        analyzer_total = ProductAnalyzer(cfg_total)
        retained_total, _ = analyzer_total.aggregate_and_filter(items)
        self.assertEqual(len(retained_total), 1)
        self.assertEqual(retained_total[0].cleaned_name, "超能植翠洗衣液3kg")

    def test_url_resolvers(self):
        """Test URL to ID resolution."""
        dy_url = "https://www.douyin.com/user/MS4wLjABAAAA12345678abcdef"
        self.assertEqual(resolve_douyin_url_or_secuid(dy_url), "MS4wLjABAAAA12345678abcdef")

        ks_url = "https://www.kuaishou.com/profile/3xabcdef12345"
        self.assertEqual(resolve_kuaishou_url_or_userid(ks_url), "3xabcdef12345")

    def test_douyin_aweme_parser(self):
        """Test Douyin aweme json parser."""
        mock_aweme = {
            "aweme_id": "71234567890",
            "desc": "今天推荐一款超级好用的洗衣液",
            "create_time": 1710000000,
            "author": {"nickname": "测试博主"},
            "anchor_info": {
                "type": 3,
                "title": "立白天然茶籽洗衣液",
                "name": "立白天然茶籽洗衣液",
                "extra": '{"title": "立白天然茶籽洗衣液5kg", "product_id": "999888", "price": 4990}'
            }
        }
        products = extract_douyin_products_from_aweme(mock_aweme, "测试博主", "sec123")
        self.assertEqual(len(products), 1)
        p = products[0]
        self.assertEqual(p.product_name, "立白天然茶籽洗衣液5kg")
        self.assertEqual(p.price, "¥49.90")
        self.assertEqual(p.video_id, "71234567890")

    def test_exporter(self):
        """Test exporting data to Excel."""
        rp = RetainedProduct(
            product_name="立白天然茶籽洗衣液5kg",
            cleaned_name="立白天然茶籽洗衣液5kg",
            platform="douyin",
            account_count=2,
            accounts=["账号1", "账号2"],
            video_count=3,
            items=[],
            price_range="¥49.90",
            sample_video_url="https://www.douyin.com/video/123"
        )
        it = VideoProductItem(
            platform="douyin",
            account_name="账号1",
            account_id="sec1",
            video_id="v1",
            video_title="好物分享",
            video_url="https://www.douyin.com/video/123",
            publish_time=1710000000,
            publish_time_str="2026-03-01 10:00:00",
            product_id="999888",
            product_name="立白天然茶籽洗衣液5kg",
            cleaned_name="立白天然茶籽洗衣液5kg",
            price="¥49.90",
            detail_url=""
        )
        test_file = "tests/test_export.xlsx"
        try:
            DataExporter.export_to_excel(test_file, [rp], [it])
            self.assertTrue(os.path.exists(test_file))
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)


if __name__ == "__main__":
    unittest.main()
