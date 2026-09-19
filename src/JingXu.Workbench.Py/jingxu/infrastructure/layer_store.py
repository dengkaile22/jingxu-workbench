"""图层持久化：蒙版与贴纸列表存于数据目录。"""

from __future__ import annotations

import json
from pathlib import Path

from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.infrastructure.paths import data_directory

OVERLAY_FILE_NAME = "overlay-layers.json"
STICKER_FILE_NAME = "sticker-layers.json"


def _store_name(kind: LayerKind) -> str:
    return OVERLAY_FILE_NAME if kind is LayerKind.OVERLAY else STICKER_FILE_NAME


def _parse_crop_bounds(raw: object) -> tuple[float, float, float, float] | None:
    """解析人工框选：必须是 4 个数字，否则视为缺失。"""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    return (x, y, width, height)


def layer_to_payload(layer: LayerSpec) -> dict:
    """把图层序列化为字典（存储与项目文档共用）。"""
    return {
        "id": layer.id,
        "source": str(layer.source),
        "start_seconds": layer.start_seconds,
        "end_seconds": layer.end_seconds,
        "x_percent": layer.x_percent,
        "y_percent": layer.y_percent,
        "width_percent": layer.width_percent,
        "height_percent": layer.height_percent,
        "opacity": layer.opacity,
        "remove_black": layer.remove_black,
        "rotation_degrees": layer.rotation_degrees,
        "feather": layer.feather,
        "top_fade": layer.top_fade,
        "source_crop_canvas": layer.source_crop_canvas,
        "source_crop_y": layer.source_crop_y,
        "source_crop_bounds": (
            list(layer.source_crop_bounds) if layer.source_crop_bounds is not None else None
        ),
        "fit": layer.fit,
        "scale_percent": layer.scale_percent,
        "start_clip_index": layer.start_clip_index,
        "audio_mode": layer.audio_mode,
        "z_index": layer.z_index,
        "enabled": layer.enabled,
    }


def layer_from_payload(kind: LayerKind, entry: dict) -> LayerSpec | None:
    """从字典还原图层；缺文件或非法条目返回 ``None``。"""
    raw_source = entry.get("source") if isinstance(entry, dict) else None
    if not raw_source:
        return None
    source = Path(str(raw_source))
    if not source.is_file():
        return None
    try:
        return LayerSpec(
            kind=kind,
            source=source,
            start_seconds=float(entry.get("start_seconds") or 0.0),
            end_seconds=float(entry.get("end_seconds") or 0.0),
            x_percent=float(entry.get("x_percent", 50.0)),
            y_percent=float(entry.get("y_percent", 50.0)),
            width_percent=float(entry.get("width_percent", 30.0)),
            height_percent=float(entry.get("height_percent") or 0.0),
            opacity=float(entry.get("opacity", 1.0)),
            remove_black=bool(entry.get("remove_black", False)),
            rotation_degrees=float(entry.get("rotation_degrees") or 0.0),
            feather=float(entry.get("feather") or 0.0),
            top_fade=float(entry.get("top_fade") or 0.0),
            source_crop_canvas=bool(entry.get("source_crop_canvas", False)),
            source_crop_y=float(entry.get("source_crop_y") or 0.0),
            source_crop_bounds=_parse_crop_bounds(entry.get("source_crop_bounds")),
            fit=str(entry.get("fit") or "fill_crop"),
            scale_percent=float(entry.get("scale_percent") or 100.0),
            start_clip_index=max(1, int(entry.get("start_clip_index") or 1)),
            audio_mode=str(entry.get("audio_mode") or "discard"),
            z_index=int(entry.get("z_index") or 0),
            enabled=bool(entry.get("enabled", True)),
            id=str(entry.get("id") or ""),
        )
    except (TypeError, ValueError):
        return None


class LayerStore:
    """按图层种类维护一份有序列表。"""

    def __init__(self, kind: LayerKind, store_path: Path | None = None) -> None:
        self._kind = kind
        self._store_path = Path(store_path) if store_path else data_directory() / _store_name(kind)
        self._layers: list[LayerSpec] = []
        self._load()

    @property
    def store_path(self) -> Path:
        return self._store_path

    @property
    def layers(self) -> list[LayerSpec]:
        return list(self._layers)

    @property
    def enabled_layers(self) -> list[LayerSpec]:
        return [layer for layer in self._layers if layer.enabled]

    def add(self, source: Path) -> LayerSpec:
        layer = LayerSpec(kind=self._kind, source=Path(source))
        self._layers.append(layer)
        self.save()
        return layer

    def replace(self, layer: LayerSpec) -> bool:
        for index, existing in enumerate(self._layers):
            if existing.id == layer.id:
                self._layers[index] = layer
                self.save()
                return True
        return False

    def remove(self, layer_id: str) -> bool:
        before = len(self._layers)
        self._layers = [layer for layer in self._layers if layer.id != layer_id]
        if len(self._layers) != before:
            self.save()
            return True
        return False

    def clear(self) -> None:
        if self._layers:
            self._layers = []
            self.save()

    def find(self, layer_id: str) -> LayerSpec | None:
        return next((layer for layer in self._layers if layer.id == layer_id), None)

    def export_layers(self) -> list[dict]:
        """导出当前图层为可序列化字典（项目文档复用）。"""
        return [layer_to_payload(layer) for layer in self._layers]

    def import_layers(self, entries: list) -> int:
        """用给定条目替换当前列表（缺文件与非法条目被跳过），并落盘。"""
        layers = [
            layer
            for layer in (layer_from_payload(self._kind, entry) for entry in entries or [])
            if layer is not None
        ]
        self._layers = layers
        self.save()
        return len(layers)

    def save(self) -> None:
        payload = {"kind": self._kind.value, "layers": self.export_layers()}
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._store_path.is_file():
            return
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        for entry in payload.get("layers") or []:
            layer = layer_from_payload(self._kind, entry)
            if layer is not None:
                self._layers.append(layer)
