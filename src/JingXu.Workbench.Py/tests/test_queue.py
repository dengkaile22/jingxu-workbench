"""渲染队列测试（使用脚本化假执行器，不调用 FFmpeg）。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import make_asset, wait_until

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.effects import FourScreenEffectPlan
from jingxu.domain.render import RenderRequest, RenderSettings
from jingxu.infrastructure.ffmpeg_runner import RenderCancelled, RenderError, RenderProgress
from jingxu.infrastructure.queue import (
    IllegalTransitionError,
    JobState,
    RenderQueue,
)

Behavior = Callable[[RenderRequest, Callable[[RenderProgress], None], threading.Event], Path]


def _request(name: str = "job", *, four_screen: bool = False) -> RenderRequest:
    plan = CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL)
    return RenderRequest(
        name=name,
        plan=plan,
        settings=RenderSettings(),
        output_path=Path("out") / f"{name}.mp4",
        four_screen=FourScreenEffectPlan() if four_screen else None,
    )


def _current(queue: RenderQueue, job_id: str):
    for job in queue.jobs:
        if job.id == job_id:
            return job
    return None


class ScriptedRunner:
    def __init__(self, behaviors: list[Behavior]) -> None:
        self._behaviors = list(behaviors)
        self.calls: list[RenderRequest] = []
        self._lock = threading.Lock()

    def __call__(self, ffmpeg, request, *, on_progress, cancel_event):  # noqa: ANN001 - 测试替身
        with self._lock:
            behavior = self._behaviors.pop(0)
            self.calls.append(request)
        return behavior(request, on_progress, cancel_event)


def _succeed(percent: float = 100.0) -> Behavior:
    def behavior(request, on_progress, cancel_event):
        on_progress(RenderProgress(percent, 1.0, 2.0, "1.2x"))
        return request.output_path

    return behavior


@pytest.fixture()
def queue_factory():
    queues: list[RenderQueue] = []

    def factory(behaviors: list[Behavior], **kwargs) -> tuple[RenderQueue, ScriptedRunner]:
        runner = ScriptedRunner(behaviors)
        queue = RenderQueue(Path("ffmpeg"), runner=runner, max_concurrency=1, **kwargs)
        queue.start()
        queues.append(queue)
        return queue, runner

    yield factory
    for queue in queues:
        queue.stop()


def test_jobs_run_in_order_and_complete(queue_factory) -> None:
    queue, runner = queue_factory([_succeed(), _succeed()])
    events: list[tuple[str, str]] = []
    queue.add_listener(lambda event, job: events.append((event, job.state.value)))

    first = queue.enqueue(_request("first"))
    second = queue.enqueue(_request("second"))

    wait_until(lambda: queue.active_count == 0)
    assert [request.name for request in runner.calls] == ["first", "second"]
    assert _current(queue, first.id).state is JobState.COMPLETED
    assert _current(queue, second.id).state is JobState.COMPLETED
    assert _current(queue, first.id).percent == 100.0
    assert ("finished", "completed") in events
    assert sum(1 for event, _ in events if event == "added") == 2


def test_snapshot_returned_by_enqueue_is_immutable(queue_factory) -> None:
    queue, _ = queue_factory([_succeed()])
    job = queue.enqueue(_request("snap"))
    wait_until(lambda: queue.active_count == 0)

    # 入队返回的是快照，不会随队列内部状态变化。
    assert job.state is JobState.QUEUED
    assert _current(queue, job.id).state is JobState.COMPLETED
    assert job.short_id == job.id[:8]


def test_failure_is_isolated_and_retryable(queue_factory) -> None:
    def explode(request, on_progress, cancel_event):
        raise RenderError("FFmpeg 退出码 1。boom")

    queue, _ = queue_factory([explode, _succeed(), _succeed()])
    broken = queue.enqueue(_request("broken"))
    healthy = queue.enqueue(_request("healthy"))

    wait_until(lambda: queue.active_count == 0)
    broken_snapshot = _current(queue, broken.id)
    assert broken_snapshot.state is JobState.FAILED
    assert "boom" in broken_snapshot.message
    assert broken_snapshot.can_retry is True
    assert _current(queue, healthy.id).state is JobState.COMPLETED

    assert queue.retry(broken.id) is True
    wait_until(lambda: queue.active_count == 0)
    retried = _current(queue, broken.id)
    assert retried.state is JobState.COMPLETED
    assert retried.attempt >= 2


def test_running_job_can_be_cancelled(queue_factory) -> None:
    started = threading.Event()

    def cancellable(request, on_progress, cancel_event):
        started.set()
        if cancel_event.wait(timeout=5):
            raise RenderCancelled("渲染已取消。")
        raise AssertionError("未收到取消信号")

    queue, _ = queue_factory([cancellable, _succeed()])
    job = queue.enqueue(_request("slow"))
    assert started.wait(timeout=5)

    assert queue.cancel(job.id) is True
    wait_until(lambda: queue.active_count == 0)
    cancelled = _current(queue, job.id)
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.message == "已取消"
    # 取消后的任务允许重试。
    assert queue.retry(job.id) is True
    wait_until(lambda: queue.active_count == 0)
    assert _current(queue, job.id).state is JobState.COMPLETED


def test_pending_job_can_be_cancelled_before_start(queue_factory) -> None:
    gate = threading.Event()
    started = threading.Event()

    def blocking(request, on_progress, cancel_event):
        started.set()
        gate.wait(timeout=5)
        return request.output_path

    queue, runner = queue_factory([blocking])
    running = queue.enqueue(_request("running"))
    queued = queue.enqueue(_request("queued"))
    assert started.wait(timeout=5)

    assert queue.cancel(queued.id) is True
    assert _current(queue, queued.id).state is JobState.CANCELLED

    gate.set()
    wait_until(lambda: queue.active_count == 0)
    assert _current(queue, running.id).state is JobState.COMPLETED
    assert [request.name for request in runner.calls] == ["running"]


def test_clear_finished_keeps_active_jobs(queue_factory) -> None:
    queue, _ = queue_factory([_succeed()])
    job = queue.enqueue(_request("done"))
    wait_until(lambda: _current(queue, job.id).state is JobState.COMPLETED)

    queue.clear_finished()
    assert queue.jobs == []


def test_concurrency_runs_two_jobs_in_parallel() -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking(request, on_progress, cancel_event):
        started.set()
        release.wait(timeout=5)
        return request.output_path

    runner = ScriptedRunner([blocking, blocking])
    queue = RenderQueue(Path("ffmpeg"), runner=runner, max_concurrency=2)
    queue.start()
    try:
        first = queue.enqueue(_request("one"))
        second = queue.enqueue(_request("two"))
        assert started.wait(timeout=5)
        wait_until(lambda: sum(1 for job in queue.jobs if job.state is JobState.RUNNING) == 2)
        release.set()
        wait_until(lambda: queue.active_count == 0)
        assert _current(queue, first.id).state is JobState.COMPLETED
        assert _current(queue, second.id).state is JobState.COMPLETED
    finally:
        queue.stop()


def test_concurrency_is_clamped_to_four() -> None:
    queue = RenderQueue(Path("ffmpeg"), runner=ScriptedRunner([]), max_concurrency=9)
    try:
        assert queue.max_concurrency == 4
        queue.set_max_concurrency(0)
        assert queue.max_concurrency == 1
    finally:
        queue.stop()


def test_four_screen_high_resolution_runs_exclusively() -> None:
    running = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def blocking(request, on_progress, cancel_event):
        order.append(request.name)
        running.set()
        release.wait(timeout=5)
        return request.output_path

    runner = ScriptedRunner([blocking, blocking])
    queue = RenderQueue(Path("ffmpeg"), runner=runner, max_concurrency=2)
    queue.start()
    try:
        normal = queue.enqueue(_request("normal"))
        assert running.wait(timeout=5)
        # 独占任务（四屏 + 1080×1920 ≥ 1280×720）必须等待普通任务结束。
        exclusive = queue.enqueue(_request("exclusive", four_screen=True))
        threading.Event().wait(0.3)
        assert order == ["normal"]

        release.set()
        wait_until(lambda: queue.active_count == 0)
        assert order == ["normal", "exclusive"]
        assert _current(queue, exclusive.id).state is JobState.COMPLETED
        assert _current(queue, normal.id).state is JobState.COMPLETED
    finally:
        queue.stop()


def test_illegal_transition_is_rejected() -> None:
    queue = RenderQueue(Path("ffmpeg"), runner=ScriptedRunner([]))
    job = queue.enqueue(_request("draft"))
    try:
        with pytest.raises(IllegalTransitionError):
            queue._transition(JobState.COMPLETED, job.id)  # noqa: SLF001 - 直接验证状态机
    finally:
        queue.stop()


def test_pause_stops_dequeue_until_resumed(queue_factory) -> None:
    queue, runner = queue_factory([_succeed()])
    queue.pause()
    job = queue.enqueue(_request("paused"))
    threading.Event().wait(0.4)

    assert runner.calls == []
    assert _current(queue, job.id).state is JobState.QUEUED

    queue.resume()
    wait_until(lambda: queue.active_count == 0)
    assert [request.name for request in runner.calls] == ["paused"]
