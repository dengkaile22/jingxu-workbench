"""临时目录清理：每条落盘路径都必须被清理白名单覆盖。

**缺陷背景**：混剪页新增「效果预览」后写了 ``%TEMP%/jingxu-effect-preview``，
但没登记进 ``KNOWN_TEMP_DIRECTORIES``。清理只认已知顶层名，于是每次预览的
jpg 永久留在 %TEMP%（本机实测确有残留）。

这类缺陷会**随着新功能不断复发**，所以本文件不只测"当前这几个目录能清"，
而是从**源码里抽出所有 ``gettempdir() / ...`` 目录名**，逐一对清理判定函数
断言——以后谁再新增一个临时目录却忘了登记，这里会直接失败。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jingxu.infrastructure.diagnostics import (  # noqa: E402
    KNOWN_TEMP_DIRECTORIES,
    _is_temp_candidate,
    cleanup_workspace,
)

PACKAGE_ROOT = APP_ROOT / "jingxu"
# 三种真实写法（见源文件）：
#   Path(tempfile.gettempdir()) / "jingxu-gate-preview"
#   temp_directory() / "jingxu-xxx"
#   temp_directory() / f"jingxu-xxx-{uuid}"
# 只取第一段字面量，忽略后面的 UUID 片段。
_TEMP_ROOT = r"(?:Path\(\s*tempfile\.gettempdir\(\)\s*\)|temp_directory\(\))"
LITERAL_DIR = re.compile(
    _TEMP_ROOT + r'\s*/\s*(?:Path\(\s*)?[fF]?"([A-Za-z][A-Za-z0-9_-]*)"'
)
CONST_DIR = re.compile(_TEMP_ROOT + r"\s*/\s*([A-Z][A-Z0-9_]*)")


def _temp_directory_literals() -> set[str]:
    """源码里直接写死在临时根下的目录名（含引用模块常量的情况）。

    引用常量时（``/ PREVIEW_TEMP_DIRECTORY``）把常量名也返回，
    由调用方在源码里解析它的字面量值。
    """
    found: set[str] = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(LITERAL_DIR.findall(text))
        for constant in CONST_DIR.findall(text):
            definition = re.search(
                rf'^{constant}\s*=\s*"([^"]+)"', text, re.MULTILINE
            )
            if definition:
                found.add(definition.group(1))
    return found


# ── 全量覆盖：源码里出现的临时目录都要能被清理 ──────────────────────────────


def test_every_literal_temp_directory_is_cleanable() -> None:
    """源码里每个 ``gettempdir() / "xxx"`` 都必须被清理白名单认出。

    回归：``jingxu-effect-preview`` 曾漏登记，残留永久留在 %TEMP%。
    """
    literals = _temp_directory_literals()
    assert literals, "未能从源码抽出任何临时目录字面量，检查正则是否失配"

    unknown = sorted(
        name
        for name in literals
        if not _is_temp_candidate(Path("C:/Temp") / name)
    )
    assert unknown == [], (
        "以下临时目录不会被清理，会永久残留在 %TEMP%（请登记到 "
        f"KNOWN_TEMP_DIRECTORIES 或改用已有前缀）：{unknown}"
    )


def test_effect_preview_is_registered() -> None:
    """混剪页「效果预览」的目录必须显式登记（本轮修的缺陷）。"""
    assert "jingxu-effect-preview" in KNOWN_TEMP_DIRECTORIES
    assert _is_temp_candidate(Path("C:/Temp/jingxu-effect-preview")) is True


# ── 清理行为 ────────────────────────────────────────────────────────────────


def test_cleanup_workspace_removes_effect_preview(tmp_path: Path) -> None:
    directory = tmp_path / "jingxu-effect-preview"
    directory.mkdir()
    for index in range(3):
        (directory / f"effect-{index}.jpg").write_bytes(b"x" * 512)

    report = cleanup_workspace(temp_directory=tmp_path)

    assert not directory.exists(), "效果预览目录没有被清理"
    assert report.deleted >= 1
    assert report.freed_bytes >= 3 * 512


def test_cleanup_workspace_keeps_unrelated_directories(tmp_path: Path) -> None:
    """绝不误删：非本软件的目录一律不动。"""
    unrelated = tmp_path / "some-other-app"
    unrelated.mkdir()
    (unrelated / "data.bin").write_bytes(b"x" * 128)
    foreign = tmp_path / "jingxu-fake-not-registered"
    foreign.mkdir()

    cleanup_workspace(temp_directory=tmp_path)

    assert unrelated.is_dir(), "删除了不属于本软件的目录"
    assert (unrelated / "data.bin").is_file()
    assert foreign.is_dir(), "删除了未登记的 jingxu-* 目录（白名单被放宽了）"


def test_cleanup_protects_active_job_outputs(tmp_path: Path) -> None:
    """运行中任务的产物与半成品必须受保护。"""
    output = tmp_path / "out.mp4"
    output.write_bytes(b"x" * 64)
    part = tmp_path / "out.mp4.part"
    part.write_bytes(b"x" * 64)

    report = cleanup_workspace(
        temp_directory=tmp_path / "empty-temp",
        protected_paths=(output, part),
    )

    assert output.is_file()
    assert part.is_file()
    assert report.skipped >= 0
