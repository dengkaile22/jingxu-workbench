"""无界面冒烟命令：素材导入与蒙版叠加（CI/诊断用）。

对齐 .NET 的 ``--import-smoke`` 与 ``--overlay-smoke``：探测素材并输出
机器可读的 JSON 报告，便于发布流水线与现场排障。
"""

from __future__ import annotations

from pathlib import Path

from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.media import MediaAsset, extract_sequence_index
from jingxu.domain.render import RenderSettings
from jingxu.infrastructure.ffprobe import ProbeError, probe_media
from jingxu.infrastructure.frame_preview import render_composite_frame

OVERLAY_PRESETS = {
    "free": {"width_percent": 90.0, "height_percent": 42.0, "y_percent": 26.0, "opacity": 0.72},
    "full": {"width_percent": 100.0, "height_percent": 100.0, "y_percent": 50.0, "opacity": 0.8},
    "shape": {"width_percent": 60.0, "height_percent": 60.0, "y_percent": 50.0, "opacity": 1.0},
}


def import_smoke(path: Path, ffprobe: Path) -> dict:
    """探测单个素材并返回导入报告（成功与失败都用同一结构）。"""
    path = Path(path)
    report: dict[str, object] = {
        "schemaVersion": 1,
        "path": str(path),
        "exists": path.is_file(),
        "sequenceIndex": extract_sequence_index(path.name),
        "asset": None,
        "error": None,
    }
    if not path.is_file():
        report["error"] = "素材不存在。"
        return report

    try:
        asset = probe_media(path, ffprobe)
    except ProbeError as error:
        report["error"] = str(error)
        return report

    report["asset"] = _asset_payload(asset)
    return report


def overlay_smoke(path: Path, ffmpeg: Path, ffprobe: Path, output: Path, preset: str = "free") -> dict:
    """用蒙版素材合成一张静帧预览，返回报告。"""
    path = Path(path)
    preset_values = OVERLAY_PRESETS.get(preset, OVERLAY_PRESETS["free"])
    report: dict[str, object] = {
        "schemaVersion": 1,
        "path": str(path),
        "preset": preset if preset in OVERLAY_PRESETS else "free",
        "output": str(output),
        "rendered": False,
        "error": None,
    }
    if not path.is_file():
        report["error"] = "蒙版素材不存在。"
        return report

    try:
        asset = probe_media(path, ffprobe)
    except ProbeError as error:
        report["error"] = str(error)
        return report

    settings = RenderSettings(width=608, height=1080, fps=30)
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=path,
        end_seconds=asset.duration if asset.duration > 0 else 1.0,
        top_fade=1.0,
        feather=0.28,
        **preset_values,
    )
    try:
        render_composite_frame(ffmpeg, asset, (layer,), settings, output, at_seconds=0.0)
    except Exception as error:  # noqa: BLE001 - 冒烟命令需要把失败原因交回调用方
        report["error"] = str(error)
        return report

    report["rendered"] = output.is_file()
    if not report["rendered"]:
        report["error"] = "合成预览未生成。"
    return report


def _asset_payload(asset: MediaAsset) -> dict:
    return {
        "duration": round(asset.duration, 3),
        "width": asset.width,
        "height": asset.height,
        "fps": asset.fps,
        "hasAudio": asset.has_audio,
        "videoCodec": asset.video_codec,
        "audioCodec": asset.audio_codec,
        "sequenceIndex": asset.sequence_index,
    }
