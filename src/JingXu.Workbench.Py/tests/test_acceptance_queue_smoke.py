"""封版验收：走**真实渲染队列**的端到端 smoke（对齐 .NET 队列状态机语义）。

已有集成测试（``test_pipeline_integration.py``）验证的是命令级编译与产出，
本文件补的是**队列级**链路：

    入队 → 排队 → 准备 → 渲染（进度上报）→ 收尾 → 完成

覆盖四种真实配置并行入队：顺序拼接 / 随机批量 / 自定义序号多任务 / 四屏+蒙版，
并核对：
* 每个任务都走到 ``COMPLETED``，输出文件非空；
* 用 ffprobe 复核成片分辨率与时长确实符合设置（不是"生成了就算过"）；
* 进度回调真的上报过（否则界面进度条永远不会动）；
* 失败任务会在输出目录留下 ``.jingxu-logs/<任务ID>/`` 诊断归档。

真机依赖 FFmpeg/FFprobe；缺组件时整文件跳过，不伪装成通过。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jingxu.application.composition_service import (  # noqa: E402
    CompositionDraft,
    build_requests,
)
from jingxu.domain.composition import OrderMode  # noqa: E402
from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.domain.render import RenderSettings  # noqa: E402
from jingxu.infrastructure.ffprobe import probe_media  # noqa: E402
from jingxu.infrastructure.queue import JobState, RenderQueue  # noqa: E402
from jingxu.infrastructure.runtime import find_tool  # noqa: E402

pytestmark = pytest.mark.integration

RENDER_TIMEOUT_SECONDS = 240.0
# 输出画幅：与素材不同，才能验证"画幅适配真的生效"
OUTPUT_WIDTH, OUTPUT_HEIGHT = 270, 480


@pytest.fixture(scope="module")
def ffmpeg() -> Path:
    tool = find_tool("ffmpeg")
    if tool is None:
        pytest.skip("本机没有 FFmpeg")
    return tool


@pytest.fixture(scope="module")
def ffprobe() -> Path:
    tool = find_tool("ffprobe")
    if tool is None:
        pytest.skip("本机没有 FFprobe")
    return tool


@pytest.fixture(scope="module")
def media(ffmpeg: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """造一组可辨别的测试素材（不同颜色/尺寸，便于核对拼接与适配）。"""
    root = tmp_path_factory.mktemp("acceptance-media")
    clips = []
    for index, color in enumerate(("red", "green", "blue")):
        target = root / f"clip{index + 1}.mp4"
        _make_clip(ffmpeg, target, color=color, size="320x240", seconds=1.0, with_audio=True)
        clips.append(target)
    mask = root / "mask.png"
    _make_image(ffmpeg, mask, color="yellow", size="160x160")
    return {"clips": clips, "mask": mask}


def _make_clip(
    ffmpeg: Path,
    target: Path,
    *,
    color: str,
    size: str,
    seconds: float,
    with_audio: bool = False,
) -> None:
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={seconds}:r=25",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += ["-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac", "-shortest"]
    command += [str(target)]
    subprocess.run(command, check=True)


def _make_image(ffmpeg: Path, target: Path, *, color: str, size: str) -> None:
    subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={size}:d=1",
            "-frames:v", "1", str(target),
        ],
        check=True,
    )


def _wait_for_jobs(queue: RenderQueue, job_ids: list[str], timeout: float) -> list:
    """等到**指定的这些任务**都结束，返回它们的快照。

    按任务 ID 跟踪，而不是按输出路径或队列顺序：
    * 同一批次里不同配置可能生成同名输出（``unique_output_path`` 会补序号），
      按路径跟踪会数错；
    * 队列可能按顺序回收历史，不能假设"前 N 个"就是本批任务。
    """
    wanted = set(job_ids)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tracked = [job for job in queue.jobs if job.id in wanted]
        if len(tracked) == len(wanted) and all(job.state.is_finished for job in tracked):
            return tracked
        time.sleep(0.2)
    states = [f"{job.output_path.name}={job.state.value}" for job in queue.jobs]
    raise AssertionError(f"任务未在 {timeout:.0f}s 内结束：{states}")


def _enqueue_all(queue: RenderQueue, requests: list) -> list[str]:
    return [queue.enqueue(request).id for request in requests]


def _probe(ffprobe: Path, path: Path):
    return probe_media(path, ffprobe)


# ── 端到端：四种配置并行入队 ────────────────────────────────────────────────


def test_queue_end_to_end_renders_every_configuration(
    ffmpeg: Path,
    ffprobe: Path,
    media: dict[str, Path],
    tmp_path: Path,
) -> None:
    clips = media["clips"]
    mask = media["mask"]
    assets = [probe_media(clip, ffprobe) for clip in clips]
    output = tmp_path / "out"
    output.mkdir()

    settings = RenderSettings(width=OUTPUT_WIDTH, height=OUTPUT_HEIGHT, fps=25, crf=28, preset="ultrafast")
    mask_layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=mask,
        x_percent=50.0,
        y_percent=26.0,
        width_percent=40.0,
        height_percent=30.0,
        opacity=0.5,
    )

    drafts = {
        "顺序拼接": CompositionDraft(mode=OrderMode.SEQUENTIAL, settings=settings),
        "随机批量": CompositionDraft(
            mode=OrderMode.RANDOM, seed=7, batch_count=2, settings=settings
        ),
        "自定义序号": CompositionDraft(
            mode=OrderMode.CUSTOM, sequence_text="312", settings=settings
        ),
        "四屏加蒙版": CompositionDraft(
            mode=OrderMode.SEQUENTIAL,
            settings=settings,
            layers=(mask_layer,),
            split=None,
        ),
    }

    queue = RenderQueue(ffmpeg)
    progress_seen: dict[str, float] = {}
    queue.add_listener(lambda event, job: progress_seen.setdefault(job.id, job.percent))
    queue.start()
    try:
        requests = []
        # 每次 build_requests 都要把"已分配但还没落盘"的路径带上，
        # 否则不同配置会算到同一个文件名而互相覆盖（壳层同样传 reserved_paths）。
        reserved: list[Path] = []
        for name, draft in drafts.items():
            built = build_requests(
                assets=assets,
                draft=draft,
                output_directory=output,
                start_index=len(requests) + 1,
                reserved_paths=reserved,
            )
            requests.extend(built)
            reserved.extend(request.output_path for request in built)
        job_ids = _enqueue_all(queue, requests)

        finished = _wait_for_jobs(queue, job_ids, RENDER_TIMEOUT_SECONDS)

        failed = [job for job in finished if job.state is not JobState.COMPLETED]
        assert failed == [], (
            "存在未完成的任务："
            + "; ".join(f"{job.display_name}={job.state.value}({job.message})" for job in failed)
        )

        # 每个成片都要真的落到磁盘、非空、且分辨率/时长符合设置
        produced = sorted(output.glob("*.mp4"))
        assert len(produced) == len(requests), f"产出文件数不符：{len(produced)} != {len(requests)}"

        for path in produced:
            assert path.stat().st_size > 0, f"{path.name} 是空文件"
            info = _probe(ffprobe, path)
            assert (info.width, info.height) == (OUTPUT_WIDTH, OUTPUT_HEIGHT), (
                f"{path.name} 分辨率不符：{info.width}x{info.height}"
            )
            assert info.duration > 0.4, f"{path.name} 时长异常：{info.duration}"

        # 进度回调必须真的上报过，否则界面进度条永远不动
        assert progress_seen, "整个批次没有收到任何进度回调"
    finally:
        queue.stop()


def test_failed_job_archives_diagnostics(ffmpeg: Path, media: dict[str, Path], tmp_path: Path) -> None:
    """失败任务要在输出目录留下 ``.jingxu-logs/<任务ID>/`` 诊断归档。

    用一条必然失败的请求触发（源文件不存在），核对归档确实生成。
    """
    output = tmp_path / "out-fail"
    output.mkdir()
    missing = tmp_path / "does-not-exist.mp4"

    from jingxu.domain.composition import CompositionPlan  # noqa: PLC0415
    from jingxu.domain.media import MediaAsset  # noqa: PLC0415
    from jingxu.domain.render import RenderRequest  # noqa: PLC0415

    ghost = MediaAsset(
        path=missing, duration=1.0, width=320, height=240, fps=25.0, has_audio=False
    )
    request = RenderRequest(
        name="必然失败",
        plan=CompositionPlan(assets=(ghost,), mode=OrderMode.SEQUENTIAL),
        settings=RenderSettings(width=OUTPUT_WIDTH, height=OUTPUT_HEIGHT, fps=25),
        output_path=output / "broken.mp4",
    )

    queue = RenderQueue(ffmpeg)
    queue.start()
    try:
        job = queue.enqueue(request)
        finished = _wait_for_jobs(queue, [job.id], RENDER_TIMEOUT_SECONDS)
        final = finished[0]
        assert final.state is JobState.FAILED, f"该任务本应失败，实际 {final.state.value}"

        logs = output / ".jingxu-logs"
        assert logs.is_dir(), "失败任务没有生成 .jingxu-logs 归档目录"
        archived = list(logs.iterdir())
        assert archived, "归档目录为空"
        assert any(item.name == job.id[:8] or job.id.startswith(item.name) for item in archived), (
            f"归档目录里没有该任务：{[item.name for item in archived]}"
        )
    finally:
        queue.stop()


def test_queue_concurrency_setting_is_respected(ffmpeg: Path, media: dict[str, Path], tmp_path: Path) -> None:
    """并发设置必须生效（1 与 2 都要能跑完，不能因并发限制而卡死）。"""
    clips = media["clips"]
    output = tmp_path / "out-concurrency"
    output.mkdir()
    settings = RenderSettings(width=OUTPUT_WIDTH, height=OUTPUT_HEIGHT, fps=25, crf=30, preset="ultrafast")
    draft = CompositionDraft(mode=OrderMode.RANDOM, seed=3, batch_count=2, settings=settings)
    assets = [probe_media(clips[0], find_tool("ffprobe"))]

    for concurrency in (1, 2):
        queue = RenderQueue(ffmpeg)
        queue.set_max_concurrency(concurrency)
        queue.start()
        try:
            requests = build_requests(assets=assets, draft=draft, output_directory=output)
            job_ids = _enqueue_all(queue, requests)
            finished = _wait_for_jobs(queue, job_ids, RENDER_TIMEOUT_SECONDS)
            states = [job.state for job in finished]
            assert all(state is JobState.COMPLETED for state in states), (
                f"并发 {concurrency} 下有任务未完成：{[s.value for s in states]}"
            )
        finally:
            queue.stop()
