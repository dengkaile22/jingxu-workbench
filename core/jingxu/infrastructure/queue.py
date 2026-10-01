"""渲染队列：状态机、并发调度、取消/重试、独占四屏与进度节流。"""

from __future__ import annotations

import inspect
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from jingxu.domain.render import RenderRequest
from jingxu.infrastructure.ffmpeg_runner import (
    RenderCancelled,
    RenderError,
    RenderProgress,
    run_render,
)

NOTIFY_THROTTLE_SECONDS = 0.5
NOTIFY_PERCENT_DELTA = 1.0
EXCLUSIVE_AREA_THRESHOLD = 1280 * 720
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 4


class JobState(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def display_text(self) -> str:
        return {
            JobState.DRAFT: "草稿",
            JobState.QUEUED: "排队中",
            JobState.PREPARING: "准备中",
            JobState.RUNNING: "渲染中",
            JobState.FINALIZING: "收尾中",
            JobState.COMPLETED: "已完成",
            JobState.FAILED: "失败",
            JobState.CANCELLED: "已取消",
        }[self]

    @property
    def is_active(self) -> bool:
        return self in (JobState.QUEUED, JobState.PREPARING, JobState.RUNNING, JobState.FINALIZING)

    @property
    def is_finished(self) -> bool:
        return self in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)


_LEGAL_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.DRAFT: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.QUEUED: frozenset({JobState.PREPARING, JobState.CANCELLED, JobState.FAILED}),
    JobState.PREPARING: frozenset({JobState.RUNNING, JobState.FAILED, JobState.CANCELLED}),
    JobState.RUNNING: frozenset({JobState.FINALIZING, JobState.FAILED, JobState.CANCELLED}),
    JobState.FINALIZING: frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset(),
    JobState.FAILED: frozenset({JobState.QUEUED}),
    JobState.CANCELLED: frozenset({JobState.QUEUED}),
}


class IllegalTransitionError(RuntimeError):
    """非法的任务状态迁移。"""


@dataclass(frozen=True, slots=True)
class RenderJob:
    """队列中的单个渲染任务（只读快照）。"""

    id: str
    request: RenderRequest
    state: JobState = JobState.QUEUED
    percent: float = 0.0
    message: str = ""
    attempt: int = 0
    can_retry: bool = False
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def display_name(self) -> str:
        return self.request.name

    @property
    def output_path(self) -> Path:
        return self.request.output_path

    @property
    def elapsed_text(self) -> str:
        if self.started_at is None:
            return "-"
        end = self.finished_at or time.time()
        return f"{max(end - self.started_at, 0):.1f}s"

    @property
    def is_active(self) -> bool:
        return self.state.is_active

    @property
    def progress_text(self) -> str:
        if self.state is JobState.RUNNING:
            return f"渲染中 {self.percent:.0f}%"
        if self.state is JobState.PREPARING:
            return "准备中…"
        if self.state is JobState.FINALIZING:
            return "收尾中…"
        return self.message or self.state.display_text


RunnerFn = Callable[..., Path]
ListenerFn = Callable[[str, RenderJob], None]


class _MutableJob:
    """队列内部使用的可变任务记录。"""

    __slots__ = (
        "id",
        "request",
        "state",
        "percent",
        "message",
        "attempt",
        "can_retry",
        "created_at",
        "started_at",
        "finished_at",
    )

    def __init__(self, job_id: str, request: RenderRequest, state: JobState) -> None:
        self.id = job_id
        self.request = request
        self.state = state
        self.percent = 0.0
        self.message = ""
        self.attempt = 0
        self.can_retry = False
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None

    def snapshot(self) -> RenderJob:
        return RenderJob(
            id=self.id,
            request=self.request,
            state=self.state,
            percent=self.percent,
            message=self.message,
            attempt=self.attempt,
            can_retry=self.can_retry,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


class RenderQueue:
    """线程安全的任务队列；事件通过监听器通知（UI 层负责切回主线程）。"""

    def __init__(
        self,
        ffmpeg_path: Path,
        *,
        runner: RunnerFn = run_render,
        max_history: int = 200,
        max_concurrency: int = 2,
    ) -> None:
        self._ffmpeg_path = Path(ffmpeg_path)
        self._runner = runner
        try:
            self._runner_accepts_job_id = "job_id" in inspect.signature(runner).parameters
        except (TypeError, ValueError):
            self._runner_accepts_job_id = False
        self._max_history = max_history
        self._max_concurrency = self.clamp_concurrency(max_concurrency)

        self._pending: list[str] = []
        self._jobs: dict[str, _MutableJob] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._listeners: list[ListenerFn] = []

        self._lock = threading.RLock()
        self._wakeup = threading.Condition(self._lock)
        self._stop_requested = False
        self._paused = False
        self._workers: list[threading.Thread] = []

    # ────────────────────────────── 生命周期 ──────────────────────────────

    @staticmethod
    def clamp_concurrency(value: int) -> int:
        return max(MIN_CONCURRENCY, min(int(value), MAX_CONCURRENCY))

    def start(self) -> None:
        with self._lock:
            if any(worker.is_alive() for worker in self._workers):
                return
            self._stop_requested = False
            self._workers = [
                threading.Thread(
                    target=self._run_worker,
                    name=f"jingxu-render-queue-{index}",
                    daemon=True,
                )
                for index in range(self._max_concurrency)
            ]
            for worker in self._workers:
                worker.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.cancel_all()
        with self._lock:
            self._stop_requested = True
            self._wakeup.notify_all()
        for worker in self._workers:
            if worker.is_alive():
                worker.join(timeout=timeout)
        self._workers = []

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    def set_max_concurrency(self, value: int) -> None:
        """调整并发（钳制 1–4）：空闲时立即生效，否则下一批任务生效。"""
        new_value = self.clamp_concurrency(value)
        if new_value == self._max_concurrency:
            return
        self._max_concurrency = new_value

        with self._lock:
            running = any(worker.is_alive() for worker in self._workers)
            has_active = any(job.state.is_active for job in self._jobs.values())

        if running and not has_active:
            self.stop()
            self.start()

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def pause(self) -> None:
        """暂停调度：当前任务继续，等待中的任务不再出队。"""
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._wakeup.notify_all()

    # ────────────────────────────── 队列操作 ──────────────────────────────

    def enqueue(self, request: RenderRequest) -> RenderJob:
        job = _MutableJob(uuid.uuid4().hex[:12], request, JobState.QUEUED)
        with self._lock:
            self._jobs[job.id] = job
            self._pending.append(job.id)
            self._cancel_events[job.id] = threading.Event()
            self._trim_history_locked()
            self._wakeup.notify_all()
        snapshot = job.snapshot()
        self._notify("added", snapshot)
        self.start()  # 入队即确保调度在线，避免任务永远停留在排队
        return snapshot

    def cancel(self, job_id: str) -> bool:
        """取消等待中或运行中的任务（运行中通过取消事件终止进程树）。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not job.state.is_active:
                return False

            self._cancel_events[job_id].set()
            if job.state in (JobState.QUEUED, JobState.DRAFT) and job_id in self._pending:
                self._pending.remove(job_id)
                self._transition_locked(job, JobState.CANCELLED, message="已取消")
                snapshot = job.snapshot()
                cancelled = True
            else:
                cancelled = False
        if cancelled:
            self._notify("finished", snapshot)
        return True

    def retry(self, job_id: str) -> bool:
        """把失败/已取消的任务重新排队（保留原请求快照）。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in (JobState.FAILED, JobState.CANCELLED):
                return False
            self._transition_locked(job, JobState.QUEUED, message="已重新排队", reset_progress=True)
            job.can_retry = False
            self._pending.append(job_id)
            self._cancel_events[job_id] = threading.Event()
            snapshot = job.snapshot()
            self._wakeup.notify_all()
        self._notify("updated", snapshot)
        self.start()
        return True

    def cancel_all(self) -> None:
        with self._lock:
            active_ids = [job_id for job_id, job in self._jobs.items() if job.state.is_active]
        for job_id in active_ids:
            self.cancel(job_id)

    @property
    def jobs(self) -> list[RenderJob]:
        """返回按创建时间排序的只读快照（UI 读取时不会被工作线程改写）。"""
        with self._lock:
            return [
                job.snapshot() for job in sorted(self._jobs.values(), key=lambda item: item.created_at)
            ]

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.state.is_active)

    @property
    def reserved_output_paths(self) -> list[Path]:
        """队列中**尚未结束**任务占用的输出路径。

        入队时这些文件还没落盘，而 ``unique_output_path`` 只看磁盘上已存在的文件，
        于是下一批请求会算到同样的文件名，后渲染的任务把先渲染的**直接覆盖**。
        调用方把它们一起传给 ``build_requests(reserved_paths=...)`` 即可避免。
        """
        with self._lock:
            return [
                job.request.output_path
                for job in self._jobs.values()
                if not job.state.is_finished
            ]

    def clear_finished(self) -> None:
        with self._lock:
            finished = [job_id for job_id, job in self._jobs.items() if not job.state.is_active]
            for job_id in finished:
                self._jobs.pop(job_id, None)
                self._cancel_events.pop(job_id, None)

    # ────────────────────────────── 监听器 ──────────────────────────────

    def add_listener(self, listener: ListenerFn) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self, event: str, job: RenderJob) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event, job)
            except Exception:  # noqa: BLE001 - 监听器异常不得影响队列
                continue

    # ────────────────────────────── 状态机 ──────────────────────────────

    def _transition_locked(
        self,
        job: _MutableJob,
        new_state: JobState,
        *,
        message: str | None = None,
        reset_progress: bool = False,
    ) -> None:
        if new_state is not job.state:
            legal = _LEGAL_TRANSITIONS.get(job.state, frozenset())
            if new_state not in legal:
                raise IllegalTransitionError(f"任务 {job.id} 不能从 {job.state.value} 迁移到 {new_state.value}。")
        job.state = new_state
        if message is not None:
            job.message = message
        if reset_progress:
            job.percent = 0.0
        if new_state is JobState.PREPARING:
            job.attempt += 1
            job.started_at = time.time()
            job.finished_at = None
        elif new_state.is_finished:
            job.finished_at = time.time()

    # ────────────────────────────── 独占调度 ──────────────────────────────

    def _requires_exclusive(self, job: _MutableJob) -> bool:
        """四屏且成片画幅面积达到 1280×720 时独占调度。"""
        four = job.request.four_screen
        if four is None:
            return False
        settings = job.request.settings
        width, height = settings.output_video.resolve_target_size(settings.width, settings.height)
        return width * height >= EXCLUSIVE_AREA_THRESHOLD

    # ────────────────────────────── 工作线程 ──────────────────────────────

    def _run_worker(self) -> None:
        while True:
            with self._lock:
                while not self._stop_requested:
                    if self._paused or not self._pending:
                        self._wakeup.wait(timeout=0.2)
                        continue
                    candidate_id = self._pending[0]
                    candidate = self._jobs.get(candidate_id)
                    if candidate is None:
                        self._pending.pop(0)
                        continue

                    # 排队中的任务尚未占用资源，不能参与独占判断，否则
                    # 四屏任务与它前后等待的任务会互相等待，整批无法出队。
                    executing = [
                        job for job in self._jobs.values()
                        if job.state in (JobState.PREPARING, JobState.RUNNING, JobState.FINALIZING)
                    ]

                    # 独占任务运行期间不再启动其他任务。
                    if any(self._requires_exclusive(job) for job in executing):
                        self._wakeup.wait(timeout=0.2)
                        continue
                    # 独占任务必须等所有其他活动任务结束后再开始。
                    if self._requires_exclusive(candidate) and executing:
                        self._wakeup.wait(timeout=0.2)
                        continue
                    break

                if self._stop_requested:
                    return

                job_id = self._pending.pop(0)
                job = self._jobs[job_id]
                cancel_event = self._cancel_events[job_id]
                self._transition_locked(job, JobState.PREPARING)
                preparing_snapshot = job.snapshot()

            self._notify("updated", preparing_snapshot)

            try:
                self._transition(JobState.RUNNING, job_id)
                runner_kwargs: dict = {
                    "on_progress": self._make_progress_handler(job_id),
                    "cancel_event": cancel_event,
                }
                if self._runner_accepts_job_id:
                    runner_kwargs["job_id"] = job_id
                output = self._runner(self._ffmpeg_path, job.request, **runner_kwargs)
                self._transition(JobState.FINALIZING, job_id)
                self._transition(
                    JobState.COMPLETED,
                    job_id,
                    message=f"完成：{Path(output).name}",
                    percent=100.0,
                )
            except RenderCancelled:
                self._transition(JobState.CANCELLED, job_id, message="已取消")
            except KeyboardInterrupt:
                raise
            except BaseException as error:  # noqa: BLE001 - 任何异常都要隔离到单个任务
                message = str(error) if isinstance(error, (RenderError, OSError)) else f"未预期错误：{error!r}"
                self._transition(JobState.FAILED, job_id, message=message, can_retry=True)

    def _transition(
        self,
        new_state: JobState,
        job_id: str,
        *,
        message: str | None = None,
        percent: float | None = None,
        can_retry: bool | None = None,
    ) -> RenderJob:
        with self._lock:
            job = self._jobs[job_id]
            self._transition_locked(job, new_state, message=message)
            if percent is not None:
                job.percent = percent
            if can_retry is not None:
                job.can_retry = can_retry
            snapshot = job.snapshot()
            if new_state.is_finished:
                self._wakeup.notify_all()
        self._notify("finished" if new_state.is_finished else "updated", snapshot)
        return snapshot

    def _make_progress_handler(self, job_id: str) -> Callable[[RenderProgress], None]:
        last_notify_at = time.monotonic()
        last_percent = -100.0

        def handler(progress: RenderProgress) -> None:
            nonlocal last_notify_at, last_percent
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.percent = progress.percent
                if progress.speed:
                    job.message = (
                        f"{progress.rendered_seconds:.1f}s / {progress.total_seconds:.1f}s · {progress.speed}"
                    )
                now = time.monotonic()
                should_notify = (
                    abs(progress.percent - last_percent) >= NOTIFY_PERCENT_DELTA
                    or now - last_notify_at >= NOTIFY_THROTTLE_SECONDS
                )
                if not should_notify:
                    return
                last_percent = progress.percent
                last_notify_at = now
                snapshot = job.snapshot()
            self._notify("updated", snapshot)

        return handler

    def _trim_history_locked(self) -> None:
        if len(self._jobs) <= self._max_history:
            return
        finished = sorted(
            (job for job in self._jobs.values() if job.state.is_finished),
            key=lambda job: job.created_at,
        )
        for job in finished[: len(self._jobs) - self._max_history]:
            self._jobs.pop(job.id, None)
            self._cancel_events.pop(job.id, None)
