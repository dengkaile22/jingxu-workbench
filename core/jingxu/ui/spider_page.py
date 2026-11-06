"""选品抓取页：独立导航页，界面完全用主程序自己的控件与主题令牌。

为什么要重做界面：历史实现直接内嵌爬虫项目自带的 PySide6 GUI
（``ecommerce_spider.EcommerceCrawlerWidget``），其配色、字号与控件风格都
来自爬虫项目，与主程序不统一。这里改为：

* 只用主程序控件词汇（``SectionHeader``/``Caption``/``PrimaryButton``/
  ``SecondaryButton``/``CountBadge``）与 ``theme`` 令牌；
* 抓取逻辑走爬虫的 CLI（``infrastructure/spider.py``），不再嵌入它的 GUI；
* 抓取在后台线程执行，界面不冻结；结果通过 ``videos_discovered`` 交给壳层
  送入下载队列。
"""

from __future__ import annotations

import threading
from dataclasses import replace
from functools import partial
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QUrl, Signal, QSize, QByteArray, QBuffer, QIODevice, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jingxu.infrastructure import spider as spider_service
from jingxu.infrastructure.spider_schedule import DailyScheduleStore, WindowsDailyTaskScheduler, CrawlRunLease, RUN_BUSY_MESSAGE
from jingxu.ui.spider_schedule_dialog import SpiderScheduleDialog
from jingxu.ui import theme
from jingxu.ui.widgets import (
    Caption,
    CountBadge,
    PrimaryButton,
    SecondaryButton,
    SectionHeader,
)

ACCOUNT_COLUMNS = ("启用", "平台", "备注名", "链接 / ID")
ACCOUNT_COLUMN_WIDTHS = (52, 64, 150, 320)
# 结果表第一列是勾选：只把选中的商品送入下载（此前是强制全发）。
# 其余列逐项对齐 .NET 结果表的八列（商品名称 / 清洗归一名称 / 平台 / 对标账号数 /
# 带货视频数 / 带货达人明细 / 参考售价 / 示例视频链接），漏掉的正是"哪些账号在带货"
# 与"示例视频"，那两条恰是做选品判断时最需要的信息。
RESULT_COLUMNS = (
    "选",
    "商品",
    "清洗名称",
    "平台",
    "最高点赞",
    "跨账号数",
    "出现次数",
    "对标账号明细",
    "价格区间",
    "示例视频链接",
    "商品主图",
)
RESULT_COLUMN_WIDTHS = (40, 240, 180, 70, 80, 80, 80, 200, 110, 240, 140)
RESULT_CHECK_COLUMN = 0
RESULT_NAME_COLUMN = 1
RESULT_PLATFORM_COLUMN = 3
RESULT_LIKES_COLUMN = 4
RESULT_SAMPLE_VIDEO_COLUMN = 9
RESULT_IMAGE_COLUMN = 10
# 可点开的链接列（对齐 .NET：商品链接与示例视频都能直接打开）。
# 平台与示例视频链接固定列号，供双击/右键打开使用。
LINK_COLUMNS = (RESULT_SAMPLE_VIDEO_COLUMN, RESULT_IMAGE_COLUMN)
# 日志行数上限，对齐 .NET AppendLog 的 200000 字符保护（按平均行长折算）。
LOG_MAX_BLOCKS = 2000
TIME_PRESETS = [(str(days), f"近 {days} 天") for days in (3, 7, 15, 30, 60, 90, 180, 365)] + [
    ("days", "自定天数"), ("range", "自定义日期"), ("all", "不限时间")]
REPORT_TASK_MODES = (("likes", "按点赞量"), ("total", "按总频次"), ("accounts", "按跨账号数"))

# 每一列取哪个字段。键名在不同来源里不一致（爬虫 `to_summary_dict` 用中文键，
# 中间层可能给 camelCase 或 snake_case），因此每列给一组候选键，按序兜底。
_RESULT_FIELD_KEYS: tuple[tuple[str, ...], ...] = (
    ("商品名称", "product_name", "productName", "name"),
    ("清洗名称", "cleaned_name", "cleanedName"),
    ("涉及平台", "platform"),
    ("最高点赞", "点赞量", "点赞数", "max_like_count", "like_count", "digg_count", "likeCount"),
    ("带货账号数", "跨账号数", "account_count", "accountCount"),
    ("带货视频数", "出现次数", "video_count", "videoCount", "total_occurrences", "totalOccurrences"),
    ("对标账号明细", "accounts", "account_names", "influencers"),
    ("参考价格", "价格区间", "price_range", "priceRange"),
    ("示例视频链接", "sample_video_url", "sampleVideoUrl", "video_url", "videoUrl"),
    ("商品主图", "cover_url", "coverUrl", "product_image_url"),
)


class SpiderBridge(QObject):
    """把后台抓取的日志与结果切回 UI 线程。"""

    log = Signal(str)
    finished = Signal(object)
    cover_ready = Signal(str, object)
    schedule_finished = Signal(object, str)


def extract_video_urls(items: list) -> list[str]:
    """从爬虫结果条目中提取视频链接（去重、保序）。

    保留此函数以兼容既有调用点；新代码请用 ``SpiderRunResult.video_urls``。
    """
    return list(
        spider_service.SpiderRunResult(success=True, message="").urls_for_entries(items)
    )


class SpiderPage(QWidget):
    """选品抓取模块（独立导航页，界面完全用主程序控件与主题令牌）。

    抓取在后台线程执行，界面不冻结；结果通过 ``videos_discovered`` 交给壳层
    送入下载队列。
    """

    videos_discovered = Signal(list)

    def __init__(
        self,
        *,
        store: spider_service.SpiderConfigStore | None = None,
        runner: spider_service.SpiderRunner | None = None,
        check_environment=None,  # noqa: ANN001 - Callable[[], SpiderEnvironment]
        schedule_store=None,
        scheduler=None,
    ) -> None:
        super().__init__()

        self._store = store or spider_service.SpiderConfigStore()
        self._runner = runner or spider_service.SpiderRunner()
        self._check_environment = check_environment or spider_service.check_environment
        self._config = self._store.load()
        self._schedule_store = schedule_store or DailyScheduleStore(self._store.path.with_name("daily_schedule.json"))
        self._scheduler = scheduler or WindowsDailyTaskScheduler()
        self._schedule_busy = False
        self._observed_schedule_finish = ""
        self._rows: list[spider_service.SpiderAccount] = []
        self._result_entries: list[dict] = []
        self._running = False
        self._cancel = threading.Event()
        self._last_result: spider_service.SpiderRunResult | None = None
        self._login_session: spider_service.SpiderLoginSession | None = None
        self._updating = False
        self._cover_cache: dict[str, bytes] = {}
        self._pending_covers: set[str] = set()
        self._deferred_covers: set[str] = set()
        self._cover_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="selection-covers")
        self._disposed = False
        # 可打开的链接单元格 (行, 列)；填充结果时重建。
        self._openable_cells: set[tuple[int, int]] = set()

        self._bridge = SpiderBridge(self)
        self._bridge.finished.connect(self._on_run_finished)
        self._bridge.log.connect(self._append_log)
        self._bridge.cover_ready.connect(self._on_cover_ready)
        self._bridge.schedule_finished.connect(self._on_schedule_finished)

        # 整页放进滚动区：本页内容很长（账号表 + 门槛 + 登录 + 结果 + 日志），
        # 窗口不够高时下方区块会被截断且无法滚动到。与合成页保持同一写法。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        layout.addLayout(self._build_header())
        layout.addSpacing(10)

        layout.addLayout(self._build_accounts_header())
        layout.addSpacing(6)
        layout.addWidget(self._build_accounts_table())

        # 「添加对标账号」独立成行（对齐 .NET：平台下拉 + 链接框 + 备注名 + 添加账号）
        layout.addSpacing(10)
        layout.addWidget(SectionHeader("添加对标账号"))
        layout.addSpacing(6)
        layout.addLayout(self._build_add_account_row())

        self._import_toggle = SecondaryButton("批量导入")
        self._import_toggle.setToolTip("每行一个主页链接/短链/ID，自动识别平台。")
        self._import_toggle.clicked.connect(self._toggle_import)
        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        import_row.addWidget(Caption("批量导入（每行一个主页链接/短链/ID，自动识别平台）"))
        import_row.addWidget(self._import_toggle)
        import_row.addStretch(1)
        layout.addSpacing(6)
        layout.addLayout(import_row)

        self._import_box = self._build_import_box()
        self._import_box.setVisible(False)
        layout.addWidget(self._import_box)

        layout.addSpacing(12)
        layout.addWidget(SectionHeader("抓取设置"))
        layout.addSpacing(6)
        layout.addLayout(self._build_filter_rows())
        layout.addSpacing(6)
        layout.addWidget(SectionHeader("筛选报表（勾选一项或多项，各自设置时间范围）"))
        layout.addWidget(self._build_report_tasks())
        layout.addWidget(Caption("勾选一项可导出单项报表；勾选多项可同时导出。每项分别筛选，抖音与快手分别列出。"))

        layout.addSpacing(10)
        layout.addLayout(self._build_action_row())
        self._schedule_caption = Caption("")
        layout.addWidget(self._schedule_caption)
        layout.addSpacing(4)
        layout.addLayout(self._build_login_row())

        layout.addSpacing(10)
        self._result_caption = Caption("尚未抓取。")
        layout.addWidget(self._result_caption)
        layout.addLayout(self._build_result_filters())
        layout.addSpacing(6)
        layout.addWidget(self._build_results_table())
        layout.addSpacing(6)
        layout.addLayout(self._build_result_actions())
        layout.addSpacing(6)
        layout.addWidget(self._build_log_box())

        self._apply_config_to_form()
        self._refresh_accounts()
        self._refresh_environment()
        self._refresh_login_status()
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(15000)
        self._schedule_timer.timeout.connect(self._refresh_schedule_status)
        self._schedule_timer.start()
        self._refresh_schedule_status()
        self._restore_last_result()

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel("选品抓取")
        title.setObjectName("Title")
        row.addWidget(title)

        self._environment_label = Caption("正在检测爬虫环境…")
        row.addWidget(self._environment_label, stretch=1)

        self._account_badge = CountBadge("0")
        row.addWidget(self._account_badge)

        detect = SecondaryButton("重新检测")
        detect.clicked.connect(self._refresh_environment)
        row.addWidget(detect)
        return row

    def _build_accounts_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(SectionHeader("对标账号"))
        row.addStretch(1)

        self._remove_account = SecondaryButton("移除选中")
        self._remove_account.clicked.connect(self._remove_selected_accounts)
        row.addWidget(self._remove_account)

        self._export_account_button = SecondaryButton("导出账号")
        self._export_account_button.setToolTip("导出全部账号（含停用账号），文本可直接在另一台设备批量导入。")
        self._export_account_button.clicked.connect(self._export_accounts)
        row.addWidget(self._export_account_button)

        clear = SecondaryButton("清空账号")
        clear.clicked.connect(self._clear_accounts)
        row.addWidget(clear)
        return row

    def _build_add_account_row(self) -> QHBoxLayout:
        """单条添加：平台 + 链接/ID + 备注名（对齐 .NET「添加对标账号」）。"""
        row = QHBoxLayout()
        row.setSpacing(8)

        # 默认「自动识别」，避免把用户的链接强行归到某个平台。
        # （此前默认抖音，导致粘贴快手链接被存成抖音账号。）
        self._platform_combo = _combo(
            [("", "自动识别"), ("douyin", "抖音"), ("kuaishou", "快手")]
        )
        self._platform_combo.setFixedWidth(96)
        self._platform_combo.setToolTip("默认按链接特征自动识别；也可手动指定平台。")
        row.addWidget(self._platform_combo)

        self._account_input = QLineEdit()
        self._account_input.setPlaceholderText("主页链接 / 分享短链 / 抖音号 / Sec-UID")
        self._account_input.returnPressed.connect(self._add_single_account)
        row.addWidget(self._account_input, stretch=1)

        self._account_name_input = QLineEdit()
        self._account_name_input.setPlaceholderText("备注名（可空）")
        self._account_name_input.setFixedWidth(150)
        self._account_name_input.returnPressed.connect(self._add_single_account)
        row.addWidget(self._account_name_input)

        add_button = PrimaryButton("+ 添加账号")
        add_button.clicked.connect(self._add_single_account)
        row.addWidget(add_button)
        return row

    def _add_single_account(self) -> None:
        """添加单个账号。空输入给出提示，不静默失败。"""
        raw = self._account_input.text().strip()
        if not raw:
            self._set_result_caption("请输入账号链接或 ID。", warn=True)
            self._account_input.setFocus()
            return
        # 平台留空表示自动识别（parse_accounts_text 会按链接特征判断）。
        platform = str(self._platform_combo.currentData() or "")
        parsed = spider_service.parse_accounts_text(raw, platform=platform)
        if not parsed:
            self._set_result_caption("未能从输入中识别出账号，请检查链接格式。", warn=True)
            return

        account = parsed[0]
        name = self._account_name_input.text().strip()
        if name:
            account = spider_service.SpiderAccount(
                platform=account.platform, url_or_id=account.url_or_id, name=name
            )

        account_key = spider_service.account_identity_key(account)
        if any(spider_service.account_identity_key(existing) == account_key for existing in self._rows):
            self._set_result_caption(f"该账号已在列表中：{account.display_name}", warn=True)
            return

        self._rows.append(account)
        self._persist()
        self._refresh_accounts()
        self._account_input.clear()
        self._account_name_input.clear()
        self._set_result_caption(f"已添加：{account.display_name}（{account.platform_label}）")

    def _build_accounts_table(self) -> QWidget:
        self._accounts_table = QTableWidget(0, len(ACCOUNT_COLUMNS))
        self._accounts_table.setHorizontalHeaderLabels(list(ACCOUNT_COLUMNS))
        self._accounts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._accounts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._accounts_table.verticalHeader().setVisible(False)
        self._accounts_table.setFixedHeight(150)
        # 列宽之和作为最小宽度：窗口不够宽时横向滚动，而不是把「平台」列挤没
        # （实测窄窗口下「快手」会串到链接列，看起来像平台识别错了）。
        header = self._accounts_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate(ACCOUNT_COLUMN_WIDTHS):
            self._accounts_table.setColumnWidth(column, width)
        self._accounts_table.setMinimumWidth(sum(ACCOUNT_COLUMN_WIDTHS) + 24)
        self._accounts_table.itemChanged.connect(self._on_account_item_changed)
        return self._accounts_table

    def _build_import_box(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        self._import_text = QPlainTextEdit()
        self._import_text.setFixedHeight(76)
        self._import_text.setPlaceholderText(
            "每行一个账号，可写「备注名=链接」。\n"
            "支持抖音/快手主页链接、分享短链，或 Sec-UID。"
        )
        layout.addWidget(self._import_text)

        row = QHBoxLayout()
        row.setSpacing(8)
        add = PrimaryButton("加入账号")
        add.clicked.connect(self._apply_import)
        row.addWidget(add)
        cancel = SecondaryButton("收起")
        cancel.clicked.connect(self._toggle_import)
        row.addWidget(cancel)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _build_filter_rows(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(6)

        advanced_row = QHBoxLayout()
        advanced_row.setSpacing(8)
        self._enable_fuzzy = QCheckBox("开启智能去噪与同款商品模糊合并")
        advanced_row.addWidget(self._enable_fuzzy)
        self._fuzzy_threshold = QDoubleSpinBox()
        self._fuzzy_threshold.setRange(0.5, 1.0)
        self._fuzzy_threshold.setSingleStep(0.05)
        self._fuzzy_threshold.setDecimals(2)
        advanced_row.addWidget(self._fuzzy_threshold)

        advanced_row.addWidget(Caption("翻页上限"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._max_scrolls = QSpinBox()
        self._max_scrolls.setRange(1, 200)
        advanced_row.addWidget(self._max_scrolls)

        self._headless = QCheckBox("无头模式（后台运行）")
        advanced_row.addWidget(self._headless)
        advanced_row.addStretch(1)
        column.addLayout(advanced_row)
        browser_row = QHBoxLayout()
        browser_row.setSpacing(8)
        browser_row.addWidget(Caption("更换独立浏览器环境：每"))
        self._browser_rotate_minutes = QSpinBox()
        self._browser_rotate_minutes.setRange(1, 120)
        self._browser_rotate_minutes.setSuffix(" 分钟")
        browser_row.addWidget(self._browser_rotate_minutes)
        browser_row.addWidget(Caption("或累计"))
        self._browser_rotate_pages = QSpinBox()
        self._browser_rotate_pages.setRange(1, 200)
        self._browser_rotate_pages.setSuffix(" 页")
        browser_row.addWidget(self._browser_rotate_pages)
        browser_row.addWidget(Caption("达到任一条件即更换，保存 Cookie 并接着抓取"))
        browser_row.addStretch(1)
        column.addLayout(browser_row)
        return column

    def _build_report_tasks(self) -> QWidget:
        table = self._tasks_table = QTableWidget(3, 7)
        table.setHorizontalHeaderLabels(["启用", "筛选条件", "门槛", "时间范围", "天数", "开始日期", "结束日期"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFixedHeight(146)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._task_widgets = {}
        for row, (mode, label) in enumerate(REPORT_TASK_MODES):
            enabled = QCheckBox()
            enabled.setChecked(True)
            table.setCellWidget(row, 0, enabled)
            table.setItem(row, 1, QTableWidgetItem(label))
            threshold = QSpinBox()
            threshold.setRange(0 if mode == "likes" else 1, 10_000_000)
            threshold.setValue(0 if mode == "likes" else 2)
            threshold.setSuffix(" 赞" if mode == "likes" else " 次" if mode == "total" else " 账号")
            preset = _combo(TIME_PRESETS)
            days = QSpinBox()
            days.setRange(1, 3650)
            days.setValue(7)
            start, end = QLineEdit(), QLineEdit()
            start.setPlaceholderText("YYYY-MM-DD")
            end.setPlaceholderText("YYYY-MM-DD")
            widgets = dict(enabled=enabled, threshold=threshold, preset=preset, days=days, start=start, end=end)
            self._task_widgets[mode] = widgets
            for column, widget in enumerate((threshold, preset, days, start, end), 2):
                table.setCellWidget(row, column, widget)
            preset.currentIndexChanged.connect(partial(self._on_task_time_changed, mode))
            _select(preset, "7")
            self._on_task_time_changed(mode)
            table.setRowHeight(row, 36)
        return table

    def _on_task_time_changed(self, mode: str, *_unused) -> None:
        widgets = self._task_widgets[mode]
        value = str(widgets["preset"].currentData())
        if value.isdigit():
            widgets["days"].setValue(int(value))
        widgets["days"].setEnabled(value == "days")
        widgets["start"].setEnabled(value == "range")
        widgets["end"].setEnabled(value == "range")

    def _collect_report_tasks(self) -> tuple[spider_service.SpiderFilters, ...]:
        defaults = self._collect_filters()
        tasks = []
        for mode, widgets in self._task_widgets.items():
            if not widgets["enabled"].isChecked():
                continue
            time = str(widgets["preset"].currentData())
            metric = {"likes": "min_likes", "total": "min_occurrences", "accounts": "min_accounts"}[mode]
            tasks.append(replace(defaults, filter_by=mode, time_mode=time if time in ("range", "all") else "days",
                                 days=widgets["days"].value(), start_date=widgets["start"].text().strip(),
                                 end_date=widgets["end"].text().strip(), **{metric: widgets["threshold"].value()}))
        return tuple(tasks)

    def _build_result_filters(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(Caption("查看报表"))
        self._result_report = _combo([("", "当前筛选结果")])
        self._result_platform = _combo([("", "全部平台"), ("douyin", "抖音"), ("kuaishou", "快手")])
        row.addWidget(self._result_report)
        row.addWidget(self._result_platform)
        row.addStretch(1)
        self._result_report.currentIndexChanged.connect(self._refilter_results)
        self._result_platform.currentIndexChanged.connect(self._refilter_results)
        return row

    def _refilter_results(self) -> None:
        if self._last_result is not None and not self._updating:
            self._fill_results(self._last_result)

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._run_button = PrimaryButton("开始抓取")
        self._run_button.setToolTip("将打开浏览器读取对标账号的带货视频，可随时取消。")
        self._run_button.clicked.connect(self._start_crawl)
        row.addWidget(self._run_button)
        self._schedule_button = SecondaryButton("定时抓取")
        self._schedule_button.setToolTip("自定义每天自动开始时间，完成后自动保存报表。")
        self._schedule_button.clicked.connect(self._configure_schedule)
        row.addWidget(self._schedule_button)

        self._cancel_button = SecondaryButton("取消抓取")
        self._cancel_button.clicked.connect(self._cancel_crawl)
        self._cancel_button.setEnabled(False)
        row.addWidget(self._cancel_button)

        self._send_button = SecondaryButton("结果送入下载")
        self._send_button.setToolTip("把结果表中勾选的商品链接加入上方下载队列。")
        self._send_button.clicked.connect(self._send_last_result)
        self._send_button.setEnabled(False)
        row.addWidget(self._send_button)

        self._export_label = Caption("")
        row.addWidget(self._export_label)
        row.addStretch(1)
        return row

    def _configure_schedule(self) -> None:
        if self._schedule_busy:
            return
        dialog = SpiderScheduleDialog(self._schedule_store.load(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_schedule(dialog.schedule())

    def _save_schedule(self, schedule) -> None:
        if not self._persist():
            return
        if schedule.enabled:
            if not self._config.enabled_accounts:
                self._set_result_caption("请先添加并启用对标账号，再开启定时抓取。", warn=True)
                return
            if not self._config.report_tasks:
                self._set_result_caption("请至少勾选一个筛选报表，再开启定时抓取。", warn=True)
                return
            for task in self._config.report_tasks:
                issue = spider_service.validate_date_filters(task)
                if issue:
                    self._set_result_caption(issue, warn=True)
                    return
        self._schedule_busy = True
        self._schedule_button.setEnabled(False)
        self._schedule_caption.setText("正在保存每日抓取时间…")
        def register():
            configured, error = None, ""
            try:
                configured = self._scheduler.configure(schedule, self._schedule_store, self._store.path)
            except Exception as problem:
                error = str(problem) if isinstance(problem, RuntimeError) else f"定时设置未保存（{type(problem).__name__}），请检查系统任务计划。"
            if not self._disposed:
                try:
                    self._bridge.schedule_finished.emit(configured, error)
                except RuntimeError:
                    pass
        threading.Thread(target=register, name="jingxu-spider-schedule", daemon=True).start()

    def _on_schedule_finished(self, schedule, error: str) -> None:
        if self._disposed:
            return
        self._schedule_busy = False
        self._schedule_button.setEnabled(True)
        self._refresh_schedule_status()
        if error:
            self._set_result_caption(error, warn=True)
        elif schedule.enabled:
            self._set_result_caption(f"已设置每天 {schedule.time} 自动抓取；完成后自动保存报表，关闭软件也可执行。")
        else:
            self._set_result_caption("每日定时抓取已停用。")

    def _refresh_schedule_status(self) -> None:
        if self._disposed or self._schedule_busy:
            return
        schedule = self._schedule_store.load()
        state = self._schedule_store.load_state()
        if schedule.enabled:
            self._schedule_caption.setText(f"每日 {schedule.time} 自动抓取 · 下次 {schedule.next_run().strftime('%m-%d %H:%M')} · 请保持电脑开机、当前账号登录并联网")
        else:
            self._schedule_caption.setText("未启用每日抓取，可点击「定时抓取」设置。")
        status = state.get("status")
        if status:
            label = {"running": "正在抓取", "complete": "已完成", "partial": "部分完成", "failed": "未完成", "skipped": "已有任务，本次已跳过"}.get(status, str(status))
            self._schedule_caption.setText(self._schedule_caption.text() + f" · 最近定时任务：{label}")
        finished = str(state.get("finishedAt") or "")
        if finished and finished != self._observed_schedule_finish and not self._running:
            self._observed_schedule_finish = finished
            self._restore_last_result()

    def _build_login_row(self) -> QHBoxLayout:
        """扫码登录入口。

        爬虫的 ``--login`` 能力此前没有界面入口：用户第一次抓取撞到登录墙后
        无从下手，只能看到抓不到数据。
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(Caption("扫码登录"), alignment=Qt.AlignmentFlag.AlignVCenter)

        self._login_buttons: dict[str, QPushButton] = {}
        for platform, label in spider_service.PLATFORM_LABELS.items():
            button = SecondaryButton(f"🔑 扫码登录{label}")
            button.setToolTip(f"打开浏览器扫码登录{label}，登录态会被复用，无需重复登录。")
            button.clicked.connect(partial(self._open_login, platform))
            row.addWidget(button)
            self._login_buttons[platform] = button

        self._login_status = Caption("")
        row.addWidget(self._login_status, stretch=1)

        self._release_profile_btn = SecondaryButton("释放档案")
        self._release_profile_btn.setToolTip("强制关闭占用选品浏览器档案的后台进程并清理残留锁。")
        self._release_profile_btn.clicked.connect(self._release_profile)
        row.addWidget(self._release_profile_btn)

        # 登录完成后必须由用户点一下，浏览器才关闭并把 Cookie 落盘；
        # 直接关窗口可能来不及写入登录态。
        self._login_done = PrimaryButton("我已登录")
        self._login_done.setToolTip("扫码完成后点这里保存登录态并关闭浏览器。")
        self._login_done.clicked.connect(self._finish_login)
        self._login_done.setEnabled(False)
        row.addWidget(self._login_done)
        return row

    def _refresh_login_status(self) -> None:
        browser = spider_service.find_browser()
        _, profile_text = spider_service.profile_status()
        if browser is None:
            self._login_status.setText(
                "未找到 Chrome/Edge，抓取无法启动；请安装后重试。"
            )
            self._login_status.setObjectName("CaptionWarn")
        else:
            # 档案被别的浏览器占用时必须在状态行就说清楚：否则用户点「开始抓取」
            # 只会看到爬虫预检失败，而登录按钮点下去甚至会直接崩（0xc0000142）。
            lock = self._profile_lock_note()
            self._login_status.setText(f"浏览器：{browser.name} · {profile_text}{lock}")
            self._login_status.setObjectName("CaptionWarn" if lock else "Caption")
        self._login_status.style().unpolish(self._login_status)
        self._login_status.style().polish(self._login_status)
        for button in self._login_buttons.values():
            button.setEnabled(browser is not None)

    def _profile_lock_note(self) -> str:
        """档案占用提示（空串表示未被占用）。

        探测失败一律当作「未占用」：这是显示用的提示，绝不能因为探测不到就
        禁用按钮、把用户挡在门外。
        """
        try:
            state = spider_service.profile_lock_state()
        except Exception:  # noqa: BLE001 - 提示失败不影响主流程
            return ""
        if state.busy:
            return f" · ⚠ 档案正被占用（进程 {'、'.join(str(pid) for pid in state.holder_pids)}）"
        if state.cleared_locks:
            return f" · 已清理残留锁（{'、'.join(state.cleared_locks)}）"
        return ""

    def _release_profile(self) -> None:
        """用户主动释放浏览器档案占用。"""
        if self._login_session is not None:
            self._login_session.close()
            self._login_session = None
            self._login_done.setEnabled(False)
        try:
            remaining = spider_service.terminate_profile_holders()
        except Exception as error:  # noqa: BLE001 - 提示错误不影响主流程
            self._set_result_caption(f"释放档案失败：{error}", warn=True)
            self._refresh_login_status()
            return
        self._refresh_login_status()
        if remaining:
            self._set_result_caption(f"仍有进程未退出（PID {remaining}），请手动关闭。", warn=True)
        else:
            self._set_result_caption("浏览器档案已成功释放，可以正常抓取或重新登录。")

    def _open_login(self, platform: str) -> None:
        if self._login_session is not None and self._login_session.is_running():
            self._set_result_caption(
                f"{self._login_session.platform_label}登录窗口已打开，"
                "请扫码完成后点「我已登录」。"
            )
            return

        lock_state = spider_service.profile_lock_state()
        if lock_state.busy:
            answer = QMessageBox.question(
                self,
                "浏览器档案被占用",
                f"{lock_state.message}\n\n"
                f"是否关闭所有使用此选品登录档案的 Chrome/Edge 窗口并打开{spider_service.PLATFORM_LABELS.get(platform, platform)}登录页？\n"
                "未保存的网页状态可能丢失。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._set_result_caption(lock_state.message, warn=True)
                self._refresh_login_status()
                return

            try:
                spider_service.terminate_profile_holders()
            except Exception as error:  # noqa: BLE001 - 关闭失败要留在界面提示，不能崩 UI
                self._set_result_caption(f"关闭占用浏览器失败：{error}", warn=True)
                return
            self._refresh_login_status()

        try:
            session = spider_service.open_login_window(platform)
        except spider_service.SpiderError as error:
            self._set_result_caption(str(error), warn=True)
            return
        self._login_session = session
        self._login_done.setEnabled(True)
        self._set_result_caption(
            f"已打开{session.platform_label}登录页：请在浏览器中扫码登录，"
            "完成后回到这里点「我已登录」保存登录态。"
        )

    def _finish_login(self) -> None:
        """保存登录态：关闭浏览器以触发 Cookie 落盘。"""
        if self._login_session is None:
            self._login_done.setEnabled(False)
            return
        label = self._login_session.platform_label
        saved = self._login_session.close()
        self._login_session = None
        self._login_done.setEnabled(False)
        self._refresh_login_status()
        self._set_result_caption(f"{label} Cookie 已保存，抓取时将使用新的独立浏览器环境。" if saved is not False else
                                 f"{label} Cookie 保存失败，请检查选品数据目录后重新登录。", warn=saved is False)

    def _build_results_table(self) -> QWidget:
        self._results_table = QTableWidget(0, len(RESULT_COLUMNS))
        self._results_table.setHorizontalHeaderLabels(list(RESULT_COLUMNS))
        self._results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setFixedHeight(300)
        header = self._results_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate(RESULT_COLUMN_WIDTHS):
            self._results_table.setColumnWidth(column, width)
        # Keep image previews before the product while preserving logical column
        # indices used by link actions and stored row data.
        header.moveSection(header.visualIndex(RESULT_IMAGE_COLUMN), 1)
        self._results_table.setMinimumWidth(sum(RESULT_COLUMN_WIDTHS) + 24)
        self._results_table.itemChanged.connect(self._on_result_item_changed)
        # 链接列可直接打开（对齐 .NET 的 OpenSelectedSampleVideo/OpenSelectedVideo）。
        self._results_table.cellDoubleClicked.connect(self._on_result_cell_double_clicked)
        self._results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._results_table.customContextMenuRequested.connect(self._on_result_context_menu)
        self._results_table.setSortingEnabled(True)
        return self._results_table

    def _build_result_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._select_all = QCheckBox("全选")
        self._select_all.setChecked(True)
        # 三态：行勾选变化时回写，避免全选框与行状态脱钩——用户取消一行后
        # 全选框若仍显示「已勾选」，再点它不会触发任何信号，看起来像坏了。
        self._select_all.setTristate(True)
        self._select_all.setToolTip("勾选或取消「结果送入下载」时包含的商品。")
        self._select_all.clicked.connect(self._on_select_all_clicked)
        row.addWidget(self._select_all)

        self._selection_caption = Caption("")
        row.addWidget(self._selection_caption, stretch=1)

        self._open_exports = SecondaryButton("打开报表目录")
        self._open_exports.setToolTip("打开导出的 Excel 报表所在目录。")
        self._open_exports.clicked.connect(self._open_exports_directory)
        row.addWidget(self._open_exports)
        return row

    def _build_log_box(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        self._log_toggle = SecondaryButton("📋 运行日志")
        self._log_toggle.clicked.connect(self._toggle_log)
        head.addWidget(self._log_toggle)

        # 「清空日志」对齐 .NET ClearLogCommand：日志很长时不必重开页面才能清掉。
        self._log_clear = SecondaryButton("清空日志")
        self._log_clear.setToolTip("清空当前显示与缓存的运行日志（不影响正在进行的抓取）。")
        self._log_clear.clicked.connect(self._clear_log)
        self._log_clear.setEnabled(False)
        head.addWidget(self._log_clear)
        head.addStretch(1)
        layout.addLayout(head)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(110)
        self._log.setFont(theme.mono_font(11))
        self._log.setVisible(False)
        # 对齐 .NET AppendLog 的容量保护（超过 200000 字符就丢掉最旧的 50000），
        # 长时间抓取时日志会很长，不设上限会一直吃内存。
        self._log.setMaximumBlockCount(LOG_MAX_BLOCKS)
        self._log.textChanged.connect(
            lambda: self._log_clear.setEnabled(bool(self._log.toPlainText().strip()))
        )
        layout.addWidget(self._log)
        return box

    def _clear_log(self) -> None:
        """清空日志（对齐 .NET ``ClearLogCommand``：连缓冲区一起清）。"""
        self._log.clear()
        self._log_clear.setEnabled(False)

    # ────────────────────────────── 环境与账号 ──────────────────────────────

    def _refresh_environment(self) -> None:
        environment = self._check_environment()
        self._environment_label.setText(environment.message)
        self._environment_label.setObjectName(
            "Caption" if environment.available else "CaptionWarn"
        )
        # 主题样式按 objectName 命中，改完需重新应用样式表。
        self._environment_label.style().unpolish(self._environment_label)
        self._environment_label.style().polish(self._environment_label)

    def _refresh_accounts(self) -> None:
        self._updating = True
        try:
            self._accounts_table.setRowCount(len(self._rows))
            for row, account in enumerate(self._rows):
                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                )
                check.setCheckState(
                    Qt.CheckState.Checked if account.enabled else Qt.CheckState.Unchecked
                )
                self._accounts_table.setItem(row, 0, check)
                for column, value in enumerate(
                    (account.platform_label, account.name or "—", account.url_or_id), start=1
                ):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    if column == 3:
                        item.setForeground(QColor(theme.INK_MUTED))
                    self._accounts_table.setItem(row, column, item)
        finally:
            self._updating = False
        enabled = sum(1 for account in self._rows if account.enabled and account.url_or_id)
        self._account_badge.setText(str(enabled))

    def _on_account_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != 0:
            return
        row = item.row()
        if not 0 <= row < len(self._rows):
            return
        self._rows[row] = replace(self._rows[row], enabled=item.checkState() == Qt.CheckState.Checked)
        self._persist()
        self._refresh_accounts()

    def _toggle_import(self) -> None:
        visible = not self._import_box.isVisible()
        self._import_box.setVisible(visible)
        self._import_toggle.setText("收起导入" if visible else "批量粘贴导入")
        if visible:
            self._import_text.setFocus()

    def _apply_import(self) -> None:
        parsed = spider_service.parse_accounts_text(self._import_text.toPlainText())
        if not parsed:
            self._set_result_caption("未识别到账号，请检查每行内容。", warn=True)
            return
        existing = {spider_service.account_identity_key(account) for account in self._rows}
        added = 0
        for account in parsed:
            key = spider_service.account_identity_key(account)
            if key in existing:
                continue
            existing.add(key)
            self._rows.append(account)
            added += 1
        self._import_text.clear()
        self._import_box.setVisible(False)
        self._import_toggle.setText("批量粘贴导入")
        self._persist()
        self._refresh_accounts()
        skipped = len(parsed) - added
        message = f"已加入 {added} 个账号。"
        if skipped:
            message += f"（跳过 {skipped} 个重复）"
        self._set_result_caption(message)

    def _export_accounts(self) -> None:
        """导出全部账号为可重新批量导入的 UTF-8 文本。"""
        if not self._rows:
            self._set_result_caption("账号列表为空，没有可导出的账号。", warn=True)
            return
        target, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出对标账号",
            "对标账号.txt",
            "文本文件 (*.txt)",
        )
        if not target:
            return
        lines = [
            f"{account.name}={account.canonical_target}" if account.name else account.canonical_target
            for account in self._rows
        ]
        try:
            Path(target).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as error:
            self._set_result_caption(f"导出账号失败：{error}", warn=True)
            return
        self._set_result_caption(f"已导出 {len(lines)} 个账号：{target}")

    def _remove_selected_accounts(self) -> None:
        selected = sorted(
            {index.row() for index in self._accounts_table.selectedIndexes()}, reverse=True
        )
        if not selected:
            self._set_result_caption("请先在账号表中选择要移除的行。", warn=True)
            return
        for row in selected:
            if 0 <= row < len(self._rows):
                self._rows.pop(row)
        self._persist()
        self._refresh_accounts()
        self._set_result_caption(f"已移除 {len(selected)} 个账号。")

    def _clear_accounts(self) -> None:
        if not self._rows:
            return
        self._rows = []
        self._persist()
        self._refresh_accounts()
        self._set_result_caption("已清空账号。")

    # ────────────────────────────── 配置 ──────────────────────────────

    def _collect_filters(self) -> spider_service.SpiderFilters:
        base = self._config.filters
        enabled = next(((mode, widgets) for mode, widgets in self._task_widgets.items() if widgets["enabled"].isChecked()), None)
        if enabled:
            mode, widgets = enabled
            time = str(widgets["preset"].currentData())
            base = replace(base, filter_by=mode, time_mode=time if time in ("range", "all") else "days",
                           days=widgets["days"].value(), start_date=widgets["start"].text().strip(), end_date=widgets["end"].text().strip(),
                           min_likes=self._task_widgets["likes"]["threshold"].value(),
                           min_occurrences=self._task_widgets["total"]["threshold"].value(),
                           min_accounts=self._task_widgets["accounts"]["threshold"].value())
        return replace(base, enable_fuzzy=self._enable_fuzzy.isChecked(),
                       fuzzy_threshold=float(self._fuzzy_threshold.value()), max_scrolls=self._max_scrolls.value(),
                       headless=self._headless.isChecked(),
                       browser_rotate_seconds=self._browser_rotate_minutes.value() * 60,
                       browser_rotate_pages=self._browser_rotate_pages.value())

    def _apply_config_to_form(self) -> None:
        filters = self._config.filters
        self._enable_fuzzy.setChecked(filters.enable_fuzzy)
        self._fuzzy_threshold.setValue(filters.fuzzy_threshold)
        self._max_scrolls.setValue(filters.max_scrolls)
        self._headless.setChecked(filters.headless)
        self._browser_rotate_minutes.setValue(max(1, (filters.browser_rotate_seconds + 59) // 60))
        self._browser_rotate_pages.setValue(filters.browser_rotate_pages)
        self._rows = list(self._config.accounts)
        tasks = {task.filter_by: task for task in self._config.report_tasks}
        for mode, widgets in self._task_widgets.items():
            task = tasks.get(mode, filters)
            widgets["enabled"].setChecked(mode in tasks if tasks else mode == filters.filter_by or filters.filter_by == "both" and mode in ("accounts", "total"))
            widgets["threshold"].setValue(getattr(task, {"likes": "min_likes", "total": "min_occurrences", "accounts": "min_accounts"}[mode]))
            widgets["days"].setValue(task.days)
            widgets["start"].setText(task.start_date)
            widgets["end"].setText(task.end_date)
            _select(widgets["preset"], str(task.days) if task.time_mode == "days" and str(task.days) in dict(TIME_PRESETS) else task.time_mode)
    def _persist(self) -> bool:
        self._config = spider_service.SpiderConfig(
            accounts=tuple(self._rows), filters=self._collect_filters(), report_tasks=self._collect_report_tasks()
        )
        try:
            self._store.save(self._config)
            return True
        except OSError as error:
            self._set_result_caption(f"配置保存失败：{error}", warn=True)
            return False

    # ────────────────────────────── 抓取 ──────────────────────────────

    def _start_crawl(self) -> None:
        if self._running:
            return
        lease = CrawlRunLease()
        if not lease.acquire():
            self._set_result_caption(RUN_BUSY_MESSAGE, warn=True)
            return
        lease.close()
        if not self._persist():
            return
        if not self._config.report_tasks:
            self._set_result_caption("请至少启用一个筛选报表任务。", warn=True)
            return
        if not self._config.enabled_accounts:
            self._set_result_caption("请先添加并启用至少一个对标账号。", warn=True)
            return

        # 日期范围在本地先校验：抓取要开浏览器翻页，不该为格式错误白等一轮。
        for task in self._config.report_tasks or (self._config.filters,):
            date_issue = spider_service.validate_date_filters(task)
            if date_issue:
                self._set_result_caption(date_issue, warn=True)
                return

        # 关键：必须先释放登录浏览器。登录与抓取共用同一个 Chromium profile 目录，
        # 而 Chromium 对 profile 加独占锁；两个实例同时用它会导致启动失败
        # （实测表现为 python.exe 应用程序错误 0xc0000142，直接崩掉）。
        released_login = False
        if self._login_session is not None:
            self._login_session.close()
            self._login_session = None
            self._login_done.setEnabled(False)
            self._refresh_login_status()
            released_login = True

        # 除了本程序自己的登录窗口，还可能有**其它**浏览器占着同一档案
        # （用户手动开着、或上一个实例崩溃残留）。此时不要白启动一轮抓取：
        # 爬虫预检会以 profile_locked 阻断，用户只会看到「环境检查未通过」。
        # 这里提前拦住并说清是哪个进程。
        lock_state = spider_service.profile_lock_state()
        if lock_state.busy:
            answer = QMessageBox.question(
                self,
                "浏览器档案被占用",
                f"{lock_state.message}\n\n"
                "是否关闭所有使用此选品登录档案的 Chrome/Edge 窗口并继续抓取？"
                "未保存的网页状态可能丢失。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._set_result_caption(lock_state.message, warn=True)
                self._refresh_login_status()
                return

            try:
                spider_service.terminate_profile_holders()
            except Exception as error:  # noqa: BLE001 - 关闭失败要留在界面提示，不能崩 UI
                self._set_result_caption(f"关闭占用浏览器失败：{error}", warn=True)
                return
            lock_state = spider_service.profile_lock_state()
            self._refresh_login_status()
            if lock_state.busy:
                self._set_result_caption(
                    f"仍有进程无法关闭：{lock_state.message}请手动关闭后重试。",
                    warn=True,
                )
                return
            released_login = True

        self._running = True
        self._cancel.clear()
        self._run_button.setEnabled(False)
        self._cancel_button.setEnabled(True)
        self._send_button.setEnabled(False)
        self._log.clear()
        # 用显式标志而不是读回界面文案来决定提示语：文案一改，逻辑就会悄悄失效。
        if released_login:
            self._set_result_caption("已释放浏览器档案，开始抓取…")
        else:
            self._set_result_caption("正在抓取…（首次会打开浏览器，可能需要扫码登录）")
        config = self._config

        def work() -> None:
            try:
                result = self._runner.run(config, on_log=self._emit_log, cancel_event=self._cancel)
            except Exception as error:
                result = spider_service.SpiderRunResult(success=False, message=f"选品数据处理失败（{type(error).__name__}），请查看运行日志并重试。")
            try:
                if not self._disposed:
                    self._bridge.finished.emit(result)
                else:
                    self._running = False
            except RuntimeError:
                self._running = False

        threading.Thread(target=work, name="jingxu-spider-run", daemon=True).start()

    def _emit_log(self, line: str) -> None:
        """后台线程调用：经信号排队到 UI 线程再写控件。"""
        if not self._disposed:
            try:
                self._bridge.log.emit(line)
            except RuntimeError:
                return

    def _append_log(self, line: str) -> None:
        if not self._disposed:
            self._log.appendPlainText(line)

    def _cancel_crawl(self) -> None:
        if not self._running:
            return
        self._cancel.set()
        self._set_result_caption("正在取消…")

    def _on_run_finished(self, result: spider_service.SpiderRunResult) -> None:
        self._running = False
        if self._disposed:
            return
        self._run_button.setEnabled(True)
        self._cancel_button.setEnabled(False)
        self._last_result = result
        self._apply_account_resolutions(result)

        # 诊断优先：环境异常/登录失效/提取不到商品都比「抓取完成」更重要，
        # 必须让用户第一眼看到原因与建议，而不是自己从日志里找。
        diagnostics = result.diagnostics
        if diagnostics is not None and diagnostics.issues:
            self._set_result_caption(
                "\n".join(diagnostics.lines()), warn=diagnostics.blocked or not result.success
            )
        elif not result.crawl_complete:
            self._set_result_caption(result.message, warn=True)
        elif result.success and result.items and not result.retained:
            self._set_result_caption(
                f"抓取完成：发现 {len(result.items)} 条带货记录，没有符合当前筛选条件的商品。"
                "可调整保留门槛后重新抓取；原始记录保留在报表明细中。"
            )
        elif result.success and not result.has_payload and not result.message.startswith("抓取失败"):
            hint = (
                "抓取完成，但没有发现有带货商品的视频。常见原因："
                "① 这些账号近期视频没挂商品；② 时间范围太窄（当前 "
                f"{spider_service.probe_time_filter(self._config.filters)}）；"
                "③ 平台页面结构变化导致解析不到。建议放宽时间范围后重试。"
            )
            self._set_result_caption(hint, warn=True)
        else:
            self._set_result_caption(result.message, warn=not result.success)

        self._fill_results(result)
        self._send_button.setEnabled(bool(self._selected_urls()))
        if result.has_payload:
            try:
                self._store.save_result(result)
            except OSError as error:
                self._set_result_caption(f"结果保存失败：{error}", warn=True)
        self._refresh_export_label(result)
        # 诊断统计写在最后：_refresh_export_label 会先重置该标签。
        if diagnostics is not None and diagnostics.videos_scanned:
            self._export_label.setText(
                f"扫描 {diagnostics.videos_scanned} 个视频 · 含商品 "
                f"{diagnostics.videos_with_products} 个"
            )

    def _apply_account_resolutions(self, result: spider_service.SpiderRunResult) -> None:
        """保存抓取中确认的真实身份，合并不同分享短链指向的同一账号。"""
        if not result.accounts:
            return
        resolved = {
            (str(item.get("platform") or ""), str(item.get("url_or_id") or "")): item
            for item in result.accounts
        }
        merged = {}
        for account in self._rows:
            item = resolved.get((account.platform, account.url_or_id))
            if item:
                identity = str((item.get("sec_uid") if account.platform == "douyin" else item.get("user_id")) or "")
                if identity:
                    account = replace(account, resolved_id=identity, name=account.name or str(item.get("name") or ""))
                    account = replace(account, url_or_id=account.canonical_target)
            key = spider_service.account_identity_key(account)
            if key in merged:
                previous = merged[key]
                merged[key] = replace(previous, enabled=previous.enabled or account.enabled)
            else:
                merged[key] = account
        updated = list(merged.values())
        if updated != self._rows:
            self._rows = updated
            self._persist()
            self._refresh_accounts()

    def _restore_last_result(self) -> None:
        """恢复上次抓取结果：抓取耗时以分钟计，关掉应用不该丢。"""
        try:
            result = self._store.load_result()
        except OSError:
            return
        if result is None:
            return
        self._last_result = result
        when = result.finished_at_display
        prefix = f"上次抓取（{when}）：" if when else "上次抓取："
        self._set_result_caption(f"{prefix}{result.message}")
        self._fill_results(result)
        self._send_button.setEnabled(bool(self._selected_urls()))
        self._refresh_export_label(result)

    def _refresh_export_label(self, result: spider_service.SpiderRunResult) -> None:
        if result.excel_path:
            self._export_label.setText(f"报表：{Path(result.excel_path).name}")
        else:
            self._export_label.setText("")

    def _fill_results(self, result: spider_service.SpiderRunResult) -> None:
        """填充结果表，只显示符合筛选条件的商品。"""
        self._result_report.blockSignals(True)
        selected = self._result_report.currentData()
        self._result_report.clear()
        if result.reports:
            for index, report in enumerate(result.reports):
                self._result_report.addItem(str(report.get("name") or "筛选报表"), index)
            match = self._result_report.findData(selected)
            self._result_report.setCurrentIndex(max(0, match))
        else:
            self._result_report.addItem("当前筛选结果", "")
        self._result_report.blockSignals(False)
        if result.reports:
            report = result.reports[int(self._result_report.currentData() or 0)]
            entries = tuple((True, entry) for entry in spider_service._dict_records(report.get("retained_products")))
            mode = str(report.get("filter_by") or "accounts")
        else:
            entries = result.effective_entries
            mode = self._config.filters.filter_by
        self._results_table.setColumnHidden(5, mode not in ("accounts", "both"))
        self._results_table.setColumnHidden(6, mode not in ("total", "both"))
        platform = str(self._result_platform.currentData() or "")
        if platform:
            entries = tuple((retained, entry) for retained, entry in entries if str(entry.get("涉及平台") or entry.get("platform") or "") == platform)
        self._result_entries = [entry for _, entry in entries]
        self._openable_cells.clear()

        previous = self._updating
        self._updating = True
        self._results_table.setSortingEnabled(False)
        try:
            self._results_table.setRowCount(len(entries))
            for row, (is_retained, entry) in enumerate(entries):
                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                )
                check.setCheckState(Qt.CheckState.Checked)
                check.setData(Qt.ItemDataRole.UserRole, entry)
                check.setToolTip("保留商品" if is_retained else "未达保留门槛的带货记录")
                self._results_table.setItem(row, RESULT_CHECK_COLUMN, check)
                self._results_table.setRowHeight(row, 32)

                for offset, value in enumerate(_entry_columns(entry), start=1):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    if offset in (RESULT_LIKES_COLUMN, 5, 6):
                        try:
                            num = int(str(value).replace(",", ""))
                            if 0 <= num <= 9_007_199_254_740_991:
                                item.setData(Qt.ItemDataRole.EditRole, num)
                        except (ValueError, TypeError, OverflowError):
                            pass
                    if offset in LINK_COLUMNS and _is_openable_url(value):
                        # 可点开的链接给出手型光标与下划线提示，否则用户不知道能双击。
                        item.setForeground(QColor(theme.BRAND_PRIMARY))
                        item.setToolTip(f"{value}\n双击或右键可直接打开")
                        font = item.font()
                        font.setUnderline(True)
                        item.setFont(font)
                        self._openable_cells.add((row, offset))
                    self._results_table.setItem(row, offset, item)
                    if offset == RESULT_IMAGE_COLUMN and _is_openable_url(value):
                        item.setData(Qt.ItemDataRole.UserRole, value)
                        item.setText("加载主图…")
                        self._request_cover(value)
        finally:
            self._results_table.setSortingEnabled(True)
            self._updating = previous
        if result.reports:
            metric = {"likes": RESULT_LIKES_COLUMN, "total": 6, "accounts": 5, "both": 5}.get(mode, 5)
            self._results_table.sortItems(metric, Qt.SortOrder.DescendingOrder)

        self._updating = True
        try:
            self._select_all.setCheckState(Qt.CheckState.Checked)
        finally:
            self._updating = previous
        self._refresh_selection_caption()

    def _request_cover(self, url: str) -> None:
        if url in self._cover_cache:
            self._on_cover_ready(url, self._cover_cache[url])
            return
        if url in self._pending_covers or self._disposed:
            return
        if not self.isVisible():
            self._deferred_covers.add(url)
            return
        self._pending_covers.add(url)
        future = self._cover_pool.submit(spider_service.fetch_product_cover, url)

        def ready(done):
            try:
                data = done.result()
            except Exception:
                data = b""
            try:
                if not self._disposed:
                    self._bridge.cover_ready.emit(url, data)
            except RuntimeError:
                pass
        future.add_done_callback(ready)

    def _on_cover_ready(self, url: str, data: bytes) -> None:
        if self._disposed:
            return
        self._pending_covers.discard(url)
        self._deferred_covers.discard(url)
        self._cover_cache[url] = data
        if len(self._cover_cache) > 256:
            self._cover_cache.pop(next(iter(self._cover_cache)))
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        pixmap = QPixmap.fromImage(reader.read()) if size.width() > 0 and size.width() * size.height() <= 20_000_000 else QPixmap()
        sorting = self._results_table.isSortingEnabled()
        self._results_table.setSortingEnabled(False)
        try:
            for row in range(self._results_table.rowCount()):
                item = self._results_table.item(row, RESULT_IMAGE_COLUMN)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == url:
                    item.setText("查看" if not pixmap.isNull() else "打开主图链接")
                    if not pixmap.isNull():
                        item.setIcon(QIcon(pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
                        self._results_table.setIconSize(QSize(64, 64))
                        self._results_table.setRowHeight(row, 72)
        finally:
            self._results_table.setSortingEnabled(sorting)

    def _on_result_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != RESULT_CHECK_COLUMN:
            return
        self._sync_select_all_state()
        self._refresh_selection_caption()

    # ── 打开链接（对齐 .NET OpenSelectedSampleVideo / OpenSelectedVideo） ──────

    def _on_result_cell_double_clicked(self, row: int, column: int) -> None:
        self._open_result_link(row, column)

    def _on_result_context_menu(self, position) -> None:  # noqa: ANN001 - QPoint
        """右键菜单：打开链接 / 复制链接。"""
        index = self._results_table.indexAt(position)
        if not index.isValid():
            return
        row, column = index.row(), index.column()
        url = self._cell_url(row, column)
        if not url:
            return

        menu = QMenu(self._results_table)
        open_action = menu.addAction("打开链接")
        copy_action = menu.addAction("复制链接")
        chosen = menu.exec(self._results_table.viewport().mapToGlobal(position))
        if chosen is open_action:
            self._open_result_link(row, column)
        elif chosen is copy_action:
            QGuiApplication.clipboard().setText(url)
            self._set_result_caption("链接已复制到剪贴板。")

    def _cell_url(self, row: int, column: int) -> str:
        """取某单元格里可打开的 URL；不可打开时返回空串。"""
        if column not in LINK_COLUMNS:
            return ""
        item = self._results_table.item(row, column)
        if item is None:
            return ""
        text = str(item.data(Qt.ItemDataRole.UserRole) or "") if column == RESULT_IMAGE_COLUMN else item.text().strip()
        return text if _is_openable_url(text) else ""

    def _open_result_link(self, row: int, column: int) -> None:
        url = self._cell_url(row, column)
        if not url:
            self._set_result_caption("该行没有可打开的链接。", warn=True)
            return
        QDesktopServices.openUrl(QUrl(url))

    def _selected_entries(self) -> list[dict]:
        """返回结果表中被勾选的原始条目。"""
        selected: list[dict] = []
        for row in range(self._results_table.rowCount()):
            check = self._results_table.item(row, RESULT_CHECK_COLUMN)
            if check is None or check.checkState() != Qt.CheckState.Checked:
                continue
            entry = check.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, dict):
                selected.append(entry)
            elif 0 <= row < len(self._result_entries):
                selected.append(self._result_entries[row])
        return selected

    def _checked_row_count(self) -> int:
        return sum(
            1
            for row in range(self._results_table.rowCount())
            if (item := self._results_table.item(row, RESULT_CHECK_COLUMN)) is not None
            and item.checkState() == Qt.CheckState.Checked
        )

    def _sync_select_all_state(self) -> None:
        """按行勾选情况回写全选框（全选 / 部分 / 全不选）。"""
        total = self._results_table.rowCount()
        checked = self._checked_row_count()
        previous = self._updating
        self._updating = True
        try:
            if total == 0 or checked == 0:
                self._select_all.setCheckState(Qt.CheckState.Unchecked)
            elif checked == total:
                self._select_all.setCheckState(Qt.CheckState.Checked)
            else:
                self._select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        finally:
            self._updating = previous

    def _on_select_all_clicked(self, checked: bool) -> None:
        """点击全选：全部勾选或全部取消。

        用 ``clicked`` 而不是 ``stateChanged``：三态下用户点击部分选中状态时，
        语义是「全选」，而 stateChanged 无法区分点击与程序回写。
        """
        if self._updating:
            return
        target = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        previous = self._updating
        self._updating = True
        try:
            for row in range(self._results_table.rowCount()):
                item = self._results_table.item(row, RESULT_CHECK_COLUMN)
                if item is not None:
                    item.setCheckState(target)
        finally:
            self._updating = previous
        self._sync_select_all_state()
        self._refresh_selection_caption()

    def _refresh_selection_caption(self) -> None:
        total = self._results_table.rowCount()
        if total == 0:
            self._selection_caption.setText("")
            self._send_button.setEnabled(False)
            return
        picked = len(self._selected_entries())
        urls = self._selected_urls()
        self._selection_caption.setText(f"已选 {picked}/{total} 款，可送出 {len(urls)} 个链接。")
        self._send_button.setEnabled(bool(urls) and not self._running)

    def _selected_urls(self) -> tuple[str, ...]:
        if self._last_result is None:
            return ()
        return self._last_result.urls_for_entries(self._selected_entries())

    def _send_last_result(self) -> None:
        urls = list(self._selected_urls())
        if not urls:
            hint = (
                "还没有可送入下载的视频链接。"
                if self._last_result is None
                else "请先在结果表中勾选要下载的商品。"
            )
            self._set_result_caption(hint, warn=True)
            return
        self.videos_discovered.emit(urls)
        self._set_result_caption(f"已送入下载 {len(urls)} 个链接。")

    def _open_exports_directory(self) -> None:
        directory = spider_service.exports_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._set_result_caption(f"无法创建报表目录：{error}", warn=True)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _toggle_log(self) -> None:
        """切换日志显示。

        用 ``isHidden()`` 而不是 ``isVisible()`` 判断当前状态：父级尚未显示
        （例如页面还没被切到前台）时 ``isVisible()`` 恒为 False，会导致永远
        走「显示」分支、开关失效。
        """
        visible = self._log.isHidden()
        self._log.setVisible(visible)
        self._log_toggle.setText("隐藏运行日志" if visible else "📋 运行日志")

    def _set_result_caption(self, text: str, *, warn: bool = False) -> None:
        self._result_caption.setText(text)
        self._result_caption.setObjectName("CaptionWarn" if warn else "Caption")
        self._result_caption.style().unpolish(self._result_caption)
        self._result_caption.style().polish(self._result_caption)

    def shutdown(self) -> None:
        """应用退出时清理资源。

        不做这步的话，关掉应用后扫码登录的浏览器窗口与正在跑的抓取进程会
        残留在后台。
        """
        self._disposed = True
        if hasattr(self, "_schedule_timer"):
            self._schedule_timer.stop()
        self._cover_pool.shutdown(wait=False, cancel_futures=True)
        if self._login_session is not None:
            try:
                self._login_session.close()
            except Exception:  # noqa: BLE001 - 退出路径不应抛异常
                pass
            self._login_session = None
        if self._running:
            self._cancel.set()

    def showEvent(self, event) -> None:  # noqa: ANN001 - QShowEvent
        super().showEvent(event)
        urls = tuple(self._deferred_covers)
        self._deferred_covers.clear()
        for url in urls:
            self._request_cover(url)

    def closeEvent(self, event) -> None:  # noqa: ANN001 - QCloseEvent
        self.shutdown()
        super().closeEvent(event)

    # ────────────────────────────── 测试辅助 ──────────────────────────────

    @property
    def accounts(self) -> list[spider_service.SpiderAccount]:
        return list(self._rows)

    @property
    def last_result(self) -> spider_service.SpiderRunResult | None:
        return self._last_result

    @property
    def is_running(self) -> bool:
        return self._running


def _combo(options: list[tuple[str, str]]):  # noqa: ANN201 - QComboBox
    from PySide6.QtWidgets import QComboBox

    combo = QComboBox()
    for value, label in options:
        combo.addItem(label, value)
    return combo


def _is_openable_url(value: object) -> bool:
    """是否是可直接打开的 http(s) 链接（破折号占位、空值都不算）。"""
    text = str(value).strip()
    return text.startswith(("http://", "https://")) and len(text) > len("https://")


def _entry_columns(entry: dict) -> tuple[str, ...]:
    """把一条结果条目映射为结果表的各列文本（不含首列勾选）。

    字段名在不同来源里不一致（爬虫 ``to_summary_dict`` 用中文键，中间层可能给
    camelCase 或 snake_case），因此每列给一组候选键并逐级兜底；列表型的
    「对标账号明细」拼成顿号分隔。缺失值显示为破折号，便于分辨"没有"与"取不到"。
    """
    values: list[str] = []
    for keys in _RESULT_FIELD_KEYS:
        raw: object = None
        for key in keys:
            candidate = entry.get(key)
            if candidate not in (None, "", [], ()):
                raw = candidate
                break
        if isinstance(raw, (list, tuple)):
            text = "、".join(str(item).strip() for item in raw if str(item).strip())
        else:
            text = str(raw).strip() if raw is not None else ""
        values.append(text or "—")
    return tuple(values)


def _select(combo, value: str) -> None:  # noqa: ANN001 - QComboBox
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)
