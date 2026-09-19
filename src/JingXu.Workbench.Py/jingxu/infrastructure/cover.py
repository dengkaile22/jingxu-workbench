"""封面导出：首段素材首帧 / 成片结尾帧 / 指定时间点取帧。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from jingxu.domain.render import CoverMode


class CoverError(RuntimeError):
    """封面生成失败。"""


def generate_cover(
    ffmpeg_path: Path,
    video_path: Path,
    output_path: Path,
    *,
    at_seconds: float = 1.0,
    mode: CoverMode = CoverMode.TIMESTAMP,
    first_source_path: Path | None = None,
    timeout: float = 60.0,
) -> Path:
    """生成 JPEG 封面；失败时清理半成品并抛出 :class:`CoverError`。

    - ``TIMESTAMP``：从成片指定时间点取帧（默认行为）；
    - ``FIRST_SOURCE_FRAME``：取第一条主素材的首帧（需提供 ``first_source_path``）；
    - ``FINAL_OUTPUT_FRAME``：取成片结尾帧（``-sseof -0.1`` 定位）。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if mode is CoverMode.FIRST_SOURCE_FRAME:
        if first_source_path is None:
            raise CoverError("首帧封面需要第一条素材路径。")
        command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(first_source_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
    elif mode is CoverMode.FINAL_OUTPUT_FRAME:
        command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
    else:
        moment = max(at_seconds, 0.0)
        command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{moment:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        _try_delete_partial(output_path)
        raise CoverError("封面取帧超时。") from error
    except OSError as error:
        _try_delete_partial(output_path)
        raise CoverError(f"无法启动 FFmpeg：{error}") from error

    if completed.returncode != 0:
        _try_delete_partial(output_path)
        detail = (completed.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"退出码 {completed.returncode}"
        raise CoverError(f"封面生成失败：{tail}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        _try_delete_partial(output_path)
        raise CoverError("封面文件未生成或为零字节。")

    return output_path


def _try_delete_partial(path: Path) -> None:
    """失败时删除半成品 JPEG；成功封面是用户可见产物，不得删除。"""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
