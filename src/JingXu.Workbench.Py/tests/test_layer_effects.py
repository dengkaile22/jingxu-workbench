"""图层边缘处理：源裁剪、alpha 包络、旋转顺序与持久化测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import RenderSettings
from jingxu.infrastructure.filter_graph import build_filter_graph
from jingxu.infrastructure.layer_store import LayerStore


def _plan() -> CompositionPlan:
    return CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL)


def _graph(*layers: LayerSpec, settings: RenderSettings | None = None):
    return build_filter_graph(_plan(), settings or RenderSettings(), layers=tuple(layers))


def test_plain_layer_has_no_envelope_filters() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"))
    script = _graph(layer).script

    assert "geq" not in script
    assert "gblur" not in script
    assert "alphamerge" not in script
    # 不透明度写入后经 null 桥接到统一最终标签 lay0（叠加段只认这一个标签）。
    assert "colorchannelmixer=aa=1.000[lay0rgba]" in script
    assert "[lay0rgba]null[lay0]" in script
    assert "[vcat][lay0]overlay=" in script


def test_plain_layer_opacity_still_precedes_overlay() -> None:
    """无形状/无羽化时链路最短：不透明度 → 桥接 → 叠加。"""
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"))
    script = _graph(layer).script
    assert script.index("colorchannelmixer=aa=1.000") < script.index("[lay0rgba]null[lay0]")
    assert script.index("[lay0rgba]null[lay0]") < script.index("[vcat][lay0]overlay=")


def test_feather_envelope_blurs_alpha_and_rotates_after_merge() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), feather=0.5, rotation_degrees=10)
    script = _graph(layer).script

    assert "geq=lum='lum(X,Y)*min(1,max(0,(H-Y)/(H*0.5+0.000001)))'" in script
    assert "gblur=sigma=2" in script
    assert "alphaextract" in script
    assert "alphamerge" in script
    assert script.find("rotate=") > script.find("alphamerge")
    assert "[lay0env]rotate=" in script
    assert script.index("colorchannelmixer=aa=1.000") < script.index("alphaextract")


def test_feather_sigma_scales_with_layer_width() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), feather=1.0)
    script = _graph(layer).script

    assert "gblur=sigma=5" in script


def test_top_fade_uses_linear_y_factor() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), top_fade=0.25)
    script = _graph(layer).script

    assert "geq=lum='lum(X,Y)*min(1,Y/(H*0.25))'" in script
    assert "gblur" not in script
    assert "alphamerge" in script


def test_manual_source_crop_emits_even_aligned_expression() -> None:
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.mp4"),
        remove_black=True,
        source_crop_bounds=(0.1, 0.2, 0.5, 0.6),
    )
    script = _graph(layer).script

    assert "crop=w='max(2\\,trunc(iw*0.5/2)*2)'" in script
    assert "h='max(2\\,trunc(ih*0.6/2)*2)'" in script
    assert "x='trunc(min(iw-ow\\,iw*0.1)/2)*2'" in script
    assert "y='trunc(min(ih-oh\\,ih*0.2)/2)*2'" in script
    assert script.index("colorkey") < script.index("crop=w=") < script.index("scale=324:-2")


def test_height_limit_crops_layer_vertically() -> None:
    layer = LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.mp4"), width_percent=80, height_percent=50)
    script = _graph(layer, settings=RenderSettings(width=1080, height=1920)).script

    assert "crop=iw:'min(ih,960)':0:'(ih-oh)/2'" in script
    assert script.index("scale=864:-2") < script.index("min(ih,960)")


def test_no_height_limit_keeps_natural_height() -> None:
    layer = LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.mp4"))
    script = _graph(layer).script

    assert "min(ih," not in script


def test_canvas_source_crop_uses_output_aspect_and_bias() -> None:
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.mp4"),
        source_crop_canvas=True,
        source_crop_y=0.5,
    )
    script = _graph(layer, settings=RenderSettings(width=1080, height=1920)).script

    assert "crop=w='min(iw\\,ih*1080/1920)'" in script
    assert "h='min(ih\\,iw*1920/1080)'" in script
    assert "x='(iw-ow)/2'" in script
    assert "y='(ih-oh)/2*(1+0.5)'" in script


def test_source_crop_bounds_wins_over_canvas_flag() -> None:
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.mp4"),
        source_crop_canvas=True,
        source_crop_y=0.5,
        source_crop_bounds=(0.25, 0.25, 0.5, 0.5),
    )
    script = _graph(layer).script

    assert "trunc(iw*0.5/2)*2" in script
    assert "min(iw\\,ih*1080/1920)" not in script


def test_layer_store_roundtrip_preserves_edge_fields(tmp_path: Path) -> None:
    store_path = tmp_path / "overlay.json"
    source = tmp_path / "蒙版.mp4"
    source.write_bytes(b"stub")

    store = LayerStore(LayerKind.OVERLAY, store_path=store_path)
    added = store.add(source)
    updated = added.with_changes(
        feather=0.4,
        top_fade=0.3,
        height_percent=55.0,
        source_crop_canvas=True,
        source_crop_y=-0.5,
        source_crop_bounds=(0.1, 0.2, 0.3, 0.4),
    )
    assert store.replace(updated) is True

    reloaded = LayerStore(LayerKind.OVERLAY, store_path=store_path)
    layer = reloaded.layers[0]
    assert layer.feather == pytest.approx(0.4)
    assert layer.top_fade == pytest.approx(0.3)
    assert layer.height_percent == pytest.approx(55.0)
    assert layer.source_crop_canvas is True
    assert layer.source_crop_y == pytest.approx(-0.5)
    assert layer.source_crop_bounds == pytest.approx((0.1, 0.2, 0.3, 0.4))


def test_layer_store_loads_legacy_and_tolerates_invalid_bounds(tmp_path: Path) -> None:
    store_path = tmp_path / "legacy.json"
    legacy_source = tmp_path / "旧蒙版.mp4"
    invalid_source = tmp_path / "坏蒙版.mp4"
    legacy_source.write_bytes(b"stub")
    invalid_source.write_bytes(b"stub")

    payload = {
        "kind": "overlay",
        "layers": [
            {"id": "legacy", "source": str(legacy_source), "start_seconds": 0.0, "enabled": True},
            {
                "id": "invalid",
                "source": str(invalid_source),
                "source_crop_bounds": ["oops", 0.2, 0.3, 0.4],
            },
            {
                "id": "short",
                "source": str(invalid_source),
                "source_crop_bounds": [0.1, 0.2, 0.3],
            },
        ],
    }
    store_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    store = LayerStore(LayerKind.OVERLAY, store_path=store_path)
    assert len(store.layers) == 3

    legacy = store.find("legacy")
    assert legacy is not None
    assert legacy.feather == 0.0
    assert legacy.top_fade == 0.0
    assert legacy.source_crop_canvas is False
    assert legacy.source_crop_y == 0.0
    assert legacy.source_crop_bounds is None

    assert store.find("invalid").source_crop_bounds is None
    assert store.find("short").source_crop_bounds is None
