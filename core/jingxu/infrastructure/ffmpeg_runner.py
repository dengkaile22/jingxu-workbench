"""FFmpeg 渲染执行器：命令编译、进度解析、取消与失败清理。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from jingxu.application.stream_copy import stream_copy_eligible
from jingxu.domain.media import MediaAsset
from jingxu.domain.render import ProcessingMode, RenderRequest
from jingxu.infrastructure.cover import CoverError, generate_cover
from jingxu.infrastructure.encoders import CPU_ENCODER, EncoderChoice, default_registry
from jingxu.infrastructure.feather import FeatherError, feather_gradient
from jingxu.infrastructure.filter_graph import (
    ExtraInput,
    FilterGraph,
    build_filter_graph,
    select_hardware_inputs,
)
from jingxu.infrastructure.process_control import ProcessTreeGuard
from jingxu.infrastructure.subtitles import write_ass
from jingxu.infrastructure.video_processing import (
    SOFTWARE_PLAN,
    HardwareProcessingPlan,
    default_processing_selector,
    is_hardware_encoder_failure,
    is_hardware_failure,
)

PART_SUFFIX = ".part.mp4"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_INPUT_THREADS = "2"


class RenderError(RuntimeError):
    """渲染失败。"""

    def __init__(self, message: str, *, stderr_text: str = "") -> None:
        super().__init__(message)
        self.stderr_text = stderr_text


class RenderCancelled(RenderError):
    """渲染被取消。"""


@dataclass(frozen=True, slots=True)
class RenderProgress:
    percent: float
    rendered_seconds: float
    total_seconds: float
    speed: str = ""


ProgressCallback = Callable[[RenderProgress], None]


def build_render_command(
    ffmpeg_path: Path,
    request: RenderRequest,
    graph: FilterGraph,
    filter_script_path: Path,
    output_path: Path,
    *,
    encoder: EncoderChoice = CPU_ENCODER,
    processing_plan: HardwareProcessingPlan | None = None,
    hardware_inputs: frozenset[int] | None = None,
) -> list[str]:
    """编译 ffmpeg 命令行（独立参数列表，不做 shell 拼接）。

    ``processing_plan`` 为 ``None`` 或软件计划时行为与迁移前一致。硬件计划生效时：

    * 设备初始化参数（``-init_hw_device``）只在命令开头插入一次；
    * 逐个硬件输入在其 ``-threads``/``-i`` 之前插入 ``-hwaccel`` 三件套；
    * **循环输入（辅助素材/图层/贴纸/梯度/BGM）永不插硬解** —— 实测 QSV 循环
      输入会重建硬件帧上下文并可能使 FFmpeg 崩溃。
    """
    selected = (
        select_hardware_inputs(request.plan, request.settings, processing_plan)
        if hardware_inputs is None
        else frozenset(hardware_inputs)
    )
    plan = processing_plan if processing_plan is not None and not processing_plan.is_software else None
    if plan is None:
        selected = frozenset()

    command = [str(ffmpeg_path), "-hide_banner", "-nostdin", "-y"]
    if selected and plan is not None:
        command.extend(plan.device_arguments)

    for index, asset in enumerate(request.plan.assets):
        if index in selected and plan is not None:
            command.extend(plan.input_arguments)
        command.extend(["-threads", VIDEO_INPUT_THREADS, "-i", str(asset.path)])

    for extra in graph.extra_inputs:
        _append_input(command, extra)

    settings = request.settings
    command.extend(
        [
            "-filter_complex_script",
            str(filter_script_path),
            "-map",
            f"[{graph.video_label}]",
        ]
    )
    if graph.has_audio:
        command.extend(["-map", f"[{graph.audio_label}]", "-c:a", "aac", "-b:a", f"{settings.audio_bitrate_k}k"])

    command.extend(
        [
            "-c:v",
            encoder.name,
            *encoder.quality_args(settings.crf, settings.preset),
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if settings.clear_metadata:
        command.extend(["-map_metadata", "-1"])
    command.extend(
        [
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]
    )
    return command


def _escape_concat_path(path: Path) -> str:
    """转义 concat 列表路径：反斜杠统一为斜杠，单引号按 shell 规则转义。"""
    return str(path).replace("\\", "/").replace("'", "'\\''")


def write_concat_list(path: Path, assets: Sequence[MediaAsset]) -> Path:
    """写出 ffmpeg concat 列表文件并返回其路径。"""
    lines = [f"file '{_escape_concat_path(asset.path)}'" for asset in assets]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_stream_copy_command(
    ffmpeg_path: Path,
    request: RenderRequest,
    concat_list_path: Path,
    output_path: Path,
) -> list[str]:
    """编译 concat 无损直拷命令（不解码、不合成）。"""
    return [
        str(ffmpeg_path),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]


def _append_input(command: list[str], extra: ExtraInput) -> None:
    """按输入类型选择循环方式：图片用 ``-loop 1``，视频用 ``-stream_loop -1``。"""
    is_image = extra.path.suffix.lower() in IMAGE_SUFFIXES
    if extra.loop:
        if is_image:
            command.extend(["-loop", "1"])
        else:
            command.extend(["-stream_loop", "-1"])
    if not is_image:
        command.extend(["-threads", VIDEO_INPUT_THREADS])
    command.extend(["-i", str(extra.path)])


def _hidden_process_kwargs() -> dict:
    """隐藏控制台窗口（Windows）；供进程树守卫复用。"""
    return ProcessTreeGuard().spawn_kwargs()


def _parse_time_value(text: str) -> float:
    hours, minutes, seconds = text.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def run_render(
    ffmpeg_path: Path,
    request: RenderRequest,
    *,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    temp_dir: Path | None = None,
    encoder: EncoderChoice | None = None,
    job_id: str | None = None,
    processing_plan: HardwareProcessingPlan | None = None,
    processing_selector=None,
) -> Path:
    """执行一次渲染，成功返回成片路径；失败/取消抛出异常并清理半成品。

    三级回退（对齐 .NET ``FfmpegRenderExecutor``）：

    L1 输入硬解/缩放失败 → 去掉硬解重编，**保留原编码器**；
    L2 编码器仍失败 → ``libx264`` 兜底，并记住坏编码器；
    L3 仍失败 → 归档诊断并抛出。

    普通滤镜错误不触发任何重试（避免白跑一遍）。重试会**重新生成滤镜脚本**，
    否则脚本里残留的 ``scale_qsv``/``hwdownload`` 会让第二遍必然同样失败。
    取消不会被重试吞掉。
    """
    script_directory = Path(tempfile.mkdtemp(prefix="jingxu-py-", dir=temp_dir))
    request.output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = request.output_path.with_name(request.output_path.name + PART_SUFFIX)
    total_seconds = max(request.total_duration, 0.001)
    filter_script_text = ""

    try:
        _ensure_render_space(request)

        # 直拷路径不探测编码器与 GPU 能力（对齐 .NET：isStreamCopy 时不探针）。
        if request.settings.stream_copy and stream_copy_eligible(request):
            concat_path = write_concat_list(script_directory / "concat.txt", request.plan.assets)
            command = build_stream_copy_command(ffmpeg_path, request, concat_path, part_path)
            return _execute(ffmpeg_path, command, request, part_path, total_seconds, on_progress, cancel_event)

        selected_encoder, plan, selector = _resolve_processing(
            ffmpeg_path, request, encoder, processing_plan, processing_selector
        )

        command, filter_path = _build_transcode_command(
            ffmpeg_path,
            request,
            script_directory,
            part_path,
            temp_dir,
            selected_encoder,
            processing_plan=plan,
        )
        filter_script_text = _read_filter_script(filter_path)
        _ensure_command_within_budget(command, script_directory)

        try:
            return _execute(
                ffmpeg_path, command, request, part_path, total_seconds, on_progress, cancel_event
            )
        except RenderCancelled:
            raise
        except RenderError as error:
            try:
                return _retry_after_failure(
                    error=error,
                    plan=plan,
                    encoder=selected_encoder,
                    selector=selector,
                    request=request,
                    execute=lambda retry_encoder, retry_plan: _execute(
                        ffmpeg_path,
                        _compile_command(
                            ffmpeg_path,
                            request,
                            script_directory,
                            part_path,
                            temp_dir,
                            retry_encoder,
                            retry_plan,
                        ),
                        request,
                        part_path,
                        total_seconds,
                        on_progress,
                        cancel_event,
                    ),
                    clear_partial=lambda: _clear_partial(part_path),
                )
            except RenderError as final_error:
                _archive_failure(request, job_id, final_error, filter_script_text)
                raise
    except BaseException:
        _clear_partial(part_path)
        raise
    finally:
        shutil.rmtree(script_directory, ignore_errors=True)


def _resolve_processing(
    ffmpeg_path: Path,
    request: RenderRequest,
    encoder: EncoderChoice | None,
    processing_plan: HardwareProcessingPlan | None,
    processing_selector,
) -> tuple[EncoderChoice, HardwareProcessingPlan, object]:
    """解析编码器与输入处理计划（仅转码路径需要）。

    显式传入 ``processing_plan`` 时不再探测（也不取默认选择器）；
    ``processing_selector`` 默认按 ffmpeg 路径取进程内缓存的选择器。
    """
    selected_encoder = encoder or default_registry(ffmpeg_path).resolve(request.settings.processing)
    if processing_plan is not None:
        return selected_encoder, processing_plan, processing_selector
    selector = processing_selector or default_processing_selector(ffmpeg_path)
    plan = selector.select(ffmpeg_path, request.settings.processing, selected_encoder)
    return selected_encoder, plan, selector


# Windows CreateProcess 命令行上限为 32767（含结尾 NUL）；留出保守余量。
# 参考 .NET ``RenderPreflight.MaxCommandLineLength = 30000``。
WINDOWS_COMMAND_LINE_LIMIT = 32767
MAX_COMMAND_LINE_LENGTH = 30000


def estimate_command_line_length(command: Sequence[str]) -> int:
    """估算 Windows 命令行长度（逐项按 argv 引号规则求和）。

    滤镜图已外置为 sidecar 脚本，因此这里只统计参数本身；含空格/引号的参数
    会被引号包裹，末尾再加结尾 NUL 与分隔空格。
    """
    total = 0
    for token in command:
        total += 1  # 参数之间的空格分隔
        if not token or any(char in token for char in ' \t"'):
            # 引号包裹 + 内部引号/反斜杠转义的最坏情况估算
            total += token.count('\\') + token.count('"') + 2
        total += len(token)
    return total + 1


def _ensure_command_within_budget(command: Sequence[str], script_directory: Path) -> None:
    """命令过长时提前失败并给出中文建议，而不是让 CreateProcess 抛原始错误。

    真正会撞上限的是「大量素材 + 很深的绝对路径」；滤镜图本身已经写入
    ``concat.filter``，不占命令行。
    """
    limit = WINDOWS_COMMAND_LINE_LIMIT if sys.platform == "win32" else MAX_COMMAND_LINE_LENGTH
    estimated = estimate_command_line_length(command)
    if estimated <= limit:
        return
    raise RenderError(
        f"FFmpeg 命令过长（约 {estimated} 字符，上限 {limit}）。"
        "请减少单次任务的素材数量，或把素材移动到层级更浅的目录后重试；"
        f"滤镜图已外置为脚本（{script_directory.name}/concat.filter），无需再精简参数。"
    )


def _read_filter_script(filter_path: Path) -> str:
    """读取刚写出的滤镜脚本，供失败归档使用。"""
    """读取刚写出的滤镜脚本，供失败归档使用。"""
    try:
        if filter_path.is_file():
            return filter_path.read_text(encoding="utf-8")
    except OSError:
        pass
    return ""


def _compile_command(
    ffmpeg_path: Path,
    request: RenderRequest,
    script_directory: Path,
    part_path: Path,
    temp_dir: Path | None,
    encoder: EncoderChoice,
    processing_plan: HardwareProcessingPlan | None,
) -> list[str]:
    """编译命令（含重写滤镜脚本），供首轮与各级回退复用。"""
    command, _ = _build_transcode_command(
        ffmpeg_path,
        request,
        script_directory,
        part_path,
        temp_dir,
        encoder,
        processing_plan=processing_plan,
    )
    return command


def _retry_after_failure(
    *,
    error: RenderError,
    plan: HardwareProcessingPlan,
    encoder: EncoderChoice,
    selector,
    request: RenderRequest,
    execute,
    clear_partial,
) -> Path:
    """L1/L2 回退；任一级成功即返回成片路径，全部失败抛出最后一次错误。

    L1 输入硬解/缩放失败 → 去掉硬解重编（**保留原编码器**）；
    L2 编码器仍失败 → ``libx264`` 兜底，并记住坏编码器（本会话不再首选它）。

    普通滤镜错误（既非设备失败也非编码器失败）不触发任何重试，直接抛出。
    """
    last_error = error
    software_plan = None  # None 等价于软件路径（build_render_command 视为无硬解）

    # L1：输入侧失败先归因于解码/缩放，不直接怪编码器。
    if not plan.is_software and (
        is_hardware_failure(error.stderr_text)
        or is_hardware_encoder_failure(encoder, error.stderr_text)
    ):
        clear_partial()
        try:
            return execute(encoder, software_plan)
        except RenderCancelled:
            raise
        except RenderError as decode_error:
            last_error = decode_error

    # L2：编码器仍失败 → CPU 兜底。
    if encoder.name != CPU_ENCODER.name and is_hardware_encoder_failure(
        encoder, last_error.stderr_text
    ):
        selector.remember_hardware_failure(encoder.name)
        clear_partial()
        try:
            return execute(CPU_ENCODER, software_plan)
        except RenderCancelled:
            raise
        except RenderError as cpu_error:
            last_error = cpu_error

    raise last_error


def _ensure_render_space(request: RenderRequest) -> None:
    """按成片时长估算输出体积；空间不足时先回收缓存再复查一次。"""
    from jingxu.infrastructure.disk_space import DiskSpaceError, estimate_output_bytes, ensure_space

    required = estimate_output_bytes(request.total_duration)
    try:
        ensure_space(request.output_path, required)
        return
    except DiskSpaceError:
        pass

    try:
        from jingxu.infrastructure.diagnostics import cleanup_workspace

        cleanup_workspace()
    except Exception:  # noqa: BLE001 - 清理失败不应掩盖空间诊断
        pass
    ensure_space(request.output_path, required)


def _archive_failure(request: RenderRequest, job_id: str | None, error: RenderError, filter_text: str) -> None:
    """把失败任务的日志与滤镜文本归档到输出目录（可诊断）。"""
    if not job_id:
        return
    try:
        from jingxu.infrastructure.diagnostic_store import archive_failure, trim_old_diagnostics

        archive_failure(
            request.output_path.parent,
            job_id,
            log_text=str(error),
            filter_text=filter_text or None,
            stderr_text=getattr(error, "stderr_text", "") or None,
        )
        trim_old_diagnostics(request.output_path.parent, current_job_id=job_id)
    except Exception:  # noqa: BLE001 - 归档失败不影响原始错误
        pass


def _strip_hardware_decode(command: list[str]) -> list[str] | None:
    """移除硬件解码参数生成软件命令；不含任何硬解参数时返回 None。

    同时清理设备初始化与输出格式参数：只摘 ``-hwaccel`` 会留下
    ``-hwaccel_output_format qsv``，导致软件帧被误标为设备帧。
    """
    removable_flags = {
        "-hwaccel",
        "-hwaccel_device",
        "-hwaccel_output_format",
        "-init_hw_device",
    }
    stripped: list[str] = []
    index = 0
    found = False
    while index < len(command):
        token = command[index]
        if token in removable_flags:
            found = True
            index += 2  # 跳过旗标与其取值（-init_hw_device 也是「旗标 值」形式）
            continue
        stripped.append(token)
        index += 1
    return stripped if found else None


def _clear_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _build_transcode_command(
    ffmpeg_path: Path,
    request: RenderRequest,
    script_directory: Path,
    part_path: Path,
    temp_dir: Path | None,
    encoder: EncoderChoice | None,
    *,
    processing_plan: HardwareProcessingPlan | None = None,
) -> tuple[list[str], Path]:
    """编译滤镜图并返回 (常规转码命令, 滤镜脚本路径)。"""
    gradient_path: Path | None = None
    if request.split is not None and request.split.feather:
        try:
            gradient_path = feather_gradient(
                ffmpeg_path,
                request.settings.width,
                request.settings.height,
                request.split.mode,
                request.split.feather_px,
                cache_directory=temp_dir,
            )
        except FeatherError:
            gradient_path = None

    script_path = script_directory / "concat.filter"
    subtitle_path: Path | None = None
    if request.subtitles is not None and not request.subtitles.is_empty:
        subtitle_path = write_ass(
            script_directory / "subtitles.ass",
            list(request.subtitles.cues),
            request.subtitles.style,
            request.settings.width,
            request.settings.height,
        )

    graph = build_filter_graph(
        request.plan,
        request.settings,
        split=request.split,
        layers=request.layers,
        bgm=request.bgm,
        gradient_path=gradient_path,
        removal=request.removal,
        subtitle_path=subtitle_path,
        boost=_materialize_boost(request),
        double_screen=request.double_screen,
        four_screen=request.four_screen,
        processing_plan=processing_plan,
    )
    choice = encoder or default_registry(ffmpeg_path).resolve(request.settings.processing)
    script_path.write_text(graph.script, encoding="utf-8")
    command = build_render_command(
        ffmpeg_path,
        request,
        graph,
        script_path,
        part_path,
        encoder=choice,
        processing_plan=processing_plan,
    )
    return command, script_path


def _materialize_boost(request: RenderRequest):
    """按任务种子物化主轨音量/缩放倍率；未启用时返回 None。

    ``settings.boost`` 正常是待物化的计划；传入已物化倍率时直接复用
    （便于测试与上层预物化）。
    """
    from jingxu.domain.effects import MaterializedMainMaterialBoost

    plan = request.settings.boost
    if plan is None:
        return None
    if isinstance(plan, MaterializedMainMaterialBoost):
        return plan if plan.is_active else None
    if not plan.is_active:
        return None
    return plan.materialize(request.plan.seed if request.plan.seed is not None else 0, len(request.plan.assets))


def _execute(
    ffmpeg_path: Path,
    command: list[str],
    request: RenderRequest,
    part_path: Path,
    total_seconds: float,
    on_progress: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> Path:
    """执行 ffmpeg 命令：进度解析、取消、半成品改名与封面生成。"""
    guard = ProcessTreeGuard()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **guard.spawn_kwargs(),
    )
    guard.attach(process)

    stderr_lines: list[str] = []
    stderr_thread = threading.Thread(
        target=_drain_stderr,
        args=(process, stderr_lines),
        daemon=True,
    )
    stderr_thread.start()

    try:
        _consume_progress(process, total_seconds, on_progress, cancel_event)
        return_code = process.wait()
    except RenderCancelled:
        guard.terminate(process)
        raise
    except BaseException:
        if process.poll() is None:
            guard.terminate(process)
        raise
    finally:
        stderr_thread.join(timeout=5)
        guard.close()

    if return_code != 0:
        detail = " ".join(stderr_lines[-3:]).strip()
        raise RenderError(
            f"FFmpeg 退出码 {return_code}。{detail}",
            stderr_text="\n".join(stderr_lines[-120:]),
        )

    if part_path.exists():
        if request.output_path.exists():
            request.output_path.unlink()
        part_path.replace(request.output_path)

    if request.cover is not None:
        try:
            generate_cover(
                ffmpeg_path,
                request.output_path,
                request.cover.output_path,
                at_seconds=request.cover.at_seconds,
                mode=request.cover.mode,
                first_source_path=request.plan.assets[0].path if request.plan.assets else None,
            )
        except CoverError:
            pass

    if on_progress is not None:
        on_progress(RenderProgress(100.0, total_seconds, total_seconds, "end"))
    return request.output_path


def _drain_stderr(process: subprocess.Popen, sink: list[str]) -> None:
    assert process.stderr is not None
    for line in process.stderr:
        text = line.strip()
        if text:
            sink.append(text)
            if len(sink) > 400:
                del sink[:200]


def _consume_progress(
    process: subprocess.Popen,
    total_seconds: float,
    on_progress: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> None:
    assert process.stdout is not None
    last_reported = -1.0

    for raw_line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            raise RenderCancelled("渲染已取消。")

        line = raw_line.strip()
        if not line or "=" not in line:
            continue

        key, _, value = line.partition("=")
        if key == "progress" and value == "end":
            return
        if on_progress is None:
            continue

        rendered = 0.0
        if key == "out_time_us":
            try:
                rendered = int(value) / 1_000_000
            except ValueError:
                continue
        elif key == "out_time":
            try:
                rendered = _parse_time_value(value)
            except ValueError:
                continue
        elif key == "speed":
            continue
        else:
            continue

        percent = min(rendered / total_seconds * 100.0, 99.9)
        if percent - last_reported >= 0.5 or percent >= 99.9:
            last_reported = percent
            on_progress(RenderProgress(round(percent, 2), rendered, total_seconds))

    if cancel_event is not None and cancel_event.is_set():
        raise RenderCancelled("渲染已取消。")
