"""
PySide6 Main Window for Douyin & Kuaishou e-commerce crawler and product analyzer.
"""
import os
import sys
from datetime import datetime, timedelta
from typing import List

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QCheckBox, QRadioButton,
    QButtonGroup, QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QTextEdit, QProgressBar, QFileDialog, QMessageBox,
    QDialog, QComboBox, QGroupBox, QSplitter, QFrame
)
from PySide6.QtCore import Qt, QDate, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices

from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig, VideoProductItem, RetainedProduct
from core.config import AppConfig
from core.browser_manager import BrowserManager
from core.analyzer import ProductAnalyzer
from core.exporter import DataExporter
from gui.worker import CrawlWorker


STYLE_SHEET = """
QMainWindow {
    background-color: #F4F6F9;
}
QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: bold;
    color: #1E293B;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    background-color: #FFFFFF;
    color: #2563EB;
}
QPushButton {
    background-color: #2563EB;
    color: white;
    font-weight: bold;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #1D4ED8;
}
QPushButton:pressed {
    background-color: #1E40AF;
}
QPushButton:disabled {
    background-color: #94A3B8;
}
QPushButton#btn_start {
    background-color: #16A34A;
    font-size: 14px;
    min-height: 32px;
}
QPushButton#btn_start:hover {
    background-color: #15803D;
}
QPushButton#btn_stop {
    background-color: #DC2626;
    font-size: 14px;
    min-height: 32px;
}
QPushButton#btn_stop:hover {
    background-color: #B91C1C;
}
QPushButton#btn_export {
    background-color: #0284C7;
    font-size: 13px;
    min-height: 30px;
}
QPushButton#btn_export:hover {
    background-color: #0369A1;
}
QPushButton#btn_login {
    background-color: #F1F5F9;
    color: #334155;
    border: 1px solid #CBD5E1;
}
QPushButton#btn_login:hover {
    background-color: #E2E8F0;
    color: #0F172A;
}
QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    gridline-color: #F1F5F9;
    selection-background-color: #DBEAFE;
    selection-color: #1E3A8A;
}
QHeaderView::section {
    background-color: #F8FAFC;
    color: #475569;
    font-weight: bold;
    border: none;
    border-bottom: 1px solid #E2E8F0;
    padding: 6px;
}
QLineEdit, QSpinBox, QDateEdit, QComboBox {
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 4px 8px;
    background: #FFFFFF;
    color: #1E293B;
}
QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus {
    border: 1px solid #2563EB;
}
QTabWidget::pane {
    border: 1px solid #E2E8F0;
    background: #FFFFFF;
    border-radius: 6px;
}
QTabBar::tab {
    background: #E2E8F0;
    color: #475569;
    padding: 8px 18px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 3px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #2563EB;
    border-bottom: 2px solid #2563EB;
}
QProgressBar {
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    text-align: center;
    background: #E2E8F0;
    color: #1E293B;
    font-weight: bold;
}
QProgressBar::chunk {
    background-color: #2563EB;
    border-radius: 5px;
}
"""


class AddAccountDialog(QDialog):
    """Dialog to manually add a single target account."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加对标账号")
        self.resize(480, 240)
        layout = QVBoxLayout(self)

        form_layout = QGridLayout()

        form_layout.addWidget(QLabel("平台:"), 0, 0)
        self.combo_platform = QComboBox()
        self.combo_platform.addItems(["抖音 (douyin)", "快手 (kuaishou)"])
        form_layout.addWidget(self.combo_platform, 0, 1)

        form_layout.addWidget(QLabel("账号昵称/备注:"), 1, 0)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("选填，留空将自动从主页抓取")
        form_layout.addWidget(self.edit_name, 1, 1)

        form_layout.addWidget(QLabel("主页链接或ID:"), 2, 0)
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("如 https://www.douyin.com/user/... 或分享短链")
        form_layout.addWidget(self.edit_url, 2, 1)

        layout.addLayout(form_layout)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_ok = QPushButton("确认添加")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: #94A3B8;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_ok)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def get_account(self) -> AccountTarget:
        platform_idx = self.combo_platform.currentIndex()
        platform = "douyin" if platform_idx == 0 else "kuaishou"
        name = self.edit_name.text().strip()
        url = self.edit_url.text().strip()
        return AccountTarget(platform=platform, url_or_id=url, name=name, enabled=True)


class BatchImportDialog(QDialog):
    """Dialog to paste multiple URLs for batch account import."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量粘贴导入账号")
        self.resize(550, 350)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("每行一个账号主页链接（支持抖音与快手主页短链或完整链接，自动识别）："))
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "https://www.douyin.com/user/MS4wLjABAAAA...\n"
            "https://v.douyin.com/xxxxxx/\n"
            "https://www.kuaishou.com/profile/xxxx\n"
            "..."
        )
        layout.addWidget(self.text_edit)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_ok = QPushButton("批量导入")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: #94A3B8;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_ok)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def get_accounts(self) -> List[AccountTarget]:
        lines = self.text_edit.toPlainText().strip().split("\n")
        accounts = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if "kuaishou" in line:
                platform = "kuaishou"
            else:
                platform = "douyin"
            accounts.append(AccountTarget(platform=platform, url_or_id=line, name="", enabled=True))
        return accounts


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎬 抖音 & 快手多账号短视频带货商品爬取分析系统")
        self.resize(1200, 850)
        self.setStyleSheet(STYLE_SHEET)

        self.config = AppConfig()
        self.worker: CrawlWorker = None
        self.crawled_items: List[VideoProductItem] = []
        self.retained_products: List[RetainedProduct] = []

        self.init_ui()
        self.load_config_to_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 12, 15, 15)
        main_layout.setSpacing(10)

        # Header area
        header_layout = QHBoxLayout()
        title_label = QLabel("🎬 抖音 & 快手多账号短视频带货商品爬取与共性保留分析")
        title_label.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))
        title_label.setStyleSheet("color: #0F172A;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        btn_login_douyin = QPushButton("🌐 登录抖音(保存Cookie)")
        btn_login_douyin.setObjectName("btn_login")
        btn_login_douyin.clicked.connect(lambda: self.open_login_browser("douyin"))
        header_layout.addWidget(btn_login_douyin)

        btn_login_ks = QPushButton("⚡ 登录快手(保存Cookie)")
        btn_login_ks.setObjectName("btn_login")
        btn_login_ks.clicked.connect(lambda: self.open_login_browser("kuaishou"))
        header_layout.addWidget(btn_login_ks)

        main_layout.addLayout(header_layout)

        # Splitter: Upper Configuration, Lower Results
        splitter = QSplitter(Qt.Vertical)

        # Top Container (Config cards)
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        # 1. Account Target Group (Left side, takes 55% width)
        group_accounts = QGroupBox("1. 🎯 对标账号配置")
        acc_layout = QVBoxLayout(group_accounts)

        # Table
        self.table_accounts = QTableWidget()
        self.table_accounts.setColumnCount(5)
        self.table_accounts.setHorizontalHeaderLabels(["启用", "平台", "账号名称/备注", "主页链接 / ID", "状态"])
        self.table_accounts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_accounts.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_accounts.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table_accounts.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_accounts.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        acc_layout.addWidget(self.table_accounts)

        # Account buttons
        acc_btn_layout = QHBoxLayout()
        btn_add_acc = QPushButton("➕ 添加账号")
        btn_add_acc.clicked.connect(self.add_account_dialog)
        btn_batch_acc = QPushButton("📋 批量导入")
        btn_batch_acc.clicked.connect(self.batch_import_dialog)
        btn_del_acc = QPushButton("🗑️ 删除选中")
        btn_del_acc.setStyleSheet("background-color: #EF4444;")
        btn_del_acc.clicked.connect(self.delete_selected_account)
        btn_clear_acc = QPushButton("🧹 清空")
        btn_clear_acc.setStyleSheet("background-color: #64748B;")
        btn_clear_acc.clicked.connect(self.clear_all_accounts)

        acc_btn_layout.addWidget(btn_add_acc)
        acc_btn_layout.addWidget(btn_batch_acc)
        acc_btn_layout.addWidget(btn_del_acc)
        acc_btn_layout.addWidget(btn_clear_acc)
        acc_layout.addLayout(acc_btn_layout)

        top_layout.addWidget(group_accounts, stretch=6)

        # Right side: Time and Occurrence settings
        right_config_layout = QVBoxLayout()
        right_config_layout.setSpacing(10)

        # 2. Time Filter Group
        group_time = QGroupBox("2. ⏱️ 自定义爬取时间范围")
        time_layout = QVBoxLayout(group_time)

        self.time_bg = QButtonGroup(self)
        self.rb_3d = QRadioButton("近 3 天")
        self.rb_7d = QRadioButton("近 7 天")
        self.rb_15d = QRadioButton("近 15 天")
        self.rb_30d = QRadioButton("近 30 天")
        self.rb_custom = QRadioButton("自定义日期")
        self.rb_all = QRadioButton("全部历史")

        self.time_bg.addButton(self.rb_3d, 3)
        self.time_bg.addButton(self.rb_7d, 7)
        self.time_bg.addButton(self.rb_15d, 15)
        self.time_bg.addButton(self.rb_30d, 30)
        self.time_bg.addButton(self.rb_custom, 0)
        self.time_bg.addButton(self.rb_all, -1)
        self.time_bg.buttonClicked.connect(self.on_time_radio_changed)

        time_radio_layout = QHBoxLayout()
        time_radio_layout.addWidget(self.rb_3d)
        time_radio_layout.addWidget(self.rb_7d)
        time_radio_layout.addWidget(self.rb_15d)
        time_radio_layout.addWidget(self.rb_30d)
        time_radio_layout.addWidget(self.rb_custom)
        time_radio_layout.addWidget(self.rb_all)
        time_layout.addLayout(time_radio_layout)

        # Date Pickers
        date_picker_layout = QHBoxLayout()
        date_picker_layout.addWidget(QLabel("起始日期:"))
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        date_picker_layout.addWidget(self.date_start)

        date_picker_layout.addWidget(QLabel("结束日期:"))
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        date_picker_layout.addWidget(self.date_end)

        time_layout.addLayout(date_picker_layout)
        right_config_layout.addWidget(group_time)

        # 3. Product Occurrence Filter Group (Requirement 3)
        group_filter = QGroupBox("3. 🔍 相同商品保留规则 (核心需求)")
        filter_layout = QVBoxLayout(group_filter)

        f_row1 = QHBoxLayout()
        f_row1.addWidget(QLabel("跨账号门槛 (保留出现在 >= 个不同对标账号的商品):"))
        self.spin_min_accounts = QSpinBox()
        self.spin_min_accounts.setRange(1, 100)
        self.spin_min_accounts.setValue(2)
        f_row1.addWidget(self.spin_min_accounts)
        filter_layout.addLayout(f_row1)

        f_row2 = QHBoxLayout()
        f_row2.addWidget(QLabel("总频次门槛 (视频累计带货次数 >= 次):"))
        self.spin_min_total = QSpinBox()
        self.spin_min_total.setRange(1, 1000)
        self.spin_min_total.setValue(1)
        f_row2.addWidget(self.spin_min_total)
        filter_layout.addLayout(f_row2)

        f_row3 = QHBoxLayout()
        f_row3.addWidget(QLabel("判定准则:"))
        self.combo_filter_mode = QComboBox()
        self.combo_filter_mode.addItems(["仅按跨账号数过滤 (只要跨账号>=N即保留)", "仅按总带货频次过滤", "两者均需满足 (跨账号>=N 且 频次>=M)"])
        f_row3.addWidget(self.combo_filter_mode)
        filter_layout.addLayout(f_row3)

        f_row4 = QHBoxLayout()
        self.cb_fuzzy = QCheckBox("启用智能去噪与相似款归并 (自动去除营销干扰词/合并同款不同包装)")
        self.cb_fuzzy.setChecked(True)
        f_row4.addWidget(self.cb_fuzzy)

        self.cb_headless = QCheckBox("后台静默运行 (无头模式)")
        self.cb_headless.setChecked(False)
        f_row4.addWidget(self.cb_headless)
        filter_layout.addLayout(f_row4)

        right_config_layout.addWidget(group_filter)

        top_layout.addLayout(right_config_layout, stretch=5)
        splitter.addWidget(top_widget)

        # Action bar
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 4, 0, 4)

        self.btn_start = QPushButton("🚀 开始爬取与分析")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_crawl)
        action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹️ 终止任务")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_crawl)
        action_layout.addWidget(self.btn_stop)

        self.btn_re_filter = QPushButton("🔄 重新按新阈值筛选")
        self.btn_re_filter.setStyleSheet("background-color: #4F46E5; min-height: 30px;")
        self.btn_re_filter.setToolTip("修改保留规则后无需重新爬取，直接一键对当前抓取的数据重新过滤！")
        self.btn_re_filter.clicked.connect(self.re_filter_current_data)
        action_layout.addWidget(self.btn_re_filter)

        self.btn_export = QPushButton("📊 导出 Excel 结果")
        self.btn_export.setObjectName("btn_export")
        self.btn_export.clicked.connect(self.export_to_excel)
        action_layout.addWidget(self.btn_export)

        main_layout.addWidget(action_widget)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("空闲就绪")
        main_layout.addWidget(self.progress_bar)

        # Bottom Results Tabs
        self.tab_widget = QTabWidget()

        # Tab 1: Retained identical products (The Core Requirement)
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)

        # Filter search box
        search_box = QHBoxLayout()
        search_box.addWidget(QLabel("🔍 快速检索保留商品:"))
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("输入商品关键词实时筛选...")
        self.edit_search.textChanged.connect(self.filter_retained_table)
        search_box.addWidget(self.edit_search)
        self.label_retained_count = QLabel("保留相同商品: 0 款")
        self.label_retained_count.setStyleSheet("font-weight: bold; color: #16A34A;")
        search_box.addWidget(self.label_retained_count)
        tab1_layout.addLayout(search_box)

        self.table_retained = QTableWidget()
        self.table_retained.setColumnCount(8)
        self.table_retained.setHorizontalHeaderLabels([
            "序号", "商品名称", "清洗后名称", "平台", "共同带货账号数", "带货视频总数", "涉及对标账号明细", "参考价格"
        ])
        self.table_retained.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_retained.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_retained.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table_retained.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_retained.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_retained.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_retained.horizontalHeader().setSectionResizeMode(6, QHeaderView.Interactive)
        self.table_retained.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table_retained.cellDoubleClicked.connect(self.on_retained_cell_double_clicked)
        tab1_layout.addWidget(self.table_retained)

        self.tab_widget.addTab(tab1, "🏆 保留相同商品汇总")

        # Tab 2: All items detail
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        self.table_all = QTableWidget()
        self.table_all.setColumnCount(8)
        self.table_all.setHorizontalHeaderLabels([
            "序号", "平台", "账号名称", "视频标题", "发布时间", "原始商品名称", "售价", "视频链接"
        ])
        self.table_all.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_all.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_all.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table_all.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_all.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_all.horizontalHeader().setSectionResizeMode(5, QHeaderView.Interactive)
        self.table_all.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table_all.horizontalHeader().setSectionResizeMode(7, QHeaderView.Interactive)
        self.table_all.cellDoubleClicked.connect(self.on_all_cell_double_clicked)
        tab2_layout.addWidget(self.table_all)
        self.tab_widget.addTab(tab2, "📦 全部带货商品明细流水")

        # Tab 3: Logs
        tab3 = QWidget()
        tab3_layout = QVBoxLayout(tab3)
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setStyleSheet("background-color: #0F172A; color: #38BDF8; font-family: Consolas, monospace;")
        tab3_layout.addWidget(self.text_log)
        self.tab_widget.addTab(tab3, "📝 实时运行日志")

        splitter.addWidget(self.tab_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        main_layout.addWidget(splitter)

    def load_config_to_ui(self):
        """Populate UI from AppConfig."""
        # Populate accounts
        self.refresh_accounts_table()

        # Populate time
        mode = self.config.time_config.mode
        days = self.config.time_config.days
        if mode == "days":
            if days == 3:
                self.rb_3d.setChecked(True)
            elif days == 7:
                self.rb_7d.setChecked(True)
            elif days == 15:
                self.rb_15d.setChecked(True)
            elif days == 30:
                self.rb_30d.setChecked(True)
            else:
                self.rb_7d.setChecked(True)
            self.on_time_radio_changed(self.time_bg.checkedButton())
        elif mode == "all":
            self.rb_all.setChecked(True)
            self.on_time_radio_changed(self.rb_all)
        else:
            self.rb_custom.setChecked(True)
            if self.config.time_config.start_date:
                self.date_start.setDate(QDate.fromString(self.config.time_config.start_date, "yyyy-MM-dd"))
            if self.config.time_config.end_date:
                self.date_end.setDate(QDate.fromString(self.config.time_config.end_date, "yyyy-MM-dd"))

        # Occurrence filter
        self.spin_min_accounts.setValue(self.config.filter_config.min_account_count)
        self.spin_min_total.setValue(self.config.filter_config.min_total_occurrences)
        mode_idx = 0
        if self.config.filter_config.filter_by == "total":
            mode_idx = 1
        elif self.config.filter_config.filter_by == "both":
            mode_idx = 2
        self.combo_filter_mode.setCurrentIndex(mode_idx)

        self.cb_fuzzy.setChecked(self.config.filter_config.enable_fuzzy_cluster)
        self.cb_headless.setChecked(self.config.headless)

    def refresh_accounts_table(self):
        """Update accounts QTableWidget."""
        self.table_accounts.setRowCount(0)
        for row_idx, acc in enumerate(self.config.accounts):
            self.table_accounts.insertRow(row_idx)

            # Checkbox
            cb_item = QTableWidgetItem()
            cb_item.setCheckState(Qt.Checked if acc.enabled else Qt.Unchecked)
            self.table_accounts.setItem(row_idx, 0, cb_item)

            # Platform
            plat_text = "抖音" if acc.platform == "douyin" else "快手"
            plat_item = QTableWidgetItem(plat_text)
            plat_item.setTextAlignment(Qt.AlignCenter)
            if acc.platform == "douyin":
                plat_item.setForeground(QColor("#BE185D"))
            else:
                plat_item.setForeground(QColor("#EA580C"))
            self.table_accounts.setItem(row_idx, 1, plat_item)

            # Name
            self.table_accounts.setItem(row_idx, 2, QTableWidgetItem(acc.name))

            # URL/ID
            self.table_accounts.setItem(row_idx, 3, QTableWidgetItem(acc.url_or_id))

            # Status
            status_item = QTableWidgetItem(acc.status)
            status_item.setTextAlignment(Qt.AlignCenter)
            self.table_accounts.setItem(row_idx, 4, status_item)

    def on_time_radio_changed(self, button):
        """Handle time preset selection."""
        now = datetime.now()
        bid = self.time_bg.id(button)
        if bid > 0:
            start = now - timedelta(days=bid)
            self.date_start.setDate(QDate(start.year, start.month, start.day))
            self.date_end.setDate(QDate(now.year, now.month, now.day))
            self.date_start.setEnabled(False)
            self.date_end.setEnabled(False)
        elif bid == 0:  # Custom
            self.date_start.setEnabled(True)
            self.date_end.setEnabled(True)
        elif bid == -1:  # All
            self.date_start.setDate(QDate(2020, 1, 1))
            self.date_end.setDate(QDate(now.year, now.month, now.day))
            self.date_start.setEnabled(False)
            self.date_end.setEnabled(False)

    def sync_ui_to_config(self):
        """Sync user input back to AppConfig."""
        # Read table accounts
        for row in range(self.table_accounts.rowCount()):
            cb_item = self.table_accounts.item(row, 0)
            if cb_item and row < len(self.config.accounts):
                self.config.accounts[row].enabled = (cb_item.checkState() == Qt.Checked)
                name_item = self.table_accounts.item(row, 2)
                url_item = self.table_accounts.item(row, 3)
                if name_item:
                    self.config.accounts[row].name = name_item.text().strip()
                if url_item:
                    self.config.accounts[row].url_or_id = url_item.text().strip()

        # Time
        bid = self.time_bg.checkedId()
        if bid > 0:
            self.config.time_config.mode = "days"
            self.config.time_config.days = bid
        elif bid == -1:
            self.config.time_config.mode = "all"
        else:
            self.config.time_config.mode = "range"
            self.config.time_config.start_date = self.date_start.date().toString("yyyy-MM-dd")
            self.config.time_config.end_date = self.date_end.date().toString("yyyy-MM-dd")

        # Filter config
        self.config.filter_config.min_account_count = self.spin_min_accounts.value()
        self.config.filter_config.min_total_occurrences = self.spin_min_total.value()
        mode_idx = self.combo_filter_mode.currentIndex()
        if mode_idx == 0:
            self.config.filter_config.filter_by = "accounts"
        elif mode_idx == 1:
            self.config.filter_config.filter_by = "total"
        else:
            self.config.filter_config.filter_by = "both"

        self.config.filter_config.enable_fuzzy_cluster = self.cb_fuzzy.isChecked()
        self.config.headless = self.cb_headless.isChecked()

        self.config.save()

    def add_account_dialog(self):
        dialog = AddAccountDialog(self)
        if dialog.exec() == QDialog.Accepted:
            acc = dialog.get_account()
            if acc.url_or_id:
                self.config.accounts.append(acc)
                self.config.save()
                self.refresh_accounts_table()

    def batch_import_dialog(self):
        dialog = BatchImportDialog(self)
        if dialog.exec() == QDialog.Accepted:
            accs = dialog.get_accounts()
            if accs:
                self.config.accounts.extend(accs)
                self.config.save()
                self.refresh_accounts_table()
                QMessageBox.information(self, "导入成功", f"已成功导入 {len(accs)} 个账号！")

    def delete_selected_account(self):
        cur_row = self.table_accounts.currentRow()
        if cur_row >= 0 and cur_row < len(self.config.accounts):
            del self.config.accounts[cur_row]
            self.config.save()
            self.refresh_accounts_table()

    def clear_all_accounts(self):
        reply = QMessageBox.question(self, "确认清空", "确定要清空列表中的所有对标账号吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.config.accounts.clear()
            self.config.save()
            self.refresh_accounts_table()

    def open_login_browser(self, platform: str):
        """Open persistent browser profile for user to scan login QR code."""
        bm = BrowserManager(headless=False)
        msg = bm.open_login_window(platform)
        self.append_log(f"[登录管理] {msg}")
        QMessageBox.information(
            self,
            f"{platform.upper()} 登录管理",
            f"已启动浏览器窗口打开 {platform} 官网。\n请在弹出的浏览器中完成扫码登录，登录状态会自动持久保存在本地，之后爬虫直接复用登录态！"
        )

    def append_log(self, text: str):
        self.text_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

    def start_crawl(self):
        self.sync_ui_to_config()

        enabled_accounts = [acc for acc in self.config.accounts if acc.enabled]
        if not enabled_accounts:
            QMessageBox.warning(self, "提示", "请先在列表中勾选至少一个启用的对标账号！")
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("正在初始化爬虫引擎...")

        self.crawled_items.clear()
        self.retained_products.clear()
        self.table_retained.setRowCount(0)
        self.table_all.setRowCount(0)

        self.worker = CrawlWorker(
            accounts=self.config.accounts,
            time_config=self.config.time_config,
            filter_config=self.config.filter_config,
            headless=self.config.headless,
            max_scrolls=self.config.max_scrolls_per_account
        )

        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(self.on_worker_progress)
        self.worker.account_status_signal.connect(self.on_account_status)
        self.worker.product_found_signal.connect(self.on_product_found)
        self.worker.finished_signal.connect(self.on_crawl_finished)
        self.worker.error_signal.connect(self.on_crawl_error)

        self.worker.start()

    def stop_crawl(self):
        if self.worker:
            self.worker.stop()
            self.btn_stop.setEnabled(False)
            self.append_log("[系统] 用户点击了终止按钮，正在安全退出...")

    def on_worker_progress(self, current: int, total: int, status: str):
        if total > 0:
            val = int((current / total) * 100)
            self.progress_bar.setValue(val)
        self.progress_bar.setFormat(f"{status} ({current}/{total})")

    def on_account_status(self, account_index: int, status: str):
        if account_index < self.table_accounts.rowCount():
            item = self.table_accounts.item(account_index, 4)
            if item:
                item.setText(status)

    def on_product_found(self, item: VideoProductItem):
        """Add to all products table in real time."""
        row = self.table_all.rowCount()
        self.table_all.insertRow(row)
        self.table_all.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table_all.setItem(row, 1, QTableWidgetItem(item.platform))
        self.table_all.setItem(row, 2, QTableWidgetItem(item.account_name))
        self.table_all.setItem(row, 3, QTableWidgetItem(item.video_title))
        self.table_all.setItem(row, 4, QTableWidgetItem(item.publish_time_str))
        self.table_all.setItem(row, 5, QTableWidgetItem(item.product_name))
        self.table_all.setItem(row, 6, QTableWidgetItem(item.price))
        self.table_all.setItem(row, 7, QTableWidgetItem(item.video_url))

    def on_crawl_finished(self, retained: List[RetainedProduct], all_items: List[VideoProductItem]):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("爬取与分析完成！")

        self.retained_products = retained
        self.crawled_items = all_items

        self.populate_retained_table(retained)
        self.tab_widget.setCurrentIndex(0)

        QMessageBox.information(
            self,
            "分析完成",
            f"爬取与共性筛选完成！\n"
            f"共扫描带货商品记录: {len(all_items)} 条\n"
            f"筛选出跨账号共同带货商品: {len(retained)} 款！\n"
            f"可在主界面查看或一键导出为 Excel 报表。"
        )

    def on_crawl_error(self, err: str):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setFormat("爬取出错")
        QMessageBox.critical(self, "运行出错", f"爬虫遇到异常: {err}")

    def populate_retained_table(self, retained: List[RetainedProduct]):
        """Render retained items to table."""
        self.table_retained.setRowCount(0)
        self.label_retained_count.setText(f"保留相同商品: {len(retained)} 款")

        for row_idx, p in enumerate(retained):
            self.table_retained.insertRow(row_idx)
            self.table_retained.setItem(row_idx, 0, QTableWidgetItem(str(row_idx + 1)))
            self.table_retained.setItem(row_idx, 1, QTableWidgetItem(p.product_name))
            self.table_retained.setItem(row_idx, 2, QTableWidgetItem(p.cleaned_name))

            plat_item = QTableWidgetItem(p.platform)
            plat_item.setTextAlignment(Qt.AlignCenter)
            self.table_retained.setItem(row_idx, 3, plat_item)

            acc_cnt_item = QTableWidgetItem(str(p.account_count))
            acc_cnt_item.setTextAlignment(Qt.AlignCenter)
            acc_cnt_item.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            acc_cnt_item.setForeground(QColor("#2563EB"))
            self.table_retained.setItem(row_idx, 4, acc_cnt_item)

            vid_cnt_item = QTableWidgetItem(str(p.video_count))
            vid_cnt_item.setTextAlignment(Qt.AlignCenter)
            self.table_retained.setItem(row_idx, 5, vid_cnt_item)

            self.table_retained.setItem(row_idx, 6, QTableWidgetItem(", ".join(p.accounts)))
            self.table_retained.setItem(row_idx, 7, QTableWidgetItem(p.price_range))

    def filter_retained_table(self, query: str):
        """Filter table rows based on search keyword."""
        query = query.strip().lower()
        visible_count = 0
        for row in range(self.table_retained.rowCount()):
            name_item = self.table_retained.item(row, 1)
            cleaned_item = self.table_retained.item(row, 2)
            acc_item = self.table_retained.item(row, 6)

            text = ""
            if name_item:
                text += name_item.text().lower() + " "
            if cleaned_item:
                text += cleaned_item.text().lower() + " "
            if acc_item:
                text += acc_item.text().lower()

            matches = (query in text) if query else True
            self.table_retained.setRowHidden(row, not matches)
            if matches:
                visible_count += 1

        self.label_retained_count.setText(f"保留相同商品: {visible_count} 款")

    def re_filter_current_data(self):
        """Re-filter currently crawled data when user tweaks threshold parameters without re-crawling."""
        if not self.crawled_items:
            QMessageBox.information(self, "提示", "暂无抓取数据，请先执行爬取，或者导入已有数据后再进行筛选。")
            return

        self.sync_ui_to_config()
        analyzer = ProductAnalyzer(self.config.filter_config)
        retained, _ = analyzer.aggregate_and_filter(self.crawled_items)
        self.retained_products = retained
        self.populate_retained_table(retained)
        self.tab_widget.setCurrentIndex(0)
        self.append_log(
            f"[重算] 已按新规则重新计算！跨账号门槛>={self.config.filter_config.min_account_count}，"
            f"频次>={self.config.filter_config.min_total_occurrences}，筛选出 {len(retained)} 款共性商品。"
        )

    def on_retained_cell_double_clicked(self, row: int, col: int):
        """Double click row to open sample video url in default system browser."""
        if row < len(self.retained_products):
            p = self.retained_products[row]
            if p.sample_video_url:
                QDesktopServices.openUrl(QUrl(p.sample_video_url))

    def on_all_cell_double_clicked(self, row: int, col: int):
        """Double click row in all items table to open video URL."""
        if row < len(self.crawled_items):
            it = self.crawled_items[row]
            if it.video_url:
                QDesktopServices.openUrl(QUrl(it.video_url))

    def export_to_excel(self):
        """Export retained and all items to Excel file."""
        if not self.retained_products and not self.crawled_items:
            QMessageBox.warning(self, "提示", "暂无数据可导出！请先爬取或加载数据。")
            return

        default_name = f"短视频带货保留相同商品_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel 报表", os.path.join(self.config.export_dir, default_name), "Excel Files (*.xlsx)"
        )

        if save_path:
            try:
                self.sync_ui_to_config()
                DataExporter.export_to_excel(
                    file_path=save_path,
                    retained_products=self.retained_products,
                    all_items=self.crawled_items,
                    accounts=self.config.accounts
                )
                self.append_log(f"[导出] 成功导出报表至: {save_path}")
                reply = QMessageBox.information(
                    self, "导出成功", f"文件已保存至:\n{save_path}\n\n是否立即打开所在文件夹？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    os.startfile(os.path.dirname(os.path.abspath(save_path)))
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出文件时发生错误: {e}")
