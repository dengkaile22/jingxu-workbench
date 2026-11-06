"""分屏中缝羽化：生成并复用静态灰度渐变（叠在接缝处的柔和阴影）。"""

from __future__ import annotations

import hashlib
import struct
import subprocess
import tempfile
import uuid
import zlib
from pathlib import Path

from jingxu.domain.splitscreen import SplitMode
from jingxu.infrastructure.process_control import no_window_kwargs


class FeatherError(RuntimeError):
    """羽化渐变生成失败。"""


def _generate_feather_png(
    width: int,
    height: int,
    mode: SplitMode,
    feather_px: int,
) -> bytes:
    """纯内存高效生成 RGBA 羽化黑底渐变 PNG，避免外部子进程及 FFmpeg geq 像素公式逐像素解释。"""
    horizontal_seam = mode in (SplitMode.DOUBLE_V, SplitMode.FOUR)
    vertical_seam = mode in (SplitMode.DOUBLE_H, SplitMode.FOUR)

    center_x = width / 2.0
    center_y = height / 2.0

    alpha_x = [0] * width
    if vertical_seam:
        for x in range(width):
            dist = abs(x - center_x)
            if dist < feather_px:
                alpha_x[x] = int(round(255 * (1.0 - dist / feather_px)))

    alpha_y = [0] * height
    if horizontal_seam:
        for y in range(height):
            dist = abs(y - center_y)
            if dist < feather_px:
                alpha_y[y] = int(round(255 * (1.0 - dist / feather_px)))

    if not horizontal_seam:
        # 仅垂直中缝：每一行像素的 alpha 完全相同
        row = bytearray(1 + width * 4)
        for x in range(width):
            row[1 + x * 4 + 3] = alpha_x[x]
        raw = bytes(row) * height
    elif not vertical_seam:
        # 仅水平中缝：只有中缝附近的行具有恒定 alpha，其余行全为 0
        zero_row = bytes(1 + width * 4)
        lines: list[bytes] = []
        for y in range(height):
            ay = alpha_y[y]
            if ay == 0:
                lines.append(zero_row)
            else:
                row = bytearray(1 + width * 4)
                row[4::4] = bytes([ay]) * width
                lines.append(bytes(row))
        raw = b"".join(lines)
    else:
        # 四分屏：双向中缝，缝外大多仅受垂直缝影响
        row_x = bytearray(1 + width * 4)
        for x in range(width):
            row_x[1 + x * 4 + 3] = alpha_x[x]
        row_x_bytes = bytes(row_x)

        lines = []
        for y in range(height):
            ay = alpha_y[y]
            if ay == 0:
                lines.append(row_x_bytes)
            else:
                row = bytearray(row_x)
                for x in range(width):
                    val = max(alpha_x[x], ay)
                    row[1 + x * 4 + 3] = val
                lines.append(bytes(row))
        raw = b"".join(lines)

    compressed = zlib.compress(raw, level=1)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


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

    # 优先使用纯内存快速生成（耗时仅 10ms，无需启动 FFmpeg 子进程）
    try:
        png_bytes = _generate_feather_png(width, height, mode, feather)
        tmp_output = root / f"jingxu-feather-{key}.tmp.{uuid.uuid4().hex[:6]}"
        tmp_output.write_bytes(png_bytes)
        tmp_output.replace(output)
        return output
    except Exception:
        pass

    # 异常降级分支：使用 FFmpeg lavfi 生成
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
