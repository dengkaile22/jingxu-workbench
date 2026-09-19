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
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
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
RESULT_COLUMNS = ("商品", "跨账号数", "出现次数", "价格区间")
RESULT_COLUMN_WIDTHS = (360, 96, 96, 120)


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
        self._running = False
        self._cancel = threading.Event()
        self._last_result: spider_service.SpiderRunResult | None = None
        self._updating = False

        self._bridge = SpiderBridge(self)
        self._bridge.finished.connect(self._on_run_finished)
        self._bridge.log.connect(self._append_log)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        layout.addLayout(self._build_header())
        layout.addSpacing(10)

        layout.addLayout(self._build_accounts_header())
        layout.addSpacing(6)
        layout.addWidget(self._build_accounts_table())

        self._import_toggle = SecondaryButton("批量粘贴导入")
        self._import_toggle.clicked.connect(self._toggle_import)
        import_row = QHBoxLayout()
        import_row.setSpacing(8)
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

        layout.addSpacing(10)
        self._result_caption = Caption("尚未抓取。")
        layout.addWidget(self._result_caption)
        layout.addSpacing(6)
        layout.addWidget(self._build_results_table())
        layout.addSpacing(6)
        layout.addWidget(self._build_log_box())

        self._apply_config_to_form()
        self._refresh_accounts()
        self._refresh_environment()

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

    def _build_accounts_table(self) -> QWidget:
        self._accounts_table = QTableWidget(0, len(ACCOUNT_COLUMNS))
        self._accounts_table.setHorizontalHeaderLabels(list(ACCOUNT_COLUMNS))
        self._accounts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._accounts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._accounts_table.verticalHeader().setVisible(False)
        self._accounts_table.setFixedHeight(150)
        header = self._accounts_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate(ACCOUNT_COLUMN_WIDTHS):
            self._accounts_table.setColumnWidth(column, width)
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
        time_row.addWidget(Caption("时间范围"), alignment=Qt.AlignmentFlag.AlignVCenter)
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

        filter_row.addWidget(Caption("跨账号 ≥"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._min_accounts = QSpinBox()
        self._min_accounts.setRange(1, 50)
        filter_row.addWidget(self._min_accounts)

        filter_row.addWidget(Caption("总频次 ≥"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._min_occurrences = QSpinBox()
        self._min_occurrences.setRange(1, 200)
        filter_row.addWidget(self._min_occurrences)
        filter_row.addStretch(1)
        column.addLayout(filter_row)

        advanced_row = QHBoxLayout()
        advanced_row.setSpacing(8)
        self._enable_fuzzy = QCheckBox("相似款自动合并")
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
        self._send_button.setToolTip("把最近一次抓取到的视频链接加入上方下载队列。")
        self._send_button.clicked.connect(self._send_last_result)
        self._send_button.setEnabled(False)
        row.addWidget(self._send_button)

        self._export_label = Caption("")
        row.addWidget(self._export_label)
        row.addStretch(1)
        return row

    def _build_results_table(self) -> QWidget:
        self._results_table = QTableWidget(0, len(RESULT_COLUMNS))
        self._results_table.setHorizontalHeaderLabels(list(RESULT_COLUMNS))
        self._results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setFixedHeight(140)
        header = self._results_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate(RESULT_COLUMN_WIDTHS):
            self._results_table.setColumnWidth(column, width)
        return self._results_table

    def _build_log_box(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._log_toggle = SecondaryButton("显示运行日志")
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

        self._running = True
        self._cancel.clear()
        self._run_button.setEnabled(False)
        self._cancel_button.setEnabled(True)
        self._send_button.setEnabled(False)
        self._log.clear()
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
        self._set_result_caption(result.message, warn=not result.success)
        self._fill_results(result)
        self._send_button.setEnabled(bool(result.video_urls))
        if result.excel_path:
            self._export_label.setText(f"报表：{Path(result.excel_path).name}")
        else:
            self._export_label.setText("")

    def _fill_results(self, result: spider_service.SpiderRunResult) -> None:
        self._results_table.setRowCount(len(result.retained))
        for row, entry in enumerate(result.retained):
            name = str(entry.get("name") or entry.get("product_name") or entry.get("cleanedName") or "")
            values = (
                name or "—",
                entry.get("account_count") or entry.get("accountCount") or "—",
                entry.get("total_occurrences") or entry.get("totalOccurrences") or "—",
                entry.get("price_range") or entry.get("priceRange") or "—",
            )
            for column, value in enumerate(values):
                self._results_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _send_last_result(self) -> None:
        if self._last_result is None or not self._last_result.video_urls:
            self._set_result_caption("还没有可送入下载的视频链接。", warn=True)
            return
        urls = list(self._last_result.video_urls)
        self.videos_discovered.emit(urls)
        self._set_result_caption(f"已送入下载 {len(urls)} 个链接。")

    def _toggle_log(self) -> None:
        """切换日志显示。

        用 ``isHidden()`` 而不是 ``isVisible()`` 判断当前状态：父级尚未显示
        （例如页面还没被切到前台）时 ``isVisible()`` 恒为 False，会导致永远
        走「显示」分支、开关失效。
        """
        visible = self._log.isHidden()
        self._log.setVisible(visible)
        self._log_toggle.setText("隐藏运行日志" if visible else "显示运行日志")

    def _set_result_caption(self, text: str, *, warn: bool = False) -> None:
        self._result_caption.setText(text)
        self._result_caption.setObjectName("CaptionWarn" if warn else "Caption")
        self._result_caption.style().unpolish(self._result_caption)
        self._result_caption.style().polish(self._result_caption)

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


def _select(combo, value: str) -> None:  # noqa: ANN001 - QComboBox
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)
