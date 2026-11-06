"""渲染队列页「陈列」UI 测试：卡片、状态胶囊、进度、计数与筛选。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import make_asset  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.composition import CompositionPlan, OrderMode  # noqa: E402
from jingxu.domain.render import RenderRequest, RenderSettings  # noqa: E402
from jingxu.infrastructure.queue import JobState, RenderQueue, _MutableJob  # noqa: E402
from jingxu.ui.queue_page import SCOPE_ACTIVE, SCOPE_FINISHED, QueuePage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _request(name: str) -> RenderRequest:
    plan = CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL)
    return RenderRequest(
        name=name,
        plan=plan,
        settings=RenderSettings(),
        output_path=Path("out") / f"{name}.mp4",
    )


def _queue() -> RenderQueue:
    return RenderQueue(Path("ffmpeg"))


def _inject(
    queue: RenderQueue,
    name: str,
    state: JobState,
    *,
    percent: float = 0.0,
    message: str = "",
    attempt: int = 0,
    can_retry: bool = False,
    started: bool = False,
) -> str:
    job = _MutableJob(f"id-{name}", _request(name), state)
    job.percent = percent
    job.message = message
    job.attempt = attempt
    job.can_retry = can_retry
    if started:
        job.started_at = time.time() - 12.0
        if state.is_finished:
            job.finished_at = time.time()
    with queue._lock:
        queue._jobs[job.id] = job
    return job.id


class TestQueueTable:
    def test_empty_state_shows_hint(self, qapp) -> None:  # noqa: ANN001
        page = QueuePage(_queue())
        assert not page._empty.isHidden()
        assert page._scroll.isHidden()
        assert page._overall_box.isHidden()
        assert page._counts.text() == "暂无任务"

    def test_running_card_shows_progress_and_speed(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(
            queue,
            "混剪_001",
            JobState.RUNNING,
            percent=62.0,
            message="12.3s / 45.0s · 2.4x",
            started=True,
        )
        page = QueuePage(queue)
        row = page._rows["id-混剪_001"]
        assert not row._progress.isHidden()
        assert row._progress.value() == 62
        detail = row._detail.text()
        assert "62%" in detail
        assert "12.3s / 45.0s" in detail
        assert "2.4x" in detail
        assert row._chip.text() == "渲染中"
        assert "输出：混剪_001.mp4" in row._meta.text()

    def test_queued_cards_hide_progress_and_show_position(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(queue, "第一个", JobState.QUEUED)
        _inject(queue, "第二个", JobState.QUEUED)
        page = QueuePage(queue)
        first = page._rows["id-第一个"]
        second = page._rows["id-第二个"]
        assert first._progress.isHidden()
        assert "第 1 位" in first._detail.text()
        assert "第 2 位" in second._detail.text()

    def test_failed_card_offers_retry_and_keeps_error(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(
            queue,
            "失败任务",
            JobState.FAILED,
            percent=41.0,
            message="FFmpeg 退出码 -12：内存申请失败",
            can_retry=True,
        )
        page = QueuePage(queue)
        row = page._rows["id-失败任务"]
        assert not row._retry.isHidden()
        assert not row._open.isHidden()
        assert not row._cancel.isEnabled()
        assert "失败于 41%" in row._detail.text()
        assert "内存申请失败" in row._meta.text()
        assert row._chip.text() == "失败"

    def test_completed_card_shows_elapsed(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(
            queue,
            "完成的任务",
            JobState.COMPLETED,
            percent=100.0,
            message="完成：完成的任务.mp4",
            started=True,
        )
        page = QueuePage(queue)
        row = page._rows["id-完成的任务"]
        assert "100%" in row._detail.text()
        assert "用时" in row._detail.text()
        assert row._retry.isHidden()
        assert not row._open.isHidden()

    def test_attempt_counter_only_after_retry(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(queue, "一次过", JobState.RUNNING, percent=10.0, attempt=1)
        _inject(queue, "重试过", JobState.RUNNING, percent=10.0, attempt=3)
        page = QueuePage(queue)
        assert page._rows["id-一次过"]._attempt.text() == ""
        assert "第 3 次尝试" in page._rows["id-重试过"]._attempt.text()


class TestQueueOverview:
    def test_count_chips_reflect_states(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(queue, "运行", JobState.RUNNING, percent=50.0)
        _inject(queue, "排队", JobState.QUEUED)
        _inject(queue, "完成", JobState.COMPLETED, percent=100.0)
        _inject(queue, "失败", JobState.FAILED)
        page = QueuePage(queue)
        assert page._counts.text() == "共 4 个任务"
        assert page._count_chips["running"].text() == "进行中 1"
        assert page._count_chips["queued"].text() == "排队 1"
        assert page._count_chips["completed"].text() == "已完成 1"
        assert page._count_chips["failed"].text() == "失败 1"
        assert not page._count_chips["failed"].isHidden()
        assert page._count_chips["running"].isHidden() is False

    def test_zero_counts_hide_chips(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(queue, "完成", JobState.COMPLETED, percent=100.0)
        page = QueuePage(queue)
        assert page._count_chips["queued"].isHidden()
        assert page._count_chips["failed"].isHidden()

    def test_overall_progress_averages_running_jobs(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(queue, "A", JobState.RUNNING, percent=50.0)
        _inject(queue, "B", JobState.RUNNING, percent=100.0)
        page = QueuePage(queue)
        assert not page._overall_box.isHidden()
        assert page._overall.value() == 75
        assert "75%" in page._overall_text.text()

    def test_scope_filter_limits_cards(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(queue, "运行", JobState.RUNNING, percent=30.0)
        _inject(queue, "完成", JobState.COMPLETED, percent=100.0)
        page = QueuePage(queue)
        assert set(page._rows) == {"id-运行", "id-完成"}

        page._on_scope_changed(SCOPE_ACTIVE)
        assert set(page._rows) == {"id-运行"}

        page._on_scope_changed(SCOPE_FINISHED)
        assert set(page._rows) == {"id-完成"}

        page._on_scope_changed("all")
        assert set(page._rows) == {"id-运行", "id-完成"}

    def test_pause_button_text_tracks_queue(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        page = QueuePage(queue)
        assert page._pause.text() == "暂停调度"
        page._toggle_pause()
        assert queue.paused
        assert page._pause.text() == "恢复调度"
        page._toggle_pause()
        assert not queue.paused


class TestQueuePagePerformanceContract:
    """高频刷新契约：内容未变化的行不重设样式表（setStyleSheet 会重算子树的样式）。"""

    def test_unchanged_job_skips_restyle(self, qapp) -> None:  # noqa: ANN001
        queue = _queue()
        _inject(queue, "运行", JobState.RUNNING, percent=42.0)
        page = QueuePage(queue)
        row = page._rows["id-运行"]

        style_calls: list[str] = []
        row.setStyleSheet = lambda qss: style_calls.append(qss)  # type: ignore[method-assign]

        # 同一份快照再次刷新：签名一致 → 直接返回，不触碰样式
        row.update_from(queue.jobs[0])
        assert style_calls == []

        # 状态变化 → 恰好重设一次样式（色条/图标/胶囊随之切换）
        with queue._lock:
            queue._jobs["id-运行"].state = JobState.COMPLETED
        row.update_from(queue.jobs[0])
        assert len(style_calls) == 1

        # 之后重复刷新同样的终态：不再重设
        row.update_from(queue.jobs[0])
        assert len(style_calls) == 1
