"""运行时清单：加载、结构校验、SHA-256 核验与逐组件诊断。

对齐 .NET ``RuntimeManifest`` / ``RuntimeManifestValidator`` / ``RuntimeDiagnosticService``：
清单固定版本、组件相对路径、许可与来源信息；可选组件缺失只提示不阻断。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_FILE_NAME = "runtime-manifest.json"
RUNTIME_ENV = "JINGXU_RUNTIME_DIR"
SKIP_HASH_ENV = "JINGXU_SKIP_HASH_VERIFY"
_PLACEHOLDER_HASH = "0" * 64
_REQUIRED_FIELDS = ("kind", "displayName", "relativePath", "sha256", "licenseId", "sourceUrl", "sourceCodeUrl")
_SEARCH_DEPTH = 8


@dataclass(frozen=True, slots=True)
class RuntimeComponent:
    """清单中的单个运行时组件。"""

    kind: str
    display_name: str
    relative_path: str
    required: bool
    version_arguments: tuple[str, ...]
    sha256: str
    license_id: str
    source_url: str
    source_code_url: str


@dataclass(frozen=True, slots=True)
class ManifestLoadResult:
    """清单加载结果：清单本体 + 校验问题列表。"""

    schema_version: int
    components: tuple[RuntimeComponent, ...]
    issues: tuple[str, ...]
    manifest_path: Path | None

    @property
    def is_valid(self) -> bool:
        return not self.issues and bool(self.components)


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    """逐组件诊断结果（设置页与自检共用）。"""

    kind: str
    display_name: str
    is_available: bool
    is_required: bool
    message: str
    suggested_action: str = ""
    resolved_path: str = ""
    source: str = ""
    license_id: str = ""


def manifest_search_paths() -> list[Path]:
    """清单候选路径：显式环境变量 → 仓库 build/ → 应用目录。"""
    candidates: list[Path] = []
    configured = os.environ.get("JINGXU_MANIFEST_PATH", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    here = Path(__file__).resolve()
    for parent in list(here.parents)[:_SEARCH_DEPTH]:
        candidates.append(parent / "build" / MANIFEST_FILE_NAME)
        candidates.append(parent / MANIFEST_FILE_NAME)
        candidates.append(parent / "runtime" / MANIFEST_FILE_NAME)
    return candidates


def load_manifest(path: Path | None = None) -> ManifestLoadResult:
    """加载并校验运行时清单；缺失时返回带问题的空结果。"""
    manifest_path = Path(path) if path is not None else next(
        (candidate for candidate in manifest_search_paths() if candidate.is_file()),
        None,
    )
    if manifest_path is None or not manifest_path.is_file():
        return ManifestLoadResult(0, (), ("未找到运行时清单 runtime-manifest.json。",), None)

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        return ManifestLoadResult(0, (), (f"清单无法解析：{error}",), manifest_path)

    if not isinstance(payload, dict):
        return ManifestLoadResult(0, (), ("清单根节点必须是对象。",), manifest_path)

    issues: list[str] = []
    schema_version = payload.get("schemaVersion")
    if not isinstance(schema_version, int) or schema_version < 1:
        issues.append("清单缺少有效的 schemaVersion（需为不小于 1 的整数）。")
        schema_version = 0

    raw_components = payload.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        issues.append("清单 components 必须是非空数组。")
        raw_components = []

    components: list[RuntimeComponent] = []
    for index, raw in enumerate(raw_components):
        label = f"components[{index}]"
        if not isinstance(raw, dict):
            issues.append(f"{label} 必须是对象。")
            continue
        missing = [field_name for field_name in _REQUIRED_FIELDS if not str(raw.get(field_name) or "").strip()]
        if missing:
            issues.append(f"{label} 缺少字段：{', '.join(missing)}。")
            continue

        relative_path = str(raw["relativePath"]).replace("\\", "/")
        if Path(relative_path).is_absolute() or relative_path.startswith("/"):
            issues.append(f"{label}.relativePath 必须是相对路径。")
            continue

        sha256 = str(raw["sha256"]).strip().lower()
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            issues.append(f"{label}.sha256 必须是 64 位十六进制字符串。")
            continue

        version_arguments = raw.get("versionArguments") or []
        if not isinstance(version_arguments, list) or any(not isinstance(item, str) for item in version_arguments):
            issues.append(f"{label}.versionArguments 必须是字符串数组。")
            version_arguments = []

        components.append(
            RuntimeComponent(
                kind=str(raw["kind"]),
                display_name=str(raw["displayName"]),
                relative_path=relative_path,
                required=bool(raw.get("required", False)),
                version_arguments=tuple(version_arguments),
                sha256=sha256,
                license_id=str(raw["licenseId"]),
                source_url=str(raw["sourceUrl"]),
                source_code_url=str(raw["sourceCodeUrl"]),
            )
        )

    return ManifestLoadResult(schema_version, tuple(components), tuple(issues), manifest_path)


def runtime_search_directories() -> list[Path]:
    """运行时搜索目录：环境变量 → 应用目录 runtime/ → 系统 PATH（由调用方处理）。"""
    directories: list[Path] = []
    configured = os.environ.get(RUNTIME_ENV, "").strip()
    if configured:
        directories.append(Path(configured).expanduser())

    here = Path(__file__).resolve()
    for parent in list(here.parents)[:_SEARCH_DEPTH]:
        candidate = parent / "runtime"
        if candidate not in directories:
            directories.append(candidate)
    return directories


def resolve_component_path(component: RuntimeComponent) -> tuple[Path | None, str]:
    """按搜索顺序定位组件文件；返回（路径, 来源描述）。"""
    for directory in runtime_search_directories():
        candidate = directory / component.relative_path
        if candidate.is_file():
            source = "环境变量 JINGXU_RUNTIME_DIR" if os.environ.get(RUNTIME_ENV, "").strip() else "应用目录 runtime/"
            return candidate, source

    name = Path(component.relative_path).name
    on_path = shutil.which(name)
    if on_path:
        return Path(on_path), "系统 PATH"
    return None, ""


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str, *, skip_env: bool = True) -> tuple[bool, str]:
    """校验文件哈希；占位哈希与显式跳过时返回通过。"""
    if skip_env and os.environ.get(SKIP_HASH_ENV, "").strip() in {"1", "true", "yes"}:
        return True, "已按环境变量跳过哈希校验。"
    if expected == _PLACEHOLDER_HASH:
        return True, "清单使用占位哈希（开发构建）。"
    try:
        actual = sha256_file(path)
    except OSError as error:
        return False, f"无法读取文件校验哈希：{error}"
    if actual != expected:
        return False, f"SHA-256 不匹配（期望 {expected[:12]}…，实际 {actual[:12]}…）。"
    return True, "哈希校验通过。"


def _version_probe(path: Path, arguments: tuple[str, ...]) -> str:
    if not arguments:
        return ""
    try:
        completed = subprocess.run(
            [str(path), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    lines = (completed.stdout or completed.stderr or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def diagnose_components(
    manifest: ManifestLoadResult | None = None,
    *,
    verify_hashes: bool = False,
) -> list[ComponentStatus]:
    """逐组件诊断：可用性、来源、版本与建议操作。"""
    result = manifest or load_manifest()
    statuses: list[ComponentStatus] = []

    for component in result.components:
        path, source = resolve_component_path(component)
        if path is None:
            statuses.append(
                ComponentStatus(
                    kind=component.kind,
                    display_name=component.display_name,
                    is_available=False,
                    is_required=component.required,
                    message="必需组件缺失。" if component.required else "可选组件未安装。",
                    suggested_action=(
                        f"将 {component.relative_path} 放入应用目录 runtime/ 并写入清单哈希。"
                        if component.required
                        else f"如需该功能，请下载 {component.display_name} 并放入 runtime/{Path(component.relative_path).parent}/。"
                    ),
                    license_id=component.license_id,
                )
            )
            continue

        message = "已就绪"
        if verify_hashes:
            ok, detail = verify_sha256(path, component.sha256)
            if not ok:
                statuses.append(
                    ComponentStatus(
                        kind=component.kind,
                        display_name=component.display_name,
                        is_available=False,
                        is_required=component.required,
                        message=detail,
                        suggested_action="重新下载该组件，或使用 Resolve-Runtimes 脚本刷新清单哈希。",
                        resolved_path=str(path),
                        source=source,
                        license_id=component.license_id,
                    )
                )
                continue
            message = detail

        version = _version_probe(path, component.version_arguments)
        if version:
            message = f"已就绪 · {version}"
        statuses.append(
            ComponentStatus(
                kind=component.kind,
                display_name=component.display_name,
                is_available=True,
                is_required=component.required,
                message=message,
                resolved_path=str(path),
                source=source,
                license_id=component.license_id,
            )
        )

    return statuses


def missing_required(manifest: ManifestLoadResult, statuses: list[ComponentStatus]) -> list[str]:
    """返回缺失的必需组件名称列表。"""
    required_kinds = {component.kind for component in manifest.components if component.required}
    return [status.display_name for status in statuses if status.is_required and not status.is_available and status.kind in required_kinds]
