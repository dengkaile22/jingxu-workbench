"""单帧合成预览：把主片与叠层参数渲染成一张 JPEG（对齐 .NET 叠层预览）。"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import LayerSpec
from jingxu.domain.media import MediaAsset
from jingxu.domain.render import RenderSettings
from jingxu.infrastructure.ffmpeg_runner import _append_input, _hidden_process_kwargs
from jingxu.infrastructure.filter_graph import build_filter_graph
from jingxu.infrastructure.process_control import no_window_kwargs


class FramePreviewError(RuntimeError):
    """单帧合成预览失败。"""


def extract_single_frame(
    ffmpeg_path: Path,
    video_path: Path,
    output_path: Path,
    *,
    timestamp: float = 0.0,
    timeout: float = 60.0,
) -> Path:
    """抽取单帧 PNG，供「预览与区域选择」在画面上框选区域。

    .NET 字幕实验室支持在视频画面上直接框选字幕区域；Python 版此前只有百分比
    输入框，用户很难填对。这里抽出首帧作为底图，配合可拖拽的选框使用。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, timestamp):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            **no_window_kwargs(),
        )
    except subprocess.TimeoutExpired as error:
        raise FramePreviewError("抽取预览帧超时。") from error
    except OSError as error:
        raise FramePreviewError(f"无法启动 FFmpeg：{error}") from error

    if completed.returncode != 0 or not output_path.is_file():
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"退出码 {completed.returncode}"
        raise FramePreviewError(f"抽取预览帧失败：{message}")
    return output_path


def composite_frame_command(
    ffmpeg_path: Path,
    base_asset: MediaAsset,
    layers: Sequence[LayerSpec],
    settings: RenderSettings,
    script_path: Path,
    output_path: Path,
    *,
    at_seconds: float = 0.0,
) -> list[str]:
    """编译单帧合成命令并写出滤镜脚本，返回 ffmpeg 参数列表。

    复用真实叠层引擎（:func:`build_filter_graph`）保证预览与成片一致；
    图层输入沿用循环输入（图片 ``-loop 1`` / 视频 ``-stream_loop -1``）。
    预览只输出单帧图片，因此构建纯视频图（素材按无音轨处理），避免出现
    FFmpeg 拒绝的未连接音频输出。
    """
    video_only = replace(
        base_asset,
        has_audio=False,
        audio_codec="",
    )
    plan = CompositionPlan(assets=(video_only,), mode=OrderMode.SEQUENTIAL)
    graph = build_filter_graph(plan, settings, layers=tuple(layers))

    script_path = Path(script_path)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(graph.script, encoding="utf-8")

    command = [str(ffmpeg_path), "-hide_banner", "-nostdin", "-y"]
    moment = max(float(at_seconds), 0.0)
    if moment > 0.0:
        command.extend(["-ss", f"{moment:.3f}"])
    command.extend(["-i", str(base_asset.path)])
    for extra in graph.extra_inputs:
        _append_input(command, extra)

    command.extend(
        [
            "-filter_complex_script",
            str(script_path),
            "-map",
            f"[{graph.video_label}]",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(output_path),
        ]
    )
    return command


def render_composite_frame(
    ffmpeg_path: Path,
    base_asset: MediaAsset,
    layers: Sequence[LayerSpec],
    settings: RenderSettings,
    output_path: Path,
    *,
    at_seconds: float = 0.0,
    timeout: float = 60.0,
) -> Path:
    """渲染单帧合成预览，成功返回 ``output_path``；失败抛 :class:`FramePreviewError`。

    滤镜脚本写在输出目录下的临时文件里，无论成败都会清理；只映射 ``[vout]``，
    滤镜图按纯视频构建。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    script_path = output_path.parent / f".jingxu-preview-{uuid4().hex[:8]}.filter"

    try:
        command = composite_frame_command(
            ffmpeg_path,
            base_asset,
            layers,
            settings,
            script_path,
            output_path,
            at_seconds=at_seconds,
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                **_hidden_process_kwargs(),
            )
        except subprocess.TimeoutExpired as error:
            raise FramePreviewError("合成预览超时。") from error
        except OSError as error:
            raise FramePreviewError(f"无法启动 FFmpeg：{error}") from error

        if completed.returncode != 0:
            stderr = completed.stderr or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            lines = stderr.strip().splitlines()
            tail = lines[-1] if lines else f"退出码 {completed.returncode}"
            raise FramePreviewError(f"合成预览失败：{tail}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise FramePreviewError("合成预览文件未生成或为零字节。")
        return output_path
    finally:
        script_path.unlink(missing_ok=True)
