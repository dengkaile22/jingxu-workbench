"""效果模板持久化：保存/应用一套混剪参数。"""

from __future__ import annotations

import json
from pathlib import Path

from jingxu.infrastructure.paths import data_directory

TEMPLATE_FILE_NAME = "effect-templates.json"
MAX_TEMPLATES = 40


class EffectTemplateStore:
    """命名模板：以名称索引的参数快照。"""

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = Path(store_path) if store_path else data_directory() / TEMPLATE_FILE_NAME
        self._templates: dict[str, dict] = {}
        self._load()

    @property
    def store_path(self) -> Path:
        return self._store_path

    @property
    def names(self) -> list[str]:
        return list(self._templates)

    def get(self, name: str) -> dict | None:
        payload = self._templates.get(name)
        return dict(payload) if payload is not None else None

    def save(self, name: str, payload: dict) -> None:
        clean = (name or "").strip()
        if not clean:
            raise ValueError("模板名称不能为空。")
        self._templates[clean] = dict(payload)
        while len(self._templates) > MAX_TEMPLATES:
            self._templates.pop(next(iter(self._templates)))
        self._persist()

    def rename(self, old_name: str, new_name: str) -> bool:
        clean = (new_name or "").strip()
        if old_name not in self._templates or not clean:
            return False
        payload = self._templates.pop(old_name)
        self._templates[clean] = payload
        self._persist()
        return True

    def delete(self, name: str) -> bool:
        if name not in self._templates:
            return False
        self._templates.pop(name)
        self._persist()
        return True

    def _persist(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(
            json.dumps({"templates": self._templates}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        if not self._store_path.is_file():
            return
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        templates = payload.get("templates")
        if isinstance(templates, dict):
            self._templates = {str(name): dict(value) for name, value in templates.items() if isinstance(value, dict)}
