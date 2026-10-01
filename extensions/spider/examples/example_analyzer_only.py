"""
Example 2: Using ProductAnalyzerComponent standalone.
Demonstrates analyzing, cleaning, and filtering products without needing crawlers.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecommerce_spider import ProductAnalyzerComponent


def main():
    print("=== [组件调用示例 2] ProductAnalyzerComponent 独立分析组件使用 ===")

    # 1. 实例化分析组件，设定跨账号出现门槛 >= 2
    analyzer = ProductAnalyzerComponent(
        min_account_count=2,       # 至少在 2 个账号出现
        min_total_occurrences=1,   # 至少出现 1 次
        enable_fuzzy_cluster=True  # 启用智能去噪与同款归并
    )

    # 2. 模拟从外部数据源（如数据库、第三方接口、CSV）导入的原始带货记录
    raw_ecommerce_data = [
        {"platform": "douyin", "account_name": "达人张三", "product_name": "【官方正品 包邮】生姜防脱洗发水500ml 拍1发2", "price": "¥39.9", "video_id": "v1"},
        {"platform": "douyin", "account_name": "达人李四", "product_name": "生姜防脱洗发水500ml瓶装家庭特惠", "price": "¥38.8", "video_id": "v2"},
        {"platform": "kuaishou", "account_name": "快手王五", "product_name": "【爆款热销】生姜防脱洗发水500ml", "price": "¥39.0", "video_id": "v3"},
        {"platform": "douyin", "account_name": "达人张三", "product_name": "【买一送一】水光玻尿酸补水面膜20片", "price": "¥29.9", "video_id": "v4"},
        {"platform": "kuaishou", "account_name": "快手赵六", "product_name": "水光玻尿酸补水面膜20片盒装", "price": "¥29.9", "video_id": "v5"},
        {"platform": "douyin", "account_name": "达人张三", "product_name": "定制高档紫砂壶", "price": "¥299.0", "video_id": "v6"},
    ]

    # 3. 调用组件的 analyze() 方法进行聚合与保留筛选
    retained_products, all_products = analyzer.analyze(raw_ecommerce_data)

    print(f"\n[*] 原始记录数: {len(raw_ecommerce_data)} 条")
    print(f"[*] 满足门槛（跨账号数 >= 2）保留的共性爆品: {len(retained_products)} 款：\n")

    for idx, p in enumerate(retained_products, 1):
        print(f"  {idx}. 商品名称: {p.cleaned_name}")
        print(f"     涉及账号数: {p.account_count} 个 ({', '.join(p.accounts)})")
        print(f"     带货视频数: {p.video_count} 条 | 价格区间: {p.price_range}\n")

    # 4. 可随时转换为 pandas DataFrame 进行进一步分析
    df = analyzer.to_dataframe(retained_products)
    print("[*] 转换为 DataFrame 预览：")
    print(df[["商品名称", "涉及平台", "带货账号数", "带货视频数", "参考价格"]])


if __name__ == "__main__":
    main()
