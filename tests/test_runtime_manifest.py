"""运行时清单校验、逐组件诊断与崩溃日志测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jingxu.infrastructure.diagnostics import (
    cleanup_startup_orphans,
    crash_log_path,
    install_crash_logging,
    log_exception,
)
from jingxu.infrastructure.runtime_manifest import (
    diagnose_components,
    load_manifest,
    missing_required,
    sha256_file,
    verify_sha256,
)


def _manifest_payload(*, sha256: str = "ab" * 32, relative: str = "ffmpeg/jingxu-test-only.exe") -> dict:
    return {
        "schemaVersion": 1,
        "components": [
            {
                "kind": "Ffmpeg",
                "displayName": "FFmpeg",
                "relativePath": relative,
                "required": True,
                "versionArguments": ["-version"],
                "sha256": sha256,
                "licenseId": "GPL-3.0-or-later",
                "sourceUrl": "https://ffmpeg.org",
                "sourceCodeUrl": "https://github.com/FFmpeg/FFmpeg",
            }
        ],
    }


class TestManifestValidation:
    def test_valid_manifest(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime-manifest.json"
        path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")

        result = load_manifest(path)

        assert result.is_valid
        assert result.schema_version == 1
        assert result.components[0].kind == "Ffmpeg"
        assert result.components[0].required is True

    def test_missing_fields_reported(self, tmp_path: Path) -> None:
        payload = _manifest_payload()
        del payload["components"][0]["licenseId"]
        path = tmp_path / "runtime-manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        result = load_manifest(path)

        assert not result.is_valid
        assert any("licenseId" in issue for issue in result.issues)

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime-manifest.json"
        path.write_text(json.dumps(_manifest_payload(relative="C:/abs/ffmpeg.exe")), encoding="utf-8")

        result = load_manifest(path)
        assert not result.is_valid
        assert any("相对路径" in issue for issue in result.issues)

    def test_bad_sha_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime-manifest.json"
        path.write_text(json.dumps(_manifest_payload(sha256="xyz")), encoding="utf-8")

        result = load_manifest(path)
        assert not result.is_valid
        assert any("sha256" in issue for issue in result.issues)

    def test_missing_manifest_file(self, tmp_path: Path) -> None:
        result = load_manifest(tmp_path / "nope.json")
        assert not result.is_valid
        assert result.issues


class TestComponentDiagnosis:
    def test_component_found_via_runtime_env(self, tmp_path: Path, monkeypatch) -> None:
        manifest_path = tmp_path / "runtime-manifest.json"
        manifest_path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")

        runtime_dir = tmp_path / "runtime"
        (runtime_dir / "ffmpeg").mkdir(parents=True)
        executable = runtime_dir / "ffmpeg" / "jingxu-test-only.exe"
        executable.write_bytes(b"stub")
        monkeypatch.setenv("JINGXU_RUNTIME_DIR", str(runtime_dir))

        manifest = load_manifest(manifest_path)
        statuses = diagnose_components(manifest)

        assert len(statuses) == 1
        status = statuses[0]
        assert status.is_available is True
        assert status.resolved_path == str(executable)
        assert "环境变量" in status.source
        assert missing_required(manifest, statuses) == []

    def test_missing_required_component(self, tmp_path: Path, monkeypatch) -> None:
        manifest_path = tmp_path / "runtime-manifest.json"
        manifest_path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")
        monkeypatch.setenv("JINGXU_RUNTIME_DIR", str(tmp_path / "empty"))

        manifest = load_manifest(manifest_path)
        statuses = diagnose_components(manifest)

        assert statuses[0].is_available is False
        assert statuses[0].is_required is True
        assert "runtime/" in statuses[0].suggested_action
        assert missing_required(manifest, statuses) == ["FFmpeg"]

    def test_optional_component_message_differs(self, tmp_path: Path, monkeypatch) -> None:
        payload = _manifest_payload()
        payload["components"][0]["required"] = False
        manifest_path = tmp_path / "runtime-manifest.json"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setenv("JINGXU_RUNTIME_DIR", str(tmp_path / "empty"))

        manifest = load_manifest(manifest_path)
        statuses = diagnose_components(manifest)

        assert statuses[0].is_available is False
        assert "可选" in statuses[0].message
        assert missing_required(manifest, statuses) == []

    def test_hash_verification(self, tmp_path: Path, monkeypatch) -> None:
        target = tmp_path / "file.bin"
        target.write_bytes(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()

        assert sha256_file(target) == expected
        ok, _ = verify_sha256(target, expected)
        assert ok is True
        bad, detail = verify_sha256(target, "11" * 32)
        assert bad is False and "不匹配" in detail

        placeholder, note = verify_sha256(target, "0" * 64)
        assert placeholder is True and "占位" in note

        monkeypatch.setenv("JINGXU_SKIP_HASH_VERIFY", "1")
        skipped, _ = verify_sha256(target, "11" * 32)
        assert skipped is True


class TestCrashLogging:
    def test_log_exception_appends_file(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))

        try:
            raise ValueError("模拟崩溃")
        except ValueError as error:
            path = log_exception(error, context="测试")

        assert path is not None
        assert path == crash_log_path()
        content = path.read_text(encoding="utf-8")
        assert "模拟崩溃" in content and "测试" in content

    def test_install_hooks_is_idempotent(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
        install_crash_logging()
        install_crash_logging()
        assert callable(__import__("sys").excepthook)


class TestStartupCleanup:
    def test_startup_cleanup_skips_fresh_temp_entries(self, tmp_path: Path) -> None:
        import os
        import time

        temp_root = tmp_path / "temp"
        temp_root.mkdir()
        fresh = temp_root / "jingxu-py-active"
        fresh.mkdir()
        (fresh / "work.txt").write_text("x", encoding="utf-8")

        stale = temp_root / "jingxu-py-stale"
        stale.mkdir()
        (stale / "old.txt").write_text("x", encoding="utf-8")
        old_time = time.time() - 3600
        os.utime(stale, (old_time, old_time))

        from jingxu.infrastructure.diagnostics import _cleanup_temp_entries

        deleted, _, skipped = _cleanup_temp_entries(temp_root, set(), min_age_seconds=600.0)

        assert deleted == 1
        assert skipped == 1
        assert fresh.exists() and not stale.exists()
