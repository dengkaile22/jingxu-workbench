"""羽化渐变生成器（feather.py）单元测试与性能验证。"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from jingxu.domain.splitscreen import SplitMode
from jingxu.infrastructure.feather import (
    FeatherError,
    _generate_feather_png,
    feather_gradient,
)


def _read_png_ihdr(data: bytes) -> tuple[int, int, int, int]:
    """读取 PNG 头部：返回 (width, height, bit_depth, color_type)。"""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: 4 bytes length, 4 bytes 'IHDR', 13 bytes data
    assert data[12:16] == b"IHDR"
    w, h, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    return w, h, bit_depth, color_type


def _extract_rgba_pixel(data: bytes, width: int, height: int, target_x: int, target_y: int) -> tuple[int, int, int, int]:
    """解压 PNG 数据并提取指定像素的 RGBA 值。"""
    # 查找 IDAT chunk
    offset = 8
    idat_parts: list[bytes] = []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        tag = data[offset + 4 : offset + 8]
        if tag == b"IDAT":
            idat_parts.append(data[offset + 8 : offset + 8 + length])
        offset += 12 + length

    decompressed = zlib.decompress(b"".join(idat_parts))
    # 每一行包含 1 字节 filter type (0) + width * 4 字节
    row_stride = 1 + width * 4
    row_start = target_y * row_stride
    pixel_start = row_start + 1 + target_x * 4
    r, g, b, a = decompressed[pixel_start : pixel_start + 4]
    return r, g, b, a


def test_generate_feather_png_header_and_dimensions() -> None:
    data = _generate_feather_png(120, 80, SplitMode.DOUBLE_H, 16)
    w, h, bit_depth, color_type = _read_png_ihdr(data)
    assert w == 120
    assert h == 80
    assert bit_depth == 8
    assert color_type == 6  # RGBA


def test_generate_feather_png_double_h_gradient() -> None:
    # 宽 100, 高 60, 垂直缝（X=50）, 羽化 20
    data = _generate_feather_png(100, 60, SplitMode.DOUBLE_H, 20)
    # 中心 X=50 处 alpha 应接近 255
    r, g, b, a_center = _extract_rgba_pixel(data, 100, 60, 50, 30)
    assert (r, g, b) == (0, 0, 0)
    assert a_center >= 250

    # X=50+10=60 处 (距离缝 10px, feather 20px) alpha 应在 120~135 左右
    _, _, _, a_mid = _extract_rgba_pixel(data, 100, 60, 60, 30)
    assert 115 <= a_mid <= 135

    # X=10 处 (距离缝 40px > 20px) alpha 必须为 0
    _, _, _, a_edge = _extract_rgba_pixel(data, 100, 60, 10, 30)
    assert a_edge == 0


def test_generate_feather_png_double_v_gradient() -> None:
    # 宽 60, 高 100, 水平缝（Y=50）, 羽化 20
    data = _generate_feather_png(60, 100, SplitMode.DOUBLE_V, 20)
    # 中心 Y=50 处 alpha 应接近 255
    r, g, b, a_center = _extract_rgba_pixel(data, 60, 100, 30, 50)
    assert (r, g, b) == (0, 0, 0)
    assert a_center >= 250

    # 顶部 Y=5 处 (距离缝 45px > 20px) alpha 必须为 0
    _, _, _, a_top = _extract_rgba_pixel(data, 60, 100, 30, 5)
    assert a_top == 0


def test_generate_feather_png_four_screen() -> None:
    # 四分屏模式：中心 (50, 50) 处 alpha 接近 255，四角 (5, 5) 处为 0
    data = _generate_feather_png(100, 100, SplitMode.FOUR, 15)
    _, _, _, a_center = _extract_rgba_pixel(data, 100, 100, 50, 50)
    assert a_center >= 250

    _, _, _, a_corner = _extract_rgba_pixel(data, 100, 100, 5, 5)
    assert a_corner == 0


def test_feather_gradient_caching(tmp_path: Path) -> None:
    dummy_ffmpeg = tmp_path / "ffmpeg.exe"
    first = feather_gradient(dummy_ffmpeg, 120, 80, SplitMode.DOUBLE_H, 16, cache_directory=tmp_path)
    assert first.is_file()

    # 二次调用直接命中缓存
    second = feather_gradient(dummy_ffmpeg, 120, 80, SplitMode.DOUBLE_H, 16, cache_directory=tmp_path)
    assert first == second


def test_feather_gradient_fallback_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import jingxu.infrastructure.feather as feather_module

    # 模拟纯内存生成异常，触发降级逻辑
    def fail_memory_gen(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("Memory generation failed")

    monkeypatch.setattr(feather_module, "_generate_feather_png", fail_memory_gen)

    # 当 FFmpeg 也不存在时，确认抛出 FeatherError
    with pytest.raises(FeatherError, match="羽化渐变生成失败"):
        feather_gradient(tmp_path / "nonexistent-ffmpeg.exe", 100, 100, SplitMode.DOUBLE_H, 10, cache_directory=tmp_path)
