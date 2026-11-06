"""批量下载页：链接解析、下载队列、发送到混剪素材。"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jingxu.infrastructure.downloader import (
    DownloadJob,
    DownloadQueue,
    DownloadState,
    default_download_directory,
    has_yt_dlp,
)
from jingxu.ui import theme
from jingxu.ui.widgets import (
    Caption,
    PrimaryButton,
    SecondaryButton,
    SectionHeader,
    chip_qss,
    status_chip,
)

URL_PATTERN = re.compile(r"https?://[^\s\"'<>）)】\]]+", re.IGNORECASE)
COLUMNS = ("任务", "文件名", "状态", "进度", "速度", "说明")
TASK_COLUMN = COLUMNS.index("任务")
FILENAME_COLUMN = COLUMNS.index("文件名")
STATUS_COLUMN = COLUMNS.index("状态")
PROGRESS_COLUMN = COLUMNS.index("进度")
SPEED_COLUMN = COLUMNS.index("速度")
MESSAGE_COLUMN = COLUMNS.index("说明")

STATE_COLORS = {
    DownloadState.PENDING: theme.INK_MUTED,
    DownloadState.RUNNING: theme.STATUS_RUNNING,
    DownloadState.COMPLETED: "#3F7A55",
    DownloadState.FAILED: theme.STATUS_FAILED,
    DownloadState.CANCELLED: theme.INK_MUTED,
}

# 状态胶囊底色：下载中与失败用浅色底强调，其余素色。
STATE_TINTS = {
    DownloadState.PENDING: "#F1F0EA",
    DownloadState.RUNNING: "#FBF1E3",
    DownloadState.COMPLETED: "#E9F3EC",
    DownloadState.FAILED: "#FAEAE7",
    DownloadState.CANCELLED: "#F1F0EA",
}


class StatusChipCell(QWidget):
    """状态列的胶囊单元格（浅底 + 彩色文字）。"""

    def __init__(self) -> None:
        super().__init__()
        self._state_key: tuple[str, str, str] | None = None
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 6, 0)
        row.setSpacing(0)
        self.chip = QLabel("")
        row.addWidget(self.chip)
        row.addStretch(1)

    def set_state(self, text: str, *, color: str, tint: str) -> None:
        key = (text, color, tint)
        if key == self._state_key:
            return
        self._state_key = key
        self.chip.setText(text)
        self.chip.setStyleSheet(chip_qss(color=color, tint=tint))


class ProgressCell(QWidget):
    """进度列的进度条 + 百分比文本。"""

    def __init__(self) -> None:
        super().__init__()
        self._color: str | None = None
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 8, 0)
        row.setSpacing(8)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        row.addWidget(self.bar, stretch=1)
        self.percent = QLabel("")
        self.percent.setObjectName("Mono")
        self.percent.setStyleSheet(f"color: {theme.INK_MUTED}; font-size: 11px;")
        self.percent.setMinimumWidth(40)
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.percent)

    def set_progress(self, *, percent: float, color: str, show_percent: bool) -> None:
        value = max(0.0, min(percent, 100.0))
        target = int(value)
        if self.bar.value() != target:
            self.bar.setValue(target)
        if self._color != color:
            self._color = color
            self.bar.setStyleSheet(
                f"QProgressBar {{ background: {theme.SURFACE_SUNK}; border: none; border-radius: 4px; }}"
                f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
            )
        text = f"{value:.0f}%" if show_percent else ""
        if self.percent.text() != text:
            self.percent.setText(text)


TERMINAL_STATES = (
    DownloadState.COMPLETED,
    DownloadState.FAILED,
    DownloadState.CANCELLED,
)


def _is_terminal(job) -> bool:  # noqa: ANN001 - DownloadJob
    """任务是否已结束（表里仍需显示，但「清空」时可移除）。"""
    return job.state in TERMINAL_STATES


def extract_urls(text: str) -> list[str]:
    """从多行文本中提取去重后的链接（保持出现顺序）。"""
    seen: set[str] = set()
    result: list[str] = []
    for match in URL_PATTERN.findall(text or ""):
        clean = match.rstrip(".,;，。；")
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


class DownloadBridge(QObject):
    event = Signal(str, object)


class DownloadPage(QWidget):
    """下载模块。"""

    files_downloaded = Signal(list)

    def __init__(self, queue: DownloadQueue) -> None:
        super().__init__()
        self._queue = queue
        self._rows: dict[str, int] = {}
        self._row_jobs: dict[int, str] = {}
        self._updating = False
        # 行级刷新缓存：变更签名与状态（跳过高频事件里的重复刷新）。
        self._row_signatures: dict[int, tuple] = {}
        self._row_state: dict[int, DownloadState] = {}
        self._last_counts: tuple[int, ...] | None = None
        self._pending_jobs: dict[str, DownloadJob] = {}
        self._jobs_timer = QTimer(self)
        self._jobs_timer.setSingleShot(True)
        self._jobs_timer.setInterval(60)
        self._jobs_timer.timeout.connect(self._flush_pending_jobs)

        bridge = DownloadBridge(self)
        bridge.event.connect(self._on_queue_event)
        self._bridge = bridge
        self._queue.add_listener(lambda event, job: self._bridge.event.emit(event, job))
        self._queue.set_concurrency(3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)
        layout.addLayout(self._build_header())
        layout.addSpacing(8)

        self._backend_hint = Caption(self._backend_text())
        layout.addWidget(self._backend_hint)

        layout.addSpacing(12)
        layout.addWidget(SectionHeader("链接"))
        layout.addSpacing(6)
        self._url_input = QPlainTextEdit()
        self._url_input.setPlaceholderText("每行一个视频链接（抖音 / 快手 / B 站等），也支持直接粘贴分享文案。")
        self._url_input.setFixedHeight(88)
        layout.addWidget(self._url_input)

        layout.addSpacing(8)
        layout.addLayout(self._build_directory_row())

        layout.addSpacing(12)
        layout.addLayout(self._build_actions_row())

        layout.addSpacing(10)
        layout.addLayout(self._build_overview())

        layout.addSpacing(6)
        self._empty_hint = Caption(
            "粘贴链接后点击「开始下载」，任务会按顺序出现在这里；等待中的任务可双击文件名修改。"
        )
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setContentsMargins(0, 18, 0, 18)
        layout.addWidget(self._empty_hint)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.SelectedClicked
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(36)
        self._table.setShowGrid(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 240)
        self._table.setColumnWidth(1, 220)
        self._table.setColumnWidth(STATUS_COLUMN, 96)
        self._table.setColumnWidth(PROGRESS_COLUMN, 200)
        self._table.setColumnWidth(4, 90)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, stretch=1)

        self._status = Caption("")
        self._status.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self._status)

        self._queue.set_output_directory(default_download_directory())
        self._queue.set_concurrency(3)
        self._directory_edit.setText(str(default_download_directory()))
        self._refresh_overview()

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel("批量下载")
        title.setObjectName("Title")
        row.addWidget(title)
        row.addStretch(1)
        return row

    def _build_directory_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(Caption("保存目录"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._directory_edit = QLineEdit()
        row.addWidget(self._directory_edit, stretch=1)

        browse = SecondaryButton("浏览…")
        browse.clicked.connect(self._choose_directory)
        row.addWidget(browse)

        open_button = SecondaryButton("打开")
        open_button.clicked.connect(self._open_directory)
        row.addWidget(open_button)
        return row

    def _build_actions_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._start = PrimaryButton("开始下载")
        self._start.clicked.connect(self._start_downloads)
        row.addWidget(self._start)

        cancel = SecondaryButton("取消全部")
        cancel.clicked.connect(self._queue.cancel_all)
        row.addWidget(cancel)

        clear = SecondaryButton("清空已完成")
        clear.clicked.connect(self._clear_finished)
        row.addWidget(clear)

        clear_all = SecondaryButton("清空列表")
        clear_all.setToolTip("取消所有下载并清空列表。")
        clear_all.clicked.connect(self._clear_all)
        row.addWidget(clear_all)

        send = SecondaryButton("发送已下载到混剪素材")
        send.setToolTip("把已完成的视频加入「商品组 A」素材列表，可直接编排渲染。")
        send.clicked.connect(self._send_to_materials)
        row.addWidget(send)

        row.addSpacing(6)
        self._auto_number_check = QCheckBox("按顺序自动编号（1.mp4, 2.mp4...）")
        self._auto_number_check.setChecked(True)
        self._auto_number_check.setToolTip("开启后按链接顺序自动命名为 1、2、3...，仍可在列表中双击修改。")
        row.addWidget(self._auto_number_check)

        row.addWidget(Caption("并发数:"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._concurrency_spin = QSpinBox()
        self._concurrency_spin.setRange(1, 8)
        self._concurrency_spin.setValue(self._queue.concurrency)
        self._concurrency_spin.setToolTip("同时下载的任务数量（1~8，推荐 2~4）。")
        self._concurrency_spin.valueChanged.connect(self._queue.set_concurrency)
        row.addWidget(self._concurrency_spin)

        row.addStretch(1)
        return row

    def _build_overview(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._counts = Caption("")
        row.addWidget(self._counts)
        self._count_chips: dict[str, QLabel] = {}
        self._count_labels: dict[str, str] = {}
        for key, label, color, tint in (
            ("pending", "等待中", theme.INK_MUTED, "#F1F0EA"),
            ("running", "下载中", theme.STATUS_RUNNING, "#FBF1E3"),
            ("completed", "已完成", "#3F7A55", "#E9F3EC"),
            ("failed", "失败", theme.STATUS_FAILED, "#FAEAE7"),
        ):
            chip = status_chip(label, color=color, tint=tint)
            chip.setVisible(False)
            self._count_chips[key] = chip
            self._count_labels[key] = label
            row.addWidget(chip)
        row.addStretch(1)
        return row

    def _refresh_overview(self) -> None:
        """更新计数胶囊与空状态提示（与任务表保持同步，内容不变则跳过）。"""
        jobs = self._queue.jobs
        counts = {
            "pending": sum(1 for job in jobs if job.state is DownloadState.PENDING),
            "running": sum(1 for job in jobs if job.state is DownloadState.RUNNING),
            "completed": sum(1 for job in jobs if job.state is DownloadState.COMPLETED),
            "failed": sum(1 for job in jobs if job.state is DownloadState.FAILED),
        }
        signature = (
            len(jobs),
            counts["pending"],
            counts["running"],
            counts["completed"],
            counts["failed"],
            self._table.rowCount(),
        )
        if signature == self._last_counts:
            return
        self._last_counts = signature

        self._counts.setText(f"共 {len(jobs)} 个任务" if jobs else "暂无下载任务")
        for key, count in counts.items():
            chip = self._count_chips[key]
            chip.setText(f"{self._count_labels[key]} {count}")
            chip.setVisible(count > 0)
        self._empty_hint.setVisible(self._table.rowCount() == 0)

    def _backend_text(self) -> str:
        if has_yt_dlp():
            return "下载引擎：yt-dlp（支持抖音 / 快手 / B 站等站点）。"
        return "下载引擎：直链模式（仅支持媒体直链）。安装 yt-dlp 后可下载站点视频：pip install yt-dlp"

    # ────────────────────────────── 操作 ──────────────────────────────

    def _choose_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择保存目录", self._directory_edit.text())
        if chosen:
            self._directory_edit.setText(chosen)
            self._queue.set_output_directory(Path(chosen))

    def _open_directory(self) -> None:
        directory = Path(self._directory_edit.text().strip() or str(default_download_directory()))
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _start_downloads(self) -> None:
        urls = extract_urls(self._url_input.toPlainText())
        if not urls:
            self._status.setText("未识别到有效链接，请检查粘贴内容。")
            return

        self._queue.set_output_directory(Path(self._directory_edit.text().strip() or str(default_download_directory())))
        existing = len(self._queue.jobs)
        filenames = (
            [f"{existing + i + 1}" for i in range(len(urls))]
            if hasattr(self, "_auto_number_check") and self._auto_number_check.isChecked()
            else None
        )
        jobs = self._queue.enqueue(urls, filenames=filenames)
        self._queue.start()
        self._url_input.clear()
        self._status.setText(f"已加入 {len(jobs)} 个下载任务。")

    def enqueue_urls(self, urls: list[str], *, filenames: list[str] | None = None) -> int:
        """外部（选品抓取）注入链接：直接入队并启动下载，返回入队数量。"""
        cleaned = [url.strip() for url in urls if url and url.strip()]
        if not cleaned:
            return 0
        self._queue.set_output_directory(Path(self._directory_edit.text().strip() or str(default_download_directory())))
        if filenames is None and hasattr(self, "_auto_number_check") and self._auto_number_check.isChecked():
            existing = len(self._queue.jobs)
            filenames = [f"{existing + i + 1}" for i in range(len(cleaned))]
        jobs = self._queue.enqueue(cleaned, filenames=filenames)
        self._queue.start()
        self._status.setText(f"已从选品结果加入 {len(jobs)} 个下载任务。")
        return len(jobs)

    def _clear_finished(self) -> None:
        """清掉已完成/失败/已取消的**记录**，保留未完成任务。

        注意：不能直接 ``setRowCount(0)`` 再清空行映射——那会把正在下载的任务
        也从界面上抹掉，而 ``_on_queue_event`` 靠 ``self._rows`` 找行，
        映射一丢，后续进度就再也不更新（实测表现为"任务凭空消失"）。
        这里统一走 ``_rebuild_table``，从队列状态重建。
        """
        self._queue.clear_finished()
        self._rebuild_table()
        self._status.setText("已清空已完成任务记录。")

    def _clear_all(self) -> None:
        """取消全部下载并清空列表（对齐 .NET ``ClearListCommand``）。"""
        self._queue.cancel_all()
        # 取消是异步的（工作线程收尾），队列里可能还有尚未转为终态的任务；
        # 界面直接按终态过滤，保证「清空列表」点完表里一定清空。
        self._queue.clear_finished()
        self._fill_table([])
        self._status.setText("列表已清空。")

    def _rebuild_table(self) -> None:
        """按队列当前状态重建表格（清空类操作后调用，避免行映射与界面脱钩）。"""
        self._fill_table([job for job in self._queue.jobs if not _is_terminal(job)])

    def _fill_table(self, jobs: list) -> None:
        previous = self._updating
        self._updating = True
        try:
            self._table.setRowCount(0)
            self._rows.clear()
            self._row_jobs.clear()
            self._row_signatures.clear()
            self._row_state.clear()
            self._pending_jobs.clear()
            for job in jobs:
                row = self._table.rowCount()
                self._table.insertRow(row)
                self._rows[job.id] = row
                self._row_jobs[row] = job.id
                self._update_row(row, job)
        finally:
            self._updating = previous
        self._refresh_overview()

    def _send_to_materials(self) -> None:
        finished = [
            job.output_path
            for job in self._queue.jobs
            if job.state is DownloadState.COMPLETED and job.output_path and Path(job.output_path).is_file()
        ]
        if not finished:
            self._status.setText("没有已完成的下载文件可发送。")
            return
        self.files_downloaded.emit([str(path) for path in finished])
        self._status.setText(f"已发送 {len(finished)} 个文件到混剪素材。")

    # ────────────────────────────── 队列事件 ──────────────────────────────

    def _on_queue_event(self, event: str, job: DownloadJob) -> None:
        if event == "added":
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._rows[job.id] = row
            self._row_jobs[row] = job.id
            self._update_row(row, job)
            self._refresh_overview()
            return
        self._pending_jobs[job.id] = job
        if event == "finished":
            # 终态（完成/失败/取消）立即呈现：文件名、用时等结果需要马上可见，
            # 顺带把积压的进度更新一并落地。
            self._jobs_timer.stop()
            self._flush_pending_jobs()
            return
        # 其余进度事件（每秒可能多条）合并到 60ms 节拍，避免逐条刷新整张表。
        if not self._jobs_timer.isActive():
            self._jobs_timer.start()

    def _flush_pending_jobs(self) -> None:
        pending = list(self._pending_jobs.values())
        self._pending_jobs.clear()
        for job in pending:
            row = self._rows.get(job.id)
            if row is not None:
                self._update_row(row, job)
        self._refresh_overview()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != FILENAME_COLUMN:
            return
        job_id = self._row_jobs.get(item.row())
        if job_id is None:
            return
        if not self._queue.set_filename(job_id, item.text()):
            self._status.setText("该任务已不存在，文件名未保存。")
            return
        # 立即回显清洗后的文件名（不等合并节拍，避免短暂显示含非法字符的输入）。
        current = next((job for job in self._queue.jobs if job.id == job_id), None)
        if current is not None:
            self._row_signatures.pop(item.row(), None)
            self._update_row(item.row(), current)

    @staticmethod
    def _text_color(column: int, job: DownloadJob) -> str:
        """文本颜色：状态色只强调失败/取消的说明列，其余保持中性。"""
        if column == MESSAGE_COLUMN:
            if job.state in (DownloadState.FAILED, DownloadState.CANCELLED):
                return STATE_COLORS[job.state]
            return theme.INK_MUTED
        if column == SPEED_COLUMN:
            return theme.INK_MUTED
        return theme.INK_PRIMARY

    def _update_row(self, row: int, job: DownloadJob) -> None:
        """刷新一行的文本、状态胶囊与进度条。

        高频进度事件会反复调用本方法；用「变更签名」跳过未变化的行，并把
        胶囊/进度条的样式表只在状态变化时重写（``setStyleSheet`` 会触发
        整棵子树的样式重算，是刷新路径上最贵的操作）。
        """
        signature = (
            job.state,
            round(job.percent, 1),
            job.speed,
            job.message,
            job.display_name,
            job.filename,
        )
        if signature == self._row_signatures.get(row) and self._row_state.get(row) is job.state:
            return
        state_changed = self._row_state.get(row) is not job.state
        self._row_signatures[row] = signature
        self._row_state[row] = job.state

        color = STATE_COLORS.get(job.state, theme.INK_MUTED)
        tint = STATE_TINTS.get(job.state, "#F1F0EA")
        suggestion = job.filename or Path(job.display_filename).stem or job.display_filename
        # 状态与进度列由单元格控件呈现，这里保留空 item 以维持列结构与非编辑性。
        values = (job.display_name, suggestion, "", "", job.speed, job.message)
        previous = self._updating
        self._updating = True
        try:
            for column, value in enumerate(values):
                item = self._table.item(row, column)
                created = item is None
                if item is None:
                    item = QTableWidgetItem()
                    self._table.setItem(row, column, item)
                text = str(value)
                if item.text() != text:
                    item.setText(text)
                    item.setForeground(QColor(self._text_color(column, job)))
                elif created or state_changed:
                    item.setForeground(QColor(self._text_color(column, job)))
                if created:
                    if column == FILENAME_COLUMN:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            task_item = self._table.item(row, TASK_COLUMN)
            if task_item is not None and task_item.toolTip() != job.url:
                task_item.setToolTip(job.url)
            filename_item = self._table.item(row, FILENAME_COLUMN)
            if filename_item is not None:
                hint = "双击修改文件名（等待中的任务改名会直接影响落盘文件名）"
                if filename_item.toolTip() != hint:
                    filename_item.setToolTip(hint)
        finally:
            self._updating = previous

        chip_cell = self._table.cellWidget(row, STATUS_COLUMN)
        if not isinstance(chip_cell, StatusChipCell):
            chip_cell = StatusChipCell()
            self._table.setCellWidget(row, STATUS_COLUMN, chip_cell)
        chip_cell.set_state(job.state.display_text, color=color, tint=tint)

        progress_cell = self._table.cellWidget(row, PROGRESS_COLUMN)
        if not isinstance(progress_cell, ProgressCell):
            progress_cell = ProgressCell()
            self._table.setCellWidget(row, PROGRESS_COLUMN, progress_cell)
        progress_cell.set_progress(
            percent=job.percent,
            color=color,
            show_percent=job.state is not DownloadState.PENDING,
        )
