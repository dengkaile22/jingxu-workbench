"""蒙版形状遮罩：几何表达式、阶段顺序、PNG 遮罩链与持久化。

与 .NET ``OverlayFilterCompiler.BuildShapeAlphaMask`` 对齐；纯字符串级测试，
真实像素效果由集成测试覆盖。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import (
    DEFAULT_MASK_CORNER_RADIUS_PX,
    MAX_MASK_CORNER_RADIUS_PX,
    SELF_SOURCE,
    LayerKind,
    LayerShapeMask,
    LayerSpec,
)
from jingxu.domain.render import RenderSettings
from jingxu.infrastructure.filter_graph import build_filter_graph
from jingxu.infrastructure.layer_store import layer_from_payload, layer_to_payload


def _plan() -> CompositionPlan:
    return CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL, seed=11)


def _settings() -> RenderSettings:
    return RenderSettings(width=1080, height=1920, fps=30)


def _layer(**overrides) -> LayerSpec:
    base = {
        "kind": LayerKind.OVERLAY,
        "source": Path("mask.mp4"),
        "width_percent": 50.0,
        "height_percent": 40.0,
    }
    base.update(overrides)
    return LayerSpec(**base)


def _script(*layers: LayerSpec, settings: RenderSettings | None = None) -> str:
    return build_filter_graph(
        _plan(), settings or _settings(), layers=tuple(layers)
    ).script


# ── 几何表达式 ──────────────────────────────────────────────────────────────


def test_default_shape_is_none_and_emits_no_shape_filter() -> None:
    layer = _layer()
    assert layer.shape_mask == LayerShapeMask.NONE.value
    script = _script(layer)
    assert "geq=r=" not in script
    assert "geq=lum=" not in script


def test_rectangle_shape_is_equivalent_to_no_shape() -> None:
    """矩形即边界框，不该产生任何 alpha 重写。"""
    script = _script(_layer(shape_mask=LayerShapeMask.RECTANGLE.value))
    assert "geq=r=" not in script
    assert "colorchannelmixer=aa=1.000" in script


def test_ellipse_shape_rewrites_alpha_channel_only() -> None:
    script = _script(_layer(shape_mask=LayerShapeMask.ELLIPSE.value))

    # 四个通道必须齐写：只写 a= 可能不进入 RGB 模式而拿不到 alpha 平面。
    assert "geq=r='r(X,Y)'" in script
    assert "g='g(X,Y)'" in script
    assert "b='b(X,Y)'" in script
    assert ":a='if(lt(pow(X-W/2,2)+pow(Y-H/2,2),pow(min(W,H)/2,2)),alpha(X,Y),0)'" in script
    # 绝不能用 geq=lum=，那会覆盖不透明度写入的 alpha。
    assert "geq=lum=" not in script


def test_shape_expressions_use_runtime_dimensions() -> None:
    """用运行时 W/H 而非编译期像素常量：图层帧高在 scale=w:-2 下只有运行时可知。"""
    script = _script(_layer(shape_mask=LayerShapeMask.ELLIPSE.value))
    assert "W/2" in script and "H/2" in script


def test_rounded_rectangle_uses_corner_radius() -> None:
    script = _script(
        _layer(shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value, mask_corner_radius_px=20)
    )
    # 半径钳到不超过短边的一半，避免极窄画面下钳制区间反转。
    # ffmpeg 的 max() 只接受两个参数，故半径钳制用嵌套两参形式。
    radius = "min(20,min(W/2,H/2))"
    assert radius in script
    assert f"max({radius},min(W-({radius}),X))" in script
    assert f"max({radius},min(H-({radius}),Y))" in script
    assert f"pow({radius},2)" in script
    # 必须由 ffmpeg 实际接受（三参 max 会被判为 Invalid argument）。
    assert "max(" in script and script.count("max(") == 2


def test_rounded_rectangle_does_not_reuse_dotnet_literal_banded_form() -> None:
    """注明差异：.NET 字面写法会整条擦除 8px 边带（几何上不是圆角）。

    这里改为标准的「到圆角矩形边界距离」，因此不应出现字面式的 gt(X,8) 组合。
    """
    script = _script(_layer(shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value))
    assert "gt(X,8)*gt(Y,8)" not in script


def test_rounded_rectangle_radius_out_of_range_is_rejected_not_clamped() -> None:
    """越界半径由校验拒绝（明确报错），而不是悄悄钳制——避免用户以为设置生效了。"""
    with pytest.raises(ValueError, match="圆角半径"):
        _script(
            _layer(shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value, mask_corner_radius_px=0.5)
        )
    with pytest.raises(ValueError, match="圆角半径"):
        _script(
            _layer(shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value, mask_corner_radius_px=9999)
        )


# ── 阶段顺序 ────────────────────────────────────────────────────────────────


def test_shape_runs_after_opacity_and_before_envelope() -> None:
    layer = _layer(
        shape_mask=LayerShapeMask.ELLIPSE.value,
        feather=0.5,
        rotation_degrees=10,
    )
    script = _script(layer)

    opacity = script.index("colorchannelmixer=aa=")
    shape = script.index("geq=r=")
    envelope = script.index("alphaextract")
    rotate = script.index("rotate=")
    overlay = script.index("overlay=x=")

    assert opacity < shape < envelope < rotate < overlay


def test_shape_without_envelope_still_bridges_to_unified_label() -> None:
    script = _script(_layer(shape_mask=LayerShapeMask.ELLIPSE.value))
    assert "[lay0shape]null[lay0]" in script
    assert "[vcat][lay0]overlay=" in script


def test_shape_does_not_change_window_or_overlay_position() -> None:
    """形状只改 alpha，不得影响时长窗口与叠加位置。"""
    plain = _script(_layer())
    shaped = _script(_layer(shape_mask=LayerShapeMask.ELLIPSE.value))

    for token in ("trim=duration=", "setpts=PTS-STARTPTS+0.000/TB", "overlay=x=main_w*0.5000"):
        assert token in plain and token in shaped
    assert "y=main_h*0.5000-overlay_h/2" in shaped


# ── PNG 遮罩 ────────────────────────────────────────────────────────────────


def test_png_mask_registers_extra_input(tmp_path: Path) -> None:
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    graph = build_filter_graph(
        _plan(),
        _settings(),
        layers=(_layer(shape_mask=LayerShapeMask.IMPORTED_PNG.value, mask_png=mask),),
    )

    purposes = [extra.purpose for extra in graph.extra_inputs]
    assert purposes == ["layer", "layer-mask"]
    assert graph.extra_inputs[1].path == mask
    assert graph.extra_inputs[1].loop is True


def test_png_mask_luma_mode_uses_gray_and_alphamerge(tmp_path: Path) -> None:
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    script = _script(
        _layer(shape_mask=LayerShapeMask.IMPORTED_PNG.value, mask_png=mask)
    )

    assert "[2:v]format=gray,scale=540:768,setsar=1[lay0mask]" in script
    assert "[lay0rgba][lay0mask]alphamerge=eof_action=repeat:repeatlast=1[lay0m]" in script


def test_png_mask_alpha_mode_extracts_alpha_channel(tmp_path: Path) -> None:
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    script = _script(
        _layer(
            shape_mask=LayerShapeMask.IMPORTED_PNG.value,
            mask_png=mask,
            mask_png_mode="alpha",
        )
    )
    assert "format=rgba,alphaextract,scale=540:768" in script
    assert "format=gray" not in script


def test_png_mask_luma_alpha_mode_multiplies_both(tmp_path: Path) -> None:
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    script = _script(
        _layer(
            shape_mask=LayerShapeMask.IMPORTED_PNG.value,
            mask_png=mask,
            mask_png_mode="luma_alpha",
        )
    )
    assert "split=2[lay0maskma][lay0maskmb]" in script
    assert "alphaextract[lay0maskmx]" in script
    assert "blend=all_mode=multiply[lay0mask]" in script


def test_png_mask_invert_appends_negate(tmp_path: Path) -> None:
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    script = _script(
        _layer(
            shape_mask=LayerShapeMask.IMPORTED_PNG.value,
            mask_png=mask,
            mask_png_invert=True,
        )
    )
    assert "setsar=1,negate[lay0mask]" in script


def test_png_mask_scale_matches_layer_frame(tmp_path: Path) -> None:
    """遮罩与图层帧必须逐像素相等，否则 alphamerge 直接失败。"""
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    settings = _settings()
    script = _script(
        _layer(shape_mask=LayerShapeMask.IMPORTED_PNG.value, mask_png=mask),
        settings=settings,
    )

    expected_width = max(2, int(round(settings.width * 50 / 100)))
    expected_height = settings.height * 40 // 100
    expected_height = int(round(expected_height)) // 2 * 2
    assert f"scale={expected_width}:{expected_height}" in script
    # 图层自身的 fit 链也用同一高度上限收口。
    assert f"crop=iw:'min(ih,{expected_height})'" in script


def test_png_mask_with_zero_height_raises() -> None:
    with pytest.raises(ValueError, match="PNG 遮罩需要显式高度"):
        _script(
            _layer(
                source=Path(":self:"),
                height_percent=0,
                shape_mask=LayerShapeMask.IMPORTED_PNG.value,
                mask_png=Path("alpha.png"),
            )
        )


def test_png_mask_without_file_raises() -> None:
    with pytest.raises(ValueError, match="缺少遮罩文件"):
        _script(_layer(shape_mask=LayerShapeMask.IMPORTED_PNG.value, mask_png=None))


def test_png_mask_rejects_gif_suffix() -> None:
    with pytest.raises(ValueError, match="仅支持"):
        _script(
            _layer(shape_mask=LayerShapeMask.IMPORTED_PNG.value, mask_png=Path("alpha.gif"))
        )


def test_self_ghost_supports_shape_mask() -> None:
    """.NET 允许自叠影 + 形状遮罩组合，Python 不应特判。"""
    script = _script(_layer(source=Path(SELF_SOURCE), shape_mask=LayerShapeMask.ELLIPSE.value))
    assert "[vcat]split[lay0keep][lay0ghost]" in script
    assert "geq=r='r(X,Y)'" in script


# ── 领域校验 ────────────────────────────────────────────────────────────────


def test_validate_shape_mask_accepts_simple_shapes() -> None:
    assert _layer().validate_shape_mask() is None
    assert _layer(shape_mask=LayerShapeMask.RECTANGLE.value).validate_shape_mask() is None
    assert _layer(shape_mask=LayerShapeMask.ELLIPSE.value).validate_shape_mask() is None


def test_validate_shape_mask_rejects_bad_radius() -> None:
    too_small = _layer(
        shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value, mask_corner_radius_px=0
    )
    assert "圆角半径" in (too_small.validate_shape_mask() or "")

    too_big = _layer(
        shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value, mask_corner_radius_px=500
    )
    assert "圆角半径" in (too_big.validate_shape_mask() or "")


def test_validate_shape_mask_rejects_bad_png_mode(tmp_path: Path) -> None:
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    layer = _layer(
        shape_mask=LayerShapeMask.IMPORTED_PNG.value, mask_png=mask, mask_png_mode="bogus"
    )
    assert "遮罩模式" in (layer.validate_shape_mask() or "")


def test_unknown_shape_string_falls_back_to_none() -> None:
    layer = _layer(shape_mask="not-a-shape")
    assert layer.shape_mask_kind is LayerShapeMask.NONE
    assert layer.validate_shape_mask() is None
    assert "geq=r=" not in _script(layer)


def test_shape_mask_kind_is_case_insensitive() -> None:
    layer = _layer(shape_mask="ELLIPSE")
    assert layer.shape_mask_kind is LayerShapeMask.ELLIPSE


# ── 持久化 ──────────────────────────────────────────────────────────────────


def test_layer_payload_roundtrip_preserves_shape_fields(tmp_path: Path) -> None:
    mask = tmp_path / "alpha.png"
    mask.write_bytes(b"stub")
    source = tmp_path / "mask.mp4"
    source.write_bytes(b"stub")
    layer = _layer(
        source=source,
        shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value,
        mask_corner_radius_px=24.0,
        mask_png=mask,
        mask_png_mode="luma_alpha",
        mask_png_invert=True,
    )
    restored = layer_from_payload(LayerKind.OVERLAY, layer_to_payload(layer))

    assert restored is not None
    assert restored.shape_mask == LayerShapeMask.ROUNDED_RECTANGLE.value
    assert restored.mask_corner_radius_px == 24.0
    assert restored.mask_png == mask
    assert restored.mask_png_mode == "luma_alpha"
    assert restored.mask_png_invert is True


def test_legacy_payload_without_shape_keys_defaults_to_none(tmp_path: Path) -> None:
    source = tmp_path / "mask.mp4"
    source.write_bytes(b"stub")
    legacy = {"source": str(source), "width_percent": 50.0}

    restored = layer_from_payload(LayerKind.OVERLAY, legacy)
    assert restored is not None
    assert restored.shape_mask == LayerShapeMask.NONE.value
    assert restored.mask_corner_radius_px == DEFAULT_MASK_CORNER_RADIUS_PX
    assert restored.mask_png is None
    assert restored.mask_png_mode == "luma"
    assert restored.mask_png_invert is False


def test_missing_mask_png_degrades_instead_of_dropping_layer(tmp_path: Path) -> None:
    """遮罩是附属资源：文件丢了不该连带丢弃整条图层。"""
    source = tmp_path / "mask.mp4"
    source.write_bytes(b"stub")
    payload = {
        "source": str(source),
        "shape_mask": LayerShapeMask.IMPORTED_PNG.value,
        "mask_png": str(tmp_path / "gone.png"),
        "height_percent": 40.0,
    }

    restored = layer_from_payload(LayerKind.OVERLAY, payload)
    assert restored is not None
    assert restored.shape_mask == LayerShapeMask.NONE.value
    assert restored.mask_png is None


def test_missing_source_still_drops_layer(tmp_path: Path) -> None:
    """素材本身丢失仍然整条丢弃（与遮罩的降级策略不同）。"""
    payload = {"source": str(tmp_path / "gone.mp4"), "width_percent": 50.0}
    assert layer_from_payload(LayerKind.OVERLAY, payload) is None


def test_self_source_sentinel_survives_roundtrip() -> None:
    """自叠影哨兵不是真实路径，必须特判保留，否则项目重开后自叠影消失。"""
    layer = _layer(source=Path(SELF_SOURCE))
    restored = layer_from_payload(LayerKind.OVERLAY, layer_to_payload(layer))

    assert restored is not None
    assert str(restored.source) == SELF_SOURCE
    assert restored.is_self_source is True


def test_unknown_shape_string_in_payload_falls_back_to_none(tmp_path: Path) -> None:
    source = tmp_path / "mask.mp4"
    source.write_bytes(b"stub")
    payload = {"source": str(source), "shape_mask": "bogus", "width_percent": 50.0}
    restored = layer_from_payload(LayerKind.OVERLAY, payload)
    assert restored is not None
    assert restored.shape_mask == LayerShapeMask.NONE.value
