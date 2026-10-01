"""渲染三级回退：硬解失败 → 软件解码保留硬编 → CPU 兜底。

用假执行器直接驱动回退决策，不依赖真实 FFmpeg 或 GPU。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jingxu.infrastructure.encoders import CPU_ENCODER, EncoderChoice
from jingxu.infrastructure.ffmpeg_runner import RenderCancelled, RenderError, _retry_after_failure
from jingxu.infrastructure.video_processing import HardwareProcessingKind, HardwareProcessingPlan

QSV = HardwareProcessingPlan(HardwareProcessingKind.QSV, True)
SOFTWARE = HardwareProcessingPlan(HardwareProcessingKind.SOFTWARE, False)
PURE_SOFTWARE = HardwareProcessingPlan()

NVENC = EncoderChoice("h264_nvenc", "NVIDIA NVENC", True)

DEVICE_FAILURE = "[h264_qsv @ 0x1] Device creation failed: -1313558101."
ENCODER_FAILURE = "[h264_nvenc @ 0x1] Cannot load nvcuda.dll: no capable devices found"
PLAIN_FILTER_FAILURE = "Filter delogo has an unconnected output"


class _RecordingSelector:
    """记录 remember_hardware_failure 调用。"""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def remember_hardware_failure(self, encoder_name: str) -> None:
        self.failures.append(encoder_name)


def _run_retry(
    error: RenderError,
    *,
    plan=QSV,
    encoder=CPU_ENCODER,
    outcomes=None,
    selector=None,
):
    """用给定结果序列驱动一次回退，返回 (返回值, 调用记录)。"""
    calls: list[tuple[str, object]] = []
    queue = list(outcomes or [])

    def execute(retry_encoder, retry_plan):
        calls.append((retry_encoder.name, retry_plan))
        result = queue.pop(0) if queue else None
        if isinstance(result, BaseException):
            raise result
        if result is None:
            raise AssertionError("假执行器结果不足")
        return Path(result)

    return (
        _retry_after_failure(
            error=error,
            plan=plan,
            encoder=encoder,
            selector=selector or _RecordingSelector(),
            request=None,  # 未使用
            execute=execute,
            clear_partial=lambda: None,
        ),
        calls,
    )


def test_hardware_failure_retries_with_software_decode_keeping_encoder() -> None:
    """L1：输入设备失败 → 去掉硬解重编，编码器不变。"""
    selector = _RecordingSelector()
    output, calls = _run_retry(
        RenderError("boom", stderr_text=DEVICE_FAILURE),
        plan=QSV,
        encoder=NVENC,
        outcomes=[Path("out.mp4")],
        selector=selector,
    )

    assert output == Path("out.mp4")
    assert calls == [("h264_nvenc", None)]  # 保留编码器，处理计划回软件
    assert selector.failures == []  # 未归咎编码器


def test_encoder_failure_also_tries_software_decode_first() -> None:
    """L1 先试「软件解码 + 原编码器」，仍失败才进 L2（不把设备问题直接归咎编码器）。"""
    selector = _RecordingSelector()
    output, calls = _run_retry(
        RenderError("boom", stderr_text=ENCODER_FAILURE),
        plan=QSV,
        encoder=NVENC,
        outcomes=[RenderError("still bad", stderr_text=ENCODER_FAILURE), Path("out.mp4")],
        selector=selector,
    )

    assert output == Path("out.mp4")
    assert calls == [("h264_nvenc", None), ("libx264", None)]
    assert selector.failures == ["h264_nvenc"]


def test_encoder_failure_retries_with_cpu_and_remembers_bad_encoder() -> None:
    """L1 直接失败（无硬解计划）→ L2 用 CPU 兜底并记住坏编码器。"""
    selector = _RecordingSelector()
    output, calls = _run_retry(
        RenderError("boom", stderr_text=ENCODER_FAILURE),
        plan=PURE_SOFTWARE,
        encoder=NVENC,
        outcomes=[Path("out.mp4")],
        selector=selector,
    )

    assert output == Path("out.mp4")
    assert calls == [("libx264", None)]
    assert selector.failures == ["h264_nvenc"]


def test_plain_filter_error_does_not_retry() -> None:
    """普通滤镜错误不触发任何重试，避免白跑一遍。"""
    selector = _RecordingSelector()
    with pytest.raises(RenderError, match="boom"):
        _run_retry(
            RenderError("boom", stderr_text=PLAIN_FILTER_FAILURE),
            plan=QSV,
            encoder=NVENC,
            outcomes=[],
            selector=selector,
        )
    assert selector.failures == []


def test_software_plan_never_retries_hardware_path() -> None:
    """计划本就是软件时，设备级错误也不该走 L1（没有硬解可退）。"""
    selector = _RecordingSelector()
    with pytest.raises(RenderError):
        _run_retry(
            RenderError("boom", stderr_text=DEVICE_FAILURE),
            plan=SOFTWARE,
            encoder=CPU_ENCODER,
            outcomes=[],
            selector=selector,
        )
    assert selector.failures == []


def test_all_tiers_failed_raises_last_error() -> None:
    """L1 与 L2 都失败时抛出最后一次错误（供上层归档）。"""
    selector = _RecordingSelector()
    with pytest.raises(RenderError, match="cpu also failed"):
        _run_retry(
            RenderError("boom", stderr_text=ENCODER_FAILURE),
            plan=QSV,
            encoder=NVENC,
            outcomes=[
                RenderError("decode retry failed", stderr_text=ENCODER_FAILURE),
                RenderError("cpu also failed", stderr_text="cpu exploded"),
            ],
            selector=selector,
        )
    assert selector.failures == ["h264_nvenc"]


def test_cancellation_is_never_swallowed_by_retry() -> None:
    """取消必须原样冒泡，不得被回退吞掉。"""
    with pytest.raises(RenderCancelled):
        _run_retry(
            RenderError("boom", stderr_text=DEVICE_FAILURE),
            plan=QSV,
            encoder=NVENC,
            outcomes=[RenderCancelled("用户取消")],
        )


def test_cpu_encoder_never_triggers_l2() -> None:
    """本来就是 CPU 编码时不应再"回退到 CPU"。"""
    selector = _RecordingSelector()
    with pytest.raises(RenderError):
        _run_retry(
            RenderError("boom", stderr_text="h264_nvenc no capable devices found"),
            plan=PURE_SOFTWARE,
            encoder=CPU_ENCODER,
            outcomes=[],
            selector=selector,
        )
    assert selector.failures == []


# ── 命令行长度预算 ──────────────────────────────────────────────────────────


def test_estimate_command_line_length_counts_separators() -> None:
    from jingxu.infrastructure.ffmpeg_runner import estimate_command_line_length

    # 4 个参数 + 分隔空格 + 结尾 NUL
    assert estimate_command_line_length(["a", "b", "c", "d"]) == 4 * 1 + 4 + 1


def test_estimate_command_line_length_penalises_spaces_and_quotes() -> None:
    from jingxu.infrastructure.ffmpeg_runner import estimate_command_line_length

    plain = estimate_command_line_length(["a.mp4"])
    spaced = estimate_command_line_length(["a b.mp4"])
    quoted = estimate_command_line_length(['a"b.mp4'])
    assert spaced > plain
    assert quoted > plain


def test_ensure_command_within_budget_accepts_short_command(tmp_path: Path) -> None:
    from jingxu.infrastructure.ffmpeg_runner import _ensure_command_within_budget

    _ensure_command_within_budget(["ffmpeg", "-i", "a.mp4"], tmp_path)


def test_ensure_command_within_budget_rejects_overlong_command(tmp_path: Path) -> None:
    from jingxu.infrastructure.ffmpeg_runner import _ensure_command_within_budget

    huge = "x" * 40000
    with pytest.raises(RenderError, match="命令过长"):
        _ensure_command_within_budget(["ffmpeg", "-i", huge], tmp_path)


def test_ensure_command_within_budget_message_is_actionable(tmp_path: Path) -> None:
    """错误信息必须给出可操作建议，并说明滤镜图已外置。"""
    from jingxu.infrastructure.ffmpeg_runner import _ensure_command_within_budget

    with pytest.raises(RenderError) as excinfo:
        _ensure_command_within_budget(["ffmpeg", "y" * 40000], tmp_path)
    message = str(excinfo.value)
    assert "减少单次任务的素材数量" in message
    assert "concat.filter" in message


def test_many_clips_with_long_paths_stay_within_budget() -> None:
    """实测规模确认：即使 80 个深路径素材也不应误触发预算守卫。

    这也是「staging 短路径别名」在 Python 侧并非必需的量化依据：
    滤镜图已外置到 sidecar，命令行只承载参数本身。
    """
    from conftest import make_asset

    from jingxu.domain.composition import CompositionPlan, OrderMode
    from jingxu.domain.render import FitMode, ProcessingMode, RenderRequest, RenderSettings
    from jingxu.infrastructure.ffmpeg_runner import (
        MAX_COMMAND_LINE_LENGTH,
        build_render_command,
        estimate_command_line_length,
    )
    from jingxu.infrastructure.filter_graph import build_filter_graph

    depth = "层" * 10
    assets = tuple(
        make_asset(f"{depth}/{depth}/素材_{index:03d}_{depth}.mp4", width=1920, height=1080)
        for index in range(1, 81)
    )
    plan = CompositionPlan(assets=assets, mode=OrderMode.SEQUENTIAL, seed=1)
    settings = RenderSettings(
        width=1080, height=1920, fps=30, fit_mode=FitMode.PAD, processing=ProcessingMode.CPU
    )
    request = RenderRequest(name="t", plan=plan, settings=settings, output_path=Path("out.mp4"))
    graph = build_filter_graph(plan, settings)
    command = build_render_command(
        Path("C:/very/long/runtime/path/ffmpeg.exe"),
        request,
        graph,
        Path("C:/tmp/concat.filter"),
        Path("C:/tmp/out.mp4"),
    )

    assert estimate_command_line_length(command) < MAX_COMMAND_LINE_LENGTH
