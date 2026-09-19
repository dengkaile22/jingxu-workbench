"""渲染队列页：与 .NET RenderQueueView 对齐。"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jingxu.infrastructure.queue import JobState, RenderJob, RenderQueue
from jingxu.ui import icons, theme
from jingxu.ui.widgets import Caption, SecondaryButton, SegmentedControl, render_svg_path

SCOPE_ALL = "all"
SCOPE_ACTIVE = "active"
SCOPE_FINISHED = "finished"

STATUS_COLORS = {
    JobState.DRAFT: theme.INK_MUTED,
    JobState.QUEUED: theme.INK_MUTED,
    JobState.PREPARING: theme.STATUS_RUNNING,
    JobState.RUNNING: theme.STATUS_RUNNING,
    JobState.FINALIZING: theme.STATUS_RUNNING,
    JobState.COMPLETED: "#3F7A55",
    JobState.FAILED: theme.STATUS_FAILED,
    JobState.CANCELLED: theme.INK_MUTED,
}

STATUS_ICONS = {
    JobState.DRAFT: icons.STATUS_DRAFT,
    JobState.QUEUED: icons.STATUS_QUEUED,
    JobState.PREPARING: icons.STATUS_QUEUED,
    JobState.RUNNING: icons.STATUS_RUNNING,
    JobState.FINALIZING: icons.STATUS_RUNNING,
    JobState.COMPLETED: icons.STATUS_COMPLETED,
    JobState.FAILED: icons.STATUS_FAILED,
    JobState.CANCELLED: icons.STATUS_CANCELLED,
}


def open_folder(path) -> None:  # noqa: ANN001 - UI 回调
    """在系统文件管理器中打开目录（跨平台）。"""
    directory = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(directory)  # noqa: S606 - 用户主动打开输出目录
        elif sys.platform == "darwin":
            subprocess.Popen(["open", directory])
        else:
            subprocess.Popen(["xdg-open", directory])
    except OSError:
        pass


class JobRow(QFrame):
    """单条任务：状态圆点 + 标题 + 进度 + 短 ID + 状态文字 + 行内操作。"""

    def __init__(self, job: RenderJob, *, on_cancel, on_retry, on_open) -> None:  # noqa: ANN001
        super().__init__()
        self.job_id = job.id
        self._on_retry = on_retry
        self._on_open = on_open
        self.setStyleSheet(f"border-bottom: 1px solid {theme.LINE_DEFAULT};")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 10)
        layout.setSpacing(12)

        self._glyph = QLabel()
        self._glyph.setFixedWidth(18)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._glyph, alignment=Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self._title = QLabel(job.display_name)
        self._title.setStyleSheet("font-size: 12px;")
        text_column.addWidget(self._title)

        self._progress_text = Caption("")
        text_column.addWidget(self._progress_text)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(5)
        self._progress.setTextVisible(False)
        self._progress.setMaximumWidth(420)
        text_column.addWidget(self._progress)

        self._short_id = QLabel(job.short_id)
        self._short_id.setObjectName("Mono")
        self._short_id.setStyleSheet(f"color: {theme.INK_MUTED}; font-size: 10px;")
        text_column.addWidget(self._short_id)
        layout.addLayout(text_column, stretch=1)

        self._status = QLabel("")
        self._status.setStyleSheet("font-size: 12px; font-weight: 600;")
        layout.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._cancel = SecondaryButton("取消")
        self._cancel.clicked.connect(lambda: on_cancel(self.job_id))
        layout.addWidget(self._cancel)

        self._retry = SecondaryButton("重试")
        self._retry.clicked.connect(lambda: self._on_retry(self.job_id))
        layout.addWidget(self._retry)

        self._open = SecondaryButton("打开目录")
        self._open.clicked.connect(lambda: self._on_open(self.job_id))
        layout.addWidget(self._open)

        self.update_from(job)

    def update_from(self, job: RenderJob) -> None:
        color = STATUS_COLORS.get(job.state, theme.INK_MUTED)
        self._glyph.setPixmap(
            render_svg_path(STATUS_ICONS.get(job.state, icons.STATUS_DRAFT), 16, color, stroke_width=2)
        )
        self._status.setText(job.state.display_text)
        self._status.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {color};")

        self._cancel.setEnabled(job.is_active)
        self._retry.setVisible(job.state in (JobState.FAILED, JobState.CANCELLED) and job.can_retry)
        self._open.setVisible(not job.is_active)

        if job.state in (JobState.RUNNING, JobState.PREPARING, JobState.FINALIZING):
            speed = _speed_from_message(job.message)
            self._progress_text.setText(f"{job.progress_text}{speed}")
            self._progress.setValue(int(job.percent))
            self._progress.setVisible(True)
        elif job.state is JobState.QUEUED:
            self._progress_text.setText("等待调度")
            self._progress.setVisible(False)
        else:
            self._progress.setVisible(False)
            detail = job.message or job.state.display_text
            if job.state is JobState.COMPLETED:
                detail = f"{detail} · {job.elapsed_text}"
            self._progress_text.setText(detail)


def _speed_from_message(message: str) -> str:
    if "·" not in message:
        return ""
    tail = message.rsplit("·", 1)[-1].strip()
    return f" · {tail}" if tail else ""


class QueuePage(QWidget):
    """队列模块页：筛选、计数、暂停/清理、任务列表。"""

    scope_changed = Signal(str)

    def __init__(self, queue: RenderQueue) -> None:
        super().__init__()
        self._queue = queue
        self._rows: dict[str, JobRow] = {}
        self._scope = SCOPE_ALL

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())
        layout.addLayout(self._build_overview())

        self._overall = QProgressBar()
        self._overall.setRange(0, 100)
        self._overall.setFixedHeight(6)
        self._overall.setTextVisible(False)
        self._overall.setVisible(False)
        layout.addWidget(self._overall)

        self._empty = QFrame()
        self._empty.setObjectName("PanelMuted")
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(16, 40, 16, 40)
        empty_layout.setSpacing(4)
        empty_icon = QLabel()
        empty_icon.setPixmap(render_svg_path(icons.MODULE_QUEUE, 34, theme.LINE_STRONG, stroke_width=1.5))
        empty_layout.addWidget(empty_icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_title = QLabel("队列为空")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setStyleSheet("font-size: 12px; font-weight: 600;")
        empty_title.setContentsMargins(0, 12, 0, 4)
        empty_layout.addWidget(empty_title)
        empty_hint = Caption("在「混剪编排」中导入素材并「加入队列」，任务会在这里排队、渲染与取消。")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_hint)
        layout.addWidget(self._empty, stretch=1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setVisible(False)
        container = QWidget()
        self._rows_layout = QVBoxLayout(container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch(1)
        self._scroll.setWidget(container)
        layout.addWidget(self._scroll, stretch=1)

        self.refresh()

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel("任务队列")
        title.setObjectName("Title")
        row.addWidget(title)
        row.addStretch(1)

        self._scope_control = SegmentedControl(
            (
                ("全部", SCOPE_ALL),
                ("进行中", SCOPE_ACTIVE),
                ("已结束", SCOPE_FINISHED),
            )
        )
        self._scope_control.changed.connect(self._on_scope_changed)
        row.addWidget(self._scope_control)
        return row

    def _build_overview(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._counts = Caption("")
        row.addWidget(self._counts, stretch=1)

        self._pause = SecondaryButton("暂停调度")
        self._pause.clicked.connect(self._toggle_pause)
        row.addWidget(self._pause)

        clear_finished = SecondaryButton("清理已完成")
        clear_finished.clicked.connect(self._clear_finished)
        row.addWidget(clear_finished)

        clear_all = SecondaryButton("全部清理")
        clear_all.clicked.connect(self._clear_all)
        row.addWidget(clear_all)
        return row

    # ────────────────────────────── 数据刷新 ──────────────────────────────

    def _on_scope_changed(self, scope: object) -> None:
        self._scope = str(scope)
        self.refresh()
        self.scope_changed.emit(self._scope)

    def refresh(self) -> None:
        jobs = self._queue.jobs
        visible = [job for job in jobs if self._matches_scope(job)]

        running = [job for job in jobs if job.state in (JobState.RUNNING, JobState.PREPARING, JobState.FINALIZING)]
        queued = [job for job in jobs if job.state is JobState.QUEUED]
        finished = [job for job in jobs if not job.is_active]
        failed = [job for job in jobs if job.state is JobState.FAILED]

        self._counts.setText(
            f"共 {len(jobs)} 个 · 渲染中 {len(running)} · 排队 {len(queued)} · "
            f"已结束 {len(finished)} · 失败 {len(failed)}"
        )

        self._pause.setText("恢复调度" if self._queue.paused else "暂停调度")

        if running:
            self._overall.setVisible(True)
            progress = sum(job.percent for job in running) / len(running)
            self._overall.setValue(int(progress))
        else:
            self._overall.setVisible(False)

        self._empty.setVisible(not visible)
        self._scroll.setVisible(bool(visible))

        # 同步任务行
        known = set(self._rows)
        wanted = {job.id for job in visible}
        for job_id in known - wanted:
            row = self._rows.pop(job_id)
            self._rows_layout.removeWidget(row)
            row.deleteLater()

        for position, job in enumerate(visible):
            row = self._rows.get(job.id)
            if row is None:
                row = JobRow(job, on_cancel=self._cancel_job, on_retry=self._retry_job, on_open=self._open_output)
                self._rows[job.id] = row
                self._rows_layout.insertWidget(position, row)
                continue
            row.update_from(job)
            current_index = self._rows_layout.indexOf(row)
            if current_index != position:
                self._rows_layout.removeWidget(row)
                self._rows_layout.insertWidget(position, row)

    def _find_job(self, job_id: str) -> RenderJob | None:
        for job in self._queue.jobs:
            if job.id == job_id:
                return job
        return None

    def _cancel_job(self, job_id: str) -> None:
        self._queue.cancel(job_id)
        self.refresh()

    def _retry_job(self, job_id: str) -> None:
        self._queue.retry(job_id)
        self.refresh()

    def _open_output(self, job_id: str) -> None:
        job = self._find_job(job_id)
        if job is None:
            return
        target = job.output_path if job.output_path.exists() else job.output_path.parent
        open_folder(target if target.is_dir() else job.output_path.parent)

    def _matches_scope(self, job: RenderJob) -> bool:
        if self._scope == SCOPE_ACTIVE:
            return job.is_active
        if self._scope == SCOPE_FINISHED:
            return not job.is_active
        return True

    # ────────────────────────────── 操作 ──────────────────────────────

    def _toggle_pause(self) -> None:
        if self._queue.paused:
            self._queue.resume()
        else:
            self._queue.pause()
        self.refresh()

    def _clear_finished(self) -> None:
        self._queue.clear_finished()
        self.refresh()

    def _clear_all(self) -> None:
        self._queue.cancel_all()
        self._queue.clear_finished()
        self.refresh()
