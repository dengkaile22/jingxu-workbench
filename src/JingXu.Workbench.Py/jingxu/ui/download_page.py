"""批量下载页：链接解析、下载队列、发送到混剪素材。"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
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
from jingxu.ui.widgets import Caption, PrimaryButton, SecondaryButton, SectionHeader

URL_PATTERN = re.compile(r"https?://[^\s\"'<>）)】\]]+", re.IGNORECASE)
COLUMNS = ("任务", "文件名", "状态", "进度", "速度", "说明")
FILENAME_COLUMN = COLUMNS.index("文件名")

STATE_COLORS = {
    DownloadState.PENDING: theme.INK_MUTED,
    DownloadState.RUNNING: theme.STATUS_RUNNING,
    DownloadState.COMPLETED: "#3F7A55",
    DownloadState.FAILED: theme.STATUS_FAILED,
    DownloadState.CANCELLED: theme.INK_MUTED,
}


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

        bridge = DownloadBridge(self)
        bridge.event.connect(self._on_queue_event)
        self._bridge = bridge
        self._queue.add_listener(lambda event, job: self._bridge.event.emit(event, job))

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

        layout.addSpacing(8)
        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.SelectedClicked
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 240)
        self._table.setColumnWidth(1, 220)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 80)
        self._table.setColumnWidth(4, 90)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, stretch=1)

        self._status = Caption("")
        self._status.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self._status)

        self._queue.set_output_directory(default_download_directory())
        self._directory_edit.setText(str(default_download_directory()))

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

        send = SecondaryButton("发送已下载到混剪素材")
        send.setToolTip("把已完成的视频加入「商品组 A」素材列表，可直接编排渲染。")
        send.clicked.connect(self._send_to_materials)
        row.addWidget(send)
        row.addStretch(1)
        return row

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
        jobs = self._queue.enqueue(urls)
        self._queue.start()
        self._url_input.clear()
        self._status.setText(f"已加入 {len(jobs)} 个下载任务。")

    def enqueue_urls(self, urls: list[str]) -> int:
        """外部（选品爬虫）注入链接：直接入队并启动下载，返回入队数量。"""
        cleaned = [url.strip() for url in urls if url and url.strip()]
        if not cleaned:
            return 0
        self._queue.set_output_directory(Path(self._directory_edit.text().strip() or str(default_download_directory())))
        jobs = self._queue.enqueue(cleaned)
        self._queue.start()
        self._status.setText(f"已从选品结果加入 {len(jobs)} 个下载任务。")
        return len(jobs)

    def _clear_finished(self) -> None:
        self._queue.clear_finished()
        previous = self._updating
        self._updating = True
        try:
            self._table.setRowCount(0)
        finally:
            self._updating = previous
        self._rows.clear()
        self._row_jobs.clear()
        self._status.setText("已清空已完成任务记录。")

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
        row = self._rows.get(job.id)
        if row is None:
            return
        self._update_row(row, job)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != FILENAME_COLUMN:
            return
        job_id = self._row_jobs.get(item.row())
        if job_id is None:
            return
        if not self._queue.set_filename(job_id, item.text()):
            self._status.setText("该任务已不存在，文件名未保存。")

    def _update_row(self, row: int, job: DownloadJob) -> None:
        color = STATE_COLORS.get(job.state, theme.INK_MUTED)
        progress = f"{job.percent:.0f}%" if job.state is DownloadState.RUNNING else ""
        suggestion = job.filename or Path(job.display_filename).stem or job.display_filename
        values = (
            job.display_name,
            suggestion,
            job.state.display_text,
            progress,
            job.speed,
            job.message,
        )
        previous = self._updating
        self._updating = True
        try:
            for column, value in enumerate(values):
                item = self._table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self._table.setItem(row, column, item)
                item.setText(str(value))
                item.setForeground(QColor(color))
                if column == FILENAME_COLUMN:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        finally:
            self._updating = previous
