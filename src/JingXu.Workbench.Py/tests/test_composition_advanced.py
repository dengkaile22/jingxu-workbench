"""统一比例 / 导出兼容性 / 差异化滤镜 / 音频库 BGM / 效果模板测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.application.composition_service import CompositionDraft, build_requests
from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.render import (
    BgmSource,
    FitMode,
    OutputResolutionPreset,
    OutputVideoSettings,
    RenderSettings,
    VariationSettings,
)
from jingxu.infrastructure.effect_templates import EffectTemplateStore
from jingxu.infrastructure.filter_graph import build_filter_graph


def _plan(*assets, seed: int | None = None) -> CompositionPlan:
    return CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL, seed=seed)


def test_fit_mode_crop_uses_increase_and_crop() -> None:
    graph = build_filter_graph(
        _plan(make_asset("a.mp4")),
        RenderSettings(width=1080, height=1920, fit_mode=FitMode.CROP),
    )
    assert "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" in graph.script
    assert "pad=" not in graph.script


def test_output_resolution_scales_final_canvas_by_short_edge() -> None:
    graph = build_filter_graph(
        _plan(make_asset("a.mp4")),
        RenderSettings(
            width=1080,
            height=1920,
            output_video=OutputVideoSettings(resolution=OutputResolutionPreset.P720),
        ),
    )
    assert "[vcat]scale=720:1280[vout]" in graph.script


def test_output_resolution_landscape_short_edge() -> None:
    graph = build_filter_graph(
        _plan(make_asset("a.mp4")),
        RenderSettings(
            width=1920,
            height=1080,
            output_video=OutputVideoSettings(resolution=OutputResolutionPreset.P480),
        ),
    )
    assert "[vcat]scale=854:480[vout]" in graph.script


def test_output_height_without_override_keeps_null_passthrough() -> None:
    graph = build_filter_graph(_plan(make_asset("a.mp4")), RenderSettings())
    assert "[vcat]null[vout]" in graph.script


def test_main_volume_inserts_volume_filter() -> None:
    graph = build_filter_graph(
        _plan(make_asset("a.mp4")),
        RenderSettings(main_volume_percent=50),
    )
    assert "[acat]volume=0.500[acatv]" in graph.script
    assert "[acatv]anull[aout]" in graph.script


def test_variation_filters_are_deterministic_per_seed() -> None:
    settings = RenderSettings(variation=VariationSettings(intensity=80))
    first = build_filter_graph(_plan(make_asset("a.mp4"), make_asset("b.mp4"), seed=7), settings)
    second = build_filter_graph(_plan(make_asset("a.mp4"), make_asset("b.mp4"), seed=7), settings)
    other = build_filter_graph(_plan(make_asset("a.mp4"), make_asset("b.mp4"), seed=99), settings)

    assert "[0:v]" in first.script and "crop=iw*" in first.script and "eq=brightness=" in first.script
    assert ("hflip" in first.script) or ("vflip" in first.script)
    assert first.script == second.script
    assert first.script != other.script


def test_variation_disabled_keeps_plain_chain() -> None:
    graph = build_filter_graph(_plan(make_asset("a.mp4")), RenderSettings())
    assert "hflip" not in graph.script and "eq=brightness" not in graph.script


def test_library_bgm_is_sampled_per_request(tmp_path: Path) -> None:
    tracks = []
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        path = tmp_path / name
        path.write_bytes(b"stub")
        tracks.append(path)

    requests = build_requests(
        assets=[make_asset("素材.mp4")],
        draft=CompositionDraft(
            mode=OrderMode.RANDOM,
            seed=5,
            batch_count=3,
            bgm_source=BgmSource(
                kind="library",
                volume_mode="random",
                volume_min=10,
                volume_max=20,
            ),
            bgm_tracks=tuple(tracks),
        ),
        output_directory=tmp_path / "out",
    )

    assert len(requests) == 3
    for request in requests:
        assert request.bgm is not None
        assert request.bgm.path in tracks
        assert 10 <= request.bgm.resolved_volume_percent <= 20


def test_single_file_bgm_wins_over_library(tmp_path: Path) -> None:
    file_bgm = tmp_path / "single.mp3"
    file_bgm.write_bytes(b"stub")
    library_track = tmp_path / "lib.mp3"
    library_track.write_bytes(b"stub")

    requests = build_requests(
        assets=[make_asset("素材.mp4")],
        draft=CompositionDraft(
            bgm_source=BgmSource(kind="file", path=file_bgm, volume_percent=77),
            bgm_tracks=(library_track,),
        ),
        output_directory=tmp_path / "out",
    )

    assert requests[0].bgm is not None
    assert requests[0].bgm.path == file_bgm
    assert requests[0].bgm.resolved_volume_percent == 77


def test_effect_template_store_roundtrip(tmp_path: Path) -> None:
    store = EffectTemplateStore(tmp_path / "templates.json")
    payload = {"aspect": "9:16", "crf": 23, "split_enabled": True}

    store.save("竖屏爆款", payload)
    assert store.names == ["竖屏爆款"]
    assert store.get("竖屏爆款") == payload

    assert store.rename("竖屏爆款", "竖屏模板") is True
    assert store.names == ["竖屏模板"]

    reloaded = EffectTemplateStore(tmp_path / "templates.json")
    assert reloaded.get("竖屏模板") == payload

    assert reloaded.delete("竖屏模板") is True
    assert reloaded.names == []

    with pytest.raises(ValueError, match="模板名称不能为空"):
        reloaded.save("   ", payload)
