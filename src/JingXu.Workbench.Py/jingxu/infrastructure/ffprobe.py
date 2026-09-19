"""FFprobe 探测：视频/音频流、时长、帧率。"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from jingxu.domain.media import MediaAsset, extract_sequence_index


class ProbeError(RuntimeError):
    """素材探测失败。"""


def _parse_fraction(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        numerator, _, denominator = value.partition("/")
        try:
            den = float(denominator)
            return float(numerator) / den if den else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def parse_probe_payload(payload: dict, path: Path) -> MediaAsset:
    """把 ffprobe JSON 解析为 :class:`MediaAsset`（便于单测）。"""
    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video_stream is None:
        raise ProbeError(f"素材缺少视频流：{path.name}")

    duration = 0.0
    for source in (payload.get("format") or {}, video_stream):
        try:
            duration = float(source.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            break

    fps = _parse_fraction(video_stream.get("avg_frame_rate")) or _parse_fraction(
        video_stream.get("r_frame_rate")
    )

    return MediaAsset(
        path=path,
        duration=duration,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        fps=round(fps, 3),
        has_audio=audio_stream is not None,
        video_codec=str(video_stream.get("codec_name") or ""),
        audio_codec=str(audio_stream.get("codec_name") or "") if audio_stream else "",
        sequence_index=extract_sequence_index(path.name),
        asset_id=uuid.uuid4().hex,
    )


def probe_media(path: Path, ffprobe_path: Path, *, timeout: float = 60.0) -> MediaAsset:
    """调用 ffprobe 探测单个素材。"""
    path = Path(path)
    if not path.is_file():
        raise ProbeError(f"素材不存在：{path}")

    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
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
        )
    except subprocess.TimeoutExpired as error:
        raise ProbeError(f"探测超时：{path.name}") from error
    except OSError as error:
        raise ProbeError(f"无法启动 ffprobe：{error}") from error

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"退出码 {completed.returncode}"
        raise ProbeError(f"探测失败：{path.name}（{tail}）")

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise ProbeError(f"探测输出无法解析：{path.name}") from error

    return parse_probe_payload(payload, path)
