"""截取优化后的下载页（注入演示任务），用于人工核对陈列效果。"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[2]  # 仓库根，随仓库移动
ROOT = Path(__file__).resolve().parent.parent
os.environ["JINGXU_DATA_DIRECTORY"] = str(ROOT / "appdata")
sys.path.insert(0, str(APP / "core"))

SHOTS = ROOT / "shots"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.downloader import DownloadJob, DownloadState, default_download_directory  # noqa: E402
from jingxu.infrastructure.queue import RenderQueue  # noqa: E402
from jingxu.infrastructure.runtime import require_tool  # noqa: E402
from jingxu.ui.assets_loader import register_bundled_fonts  # noqa: E402
from jingxu.ui.shell_window import MODULE_DOWNLOADS, ShellWindow  # noqa: E402
from jingxu.ui.theme import apply_application_theme  # noqa: E402


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


DEMO_JOBS = [
    DownloadJob(
        id="demo-1",
        url="https://www.douyin.com/video/7418529637418529637",
        state=DownloadState.COMPLETED,
        title="口红测评合集：三支热门色号上嘴对比",
        filename="口红测评合集",
        percent=100.0,
        message="完成：口红测评合集.mp4",
    ),
    DownloadJob(
        id="demo-2",
        url="https://www.douyin.com/video/7418529637418529638",
        state=DownloadState.RUNNING,
        title="保湿面霜开箱测评",
        filename="保湿面霜开箱",
        percent=62.0,
        speed="2.4MiB/s",
        message="12.4MB / 20.0MB",
    ),
    DownloadJob(
        id="demo-3",
        url="https://v.kuaishou.com/s/8XkQm2A",
        state=DownloadState.PENDING,
        title="零食研究所：直播间爆款清单",
        filename="3",
    ),
    DownloadJob(
        id="demo-4",
        url="https://www.bilibili.com/video/BV1xx411c7mD",
        state=DownloadState.FAILED,
        title="空气炸锅美食教程",
        filename="空气炸锅美食",
        percent=37.0,
        message="下载失败：HTTP 403 Forbidden（链接可能已失效）",
    ),
]


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

    win._select_module(MODULE_DOWNLOADS)
    pump(app, 0.6)

    page = win._download_page
    page._directory_edit.setText(str(default_download_directory()))
    download_queue = page._queue
    with download_queue._lock:
        for job in DEMO_JOBS:
            download_queue._jobs[job.id] = job
            download_queue._cancel_events[job.id] = threading.Event()
    for job in DEMO_JOBS:
        download_queue._notify("added", job)
    pump(app, 1.2)

    SHOTS.mkdir(parents=True, exist_ok=True)
    image = win.grab()
    target = SHOTS / "downloads.png"
    image.save(str(target))
    print("saved", target, image.width(), image.height(), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
