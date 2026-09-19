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
