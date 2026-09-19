"""单帧合成预览：命令形状、滤镜脚本片段与执行异常测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import RenderSettings
from jingxu.infrastructure.frame_preview import (
    FramePreviewError,
    composite_frame_command,
    render_composite_frame,
)

SETTINGS = RenderSettings(width=1080, height=1920, fps=30)


def _layers() -> tuple[LayerSpec, LayerSpec]:
    return (
        LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.mp4")),
        LayerSpec(kind=LayerKind.STICKER, source=Path("sticker.png")),
    )


def test_command_shape_loops_inputs_and_maps_single_frame(tmp_path: Path) -> None:
    script = tmp_path / "preview.filter"
    command = composite_frame_command(
        Path("ffmpeg"),
        make_asset("a.mp4"),
        _layers(),
        SETTINGS,
        script,
        tmp_path / "preview.jpg",
    )

    assert command[:4] == ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    assert command.count("-i") == 3
    assert command.index("-stream_loop") < command.index("-loop")
    assert command[command.index("-stream_loop") + 1] == "-1"
    assert command[command.index("-loop") + 1] == "1"
    assert command[command.index("-filter_complex_script") + 1] == str(script)
    assert command[command.index("-map") + 1] == "[vout]"
    assert command[command.index("-frames:v") + 1] == "1"
    assert command[command.index("-q:v") + 1] == "3"
    assert command[-1].endswith(".jpg")
    assert "-ss" not in command
    assert script.is_file()


def test_command_seek_precedes_base_input(tmp_path: Path) -> None:
    command = composite_frame_command(
        Path("ffmpeg"),
        make_asset("a.mp4"),
        (),
        SETTINGS,
        tmp_path / "preview.filter",
        tmp_path / "preview.jpg",
        at_seconds=0.5,
    )

    assert command[command.index("-ss") + 1] == "0.500"
    assert command.index("-ss") < command.index("-i")


def test_script_applies_height_limit_and_feather(tmp_path: Path) -> None:
    """height_percent 与 feather 经真实叠层引擎写入滤镜脚本。"""
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.png"),
        height_percent=50.0,
        feather=0.4,
    )
    script = tmp_path / "preview.filter"
    composite_frame_command(
        Path("ffmpeg"),
        make_asset("a.mp4"),
        (layer,),
        SETTINGS,
        script,
        tmp_path / "preview.jpg",
    )

    content = script.read_text(encoding="utf-8")
    assert "min(ih,960)" in content
    assert "alphaextract" in content
    assert "alphamerge" in content
    assert "gblur=sigma=2" in content


def test_script_is_video_only_even_when_base_has_audio(tmp_path: Path) -> None:
    """预览只输出图片：脚本不得包含未映射的音频输出（FFmpeg 会报未连接）。"""
    script = tmp_path / "preview.filter"
    composite_frame_command(
        Path("ffmpeg"),
        make_asset("a.mp4", has_audio=True),
        _layers(),
        SETTINGS,
        script,
        tmp_path / "preview.jpg",
    )

    content = script.read_text(encoding="utf-8")
    assert "[aout]" not in content
    assert "aformat" not in content
    assert "anull" not in content
    assert "[vout]" in content


def test_render_creates_output_and_cleans_script(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        captured["command"] = command
        captured["kwargs"] = kwargs
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = tmp_path / "preview.jpg"

    result = render_composite_frame(Path("ffmpeg"), make_asset("a.mp4"), _layers(), SETTINGS, output)

    assert result == output
    assert output.read_bytes() == b"jpeg"
    command = captured["command"]
    script_path = Path(command[command.index("-filter_complex_script") + 1])
    assert script_path.parent == tmp_path
    assert script_path.exists() is False
    assert captured["kwargs"]["timeout"] == 60.0


def test_render_raises_on_nonzero_exit_and_cleans_script(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    scripts: list[Path] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        scripts.append(Path(command[command.index("-filter_complex_script") + 1]))
        return subprocess.CompletedProcess(command, 1, b"", b"boom\nError opening file")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FramePreviewError) as error:
        render_composite_frame(
            Path("ffmpeg"),
            make_asset("a.mp4"),
            _layers(),
            SETTINGS,
            tmp_path / "preview.jpg",
        )

    assert "Error opening file" in str(error.value)
    assert scripts and scripts[0].exists() is False


def test_render_raises_on_timeout_and_cleans_script(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    scripts: list[Path] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        scripts.append(Path(command[command.index("-filter_complex_script") + 1]))
        raise subprocess.TimeoutExpired(command, 1.0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FramePreviewError, match="超时"):
        render_composite_frame(
            Path("ffmpeg"),
            make_asset("a.mp4"),
            _layers(),
            SETTINGS,
            tmp_path / "preview.jpg",
        )

    assert scripts and scripts[0].exists() is False


def test_render_raises_when_output_missing(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FramePreviewError, match="未生成"):
        render_composite_frame(
            Path("ffmpeg"),
            make_asset("a.mp4"),
            (),
            SETTINGS,
            tmp_path / "preview.jpg",
        )
