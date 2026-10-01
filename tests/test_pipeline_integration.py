"""真机端到端渲染测试：需要本机 FFmpeg/FFprobe。

运行：python -m pytest -m integration
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import (
    BgmSettings,
    CoverRequest,
    FitMode,
    OutputResolutionPreset,
    OutputVideoSettings,
    ProcessingMode,
    RenderRequest,
    RenderSettings,
    TransitionSettings,
    VariationSettings,
)
from jingxu.domain.splitscreen import SplitMode, SplitScreenSpec
from jingxu.domain.subtitles import (
    RemovalMode,
    SubtitleBurnSpec,
    SubtitleCue,
    SubtitleRemovalSpec,
    SubtitleStyle,
)
from jingxu.application.stream_copy import stream_copy_eligible
from jingxu.infrastructure.ffmpeg_runner import run_render
from jingxu.infrastructure.ffprobe import probe_media
from jingxu.infrastructure.frame_preview import render_composite_frame
from jingxu.infrastructure.runtime import find_tool

pytestmark = pytest.mark.integration


def _require_tools() -> tuple[Path, Path]:
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("本机未找到 FFmpeg/FFprobe，跳过真机渲染测试。")
    return ffmpeg, ffprobe


def _make_clip(
    ffmpeg: Path,
    path: Path,
    *,
    size: str,
    rate: int,
    seconds: float,
    with_audio: bool,
) -> None:
    command = [
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    command += ["-c:a", "aac", "-shortest"] if with_audio else ["-an"]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True)


def test_render_mixed_sources_into_single_canvas(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_tools()

    landscape = tmp_path / "横屏有声.mp4"
    portrait = tmp_path / "竖屏无声.mp4"
    _make_clip(ffmpeg, landscape, size="640x360", rate=30, seconds=1.2, with_audio=True)
    _make_clip(ffmpeg, portrait, size="720x1280", rate=25, seconds=0.8, with_audio=False)

    assets = [probe_media(landscape, ffprobe), probe_media(portrait, ffprobe)]
    assert assets[0].has_audio is True
    assert assets[1].has_audio is False
    assert assets[0].width == 640 and assets[1].height == 1280

    plan = CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL)
    request = RenderRequest(
        name="验收混剪",
        plan=plan,
        settings=RenderSettings(width=540, height=960, fps=30, crf=28, preset="ultrafast"),
        output_path=tmp_path / "成片.mp4",
    )

    progresses = []
    output = run_render(ffmpeg, request, on_progress=progresses.append)

    assert output.exists() and output.stat().st_size > 5_000
    assert not list(tmp_path.glob("*.part.mp4"))

    result = probe_media(output, ffprobe)
    assert result.width == 540 and result.height == 960
    assert result.fps == pytest.approx(30, abs=0.5)
    assert result.duration == pytest.approx(plan.total_duration, abs=0.6)
    assert result.has_audio is True
    assert progresses and progresses[-1].percent == 100.0


def test_render_with_bgm_cover_and_auto_encoder(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_tools()

    video = tmp_path / "素材.mp4"
    bgm = tmp_path / "bgm.m4a"
    _make_clip(ffmpeg, video, size="480x270", rate=30, seconds=1.0, with_audio=True)
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=220:duration=3", "-c:a", "aac", str(bgm)],
        check=True,
        capture_output=True,
    )

    asset = probe_media(video, ffprobe)
    plan = CompositionPlan(assets=(asset,), mode=OrderMode.SEQUENTIAL, seed=11)
    request = RenderRequest(
        name="BGM 验收",
        plan=plan,
        settings=RenderSettings(
            width=320,
            height=240,
            fps=24,
            crf=30,
            preset="ultrafast",
            processing=ProcessingMode.AUTO,
            fit_mode=FitMode.CROP,
            output_video=OutputVideoSettings(resolution=OutputResolutionPreset.P480),
            main_volume_percent=80,
            variation=VariationSettings(intensity=60),
        ),
        output_path=tmp_path / "成片.mp4",
        cover=CoverRequest(output_path=tmp_path / "封面.jpg", at_seconds=0.4),
        bgm=BgmSettings(path=bgm, volume_percent=25, fade_out_seconds=0.3),
    )

    output = run_render(ffmpeg, request)

    assert output.exists() and output.stat().st_size > 3_000
    cover = tmp_path / "封面.jpg"
    assert cover.exists() and cover.stat().st_size > 1_000

    result = probe_media(output, ffprobe)
    assert result.has_audio is True
    assert result.width == 640 and result.height == 480  # 导出兼容性按短边缩放
    assert result.duration == pytest.approx(plan.total_duration, abs=0.6)


def test_four_screen_with_feather_sticker_and_mask_render(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_tools()

    base_a = tmp_path / "base_a.mp4"
    base_b = tmp_path / "base_b.mp4"
    _make_clip(ffmpeg, base_a, size="640x360", rate=30, seconds=1.2, with_audio=True)
    _make_clip(ffmpeg, base_b, size="480x854", rate=24, seconds=0.8, with_audio=False)

    aux_paths = []
    for index, size in enumerate(("360x360", "480x270", "270x480")):
        aux = tmp_path / f"aux{index}.mp4"
        _make_clip(ffmpeg, aux, size=size, rate=30, seconds=1.0, with_audio=False)
        aux_paths.append(aux)

    sticker = tmp_path / "sticker.png"
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=red@0.6:s=200x200:d=1,format=rgba", "-frames:v", "1", str(sticker)],
        check=True,
        capture_output=True,
    )

    mask = tmp_path / "mask.mp4"
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=black:s=320x240:d=1.5,drawbox=x=80:y=60:w=160:h=120:color=white:t=fill",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(mask)],
        check=True,
        capture_output=True,
    )

    assets = [probe_media(base_a, ffprobe), probe_media(base_b, ffprobe)]
    plan = CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL)
    request = RenderRequest(
        name="分屏验收",
        plan=plan,
        settings=RenderSettings(width=540, height=960, fps=24, crf=30, preset="ultrafast"),
        output_path=tmp_path / "分屏成片.mp4",
        split=SplitScreenSpec(
            mode=SplitMode.FOUR,
            same_source=False,
            aux_paths=tuple(aux_paths),
            start_index=0,
            feather=True,
            feather_px=16,
        ),
        layers=(
            LayerSpec(
                kind=LayerKind.STICKER,
                source=sticker,
                start_seconds=0.2,
                end_seconds=1.0,
                x_percent=20,
                y_percent=20,
                width_percent=25,
            ),
            LayerSpec(
                kind=LayerKind.OVERLAY,
                source=mask,
                start_seconds=0.0,
                end_seconds=0.6,
                width_percent=50,
                remove_black=True,
                opacity=0.9,
            ),
        ),
        cover=CoverRequest(output_path=tmp_path / "分屏封面.jpg", at_seconds=0.3),
    )

    output = run_render(ffmpeg, request)

    assert output.exists() and output.stat().st_size > 5_000
    assert (tmp_path / "分屏封面.jpg").is_file()
    assert not list(tmp_path.glob("*.part.mp4"))

    result = probe_media(output, ffprobe)
    assert result.width == 540 and result.height == 960
    assert result.duration == pytest.approx(plan.total_duration, abs=0.7)
    assert result.has_audio is True

def _extract_frame(ffmpeg: Path, video: Path, moment: float, target: Path) -> None:
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{moment:.2f}",
         "-i", str(video), "-frames:v", "1", str(target)],
        check=True,
        capture_output=True,
    )


def _count_pixels(image_path: Path, predicate, *, x0: float, y0: float, x1: float, y1: float) -> int:
    """统计区域内满足条件的像素数（用于验证字幕/遮挡是否落位）。"""
    from PySide6.QtGui import QImage

    image = QImage(str(image_path))
    if image.isNull():
        return 0
    left, right = int(image.width() * x0), int(image.width() * x1)
    top, bottom = int(image.height() * y0), int(image.height() * y1)
    matched = 0
    for y in range(top, bottom, 2):
        for x in range(left, right, 2):
            color = image.pixelColor(x, y)
            if predicate(color.red(), color.green(), color.blue()):
                matched += 1
    return matched


def test_composite_frame_preview_renders_feathered_layer(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_tools()

    base = tmp_path / "preview_base.mp4"
    _make_clip(ffmpeg, base, size="320x240", rate=30, seconds=1.0, with_audio=True)
    mask = tmp_path / "preview_mask.png"
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=red@0.9:s=200x120:d=1", "-frames:v", "1", str(mask)],
        check=True,
        capture_output=True,
    )

    asset = probe_media(base, ffprobe)
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=mask,
        end_seconds=1.0,
        height_percent=60,
        feather=0.3,
        top_fade=0.2,
    )
    preview = tmp_path / "合成预览.jpg"
    render_composite_frame(
        ffmpeg,
        asset,
        (layer,),
        RenderSettings(width=320, height=240, fps=30),
        preview,
        at_seconds=0.5,
    )

    assert preview.exists() and preview.stat().st_size > 500
    from PySide6.QtGui import QImage

    image = QImage(str(preview))
    assert not image.isNull()
    assert image.width() == 320 and image.height() == 240


@pytest.mark.parametrize("feather_enabled", [False, True])
@pytest.mark.parametrize(
    ("placement", "top_channel", "bottom_channel"),
    [
        ("top", 2, 0),
        ("bottom", 0, 2),
    ],
)
def test_double_screen_preserves_both_halves(
    tmp_path: Path,
    feather_enabled: bool,
    placement: str,
    top_channel: int,
    bottom_channel: int,
) -> None:
    """上下双屏无论羽化与覆盖方向，都不能把任一半屏盖成黑色。"""
    from jingxu.domain.effects import (
        DoubleScreenClipSelection,
        DoubleScreenEffectPlan,
        DoubleScreenPlacement,
        DoubleScreenPlacementMode,
        DoubleScreenSourceMode,
    )

    ffmpeg, ffprobe = _require_tools()
    main_path = tmp_path / "main.mp4"
    aux_path = tmp_path / "aux.mp4"
    for source, color in ((main_path, "red"), (aux_path, "blue")):
        subprocess.run(
            [
                str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=128x128:r=12:d=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ],
            check=True,
            capture_output=True,
        )
    main, auxiliary = probe_media(main_path, ffprobe), probe_media(aux_path, ffprobe)
    plan = CompositionPlan(assets=(main,), mode=OrderMode.SEQUENTIAL, seed=1)
    effect = DoubleScreenEffectPlan(
        source_mode=DoubleScreenSourceMode.CURRENT_CLIP,
        placement_mode=(
            DoubleScreenPlacementMode.TOP if placement == "top" else DoubleScreenPlacementMode.BOTTOM
        ),
        feather_enabled=feather_enabled,
        feather_pixels=18,
        clip_selections=(
            DoubleScreenClipSelection(
                0,
                auxiliary,
                DoubleScreenPlacement.TOP if placement == "top" else DoubleScreenPlacement.BOTTOM,
            ),
        ),
    )
    output = tmp_path / "double-screen.mp4"
    run_render(
        ffmpeg,
        RenderRequest(
            name="双屏无羽化",
            plan=plan,
            settings=RenderSettings(width=128, height=128, fps=12, preset="ultrafast"),
            output_path=output,
            double_screen=effect,
        ),
    )
    frame = subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-ss", "0.2", "-i", str(output),
            "-frames:v", "1", "-vf", "format=rgb24", "-f", "rawvideo", "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    top = frame[(32 * 128 + 64) * 3 : (32 * 128 + 65) * 3]
    bottom = frame[(96 * 128 + 64) * 3 : (96 * 128 + 65) * 3]

    assert len(frame) == 128 * 128 * 3
    assert top[top_channel] > top[1] * 2 + 80, f"上屏颜色不正确，实际 RGB={tuple(top)}"
    assert bottom[bottom_channel] > bottom[1] * 2 + 80, f"下屏颜色不正确，实际 RGB={tuple(bottom)}"


def test_double_screen_and_boost_render(tmp_path: Path) -> None:
    """上下双屏（随机辅助素材 + 羽化）与主素材增强的真实渲染验收。"""
    from jingxu.domain.effects import (
        DoubleScreenEffectPlan,
        DoubleScreenPlacementMode,
        DoubleScreenSourceMode,
        MainMaterialBoostMode,
        MainMaterialBoostPlan,
    )

    ffmpeg, ffprobe = _require_tools()

    first = tmp_path / "clip_1.mp4"
    second = tmp_path / "clip_2.mp4"
    aux = tmp_path / "aux_9.mp4"
    _make_clip(ffmpeg, first, size="640x360", rate=30, seconds=1.0, with_audio=True)
    _make_clip(ffmpeg, second, size="640x360", rate=30, seconds=1.0, with_audio=True)
    _make_clip(ffmpeg, aux, size="360x640", rate=30, seconds=1.0, with_audio=False)

    assets = [probe_media(first, ffprobe), probe_media(second, ffprobe), probe_media(aux, ffprobe)]
    plan = CompositionPlan(assets=tuple(assets[:2]), mode=OrderMode.SEQUENTIAL, seed=42)
    effect = DoubleScreenEffectPlan(
        start_clip_index=1,
        source_mode=DoubleScreenSourceMode.RANDOM_CURRENT_FOLDER,
        placement_mode=DoubleScreenPlacementMode.RANDOM,
        feather_enabled=True,
        feather_pixels=48,
    ).materialize_for_plan(plan, assets, 0)
    boost = MainMaterialBoostPlan(
        enable_volume=True,
        volume_mode=MainMaterialBoostMode.FIXED,
        volume_min_percent=105,
        volume_max_percent=105,
        enable_scale=True,
        scale_mode=MainMaterialBoostMode.FIXED,
        scale_min_percent=105,
        scale_max_percent=105,
    ).materialize(plan.seed, len(plan.assets))

    from dataclasses import replace

    request = RenderRequest(
        name="双屏增强验收",
        plan=plan,
        settings=replace(
            RenderSettings(width=540, height=960, fps=30, crf=30, preset="ultrafast"),
            boost=boost,
        ),
        output_path=tmp_path / "双屏成片.mp4",
        double_screen=effect,
    )

    output = run_render(ffmpeg, request)

    assert output.exists() and output.stat().st_size > 5_000
    assert not list(tmp_path.glob("*.part.mp4"))

    result = probe_media(output, ffprobe)
    assert result.width == 540 and result.height == 960
    assert result.duration == pytest.approx(plan.total_duration, abs=0.6)
    assert result.has_audio is True


def test_double_screen_same_source_render(tmp_path: Path) -> None:
    """同源上下双屏（无外部素材）真实渲染验收，验证 split=2 与两半屏完整渲染。"""
    from jingxu.domain.effects import (
        DoubleScreenEffectPlan,
        DoubleScreenPlacementMode,
        DoubleScreenSourceMode,
    )

    ffmpeg, ffprobe = _require_tools()

    first = tmp_path / "clip_a.mp4"
    second = tmp_path / "clip_b.mp4"
    _make_clip(ffmpeg, first, size="640x360", rate=30, seconds=1.0, with_audio=True)
    _make_clip(ffmpeg, second, size="640x360", rate=30, seconds=1.0, with_audio=True)

    assets = [probe_media(first, ffprobe), probe_media(second, ffprobe)]
    plan = CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL, seed=42)
    effect = DoubleScreenEffectPlan(
        start_clip_index=1,
        source_mode=DoubleScreenSourceMode.CURRENT_CLIP,
        placement_mode=DoubleScreenPlacementMode.BOTTOM,
        feather_enabled=True,
        feather_pixels=32,
    ).materialize_for_plan(plan, [], 0)

    request = RenderRequest(
        name="同源双屏测试",
        plan=plan,
        settings=RenderSettings(
            width=540,
            height=960,
            fps=30,
            preset="ultrafast",
            crf=26,
        ),
        output_path=tmp_path / "同源双屏成片.mp4",
        double_screen=effect,
    )

    output = run_render(ffmpeg, request)
    assert output.exists() and output.stat().st_size > 5_000
    result = probe_media(output, ffprobe)
    assert result.width == 540 and result.height == 960
    assert result.duration == pytest.approx(plan.total_duration, abs=0.6)
    assert result.has_audio is True


def test_four_screen_feather_render(tmp_path: Path) -> None:
    """四屏（内联灰度羽化）真实渲染验收。"""
    from jingxu.domain.effects import FourScreenEffectPlan, FourScreenSourceMode

    ffmpeg, ffprobe = _require_tools()

    main = tmp_path / "main_1.mp4"
    aux = tmp_path / "aux_2.mp4"
    _make_clip(ffmpeg, main, size="640x360", rate=30, seconds=1.0, with_audio=True)
    _make_clip(ffmpeg, aux, size="360x640", rate=30, seconds=1.0, with_audio=False)

    assets = [probe_media(main, ffprobe), probe_media(aux, ffprobe)]
    plan = CompositionPlan(assets=(assets[0],), mode=OrderMode.SEQUENTIAL, seed=7)
    effect = FourScreenEffectPlan(
        start_clip_index=1,
        source_mode=FourScreenSourceMode.RANDOM_CURRENT_FOLDER,
        feather_enabled=True,
        feather_pixels=32,
    ).materialize_for_plan(plan, assets, 0)

    request = RenderRequest(
        name="四屏羽化验收",
        plan=plan,
        settings=RenderSettings(width=540, height=960, fps=30, crf=30, preset="ultrafast"),
        output_path=tmp_path / "四屏成片.mp4",
        four_screen=effect,
    )

    output = run_render(ffmpeg, request)

    assert output.exists() and output.stat().st_size > 5_000
    result = probe_media(output, ffprobe)
    assert result.width == 540 and result.height == 960
    assert result.duration == pytest.approx(plan.total_duration, abs=0.6)


def test_self_ghost_overlay_render(tmp_path: Path) -> None:
    """自叠影（从主画面分流）真实渲染验收。"""
    from jingxu.infrastructure.filter_graph import SELF_SOURCE

    ffmpeg, ffprobe = _require_tools()

    clip = tmp_path / "base.mp4"
    _make_clip(ffmpeg, clip, size="480x854", rate=30, seconds=1.2, with_audio=True)
    asset = probe_media(clip, ffprobe)
    plan = CompositionPlan(assets=(asset,), mode=OrderMode.SEQUENTIAL)

    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path(SELF_SOURCE),
        width_percent=90,
        height_percent=42,
        y_percent=26,
        opacity=0.28,
        top_fade=1.0,
        feather=0.28,
    )
    request = RenderRequest(
        name="自叠影验收",
        plan=plan,
        settings=RenderSettings(width=480, height=854, fps=30, crf=30, preset="ultrafast"),
        output_path=tmp_path / "自叠影.mp4",
        layers=(layer,),
    )

    output = run_render(ffmpeg, request)

    assert output.exists() and output.stat().st_size > 5_000
    result = probe_media(output, ffprobe)
    assert result.width == 480 and result.height == 854
    ffmpeg, ffprobe = _require_tools()

    first = tmp_path / "t1.mp4"
    second = tmp_path / "t2.mp4"
    _make_clip(ffmpeg, first, size="320x240", rate=30, seconds=1.0, with_audio=True)
    _make_clip(ffmpeg, second, size="320x240", rate=30, seconds=1.0, with_audio=True)
    assets = (probe_media(first, ffprobe), probe_media(second, ffprobe))

    plan = CompositionPlan(assets=assets, mode=OrderMode.SEQUENTIAL)
    request = RenderRequest(
        name="转场验收",
        plan=plan,
        settings=RenderSettings(
            width=320,
            height=240,
            fps=30,
            crf=30,
            preset="ultrafast",
            transition=TransitionSettings(enabled=True, duration_seconds=0.5),
        ),
        output_path=tmp_path / "转场成片.mp4",
    )

    assert request.total_duration == pytest.approx(1.5, abs=0.05)
    assert stream_copy_eligible(request) is False

    output = run_render(ffmpeg, request)
    result = probe_media(output, ffprobe)
    assert result.duration == pytest.approx(1.5, abs=0.3)
    assert not list(tmp_path.glob("*.part.mp4"))


def test_subtitle_burn_and_hard_subtitle_removal_render(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_tools()

    black = tmp_path / "黑底.mp4"
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=black:s=640x360:r=30:d=2", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", str(black)],
        check=True,
        capture_output=True,
    )

    asset = probe_media(black, ffprobe)
    plan = CompositionPlan(assets=(asset,), mode=OrderMode.SEQUENTIAL)
    settings = RenderSettings(width=640, height=360, fps=30, crf=30, preset="ultrafast")

    burned = tmp_path / "烧录.mp4"
    run_render(
        ffmpeg,
        RenderRequest(
            name="烧录",
            plan=plan,
            settings=settings,
            output_path=burned,
            subtitles=SubtitleBurnSpec(
                cues=(SubtitleCue(0.3, 1.6, "字幕烧录验证"),),
                style=SubtitleStyle(font_size=28, color="#FFFFFF", outline=2, margin_v=30),
            ),
        ),
    )

    burned_frame = tmp_path / "burned.png"
    _extract_frame(ffmpeg, burned, 0.8, burned_frame)
    bright = lambda r, g, b: r > 200 and g > 200 and b > 200  # noqa: E731
    assert _count_pixels(burned_frame, bright, x0=0.1, y0=0.7, x1=0.9, y1=1.0) > 20

    covered = tmp_path / "遮盖.mp4"
    run_render(
        ffmpeg,
        RenderRequest(
            name="遮盖",
            plan=plan,
            settings=settings,
            output_path=covered,
            removal=SubtitleRemovalSpec(
                mode=RemovalMode.COVER,
                x_percent=10,
                y_percent=70,
                width_percent=80,
                height_percent=25,
            ),
        ),
    )

    covered_frame = tmp_path / "covered.png"
    _extract_frame(ffmpeg, covered, 0.8, covered_frame)
    dark = lambda r, g, b: r < 25 and g < 25 and b < 25  # noqa: E731
    assert _count_pixels(covered_frame, dark, x0=0.15, y0=0.75, x1=0.85, y1=0.95) > 100


# ── 形状遮罩像素验收 ───────────────────────────────────────────────────────


def _make_solid(ffmpeg: Path, path: Path, *, color: str, size: str, seconds: float = 2.0) -> None:
    subprocess.run(
        [
            str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30",
            "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_half_masked_png(ffmpeg: Path, path: Path, *, size: int = 400) -> None:
    """生成「左半白、右半黑」的灰度遮罩 PNG。"""
    subprocess.run(
        [
            str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={size}x{size}",
            "-f", "lavfi", "-i", f"color=c=white:s={size // 2}x{size}",
            "-filter_complex", "[0:v][1:v]overlay=0:0", "-frames:v", "1", str(path),
        ],
        check=True,
        capture_output=True,
    )


def _red_fraction(ffmpeg: Path, video: Path, tmp_path: Path, name: str) -> float:
    """统计画面中「图层红」的像素占比（缩到 90x160 后逐像素判定）。"""
    frame = tmp_path / f"{name}.png"
    _extract_frame(ffmpeg, video, 1.0, frame)
    raw = tmp_path / f"{name}.raw"
    subprocess.run(
        [
            str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(frame),
            "-vf", "scale=90:160", "-pix_fmt", "rgb24", "-f", "rawvideo", str(raw),
        ],
        check=True,
        capture_output=True,
    )
    data = raw.read_bytes()
    width, height = 90, 160
    total = width * height
    red = 0
    for index in range(0, len(data), 3):
        if data[index] > 150 and data[index + 1] < 90 and data[index + 2] < 90:
            red += 1
    assert len(data) >= total * 3
    return red / total


def _shape_layer(source: Path, **overrides) -> LayerSpec:
    base = {
        "kind": LayerKind.OVERLAY,
        "source": source,
        "x_percent": 50.0,
        "y_percent": 50.0,
        "width_percent": 60.0,
        "height_percent": 60.0,
        "opacity": 1.0,
    }
    base.update(overrides)
    return LayerSpec(**base)


def _render_shape_case(
    ffmpeg: Path,
    ffprobe: Path,
    tmp_path: Path,
    main: Path,
    layer: LayerSpec,
    name: str,
) -> Path:
    request = RenderRequest(
        name=name,
        plan=CompositionPlan(assets=(probe_media(main, ffprobe),), mode=OrderMode.SEQUENTIAL),
        settings=RenderSettings(
            width=720, height=1280, fps=30, crf=20, preset="ultrafast",
            processing=ProcessingMode.CPU, fit_mode=FitMode.PAD,
        ),
        output_path=tmp_path / f"{name}.mp4",
        layers=(layer,),
    )
    return run_render(ffmpeg, request)


def test_shape_mask_pixel_acceptance(tmp_path: Path) -> None:
    """白底主片 + 红图层：形状遮罩必须真的改变可见面积。

    验收点（对齐 .NET OverlayRenderTests 的思路，改为量化面积比较）：

    * 无形状 → 红占比≈图层面积（60%×60%=36%）；
    * 椭圆 → 按内切圆语义，红占比明显下降且中心仍为红；
    * 圆角矩形 → 红占比略低于基准（只削掉四角）；
    * PNG 灰度遮罩（左白右黑）→ 红占比约为基准的一半；
    * 形状 + 羽化共存时不报错且红占比略低于纯椭圆。
    """
    ffmpeg, ffprobe = _require_tools()
    from jingxu.domain.layers import LayerShapeMask

    main = tmp_path / "main.mp4"
    layer_video = tmp_path / "layer.mp4"
    _make_solid(ffmpeg, main, color="white", size="720x1280")
    _make_solid(ffmpeg, layer_video, color="red", size="720x1280")

    plain = _render_shape_case(ffmpeg, ffprobe, tmp_path, main, _shape_layer(layer_video), "plain")
    plain_ratio = _red_fraction(ffmpeg, plain, tmp_path, "plain")
    assert 0.25 < plain_ratio < 0.45, plain_ratio

    ellipse = _render_shape_case(
        ffmpeg,
        ffprobe,
        tmp_path,
        main,
        _shape_layer(layer_video, shape_mask=LayerShapeMask.ELLIPSE.value),
        "ellipse",
    )
    ellipse_ratio = _red_fraction(ffmpeg, ellipse, tmp_path, "ellipse")
    # .NET 语义是「边界框内切圆」：半径 = min(W,H)/2。图层是 432x768 的非方框，
    # 圆只占边界框的 π·W/(4·H) ≈ 44%，即画布的约 16%，而非 π/4≈78%。
    assert ellipse_ratio == pytest.approx(plain_ratio * 0.442, rel=0.15), (
        plain_ratio,
        ellipse_ratio,
    )

    rounded = _render_shape_case(
        ffmpeg,
        ffprobe,
        tmp_path,
        main,
        _shape_layer(
            layer_video,
            shape_mask=LayerShapeMask.ROUNDED_RECTANGLE.value,
            mask_corner_radius_px=80,
        ),
        "rounded",
    )
    rounded_ratio = _red_fraction(ffmpeg, rounded, tmp_path, "rounded")
    # 只削四角：应低于基准但明显高于椭圆。
    assert rounded_ratio < plain_ratio, (plain_ratio, rounded_ratio)
    assert rounded_ratio > ellipse_ratio, (ellipse_ratio, rounded_ratio)

    mask_png = tmp_path / "half.png"
    _make_half_masked_png(ffmpeg, mask_png)
    png = _render_shape_case(
        ffmpeg,
        ffprobe,
        tmp_path,
        main,
        _shape_layer(
            layer_video,
            shape_mask=LayerShapeMask.IMPORTED_PNG.value,
            mask_png=mask_png,
        ),
        "png",
    )
    png_ratio = _red_fraction(ffmpeg, png, tmp_path, "png")
    # 左半遮罩 → 约为基准的一半。
    assert png_ratio == pytest.approx(plain_ratio / 2, rel=0.25), (plain_ratio, png_ratio)

    feathered = _render_shape_case(
        ffmpeg,
        ffprobe,
        tmp_path,
        main,
        _shape_layer(layer_video, shape_mask=LayerShapeMask.ELLIPSE.value, feather=0.4),
        "ellipse-feather",
    )
    feathered_ratio = _red_fraction(ffmpeg, feathered, tmp_path, "ellipse-feather")
    # 羽化在形状之后生效：边界被软化，纯红像素只会更少。
    assert feathered_ratio <= ellipse_ratio + 0.01, (ellipse_ratio, feathered_ratio)
    assert feathered_ratio > 0.02, feathered_ratio

    for output in (plain, ellipse, rounded, png, feathered):
        probed = probe_media(output, ffprobe)
        assert (probed.width, probed.height) == (720, 1280)
        assert probed.duration == pytest.approx(2.0, abs=0.3)
