"""Whisper.cpp 离线识别：抽音频 → 识别 → 解析 SRT。"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import jingxu.infrastructure.runtime as runtime_module
from jingxu.domain.subtitles import SubtitleCue
from jingxu.infrastructure.runtime import ToolNotFoundError
from jingxu.infrastructure.process_control import no_window_kwargs
from jingxu.infrastructure.subtitles import parse_srt

PROGRESS_PATTERN = re.compile(r"progress\s*=\s*(\d+)\s*%", re.IGNORECASE)
LANGUAGE_PATTERN = re.compile(r"auto-detected language:\s*([A-Za-z-]+)", re.IGNORECASE)
DEFAULT_MODEL_NAME = "ggml-base.bin"

# 发布流水线会为缺失的可选组件写入 1 字节占位文件，需按体积过滤。
MIN_CLI_BYTES = 64 * 1024
MIN_MODEL_BYTES = 1024 * 1024


def _is_real_file(path: Path, minimum_bytes: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= minimum_bytes
    except OSError:
        return False


class WhisperError(RuntimeError):
    """识别失败。"""


class WhisperCancelled(WhisperError):
    """识别被取消。"""


@dataclass(frozen=True, slots=True)
class WhisperRuntime:
    cli: Path
    model: Path

    @property
    def label(self) -> str:
        return f"{self.cli.name} · {self.model.name}"


def _candidates(name: str) -> list[Path]:
    roots = runtime_module._search_roots()  # noqa: SLF001 - 复用同一套向上查找
    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / "runtime" / "whisper" / name)
    return candidates


def find_whisper(model_name: str = DEFAULT_MODEL_NAME) -> WhisperRuntime | None:
    """定位 whisper-cli 与模型；缺失或仅为占位文件时返回 ``None``。"""
    executable = "whisper-cli.exe" if runtime_module.os.name == "nt" else "whisper-cli"

    for root in runtime_module._search_roots():  # noqa: SLF001
        whisper_dir = root / "runtime" / "whisper"
        cli = whisper_dir / executable
        model = whisper_dir / "models" / model_name
        if _is_real_file(cli, MIN_CLI_BYTES) and _is_real_file(model, MIN_MODEL_BYTES):
            return WhisperRuntime(cli=cli, model=model)

    on_path = shutil.which("whisper-cli")
    if on_path and _is_real_file(Path(on_path), MIN_CLI_BYTES):
        for root in runtime_module._search_roots():  # noqa: SLF001
            model = root / "runtime" / "whisper" / "models" / model_name
            if _is_real_file(model, MIN_MODEL_BYTES):
                return WhisperRuntime(cli=Path(on_path), model=model)
    return None


def require_whisper(model_name: str = DEFAULT_MODEL_NAME) -> WhisperRuntime:
    runtime = find_whisper(model_name)
    if runtime is None:
        raise ToolNotFoundError(
            "未找到 Whisper 识别组件。请将 whisper-cli.exe 与 models/ggml-base.bin 放入 runtime/whisper/。"
        )
    return runtime


def _extract_audio(ffmpeg_path: Path, video_path: Path, output_path: Path) -> None:
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        **no_window_kwargs(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not output_path.is_file():
        detail = (completed.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"退出码 {completed.returncode}"
        raise WhisperError(f"提取音频失败：{tail}")


def transcribe(
    video_path: Path,
    *,
    ffmpeg_path: Path,
    runtime: WhisperRuntime | None = None,
    language: str = "auto",
    on_progress: Callable[[float, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    temp_directory: Path | None = None,
) -> list[SubtitleCue]:
    """离线识别视频语音，返回带时间轴的字幕条目。"""
    whisper = runtime or require_whisper()
    work_directory = Path(tempfile.mkdtemp(prefix="jingxu-py-whisper-", dir=temp_directory))

    try:
        audio_path = work_directory / "audio.wav"
        if on_progress is not None:
            on_progress(2.0, "提取音频…")
        _extract_audio(ffmpeg_path, Path(video_path), audio_path)

        output_base = work_directory / "transcript"
        command = [
            str(whisper.cli),
            "-m",
            str(whisper.model),
            "-f",
            str(audio_path),
            "-l",
            language or "auto",
            "-pp",
            "-osrt",
            "-of",
            str(output_base),
        ]

        if on_progress is not None:
            on_progress(5.0, "识别中（whisper.cpp）…")

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if runtime_module.os.name == "nt" else 0,
            )
        except OSError as error:
            raise WhisperError(f"无法启动 Whisper（{whisper.cli.name} 可能不是有效的可执行文件）：{error}") from error

        assert process.stderr is not None
        detected = ""
        try:
            for line in process.stderr:
                if cancel_event is not None and cancel_event.is_set():
                    raise WhisperCancelled("识别已取消。")

                match = PROGRESS_PATTERN.search(line)
                if match and on_progress is not None:
                    percent = 5.0 + float(match.group(1)) * 0.93
                    on_progress(min(percent, 99.0), f"识别中… {match.group(1)}%")
                    continue

                language_match = LANGUAGE_PATTERN.search(line)
                if language_match:
                    detected = language_match.group(1)
                    if on_progress is not None:
                        on_progress(8.0, f"检测语言：{detected}")
            return_code = process.wait()
        except WhisperCancelled:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise

        if return_code != 0:
            raise WhisperError(f"Whisper 退出码 {return_code}。")

        srt_path = output_base.with_suffix(".srt")
        if not srt_path.is_file():
            raise WhisperError("Whisper 未生成字幕文件。")

        cues = parse_srt(srt_path.read_text(encoding="utf-8", errors="replace"))
        if on_progress is not None:
            on_progress(100.0, f"识别完成：{len(cues)} 条字幕" + (f"（{detected}）" if detected else ""))
        return cues
    finally:
        shutil.rmtree(work_directory, ignore_errors=True)
