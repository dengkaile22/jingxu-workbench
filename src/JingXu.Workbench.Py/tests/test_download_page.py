"""下载任务文件名清理、队列改名与下载页行内编辑测试。"""

from __future__ import annotations

import os
import sys
import threading
import types
import urllib.request
from pathlib import Path

import pytest
from conftest import wait_until

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.downloader import (  # noqa: E402
    DownloadError,
    DownloadJob,
    DownloadQueue,
    DownloadState,
    _unique_path,
    download_direct,
    download_with_yt_dlp,
    sanitize_filename,
)

# ────────────────────────────── 纯函数 ──────────────────────────────


def test_sanitize_filename_removes_invalid_and_control_chars() -> None:
    assert sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"
    assert sanitize_filename("空\x00白\x1f字") == "空白字"


def test_sanitize_filename_strips_edges_and_trailing_dots() -> None:
    assert sanitize_filename("  视频 名...  ") == "视频 名"
    assert sanitize_filename("name. ") == "name"
    assert sanitize_filename("  <名称>  ") == "名称"


def test_sanitize_filename_collapses_whitespace() -> None:
    assert sanitize_filename("a   b") == "a b"
    assert sanitize_filename("a\t\t b") == "a b"
    assert sanitize_filename("  两端  空白  ") == "两端 空白"


def test_sanitize_filename_truncates_to_120_chars() -> None:
    assert sanitize_filename("长" * 130) == "长" * 120
    assert sanitize_filename("a" * 119 + "." + "b" * 10) == "a" * 119


def test_sanitize_filename_falls_back_to_default_name() -> None:
    assert sanitize_filename("") == "未命名"
    assert sanitize_filename("   ") == "未命名"
    assert sanitize_filename('<>:"/\\|?*') == "未命名"


def test_unique_path_appends_sequence_on_conflict(tmp_path: Path) -> None:
    assert _unique_path(tmp_path, "名字", ".mp4") == tmp_path / "名字.mp4"
    (tmp_path / "名字.mp4").write_bytes(b"x")
    assert _unique_path(tmp_path, "名字", ".mp4") == tmp_path / "名字_001.mp4"
    (tmp_path / "名字_001.mp4").write_bytes(b"x")
    assert _unique_path(tmp_path, "名字", ".mp4") == tmp_path / "名字_002.mp4"


def test_display_filename_falls_back_to_title_then_url() -> None:
    job = DownloadJob(id="x", url="https://example.com/a")
    assert job.display_filename == "https://example.com/a"
    job.title = "标题"
    assert job.display_filename == "标题"
    job.filename = "自定义"
    assert job.display_filename == "自定义"


# ────────────────────────────── 下载器 ──────────────────────────────


def test_download_with_yt_dlp_uses_safe_name_and_renames(monkeypatch, tmp_path: Path) -> None:
    seen: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, options: dict) -> None:
            seen.append(options)

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            produced = tmp_path / "标题_abc.mp4"
            produced.write_bytes(b"stub")
            return {"title": "标题", "requested_downloads": [{"filepath": str(produced)}]}

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    (tmp_path / "我的 视频.mp4").write_bytes(b"occupied")

    path = download_with_yt_dlp(
        "https://example.com/a",
        tmp_path,
        lambda *_args: None,
        threading.Event(),
        filename="我的 视频.",
    )

    assert seen[0]["outtmpl"] == str(tmp_path / "我的 视频.%(ext)s")
    assert path == tmp_path / "我的 视频_001.mp4"
    assert path.read_bytes() == b"stub"
    assert (tmp_path / "我的 视频.mp4").read_bytes() == b"occupied"
    assert not (tmp_path / "标题_abc.mp4").exists()


def test_download_with_yt_dlp_finds_merged_file_after_extension_change(monkeypatch, tmp_path: Path) -> None:
    class FakeYoutubeDL:
        def __init__(self, options: dict) -> None:
            pass

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            (tmp_path / "成片.mp4").write_bytes(b"merged")
            missing = tmp_path / "成片.webm"
            return {"title": "标题", "requested_downloads": [{"filepath": str(missing)}]}

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    path = download_with_yt_dlp(
        "https://example.com/a",
        tmp_path,
        lambda *_args: None,
        threading.Event(),
        filename="成片",
    )

    assert path == tmp_path / "成片.mp4"
    assert path.read_bytes() == b"merged"


def test_download_with_yt_dlp_keeps_default_template_without_filename(monkeypatch, tmp_path: Path) -> None:
    seen: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, options: dict) -> None:
            seen.append(options)

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            produced = tmp_path / "标题_abc.mp4"
            produced.write_bytes(b"stub")
            return {"title": "标题", "requested_downloads": [{"filepath": str(produced)}]}

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    path = download_with_yt_dlp("https://example.com/a", tmp_path, lambda *_args: None, threading.Event())

    assert seen[0]["outtmpl"] == str(tmp_path / "%(title).80s_%(id)s.%(ext)s")
    assert path == tmp_path / "标题_abc.mp4"
    assert path.is_file()


def test_download_direct_uses_sanitized_filename(monkeypatch, tmp_path: Path) -> None:
    payload = [b"data", b""]

    class FakeResponse:
        headers = {"Content-Length": "4"}

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self, _size: int = -1) -> bytes:
            return payload.pop(0)

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=30: FakeResponse())
    progress: list[tuple[float, str, str]] = []

    path = download_direct(
        "https://example.com/video.mov",
        tmp_path,
        lambda percent, speed, title: progress.append((percent, speed, title)),
        threading.Event(),
        filename="直链 视频.",
    )

    assert path == tmp_path / "直链 视频.mov"
    assert path.read_bytes() == b"data"
    assert progress[-1] == (100.0, "", "直链 视频.mov")


# ────────────────────────────── 队列 ──────────────────────────────


class RecordingDownloader:
    """记录调用参数并写出占位文件的下载替身；filename 必须以关键字传入。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def __call__(
        self,
        url: str,
        output_directory: Path,
        on_progress,
        cancel_event,
        *,
        filename: str = "",
    ) -> Path:
        with self._lock:
            self.calls.append({"url": url, "filename": filename})
        on_progress(100.0, "", filename or "stub")
        path = Path(output_directory) / f"{filename or 'stub'}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stub")
        return path


class GatedDownloader(RecordingDownloader):
    """首个任务阻塞，便于在 worker 忙碌时修改后续任务的文件名。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(
        self,
        url: str,
        output_directory: Path,
        on_progress,
        cancel_event,
        *,
        filename: str = "",
    ) -> Path:
        with self._lock:
            self.calls.append({"url": url, "filename": filename})
        if url.endswith("first"):
            self.started.set()
            if not self.release.wait(timeout=5):
                raise DownloadError("测试闸门超时。")
        on_progress(100.0, "", filename or "stub")
        path = Path(output_directory) / f"{filename or 'stub'}.mp4"
        path.write_bytes(b"stub")
        return path


@pytest.fixture()
def queue_factory(tmp_path: Path):
    queues: list[DownloadQueue] = []

    def factory(downloader) -> DownloadQueue:
        queue = DownloadQueue(tmp_path, downloader=downloader)
        queues.append(queue)
        return queue

    yield factory
    for queue in queues:
        queue.stop()


def test_set_filename_updates_pending_job_and_worker_receives_keyword(tmp_path: Path, queue_factory) -> None:
    downloader = GatedDownloader()
    queue = queue_factory(downloader)

    first = queue.enqueue(["https://example.com/first"])[0]
    assert downloader.started.wait(timeout=5)

    second = queue.enqueue(["https://example.com/second"])[0]
    try:
        assert second.state is DownloadState.PENDING
        assert queue.set_filename(second.id, "  第二  个.  ") is True
        assert second.filename == "第二 个"
    finally:
        downloader.release.set()

    wait_until(lambda: queue.active_count == 0)
    assert first.state is DownloadState.COMPLETED
    assert second.state is DownloadState.COMPLETED
    assert [call["filename"] for call in downloader.calls] == ["", "第二 个"]
    assert (tmp_path / "第二 个.mp4").is_file()


def test_set_filename_renames_completed_output(tmp_path: Path, queue_factory) -> None:
    queue = queue_factory(RecordingDownloader())
    job = queue.enqueue(["https://example.com/a"])[0]
    wait_until(lambda: job.state is DownloadState.COMPLETED)
    original = job.output_path
    assert original is not None and original == tmp_path / "stub.mp4"

    assert queue.set_filename(job.id, "新的 名字.") is True

    target = tmp_path / "新的 名字.mp4"
    assert target.is_file()
    assert not original.exists()
    assert job.filename == "新的 名字"
    assert job.output_path == target
    assert target.name in job.message


def test_set_filename_completed_conflict_uniqueifies(tmp_path: Path, queue_factory) -> None:
    queue = queue_factory(RecordingDownloader())
    job = queue.enqueue(["https://example.com/a"])[0]
    wait_until(lambda: job.state is DownloadState.COMPLETED)
    (tmp_path / "成片.mp4").write_bytes(b"occupied")

    assert queue.set_filename(job.id, "成片") is True

    assert (tmp_path / "成片.mp4").read_bytes() == b"occupied"
    assert (tmp_path / "成片_001.mp4").read_bytes() == b"stub"
    assert job.output_path == tmp_path / "成片_001.mp4"
    assert not (tmp_path / "stub.mp4").exists()


def test_set_filename_updates_failed_job_without_rename(queue_factory) -> None:
    def failing(url, output_directory, on_progress, cancel_event, *, filename=""):
        raise DownloadError("boom")

    queue = queue_factory(failing)
    job = queue.enqueue(["https://example.com/a"])[0]
    wait_until(lambda: job.state is DownloadState.FAILED)

    events: list[str] = []
    queue.add_listener(lambda event, _job: events.append(event))
    assert queue.set_filename(job.id, "新名") is True

    assert job.filename == "新名"
    assert job.message == "boom"
    assert job.output_path is None
    assert events[-1] == "updated"


def test_set_filename_missing_job_returns_false(queue_factory) -> None:
    queue = queue_factory(RecordingDownloader())
    assert queue.set_filename("missing-id", "名字") is False


# ────────────────────────────── 下载页 ──────────────────────────────


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def test_download_page_filename_column_inline_edit(qapp, tmp_path: Path, queue_factory) -> None:  # noqa: ANN001
    from jingxu.ui.download_page import COLUMNS, DownloadPage

    queue = queue_factory(RecordingDownloader())
    page = DownloadPage(queue)
    queue.set_output_directory(tmp_path)

    job = queue.enqueue(["https://example.com/a"])[0]

    def row_ready() -> bool:
        qapp.processEvents()
        return job.id in page._rows and job.state is DownloadState.COMPLETED

    wait_until(row_ready)
    qapp.processEvents()

    row = page._rows[job.id]
    assert COLUMNS == ("任务", "文件名", "状态", "进度", "速度", "说明")
    filename_item = page._table.item(row, 1)
    assert filename_item.text() == "stub"
    assert filename_item.flags() & Qt.ItemFlag.ItemIsEditable
    for column in (0, 2, 3, 4, 5):
        assert not (page._table.item(row, column).flags() & Qt.ItemFlag.ItemIsEditable)

    filename_item.setText("行内 编辑.")
    assert job.filename == "行内 编辑"
    assert page._table.item(row, 1).text() == "行内 编辑"
    assert (tmp_path / "行内 编辑.mp4").is_file()
    assert not (tmp_path / "stub.mp4").exists()


def test_download_page_clear_finished_resets_rows(qapp, tmp_path: Path, queue_factory) -> None:  # noqa: ANN001
    from jingxu.ui.download_page import DownloadPage

    queue = queue_factory(RecordingDownloader())
    page = DownloadPage(queue)
    queue.set_output_directory(tmp_path)
    queue.enqueue(["https://example.com/a"])

    def finished() -> bool:
        qapp.processEvents()
        return queue.active_count == 0 and page._table.rowCount() == 1

    wait_until(finished)

    page._clear_finished()

    assert page._table.rowCount() == 0
    assert page._rows == {}
    assert page._row_jobs == {}
