"""截取优化后的队列页（含演示任务数据），用于人工核对陈列效果。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[2]  # 仓库根，随仓库移动
ROOT = Path(__file__).resolve().parent.parent
os.environ["JINGXU_DATA_DIRECTORY"] = str(ROOT / "appdata")
sys.path.insert(0, str(APP / "core"))

SHOTS = ROOT / "shots"
DEMO = ROOT / "demo"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.queue import JobState, RenderQueue  # noqa: E402
from jingxu.infrastructure.runtime import require_tool  # noqa: E402
from jingxu.ui.assets_loader import register_bundled_fonts  # noqa: E402
from jingxu.ui.shell_window import MODULE_QUEUE, ShellWindow  # noqa: E402
from jingxu.ui.theme import apply_application_theme  # noqa: E402

PRODUCTS = sorted((DEMO / "products").glob("*.mp4"))


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    app = QApplication.instance() or QApplication(["jingxu"])
    register_bundled_fonts()
    apply_application_theme(app)
    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")
    queue = RenderQueue(ffmpeg)
    win = ShellWindow(ffmpeg, ffprobe, queue)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(1920, 1080)
    win.show()
    pump(app, 1.0)

    win._select_module(MODULE_QUEUE)
    win._add_materials([str(path) for path in PRODUCTS])
    pump(app, 1.5)

    queue.pause()
    win._composition_page._batch_count.setValue(5)
    win._enqueue()
    jobs = queue.jobs
    order = [job.id for job in jobs]
    with queue._lock:
        internal = [queue._jobs[job_id] for job_id in order]
        if internal:
            running = internal[0]
            queue._transition_locked(running, JobState.PREPARING)
            queue._transition_locked(running, JobState.RUNNING, message="渲染中")
            running.percent = 62.0
            running.message = "18.4s / 29.7s · 2.4x"
        if len(internal) >= 3:
            done = internal[2]
            queue._transition_locked(done, JobState.PREPARING)
            queue._transition_locked(done, JobState.RUNNING)
            queue._transition_locked(done, JobState.FINALIZING)
            queue._transition_locked(done, JobState.COMPLETED, message="完成：混剪_003.mp4")
            done.percent = 100.0
        if len(internal) >= 4:
            retried = internal[3]
            queue._transition_locked(retried, JobState.PREPARING)
            queue._transition_locked(retried, JobState.RUNNING)
            queue._transition_locked(retried, JobState.FAILED, message="编码器不可用：nvenc 初始化失败")
            retried.percent = 37.0
            retried.can_retry = True
            retried.attempt = 2
        snapshots = [job.snapshot() for job in internal]
    for snapshot in snapshots:
        queue._notify("updated", snapshot)
    pump(app, 0.8)

    SHOTS.mkdir(parents=True, exist_ok=True)
    image = win.grab()
    target = SHOTS / "queue.png"
    image.save(str(target))
    print("saved", target, image.width(), image.height(), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
