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
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
    "跨账号数",
    "出现次数",
    "对标账号明细",
    "价格区间",
    "示例视频链接",
)
RESULT_COLUMN_WIDTHS = (40, 260, 200, 70, 90, 90, 220, 120, 240)
RESULT_CHECK_COLUMN = 0
RESULT_NAME_COLUMN = 1

# 每一列取哪个字段。键名在不同来源里不一致（爬虫 `to_summary_dict` 用中文键，
# 中间层可能给 camelCase 或 snake_case），因此每列给一组候选键，按序兜底。
_RESULT_FIELD_KEYS: tuple[tuple[str, ...], ...] = (
    ("商品名称", "product_name", "productName", "name"),
    ("清洗名称", "cleaned_name", "cleanedName"),
    ("涉及平台", "platform"),
    ("带货账号数", "account_count", "accountCount"),
    ("带货视频数", "video_count", "videoCount", "total_occurrences", "totalOccurrences"),
    ("对标账号明细", "accounts", "account_names", "influencers"),
    ("参考价格", "price_range", "priceRange"),
    ("示例视频链接", "sample_video_url", "sampleVideoUrl", "video_url", "videoUrl"),
)


class SpiderBridge(QObject):
    """把后台抓取的日志与结果切回 UI 线程。"""

    log = Signal(str)
    finished = Signal(object)


def extract_video_urls(items: list) -> list[str]:
    """从爬虫结果条目中提取视频链接（去重、保序）。

    保留此函数以兼容既有调用点；新代码请用 ``SpiderRunResult.video_urls``。
    """
    return list(
        spider_service.SpiderRunResult(success=True, message="", items=tuple(items)).video_urls
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
    ) -> None:
        super().__init__()

        self._store = store or spider_service.SpiderConfigStore()
        self._runner = runner or spider_service.SpiderRunner()
        self._check_environment = check_environment or spider_service.check_environment
        self._config = self._store.load()
        self._rows: list[spider_service.SpiderAccount] = []
        self._result_entries: list[dict] = []
        self._running = False
        self._cancel = threading.Event()
        self._last_result: spider_service.SpiderRunResult | None = None
        self._login_session: spider_service.SpiderLoginSession | None = None
        self._updating = False

        self._bridge = SpiderBridge(self)
        self._bridge.finished.connect(self._on_run_finished)
        self._bridge.log.connect(self._append_log)

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
        layout.addWidget(SectionHeader("抓取范围与保留门槛"))
        layout.addSpacing(6)
        layout.addLayout(self._build_filter_rows())

        layout.addSpacing(10)
        layout.addLayout(self._build_action_row())
        layout.addSpacing(4)
        layout.addLayout(self._build_login_row())

        layout.addSpacing(10)
        self._result_caption = Caption("尚未抓取。")
        layout.addWidget(self._result_caption)
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
        self._account_input.setPlaceholderText("主页链接 / 分享短链 / Sec-UID")
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

        if any(
            existing.platform == account.platform and existing.url_or_id == account.url_or_id
            for existing in self._rows
        ):
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

        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        time_row.addWidget(Caption("时间范围（遇到超期视频自动早停）"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._time_mode = _combo(
            [(value, label) for value, label in spider_service.TIME_MODES]
        )
        self._time_mode.currentIndexChanged.connect(self._on_time_mode_changed)
        time_row.addWidget(self._time_mode)

        self._days = QSpinBox()
        self._days.setRange(1, 365)
        self._days.setSuffix(" 天")
        time_row.addWidget(self._days)

        self._start_date = QLineEdit()
        self._start_date.setPlaceholderText("起始 YYYY-MM-DD")
        self._start_date.setFixedWidth(126)
        time_row.addWidget(self._start_date)
        self._end_date = QLineEdit()
        self._end_date.setPlaceholderText("结束 YYYY-MM-DD")
        self._end_date.setFixedWidth(126)
        time_row.addWidget(self._end_date)
        time_row.addStretch(1)
        column.addLayout(time_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(Caption("保留准则"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._filter_by = _combo([(value, label) for value, label in spider_service.FILTER_MODES])
        filter_row.addWidget(self._filter_by)

        filter_row.addWidget(Caption("共同带货账号数 ≥ N（共性爆品核心）"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._min_accounts = QSpinBox()
        self._min_accounts.setRange(1, 50)
        filter_row.addWidget(self._min_accounts)

        filter_row.addWidget(Caption("累计带货频次 ≥ M"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._min_occurrences = QSpinBox()
        self._min_occurrences.setRange(1, 200)
        filter_row.addWidget(self._min_occurrences)
        filter_row.addStretch(1)
        column.addLayout(filter_row)

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
        return column

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._run_button = PrimaryButton("开始抓取")
        self._run_button.setToolTip("将打开浏览器读取对标账号的带货视频，可随时取消。")
        self._run_button.clicked.connect(self._start_crawl)
        row.addWidget(self._run_button)

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

    def _open_login(self, platform: str) -> None:
        if self._login_session is not None and self._login_session.is_running():
            self._set_result_caption(
                f"{self._login_session.platform_label}登录窗口已打开，"
                "请扫码完成后点「我已登录」。"
            )
            return
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
        self._login_session.close()
        self._login_session = None
        self._login_done.setEnabled(False)
        self._refresh_login_status()
        self._set_result_caption(f"{label}登录态已保存，可以开始抓取了。")

    def _build_results_table(self) -> QWidget:
        self._results_table = QTableWidget(0, len(RESULT_COLUMNS))
        self._results_table.setHorizontalHeaderLabels(list(RESULT_COLUMNS))
        self._results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setFixedHeight(150)
        header = self._results_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate(RESULT_COLUMN_WIDTHS):
            self._results_table.setColumnWidth(column, width)
        self._results_table.setMinimumWidth(sum(RESULT_COLUMN_WIDTHS) + 24)
        self._results_table.itemChanged.connect(self._on_result_item_changed)
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
        self._log_toggle = SecondaryButton("📋 运行日志")
        self._log_toggle.clicked.connect(self._toggle_log)
        layout.addWidget(self._log_toggle)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(110)
        self._log.setFont(theme.mono_font(11))
        self._log.setVisible(False)
        layout.addWidget(self._log)
        return box

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
        self._rows[row] = spider_service.SpiderAccount(
            platform=self._rows[row].platform,
            url_or_id=self._rows[row].url_or_id,
            name=self._rows[row].name,
            enabled=item.checkState() == Qt.CheckState.Checked,
        )
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
        existing = {(account.platform, account.url_or_id) for account in self._rows}
        added = 0
        for account in parsed:
            key = (account.platform, account.url_or_id)
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
        return spider_service.SpiderFilters(
            time_mode=str(self._time_mode.currentData() or "days"),
            days=int(self._days.value()),
            start_date=self._start_date.text().strip(),
            end_date=self._end_date.text().strip(),
            min_accounts=int(self._min_accounts.value()),
            min_occurrences=int(self._min_occurrences.value()),
            filter_by=str(self._filter_by.currentData() or "accounts"),
            enable_fuzzy=self._enable_fuzzy.isChecked(),
            fuzzy_threshold=float(self._fuzzy_threshold.value()),
            max_scrolls=int(self._max_scrolls.value()),
            headless=self._headless.isChecked(),
        )

    def _apply_config_to_form(self) -> None:
        filters = self._config.filters
        _select(self._time_mode, filters.time_mode)
        _select(self._filter_by, filters.filter_by)
        self._days.setValue(filters.days)
        self._start_date.setText(filters.start_date)
        self._end_date.setText(filters.end_date)
        self._min_accounts.setValue(filters.min_accounts)
        self._min_occurrences.setValue(filters.min_occurrences)
        self._enable_fuzzy.setChecked(filters.enable_fuzzy)
        self._fuzzy_threshold.setValue(filters.fuzzy_threshold)
        self._max_scrolls.setValue(filters.max_scrolls)
        self._headless.setChecked(filters.headless)
        self._rows = list(self._config.accounts)
        self._on_time_mode_changed()

    def _on_time_mode_changed(self) -> None:
        mode = str(self._time_mode.currentData() or "days")
        self._days.setEnabled(mode == "days")
        self._start_date.setEnabled(mode == "range")
        self._end_date.setEnabled(mode == "range")

    def _persist(self) -> None:
        self._config = spider_service.SpiderConfig(
            accounts=tuple(self._rows), filters=self._collect_filters()
        )
        try:
            self._store.save(self._config)
        except OSError as error:
            self._set_result_caption(f"配置保存失败：{error}", warn=True)

    # ────────────────────────────── 抓取 ──────────────────────────────

    def _start_crawl(self) -> None:
        if self._running:
            return
        self._persist()
        if not self._config.enabled_accounts:
            self._set_result_caption("请先添加并启用至少一个对标账号。", warn=True)
            return

        # 日期范围在本地先校验：抓取要开浏览器翻页，不该为格式错误白等一轮。
        date_issue = spider_service.validate_date_filters(self._config.filters)
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
            self._set_result_caption(lock_state.message, warn=True)
            self._refresh_login_status()
            return

        self._running = True
        self._cancel.clear()
        self._run_button.setEnabled(False)
        self._cancel_button.setEnabled(True)
        self._send_button.setEnabled(False)
        self._log.clear()
        # 用显式标志而不是读回界面文案来决定提示语：文案一改，逻辑就会悄悄失效。
        if released_login:
            self._set_result_caption("已关闭登录浏览器以释放档案，开始抓取…")
        else:
            self._set_result_caption("正在抓取…（首次会打开浏览器，可能需要扫码登录）")
        config = self._config

        def work() -> None:
            result = self._runner.run(
                config, on_log=self._emit_log, cancel_event=self._cancel
            )
            self._bridge.finished.emit(result)

        threading.Thread(target=work, name="jingxu-spider-run", daemon=True).start()

    def _emit_log(self, line: str) -> None:
        """后台线程调用：经信号排队到 UI 线程再写控件。"""
        self._bridge.log.emit(line)

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)

    def _cancel_crawl(self) -> None:
        if not self._running:
            return
        self._cancel.set()
        self._set_result_caption("正在取消…")

    def _on_run_finished(self, result: spider_service.SpiderRunResult) -> None:
        self._running = False
        self._run_button.setEnabled(True)
        self._cancel_button.setEnabled(False)
        self._last_result = result

        # 诊断优先：环境异常/登录失效/提取不到商品都比「抓取完成」更重要，
        # 必须让用户第一眼看到原因与建议，而不是自己从日志里找。
        diagnostics = result.diagnostics
        if diagnostics is not None and diagnostics.issues:
            self._set_result_caption(
                "\n".join(diagnostics.lines()), warn=diagnostics.blocked or not result.success
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
        self._send_button.setEnabled(bool(result.video_urls))
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
        self._send_button.setEnabled(bool(result.video_urls))
        self._refresh_export_label(result)

    def _refresh_export_label(self, result: spider_service.SpiderRunResult) -> None:
        if result.excel_path:
            self._export_label.setText(f"报表：{Path(result.excel_path).name}")
        else:
            self._export_label.setText("")

    def _fill_results(self, result: spider_service.SpiderRunResult) -> None:
        """填充结果表。条目来源见 ``effective_entries``（保留商品优先）。"""
        entries = result.effective_entries
        self._result_entries = [entry for _, entry in entries]

        previous = self._updating
        self._updating = True
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
                check.setToolTip("保留商品" if is_retained else "未达保留门槛的带货记录")
                self._results_table.setItem(row, RESULT_CHECK_COLUMN, check)

                for offset, value in enumerate(_entry_columns(entry), start=1):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self._results_table.setItem(row, offset, item)
        finally:
            self._updating = previous

        self._updating = True
        try:
            self._select_all.setCheckState(Qt.CheckState.Checked)
        finally:
            self._updating = previous
        self._refresh_selection_caption()

    def _on_result_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != RESULT_CHECK_COLUMN:
            return
        self._sync_select_all_state()
        self._refresh_selection_caption()

    def _selected_entries(self) -> list[dict]:
        """返回结果表中被勾选的原始条目。"""
        selected: list[dict] = []
        for row in range(self._results_table.rowCount()):
            check = self._results_table.item(row, RESULT_CHECK_COLUMN)
            if check is None or check.checkState() != Qt.CheckState.Checked:
                continue
            if 0 <= row < len(self._result_entries):
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
            return
        picked = len(self._selected_entries())
        urls = self._selected_urls()
        self._selection_caption.setText(f"已选 {picked}/{total} 款，可送出 {len(urls)} 个链接。")

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
        if self._login_session is not None:
            try:
                self._login_session.close()
            except Exception:  # noqa: BLE001 - 退出路径不应抛异常
                pass
            self._login_session = None
        if self._running:
            self._cancel.set()

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
