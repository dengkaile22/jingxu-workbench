"""批量下载：优先 yt-dlp，缺失时回退直链 HTTP 下载。"""

from __future__ import annotations

import itertools
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".mp3", ".m4a", ".flv", ".avi"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JingXuWorkbench/0.1"
INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
MAX_FILENAME_LENGTH = 120


def sanitize_filename(name: str) -> str:
    """清理用户输入的文件名基名：剔除非法/控制字符并限制长度。"""
    chars: list[str] = []
    for char in name or "":
        if char in INVALID_FILENAME_CHARS:
            continue
        if ord(char) < 32 or ord(char) == 127:  # 控制字符
            continue
        chars.append(char)
    cleaned = re.sub(r"\s+", " ", "".join(chars)).strip()
    cleaned = cleaned.rstrip(". ")
    cleaned = cleaned[:MAX_FILENAME_LENGTH].rstrip(". ")
    return cleaned or "未命名"


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """在目录内返回不冲突的文件路径；冲突时追加 _001 形式的序号。"""
    directory = Path(directory)
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = directory / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


class DownloadState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def display_text(self) -> str:
        return {
            "pending": "等待中",
            "running": "下载中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }[self.value]


@dataclass
class DownloadJob:
    id: str
    url: str
    state: DownloadState = DownloadState.PENDING
    title: str = ""
    filename: str = ""
    percent: float = 0.0
    speed: str = ""
    message: str = ""
    output_path: Path | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def display_name(self) -> str:
        return self.title or self.url

    @property
    def display_filename(self) -> str:
        """文件名回退顺序：用户指定 → 标题 → 链接。"""
        return self.filename or self.title or self.url

    @property
    def is_active(self) -> bool:
        return self.state in (DownloadState.PENDING, DownloadState.RUNNING)


ProgressCallback = Callable[[float, str, str], None]
CancelEvent = threading.Event


class DownloadError(RuntimeError):
    """下载失败。"""


class DownloadCancelled(DownloadError):
    """下载被取消。"""


def yt_dlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def download_with_yt_dlp(
    url: str,
    output_directory: Path,
    on_progress: ProgressCallback,
    cancel_event: CancelEvent,
    filename: str = "",
) -> Path:
    """使用 yt-dlp 下载（支持抖音/快手/B站等站点）。"""
    import yt_dlp

    output_directory.mkdir(parents=True, exist_ok=True)
    safe = sanitize_filename(filename) if filename and filename.strip() else ""
    template = f"{safe}.%(ext)s" if safe else "%(title).80s_%(id)s.%(ext)s"
    state: dict[str, object] = {"path": None, "title": ""}

    def hook(payload: dict) -> None:
        if cancel_event.is_set():
            raise DownloadCancelled("下载已取消。")
        status = payload.get("status")
        if status == "downloading":
            total = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
            done = payload.get("downloaded_bytes") or 0
            percent = (done / total * 100) if total else 0.0
            speed = payload.get("_speed_str") or ""
            on_progress(percent, speed, "")
        elif status == "finished":
            on_progress(100.0, "", "合并中…")

    options = {
        "outtmpl": str(output_directory / template),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "http_headers": {"User-Agent": USER_AGENT},
        # 与 .NET 版一致的稳健性选项：断点续传、分片并发与重试。
        "continuedl": True,
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
    }
    cookies_file = os.environ.get("JINGXU_YTDLP_COOKIES", "").strip()
    if cookies_file and Path(cookies_file).is_file():
        options["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if info is None:
                raise DownloadError("未能解析该链接。")
            state["title"] = str(info.get("title") or "")
            path = info.get("requested_downloads") or []
            if path:
                candidate = Path(path[0].get("filepath") or "")
            else:
                candidate = Path(downloader.prepare_filename(info))
            if candidate.suffix.lower() not in MEDIA_SUFFIXES:
                candidate = candidate.with_suffix(".mp4")
            if not candidate.is_file():
                merged = candidate.with_suffix(".mp4")
                if merged.is_file():
                    candidate = merged
            if safe and not candidate.is_file():
                for existing in output_directory.iterdir():
                    if existing.is_file() and existing.stem == safe and existing.suffix.lower() in MEDIA_SUFFIXES:
                        candidate = existing
                        break
            if safe and candidate.is_file() and candidate.stem != safe:
                target = _unique_path(candidate.parent, safe, candidate.suffix or ".mp4")
                candidate.replace(target)
                candidate = target
            state["path"] = candidate
    except DownloadCancelled:
        raise
    except Exception as error:  # noqa: BLE001 - yt-dlp 抛出的异常类型繁多
        if cancel_event.is_set():
            raise DownloadCancelled("下载已取消。") from error
        # yt-dlp 原文（如一大串 Unsupported URL）对用户毫无指导意义，
        # 换成可照做的说明；其余错误保留原文便于排查。
        raw = str(error)
        if "Unsupported URL" in raw or "unsupported url" in raw.lower():
            message = describe_unsupported_url(url)
        else:
            message = f"下载失败：{raw}"
        log_download_error(url, f"{message}\n  原始错误：{raw}")
        raise DownloadError(message) from error

    path = state["path"]
    if path is None or not Path(path).is_file():
        raise DownloadError("下载完成但未找到输出文件。")
    on_progress(100.0, "", str(state["title"]))
    return Path(path)


def download_direct(
    url: str,
    output_directory: Path,
    on_progress: ProgressCallback,
    cancel_event: CancelEvent,
    filename: str = "",
) -> Path:
    """直链回退：仅适用于 URL 本身指向媒体文件的场景。"""
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in MEDIA_SUFFIXES:
        raise DownloadError("未安装 yt-dlp，且该链接不是可直连的媒体文件。请安装：pip install yt-dlp")

    output_directory.mkdir(parents=True, exist_ok=True)
    if filename and filename.strip():
        name = sanitize_filename(filename) + (suffix or ".mp4")
    else:
        name = Path(urllib.parse.unquote(parsed.path)).name or f"download_{uuid.uuid4().hex[:8]}"
    output_path = output_directory / name
    part_path = output_path.with_name(output_path.name + ".part")

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, part_path.open("wb") as sink:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            last_report = 0.0
            while True:
                if cancel_event.is_set():
                    raise DownloadCancelled("下载已取消。")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                sink.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last_report >= 0.2:
                    last_report = now
                    percent = (done / total * 100) if total else 0.0
                    on_progress(percent, "", "")
    except DownloadCancelled:
        part_path.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as error:
        part_path.unlink(missing_ok=True)
        message = describe_http_error(error.code)
        log_download_error(url, f"HTTP {error.code} {message}")
        raise DownloadError(message) from error
    except (urllib.error.URLError, TimeoutError) as error:
        part_path.unlink(missing_ok=True)
        reason = getattr(error, "reason", error)
        message = f"网络错误：{reason}。请检查网络或稍后重试。"
        log_download_error(url, message)
        raise DownloadError(message) from error
    except OSError as error:
        part_path.unlink(missing_ok=True)
        log_download_error(url, f"IO 错误：{error}")
        raise DownloadError(f"下载失败：{error}") from error

    if output_path.exists():
        output_path.unlink()
    part_path.replace(output_path)
    on_progress(100.0, "", name)
    return output_path


_HTTP_ERROR_MESSAGES = {
    401: "需要登录或授权（401）。请在浏览器登录后重试，或设置 JINGXU_YTDLP_COOKIES。",
    403: "服务器拒绝访问（403）。请更新 yt-dlp 或设置 cookies 后重试。",
    404: "链接已失效或内容不存在（404）。",
    429: "请求过于频繁（429）。请稍后重试。",
    503: "服务暂时不可用（503）。请稍后重试。",
}


def describe_http_error(status: int) -> str:
    """把常见 HTTP 状态映射为可操作的中文提示（对齐 .NET 下载错误映射）。"""
    return _HTTP_ERROR_MESSAGES.get(status, f"下载失败：服务器返回 HTTP {status}。")


# 主页/个人页链接：yt-dlp 不支持，且这类链接在选品流程里很常见
# （用户从对标账号复制分享文案得到的就是主页链接）。
_PROFILE_URL_MARKERS = (
    "/user/",
    "/profile/",
    "/share/user/",
    "live.kuaishou.com/profile",
)


def looks_like_profile_url(url: str) -> bool:
    """判断是否为主页/个人页链接而非单个视频链接。"""
    lowered = (url or "").lower()
    return any(marker in lowered for marker in _PROFILE_URL_MARKERS)


def describe_unsupported_url(url: str) -> str:
    """把「不支持的链接」翻译成用户能照做的说明。

    直接抛 yt-dlp 原文会让用户看到一大串 ``Unsupported URL: https://...``，
    既不知道原因也不知道怎么改；实测用户正是被这个误导为「下载功能失效」。
    """
    if looks_like_profile_url(url):
        return (
            "这是账号主页链接，不是单个视频链接，下载器无法处理。\n"
            "请在抖音/快手里打开要下载的那条视频，用「分享 → 复制链接」取得视频链接。"
        )
    return (
        "该链接不被下载器支持（可能是短剧/直播等特殊页面）。\n"
        "请改用视频的分享链接，或先确认该内容可正常播放。"
    )


def log_download_error(url: str, message: str) -> None:
    """把下载失败写入 ``<数据目录>/logs/download-YYYYMMDD.log``（失败静默）。"""
    try:
        from jingxu.infrastructure.diagnostics import logs_directory

        directory = logs_directory()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"download-{time.strftime('%Y%m%d')}.log"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {url}\n  {message}\n")
    except OSError:
        pass


class DownloadQueue:
    """单工作线程顺序下载；事件通过监听器通知（UI 层负责切回主线程）。"""

    def __init__(self, output_directory: Path, *, downloader: Callable[..., Path] | None = None) -> None:
        self._output_directory = Path(output_directory)
        self._downloader = downloader or (download_with_yt_dlp if yt_dlp_available() else download_direct)

        self._pending: list[str] = []
        self._jobs: dict[str, DownloadJob] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._listeners: list[Callable[[str, DownloadJob], None]] = []

        self._lock = threading.RLock()
        self._wakeup = threading.Condition(self._lock)
        self._stop_requested = False
        self._worker: threading.Thread | None = None

    # ────────────────────────────── 生命周期 ──────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop_requested = False
            self._worker = threading.Thread(target=self._run_worker, name="jingxu-download-queue", daemon=True)
            self._worker.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.cancel_all()
        with self._lock:
            self._stop_requested = True
            self._wakeup.notify_all()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
        self._worker = None

    # ────────────────────────────── 队列操作 ──────────────────────────────

    def set_output_directory(self, directory: Path) -> None:
        self._output_directory = Path(directory)

    def enqueue(self, urls: list[str]) -> list[DownloadJob]:
        jobs: list[DownloadJob] = []
        with self._lock:
            for url in urls:
                clean = url.strip()
                if not clean:
                    continue
                job = DownloadJob(id=uuid.uuid4().hex[:12], url=clean)
                self._jobs[job.id] = job
                self._pending.append(job.id)
                self._cancel_events[job.id] = threading.Event()
                jobs.append(job)
            self._wakeup.notify_all()
        for job in jobs:
            self._notify("added", job)
        if jobs:
            self.start()  # 入队即确保调度在线
        return jobs

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not job.is_active:
                return False
            self._cancel_events[job_id].set()
            if job.state is DownloadState.PENDING and job_id in self._pending:
                self._pending.remove(job_id)
                job.state = DownloadState.CANCELLED
                job.finished_at = time.time()
                job.message = "已取消"
        if job.state is DownloadState.CANCELLED:
            self._notify("finished", job)
        return True

    def cancel_all(self) -> None:
        with self._lock:
            active = [job_id for job_id, job in self._jobs.items() if job.is_active]
        for job_id in active:
            self.cancel(job_id)

    def set_filename(self, job_id: str, filename: str) -> bool:
        """设置任务的文件名基名；已完成任务会同步重命名磁盘文件。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.filename = sanitize_filename(filename)
            if job.state is DownloadState.COMPLETED and job.output_path is not None:
                source = Path(job.output_path)
                if source.is_file() and source.stem != job.filename:
                    target = _unique_path(source.parent, job.filename, source.suffix)
                    try:
                        source.replace(target)
                    except OSError as error:
                        job.message = f"重命名失败：{error}"
                    else:
                        job.output_path = target
                        job.message = f"完成：{target.name}"
        self._notify("updated", job)
        return True

    def clear_finished(self) -> None:
        """移除已结束（完成/失败/取消）任务的记录，未结束的任务保持不动。

        **必须同时清掉 ``_pending`` 里的 ID**：工作线程是按「先 pop ID、再查
        ``_jobs``」取任务的，只删 ``_jobs`` 会在待办队列里留下悬空 ID，
        线程随后就 ``self._jobs[job_id]`` 抛 KeyError 并整体退出——
        表现为"下载列表点了清空之后，新任务再也不开始"。
        """
        with self._lock:
            for job_id in [job.id for job in self._jobs.values() if not job.is_active]:
                self._jobs.pop(job_id, None)
                self._cancel_events.pop(job_id, None)
                if job_id in self._pending:
                    self._pending.remove(job_id)

    @property
    def jobs(self) -> list[DownloadJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at)

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.is_active)

    def add_listener(self, listener: Callable[[str, DownloadJob], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self, event: str, job: DownloadJob) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event, job)
            except Exception:  # noqa: BLE001 - 监听器异常不得影响队列
                continue

    # ────────────────────────────── 工作线程 ──────────────────────────────

    def _run_worker(self) -> None:
        while True:
            with self._lock:
                while not self._pending and not self._stop_requested:
                    self._wakeup.wait(timeout=0.3)
                if self._stop_requested:
                    return
                job_id = self._pending.pop(0)
                job = self._jobs.get(job_id)
                if job is None:
                    # 已被清理/取消：待办里不该再出现它的 ID，跳过而不是崩溃。
                    self._cancel_events.pop(job_id, None)
                    continue
                cancel_event = self._cancel_events.get(job_id) or threading.Event()

            job.state = DownloadState.RUNNING
            self._notify("updated", job)
            counter = itertools.count()

            def on_progress(percent: float, speed: str, title: str, _job=job, _counter=counter) -> None:
                if title:
                    _job.title = title
                _job.percent = percent
                _job.speed = speed
                if next(_counter) % 4 == 0:
                    self._notify("updated", _job)

            try:
                output = self._downloader(
                    job.url,
                    self._output_directory,
                    on_progress,
                    cancel_event,
                    filename=job.filename,
                )
                job.output_path = Path(output)
                job.state = DownloadState.COMPLETED
                job.percent = 100.0
                job.message = f"完成：{job.output_path.name}"
            except DownloadCancelled:
                job.state = DownloadState.CANCELLED
                job.message = "已取消"
            except DownloadError as error:
                job.state = DownloadState.FAILED
                job.message = str(error)
            except Exception as error:  # noqa: BLE001 - 单任务失败不得影响队列
                job.state = DownloadState.FAILED
                job.message = f"未预期错误：{error!r}"
            finally:
                job.finished_at = time.time()
                self._notify("finished", job)


def default_download_directory() -> Path:
    """默认下载目录：用户下载文件夹下的「镜序素材」。"""
    downloads = Path.home() / "Downloads"
    base = downloads if downloads.is_dir() else Path.home()
    return base / "镜序素材"


def has_yt_dlp() -> bool:
    return shutil.which("yt-dlp") is not None or yt_dlp_available()
