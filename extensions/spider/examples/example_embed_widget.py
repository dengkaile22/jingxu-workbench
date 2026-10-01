"""
Example 3: Embedding EcommerceCrawlerWidget into an existing PySide6 application.
Demonstrates how any desktop app can integrate the crawler UI as a plug-and-play widget.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QLabel, QVBoxLayout, QWidget
from ecommerce_spider import EcommerceCrawlerWidget


class ParentBusinessApp(QMainWindow):
    """Example of an existing corporate/business software incorporating our crawler component."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("我的电商业务管理综合工作台 (集成爬虫组件示例)")
        self.resize(1280, 880)

        # Main tabs of the parent application
        tab_widget = QTabWidget()
        self.setCentralWidget(tab_widget)

        # Tab 1: Parent App's existing feature
        tab_home = QWidget()
        h_layout = QVBoxLayout(tab_home)
        h_layout.addWidget(QLabel("这里是您主系统的原有用例页面（如店铺后台、订单管理、ERP系统等）..."))
        tab_widget.addTab(tab_home, "🏠 主系统首页")

        # Tab 2: Plug in our EcommerceCrawlerWidget directly!
        # Seamlessly integrated as a child widget!
        self.crawler_component = EcommerceCrawlerWidget(parent=self)
        self.crawler_component.crawl_finished.connect(self.on_crawl_finished_callback)

        tab_widget.addTab(self.crawler_component, "🎬 短视频竞品对标与爆品保留 (组件集成)")

    def on_crawl_finished_callback(self, retained_products, all_items):
        """Parent system receives event callback when crawling finishes."""
        print(f"[主系统收到回调] 爬虫组件执行完毕！发现跨账号保留商品 {len(retained_products)} 款！")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ParentBusinessApp()
    window.show()
    sys.exit(app.exec())
