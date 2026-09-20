"""硬件解码与 GPU 缩放：能力探测、白名单准入、设备参数与失败分类。

对齐 .NET ``HardwareVideoProcessingPlan`` / ``HardwareVideoProcessingSelector`` /
``HardwareVideoProcessingFailure``，仅针对 Windows x64。

设计要点（逐条对应 .NET 注释与 docs/gpu-performance-1.0.2.md 的实测结论）：

* 只对**主片**启用硬解：兼容的 8 位 H.264/yuv420p、无旋转、偶数尺寸且宽高在
  128–4096 之间。蒙版、贴纸、调色与合成仍在 CPU 完成。
* 循环输入（``-stream_loop -1`` / ``-loop 1``）一律禁用硬解：实测 QSV 循环
  辅助输入会重建硬件帧上下文，可能重建整个合成图甚至使 FFmpeg 崩溃。
* 探测必须**真实编码再硬解**：用 lavfi + hwupload 会把部分可用 QSV 设备误判为
  失败，因此先真编一段 H.264 样本再解码它。
* D3D11VA 只做「解码 + hwdownload」，不提供 GPU 缩放：实机 ``scale_d3d11`` 失败，
  未设为默认。
"""

from __future__ import annotations

import math
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from jingxu.domain.media import MediaAsset
from jingxu.domain.render import FitMode, ProcessingMode
from jingxu.infrastructure.encoders import CPU_ENCODER, EncoderChoice
from jingxu.infrastructure.process_control import no_window_kwargs
from jingxu.infrastructure.paths import temp_directory

# ── 常量（取值来源见 .NET HardwareVideoProcessingPlan）───────────────────────

HARDWARE_DEVICE_NAME = "jxgpu"
DOWNLOAD_FILTER = "hwdownload,format=nv12"
MIN_HARDWARE_EDGE = 128
MAX_HARDWARE_EDGE = 4096
DEFAULT_PROBE_TIMEOUT = 8.0
PROBE_SAMPLE_SIZE = "640x480"
PROBE_SCALE_WIDTH, PROBE_SCALE_HEIGHT = 320, 240


class HardwareProcessingKind(str, Enum):
    """输入侧硬件处理能力（与最终编码器选择相互独立）。"""

    SOFTWARE = "software"
    QSV = "qsv"
    CUDA = "cuda"
    D3D11 = "d3d11"


@dataclass(frozen=True, slots=True)
class HardwareProcessingPlan:
    """设备实测后的输入解码/缩放能力。"""

    kind: HardwareProcessingKind = HardwareProcessingKind.SOFTWARE
    can_scale: bool = False

    @property
    def display_name(self) -> str:
        return {
            HardwareProcessingKind.QSV: "Intel QSV",
            HardwareProcessingKind.CUDA: "NVIDIA CUDA",
            HardwareProcessingKind.D3D11: "D3D11VA",
        }.get(self.kind, "CPU")

    @property
    def description(self) -> str:
        """设置页/日志用的一行中文说明（对齐 .NET ``Description``）。"""
        if self.kind is HardwareProcessingKind.SOFTWARE:
            return "解码与缩放使用 CPU。"
        scale_text = "可用 GPU" if self.can_scale else "使用 CPU"
        return (
            f"已实测 {self.display_name} 硬件解码；缩放{scale_text}。"
            "兼容的 8 位 H.264 主片可启用；循环辅助视频、蒙版与合成使用 CPU。"
        )

    @property
    def is_software(self) -> bool:
        return self.kind is HardwareProcessingKind.SOFTWARE

    # ── 白名单 ────────────────────────────────────────────────────────────

    def supports(self, asset: MediaAsset) -> bool:
        """该素材是否满足硬解准入。

        空 ``pixel_format`` 一律拒绝：ffprobe 已经能给出 pix_fmt，空值意味着探测
        不完整，宁可走软件路径也不要冒险让 FFmpeg 在转换时失败。
        """
        if self.is_software:
            return False
        return (
            asset.video_codec.strip().lower() == "h264"
            and asset.pixel_format.strip().lower() == "yuv420p"
            and asset.rotation_degrees == 0
            and MIN_HARDWARE_EDGE <= asset.width <= MAX_HARDWARE_EDGE
            and MIN_HARDWARE_EDGE <= asset.height <= MAX_HARDWARE_EDGE
            and asset.width % 2 == 0
            and asset.height % 2 == 0
        )

    def should_use_input(
        self,
        asset: MediaAsset,
        mode: ProcessingMode,
        fit_mode: FitMode,
        width: int,
        height: int,
    ) -> bool:
        """Auto 模式只在能真正减少回传像素时才启用输入加速。"""
        if not self.supports(asset):
            return False
        if mode is ProcessingMode.GPU:
            return True
        return self.can_scale and has_downscale_opportunity(asset, fit_mode, width, height)

    # ── 设备与输入参数 ────────────────────────────────────────────────────

    @property
    def device_arguments(self) -> list[str]:
        """全局设备初始化参数（每次命令只插一次）。"""
        return {
            HardwareProcessingKind.QSV: ["-init_hw_device", "qsv=jxgpu:hw_any"],
            HardwareProcessingKind.CUDA: ["-init_hw_device", "cuda=jxgpu:0"],
            HardwareProcessingKind.D3D11: ["-init_hw_device", "d3d11va=jxgpu"],
        }.get(self.kind, [])

    @property
    def input_arguments(self) -> list[str]:
        """单个硬件输入的解码参数（紧跟在该 ``-i`` 之前）。"""
        return {
            HardwareProcessingKind.QSV: [
                "-hwaccel",
                "qsv",
                "-hwaccel_device",
                HARDWARE_DEVICE_NAME,
                "-hwaccel_output_format",
                "qsv",
            ],
            HardwareProcessingKind.CUDA: [
                "-hwaccel",
                "cuda",
                "-hwaccel_device",
                HARDWARE_DEVICE_NAME,
                "-hwaccel_output_format",
                "cuda",
            ],
            HardwareProcessingKind.D3D11: [
                "-hwaccel",
                "d3d11va",
                "-hwaccel_device",
                HARDWARE_DEVICE_NAME,
                "-hwaccel_output_format",
                "d3d11",
            ],
        }.get(self.kind, [])

    def scale_and_download(self, width: int, height: int) -> str:
        """GPU 缩放 + 显式回传软件帧。

        回传是必需的：一旦使用 ``-hwaccel_output_format``，帧留在设备上，所有
        CPU 滤镜（overlay/geq/alphamerge/ass/变体链）都会报
        ``Impossible to convert between the formats``。
        """
        if self.kind is HardwareProcessingKind.CUDA:
            return f"scale_cuda=w={width}:h={height}:format=nv12:passthrough=0,{DOWNLOAD_FILTER}"
        return f"scale_qsv=w={width}:h={height}:format=nv12,{DOWNLOAD_FILTER}"

    def build_main_fit_filter(
        self,
        asset: MediaAsset,
        fit_mode: FitMode,
        width: int,
        height: int,
        input_index: int,
    ) -> str | None:
        """返回主片适配前缀（以 ``[i:v]`` 开头、以 ``,`` 结尾）。

        ``None`` 表示无法在 GPU 上完成适配，调用方应改用 download-only 前缀
        （把设备帧原样下载回软件后再走原有软件链）。
        """
        if not self.can_scale or self.kind not in (
            HardwareProcessingKind.QSV,
            HardwareProcessingKind.CUDA,
        ):
            return None

        size = resolve_hardware_scaled_size(asset, fit_mode, width, height)
        if size is None:
            return None

        scaled_width, scaled_height = size
        if scaled_width == asset.width and scaled_height == asset.height:
            transform = DOWNLOAD_FILTER
        else:
            transform = self.scale_and_download(scaled_width, scaled_height)

        suffix = ""
        if fit_mode is FitMode.CROP:
            suffix = f",crop={width}:{height}"
        elif fit_mode is FitMode.PAD:
            suffix = f",pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        # STRETCH 无需收口；BLUR 不在此路径（resolve 返回 None）。
        return f"[{input_index}:v]{transform}{suffix},"

    def download_only_prefix(self, input_index: int) -> str:
        """把设备帧下载回软件内存，便于后续 CPU 滤镜链处理。"""
        label = f"gpu{input_index}"
        return f"[{input_index}:v]{DOWNLOAD_FILTER}[{label}];[{label}]"


SOFTWARE_PLAN = HardwareProcessingPlan(HardwareProcessingKind.SOFTWARE, False)


# ── 尺寸计算（AwayFromZero 舍入，避免 Python round 的银行家舍入）──────────────


def _round_half_away_from_zero(value: float) -> int:
    """对齐 .NET ``Math.Round(..., MidpointRounding.AwayFromZero)``。"""
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


def resolve_hardware_scaled_size(
    asset: MediaAsset,
    fit_mode: FitMode,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    """算出 GPU 缩放后的目标像素尺寸；不可用时返回 ``None``。

    CenterCrop 取外接（max），Letterbox/PAD 取内接（min），Stretch 直接用目标；
    结果必须是 128–4096 的偶数，否则交回软件路径。
    """
    if asset.width <= 0 or asset.height <= 0:
        return None
    if fit_mode not in (FitMode.CROP, FitMode.PAD, FitMode.STRETCH):
        return None

    scaled_width = width
    scaled_height = height
    if fit_mode in (FitMode.CROP, FitMode.PAD):
        from_height = _round_half_away_from_zero(height * asset.width / asset.height)
        from_width = _round_half_away_from_zero(width * asset.height / asset.width)
        if fit_mode is FitMode.CROP:
            scaled_width = max(width, from_height)
            scaled_height = max(height, from_width)
        else:
            scaled_width = min(width, from_height)
            scaled_height = min(height, from_width)

    if not (
        MIN_HARDWARE_EDGE <= scaled_width <= MAX_HARDWARE_EDGE
        and MIN_HARDWARE_EDGE <= scaled_height <= MAX_HARDWARE_EDGE
    ):
        return None
    if scaled_width % 2 != 0 or scaled_height % 2 != 0:
        return None
    return scaled_width, scaled_height


def has_downscale_opportunity(
    asset: MediaAsset,
    fit_mode: FitMode,
    width: int,
    height: int,
) -> bool:
    """只有能真正减少回传像素时才值得启用硬解 + GPU 缩放。

    这里对空 ``pixel_format`` 比 :meth:`HardwareProcessingPlan.supports` 宽松：
    它只回答"缩放是否有收益"，具体是否启用仍由 ``supports`` 决定。
    """
    if (
        asset.video_codec.strip().lower() != "h264"
        or asset.rotation_degrees != 0
        or not (MIN_HARDWARE_EDGE <= asset.width <= MAX_HARDWARE_EDGE)
        or not (MIN_HARDWARE_EDGE <= asset.height <= MAX_HARDWARE_EDGE)
    ):
        return False
    if asset.pixel_format and asset.pixel_format.strip().lower() != "yuv420p":
        return False

    size = resolve_hardware_scaled_size(asset, fit_mode, width, height)
    if size is None:
        return False
    scaled_width, scaled_height = size
    return (
        scaled_width <= asset.width
        and scaled_height <= asset.height
        and (scaled_width < asset.width or scaled_height < asset.height)
    )


# ── 失败分类（避免把普通滤镜错误误当硬件问题而白跑一遍）─────────────────────

_HARDWARE_DEVICE_MARKERS: tuple[str, ...] = (
    "device creation failed",
    "device setup failed for decoder",
    "no device available for decoder",
    "failed setup for format qsv",
    "failed setup for format cuda",
    "failed setup for format d3d11",
    "failed to create a qsv device",
    "hwaccel initialisation returned error",
    "hardware does not support image size",
    "cannot load nvcuda",
    "cuda_error",
    "reconfiguring filter graph because hwaccel changed",
    "error initializing the mfx video decoder",
    "error during qsv decoding",
    "error initializing a qsv frame pool",
    "failed to begin frame: 0x",
    "failed to execute: 0x",
    "failed to end frame: 0x",
)

_HARDWARE_COMPONENT_NAMES: tuple[str, ...] = (
    "h264_qsv",
    "scale_qsv",
    "scale_cuda",
    "hwdownload",
    "init_hw_device",
    "hwaccel_device",
)

_HARDWARE_LINE_MARKERS: tuple[str, ...] = ("error", "failed", "invalid", "not supported")

_ENCODER_FAMILY_MARKERS: dict[str, tuple[str, ...]] = {
    "nvenc": ("h264_nvenc", "nvenc", "nvcuda", "cuda"),
    "qsv": ("h264_qsv", "qsv", "mfx"),
    "amf": ("h264_amf", "amf"),
}

_ENCODER_FAILURE_MARKERS: tuple[str, ...] = (
    "no capable devices found",
    "cannot load nvcuda",
    "cannot load nvencodeapi",
    "error initializing output stream",
    "error while opening encoder",
    "openencodesession",
    "native frames context",
    "nvenc api",
    "failed to initialise",
    "failed to initialize",
    "device setup failed",
    "device lost",
    "unsupported device",
    "initializing an internal mfx session",
    "failed to create mfx session",
    "amf failed to initialise",
    "encoder initialization failed",
    "out of memory",
)


def hardware_failure_markers() -> tuple[str, ...]:
    """暴露设备级关键字清单，便于测试逐条覆盖。"""
    return _HARDWARE_DEVICE_MARKERS


def is_hardware_failure(stderr: str) -> bool:
    """stderr 是否指示**输入侧**硬解/缩放失败。

    两条判据：命中设备级关键字；或**同一行**同时出现硬件组件名与错误词。
    限定同一行是为了不把后续普通滤镜错误误判为硬件问题。
    """
    text = (stderr or "").lower()
    if not text:
        return False
    if any(marker in text for marker in _HARDWARE_DEVICE_MARKERS):
        return True

    for line in text.splitlines():
        if not any(name in line for name in _HARDWARE_COMPONENT_NAMES):
            continue
        if any(marker in line for marker in _HARDWARE_LINE_MARKERS):
            return True
    return False


def is_hardware_encoder_failure(encoder: EncoderChoice, stderr: str) -> bool:
    """stderr 是否指示该硬件**编码器**初始化失败。

    先要求命中该编码器家族关键字，再要求命中具体失败词，避免把普通编码错误
    误判成设备问题。
    """
    if encoder.name == CPU_ENCODER.name or not stderr:
        return False

    text = stderr.lower()
    family = next(
        (markers for key, markers in _ENCODER_FAMILY_MARKERS.items() if key in encoder.name.lower()),
        None,
    )
    if family is None or not any(marker in text for marker in family):
        return False
    return any(marker in text for marker in _ENCODER_FAILURE_MARKERS)


# ── 设备探测与缓存 ──────────────────────────────────────────────────────────

ProbeFunc = Callable[[Path, list[str], Path], bool]


class HardwareProcessingSelector:
    """探测某台设备实际可用的输入处理能力，并按 ffmpeg 路径 + 编码器缓存。

    缓存键包含编码器：NVENC 才试 CUDA、QSV 才试 QSV，探测结果因此不同。
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_PROBE_TIMEOUT,
        probe_func: ProbeFunc | None = None,
    ) -> None:
        self._timeout = timeout if timeout > 0 else DEFAULT_PROBE_TIMEOUT
        self._injected_probe = probe_func
        self._cache: dict[str, HardwareProcessingPlan] = {}
        self._lock = threading.RLock()

    def select(
        self,
        ffmpeg: Path,
        mode: ProcessingMode,
        encoder: EncoderChoice = CPU_ENCODER,
    ) -> HardwareProcessingPlan:
        """返回可用的处理计划；CPU 模式与不支持的平台直接返回软件计划。"""
        if mode is ProcessingMode.CPU:
            return SOFTWARE_PLAN
        if mode not in (ProcessingMode.AUTO, ProcessingMode.GPU):
            raise ValueError(f"未知的视频处理模式：{mode}")
        if sys.platform != "win32":
            # 本次迁移只覆盖 Windows x64；其他平台一律软件路径。
            return SOFTWARE_PLAN

        key = f"{_normalize_path(ffmpeg)}|{encoder.name}"
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        plan = self._probe(ffmpeg, encoder)
        with self._lock:
            self._cache[key] = plan
        return plan

    def reset_probe(self, ffmpeg: Path | None = None) -> None:
        """清空探测缓存（设置页「重新检测」）。

        传入 ``None`` 清空全部，否则只清该 ffmpeg 路径下的条目。
        """
        with self._lock:
            if ffmpeg is None:
                self._cache.clear()
                return
            prefix = _normalize_path(ffmpeg) + "|"
            for key in [key for key in self._cache if key.startswith(prefix)]:
                self._cache.pop(key, None)

    def _probe(self, ffmpeg: Path, encoder: EncoderChoice) -> HardwareProcessingPlan:
        """真实编码一段样本，再逐个候选试硬解；任一环节失败都降级为软件。"""
        directory = temp_directory() / f"jingxu-py-gpu-probe-{uuid.uuid4().hex}"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            sample = directory / "sample.mp4"
            if not self._probe_once(ffmpeg, _sample_encode_arguments(sample), directory):
                return SOFTWARE_PLAN

            for candidate in _candidates_for(encoder):
                if self._probe_once(
                    ffmpeg,
                    _device_probe_arguments(candidate, sample),
                    directory,
                ):
                    return candidate
            return SOFTWARE_PLAN
        except Exception:  # noqa: BLE001 - 探测失败只降低能力，绝不使任务失败
            return SOFTWARE_PLAN
        finally:
            _remove_directory(directory)

    def _probe_once(self, ffmpeg: Path, arguments: list[str], directory: Path) -> bool:
        """执行一次探测：注入的探测函数优先，否则用本实例的超时。"""
        if self._injected_probe is not None:
            try:
                return bool(self._injected_probe(ffmpeg, arguments, directory))
            except Exception:  # noqa: BLE001 - 探测异常一律视为不可用
                return False
        return _run_probe(ffmpeg, arguments, directory, timeout=self._timeout)


def _candidates_for(encoder: EncoderChoice) -> list[HardwareProcessingPlan]:
    """候选顺序与 .NET 一致：编码器决定首选，其后总是尝试 D3D11（仅解码）。"""
    candidates: list[HardwareProcessingPlan] = []
    if "nvenc" in encoder.name:
        candidates.append(HardwareProcessingPlan(HardwareProcessingKind.CUDA, True))
    elif "qsv" in encoder.name:
        candidates.append(HardwareProcessingPlan(HardwareProcessingKind.QSV, True))
    candidates.append(HardwareProcessingPlan(HardwareProcessingKind.D3D11, False))
    return candidates


def _sample_encode_arguments(sample: Path) -> list[str]:
    """先真编一段 H.264 样本：lavfi + hwupload 会把可用 QSV 设备误判为失败。"""
    return [
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={PROBE_SAMPLE_SIZE}:r=25:d=0.04",
        "-frames:v",
        "1",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(sample),
    ]


def _device_probe_arguments(plan: HardwareProcessingPlan, sample: Path) -> list[str]:
    arguments = ["-hide_banner", "-loglevel", "error"]
    arguments.extend(plan.device_arguments)
    arguments.extend(plan.input_arguments)
    arguments.extend(["-threads", "2", "-i", str(sample), "-vf"])
    if plan.can_scale:
        arguments.append(plan.scale_and_download(PROBE_SCALE_WIDTH, PROBE_SCALE_HEIGHT))
    else:
        arguments.append(DOWNLOAD_FILTER)
    arguments.extend(["-frames:v", "1", "-an", "-f", "null", "-"])
    return arguments


def _run_probe(ffmpeg: Path, arguments: list[str], directory: Path, *, timeout: float) -> bool:
    """执行一次探测；退出码 0 才算通过，超时与异常都视为不可用。"""
    command = [str(ffmpeg), *arguments]
    try:
        completed = subprocess.run(
            command,
            **no_window_kwargs(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            cwd=str(directory),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _normalize_path(ffmpeg: Path) -> str:
    try:
        return str(Path(ffmpeg).resolve()).casefold()
    except OSError:
        return str(ffmpeg).casefold()


def _remove_directory(path: Path) -> None:
    try:
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    child.unlink(missing_ok=True)
            for child in sorted(path.rglob("*"), key=lambda p: len(str(p)), reverse=True):
                if child.is_dir():
                    child.rmdir()
            path.rmdir()
    except OSError:
        pass


_SELECTOR_CACHE: dict[str, HardwareProcessingSelector] = {}
_SELECTOR_LOCK = threading.RLock()


def default_processing_selector(ffmpeg: Path) -> HardwareProcessingSelector:
    """按 ffmpeg 路径缓存的选择器（进程内复用探测结果）。"""
    key = _normalize_path(ffmpeg)
    with _SELECTOR_LOCK:
        selector = _SELECTOR_CACHE.get(key)
        if selector is None:
            selector = HardwareProcessingSelector()
            _SELECTOR_CACHE[key] = selector
        return selector
