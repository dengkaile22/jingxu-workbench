"""无损直拷：阻止条件、concat 列表、命令形状与执行路径测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.application.stream_copy import stream_copy_blockers, stream_copy_eligible
from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import (
    BgmSettings,
    OutputResolutionPreset,
    OutputVideoSettings,
    RenderRequest,
    RenderSettings,
    VariationSettings,
)
from jingxu.domain.splitscreen import SplitMode, SplitScreenSpec
from jingxu.domain.subtitles import SubtitleBurnSpec, SubtitleCue, SubtitleRemovalSpec
from jingxu.infrastructure import ffmpeg_runner
from jingxu.infrastructure.ffmpeg_runner import (
    build_stream_copy_command,
    run_render,
    write_concat_list,
)

CANVAS = RenderSettings(width=640, height=360, fps=30)


def _request(
    *assets,
    settings: RenderSettings | None = None,
    output_path: Path | None = None,
    **overrides,
) -> RenderRequest:
    canonical = assets or (make_asset("a.mp4", width=640, height=360, fps=30),)
    return RenderRequest(
        name="直拷",
        plan=CompositionPlan(assets=tuple(canonical), mode=OrderMode.SEQUENTIAL),
        settings=settings or CANVAS,
        output_path=output_path or Path("out") / "成片.mp4",
        **overrides,
    )


def test_stream_copy_eligible_happy_path() -> None:
    request = _request()
    assert stream_copy_blockers(request) == ()
    assert stream_copy_eligible(request) is True


CASES = [
    (lambda: _request(split=SplitScreenSpec(mode=SplitMode.DOUBLE_H, same_source=True)), "分屏"),
    (lambda: _request(layers=(LayerSpec(kind=LayerKind.STICKER, source=Path("s.png")),)), "图层"),
    (
        lambda: _request(
            settings=RenderSettings(width=640, height=360, fps=30, variation=VariationSettings())
        ),
        "差异化",
    ),
    (lambda: _request(bgm=BgmSettings(path=Path("bgm.mp3"))), "背景音乐"),
    (
        lambda: _request(subtitles=SubtitleBurnSpec(cues=(SubtitleCue(0.0, 1.0, "你好"),))),
        "字幕",
    ),
    (lambda: _request(removal=SubtitleRemovalSpec()), "硬字幕"),
    (
        lambda: _request(
            settings=RenderSettings(
                width=640,
                height=360,
                fps=30,
                output_video=OutputVideoSettings(resolution=OutputResolutionPreset.P720),
            )
        ),
        "分辨率",
    ),
    (
        lambda: _request(settings=RenderSettings(width=640, height=360, fps=30, main_volume_percent=80)),
        "音量",
    ),
    (
        lambda: _request(
            make_asset("a.mp4", width=640, height=360, fps=30),
            make_asset("b.mp4", width=1280, height=720, fps=30),
        ),
        "不一致",
    ),
    (
        lambda: _request(
            make_asset("a.mp4", width=640, height=360, fps=30),
            make_asset("b.mp4", width=640, height=360, fps=25),
        ),
        "不一致",
    ),
    (
        lambda: _request(
            make_asset("a.mp4", width=640, height=360, fps=30),
            replace(
                make_asset("b.mp4", width=640, height=360, fps=30),
                video_codec="hevc",
            ),
        ),
        "不一致",
    ),
    (lambda: _request(settings=RenderSettings(width=720, height=360, fps=30)), "画幅"),
    (lambda: _request(settings=RenderSettings(width=640, height=360, fps=25)), "帧率"),
]


@pytest.mark.parametrize(("build", "fragment"), CASES)
def test_stream_copy_blockers_truth_table(build, fragment: str) -> None:
    blockers = stream_copy_blockers(build())

    assert len(blockers) == 1
    assert fragment in blockers[0]
    assert stream_copy_eligible(build()) is False


def test_disabled_layer_does_not_block_copy() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), enabled=False)
    assert stream_copy_blockers(_request(layers=(layer,))) == ()


def test_write_concat_list_escapes_quotes_and_backslashes(tmp_path: Path) -> None:
    assets = (
        make_asset("带'引号.mp4"),
        replace(make_asset("b.mp4"), path=Path(r"D:\videos\b.mp4")),
    )
    output = write_concat_list(tmp_path / "nested" / "concat.txt", assets)

    assert output.is_file()
    assert output.read_text(encoding="utf-8").splitlines() == [
        "file 'materials/带'\\''引号.mp4'",
        "file 'D:/videos/b.mp4'",
    ]


def test_build_stream_copy_command_shape(tmp_path: Path) -> None:
    request = _request()
    command = build_stream_copy_command(
        Path("ffmpeg"),
        request,
        tmp_path / "concat.txt",
        tmp_path / "out.mp4",
    )

    assert command == [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(tmp_path / "concat.txt"),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(tmp_path / "out.mp4"),
    ]


class _FakeProcess:
    """假 FFmpeg 进程：stdout 输出进度，wait 时按命令尾参创建输出文件。

    必须实现上下文管理器协议——``subprocess.run`` 会以 ``with Popen(...)`` 使用
    进程对象；缺少 ``__exit__`` 时任何真实 ``subprocess.run`` 调用都会抛
    ``TypeError``（曾被误当成跨测试竞态）。
    """

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.stdout = iter(["frame=12\n", "out_time_us=2000000\n", "progress=end\n"])
        self.stderr = iter(["stub stderr\n"])
        self.returncode = 0

    def __enter__(self) -> "_FakeProcess":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        self.stdout = iter(())
        self.stderr = iter(())
        return False

    def wait(self, timeout: float | None = None) -> int:
        Path(self.command[-1]).write_bytes(b"fake mp4")
        return 0

    def poll(self) -> int:
        return 0

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass

    def communicate(self, input=None, timeout=None):  # noqa: ANN001
        return "", "stub stderr\n"


def test_run_render_stream_copy_executes_concat_command(tmp_path: Path, monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_popen(command, **kwargs):  # noqa: ANN001
        captured.append(list(command))
        return _FakeProcess(list(command))

    monkeypatch.setattr(ffmpeg_runner.subprocess, "Popen", fake_popen)

    request = _request(
        make_asset("a.mp4", duration=1.0, width=640, height=360, fps=30),
        make_asset("b.mp4", duration=1.0, width=640, height=360, fps=30),
        settings=RenderSettings(width=640, height=360, fps=30, stream_copy=True),
        output_path=tmp_path / "成片.mp4",
    )
    progresses = []

    output = run_render(Path("ffmpeg"), request, on_progress=progresses.append, temp_dir=tmp_path)

    assert output == request.output_path
    assert output.read_bytes() == b"fake mp4"
    assert not list(tmp_path.glob("*.part.mp4"))
    assert len(captured) == 1

    command = captured[0]
    assert command[command.index("-f") + 1] == "concat"
    assert command[command.index("-safe") + 1] == "0"
    assert command[command.index("-c") + 1] == "copy"
    assert "-filter_complex_script" not in command
    concat_path = Path(command[command.index("-i") + 1])
    assert concat_path.name == "concat.txt"
    assert progresses and progresses[-1].percent == pytest.approx(100.0)
    assert progresses[-1].speed == "end"


class _FakeRegistry:
    def resolve(self, mode):  # noqa: ANN001
        return ffmpeg_runner.CPU_ENCODER


class _FakeProcessingSelector:
    """返回软件处理计划，避免测试触发真实 GPU 探测。"""

    def select(self, ffmpeg, mode, encoder=None):  # noqa: ANN001
        return ffmpeg_runner.SOFTWARE_PLAN

    def remember_hardware_failure(self, encoder_name: str) -> None:
        pass

    def reset_probe(self, ffmpeg=None) -> None:  # noqa: ANN001
        pass


def test_run_render_falls_back_to_transcode_when_blocked(tmp_path: Path, monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_popen(command, **kwargs):  # noqa: ANN001
        captured.append(list(command))
        return _FakeProcess(list(command))

    monkeypatch.setattr(ffmpeg_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ffmpeg_runner, "default_registry", lambda path: _FakeRegistry())
    monkeypatch.setattr(
        ffmpeg_runner, "default_processing_selector", lambda path: _FakeProcessingSelector()
    )

    request = _request(
        settings=RenderSettings(
            width=640,
            height=360,
            fps=30,
            stream_copy=True,
            output_video=OutputVideoSettings(resolution=OutputResolutionPreset.P480),
        ),
        output_path=tmp_path / "回退.mp4",
    )
    output = run_render(Path("ffmpeg"), request, temp_dir=tmp_path)

    assert output.is_file()
    assert "-filter_complex_script" in captured[0]
    assert captured[0][captured[0].index("-c:v") + 1] == "libx264"
