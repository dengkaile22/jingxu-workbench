"""BGM 混音、封面与图层/分屏的编排测试。"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import make_asset

from jingxu.application.composition_service import CompositionDraft, build_requests
from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import (
    AUDIO_PERCENT_MAX,
    AUDIO_PERCENT_MIN,
    DEFAULT_BGM_GAIN,
    BgmSettings,
    BgmSource,
    RenderSettings,
    audio_percent_to_gain,
    gain_to_audio_percent,
    legacy_bgm_percent_to_percent,
)
from jingxu.domain.splitscreen import SplitMode, SplitScreenSpec
from jingxu.infrastructure.filter_graph import build_filter_graph


def _plan(*assets) -> CompositionPlan:
    return CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL)


def test_bgm_is_trimmed_mixed_and_faded() -> None:
    graph = build_filter_graph(
        _plan(make_asset("a.mp4", duration=4.0)),
        RenderSettings(),
        bgm=BgmSettings(path=Path("bgm.mp3"), volume_percent=40, fade_out_seconds=1.5),
    )

    assert "[1:a]" in graph.script
    assert "atrim=duration=4.000" in graph.script
    assert "volume=0.400" in graph.script
    assert "afade=t=out:st=2.500:d=1.500" in graph.script
    assert "[acat][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]" in graph.script
    assert graph.has_audio is True
    assert graph.extra_inputs[-1].purpose == "bgm"


def test_bgm_only_when_assets_have_no_audio() -> None:
    graph = build_filter_graph(
        _plan(make_asset("a.mp4", has_audio=False)),
        RenderSettings(),
        bgm=BgmSettings(path=Path("bgm.mp3")),
    )

    assert "amix" not in graph.script
    assert ",anull[aout]" in graph.script


def test_no_bgm_keeps_original_chain() -> None:
    graph = build_filter_graph(_plan(make_asset("a.mp4")), RenderSettings())
    assert "amix" not in graph.script
    assert "concat=n=1:v=1:a=1[vcat][acat]" in graph.script
    assert "[acat]anull[aout]" in graph.script


def test_layer_overlay_uses_window_and_position() -> None:
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.mp4"),
        start_seconds=2.0,
        end_seconds=5.0,
        x_percent=25.0,
        y_percent=75.0,
        width_percent=40.0,
        opacity=0.8,
        remove_black=True,
    )
    graph = build_filter_graph(_plan(make_asset("a.mp4", duration=8.0)), RenderSettings(), layers=(layer,))

    assert graph.extra_inputs[0].purpose == "layer"
    assert "[1:v]trim=duration=3.000,setpts=PTS-STARTPTS+2.000/TB" in graph.script
    assert "colorkey=black:0.10:0.06" in graph.script
    assert "colorchannelmixer=aa=0.800" in graph.script
    assert "main_w*0.2500-overlay_w/2" in graph.script
    assert "main_h*0.7500-overlay_h/2" in graph.script
    assert "eof_action=pass" in graph.script
    assert "[vcat][lay0]overlay" in graph.script
    assert "[vout]" in graph.script


def test_disabled_layer_is_skipped() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), enabled=False)
    graph = build_filter_graph(_plan(make_asset("a.mp4")), RenderSettings(), layers=(layer,))
    assert graph.extra_inputs == ()
    assert "overlay" not in graph.script


def test_four_screen_uses_xstack_and_aux_once() -> None:
    split = SplitScreenSpec(
        mode=SplitMode.FOUR,
        same_source=False,
        aux_paths=(Path("aux1.mp4"), Path("aux2.mp4"), Path("aux3.mp4")),
        start_index=0,
    )
    graph = build_filter_graph(_plan(make_asset("a.mp4", duration=3.0)), RenderSettings(), split=split)

    purposes = [extra.purpose for extra in graph.extra_inputs]
    assert purposes == ["aux", "aux", "aux"]
    assert "[1:v]split=1[aux0_0]" in graph.script
    assert "[2:v]split=1[aux1_0]" in graph.script
    assert "[3:v]split=1[aux2_0]" in graph.script
    assert "xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0" in graph.script
    assert "trim=duration=3.000" in graph.script  # 辅助素材裁剪到片段时长


def test_double_screen_same_source_uses_split_copies() -> None:
    split = SplitScreenSpec(mode=SplitMode.DOUBLE_H, same_source=True, start_index=1, feather=False)
    graph = build_filter_graph(
        _plan(make_asset("a.mp4"), make_asset("b.mp4")),
        RenderSettings(),
        split=split,
    )

    assert graph.extra_inputs == ()
    assert "[0:v]" in graph.script
    # 第二段才分屏
    assert "[v1]split=2[same1_0][same1_1]" in graph.script
    assert "hstack=inputs=2" in graph.script
    assert graph.script.count("hstack") == 1


def test_feather_overlays_cached_gradient() -> None:
    split = SplitScreenSpec(mode=SplitMode.FOUR, same_source=True, start_index=0, feather=True)
    graph = build_filter_graph(
        _plan(make_asset("a.mp4")),
        RenderSettings(),
        split=split,
        gradient_path=Path("feather.png"),
    )

    assert graph.extra_inputs[-1].purpose == "gradient"
    assert "[1:v]split=1[grad0]" in graph.script
    assert "[v0_comp][grad0]overlay=0:0:shortest=1[v0]" in graph.script


def test_draft_split_and_layers_flow_into_requests(tmp_path: Path) -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"))
    requests = build_requests(
        assets=[make_asset("a.mp4")],
        draft=CompositionDraft(
            mode=OrderMode.RANDOM,
            seed=1,
            output_prefix="测试",
            cover_enabled=True,
            cover_at_seconds=2.5,
            bgm=BgmSettings(path=Path("bgm.mp3"), volume_percent=20),
            split=SplitScreenSpec(mode=SplitMode.DOUBLE_H, same_source=True),
            layers=(layer,),
        ),
        output_directory=tmp_path,
    )

    request = requests[0]
    assert request.cover is not None
    assert request.cover.output_path.name == "测试.jpg"
    assert request.cover.at_seconds == 2.5
    assert request.bgm is not None and request.bgm.volume_percent == 20
    assert request.split is not None and request.split.mode is SplitMode.DOUBLE_H
    assert request.layers and request.layers[0].kind is LayerKind.STICKER
    script = build_filter_graph(request.plan, request.settings, layers=request.layers).script
    assert "trim=duration=" in script and "eof_action=pass" in script


# ── 背景音乐音量语义（−100..+100，对齐 .NET AudioVolumeMapping）───────────────


def test_audio_percent_to_gain_anchors() -> None:
    """三个锚点：−100 静音、0 默认 BGM 音量、+100 最大。"""
    assert audio_percent_to_gain(AUDIO_PERCENT_MIN) == 0.0
    assert audio_percent_to_gain(0) == DEFAULT_BGM_GAIN
    assert audio_percent_to_gain(AUDIO_PERCENT_MAX) == 1.0


def test_audio_percent_to_gain_is_monotonic_and_clamped() -> None:
    values = [audio_percent_to_gain(percent) for percent in range(-100, 101, 10)]
    assert values == sorted(values)
    assert audio_percent_to_gain(-500) == 0.0
    assert audio_percent_to_gain(500) == 1.0
    assert all(0.0 <= value <= 1.0 for value in values)


def test_gain_to_audio_percent_round_trips() -> None:
    for percent in (-100, -50, 0, 25, 50, 100):
        assert gain_to_audio_percent(audio_percent_to_gain(percent)) == percent


def test_legacy_bgm_percent_migration_matches_gain_curve() -> None:
    """旧「百分数即增益」换算后必须保留原增益（±0.02 容差）。"""
    for old in (0, 5, 18, 30, 50, 100, 200):
        new = legacy_bgm_percent_to_percent(old)
        expected_gain = min(old / 100.0, 1.0)
        assert abs(audio_percent_to_gain(new) - expected_gain) <= 0.02, old


def test_bgm_settings_default_is_legacy_gain() -> None:
    """未显式指定音量时必须保持旧默认值 0.18，避免既有行为漂移。"""
    settings = BgmSettings(path=Path("bgm.mp3"))
    assert settings.resolved_gain == DEFAULT_BGM_GAIN
    assert settings.resolved_volume_percent == 0


def test_bgm_settings_legacy_percent_override_still_direct_gain() -> None:
    """兼容路径：显式传 volume_percent 时按旧语义（percent/100）直算。"""
    settings = BgmSettings(path=Path("bgm.mp3"), volume_percent=40)
    assert settings.resolved_gain == 0.4
    assert settings.resolved_volume_percent == 40


def test_bgm_gain_is_used_in_filter_script() -> None:
    """音量以增益写进滤镜：0% → 0.180，+100% → 1.000。"""
    default_graph = build_filter_graph(
        _plan(make_asset("a.mp4", duration=2.0)),
        RenderSettings(),
        bgm=BgmSettings(path=Path("bgm.mp3"), volume_gain=audio_percent_to_gain(0)),
    )
    assert "volume=0.180" in default_graph.script

    max_graph = build_filter_graph(
        _plan(make_asset("a.mp4", duration=2.0)),
        RenderSettings(),
        bgm=BgmSettings(path=Path("bgm.mp3"), volume_gain=audio_percent_to_gain(100)),
    )
    assert "volume=1.000" in max_graph.script


def test_bgm_source_random_range_uses_new_semantics() -> None:
    source = BgmSource(kind="library", volume_mode="random", volume_min=-20, volume_max=-10)
    percents = {source.resolved_volume(offset) for offset in range(8)}
    assert percents and all(-20 <= percent <= -10 for percent in percents)
    assert all(0.0 <= source.resolved_gain(offset) <= DEFAULT_BGM_GAIN for offset in range(8))


def test_bgm_source_negative_volume_is_quieter_than_default() -> None:
    quiet = BgmSource(kind="file", path=Path("bgm.mp3"), volume_percent=-50)
    loud = BgmSource(kind="file", path=Path("bgm.mp3"), volume_percent=50)
    assert quiet.resolved_gain(0) < DEFAULT_BGM_GAIN < loud.resolved_gain(0)
