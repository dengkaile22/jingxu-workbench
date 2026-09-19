"""硬件解码/缩放：白名单、尺寸计算、设备参数、失败分类与探测缓存。

纯函数级测试，不依赖真实 GPU 或 FFmpeg；真实设备行为由集成测试覆盖。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.domain.render import FitMode, ProcessingMode
from jingxu.infrastructure.encoders import CPU_ENCODER, EncoderChoice
from jingxu.infrastructure.video_processing import (
    DEFAULT_PROBE_TIMEOUT,
    DOWNLOAD_FILTER,
    HARDWARE_DEVICE_NAME,
    HardwareProcessingKind,
    HardwareProcessingPlan,
    HardwareProcessingSelector,
    SOFTWARE_PLAN,
    hardware_failure_markers,
    has_downscale_opportunity,
    is_hardware_encoder_failure,
    is_hardware_failure,
    resolve_hardware_scaled_size,
)

QSV = HardwareProcessingPlan(HardwareProcessingKind.QSV, True)
CUDA = HardwareProcessingPlan(HardwareProcessingKind.CUDA, True)
D3D11 = HardwareProcessingPlan(HardwareProcessingKind.D3D11, False)

NVENC = EncoderChoice("h264_nvenc", "NVIDIA NVENC", True)
QSV_ENCODER = EncoderChoice("h264_qsv", "Intel Quick Sync", True)


# ── 白名单 ──────────────────────────────────────────────────────────────────


def test_software_plan_supports_nothing() -> None:
    assert SOFTWARE_PLAN.supports(make_asset()) is False
    assert SOFTWARE_PLAN.is_software is True
    assert SOFTWARE_PLAN.device_arguments == []
    assert SOFTWARE_PLAN.input_arguments == []


def test_supports_accepts_whitelisted_asset() -> None:
    asset = make_asset(width=1920, height=1080)
    assert QSV.supports(asset) is True
    assert CUDA.supports(asset) is True
    assert D3D11.supports(asset) is True


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"video_codec": "hevc"}, id="non-h264"),
        pytest.param({"pixel_format": "yuv444p"}, id="yuv444p"),
        pytest.param({"pixel_format": "yuv420p10le"}, id="10bit"),
        pytest.param({"pixel_format": ""}, id="empty-pixel-format"),
        pytest.param({"rotation_degrees": 90}, id="rotated"),
        pytest.param({"width": 1081}, id="odd-width"),
        pytest.param({"height": 361}, id="odd-height"),
        pytest.param({"width": 100}, id="below-min-edge"),
        pytest.param({"height": 4320}, id="above-max-edge"),
    ],
)
def test_supports_rejects_incompatible_asset(kwargs: dict) -> None:
    assert QSV.supports(make_asset(**kwargs)) is False


def test_supports_accepts_boundary_sizes() -> None:
    assert QSV.supports(make_asset(width=128, height=128)) is True
    assert QSV.supports(make_asset(width=4096, height=4096)) is True
    assert QSV.supports(make_asset(width=126, height=128)) is False
    assert QSV.supports(make_asset(width=4098, height=4096)) is False


# ── Auto / GPU 启用条件 ─────────────────────────────────────────────────────


def test_gpu_mode_uses_input_without_downscale_opportunity() -> None:
    """GPU 模式只要白名单通过就启用，不要求缩放收益。"""
    asset = make_asset(width=1920, height=1080)
    assert QSV.should_use_input(asset, ProcessingMode.GPU, FitMode.CROP, 1920, 1080) is True


def test_auto_mode_requires_downscale_opportunity() -> None:
    """目标画幅与源同尺寸 → Auto 不启用（没有回传收益）。"""
    asset = make_asset(width=1920, height=1080)
    assert QSV.should_use_input(asset, ProcessingMode.AUTO, FitMode.STRETCH, 1920, 1080) is False
    assert QSV.should_use_input(asset, ProcessingMode.AUTO, FitMode.PAD, 1080, 1920) is True


def test_auto_mode_requires_can_scale() -> None:
    """D3D11VA 只解码不缩放，Auto 下不满足收益前提。"""
    asset = make_asset(width=1920, height=1080)
    assert D3D11.should_use_input(asset, ProcessingMode.AUTO, FitMode.PAD, 1080, 1920) is False
    assert D3D11.should_use_input(asset, ProcessingMode.GPU, FitMode.PAD, 1080, 1920) is True


def test_should_use_input_rejects_non_whitelisted_even_in_gpu_mode() -> None:
    asset = make_asset(video_codec="hevc")
    assert QSV.should_use_input(asset, ProcessingMode.GPU, FitMode.CROP, 720, 1280) is False


# ── 尺寸计算与舍入 ─────────────────────────────────────────────────────────


def test_resolve_scaled_size_letterbox_uses_inner_rect() -> None:
    """PAD（Contain）：取内接矩形，两个方向都不超过目标。"""
    asset = make_asset(width=1920, height=1080)
    assert resolve_hardware_scaled_size(asset, FitMode.PAD, 1080, 1920) == (1080, 608)

    portrait = make_asset(width=1080, height=1920)
    assert resolve_hardware_scaled_size(portrait, FitMode.PAD, 1080, 1080) == (608, 1080)


def test_resolve_scaled_size_letterbox_returns_none_when_scaled_size_is_invalid() -> None:
    """内接矩形出现奇数边或越界时必须交回软件路径（实测值固化）。"""
    big = make_asset(width=2560, height=1440)
    assert resolve_hardware_scaled_size(big, FitMode.PAD, 720, 1280) is None
    # 同一素材换更大的画幅则是合法偶数内接矩形。
    assert resolve_hardware_scaled_size(big, FitMode.PAD, 1080, 1920) == (1080, 608)


def test_resolve_scaled_size_center_crop_uses_outer_rect() -> None:
    """CROP（Cover）：取外接矩形，覆盖整幅画布后裁切。"""
    asset = make_asset(width=1920, height=1080)
    assert resolve_hardware_scaled_size(asset, FitMode.CROP, 720, 1280) == (2276, 1280)


def test_resolve_scaled_size_center_crop_returns_none_when_exceeding_device_range() -> None:
    """竖屏成片时横屏素材会被放大到超过 4096，必须交回软件路径。"""
    asset = make_asset(width=1920, height=1080)
    assert resolve_hardware_scaled_size(asset, FitMode.CROP, 1080, 1920) is None
    assert resolve_hardware_scaled_size(asset, FitMode.CROP, 1080, 1920) is None


def test_resolve_scaled_size_stretch_uses_target() -> None:
    asset = make_asset(width=640, height=360)
    assert resolve_hardware_scaled_size(asset, FitMode.STRETCH, 720, 1280) == (720, 1280)


def test_resolve_scaled_size_stretch_returns_none_when_source_larger_than_target() -> None:
    """Stretch 直接用目标尺寸，源尺寸大于目标即视为放过（scale 无收益）。"""
    asset = make_asset(width=1920, height=1080)
    assert resolve_hardware_scaled_size(asset, FitMode.STRETCH, 3840, 2160) == (3840, 2160)


def test_resolve_scaled_size_midpoint_uses_away_from_zero() -> None:
    """必须用 AwayFromZero，而不是 Python round() 的银行家舍入。

    2560×1440 → 目标 1096×602（PAD）时 ``from_width = 1096*1440/2560 = 616.5``：
    AwayFromZero 得 617 → 内接高 ``int(1096*1440/2560)`` 路径给出 1070；
    若用银行家舍入得 616，则最终高会变成 1093（计算结果不同）。
    """
    asset = make_asset(width=2560, height=1440)
    assert resolve_hardware_scaled_size(asset, FitMode.PAD, 1096, 602) == (1070, 602)

    from jingxu.infrastructure.video_processing import _round_half_away_from_zero

    assert _round_half_away_from_zero(616.5) == 617
    assert _round_half_away_from_zero(292.5) == 293
    assert _round_half_away_from_zero(550.5) == 551
    # Python 内置 round 在前两个值上给出不同结果，正是本用例要防的回归。
    assert round(616.5) == 616
    assert round(292.5) == 292
    assert round(550.5) == 550


def test_resolve_scaled_size_rejects_blur_and_unknown_fit() -> None:
    asset = make_asset(width=1920, height=1080)
    assert resolve_hardware_scaled_size(asset, FitMode.BLUR, 720, 1280) is None


def test_resolve_scaled_size_rejects_out_of_range_target() -> None:
    asset = make_asset(width=1920, height=1080)
    # 目标过小（<128）或过大（>4096）都应交回软件路径。
    assert resolve_hardware_scaled_size(asset, FitMode.STRETCH, 64, 64) is None
    assert resolve_hardware_scaled_size(asset, FitMode.STRETCH, 5000, 5000) is None


def test_has_downscale_opportunity_true_only_when_pixels_shrink() -> None:
    asset = make_asset(width=1920, height=1080)
    assert has_downscale_opportunity(asset, FitMode.PAD, 1080, 1920) is True
    assert has_downscale_opportunity(asset, FitMode.STRETCH, 1920, 1080) is False
    assert has_downscale_opportunity(asset, FitMode.STRETCH, 3840, 2160) is False
    # 竖屏成片会把横屏素材放大到超范围，无收益。
    assert has_downscale_opportunity(asset, FitMode.CROP, 1080, 1920) is False
    # 内接矩形不可用时也无收益。
    assert has_downscale_opportunity(asset, FitMode.PAD, 720, 1280) is False


def test_has_downscale_opportunity_tolerates_empty_pixel_format() -> None:
    """该判定只回答"缩放是否有收益"，允许空 pix_fmt（白名单另有严格判定）。"""
    asset = make_asset(width=1920, height=1080, pixel_format="")
    assert has_downscale_opportunity(asset, FitMode.PAD, 1080, 1920) is True
    assert QSV.supports(asset) is False


# ── 设备与输入参数 ──────────────────────────────────────────────────────────


def test_device_arguments_per_kind() -> None:
    assert QSV.device_arguments == ["-init_hw_device", f"qsv={HARDWARE_DEVICE_NAME}:hw_any"]
    assert CUDA.device_arguments == ["-init_hw_device", f"cuda={HARDWARE_DEVICE_NAME}:0"]
    assert D3D11.device_arguments == ["-init_hw_device", f"d3d11va={HARDWARE_DEVICE_NAME}"]


def test_input_arguments_per_kind() -> None:
    assert QSV.input_arguments == [
        "-hwaccel",
        "qsv",
        "-hwaccel_device",
        HARDWARE_DEVICE_NAME,
        "-hwaccel_output_format",
        "qsv",
    ]
    assert CUDA.input_arguments[5] == "cuda"
    assert D3D11.input_arguments[5] == "d3d11"


def test_scale_and_download_per_kind() -> None:
    qsv_filter = QSV.scale_and_download(720, 1280)
    assert qsv_filter == f"scale_qsv=w=720:h=1280:format=nv12,{DOWNLOAD_FILTER}"

    cuda_filter = CUDA.scale_and_download(720, 1280)
    assert cuda_filter == f"scale_cuda=w=720:h=1280:format=nv12:passthrough=0,{DOWNLOAD_FILTER}"


def test_description_mentions_cpu_fallback_for_loops_and_overlays() -> None:
    assert SOFTWARE_PLAN.description == "解码与缩放使用 CPU。"
    assert "循环辅助视频、蒙版与合成使用 CPU" in QSV.description
    assert "缩放可用 GPU" in QSV.description
    assert "缩放使用 CPU" in D3D11.description


# ── 主片适配前缀 ────────────────────────────────────────────────────────────


def test_build_main_fit_filter_returns_none_for_blur_and_d3d11() -> None:
    asset = make_asset(width=1920, height=1080)
    assert D3D11.build_main_fit_filter(asset, FitMode.PAD, 720, 1280, 0) is None
    assert QSV.build_main_fit_filter(asset, FitMode.BLUR, 720, 1280, 0) is None
    assert CUDA.build_main_fit_filter(asset, FitMode.BLUR, 720, 1280, 0) is None


def test_build_main_fit_filter_center_crop_scales_then_downloads_then_crops() -> None:
    asset = make_asset(width=1920, height=1080)
    prefix = QSV.build_main_fit_filter(asset, FitMode.CROP, 720, 1280, 0)
    assert prefix is not None
    assert prefix.startswith("[0:v]")
    assert prefix.endswith(",")
    # 顺序硬约束：GPU 缩放 → 回传软件帧 → 软件裁切收口。
    assert prefix.index("scale_qsv=") < prefix.index("hwdownload") < prefix.index("crop=720:1280")


def test_build_main_fit_filter_letterbox_pads_after_download() -> None:
    asset = make_asset(width=1080, height=1920)
    prefix = QSV.build_main_fit_filter(asset, FitMode.PAD, 1080, 1080, 1)
    assert prefix is not None
    assert prefix.startswith("[1:v]")
    assert "pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black" in prefix
    assert prefix.index("hwdownload") < prefix.index("pad=")


def test_build_main_fit_filter_stretch_has_no_crop_or_pad() -> None:
    asset = make_asset(width=640, height=360)
    prefix = QSV.build_main_fit_filter(asset, FitMode.STRETCH, 720, 1280, 0)
    assert prefix is not None
    assert "crop=" not in prefix and "pad=" not in prefix


def test_build_main_fit_filter_downloads_only_when_size_unchanged() -> None:
    """源尺寸已达目标 → 不发 scale 滤镜，只把设备帧回传到软件。"""
    asset = make_asset(width=1080, height=1920)
    prefix = QSV.build_main_fit_filter(asset, FitMode.STRETCH, 1080, 1920, 2)
    assert prefix == f"[2:v]{DOWNLOAD_FILTER},"


def test_download_only_prefix_creates_passthrough_label() -> None:
    prefix = D3D11.download_only_prefix(3)
    assert prefix == f"[3:v]{DOWNLOAD_FILTER}[gpu3];[gpu3]"


# ── 失败分类 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("marker", hardware_failure_markers())
def test_is_hardware_failure_matches_device_markers(marker: str) -> None:
    assert is_hardware_failure(f"[h264_qsv @ 0x1] {marker}") is True


def test_is_hardware_failure_requires_component_on_same_line() -> None:
    assert is_hardware_failure("overlay: error opening file") is False
    assert is_hardware_failure("hwdownload: invalid argument") is True
    # 组件名与错误词分处两行不应命中。
    assert is_hardware_failure("hwdownload\nsome unrelated error") is False


def test_is_hardware_failure_ignores_plain_filter_errors() -> None:
    assert is_hardware_failure("") is False
    assert is_hardware_failure("Filter delogo has an unconnected output") is False
    assert is_hardware_failure("xfade duration too large") is False


def test_is_hardware_encoder_failure_requires_family_and_marker() -> None:
    assert is_hardware_encoder_failure(NVENC, "x264: error while opening encoder") is False
    assert is_hardware_encoder_failure(NVENC, "h264_nvenc: no capable devices found") is True
    assert is_hardware_encoder_failure(NVENC, "h264_nvenc: unrelated warning") is False
    assert is_hardware_encoder_failure(QSV_ENCODER, "qsv: failed to create mfx session") is True
    assert is_hardware_encoder_failure(CPU_ENCODER, "error while opening encoder") is False
    assert is_hardware_encoder_failure(NVENC, "") is False


# ── 探测与缓存 ──────────────────────────────────────────────────────────────


def _recording_probe(results: list[bool]):
    """返回 (probe_func, calls)：按顺序消费 results，记录每次调用的参数。"""
    calls: list[list[str]] = []

    def probe(ffmpeg: Path, arguments: list[str], directory: Path) -> bool:
        calls.append(list(arguments))
        return results[len(calls) - 1] if len(calls) <= len(results) else False

    return probe, calls


def test_selector_cpu_mode_never_probes() -> None:
    probe, calls = _recording_probe([True])
    selector = HardwareProcessingSelector(probe_func=probe)
    assert selector.select(Path("ffmpeg.exe"), ProcessingMode.CPU, NVENC) is SOFTWARE_PLAN
    assert calls == []


def test_selector_caches_per_ffmpeg_and_encoder(tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    probe, calls = _recording_probe([True, True])
    selector = HardwareProcessingSelector(probe_func=probe)

    first = selector.select(ffmpeg, ProcessingMode.AUTO, NVENC)
    assert first.kind is HardwareProcessingKind.CUDA
    assert len(calls) == 2  # 样本编码 + CUDA 解码探针

    again = selector.select(ffmpeg, ProcessingMode.AUTO, NVENC)
    assert again is first
    assert len(calls) == 2  # 命中缓存，不再探测

    # 不同编码器使用独立缓存键。
    selector.select(ffmpeg, ProcessingMode.AUTO, QSV_ENCODER)
    assert len(calls) > 2


def test_selector_reset_probe_clears_cache(tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    probe, calls = _recording_probe([True, True, True, True])
    selector = HardwareProcessingSelector(probe_func=probe)

    selector.select(ffmpeg, ProcessingMode.AUTO, NVENC)
    assert len(calls) == 2
    selector.reset_probe(ffmpeg)
    selector.select(ffmpeg, ProcessingMode.AUTO, NVENC)
    assert len(calls) == 4


def test_selector_returns_software_when_sample_encode_fails(tmp_path: Path) -> None:
    probe, calls = _recording_probe([False])
    selector = HardwareProcessingSelector(probe_func=probe)
    plan = selector.select(tmp_path / "ffmpeg.exe", ProcessingMode.AUTO, NVENC)
    assert plan is SOFTWARE_PLAN
    assert len(calls) == 1  # 样本都没编出来，不再试设备


def test_selector_falls_back_to_d3d11_when_qsv_device_fails(tmp_path: Path) -> None:
    """QSV 编码器：样本成功 → QSV 探针失败 → D3D11 探针成功。"""
    probe, _ = _recording_probe([True, False, True])
    selector = HardwareProcessingSelector(probe_func=probe)
    plan = selector.select(tmp_path / "ffmpeg.exe", ProcessingMode.GPU, QSV_ENCODER)
    assert plan.kind is HardwareProcessingKind.D3D11
    assert plan.can_scale is False


def test_selector_returns_software_when_all_device_probes_fail(tmp_path: Path) -> None:
    probe, _ = _recording_probe([True, False, False])
    selector = HardwareProcessingSelector(probe_func=probe)
    plan = selector.select(tmp_path / "ffmpeg.exe", ProcessingMode.AUTO, NVENC)
    assert plan is SOFTWARE_PLAN


def test_selector_nvenc_tries_cuda_then_d3d11(tmp_path: Path) -> None:
    """NVENC 编码器：先试 CUDA（可缩放），失败再试 D3D11（仅解码）。"""
    probe, calls = _recording_probe([True, False, True])
    selector = HardwareProcessingSelector(probe_func=probe)
    plan = selector.select(tmp_path / "ffmpeg.exe", ProcessingMode.GPU, NVENC)
    assert plan.kind is HardwareProcessingKind.D3D11

    joined = [" ".join(call) for call in calls]
    assert "cuda=jxgpu:0" in joined[1]
    assert "d3d11va=jxgpu" in joined[2]


def test_selector_swallows_probe_exceptions(tmp_path: Path) -> None:
    def exploding_probe(ffmpeg: Path, arguments: list[str], directory: Path) -> bool:
        raise TimeoutError("probe timeout")

    selector = HardwareProcessingSelector(probe_func=exploding_probe)
    plan = selector.select(tmp_path / "ffmpeg.exe", ProcessingMode.AUTO, NVENC)
    assert plan is SOFTWARE_PLAN


def test_selector_rejects_unknown_mode(tmp_path: Path) -> None:
    selector = HardwareProcessingSelector(probe_func=lambda *_: True)

    class _Bogus:
        pass

    with pytest.raises(ValueError, match="未知的视频处理模式"):
        selector.select(tmp_path / "ffmpeg.exe", _Bogus(), NVENC)  # type: ignore[arg-type]


def test_probe_arguments_pin_yuv420p_sample_and_download(tmp_path: Path) -> None:
    """样本必须显式 yuv420p；设备探针必须回传后再 f null。"""
    probe, calls = _recording_probe([True, True])
    selector = HardwareProcessingSelector(probe_func=probe)
    selector.select(tmp_path / "ffmpeg.exe", ProcessingMode.GPU, NVENC)

    sample_args = calls[0]
    assert "yuv420p" in sample_args
    assert "libx264" in sample_args

    device_args = calls[1]
    assert "-init_hw_device" in device_args
    assert "-hwaccel_output_format" in device_args
    assert DOWNLOAD_FILTER in " ".join(device_args)
    assert device_args[-3:] == ["-f", "null", "-"]


def test_default_probe_timeout_matches_dotnet() -> None:
    assert DEFAULT_PROBE_TIMEOUT == 8.0
