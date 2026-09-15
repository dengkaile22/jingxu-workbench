"""
Example 1: Using EcommerceCrawlerComponent as a Python SDK.
Minimal, elegant, 5-line integration into your Python scripts or pipelines.
"""
import os
import sys

# Ensure parent path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecommerce_spider import EcommerceCrawlerComponent


def main():
    print("=== [组件调用示例 1] EcommerceCrawlerComponent SDK 使用示范 ===")

    # 1. 实例化组件 (支持无头模式与自定义持久化目录)
    crawler = EcommerceCrawlerComponent(headless=True)

    # 2. 自定义添加对标账号 (支持抖音与快手，支持链式调用)
    crawler.add_account("douyin", "https://www.douyin.com/user/MS4wLjABAAAA_example_a", name="美妆达人A")
    crawler.add_account("douyin", "https://www.douyin.com/user/MS4wLjABAAAA_example_b", name="测评博主B")
    crawler.add_account("kuaishou", "https://www.kuaishou.com/profile/example_ks_c", name="老铁严选C")

    # 3. 自定义爬取时间 (如近 7 天)
    crawler.set_time_filter(days=7)

    # 4. 自定义相同商品出现次数去保留商品 (保留在 >= 2 个不同账号中出现的商品)
    crawler.set_retention_rule(
        min_account_count=2,       # 跨账号门槛
        min_total_occurrences=1,   # 视频频次门槛
        enable_fuzzy=True          # 智能去噪与同款包装相似款合并
    )

    print(f"[*] 组件配置完成：已配置 {len(crawler.accounts)} 个对标账号，时间跨度 {crawler.time_config.days} 天")
    print(f"[*] 保留规则：跨账号数 >= {crawler.filter_config.min_account_count}")

    # 5. 调用 run() 方法执行爬取与分析 (此步骤将启动浏览器执行)
    # retained_products, all_items = crawler.run(
    #     on_log=lambda msg: print(f"[LOG] {msg}"),
    #     on_progress=lambda cur, tot, stat: print(f"进度: {cur}/{tot} - {stat}")
    # )

    # 6. 一键导出 Excel 报表
    # crawler.export_excel("data/sdk_export.xlsx")
    print("[✓] SDK 组件集成测试通过！")


if __name__ == "__main__":
    main()
