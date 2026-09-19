"""硬件编码器探测与质量参数映射（自动 / CPU / GPU）。"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jingxu.domain.render import ProcessingMode


@dataclass(frozen=True, slots=True)
class EncoderChoice:
    """一个可用编码器及其质量参数模板。"""

    name: str
    label: str
    hardware: bool

    def quality_args(self, crf: int, preset: str) -> list[str]:
        quality = max(0, min(crf, 51))
        if self.name == "libx264":
            return ["-preset", preset, "-threads", "0", "-crf", str(quality)]
        if self.name == "h264_nvenc":
            speed = {
                "ultrafast": "p2",
                "superfast": "p4",
                "veryfast": "p4",
                "faster": "p5",
                "fast": "p6",
                "medium": "p5",
                "slow": "p6",
            }.get(preset, "p5")
            return [
                "-preset",
                speed,
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                str(quality),
                "-b:v",
                "0",
            ]
        if self.name == "h264_qsv":
            speed = {
                "ultrafast": "veryfast",
                "veryfast": "veryfast",
                "faster": "faster",
                "fast": "faster",
                "medium": "medium",
                "slow": "slow",
            }.get(preset, "medium")
            return ["-preset", speed, "-global_quality", str(quality)]
        if self.name == "h264_amf":
            quality_mode = {
                "ultrafast": "speed",
                "veryfast": "speed",
                "faster": "balanced",
                "fast": "balanced",
                "medium": "balanced",
                "slow": "quality",
            }.get(preset, "balanced")
            return [
                "-quality",
                quality_mode,
                "-rc",
                "cqp",
                "-qp_i",
                str(quality),
                "-qp_p",
                str(quality),
                "-qp_b",
                str(quality),
            ]
        if self.name == "h264_mf":
            return ["-rate_control", "quality", "-quality", "90" if quality <= 23 else "70"]
        if self.name == "h264_videotoolbox":
            return ["-q:v", str(max(1, 100 - quality * 2)), "-b:v", "0"]
        return ["-preset", preset, "-crf", str(quality)]


CPU_ENCODER = EncoderChoice("libx264", "CPU (libx264)", False)

CANDIDATES: tuple[EncoderChoice, ...] = (
    EncoderChoice("h264_nvenc", "NVIDIA NVENC", True),
    EncoderChoice("h264_qsv", "Intel Quick Sync", True),
    EncoderChoice("h264_amf", "AMD AMF", True),
    EncoderChoice("h264_videotoolbox", "Apple VideoToolbox", True),
    EncoderChoice("h264_mf", "MediaFoundation", True),
)

AVAILABLE_CANDIDATES_HINT = "、".join(candidate.name for candidate in CANDIDATES)

ProbeFunc = Callable[[EncoderChoice], bool]

_REGISTRY_CACHE: dict[str, "EncoderRegistry"] = {}


def default_registry(ffmpeg: Path) -> "EncoderRegistry":
    """按 ffmpeg 路径缓存的全局注册表（探针结果进程内复用）。"""
    key = str(Path(ffmpeg).resolve())
    registry = _REGISTRY_CACHE.get(key)
    if registry is None:
        registry = EncoderRegistry(ffmpeg)
        _REGISTRY_CACHE[key] = registry
    return registry


class EncoderRegistry:
    """探测并缓存可用的硬件编码器；探测失败即视为不可用。"""

    def __init__(self, ffmpeg: Path, *, probe_func: ProbeFunc | None = None, timeout: float = 30.0) -> None:
        self._ffmpeg = Path(ffmpeg)
        self._probe_func = probe_func or self._run_probe
        self._timeout = timeout
        self._probed: dict[str, bool] = {}
        self._resolved: dict[ProcessingMode, EncoderChoice] = {}
        self._notes: dict[ProcessingMode, str] = {}

    # ────────────────────────────── 对外 ──────────────────────────────

    def resolve(self, mode: ProcessingMode) -> EncoderChoice:
        if mode in self._resolved:
            return self._resolved[mode]

        choice: EncoderChoice
        if mode is ProcessingMode.CPU:
            choice = CPU_ENCODER
            self._notes[mode] = "已按设置使用 CPU 编码。"
        else:
            hardware = self._first_usable()
            if hardware is not None:
                choice = hardware
                self._notes[mode] = f"已选用 {hardware.label} 硬件编码。"
            else:
                choice = CPU_ENCODER
                self._notes[mode] = "未检测到可用硬件编码器，已回退 CPU 编码。"

        self._resolved[mode] = choice
        return choice

    def note(self, mode: ProcessingMode) -> str:
        return self._notes.get(mode, "")

    def available_names(self) -> list[str]:
        return [candidate.name for candidate in CANDIDATES if self.is_usable(candidate)]

    def is_usable(self, candidate: EncoderChoice) -> bool:
        if candidate.name not in self._probed:
            self._probed[candidate.name] = bool(self._probe_func(candidate))
        return self._probed[candidate.name]

    # ────────────────────────────── 内部 ──────────────────────────────

    def _first_usable(self) -> EncoderChoice | None:
        for candidate in CANDIDATES:
            if self.is_usable(candidate):
                return candidate
        return None

    def _run_probe(self, candidate: EncoderChoice) -> bool:
        command = [
            str(self._ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=256x144:rate=30:duration=0.4",
            "-c:v",
            candidate.name,
            *candidate.quality_args(28, "ultrafast"),
            "-f",
            "null",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0
