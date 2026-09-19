"""字幕实验室持久化：条目、样式与去除区域。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jingxu.domain.subtitles import (
    RemovalMode,
    SubtitleBurnSpec,
    SubtitleCue,
    SubtitlePosition,
    SubtitleRemovalSpec,
    SubtitleStyle,
)
from jingxu.infrastructure.paths import data_directory

STORE_FILE_NAME = "subtitle-lab.json"


@dataclass
class SubtitleDocument:
    cues: list[SubtitleCue] = field(default_factory=list)
    style: SubtitleStyle = SubtitleStyle()
    removal: SubtitleRemovalSpec = SubtitleRemovalSpec()

    def burn_spec(self) -> SubtitleBurnSpec | None:
        if not self.cues:
            return None
        return SubtitleBurnSpec(cues=tuple(self.cues), style=self.style)


def document_to_payload(document: SubtitleDocument) -> dict:
    """把字幕文档序列化为字典（存储与项目文档共用）。"""
    return {
        "cues": [
            {"start": cue.start, "end": cue.end, "text": cue.text} for cue in document.cues
        ],
        "style": {
            "font_name": document.style.font_name,
            "font_size": document.style.font_size,
            "color": document.style.color,
            "outline_color": document.style.outline_color,
            "outline": document.style.outline,
            "shadow": document.style.shadow,
            "margin_v": document.style.margin_v,
            "position": document.style.position.value,
        },
        "removal": {
            "mode": document.removal.mode.value,
            "x_percent": document.removal.x_percent,
            "y_percent": document.removal.y_percent,
            "width_percent": document.removal.width_percent,
            "height_percent": document.removal.height_percent,
            "blur_power": document.removal.blur_power,
            "enabled": document.removal.enabled,
        },
    }


def payload_to_document(payload: dict) -> SubtitleDocument:
    """从字典还原字幕文档（字段缺失或非法时用默认值）。"""
    cues = []
    for entry in payload.get("cues") or []:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        start = float(entry.get("start") or 0.0)
        end = float(entry.get("end") or 0.0)
        cues.append(SubtitleCue(start=start, end=max(end, start + 0.01), text=text))

    style_payload = payload.get("style") or {}
    try:
        position = SubtitlePosition(str(style_payload.get("position") or "bottom"))
    except ValueError:
        position = SubtitlePosition.BOTTOM

    removal_payload = payload.get("removal") or {}
    try:
        mode = RemovalMode(str(removal_payload.get("mode") or "blur"))
    except ValueError:
        mode = RemovalMode.BLUR

    return SubtitleDocument(
        cues=cues,
        style=SubtitleStyle(
            font_name=str(style_payload.get("font_name") or "Microsoft YaHei"),
            font_size=int(style_payload.get("font_size") or 22),
            color=str(style_payload.get("color") or "#FFFFFF"),
            outline_color=str(style_payload.get("outline_color") or "#000000"),
            outline=int(style_payload.get("outline") or 2),
            shadow=int(style_payload.get("shadow") or 0),
            margin_v=int(style_payload.get("margin_v") or 40),
            position=position,
        ),
        removal=SubtitleRemovalSpec(
            mode=mode,
            x_percent=float(removal_payload.get("x_percent", 8.0)),
            y_percent=float(removal_payload.get("y_percent", 76.0)),
            width_percent=float(removal_payload.get("width_percent", 84.0)),
            height_percent=float(removal_payload.get("height_percent", 18.0)),
            blur_power=int(removal_payload.get("blur_power", 12)),
            enabled=bool(removal_payload.get("enabled", True)),
        ),
    )


class SubtitleStore:
    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = Path(store_path) if store_path else data_directory() / STORE_FILE_NAME
        self.document = SubtitleDocument()
        self._load()

    @property
    def store_path(self) -> Path:
        return self._store_path

    def export_document(self) -> dict:
        return document_to_payload(self.document)

    def import_document(self, payload: dict) -> None:
        self.document = payload_to_document(payload or {})
        self.save()

    def save(self) -> None:
        payload = document_to_payload(self.document)
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._store_path.is_file():
            return
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        self.document = payload_to_document(payload)
