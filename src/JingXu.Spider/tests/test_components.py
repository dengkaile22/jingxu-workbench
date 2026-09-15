"""
Unit tests for the modular component API in ecommerce_spider.
"""
import unittest
from ecommerce_spider import (
    EcommerceCrawlerComponent,
    ProductAnalyzerComponent,
    clean_product_title,
    calculate_string_similarity,
)


class TestComponents(unittest.TestCase):

    def test_analyzer_component_direct_dict(self):
        """Test ProductAnalyzerComponent on raw dictionary data."""
        analyzer = ProductAnalyzerComponent(min_account_count=2, enable_fuzzy_cluster=True)
        raw_items = [
            {"platform": "douyin", "account_name": "A", "product_name": "【爆款】男士洗面奶100g", "price": "¥29.9"},
            {"platform": "kuaishou", "account_name": "B", "product_name": "男士洗面奶100g清爽控油", "price": "¥29.9"},
            {"platform": "douyin", "account_name": "A", "product_name": "独家定制剃须刀", "price": "¥99"},
        ]
        retained = analyzer.filter_retained(raw_items)
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].cleaned_name, "男士洗面奶100g")
        self.assertEqual(retained[0].account_count, 2)

    def test_crawler_component_fluent_api(self):
        """Test fluent builder API of EcommerceCrawlerComponent."""
        comp = EcommerceCrawlerComponent(headless=True)
        comp.add_account("douyin", "https://www.douyin.com/user/MS4wLjABAAAA_1", name="达人1")
        comp.add_account("kuaishou", "https://www.kuaishou.com/profile/2", name="达人2")
        comp.set_time_filter(days=15)
        comp.set_retention_rule(min_account_count=3, min_total_occurrences=2)

        self.assertEqual(len(comp.accounts), 2)
        self.assertEqual(comp.time_config.days, 15)
        self.assertEqual(comp.filter_config.min_account_count, 3)
        self.assertEqual(comp.filter_config.min_total_occurrences, 2)


if __name__ == "__main__":
    unittest.main()
