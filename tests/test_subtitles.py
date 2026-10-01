"""字幕：SRT/ASS 处理与烧录/去除滤镜测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.render import RenderSettings
from jingxu.domain.subtitles import (
    RemovalMode,
    SubtitleBurnSpec,
    SubtitleCue,
    SubtitlePosition,
    SubtitleRemovalSpec,
    SubtitleStyle,
)
from jingxu.infrastructure.filter_graph import build_filter_graph
from jingxu.infrastructure.subtitles import (
    build_ass,
    escape_filter_path,
    format_ass_time,
    format_srt,
    parse_srt,
)

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:03,500
第一句字幕

2
00:00:04,000 --> 00:00:06,200
第二句
换行文本
"""


def _plan(*assets) -> CompositionPlan:
    return CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL)


class TestSrt:
    def test_parse_roundtrip(self) -> None:
        cues = parse_srt(SAMPLE_SRT)
        assert len(cues) == 2
        assert cues[0].start == 1.0
        assert cues[0].end == 3.5
        assert cues[0].text == "第一句字幕"
        assert cues[1].text == "第二句\n换行文本"

        exported = format_srt(cues)
        assert "00:00:01,000 --> 00:00:03,500" in exported
        assert parse_srt(exported)[1].text == "第二句\n换行文本"

    def test_parse_tolerates_missing_index_and_short_ms(self) -> None:
        cues = parse_srt("00:00:00.5 --> 00:00:01.25\n嗨\n")
        assert cues and cues[0].start == 0.5 and cues[0].end == 1.25

    def test_format_ass_time(self) -> None:
        assert format_ass_time(3661.234) == "1:01:01.23"
        assert format_ass_time(0) == "0:00:00.00"


class TestAss:
    def test_build_ass_has_style_and_dialogues(self) -> None:
        cues = [SubtitleCue(0.5, 2.0, "你好\n世界")]
        style = SubtitleStyle(
            font_size=30,
            color="#FFE066",
            outline=3,
            margin_v=90,
            position=SubtitlePosition.TOP,
        )
        text = build_ass(cues, style, 1080, 1920)

        assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
        assert "Microsoft YaHei,30" in text
        assert "&H0066E0FF" in text  # 黄色（BGR）
        assert "1,3,0,8,40,40,90" in text  # BorderStyle/Outline/Shadow/Alignment/Margins
        assert "Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,你好\\N世界" in text

    def test_escape_filter_path_windows(self) -> None:
        escaped = escape_filter_path(Path(r"C:\Users\a b\Temp\sub.ass"))
        assert escaped == "C\\:/Users/a b/Temp/sub.ass"


class TestGraphIntegration:
    def test_subtitle_burn_references_escaped_path(self) -> None:
        graph = build_filter_graph(
            _plan(make_asset("a.mp4")),
            RenderSettings(),
            subtitle_path=Path(r"C:\Temp\字幕.ass"),
        )
        assert "ass='C\\:/Temp/字幕.ass'[vsub]" in graph.script
        assert "[vsub]null[vout]" in graph.script
        assert "[vcat]ass=" in graph.script

    def test_srt_burn_uses_subtitles_filter(self) -> None:
        graph = build_filter_graph(
            _plan(make_asset("a.mp4")),
            RenderSettings(),
            subtitle_path=Path(r"C:\Temp\字幕.srt"),
        )
        assert "subtitles=filename='C\\:/Temp/字幕.srt'[vsub]" in graph.script

    def test_blur_removal_chain(self) -> None:
        graph = build_filter_graph(
            _plan(make_asset("a.mp4")),
            RenderSettings(width=1080, height=1920),
            removal=SubtitleRemovalSpec(mode=RemovalMode.BLUR, x_percent=8, y_percent=76, width_percent=84, height_percent=18, blur_power=12),
        )
        assert "[vcat]split=2[rbase][rcrop]" in graph.script
        assert "crop=906:346:86:1459,gblur=sigma=12[rblur]" in graph.script
        assert "[rbase][rblur]overlay=86:1459[vrm]" in graph.script
        assert "[vrm]null[vout]" in graph.script

    def test_crop_and_reframe_requires_edge_region(self) -> None:
        bottom = build_filter_graph(
            _plan(make_asset("a.mp4")),
            RenderSettings(width=1080, height=1920),
            removal=SubtitleRemovalSpec(
                mode=RemovalMode.CROP_AND_REFRAME,
                x_percent=0,
                y_percent=82,
                width_percent=100,
                height_percent=18,
            ),
        )
        assert "crop=1080:1574:0:0,scale=1080:1920[vrm]" in bottom.script

        with pytest.raises(ValueError, match="裁切重构仅适用于贴顶或贴底"):
            build_filter_graph(
                _plan(make_asset("a.mp4")),
                RenderSettings(width=1080, height=1920),
                removal=SubtitleRemovalSpec(
                    mode=RemovalMode.CROP_AND_REFRAME,
                    x_percent=0,
                    y_percent=40,
                    width_percent=100,
                    height_percent=10,
                ),
            )

    def test_cover_and_delogo_modes(self) -> None:
        cover = build_filter_graph(
            _plan(make_asset("a.mp4")),
            RenderSettings(width=720, height=1280),
            removal=SubtitleRemovalSpec(mode=RemovalMode.COVER),
        )
        assert "drawbox=x=58:y=973:w=604:h=230:color=black@1.0:t=fill[vrm]" in cover.script

        delogo = build_filter_graph(
            _plan(make_asset("a.mp4")),
            RenderSettings(width=720, height=1280),
            removal=SubtitleRemovalSpec(mode=RemovalMode.DELOGO),
        )
        assert "delogo=x=58:y=973:w=604:h=230[vrm]" in delogo.script

    def test_burn_spec_flows_into_request(self) -> None:
        from jingxu.application.composition_service import CompositionDraft, build_requests
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            requests = build_requests(
                assets=[make_asset("a.mp4")],
                draft=CompositionDraft(
                    output_prefix="字幕",
                    subtitles=SubtitleBurnSpec(cues=(SubtitleCue(0, 1, "嗨"),)),
                    removal=SubtitleRemovalSpec(mode=RemovalMode.BLUR),
                ),
                output_directory=Path(directory),
            )
        request = requests[0]
        assert request.subtitles is not None and len(request.subtitles.cues) == 1
        assert request.removal is not None and request.removal.mode is RemovalMode.BLUR
