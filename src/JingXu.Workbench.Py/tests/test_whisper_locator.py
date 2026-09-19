"""Whisper 组件定位测试（占位文件识别）。"""

from __future__ import annotations

from pathlib import Path

import pytest

import jingxu.infrastructure.runtime as runtime_module
import jingxu.infrastructure.whisper as whisper_module
from jingxu.infrastructure.whisper import (
    MIN_CLI_BYTES,
    MIN_MODEL_BYTES,
    find_whisper,
    require_whisper,
)


def _build_runtime(root: Path, *, cli_bytes: int, model_bytes: int) -> Path:
    whisper_dir = root / "runtime" / "whisper"
    (whisper_dir / "models").mkdir(parents=True)
    executable = "whisper-cli.exe" if runtime_module.os.name == "nt" else "whisper-cli"
    (whisper_dir / executable).write_bytes(b"\0" * cli_bytes)
    (whisper_dir / "models" / "ggml-base.bin").write_bytes(b"\0" * model_bytes)
    return whisper_dir


def test_find_whisper_rejects_publish_stubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _build_runtime(tmp_path, cli_bytes=1, model_bytes=1)
    monkeypatch.setattr(runtime_module, "_search_roots", lambda: [tmp_path])
    monkeypatch.setattr(whisper_module.shutil, "which", lambda name: None)

    assert find_whisper() is None


def test_find_whisper_accepts_real_sized_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    whisper_dir = _build_runtime(tmp_path, cli_bytes=MIN_CLI_BYTES, model_bytes=MIN_MODEL_BYTES)
    monkeypatch.setattr(runtime_module, "_search_roots", lambda: [tmp_path])

    runtime = find_whisper()

    assert runtime is not None
    assert runtime.cli.parent == whisper_dir
    assert runtime.model.name == "ggml-base.bin"


def test_require_whisper_message_mentions_runtime_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module, "_search_roots", lambda: [tmp_path])
    monkeypatch.setattr(whisper_module.shutil, "which", lambda name: None)

    with pytest.raises(FileNotFoundError, match="runtime/whisper"):
        require_whisper()
