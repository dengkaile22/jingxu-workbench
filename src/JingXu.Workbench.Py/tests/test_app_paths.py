"""应用路径解析：源码运行与 PyInstaller 冻结运行的差异。

冻结相关的分支用 monkeypatch 模拟 ``sys.frozen`` / ``sys._MEIPASS`` /
``sys.executable``，不需要真的打包才能验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from jingxu.infrastructure import app_paths


@pytest.fixture(autouse=True)
def _restore_sys_state():
    """确保测试不会把冻结标志泄漏给其它用例。"""
    frozen = getattr(sys, "frozen", None)
    meipass = getattr(sys, "_MEIPASS", None)
    executable = sys.executable
    yield
    for name, value in (("frozen", frozen), ("_MEIPASS", meipass)):
        if value is None:
            if hasattr(sys, name):
                delattr(sys, name)
        else:
            setattr(sys, name, value)
    sys.executable = executable


def test_source_run_is_not_frozen() -> None:
    assert app_paths.is_frozen() is False


def test_app_root_in_source_run_contains_runtime_directory() -> None:
    """源码运行时应用根为仓库根：其下应有 runtime/（运行时解析的第一候选）。"""
    root = app_paths.app_root()
    assert root.name == "视频剪辑工具2026071001" or (root / "JingXu.Workbench.sln").is_file()
    assert (root / "runtime").is_dir() or (root / "runtime").exists()


def test_package_root_in_source_run_points_to_python_project() -> None:
    """Python 项目目录含 pyproject.toml，供打包脚本定位。"""
    package = app_paths.package_root()
    assert (package / "pyproject.toml").is_file()
    assert (package / "jingxu").is_dir()


def test_search_roots_include_package_and_project_root() -> None:
    roots = app_paths.search_roots()
    package = Path(__file__).resolve().parents[1]
    assert package in roots
    assert app_paths.app_root() in roots


def test_search_roots_are_unique() -> None:
    roots = app_paths.search_roots()
    keys = [str(path).casefold() for path in roots]
    assert len(keys) == len(set(keys))


def test_frozen_app_root_points_to_executable_directory(tmp_path: Path, monkeypatch) -> None:
    fake_exe = tmp_path / "portable" / "炳恒快速混剪.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"stub")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    assert app_paths.is_frozen() is True
    assert app_paths.app_root() == fake_exe.parent


def test_frozen_search_roots_prioritise_executable_directory(tmp_path: Path, monkeypatch) -> None:
    """冻结后「与 exe 同级的 runtime/」必须排在候选第一位。"""
    fake_exe = tmp_path / "portable" / "app.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"stub")
    meipass = tmp_path / "_MEI123"
    meipass.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    roots = app_paths.search_roots()
    assert roots[0] == fake_exe.parent
    assert meipass in roots
    # 同级 runtime/ 能被找到——这是便携包的关键前提。
    assert (roots[0] / "runtime").parent == fake_exe.parent


def test_frozen_search_roots_do_not_walk_into_source_layout(
    tmp_path: Path, monkeypatch
) -> None:
    """冻结时不得上溯到源码布局：否则打包机上的仓库 runtime/ 会被误命中。

    否则便携包缺组件时会显示「就绪」，并暴露打包机的绝对路径。
    """
    fake_exe = tmp_path / "portable" / "app.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"stub")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    roots = app_paths.search_roots()
    # 只允许 exe 同级与上一级；repo/包目录不得出现。
    assert set(roots) == {fake_exe.parent, fake_exe.parent.parent}
    package_parents = set(Path(__file__).resolve().parents)
    assert not (set(roots) & package_parents)


def test_frozen_runtime_resolution_finds_sibling_runtime(tmp_path: Path, monkeypatch) -> None:
    """端到端：冻结时 runtime/ffmpeg 解析应命中 exe 同级的 runtime 目录。"""
    fake_exe = tmp_path / "portable" / "app.exe"
    ffmpeg = tmp_path / "portable" / "runtime" / "ffmpeg" / "ffmpeg.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"stub")
    ffmpeg.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.write_bytes(b"stub")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.delenv("JINGXU_RUNTIME_DIR", raising=False)

    from jingxu.infrastructure.runtime import _runtime_candidates

    candidates = _runtime_candidates("ffmpeg")
    assert ffmpeg in candidates
    # 同级 runtime 必须早于源码布局的候选。
    assert candidates.index(ffmpeg) == 0


def test_frozen_runtime_env_override_still_wins(tmp_path: Path, monkeypatch) -> None:
    """显式环境变量优先级不变（对齐 .NET「用户指定目录」高于内置）。"""
    fake_exe = tmp_path / "portable" / "app.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"stub")
    override = tmp_path / "custom-runtime"
    (override / "ffmpeg").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setenv("JINGXU_RUNTIME_DIR", str(override))

    from jingxu.infrastructure.runtime import _runtime_candidates

    candidates = _runtime_candidates("ffmpeg")
    assert candidates[0] == override / "ffmpeg" / "ffmpeg.exe"


def test_manifest_search_paths_include_frozen_executable_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """冻结后 runtime-manifest.json 应能从 exe 同级读到。"""
    fake_exe = tmp_path / "portable" / "app.exe"
    manifest = tmp_path / "portable" / "runtime-manifest.json"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"stub")
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.delenv("JINGXU_MANIFEST_PATH", raising=False)

    from jingxu.infrastructure.runtime_manifest import manifest_search_paths

    assert manifest in manifest_search_paths()


def test_frozen_component_resolution_stays_inside_portable_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """端到端：便携目录只放 ffmpeg 时，其余组件必须如实报缺失。

    这是防止「命中打包机仓库 runtime/」的回归防线。
    """
    import json

    from jingxu.infrastructure.runtime_manifest import (
        load_manifest,
        resolve_component_path,
    )

    portable = tmp_path / "portable"
    ffmpeg_dir = portable / "runtime" / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        (ffmpeg_dir / name).write_bytes(b"stub")
    # 便携包内的清单（只声明必需组件，避免测试依赖仓库清单内容）。
    (portable / "runtime-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "components": [
                    {
                        "kind": "Ffmpeg",
                        "displayName": "FFmpeg",
                        "relativePath": "ffmpeg/ffmpeg.exe",
                        "required": True,
                        "sha256": "0" * 64,
                        "licenseId": "GPL-3.0-or-later",
                        "sourceUrl": "https://ffmpeg.org",
                        "sourceCodeUrl": "https://github.com/FFmpeg/FFmpeg",
                    },
                    {
                        "kind": "Tesseract",
                        "displayName": "Tesseract OCR",
                        "relativePath": "tesseract/tesseract.exe",
                        "required": False,
                        "sha256": "0" * 64,
                        "licenseId": "Apache-2.0",
                        "sourceUrl": "https://github.com/tesseract-ocr/tesseract",
                        "sourceCodeUrl": "https://github.com/tesseract-ocr/tesseract",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    exe = portable / "app.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.delenv("JINGXU_RUNTIME_DIR", raising=False)

    components = {component.kind: component for component in load_manifest().components}
    ffmpeg_path, _ = resolve_component_path(components["Ffmpeg"])
    tesseract_path, _ = resolve_component_path(components["Tesseract"])

    assert ffmpeg_path is not None
    assert str(ffmpeg_path).startswith(str(portable))
    assert tesseract_path is None, "不应命中便携目录之外的 tesseract"


def test_spider_directory_found_next_to_frozen_executable(tmp_path: Path, monkeypatch) -> None:
    """冻结后选品爬虫应能在 exe 同级 runtime/spider 找到。"""
    from jingxu.infrastructure.spider import spider_directory

    fake_exe = tmp_path / "portable" / "app.exe"
    spider = tmp_path / "portable" / "runtime" / "spider"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"stub")
    spider.mkdir(parents=True)
    (spider / "cli.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.delenv("JINGXU_SPIDER_DIR", raising=False)

    assert spider_directory() == spider


# ── 报告文件（打包发布验收依赖）────────────────────────────────────────────


def test_parse_args_accepts_report_file() -> None:
    from jingxu.__main__ import _parse_args

    args = _parse_args(["--self-test", "--report-file", "out.json"])
    assert args.self_test is True
    assert args.report_file == "out.json"


def test_parse_args_report_file_defaults_to_none() -> None:
    from jingxu.__main__ import _parse_args

    assert _parse_args(["--self-test"]).report_file is None


def test_emit_report_writes_utf8_file(tmp_path: Path) -> None:
    """报告必须写文件且在 stdout 不可用时仍然成功。"""
    from jingxu.__main__ import _emit_report

    target = tmp_path / "report.json"
    _emit_report('{"消息":"中文"}', str(target))

    assert target.read_text(encoding="utf-8") == '{"消息":"中文"}'


def test_emit_report_without_file_does_not_raise() -> None:
    from jingxu.__main__ import _emit_report

    _emit_report("{}", None)


def test_self_test_report_file_runs_end_to_end(tmp_path: Path) -> None:
    """真跑一次 --self-test --report-file，确认报告可被发布脚本解析。

    窗口模式（PyInstaller --windowed）下 stdout 不可靠，发布脚本完全依赖该
    文件；这里在源码模式下验证同一条路径。
    """
    import json
    import subprocess

    package_root = app_paths.package_root()
    report = tmp_path / "self-test.json"
    completed = subprocess.run(
        [sys.executable, "-m", "jingxu", "--self-test", "--report-file", str(report)],
        cwd=str(package_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )

    assert report.is_file(), completed.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert set(payload) >= {"success", "manifestValid", "components", "missingRequired", "window"}
    # 报告与退出码必须一致。
    assert payload["success"] == (completed.returncode == 0)
