"""Tesseract OCR 硬字幕检测：抽帧 → TSV 解析 → 跨帧聚类。"""

from __future__ import annotations

import math
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from jingxu.domain.subtitles import DetectedSubtitleSegment
from jingxu.infrastructure.diagnostics import runtime_tesseract
from jingxu.infrastructure.process_control import no_window_kwargs
from jingxu.infrastructure.ffprobe import ProbeError, probe_media

SESSION_PREFIX = "jingxu-ocr-"
DEFAULT_SCAN_REGION = (0.0, 0.55, 1.0, 0.45)
DEFAULT_INTERVAL = 0.5
DEFAULT_MAX_FRAMES = 3600
DEFAULT_TIME_GAP = 1.5
DEFAULT_IOU_THRESHOLD = 0.35
DEFAULT_MIN_CONFIDENCE = 0.55
FRAME_EXTRACT_PROGRESS = (5.0, 40.0)
OCR_PROGRESS = 45.0
PARSE_PROGRESS = 92.0


class OcrError(RuntimeError):
    """OCR 检测失败。"""


class OcrCancelled(OcrError):
    """OCR 检测被取消。"""


@dataclass(frozen=True, slots=True)
class OcrWord:
    """Tesseract 行级文本：像素 bbox 与 0–1 置信度。"""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float
    page: int
    block: int
    par: int
    line: int


def find_tesseract() -> Path | None:
    """定位可用的 Tesseract（复用运行时诊断逻辑）。"""
    return runtime_tesseract()


def plan_frame_samples(
    duration: float,
    *,
    interval: float = DEFAULT_INTERVAL,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> list[float]:
    """规划抽帧时间点：短视频按固定间隔，超限时等距降采样并覆盖首尾。"""
    if duration <= 0 or interval <= 0 or max_frames <= 0:
        return []

    count = int(math.ceil(duration / interval - 1e-9))
    samples = [index * interval for index in range(count)]
    if len(samples) <= max_frames:
        return samples

    return [duration * index / max_frames for index in range(max_frames)]


def _header_index(header: Sequence[str]) -> dict[str, int]:
    return {name.strip().lower(): position for position, name in enumerate(header)}


def _cell(columns: Sequence[str], index: dict[str, int], name: str) -> str | None:
    position = index.get(name)
    if position is None or position >= len(columns):
        return None
    return columns[position]


def parse_tesseract_tsv(text: str) -> list[OcrWord]:
    """解析 Tesseract TSV（仅 level-5 词行），按页/块/段/行分组。"""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= 1:
        return []

    header = lines[0].split("\t")
    index = _header_index(header)

    grouped: dict[tuple[int, int, int, int], list[tuple[str, float, int, int, int, int]]] = {}
    order: list[tuple[int, int, int, int]] = []
    for row in lines[1:]:
        columns = row.split("\t")
        try:
            if int(_cell(columns, index, "level") or "") != 5:
                continue
        except ValueError:
            continue

        label = (_cell(columns, index, "text") or "").strip()
        if not label:
            continue
        try:
            page = int(_cell(columns, index, "page_num") or "")
            block = int(_cell(columns, index, "block_num") or "")
            par = int(_cell(columns, index, "par_num") or "")
            line = int(_cell(columns, index, "line_num") or "")
            confidence = float(_cell(columns, index, "conf") or "")
            left = int(_cell(columns, index, "left") or "")
            top = int(_cell(columns, index, "top") or "")
            width = int(_cell(columns, index, "width") or "")
            height = int(_cell(columns, index, "height") or "")
        except (TypeError, ValueError):
            continue

        key = (page, block, par, line)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((label, confidence, left, top, width, height))

    words: list[OcrWord] = []
    for key in order:
        members = grouped[key]
        joined = " ".join(member[0] for member in sorted(members, key=lambda member: member[2])).strip()
        if not joined:
            continue
        left = min(member[2] for member in members)
        top = min(member[3] for member in members)
        right = max(member[2] + member[4] for member in members)
        bottom = max(member[3] + member[5] for member in members)
        confidence = statistics.fmean(member[1] for member in members) / 100.0
        words.append(
            OcrWord(
                text=joined,
                left=left,
                top=top,
                width=max(0, right - left),
                height=max(0, bottom - top),
                confidence=confidence,
                page=key[0],
                block=key[1],
                par=key[2],
                line=key[3],
            )
        )
    return words


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """归一化框 (x, y, w, h) 的交并比。"""
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[0] + a[2], b[0] + b[2])
    bottom = min(a[1] + a[3], b[1] + b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = a[2] * a[3] + b[2] * b[3] - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _upper_median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def cluster_observations(
    observations: Sequence[tuple[float, float, float, float, float, float]],
    *,
    time_gap: float = DEFAULT_TIME_GAP,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    total_duration: float = 0.0,
) -> list[DetectedSubtitleSegment]:
    """把逐帧观测 (time, x, y, w, h, conf) 聚类为稳定字幕区域。"""
    ordered = sorted(observations, key=lambda observation: observation[0])
    if not ordered:
        return []

    clusters: list[list[tuple[float, float, float, float, float, float]]] = [[ordered[0]]]
    for observation in ordered[1:]:
        cluster = clusters[-1]
        latest = cluster[-1]
        gap = observation[0] - latest[0]
        overlap = iou(latest[1:5], observation[1:5])
        if gap <= time_gap and overlap >= iou_threshold:
            cluster.append(observation)
        else:
            clusters.append([observation])

    segments: list[DetectedSubtitleSegment] = []
    for cluster in clusters:
        left = _upper_median([item[1] for item in cluster])
        top = _upper_median([item[2] for item in cluster])
        right = _upper_median([item[1] + item[3] for item in cluster])
        bottom = _upper_median([item[2] + item[4] for item in cluster])
        start = min(item[0] for item in cluster)
        end = max(item[0] for item in cluster)
        if total_duration > 0:
            end = min(end, total_duration)
        confidence = statistics.fmean(item[5] for item in cluster)
        # 对齐 .NET SubtitleRegionClusterer：均值或任一观测低于阈值都需复核。
        needs_review = confidence < min_confidence or any(item[5] < min_confidence for item in cluster)
        segments.append(
            DetectedSubtitleSegment(
                x_percent=left * 100.0,
                y_percent=top * 100.0,
                width_percent=max(0.0, right - left) * 100.0,
                height_percent=max(0.0, bottom - top) * 100.0,
                start_seconds=start,
                end_seconds=end,
                confidence=confidence,
                requires_review=needs_review,
            )
        )
    return segments


def map_box_to_scan_region(
    box: tuple[float, float, float, float],
    scan_region: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """把扫描区内的相对框映射回全画面坐标。"""
    x, y, width, height = box
    region_x, region_y, region_width, region_height = scan_region
    return (
        region_x + x * region_width,
        region_y + y * region_height,
        width * region_width,
        height * region_height,
    )


def _extract_frame(ffmpeg_path: Path, video_path: Path, timestamp: float, output_path: Path) -> bool:
    """抽取单帧 PNG，成功返回 True。"""
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            **no_window_kwargs(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120.0,
        )
    except subprocess.TimeoutExpired:
        return False
    except OSError as error:
        raise OcrError(f"无法启动 FFmpeg：{error}") from error
    return completed.returncode == 0 and output_path.is_file()


def _run_tesseract(
    tesseract_path: Path,
    list_file: Path,
    *,
    language: str,
    session_dir: Path,
    timeout: float = 600.0,
    cancel_event: threading.Event | None = None,
) -> str:
    """以 TSV 输出批量识别 frames.txt，返回标准输出文本。"""
    command = [str(tesseract_path), list_file.name, "stdout", "-l", language, "tsv"]
    stdout_path = session_dir / "ocr-output.tsv"
    stderr_path = session_dir / "ocr-error.log"
    try:
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(command, **no_window_kwargs(), cwd=str(session_dir), stdout=stdout_file, stderr=stderr_file)
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.kill()
                    process.wait()
                    raise OcrCancelled("OCR 检测已取消。")
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait()
                    raise OcrError("Tesseract 运行超时。")
                time.sleep(0.1)
    except OSError as error:
        raise OcrError(f"无法启动 Tesseract：{error}") from error

    if process.returncode != 0:
        detail = [
            line.strip()
            for line in stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        tail = detail[-1] if detail else f"退出码 {process.returncode}"
        raise OcrError(f"Tesseract 运行失败：{tail}")
    return stdout_path.read_text(encoding="utf-8", errors="replace")


def _parse_page_sizes(text: str) -> dict[int, tuple[float, float]]:
    """从 TSV 的 level-1 行提取每页像素尺寸，用于归一化词框。"""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= 1:
        return {}
    index = _header_index(lines[0].split("\t"))
    sizes: dict[int, tuple[float, float]] = {}
    for row in lines[1:]:
        columns = row.split("\t")
        try:
            if int(_cell(columns, index, "level") or "") != 1:
                continue
            page = int(_cell(columns, index, "page_num") or "")
            width = float(_cell(columns, index, "width") or "")
            height = float(_cell(columns, index, "height") or "")
        except (TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            sizes[page] = (width, height)
    return sizes


def detect_subtitle_regions(
    ffmpeg_path: Path,
    video_path: Path,
    *,
    duration: float | None = None,
    ffprobe_path: Path | None = None,
    tesseract_path: Path | None = None,
    scan_region: tuple[float, float, float, float] = DEFAULT_SCAN_REGION,
    interval: float = DEFAULT_INTERVAL,
    language: str = "chi_sim+eng",
    on_progress: Callable[[float, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    temp_directory: Path | None = None,
    timeout: float = 600.0,
) -> list[DetectedSubtitleSegment]:
    """FFmpeg 抽帧 + Tesseract OCR，返回检测到的硬字幕区域。"""
    video = Path(video_path)
    if not video.is_file():
        raise OcrError(f"素材不存在：{video}")

    def report(percent: float, text: str) -> None:
        if on_progress is not None:
            on_progress(percent, text)

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise OcrCancelled("OCR 检测已取消。")

    check_cancelled()
    report(1.0, "准备 OCR…")

    frame_width = 0.0
    frame_height = 0.0
    if duration is None:
        probe_tool = Path(ffprobe_path) if ffprobe_path is not None else None
        if probe_tool is None:
            located = shutil.which("ffprobe")
            probe_tool = Path(located) if located else None
        if probe_tool is None:
            raise OcrError("未找到 FFprobe，无法获取视频时长；请安装 FFprobe 或显式传入 duration。")
        try:
            media = probe_media(video, probe_tool)
        except ProbeError as error:
            raise OcrError(str(error)) from error
        duration = media.duration
        frame_width = float(media.width)
        frame_height = float(media.height)

    tesseract = Path(tesseract_path) if tesseract_path is not None else find_tesseract()
    if tesseract is None:
        raise OcrError("未找到 Tesseract OCR。请将 Tesseract 放入 runtime/tesseract/，或加入系统 PATH。")

    samples = plan_frame_samples(float(duration), interval=interval)
    if not samples:
        return []

    try:
        session_dir = Path(
            tempfile.mkdtemp(prefix=f"{SESSION_PREFIX}{uuid.uuid4().hex[:8]}-", dir=temp_directory)
        )
    except OSError as error:
        raise OcrError(f"无法创建 OCR 临时目录：{error}") from error

    try:
        frame_paths: list[Path] = []
        frame_times: list[float] = []
        total = len(samples)
        for position, timestamp in enumerate(samples):
            check_cancelled()
            frame_path = session_dir / f"frame_{position:04d}.png"
            if _extract_frame(Path(ffmpeg_path), video, timestamp, frame_path):
                frame_paths.append(frame_path)
                frame_times.append(timestamp)
            report(
                FRAME_EXTRACT_PROGRESS[0]
                + (FRAME_EXTRACT_PROGRESS[1] - FRAME_EXTRACT_PROGRESS[0]) * (position + 1) / total,
                f"抽帧 {position + 1}/{total}",
            )

        if not frame_paths:
            raise OcrError("抽帧失败，无法继续 OCR。")

        check_cancelled()
        list_file = session_dir / "frames.txt"
        list_file.write_text("".join(f"{path}\n" for path in frame_paths), encoding="utf-8")

        report(OCR_PROGRESS, "正在进行 OCR 识别…")
        stdout = _run_tesseract(
            tesseract,
            list_file,
            language=language,
            session_dir=session_dir,
            timeout=timeout,
            cancel_event=cancel_event,
        )

        words = parse_tesseract_tsv(stdout)
        report(PARSE_PROGRESS, f"OCR 提取到 {len(words)} 行文本")

        page_sizes = _parse_page_sizes(stdout)
        observations: list[tuple[float, float, float, float, float, float]] = []
        for word in words:
            page_index = word.page - 1
            if page_index < 0 or page_index >= len(frame_paths):
                continue
            size = page_sizes.get(word.page)
            if size is None and frame_width > 0 and frame_height > 0:
                size = (frame_width, frame_height)
            if size is None or size[0] <= 0 or size[1] <= 0:
                continue
            normalized = (
                word.left / size[0],
                word.top / size[1],
                word.width / size[0],
                word.height / size[1],
            )
            mapped = map_box_to_scan_region(normalized, scan_region)
            observations.append((frame_times[page_index], *mapped, word.confidence))

        segments = cluster_observations(observations, total_duration=float(duration))
        report(100.0, f"检测完成：{len(segments)} 个区域")
        return segments
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)
