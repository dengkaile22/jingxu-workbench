"""ASS 解析/导出、时间轴校验与 OCR 复核门禁测试。"""

from __future__ import annotations

import pytest

from jingxu.domain.subtitles import (
    DetectedSubtitleSegment,
    SubtitleCue,
    SubtitleStyle,
    has_pending_reviews,
    resolve_overlaps,
    validate_timeline,
)
from jingxu.infrastructure.subtitles import (
    build_ass,
    load_subtitle_file,
    parse_ass,
    parse_srt,
)

ASS_SAMPLE = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2,0,2,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,第一条字幕
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,含逗号,的第二条\\N换行文本
"""


class TestAssParsing:
    def test_parse_ass_reads_cues(self) -> None:
        cues = parse_ass(ASS_SAMPLE)

        assert len(cues) == 2
        assert cues[0].start == pytest.approx(1.0)
        assert cues[0].end == pytest.approx(3.5)
        assert cues[0].text == "第一条字幕"
        assert "含逗号,的第二条" in cues[1].text
        assert "\n" in cues[1].text

    def test_parse_ass_requires_format_line(self) -> None:
        broken = "[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,没有格式行\n"
        assert parse_ass(broken) == []

    def test_load_subtitle_file_dispatches_by_extension(self, tmp_path) -> None:  # noqa: ANN001
        ass_path = tmp_path / "字幕.ass"
        ass_path.write_text(ASS_SAMPLE, encoding="utf-8-sig")
        srt_path = tmp_path / "字幕.srt"
        srt_path.write_text("1\n00:00:00,500 --> 00:00:02,000\n你好\n", encoding="utf-8")

        assert len(load_subtitle_file(ass_path)) == 2
        assert len(load_subtitle_file(srt_path)) == 1

    def test_ass_roundtrip(self) -> None:
        cues = [SubtitleCue(start=0.5, end=2.0, text="往返测试")]
        text = build_ass(cues, SubtitleStyle(), 1080, 1920)
        parsed = parse_ass(text)

        assert len(parsed) == 1
        assert parsed[0].start == pytest.approx(0.5)
        assert parsed[0].text == "往返测试"

    def test_parse_srt_still_works(self) -> None:
        cues = parse_srt("1\n00:00:00,000 --> 00:00:01,000\nA\n")
        assert cues[0].text == "A"


class TestTimelineValidation:
    def test_valid_timeline_has_no_issues(self) -> None:
        cues = [SubtitleCue(0.0, 1.0, "一"), SubtitleCue(1.5, 2.5, "二")]
        assert validate_timeline(cues) == []

    def test_detects_reversed_and_empty_and_overlap(self) -> None:
        cues = [
            SubtitleCue(0.0, 2.0, "一"),
            SubtitleCue(1.0, 3.0, "二"),
            SubtitleCue(4.0, 4.0, ""),
        ]
        issues = validate_timeline(cues)

        assert any("重叠" in issue for issue in issues)
        assert any("结束时间必须晚于开始时间" in issue for issue in issues)
        assert any("不能为空" in issue for issue in issues)

    def test_resolve_overlaps_trims_previous(self) -> None:
        cues = [SubtitleCue(0.0, 2.0, "一"), SubtitleCue(1.0, 3.0, "二")]
        resolved = resolve_overlaps(cues)

        assert resolved[0].end == pytest.approx(1.0)
        assert len(resolved) == 2


class TestReviewGating:
    def test_pending_review_blocks(self) -> None:
        pending = [DetectedSubtitleSegment(0, 0, 1, 1, 0, 1, 0.4, requires_review=True)]
        confirmed = [
            DetectedSubtitleSegment(0, 0, 1, 1, 0, 1, 0.4, requires_review=True, review_state="confirmed")
        ]

        assert has_pending_reviews(pending) is True
        assert has_pending_reviews(confirmed) is False
        assert has_pending_reviews([]) is False
