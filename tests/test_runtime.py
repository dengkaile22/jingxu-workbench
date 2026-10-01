"""运行时定位与 ffprobe 解析测试。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import jingxu.infrastructure.runtime as runtime_module
from jingxu.infrastructure.ffprobe import ProbeError, parse_probe_payload
from jingxu.infrastructure.runtime import ToolNotFoundError, find_tool, require_tool

TOOL_NAME = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def _stub_runtime(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    (root / "ffmpeg").mkdir(parents=True)
    executable = root / "ffmpeg" / TOOL_NAME
    executable.write_text("stub", encoding="utf-8")
    return root


def test_find_tool_prefers_configured_runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _stub_runtime(tmp_path)
    monkeypatch.setenv("JINGXU_RUNTIME_DIR", str(root))
    monkeypatch.setattr(runtime_module, "_search_roots", lambda: [])

    assert find_tool("ffmpeg") == root / "ffmpeg" / TOOL_NAME


def test_find_tool_falls_back_to_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JINGXU_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(runtime_module, "_search_roots", lambda: [])
    fake = tmp_path / TOOL_NAME
    fake.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: str(fake) if name == "ffmpeg" else None)

    assert find_tool("ffmpeg") == fake


def test_require_tool_raises_with_actionable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JINGXU_RUNTIME_DIR", "Z:/definitely-missing")
    monkeypatch.setattr(runtime_module, "_search_roots", lambda: [])
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(ToolNotFoundError, match="runtime/ffmpeg"):
        require_tool("ffmpeg")


def test_parse_probe_payload_reads_video_and_audio(tmp_path: Path) -> None:
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "avg_frame_rate": "30000/1001"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "12.345"},
    }

    asset = parse_probe_payload(payload, Path("sample.mp4"))

    assert asset.width == 1080
    assert asset.height == 1920
    assert asset.fps == pytest.approx(29.97)
    assert asset.duration == pytest.approx(12.345)
    assert asset.has_audio is True
    assert asset.audio_codec == "aac"


def test_parse_probe_payload_requires_video_stream() -> None:
    with pytest.raises(ProbeError, match="缺少视频流"):
        parse_probe_payload({"streams": [{"codec_type": "audio"}]}, Path("audio.m4a"))
