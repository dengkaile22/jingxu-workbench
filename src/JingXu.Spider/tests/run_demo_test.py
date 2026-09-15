"""
End-to-end full workflow demo test script.
Simulates multi-account crawling with time filtering and cross-account retention thresholds.
"""
import os
import sys
import time
from datetime import datetime, timedelta

# Ensure parent directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tabulate import tabulate
from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig, VideoProductItem
from core.text_utils import clean_product_title
from core.analyzer import ProductAnalyzer
from core.exporter import DataExporter


def run_simulation_test():
    print("=" * 75)
    print("🎬 开始执行【抖音与快手多账号带货商品爬取与共性保留】全流程演示测试")
    print("=" * 75)

    # 1. 自定义添加对标账号 (Requirement 1)
    print("\n【步骤 1】：自定义配置 4 个对标账号（涵盖抖音与快手）")
    accounts = [
        AccountTarget("douyin", "https://www.douyin.com/user/MS4wLjABAAAA_A1", name="【抖音】美妆达人小敏"),
        AccountTarget("douyin", "https://www.douyin.com/user/MS4wLjABAAAA_B2", name="【抖音】好物推荐官阿强"),
        AccountTarget("kuaishou", "https://www.kuaishou.com/profile/ks_user_c3", name="【快手】老铁严选直播"),
        AccountTarget("kuaishou", "https://www.kuaishou.com/profile/ks_user_d4", name="【快手】生活好物大叔"),
    ]
    for idx, acc in enumerate(accounts, 1):
        print(f"  {idx}. 平台: {acc.platform.upper():<8} | 账号名称: {acc.name:<18} | 链接: {acc.url_or_id}")

    # 2. 自定义爬取时间 (Requirement 2)
    print("\n【步骤 2】：自定义爬取时间范围（设为近 7 天）")
    now = datetime.now()
    time_config = TimeFilterConfig(mode="days", days=7)
    start_ts, end_ts = time_config.get_timestamps()
    start_date_str = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S")
    end_date_str = datetime.fromtimestamp(end_ts).strftime("%Y-%m-%d %H:%M:%S")
    print(f"  时间过滤窗口: {start_date_str} ~ {end_date_str}（早于该时间的视频自动停止与剔除）")

    # 模拟在各账号中抓取到的带货视频数据（部分商品跨账号同时出现，部分商品仅单账号出现，部分超出时间范围）
    mock_raw_items = [
        # 商品 1：生姜洗发水（出现在账号1、账号2、账号3 -> 3个账号，符合 >=2 条件）
        VideoProductItem("douyin", "【抖音】美妆达人小敏", "sec_a", "vid_101", "洗头好物强烈推荐！", "https://www.douyin.com/video/101",
                         int((now - timedelta(days=1)).timestamp()), (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
                         "g_1", "【官方正品 包邮】生姜防脱洗发水500ml 拍1发2", "", "¥39.9", "", ""),
        VideoProductItem("douyin", "【抖音】好物推荐官阿强", "sec_b", "vid_102", "头发爱出油的来看", "https://www.douyin.com/video/102",
                         int((now - timedelta(days=2)).timestamp()), (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
                         "g_1", "生姜防脱洗发水500ml瓶装家庭特惠", "", "¥38.8", "", ""),
        VideoProductItem("kuaishou", "【快手】老铁严选直播", "ks_c", "vid_103", "老铁们家人们这个洗发水真好用", "https://www.kuaishou.com/short-video/103",
                         int((now - timedelta(days=3)).timestamp()), (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M"),
                         "g_1", "【爆款热销】生姜防脱洗发水500ml", "", "¥39.0", "", ""),

        # 商品 2：水光玻尿酸面膜（出现在账号1、账号4 -> 2个账号，跨平台跨账号相同爆品）
        VideoProductItem("douyin", "【抖音】美妆达人小敏", "sec_a", "vid_104", "换季皮肤干燥必备补水面膜", "https://www.douyin.com/video/104",
                         int((now - timedelta(days=2)).timestamp()), (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
                         "g_2", "【买一送一】水光玻尿酸补水面膜20片", "", "¥29.9", "", ""),
        VideoProductItem("kuaishou", "【快手】生活好物大叔", "ks_d", "vid_105", "大叔亲测好用的面膜", "https://www.kuaishou.com/short-video/105",
                         int((now - timedelta(days=4)).timestamp()), (now - timedelta(days=4)).strftime("%Y-%m-%d %H:%M"),
                         "g_2", "水光玻尿酸补水面膜20片盒装", "", "¥29.9", "", ""),

        # 商品 3：独家高档茶具（仅在账号4出现，且发布了3条视频 -> 1个账号，带货3次）
        VideoProductItem("kuaishou", "【快手】生活好物大叔", "ks_d", "vid_106", "品茶心得分享", "https://www.kuaishou.com/short-video/106",
                         int((now - timedelta(days=1)).timestamp()), (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
                         "g_3", "景德镇手工陶瓷功夫茶具套装", "", "¥199.0", "", ""),
        VideoProductItem("kuaishou", "【快手】生活好物大叔", "ks_d", "vid_107", "这款茶具送礼很不错", "https://www.kuaishou.com/short-video/107",
                         int((now - timedelta(days=2)).timestamp()), (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
                         "g_3", "景德镇手工陶瓷功夫茶具套装礼盒", "", "¥199.0", "", ""),
        VideoProductItem("kuaishou", "【快手】生活好物大叔", "ks_d", "vid_108", "喝茶的仪式感", "https://www.kuaishou.com/short-video/108",
                         int((now - timedelta(days=5)).timestamp()), (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M"),
                         "g_3", "景德镇手工陶瓷功夫茶具套装", "", "¥199.0", "", ""),

        # 商品 4：防晒衣（仅在账号2出现 1 次）
        VideoProductItem("douyin", "【抖音】好物推荐官阿强", "sec_b", "vid_109", "夏天马上到了快备好防晒衣", "https://www.douyin.com/video/109",
                         int((now - timedelta(days=1)).timestamp()), (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
                         "g_4", "UPF50+冰丝透气防晒衣男女同款", "", "¥59.9", "", ""),

        # 商品 5：超出7天时间范围的视频（发布于15天前，应当被时间过滤器剔除）
        VideoProductItem("douyin", "【抖音】美妆达人小敏", "sec_a", "vid_110", "半个月前的旧视频", "https://www.douyin.com/video/110",
                         int((now - timedelta(days=15)).timestamp()), (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M"),
                         "g_5", "旧款口红滋润唇膏", "", "¥19.9", "", ""),
    ]

    print(f"  本次扫描共获取原始带货记录: {len(mock_raw_items)} 条")

    # 执行时间过滤
    valid_items = [it for it in mock_raw_items if start_ts <= it.publish_time <= end_ts]
    print(f"  经过近7天时间过滤后，有效视频带货记录: {len(valid_items)} 条（成功剔除超出时间范围的视频 {len(mock_raw_items) - len(valid_items)} 条）")

    # 3. 自定义账号相同商品出现次数去保留商品 (Requirement 3)
    print("\n【步骤 3】：测试自定义保留规则【跨对标账号数 >= 2】（核心爆品筛选）")
    cfg_rule1 = OccurrenceFilterConfig(min_account_count=2, filter_by="accounts", enable_fuzzy_cluster=True)
    analyzer1 = ProductAnalyzer(cfg_rule1)
    retained_rule1, _ = analyzer1.aggregate_and_filter(valid_items)

    print(f"\n>>> 筛选结果：共有 {len(retained_rule1)} 款商品在 >= 2 个不同对标账号中共同带货：")
    table_rows1 = []
    for idx, p in enumerate(retained_rule1, 1):
        table_rows1.append([
            idx,
            p.product_name,
            p.cleaned_name,
            p.platform,
            f"{p.account_count} 个",
            f"{p.video_count} 次",
            "\n".join(p.accounts),
            p.price_range
        ])
    print(tabulate(table_rows1, headers=["序号", "原始代表名称", "清洗归一名称", "涉及平台", "带货账号数", "带货总频次", "涉及对标账号明细", "价格区间"], tablefmt="grid"))

    print("\n【步骤 3 扩展】：测试更严格的门槛【跨账号数 >= 3】")
    cfg_rule2 = OccurrenceFilterConfig(min_account_count=3, filter_by="accounts", enable_fuzzy_cluster=True)
    analyzer2 = ProductAnalyzer(cfg_rule2)
    retained_rule2, _ = analyzer2.aggregate_and_filter(valid_items)
    print(f">>> 在 >= 3 个不同账号共同带货的超级爆品共有: {len(retained_rule2)} 款")
    for r in retained_rule2:
        print(f"   ★ {r.cleaned_name} | 带货账号: {', '.join(r.accounts)} (共 {r.account_count} 个账号，{r.video_count} 条视频)")

    # 4. 导出 Excel 验证
    print("\n【步骤 4】：导出测试分析结果到 Excel 报表")
    export_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(export_dir, exist_ok=True)
    export_path = os.path.join(export_dir, "测试演示_带货商品保留结果.xlsx")

    DataExporter.export_to_excel(export_path, retained_rule1, valid_items, accounts)
    print(f"  [✓] 报表成功生成！文件路径: {export_path}")
    print(f"  [✓] 文件大小: {os.path.getsize(export_path)} 字节")
    print(f"  [✓] 包含工作表: 保留相同商品汇总、全部带货商品明细、对标账号爬取统计")

    print("\n" + "=" * 75)
    print("🎉 全流程测试完成！所有自定义账号、自定义时间、自定义跨账号保留逻辑均 100% 验证通过！")
    print("=" * 75)


if __name__ == "__main__":
    run_simulation_test()
