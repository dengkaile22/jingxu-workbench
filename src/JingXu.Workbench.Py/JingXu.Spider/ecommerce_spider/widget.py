"""
Embeddable PySide6 UI Component for Douyin & Kuaishou e-commerce crawling & analysis.
Can be plugged into any existing PySide6/PyQt desktop application as a standard QWidget.
"""
import os
from datetime import datetime, timedelta
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QCheckBox, QRadioButton,
    QButtonGroup, QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QTextEdit, QProgressBar, QFileDialog, QMessageBox,
    QDialog, QComboBox, QGroupBox, QSplitter
)
from PySide6.QtCore import Qt, QDate, QUrl, Signal
from PySide6.QtGui import QFont, QColor, QDesktopServices

from core.models import AccountTarget, TimeFilterConfig, OccurrenceFilterConfig, VideoProductItem, RetainedProduct
from core.config import AppConfig
from core.browser_manager import BrowserManager
from core.analyzer import ProductAnalyzer
from core.exporter import DataExporter
from gui.worker import CrawlWorker
from gui.main_window import AddAccountDialog, BatchImportDialog, STYLE_SHEET


class EcommerceCrawlerWidget(QWidget):
    """
    Reusable PySide6 composite widget.
    Embed into any layout: `my_layout.addWidget(EcommerceCrawlerWidget())`.
    """

    # Custom signals for integration with parent application
    crawl_finished = Signal(list, list)   # (retained_products, all_items)
    product_discovered = Signal(object)    # VideoProductItem

    def __init__(self, parent: Optional[QWidget] = None, config_path: Optional[str] = None):
        super().__init__(parent)
        self.setStyleSheet(STYLE_SHEET)

        self.config = AppConfig(config_path) if config_path else AppConfig()
        self.worker: Optional[CrawlWorker] = None
        self.crawled_items: List[VideoProductItem] = []
        self.retained_products: List[RetainedProduct] = []

        self.init_ui()
        self.load_config_to_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 10)
        main_layout.setSpacing(8)

        # Header bar
        header_layout = QHBoxLayout()
        title_label = QLabel("🎬 抖音 & 快手多账号短视频带货商品爬取与共性保留分析组件")
        title_label.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        title_label.setStyleSheet("color: #0F172A;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        btn_login_douyin = QPushButton("🌐 登录抖音")
        btn_login_douyin.setObjectName("btn_login")
        btn_login_douyin.clicked.connect(lambda: self.open_login_browser("douyin"))
        header_layout.addWidget(btn_login_douyin)

        btn_login_ks = QPushButton("⚡ 登录快手")
        btn_login_ks.setObjectName("btn_login")
        btn_login_ks.clicked.connect(lambda: self.open_login_browser("kuaishou"))
        header_layout.addWidget(btn_login_ks)

        main_layout.addLayout(header_layout)

        # Splitter: Upper Config, Lower Results
        splitter = QSplitter(Qt.Vertical)

        # Top Container
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        # 1. Accounts
        group_accounts = QGroupBox("1. 🎯 对标账号配置")
        acc_layout = QVBoxLayout(group_accounts)

        self.table_accounts = QTableWidget()
        self.table_accounts.setColumnCount(5)
        self.table_accounts.setHorizontalHeaderLabels(["启用", "平台", "账号名称", "主页链接 / ID", "状态"])
        self.table_accounts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_accounts.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_accounts.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table_accounts.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_accounts.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        acc_layout.addWidget(self.table_accounts)

        acc_btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ 添加")
        btn_add.clicked.connect(self.add_account_dialog)
        btn_batch = QPushButton("📋 批量导入")
        btn_batch.clicked.connect(self.batch_import_dialog)
        btn_del = QPushButton("🗑️ 删除")
        btn_del.setStyleSheet("background-color: #EF4444;")
        btn_del.clicked.connect(self.delete_selected_account)
        btn_clear = QPushButton("🧹 清空")
        btn_clear.setStyleSheet("background-color: #64748B;")
        btn_clear.clicked.connect(self.clear_all_accounts)

        acc_btn_layout.addWidget(btn_add)
        acc_btn_layout.addWidget(btn_batch)
        acc_btn_layout.addWidget(btn_del)
        acc_btn_layout.addWidget(btn_clear)
        acc_layout.addLayout(acc_btn_layout)

        top_layout.addWidget(group_accounts, stretch=6)

        # Right config
        right_config_layout = QVBoxLayout()
        right_config_layout.setSpacing(8)

        # 2. Time Filter
        group_time = QGroupBox("2. ⏱️ 爬取时间范围")
        time_layout = QVBoxLayout(group_time)

        self.time_bg = QButtonGroup(self)
        self.rb_3d = QRadioButton("近3天")
        self.rb_7d = QRadioButton("近7天")
        self.rb_15d = QRadioButton("近15天")
        self.rb_30d = QRadioButton("近30天")
        self.rb_custom = QRadioButton("自定义")
        self.rb_all = QRadioButton("全部")

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

        date_picker_layout = QHBoxLayout()
        date_picker_layout.addWidget(QLabel("起始:"))
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        date_picker_layout.addWidget(self.date_start)

        date_picker_layout.addWidget(QLabel("结束:"))
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        date_picker_layout.addWidget(self.date_end)

        time_layout.addLayout(date_picker_layout)
        right_config_layout.addWidget(group_time)

        # 3. Retention Filter
        group_filter = QGroupBox("3. 🔍 相同商品保留规则")
        filter_layout = QVBoxLayout(group_filter)

        f_row1 = QHBoxLayout()
        f_row1.addWidget(QLabel("跨账号门槛 (出现在 >= 个不同账号):"))
        self.spin_min_accounts = QSpinBox()
        self.spin_min_accounts.setRange(1, 100)
        self.spin_min_accounts.setValue(2)
        f_row1.addWidget(self.spin_min_accounts)
        filter_layout.addLayout(f_row1)

        f_row2 = QHBoxLayout()
        f_row2.addWidget(QLabel("总频次门槛 (视频出现 >= 次):"))
        self.spin_min_total = QSpinBox()
        self.spin_min_total.setRange(1, 1000)
        self.spin_min_total.setValue(1)
        f_row2.addWidget(self.spin_min_total)
        filter_layout.addLayout(f_row2)

        f_row3 = QHBoxLayout()
        self.cb_fuzzy = QCheckBox("启用智能去噪与相似款归并")
        self.cb_fuzzy.setChecked(True)
        f_row3.addWidget(self.cb_fuzzy)

        self.cb_headless = QCheckBox("无头模式")
        self.cb_headless.setChecked(False)
        f_row3.addWidget(self.cb_headless)
        filter_layout.addLayout(f_row3)

        right_config_layout.addWidget(group_filter)
        top_layout.addLayout(right_config_layout, stretch=5)
        splitter.addWidget(top_widget)

        # Action bar
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 2, 0, 2)

        self.btn_start = QPushButton("🚀 开始爬取与分析")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_crawl)
        action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹️ 终止")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_crawl)
        action_layout.addWidget(self.btn_stop)

        self.btn_re_filter = QPushButton("🔄 重新按新阈值筛选")
        self.btn_re_filter.setStyleSheet("background-color: #4F46E5; min-height: 28px;")
        self.btn_re_filter.clicked.connect(self.re_filter_current_data)
        action_layout.addWidget(self.btn_re_filter)

        self.btn_export = QPushButton("📊 导出 Excel")
        self.btn_export.setObjectName("btn_export")
        self.btn_export.clicked.connect(self.export_to_excel)
        action_layout.addWidget(self.btn_export)

        main_layout.addWidget(action_widget)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("空闲就绪")
        main_layout.addWidget(self.progress_bar)

        # Tabs
        self.tab_widget = QTabWidget()

        # Tab 1: Retained identical items
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        search_box = QHBoxLayout()
        search_box.addWidget(QLabel("🔍 过滤:"))
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("输入关键词过滤保留商品...")
        self.edit_search.textChanged.connect(self.filter_retained_table)
        search_box.addWidget(self.edit_search)
        self.label_retained_count = QLabel("保留相同商品: 0 款")
        self.label_retained_count.setStyleSheet("font-weight: bold; color: #16A34A;")
        search_box.addWidget(self.label_retained_count)
        tab1_layout.addLayout(search_box)

        self.table_retained = QTableWidget()
        self.table_retained.setColumnCount(8)
        self.table_retained.setHorizontalHeaderLabels([
            "序号", "商品名称", "清洗名称", "平台", "共同带货账号数", "带货总频次", "涉及对标账号明细", "价格区间"
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

        # Tab 2: All items
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
        self.tab_widget.addTab(tab2, "📦 全部带货商品流水")

        # Tab 3: Logs
        tab3 = QWidget()
        tab3_layout = QVBoxLayout(tab3)
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setStyleSheet("background-color: #0F172A; color: #38BDF8; font-family: Consolas, monospace;")
        tab3_layout.addWidget(self.text_log)
        self.tab_widget.addTab(tab3, "📝 实时日志")

        splitter.addWidget(self.tab_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        main_layout.addWidget(splitter)

    def load_config_to_ui(self):
        self.refresh_accounts_table()
        mode = self.config.time_config.mode
        days = self.config.time_config.days
        if mode == "days":
            if days == 3: self.rb_3d.setChecked(True)
            elif days == 7: self.rb_7d.setChecked(True)
            elif days == 15: self.rb_15d.setChecked(True)
            elif days == 30: self.rb_30d.setChecked(True)
            else: self.rb_7d.setChecked(True)
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

        self.spin_min_accounts.setValue(self.config.filter_config.min_account_count)
        self.spin_min_total.setValue(self.config.filter_config.min_total_occurrences)
        self.cb_fuzzy.setChecked(self.config.filter_config.enable_fuzzy_cluster)
        self.cb_headless.setChecked(self.config.headless)

    def refresh_accounts_table(self):
        self.table_accounts.setRowCount(0)
        for row_idx, acc in enumerate(self.config.accounts):
            self.table_accounts.insertRow(row_idx)
            cb_item = QTableWidgetItem()
            cb_item.setCheckState(Qt.Checked if acc.enabled else Qt.Unchecked)
            self.table_accounts.setItem(row_idx, 0, cb_item)

            plat_text = "抖音" if acc.platform == "douyin" else "快手"
            plat_item = QTableWidgetItem(plat_text)
            plat_item.setTextAlignment(Qt.AlignCenter)
            plat_item.setForeground(QColor("#BE185D" if acc.platform == "douyin" else "#EA580C"))
            self.table_accounts.setItem(row_idx, 1, plat_item)
            self.table_accounts.setItem(row_idx, 2, QTableWidgetItem(acc.name))
            self.table_accounts.setItem(row_idx, 3, QTableWidgetItem(acc.url_or_id))
            status_item = QTableWidgetItem(acc.status)
            status_item.setTextAlignment(Qt.AlignCenter)
            self.table_accounts.setItem(row_idx, 4, status_item)

    def on_time_radio_changed(self, button):
        now = datetime.now()
        bid = self.time_bg.id(button)
        if bid > 0:
            start = now - timedelta(days=bid)
            self.date_start.setDate(QDate(start.year, start.month, start.day))
            self.date_end.setDate(QDate(now.year, now.month, now.day))
            self.date_start.setEnabled(False)
            self.date_end.setEnabled(False)
        elif bid == 0:
            self.date_start.setEnabled(True)
            self.date_end.setEnabled(True)
        elif bid == -1:
            self.date_start.setDate(QDate(2020, 1, 1))
            self.date_end.setDate(QDate(now.year, now.month, now.day))
            self.date_start.setEnabled(False)
            self.date_end.setEnabled(False)

    def sync_ui_to_config(self):
        for row in range(self.table_accounts.rowCount()):
            cb_item = self.table_accounts.item(row, 0)
            if cb_item and row < len(self.config.accounts):
                self.config.accounts[row].enabled = (cb_item.checkState() == Qt.Checked)
                name_item = self.table_accounts.item(row, 2)
                url_item = self.table_accounts.item(row, 3)
                if name_item: self.config.accounts[row].name = name_item.text().strip()
                if url_item: self.config.accounts[row].url_or_id = url_item.text().strip()

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

        self.config.filter_config.min_account_count = self.spin_min_accounts.value()
        self.config.filter_config.min_total_occurrences = self.spin_min_total.value()
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

    def delete_selected_account(self):
        cur = self.table_accounts.currentRow()
        if 0 <= cur < len(self.config.accounts):
            del self.config.accounts[cur]
            self.config.save()
            self.refresh_accounts_table()

    def clear_all_accounts(self):
        reply = QMessageBox.question(self, "确认", "确定要清空所有对标账号吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.config.accounts.clear()
            self.config.save()
            self.refresh_accounts_table()

    def open_login_browser(self, platform: str):
        bm = BrowserManager(headless=False)
        msg = bm.open_login_window(platform)
        self.append_log(f"[登录管理] {msg}")

    def append_log(self, text: str):
        self.text_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

    def start_crawl(self):
        self.sync_ui_to_config()
        enabled = [acc for acc in self.config.accounts if acc.enabled]
        if not enabled:
            QMessageBox.warning(self, "提示", "请先在列表中勾选至少一个启用的对标账号！")
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("正在初始化爬虫...")

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
            self.append_log("[系统] 用户点击终止，正在停止...")

    def on_worker_progress(self, cur: int, tot: int, stat: str):
        if tot > 0:
            self.progress_bar.setValue(int((cur / tot) * 100))
        self.progress_bar.setFormat(f"{stat} ({cur}/{tot})")

    def on_account_status(self, idx: int, stat: str):
        if idx < self.table_accounts.rowCount():
            item = self.table_accounts.item(idx, 4)
            if item: item.setText(stat)

    def on_product_found(self, item: VideoProductItem):
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
        self.product_discovered.emit(item)

    def on_crawl_finished(self, retained: List[RetainedProduct], all_items: List[VideoProductItem]):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("分析完成！")

        self.retained_products = retained
        self.crawled_items = all_items
        self.populate_retained_table(retained)
        self.tab_widget.setCurrentIndex(0)
        self.crawl_finished.emit(retained, all_items)

    def on_crawl_error(self, err: str):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setFormat("出错")
        QMessageBox.critical(self, "错误", f"爬虫异常: {err}")

    def populate_retained_table(self, retained: List[RetainedProduct]):
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

            acc_cnt = QTableWidgetItem(str(p.account_count))
            acc_cnt.setTextAlignment(Qt.AlignCenter)
            acc_cnt.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            acc_cnt.setForeground(QColor("#2563EB"))
            self.table_retained.setItem(row_idx, 4, acc_cnt)

            vid_cnt = QTableWidgetItem(str(p.video_count))
            vid_cnt.setTextAlignment(Qt.AlignCenter)
            self.table_retained.setItem(row_idx, 5, vid_cnt)
            self.table_retained.setItem(row_idx, 6, QTableWidgetItem(", ".join(p.accounts)))
            self.table_retained.setItem(row_idx, 7, QTableWidgetItem(p.price_range))

    def filter_retained_table(self, query: str):
        query = query.strip().lower()
        vis = 0
        for row in range(self.table_retained.rowCount()):
            name = (self.table_retained.item(row, 1).text() if self.table_retained.item(row, 1) else "").lower()
            acc = (self.table_retained.item(row, 6).text() if self.table_retained.item(row, 6) else "").lower()
            matches = (query in name or query in acc) if query else True
            self.table_retained.setRowHidden(row, not matches)
            if matches: vis += 1
        self.label_retained_count.setText(f"保留相同商品: {vis} 款")

    def re_filter_current_data(self):
        if not self.crawled_items:
            QMessageBox.information(self, "提示", "暂无数据，请先爬取或导入数据。")
            return
        self.sync_ui_to_config()
        analyzer = ProductAnalyzer(self.config.filter_config)
        retained, _ = analyzer.aggregate_and_filter(self.crawled_items)
        self.retained_products = retained
        self.populate_retained_table(retained)
        self.tab_widget.setCurrentIndex(0)
        self.append_log(f"[重算] 按新门槛筛选出 {len(retained)} 款共性商品。")

    def on_retained_cell_double_clicked(self, row: int, col: int):
        if row < len(self.retained_products):
            url = self.retained_products[row].sample_video_url
            if url: QDesktopServices.openUrl(QUrl(url))

    def on_all_cell_double_clicked(self, row: int, col: int):
        if row < len(self.crawled_items):
            url = self.crawled_items[row].video_url
            if url: QDesktopServices.openUrl(QUrl(url))

    def export_to_excel(self):
        if not self.retained_products and not self.crawled_items:
            QMessageBox.warning(self, "提示", "暂无数据可导出！")
            return
        default_name = f"短视频带货保留相同商品_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel 报表", os.path.join(self.config.export_dir, default_name), "Excel Files (*.xlsx)"
        )
        if save_path:
            self.sync_ui_to_config()
            DataExporter.export_to_excel(save_path, self.retained_products, self.crawled_items, self.config.accounts)
            QMessageBox.information(self, "成功", f"文件已保存至:\n{save_path}")
