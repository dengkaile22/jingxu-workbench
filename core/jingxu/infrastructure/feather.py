"""分屏中缝羽化：生成并复用静态灰度渐变（叠在接缝处的柔和阴影）。"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from jingxu.domain.splitscreen import SplitMode

from jingxu.infrastructure.process_control import no_window_kwargs


class FeatherError(RuntimeError):
    """羽化渐变生成失败。"""


def feather_gradient(
    ffmpeg_path: Path,
    width: int,
    height: int,
    mode: SplitMode,
    feather_px: int,
    *,
    cache_directory: Path | None = None,
    timeout: float = 60.0,
) -> Path:
    """按尺寸与分屏模式生成（并缓存）一张带 alpha 渐变的黑色位图。"""
    width = max(2, int(width))
    height = max(2, int(height))
    feather = max(2, int(feather_px))
    key = hashlib.sha256(f"{width}x{height}:{mode.value}:{feather}".encode()).hexdigest()[:16]

    root = Path(cache_directory) if cache_directory else Path(tempfile.gettempdir())
    output = root / f"jingxu-feather-{key}.png"
    if output.is_file():
        return output

    horizontal_seam = mode in (SplitMode.DOUBLE_V, SplitMode.FOUR)
    vertical_seam = mode in (SplitMode.DOUBLE_H, SplitMode.FOUR)

    expressions: list[str] = []
    if vertical_seam:
        center = width / 2
        expressions.append(f"if(lt(abs(X-{center:.1f}),{feather}),255*(1-abs(X-{center:.1f})/{feather}),0)")
    if horizontal_seam:
        center = height / 2
        expressions.append(f"if(lt(abs(Y-{center:.1f}),{feather}),255*(1-abs(Y-{center:.1f})/{feather}),0)")
    alpha = expressions[0] if len(expressions) == 1 else f"max({expressions[0]},{expressions[1]})"

    source = f"color=c=black@0.0:s={width}x{height}:d=1,format=rgba,geq=r=0:g=0:b=0:a='{alpha}'"
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        source,
        "-frames:v",
        "1",
        str(output),
    ]

    try:
        completed = subprocess.run(
            command,
            **no_window_kwargs(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FeatherError(f"羽化渐变生成失败：{error}") from error

    if completed.returncode != 0 or not output.is_file():
        detail = (completed.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"退出码 {completed.returncode}"
        raise FeatherError(f"羽化渐变生成失败：{tail}")

    return output
