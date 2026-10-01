"""序号命名模板：保存/应用/重命名/删除常用序号表达式。

文档格式：``{"schemaVersion": 1, "templates": [{"id", "displayName", "expression"}]}``
（对齐 .NET ``SequenceTemplateService``）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from jingxu.domain.composition import SequenceError, parse_expression, split_expressions
from jingxu.infrastructure.paths import data_directory

CURRENT_SCHEMA_VERSION = 1
MAX_TEMPLATES = 60


@dataclass(frozen=True, slots=True)
class SequenceTemplate:
    """一条序号模板。"""

    id: str
    display_name: str
    expression: str


def validate_expression(expression: str) -> str:
    """校验序号表达式（支持多条，换行/分号分隔）。"""
    expressions = split_expressions(expression)
    if not expressions:
        raise ValueError("序号表达式不能为空。")
    for item in expressions:
        try:
            parse_expression(item)
        except SequenceError as error:
            raise ValueError(f"表达式「{item}」：{error}") from error
    return expression.strip()


class SequenceTemplateStore:
    """序号模板的 JSON 存储（原子写入，按名称唯一）。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else data_directory() / "sequence-templates.json"
        self._templates: list[SequenceTemplate] = []
        self._load()

    # ────────────────────────────── 读取 ──────────────────────────────

    @property
    def templates(self) -> list[SequenceTemplate]:
        return list(self._templates)

    @property
    def names(self) -> list[str]:
        return [template.display_name for template in self._templates]

    def get(self, name: str) -> SequenceTemplate | None:
        wanted = (name or "").strip()
        for template in self._templates:
            if template.display_name == wanted:
                return template
        return None

    # ────────────────────────────── 写入 ──────────────────────────────

    def save(self, name: str, expression: str) -> SequenceTemplate:
        """新增或按名称覆盖模板。"""
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("模板名称不能为空。")
        validated = validate_expression(expression)

        existing = self.get(clean_name)
        if existing is not None:
            updated = SequenceTemplate(id=existing.id, display_name=clean_name, expression=validated)
            self._templates = [updated if template.id == existing.id else template for template in self._templates]
            self._persist()
            return updated

        template = SequenceTemplate(id=uuid.uuid4().hex, display_name=clean_name, expression=validated)
        self._templates.append(template)
        if len(self._templates) > MAX_TEMPLATES:
            self._templates = self._templates[-MAX_TEMPLATES:]
        self._persist()
        return template

    def rename(self, name: str, new_name: str) -> bool:
        template = self.get(name)
        clean_name = (new_name or "").strip()
        if template is None or not clean_name:
            return False
        if self.get(clean_name) is not None and clean_name != template.display_name:
            raise ValueError(f"已存在同名模板：{clean_name}。")
        self._templates = [
            SequenceTemplate(id=item.id, display_name=clean_name, expression=item.expression)
            if item.id == template.id
            else item
            for item in self._templates
        ]
        self._persist()
        return True

    def delete(self, name: str) -> bool:
        template = self.get(name)
        if template is None:
            return False
        self._templates = [item for item in self._templates if item.id != template.id]
        self._persist()
        return True

    # ────────────────────────────── 存储 ──────────────────────────────

    def _load(self) -> None:
        if not self._path.is_file():
            self._templates = []
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            self._templates = []
            return

        templates: list[SequenceTemplate] = []
        raw_templates = payload.get("templates") if isinstance(payload, dict) else None
        if isinstance(raw_templates, list):
            for raw in raw_templates:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("displayName") or "").strip()
                expression = str(raw.get("expression") or "").strip()
                if not name or not expression:
                    continue
                templates.append(
                    SequenceTemplate(
                        id=str(raw.get("id") or uuid.uuid4().hex),
                        display_name=name,
                        expression=expression,
                    )
                )
        self._templates = templates

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": CURRENT_SCHEMA_VERSION,
            "templates": [
                {"id": template.id, "displayName": template.display_name, "expression": template.expression}
                for template in self._templates
            ],
        }
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._path)
