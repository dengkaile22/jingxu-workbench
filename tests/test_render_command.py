"""FFmpeg 命令编译测试。"""

from __future__ import annotations

from pathlib import Path

from conftest import make_asset

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import RenderRequest, RenderSettings, VariationSettings
from jingxu.infrastructure.encoders import CPU_ENCODER
from jingxu.infrastructure.ffmpeg_runner import build_render_command
from jingxu.infrastructure.filter_graph import build_filter_graph

SETTINGS = RenderSettings(width=1080, height=1920, fps=30, crf=21, preset="fast")


def _request(*assets, **kwargs) -> RenderRequest:
    plan = CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL)
    return RenderRequest(
        name="混剪 #1",
        plan=plan,
        settings=SETTINGS,
        output_path=Path("out") / "混剪_1.mp4",
        **kwargs,
    )


def test_command_maps_inputs_graph_and_codec() -> None:
    request = _request(make_asset("a.mp4"), make_asset("b.mp4"))
    graph = build_filter_graph(request.plan, request.settings)
    command = build_render_command(
        Path("ffmpeg"), request, graph, Path("concat.filter"), request.output_path
    )

    assert command[:4] == ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    assert command.count("-i") == 2
    assert command[command.index("-filter_complex_script") + 1].endswith("concat.filter")
    assert command[command.index("-map") + 1] == "[vout]"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "[aout]"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-crf") + 1] == "21"
    assert command[command.index("-preset") + 1] == "fast"
    assert command[-1].endswith("混剪_1.mp4")
    assert command[-4:-1] == ["-progress", "pipe:1", "-nostats"]


def test_command_without_audio_omits_audio_mapping() -> None:
    request = _request(make_asset("a.mp4", has_audio=False))
    graph = build_filter_graph(request.plan, request.settings)
    command = build_render_command(
        Path("ffmpeg"), request, graph, Path("concat.filter"), request.output_path
    )

    assert "[aout]" not in command
    assert "-c:a" not in command


def test_image_layers_use_loop_and_video_layers_use_stream_loop() -> None:
    layer_video = LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.mp4"))
    layer_image = LayerSpec(kind=LayerKind.STICKER, source=Path("sticker.png"))
    request = _request(make_asset("a.mp4"), layers=(layer_video, layer_image))
    graph = build_filter_graph(request.plan, request.settings, layers=request.layers)
    command = build_render_command(
        Path("ffmpeg"), request, graph, Path("concat.filter"), request.output_path
    )

    assert command[command.index("-stream_loop") + 1] == "-1"
    assert command[command.index("-loop") + 1] == "1"
    assert command.count("-i") == 3


def test_variation_rotate_sits_between_mirror_and_crop() -> None:
    plan = CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL, seed=1)
    settings = RenderSettings(
        variation=VariationSettings(intensity=100, rotate=True, rotation_max_degrees=2.0)
    )
    script = build_filter_graph(plan, settings).script

    assert ":ow=iw:oh=ih:c=black" in script
    assert script.index("flip") < script.index("rotate=") < script.index("crop=iw*")


def test_variation_chain_is_deterministic_per_seed() -> None:
    plan = CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL, seed=7)
    settings = RenderSettings(variation=VariationSettings(intensity=100, rotate=False))
    first = build_filter_graph(plan, settings).script
    second = build_filter_graph(plan, settings).script

    assert first == second
    assert "eq=brightness=" in first and "contrast=" in first
    assert "crop=iw*" in first
    assert "rotate=" not in first


def test_variation_mirror_uses_hflip_or_vflip() -> None:
    plan = CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL, seed=3)
    settings = RenderSettings(variation=VariationSettings(intensity=100, light_crop=False, color=False))
    script = build_filter_graph(plan, settings).script
    assert "hflip" in script or "vflip" in script


def test_variation_denoise_uses_intensity_strength() -> None:
    plan = CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL, seed=5)
    settings = RenderSettings(
        variation=VariationSettings(intensity=200, mirror=False, light_crop=False, color=False, denoise=True, rotate=False)
    )
    script = build_filter_graph(plan, settings).script
    assert "hqdn3d=5.0:5.0:5.0" in script


def test_encoder_quality_args_are_used() -> None:
    request = _request(make_asset("a.mp4"))
    graph = build_filter_graph(request.plan, request.settings)
    command = build_render_command(
        Path("ffmpeg"),
        request,
        graph,
        Path("concat.filter"),
        request.output_path,
        encoder=CPU_ENCODER,
    )

    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-crf") + 1] == "21"
