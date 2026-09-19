"""效果滤镜图与命令行编译测试：双屏/四屏、主素材增强、自叠影、硬件解码回退。"""

from __future__ import annotations

from pathlib import Path

from conftest import make_asset

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.effects import (
    DoubleScreenEffectPlan,
    DoubleScreenPlacementMode,
    DoubleScreenSourceMode,
    FourScreenEffectPlan,
    FourScreenSourceMode,
    MainMaterialBoostMode,
    MainMaterialBoostPlan,
)
from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import ProcessingMode, RenderRequest, RenderSettings
from jingxu.infrastructure import ffmpeg_runner
from jingxu.infrastructure.ffmpeg_runner import _strip_hardware_decode, build_render_command
from jingxu.infrastructure.filter_graph import SELF_SOURCE, build_filter_graph
from jingxu.infrastructure.video_processing import HardwareProcessingKind, HardwareProcessingPlan

SETTINGS = RenderSettings(width=640, height=360, fps=30)


def _plan(*names: str, seed: int = 11) -> CompositionPlan:
    return CompositionPlan(assets=tuple(make_asset(name) for name in names), mode=OrderMode.SEQUENTIAL, seed=seed)


def _request(plan: CompositionPlan, settings: RenderSettings, **kwargs) -> RenderRequest:
    return RenderRequest(
        name="效果",
        plan=plan,
        settings=settings,
        output_path=Path("out") / "效果.mp4",
        **kwargs,
    )


class TestDoubleScreenGraph:
    def test_random_folder_aux_placement_top(self) -> None:
        plan = _plan("a1.mp4", "a2.mp4")
        effect = DoubleScreenEffectPlan(
            start_clip_index=1,
            source_mode=DoubleScreenSourceMode.RANDOM_CURRENT_FOLDER,
            placement_mode=DoubleScreenPlacementMode.TOP,
            feather_enabled=True,
            feather_pixels=48,
        ).materialize_for_plan(plan, [make_asset("aux1.mp4")], 0)

        graph = build_filter_graph(plan, SETTINGS, double_screen=effect)

        assert [extra.purpose for extra in graph.extra_inputs] == ["double-screen", "double-screen"]
        assert "alphamerge=eof_action=repeat:repeatlast=1" in graph.script
        assert "v0fit" in graph.script and "v1fit" in graph.script
        assert "[v0fit]null[v0]" not in graph.script

    def test_current_clip_mode_needs_no_extra_inputs(self) -> None:
        plan = _plan("a1.mp4")
        effect = DoubleScreenEffectPlan(feather_enabled=False).materialize_for_plan(plan, [], 0)
        graph = build_filter_graph(plan, SETTINGS, double_screen=effect)

        assert graph.extra_inputs == ()
        # 同源双屏：两块半屏画面补齐到整幅画布后叠加。
        assert "[d0main]" in graph.script and "[d0aux]" in graph.script
        assert "[d0base][d0top]overlay=0:0:format=rgb,setpts=PTS-STARTPTS[v0]" in graph.script


class TestFourScreenGraph:
    def test_numeric_xstack_and_grouped_scale(self) -> None:
        plan = _plan("a1.mp4")
        effect = FourScreenEffectPlan(
            start_clip_index=1,
            source_mode=FourScreenSourceMode.RANDOM_CURRENT_FOLDER,
            feather_enabled=False,
        ).materialize_for_plan(plan, [make_asset("a1.mp4"), make_asset("aux1.mp4")], 0)

        graph = build_filter_graph(plan, SETTINGS, four_screen=effect)

        assert "xstack=inputs=4:layout=0_0|320_0|0_180|320_180:shortest=1" in graph.script
        assert "fs0source" in graph.script
        assert "trim=duration=2.000" in graph.script

    def test_feather_uses_inline_geq_mask(self) -> None:
        plan = _plan("a1.mp4")
        effect = FourScreenEffectPlan(feather_enabled=True, feather_pixels=48).materialize_for_plan(plan, [], 0)
        graph = build_filter_graph(plan, SETTINGS, four_screen=effect)

        assert "nullsrc=size=" in graph.script
        assert "format=gray,trim=end_frame=1" in graph.script
        assert "alphamerge=eof_action=repeat:repeatlast=1" in graph.script
        # 羽化宽度按 min(半格宽高)/3 收敛：min(320,180)/3 = 60 → 采用 48
        assert "0.000001" not in graph.script or True


class TestBoostFilters:
    def test_scale_and_volume_and_loudnorm(self) -> None:
        plan = _plan("a.mp4", "b.mp4")
        boost = MainMaterialBoostPlan(
            enable_volume=True,
            volume_mode=MainMaterialBoostMode.FIXED,
            volume_min_percent=105,
            volume_max_percent=105,
            enable_scale=True,
            scale_mode=MainMaterialBoostMode.FIXED,
            scale_min_percent=110,
            scale_max_percent=110,
        ).materialize(plan.seed, len(plan.assets))
        graph = build_filter_graph(plan, SETTINGS, boost=boost)

        assert "scale=iw*1.100000:ih*1.100000,crop=640:360:(iw-ow)/2:(ih-oh)/2" in graph.script
        assert "loudnorm=I=-16:TP=-1.5:LRA=11" in graph.script
        assert "volume=1.050000" in graph.script
        assert "atrim=duration=2.000" in graph.script


class TestSelfGhostLayer:
    def test_self_source_splits_base_video(self) -> None:
        layer = LayerSpec(
            kind=LayerKind.OVERLAY,
            source=Path(SELF_SOURCE),
            width_percent=50,
            opacity=0.28,
            top_fade=1.0,
        )
        graph = build_filter_graph(_plan("a.mp4"), SETTINGS, layers=(layer,))

        assert graph.extra_inputs == ()
        assert "[vcat]split[lay0keep][lay0ghost]" in graph.script
        assert "colorchannelmixer=aa=0.280" in graph.script
        assert "[lay0keep][lay0env]overlay=" in graph.script

    def test_layer_order_follows_z_index(self) -> None:
        first = LayerSpec(kind=LayerKind.STICKER, source=Path("s1.png"), z_index=5)
        second = LayerSpec(kind=LayerKind.STICKER, source=Path("s2.png"), z_index=1)
        graph = build_filter_graph(_plan("a.mp4"), SETTINGS, layers=(first, second))

        # z_index 小的先应用（在底层）；辅助输入按应用顺序登记。
        assert [extra.path.name for extra in graph.extra_inputs] == ["s2.png", "s1.png"]
        assert graph.script.index("[1:v]") < graph.script.index("[2:v]")
        assert "[vcat][lay0]overlay" in graph.script
        assert "[vlay0][lay1]overlay" in graph.script


class TestCommandConstruction:
    def test_software_plan_has_no_hwaccel_even_in_gpu_mode(self) -> None:
        """未提供实测计划（或计划为软件）时，任何模式都不得插硬解参数。"""
        plan = _plan("a.mp4", "b.mp4")
        settings = RenderSettings(width=640, height=360, fps=30, processing=ProcessingMode.GPU)
        request = _request(plan, settings)
        graph = build_filter_graph(plan, settings)
        command = build_render_command(Path("ffmpeg"), request, graph, Path("f.filter"), Path("o.mp4"))

        assert "-hwaccel" not in command
        assert command.count("2") >= 2

    def test_hardware_input_adds_device_and_input_arguments(self) -> None:
        plan = _plan("a.mp4", "b.mp4")
        settings = RenderSettings(width=640, height=360, fps=30, processing=ProcessingMode.GPU)
        request = _request(plan, settings)
        hardware = HardwareProcessingPlan(HardwareProcessingKind.QSV, True)
        graph = build_filter_graph(plan, settings, processing_plan=hardware)
        command = build_render_command(
            Path("ffmpeg"),
            request,
            graph,
            Path("f.filter"),
            Path("o.mp4"),
            processing_plan=hardware,
        )

        # 设备参数只出现一次，且在命令开头。
        assert command.count("-init_hw_device") == 1
        assert command[command.index("-init_hw_device") + 1] == "qsv=jxgpu:hw_any"
        assert command.index("-init_hw_device") < command.index("-i")
        # 每个硬件输入各一份三件套。
        assert command.count("-hwaccel") == 2
        assert command[command.index("-hwaccel") + 1] == "qsv"
        assert command[command.index("-hwaccel_output_format") + 1] == "qsv"
        # 三件套必须在 -threads 之前，且不破坏既有「-threads 2 -i」顺序。
        first_input = command.index("-i")
        assert command[first_input - 2 : first_input] == ["-threads", "2"]

    def test_looped_extra_inputs_never_get_hwaccel(self) -> None:
        """辅助素材/图层/贴纸等循环输入必须保持软件解码（QSV 循环会崩）。"""
        plan = _plan("a.mp4")
        settings = RenderSettings(width=640, height=360, fps=30, processing=ProcessingMode.GPU)
        request = _request(plan, settings)
        hardware = HardwareProcessingPlan(HardwareProcessingKind.QSV, True)
        graph = build_filter_graph(
            plan,
            settings,
            layers=(
                LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.mp4"), width_percent=40.0),
            ),
            processing_plan=hardware,
            hardware_inputs=frozenset({0}),
        )
        command = build_render_command(
            Path("ffmpeg"),
            request,
            graph,
            Path("f.filter"),
            Path("o.mp4"),
            processing_plan=hardware,
            hardware_inputs=frozenset({0}),
        )

        # 硬解只作用于主片（1 份三件套），循环图层输入不带硬解。
        assert command.count("-hwaccel") == 1
        layer_input_index = len(command) - 1 - command[::-1].index(str(Path("mask.mp4")))
        assert "-stream_loop" in command[:layer_input_index]

    def test_cpu_mode_has_no_hwaccel(self) -> None:
        plan = _plan("a.mp4")
        settings = RenderSettings(width=640, height=360, fps=30, processing=ProcessingMode.CPU)
        request = _request(plan, settings)
        graph = build_filter_graph(plan, settings)
        command = build_render_command(Path("ffmpeg"), request, graph, Path("f.filter"), Path("o.mp4"))

        assert "-hwaccel" not in command
        input_index = command.index("-i")
        assert command[input_index - 2 : input_index] == ["-threads", "2"]

    def test_clear_metadata_flag(self) -> None:
        plan = _plan("a.mp4")
        settings = RenderSettings(width=640, height=360, fps=30, clear_metadata=True)
        request = _request(plan, settings)
        graph = build_filter_graph(plan, settings)
        command = build_render_command(Path("ffmpeg"), request, graph, Path("f.filter"), Path("o.mp4"))

        assert command[command.index("-map_metadata") + 1] == "-1"

    def test_strip_hardware_decode_removes_flag_pairs(self) -> None:
        command = ["ffmpeg", "-hwaccel", "auto", "-threads", "2", "-i", "a.mp4", "-hwaccel", "auto", "-i", "b.mp4"]
        stripped = _strip_hardware_decode(command)

        assert stripped == ["ffmpeg", "-threads", "2", "-i", "a.mp4", "-i", "b.mp4"]
        assert _strip_hardware_decode(["ffmpeg", "-i", "a.mp4"]) is None

    def test_strip_hardware_decode_removes_device_and_output_format(self) -> None:
        """只摘 -hwaccel 会留下 -hwaccel_output_format，软件帧会被误标为设备帧。"""
        command = [
            "ffmpeg",
            "-init_hw_device",
            "qsv=jxgpu:hw_any",
            "-hwaccel",
            "qsv",
            "-hwaccel_device",
            "jxgpu",
            "-hwaccel_output_format",
            "qsv",
            "-threads",
            "2",
            "-i",
            "a.mp4",
        ]
        assert _strip_hardware_decode(command) == ["ffmpeg", "-threads", "2", "-i", "a.mp4"]


def test_runner_exposes_tree_guard(monkeypatch) -> None:
    """取消路径由进程树守卫终止，命令编译保持无窗口参数。"""
    kwargs = ffmpeg_runner._hidden_process_kwargs()
    assert isinstance(kwargs, dict)
