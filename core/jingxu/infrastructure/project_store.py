"""项目文档持久化：版本化 JSON、原子写入与只读兼容。

项目文件（``.jxproj``）包含素材集合、混剪设置、图层、字幕与最近任务；
读取高于当前支持版本的文档时以只读方式打开，保存时需另存为新文件。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

PROJECT_SUFFIX = ".jxproj"
CURRENT_SCHEMA_VERSION = 1


class ProjectError(RuntimeError):
    """项目文件读取或写入失败。"""


@dataclass(frozen=True, slots=True)
class ProjectDocument:
    """与具体界面解耦的项目快照。"""

    schema_version: int = CURRENT_SCHEMA_VERSION
    name: str = "未命名项目"
    groups: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
    output_directory: str = ""
    composition: dict = field(default_factory=dict)
    overlays: tuple[dict, ...] = ()
    stickers: tuple[dict, ...] = ()
    subtitles: dict = field(default_factory=dict)
    recent_jobs: tuple[dict, ...] = ()
    created_at: str = ""
    modified_at: str = ""
    read_only: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _as_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_mapping(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _as_entries(value: object) -> tuple[dict, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(entry) for entry in value if isinstance(entry, dict))


def _parse_group(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text for text in (_as_text(item) for item in value) if text)


def _parse_groups(value: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    if isinstance(value, (list, tuple)):
        groups = [_parse_group(entry) for entry in list(value)[:2]]
    while len(groups) < 2:
        groups.append(())
    return (groups[0], groups[1])


def _pick(payload: dict, *keys: str) -> object:
    """按优先顺序取字段，兼容 camelCase 与 snake_case。"""
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def project_snapshot(document: ProjectDocument) -> dict:
    """把文档转为 JSON 可序列化字典（``read_only`` 为运行时标记，不落盘）。"""
    return {
        "schemaVersion": int(document.schema_version),
        "name": str(document.name),
        "groups": [list(group) for group in document.groups],
        "output_directory": _as_text(document.output_directory),
        "composition": dict(document.composition),
        "overlays": [dict(entry) for entry in document.overlays],
        "stickers": [dict(entry) for entry in document.stickers],
        "subtitles": dict(document.subtitles),
        "recent_jobs": [dict(entry) for entry in document.recent_jobs],
        "created_at": _as_text(document.created_at),
        "modified_at": _as_text(document.modified_at),
    }


def document_from_payload(
    payload: dict,
    *,
    supported_version: int = CURRENT_SCHEMA_VERSION,
) -> ProjectDocument:
    """从字典还原文档；字段缺失或类型异常时回退默认值。"""
    if not isinstance(payload, dict):
        raise ProjectError("项目文件结构无效。")

    try:
        version = int(_pick(payload, "schemaVersion", "schema_version"))
    except (TypeError, ValueError):
        version = CURRENT_SCHEMA_VERSION

    return ProjectDocument(
        schema_version=version,
        name=_as_text(_pick(payload, "name")) or "未命名项目",
        groups=_parse_groups(_pick(payload, "groups")),
        output_directory=_as_text(_pick(payload, "output_directory", "outputDirectory")),
        composition=_as_mapping(_pick(payload, "composition")),
        overlays=_as_entries(_pick(payload, "overlays")),
        stickers=_as_entries(_pick(payload, "stickers")),
        subtitles=_as_mapping(_pick(payload, "subtitles")),
        recent_jobs=_as_entries(_pick(payload, "recent_jobs", "recentJobs")),
        created_at=_as_text(_pick(payload, "created_at", "createdAt")),
        modified_at=_as_text(_pick(payload, "modified_at", "modifiedAt")),
        read_only=version > int(supported_version),
    )


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))
    except OSError:
        return left == right


def _atomic_write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise


def save_project(
    path: Path,
    document: ProjectDocument,
    *,
    source_path: Path | None = None,
) -> ProjectDocument:
    """原子写入项目文件，返回填好时间戳的文档。

    ``source_path`` 为文档的原始路径；只读文档（更高版本）不允许覆盖来源文件。
    """
    target = Path(path)
    if document.read_only and source_path is not None and _same_path(target, Path(source_path)):
        raise ProjectError("项目由更高版本保存，仅可另存为新文件。")

    now = _now_iso()
    saved = replace(
        document,
        schema_version=CURRENT_SCHEMA_VERSION,
        created_at=document.created_at or now,
        modified_at=now,
        read_only=False,
    )
    try:
        _atomic_write_json(target, project_snapshot(saved))
    except OSError as error:
        raise ProjectError(f"无法写入项目文件：{target}") from error
    return saved


def load_project(
    path: Path,
    *,
    supported_version: int = CURRENT_SCHEMA_VERSION,
) -> ProjectDocument:
    """读取项目文件；更高版本标记为只读而不报错。"""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise ProjectError(f"无法读取项目文件：{source}") from error

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ProjectError(f"项目文件不是合法 JSON：{source}") from error

    if not isinstance(payload, dict):
        raise ProjectError(f"项目文件结构无效：{source}")

    return document_from_payload(payload, supported_version=supported_version)
