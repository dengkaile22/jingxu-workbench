"""贴纸/图层画幅模式与宽高比锁定（对齐 .NET StickerAspectMode / FixedAspectRatio）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from jingxu.domain.layers import (
    ASPECT_CANVAS_SIZES,
    LayerAspectMode,
    LayerFixedRatio,
    LayerKind,
    LayerSpec,
)
from jingxu.infrastructure.layer_store import layer_from_payload, layer_to_payload


def _layer(**overrides) -> LayerSpec:
    base = {
        "kind": LayerKind.STICKER,
        "source": Path("s.png"),
        "x_percent": 50.0,
        "y_percent": 50.0,
        "width_percent": 30.0,
        "height_percent": 0.0,
    }
    base.update(overrides)
    return LayerSpec(**base)


# ── 枚举与画布尺寸 ──────────────────────────────────────────────────────────


def test_aspect_mode_canvas_sizes_match_dotnet() -> None:
    assert LayerAspectMode.RATIO_9X16.canvas_size == (1080, 1920)
    assert LayerAspectMode.RATIO_3X4.canvas_size == (1080, 1440)
    assert LayerAspectMode.RATIO_1X1.canvas_size == (1080, 1080)
    assert LayerAspectMode.RATIO_4X3.canvas_size == (1440, 1080)
    assert LayerAspectMode.RATIO_16X9.canvas_size == (1920, 1080)


def test_follow_composition_falls_back_to_landscape_9x16() -> None:
    """跟随模式没有固定画布：回落到 .NET 的默认 (1080, 1920)。"""
    assert LayerAspectMode.FOLLOW_COMPOSITION.canvas_size == (1080, 1920)


def test_aspect_mode_display_names_are_chinese() -> None:
    assert LayerAspectMode.FOLLOW_COMPOSITION.display_text == "跟随混剪画幅"
    assert LayerAspectMode.RATIO_1X1.display_text == "1:1 方形"


def test_fixed_ratio_aspect_values_match_dotnet() -> None:
    assert LayerFixedRatio.RATIO_9X16.aspect_ratio == pytest.approx(9 / 16)
    assert LayerFixedRatio.RATIO_3X4.aspect_ratio == pytest.approx(3 / 4)
    assert LayerFixedRatio.RATIO_1X1.aspect_ratio == pytest.approx(1.0)
    assert LayerFixedRatio.RATIO_4X3.aspect_ratio == pytest.approx(4 / 3)
    assert LayerFixedRatio.RATIO_16X9.aspect_ratio == pytest.approx(16 / 9)


def test_fixed_ratio_none_means_no_constraint() -> None:
    assert LayerFixedRatio.NONE.aspect_ratio == 0.0
    assert LayerFixedRatio.NONE.canvas_size == (0, 0)
    assert LayerFixedRatio.NONE.display_text == "无固定比例"


def test_fixed_ratio_canvas_size_is_reference_canvas() -> None:
    assert LayerFixedRatio.RATIO_3X4.canvas_size == (1080, 1440)
    assert ASPECT_CANVAS_SIZES["3:4"] == (1080, 1440)


# ── 容错解析 ────────────────────────────────────────────────────────────────


def test_fixed_ratio_parsing_is_case_insensitive() -> None:
    assert _layer(fixed_aspect_ratio="1:1").fixed_ratio is LayerFixedRatio.RATIO_1X1


def test_unknown_fixed_ratio_falls_back_to_none() -> None:
    assert _layer(fixed_aspect_ratio="bogus").fixed_ratio is LayerFixedRatio.NONE


def test_default_fixed_ratio_is_none() -> None:
    assert _layer().fixed_ratio is LayerFixedRatio.NONE
    assert _layer().fixed_aspect_ratio == "none"


# ── 约束数学 ────────────────────────────────────────────────────────────────


def test_constrain_size_is_noop_without_ratio() -> None:
    layer = _layer()
    assert layer.constrain_size(width_percent=30, height_percent=40, driven_by="width") == (30.0, 40.0)


def test_constrain_by_width_derives_height() -> None:
    """1:1 锁定：宽度 30% → 高度 30%。"""
    layer = _layer(fixed_aspect_ratio=LayerFixedRatio.RATIO_1X1.value, width_percent=30)
    assert layer.constrain_size(width_percent=30, height_percent=0, driven_by="width") == (30.0, 30.0)


def test_constrain_by_width_uses_ratio_for_portrait() -> None:
    """锚点在左上角时高度完全由比例推导：9:16（ratio=0.5625）→ 宽度 45% 得高度 80%。"""
    layer = _layer(
        kind=LayerKind.STICKER,
        fixed_aspect_ratio=LayerFixedRatio.RATIO_9X16.value,
        x_percent=0.0,
        y_percent=0.0,
    )
    width, height = layer.constrain_size(width_percent=45, height_percent=0, driven_by="width")
    assert width == pytest.approx(45.0)
    assert height == pytest.approx(80.0)


def test_constrain_by_width_is_capped_by_remaining_height() -> None:
    """中心锚点 (50,50) 时只有下半 50% 可用，超出的高度应收口回宽度。"""
    layer = _layer(
        kind=LayerKind.STICKER,
        fixed_aspect_ratio=LayerFixedRatio.RATIO_9X16.value,
        x_percent=50.0,
        y_percent=50.0,
    )
    width, height = layer.constrain_size(width_percent=45, height_percent=0, driven_by="width")
    assert height == pytest.approx(50.0)
    assert width == pytest.approx(50.0 * 9 / 16, abs=0.05)


def test_constrain_by_height_derives_width() -> None:
    """由高度驱动时应反推宽度：1:1 下高度 25% → 宽度 25%。"""
    layer = _layer(fixed_aspect_ratio=LayerFixedRatio.RATIO_1X1.value)
    assert layer.constrain_size(width_percent=0, height_percent=25, driven_by="height") == (25.0, 25.0)


def test_constrain_clamps_into_remaining_space() -> None:
    """16:9 锁定 + 中心锚点：宽度受剩余 50% 限制，高度由比例推出（不是把高度撞满）。

    宽度推到 100% 时，先把宽度钳到剩余 50%，再由比例推出高度 28.12%；
    若只按高度收口会得到 88.89% 宽的更宽结果，但那会横向越界。
    """
    layer = _layer(
        fixed_aspect_ratio=LayerFixedRatio.RATIO_16X9.value,
        x_percent=50.0,
        y_percent=50.0,
    )
    width, height = layer.constrain_size(width_percent=100, height_percent=0, driven_by="width")
    assert width == pytest.approx(50.0, abs=0.01)
    assert height == pytest.approx(50.0 * 9 / 16, abs=0.05)
    # 两个方向都不得越界。
    assert width <= 100.0 - layer.x_percent + 0.01
    assert height <= 100.0 - layer.y_percent + 0.01
    # 高宽比必须严格保持锁定值。
    assert width / height == pytest.approx(16 / 9, rel=0.001)


def test_constrain_respects_x_offset_for_width_limit() -> None:
    """X 偏右时可用宽度变小：宽度被钳到 100-X，高度随之收缩。"""
    layer = _layer(
        fixed_aspect_ratio=LayerFixedRatio.RATIO_1X1.value,
        x_percent=80.0,
        y_percent=50.0,
    )
    width, height = layer.constrain_size(width_percent=90, height_percent=0, driven_by="width")
    assert width <= 20.0 + 0.01
    assert height == pytest.approx(width, abs=0.01)


def test_constrain_never_returns_non_positive() -> None:
    """非正输入也要返回 > 0（与 .NET Math.Max(0.01, ...) 一致）。"""
    layer = _layer(fixed_aspect_ratio=LayerFixedRatio.RATIO_1X1.value, x_percent=99.9, y_percent=99.9)
    width, height = layer.constrain_size(width_percent=0, height_percent=0, driven_by="width")
    assert width > 0 and height > 0


def test_constrain_uses_explicit_anchor_when_provided() -> None:
    layer = _layer(fixed_aspect_ratio=LayerFixedRatio.RATIO_1X1.value)
    width, height = layer.constrain_size(
        width_percent=60,
        height_percent=0,
        driven_by="width",
        x_percent=10.0,
        y_percent=90.0,
    )
    # 剩余高度只有 10%，应从高度反推宽度。
    assert height <= 10.0 + 0.01
    assert width == pytest.approx(height, abs=0.01)


# ── 持久化 ──────────────────────────────────────────────────────────────────


def test_layer_payload_roundtrip_preserves_fixed_ratio(tmp_path: Path) -> None:
    source = tmp_path / "s.png"
    source.write_bytes(b"stub")
    layer = _layer(source=source, fixed_aspect_ratio=LayerFixedRatio.RATIO_9X16.value)

    restored = layer_from_payload(LayerKind.STICKER, layer_to_payload(layer))
    assert restored is not None
    assert restored.fixed_aspect_ratio == LayerFixedRatio.RATIO_9X16.value
    assert restored.fixed_ratio is LayerFixedRatio.RATIO_9X16


def test_legacy_payload_defaults_to_no_ratio(tmp_path: Path) -> None:
    source = tmp_path / "s.png"
    source.write_bytes(b"stub")
    restored = layer_from_payload(LayerKind.STICKER, {"source": str(source)})
    assert restored is not None
    assert restored.fixed_aspect_ratio == LayerFixedRatio.NONE.value


def test_unknown_ratio_in_payload_falls_back_to_none(tmp_path: Path) -> None:
    source = tmp_path / "s.png"
    source.write_bytes(b"stub")
    payload = {"source": str(source), "fixed_aspect_ratio": "21:9"}
    restored = layer_from_payload(LayerKind.STICKER, payload)
    assert restored is not None
    assert restored.fixed_aspect_ratio == LayerFixedRatio.NONE.value
