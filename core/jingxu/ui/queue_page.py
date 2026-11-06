"""渲染队列页：与 .NET RenderQueueView 对齐（卡片式任务陈列）。"""

from __future__ import annotations

import os
import subprocess
import sys
import time

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
from jingxu.infrastructure.process_control import no_window_kwargs
from jingxu.ui import icons, theme
from jingxu.ui.widgets import (
    Caption,
    SecondaryButton,
    SegmentedControl,
    chip_qss,
    render_svg_path,
    status_chip,
)

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

# 状态胶囊底色：运行族与失败任务用浅色底强调，其余保持素色。
STATUS_TINTS = {
    JobState.DRAFT: "#F1F0EA",
    JobState.QUEUED: "#F1F0EA",
    JobState.PREPARING: "#FBF1E3",
    JobState.RUNNING: "#FBF1E3",
    JobState.FINALIZING: "#FBF1E3",
    JobState.COMPLETED: "#E9F3EC",
    JobState.FAILED: "#FAEAE7",
    JobState.CANCELLED: "#F1F0EA",
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

# 需要浅色底的进行中/失败状态（卡片整体着色，一眼可辨）。
_TINTED_STATES = frozenset(
    {
        JobState.PREPARING,
        JobState.RUNNING,
        JobState.FINALIZING,
        JobState.FAILED,
    }
)


def open_folder(path) -> None:  # noqa: ANN001 - UI 回调
    """在系统文件管理器中打开目录（跨平台）。"""
    directory = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(directory)  # noqa: S606 - 用户主动打开输出目录
        elif sys.platform == "darwin":
            subprocess.Popen(["open", directory], **no_window_kwargs())
        else:
            subprocess.Popen(["xdg-open", directory], **no_window_kwargs())
    except OSError:
        pass


def _clip(text: str, limit: int = 72) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _set_label(label: QLabel, text: str) -> None:
    """仅在文本变化时写 QLabel：重复 setText 会触发尺寸提示与重绘。"""
    if label.text() != text:
        label.setText(text)


def _set_visible(widget: QWidget, visible: bool) -> None:
    """仅在可见性变化时调整（用 isHidden 判断显式隐藏状态）。"""
    if widget.isHidden() == visible:
        widget.setVisible(visible)


def _card_style(color: str, background: str) -> str:
    return (
        "QFrame#JobCard {"
        f" background: {background};"
        f" border: 1px solid {theme.LINE_DEFAULT};"
        f" border-left: 4px solid {color};"
        " border-radius: 10px;"
        "}"
        f"QFrame#JobCard QProgressBar {{ background: {theme.SURFACE_SUNK};"
        " border: none; border-radius: 4px; }"
        f"QFrame#JobCard QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
    )


class JobRow(QFrame):
    """单条任务的卡片式陈列。

    信息层级：标题 + 输出信息 → 进度条 + 数值详情 → 状态胶囊与行内操作。
    状态同时用「左侧色条 + 图标 + 胶囊」三重表达，扫一眼即可区分。
    """

    def __init__(
        self,
        job: RenderJob,
        *,
        on_cancel,  # noqa: ANN001 - UI 回调
        on_retry,  # noqa: ANN001
        on_open,  # noqa: ANN001
        queue_position: int | None = None,
    ) -> None:
        super().__init__()
        self.job_id = job.id
        self._on_retry = on_retry
        self._on_open = on_open
        self.setObjectName("JobCard")

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 14, 12)
        root.setSpacing(12)

        self._glyph = QLabel()
        self._glyph.setFixedWidth(20)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._glyph, alignment=Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._title = QLabel(job.display_name)
        self._title.setStyleSheet("font-size: 13px; font-weight: 600;")
        title_row.addWidget(self._title)
        self._attempt = Caption("")
        title_row.addWidget(self._attempt)
        title_row.addStretch(1)
        self._chip = QLabel("")
        title_row.addWidget(self._chip)
        column.addLayout(title_row)

        self._meta = Caption("")
        column.addWidget(self._meta)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        progress_row.addWidget(self._progress, stretch=1)
        self._detail = QLabel("")
        self._detail.setObjectName("Mono")
        self._detail.setStyleSheet(f"color: {theme.INK_MUTED}; font-size: 12px;")
        self._detail.setMinimumWidth(210)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self._detail)
        column.addLayout(progress_row)
        root.addLayout(column, stretch=1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._cancel = SecondaryButton("取消")
        self._cancel.clicked.connect(lambda: on_cancel(self.job_id))
        buttons.addWidget(self._cancel)
        self._retry = SecondaryButton("重试")
        self._retry.clicked.connect(lambda: self._on_retry(self.job_id))
        buttons.addWidget(self._retry)
        self._open = SecondaryButton("打开目录")
        self._open.clicked.connect(lambda: self._on_open(self.job_id))
        buttons.addWidget(self._open)
        root.addLayout(buttons)

        self._signature: tuple | None = None
        self._styled_state: JobState | None = None
        self.update_from(job, queue_position=queue_position)

    def update_from(self, job: RenderJob, *, queue_position: int | None = None) -> None:
        """刷新卡片。

        高频事件（渲染进度每秒多次）会反复调用本方法；这里用「变更签名」跳过
        未变化的行，并把样式表/图标只在**状态变化时**重设——``setStyleSheet``
        会触发整棵子树的样式重算，是刷新路径上最贵的操作。
        """
        signature = (
            job.state,
            round(job.percent, 1),
            job.message,
            job.display_name,
            job.attempt,
            job.can_retry,
            queue_position,
            # 运行中任务的「已用 X」按秒刷新，避免被签名守卫冻结。
            int(time.time() - job.started_at) if job.is_active and job.started_at else 0,
        )
        if signature == self._signature:
            return
        self._signature = signature
        if job.state is not self._styled_state:
            self._apply_state_style(job.state)
            self._styled_state = job.state

        _set_label(self._title, job.display_name)
        _set_label(self._attempt, f"第 {job.attempt} 次尝试" if job.attempt > 1 else "")
        _set_label(self._meta, self._meta_text(job))
        self._apply_progress(job, queue_position)

        self._cancel.setEnabled(job.is_active)
        _set_visible(self._retry, job.state in (JobState.FAILED, JobState.CANCELLED) and job.can_retry)
        _set_visible(self._open, not job.is_active)

    def _apply_state_style(self, state: JobState) -> None:
        """状态相关的外观：卡片底色/左色条、状态图标与胶囊（仅在状态变化时调用）。"""
        color = STATUS_COLORS.get(state, theme.INK_MUTED)
        tint = STATUS_TINTS.get(state, "#F1F0EA")
        background = tint if state in _TINTED_STATES else theme.SURFACE_PANEL
        self.setStyleSheet(_card_style(color, background))
        self._glyph.setPixmap(
            render_svg_path(STATUS_ICONS.get(state, icons.STATUS_DRAFT), 16, color, stroke_width=2)
        )
        _set_label(self._chip, state.display_text)
        self._chip.setStyleSheet(chip_qss(color=color, tint=tint))

    def _meta_text(self, job: RenderJob) -> str:
        parts = [f"输出：{job.output_path.name}", f"#{job.short_id}"]
        if job.state is JobState.FAILED and job.message:
            parts.append(_clip(job.message, 64))
        return " · ".join(parts)

    def _apply_progress(self, job: RenderJob, queue_position: int | None) -> None:
        if job.state in (JobState.DRAFT, JobState.QUEUED):
            _set_visible(self._progress, False)
            if job.state is JobState.QUEUED:
                suffix = f" · 第 {queue_position} 位" if queue_position else ""
                _set_label(self._detail, f"排队中{suffix}")
            else:
                _set_label(self._detail, job.message or "草稿")
            return

        percent = max(0.0, min(job.percent, 100.0))
        _set_visible(self._progress, True)
        value = int(percent)
        if self._progress.value() != value:
            self._progress.setValue(value)

        if job.state in (JobState.RUNNING, JobState.PREPARING, JobState.FINALIZING):
            speed = _speed_from_message(job.message)
            rendered = _timing_from_message(job.message)
            parts = [f"{percent:.0f}%"]
            if rendered:
                parts.append(rendered)
            if speed:
                parts.append(speed)
            elif job.started_at is not None:
                parts.append(f"已用 {job.elapsed_text}")
            _set_label(self._detail, " · ".join(parts))
        elif job.state is JobState.COMPLETED:
            _set_label(self._detail, f"100% · 用时 {job.elapsed_text}")
        elif job.state is JobState.FAILED:
            text = f"失败于 {percent:.0f}% · 可重试" if job.can_retry else f"失败于 {percent:.0f}%"
            _set_label(self._detail, text)
        elif job.state is JobState.CANCELLED:
            _set_label(self._detail, f"已取消 · 停于 {percent:.0f}%")
        else:
            _set_label(self._detail, f"{percent:.0f}%")


def _speed_from_message(message: str) -> str:
    tail = message.rsplit("·", 1)[-1].strip() if "·" in message else ""
    return tail if tail.endswith("x") else ""


def _timing_from_message(message: str) -> str:
    """从「12.3s / 45.0s · 2.4x」中取出「12.3s / 45.0s」段。"""
    if "/" not in message:
        return ""
    head = message.split("·", 1)[0].strip()
    return head if "/" in head else ""


class QueuePage(QWidget):
    """队列模块页：筛选、计数徽标、暂停/清理、卡片式任务列表。"""

    scope_changed = Signal(str)

    def __init__(self, queue: RenderQueue) -> None:
        super().__init__()
        self._queue = queue
        self._rows: dict[str, JobRow] = {}
        self._scope = SCOPE_ALL
        self._last_counts: tuple[int, ...] | None = None
        self._last_order: tuple[str, ...] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())
        layout.addLayout(self._build_overview())

        self._overall_box = QWidget()
        overall_row = QHBoxLayout(self._overall_box)
        overall_row.setContentsMargins(0, 0, 0, 0)
        overall_row.setSpacing(10)
        overall_label = Caption("总体进度")
        overall_row.addWidget(overall_label)
        self._overall = QProgressBar()
        self._overall.setRange(0, 100)
        self._overall.setFixedHeight(8)
        self._overall.setTextVisible(False)
        overall_row.addWidget(self._overall, stretch=1)
        self._overall_text = QLabel("")
        self._overall_text.setObjectName("Mono")
        self._overall_text.setStyleSheet(f"color: {theme.INK_MUTED}; font-size: 12px;")
        self._overall_text.setMinimumWidth(120)
        self._overall_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        overall_row.addWidget(self._overall_text)
        self._overall_box.setVisible(False)
        layout.addWidget(self._overall_box)

        layout.addWidget(self._build_empty(), stretch=1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setVisible(False)
        container = QWidget()
        self._rows_layout = QVBoxLayout(container)
        self._rows_layout.setContentsMargins(0, 2, 6, 2)
        self._rows_layout.setSpacing(10)
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
        row.setSpacing(8)

        self._counts = Caption("")
        row.addWidget(self._counts)

        self._count_chips: dict[str, QLabel] = {}
        self._count_labels: dict[str, str] = {}
        for key, label, color, tint in (
            ("running", "进行中", theme.STATUS_RUNNING, "#FBF1E3"),
            ("queued", "排队", theme.INK_MUTED, "#F1F0EA"),
            ("completed", "已完成", "#3F7A55", "#E9F3EC"),
            ("failed", "失败", theme.STATUS_FAILED, "#FAEAE7"),
        ):
            chip = status_chip(label, color=color, tint=tint)
            chip.setVisible(False)
            self._count_chips[key] = chip
            self._count_labels[key] = label
            row.addWidget(chip)

        row.addStretch(1)

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

    def _build_empty(self) -> QFrame:
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
        empty_tip = Caption("支持暂停调度 · 单任务取消 · 失败隔离重试")
        empty_tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_tip)
        return self._empty

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
        completed = [job for job in jobs if job.state is JobState.COMPLETED]
        failed = [job for job in jobs if job.state is JobState.FAILED]

        # 页面级元素只在内容变化时更新（setText/setVisible 都会触发布局开销）。
        counts = (len(jobs), len(running), len(queued), len(completed), len(failed))
        if counts != self._last_counts:
            self._last_counts = counts
            self._counts.setText(f"共 {len(jobs)} 个任务" if jobs else "暂无任务")
            for key, count in (
                ("running", len(running)),
                ("queued", len(queued)),
                ("completed", len(completed)),
                ("failed", len(failed)),
            ):
                chip = self._count_chips[key]
                chip.setText(f"{self._count_labels[key]} {count}")
                _set_visible(chip, count > 0)

        paused_text = "恢复调度" if self._queue.paused else "暂停调度"
        _set_label(self._pause, paused_text)

        if running:
            progress = sum(job.percent for job in running) / len(running)
            value = int(progress)
            if self._overall.value() != value:
                self._overall.setValue(value)
            _set_label(self._overall_text, f"{progress:.0f}% · 进行中 {len(running)} 个")
            _set_visible(self._overall_box, True)
        else:
            _set_visible(self._overall_box, False)

        _set_visible(self._empty, not visible)
        _set_visible(self._scroll, bool(visible))

        positions = {job.id: index + 1 for index, job in enumerate(queued)}
        order = tuple(job.id for job in visible)
        order_changed = order != self._last_order
        self._last_order = order

        # 同步任务卡片
        known = set(self._rows)
        wanted = set(order)
        for job_id in known - wanted:
            row = self._rows.pop(job_id)
            self._rows_layout.removeWidget(row)
            row.deleteLater()
            order_changed = True

        for position, job in enumerate(visible):
            row = self._rows.get(job.id)
            if row is None:
                row = JobRow(
                    job,
                    on_cancel=self._cancel_job,
                    on_retry=self._retry_job,
                    on_open=self._open_output,
                    queue_position=positions.get(job.id),
                )
                self._rows[job.id] = row
                self._rows_layout.insertWidget(position, row)
                order_changed = True
                continue
            row.update_from(job, queue_position=positions.get(job.id))

        # 顺序未变时不触碰布局（indexOf/insertWidget 是较贵的 QLayout 调用）。
        if order_changed:
            for position, job in enumerate(visible):
                row = self._rows[job.id]
                if self._rows_layout.indexOf(row) != position:
                    self._rows_layout.removeWidget(row)
                    self._rows_layout.insertWidget(position, row)
            self._rows_layout.activate()

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
