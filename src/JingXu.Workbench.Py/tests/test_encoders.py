"""硬件编码器与质量参数测试。"""

from __future__ import annotations

from pathlib import Path

from jingxu.domain.render import ProcessingMode
from jingxu.infrastructure.encoders import CPU_ENCODER, EncoderChoice, EncoderRegistry


def _registry(usable: set[str]) -> EncoderRegistry:
    return EncoderRegistry(Path("ffmpeg"), probe_func=lambda candidate: candidate.name in usable)


def test_nvenc_quality_args_use_cq_and_preset() -> None:
    choice = EncoderChoice("h264_nvenc", "NVIDIA NVENC", True)
    args = choice.quality_args(23, "veryfast")
    assert "-cq" in args and "23" in args
    assert args[args.index("-preset") + 1] == "p4"
    assert args[args.index("-tune") + 1] == "hq"
    assert "-rc" in args and "vbr" in args


def test_qsv_and_amf_and_videotoolbox_args() -> None:
    qsv = EncoderChoice("h264_qsv", "QSV", True).quality_args(20, "veryfast")
    assert "-global_quality" in qsv and "20" in qsv
    assert qsv[qsv.index("-preset") + 1] == "veryfast"
    amf = EncoderChoice("h264_amf", "AMF", True).quality_args(26, "veryfast")
    assert amf[0] == "-quality" and amf[1] == "speed"
    assert "-rc" in amf and "cqp" in amf and amf.count("26") == 3
    vt = EncoderChoice("h264_videotoolbox", "VT", True).quality_args(23, "veryfast")
    assert vt[0] == "-q:v" and 1 <= int(vt[1]) <= 100


def test_cpu_encoder_uses_crf_preset() -> None:
    args = CPU_ENCODER.quality_args(21, "fast")
    assert args == ["-preset", "fast", "-threads", "0", "-crf", "21"]


def test_auto_prefers_first_usable_hardware() -> None:
    registry = _registry({"h264_qsv"})
    choice = registry.resolve(ProcessingMode.AUTO)
    assert choice.name == "h264_qsv"
    assert "Intel" in registry.note(ProcessingMode.AUTO)


def test_auto_falls_back_to_cpu() -> None:
    registry = _registry(set())
    choice = registry.resolve(ProcessingMode.AUTO)
    assert choice.name == "libx264"
    assert "回退" in registry.note(ProcessingMode.AUTO)


def test_cpu_mode_never_probes_hardware() -> None:
    calls: list[str] = []

    def probe(candidate: EncoderChoice) -> bool:
        calls.append(candidate.name)
        return True

    registry = EncoderRegistry(Path("ffmpeg"), probe_func=probe)
    choice = registry.resolve(ProcessingMode.CPU)
    assert choice.name == "libx264"
    assert calls == []


def test_gpu_mode_falls_back_when_no_hardware() -> None:
    registry = _registry(set())
    choice = registry.resolve(ProcessingMode.GPU)
    assert choice.name == "libx264"
    assert "回退" in registry.note(ProcessingMode.GPU)
