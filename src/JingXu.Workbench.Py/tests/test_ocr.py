"""OCR 硬字幕检测：TSV 解析、聚类、采样计划与检测流程。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import jingxu.infrastructure.ocr as ocr_module
from jingxu.infrastructure.ocr import (
    OcrCancelled,
    OcrError,
    cluster_observations,
    detect_subtitle_regions,
    find_tesseract,
    iou,
    map_box_to_scan_region,
    parse_tesseract_tsv,
    plan_frame_samples,
)

HEADER = "\t".join(
    (
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    )
)


def tsv_row(
    level: int,
    page: int,
    block: int,
    par: int,
    line: int,
    word: int,
    left: int,
    top: int,
    width: int,
    height: int,
    conf: str | int,
    text: str,
) -> str:
    return "\t".join(
        str(value)
        for value in (level, page, block, par, line, word, left, top, width, height, conf, text)
    )


# ────────────────────────────── TSV 解析 ──────────────────────────────


def test_parse_tesseract_tsv_groups_words_by_line() -> None:
    tsv = "\n".join(
        (
            HEADER,
            tsv_row(1, 1, 0, 0, 0, 0, 0, 0, 640, 360, -1, ""),
            tsv_row(4, 1, 1, 1, 1, 0, 40, 300, 200, 30, 90, "整行"),
            tsv_row(5, 1, 1, 1, 1, 1, 120, 300, 60, 30, 80, "世界"),
            tsv_row(5, 1, 1, 1, 1, 2, 40, 300, 60, 30, 90, "你好"),
            tsv_row(5, 1, 1, 1, 1, 3, 40, 300, 0, 0, 70, ""),
            tsv_row(5, 1, 1, 2, 2, 1, 40, 340, 80, 30, "脏值", "坏行"),
            tsv_row(5, 2, 1, 1, 1, 1, 40, 300, 100, 30, 60, "第二页"),
            tsv_row(5, 2, 1, 2, 1, 1, 40, 340, 80, 30, 55, "  "),
        )
    )

    words = parse_tesseract_tsv(tsv)

    assert len(words) == 2
    first = words[0]
    assert first.text == "你好 世界"
    assert (first.left, first.top, first.width, first.height) == (40, 300, 140, 30)
    assert first.confidence == pytest.approx(0.85)
    assert (first.page, first.block, first.par, first.line) == (1, 1, 1, 1)
    second = words[1]
    assert second.text == "第二页"
    assert second.confidence == pytest.approx(0.6)
    assert (second.page, second.par) == (2, 1)


def test_parse_tesseract_tsv_handles_empty_payloads() -> None:
    assert parse_tesseract_tsv("") == []
    assert parse_tesseract_tsv(HEADER) == []
    assert parse_tesseract_tsv("garbage without header\n") == []


# ────────────────────────────── 聚类 ──────────────────────────────


def test_cluster_merges_neighboring_similar_observations() -> None:
    segments = cluster_observations(
        [
            (0.0, 0.10, 0.70, 0.60, 0.20, 0.90),
            (0.5, 0.11, 0.71, 0.60, 0.20, 0.80),
            (1.0, 0.12, 0.72, 0.60, 0.20, 0.70),
        ]
    )

    assert len(segments) == 1
    segment = segments[0]
    assert segment.x_percent == pytest.approx(11.0)
    assert segment.y_percent == pytest.approx(71.0)
    assert segment.width_percent == pytest.approx(60.0)
    assert segment.height_percent == pytest.approx(20.0)
    assert segment.start_seconds == pytest.approx(0.0)
    assert segment.end_seconds == pytest.approx(1.0)
    assert segment.confidence == pytest.approx(0.8)
    assert segment.requires_review is False


def test_cluster_splits_on_time_gap_and_low_overlap() -> None:
    by_time = cluster_observations(
        [
            (0.0, 0.10, 0.70, 0.50, 0.20, 0.90),
            (2.0, 0.10, 0.70, 0.50, 0.20, 0.90),
        ]
    )
    assert len(by_time) == 2

    by_iou = cluster_observations(
        [
            (0.0, 0.10, 0.70, 0.20, 0.20, 0.90),
            (0.5, 0.70, 0.70, 0.20, 0.20, 0.90),
        ]
    )
    assert len(by_iou) == 2


def test_cluster_marks_low_confidence_for_review() -> None:
    segments = cluster_observations(
        [
            (0.0, 0.10, 0.70, 0.50, 0.20, 0.90),
            (0.5, 0.10, 0.70, 0.50, 0.20, 0.10),
        ]
    )

    assert len(segments) == 1
    assert segments[0].requires_review is True
    assert segments[0].confidence == pytest.approx(0.5)


def test_cluster_clamps_end_to_total_duration() -> None:
    segments = cluster_observations(
        [
            (9.0, 0.10, 0.70, 0.50, 0.20, 0.90),
            (10.0, 0.10, 0.70, 0.50, 0.20, 0.90),
        ],
        total_duration=9.5,
    )

    assert len(segments) == 1
    assert segments[0].end_seconds == pytest.approx(9.5)


def test_cluster_returns_empty_for_no_observations() -> None:
    assert cluster_observations([]) == []


# ────────────────────────────── 采样 / 几何 ──────────────────────────────


def test_plan_frame_samples_uses_half_second_steps() -> None:
    assert plan_frame_samples(2.0) == [0.0, 0.5, 1.0, 1.5]
    assert plan_frame_samples(0.0) == []
    assert plan_frame_samples(-1.0) == []


def test_plan_frame_samples_downsamples_long_media() -> None:
    samples = plan_frame_samples(10000.0)
    assert len(samples) == 3600
    assert samples[0] == 0.0
    assert 0.0 < samples[-1] < 10000.0
    assert 10000.0 - samples[-1] <= 10000.0 / 3600 + 1e-6
    assert all(later > earlier for earlier, later in zip(samples, samples[1:]))


def test_plan_frame_samples_honors_max_frames() -> None:
    assert plan_frame_samples(2.0, max_frames=2) == [0.0, 1.0]


def test_map_box_to_scan_region_offsets_and_scales() -> None:
    assert map_box_to_scan_region((0.0, 0.0, 0.5, 0.5), (0.0, 0.55, 1.0, 0.45)) == pytest.approx(
        (0.0, 0.55, 0.5, 0.225)
    )
    assert map_box_to_scan_region((0.2, 0.4, 0.4, 0.2), (0.1, 0.2, 0.5, 0.6)) == pytest.approx(
        (0.2, 0.44, 0.2, 0.12)
    )


def test_iou_handles_overlap_disjoint_and_degenerate_boxes() -> None:
    assert iou((0.0, 0.0, 1.0, 1.0), (0.0, 0.0, 1.0, 1.0)) == pytest.approx(1.0)
    assert iou((0.0, 0.0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)) == pytest.approx(0.0)
    assert iou((0.2, 0.2, 0.4, 0.4), (0.4, 0.4, 0.4, 0.4)) == pytest.approx(1 / 7)


def test_find_tesseract_reuses_runtime_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = Path("runtime") / "tesseract"
    monkeypatch.setattr(ocr_module, "runtime_tesseract", lambda: sentinel)
    assert find_tesseract() == sentinel


# ────────────────────────────── 检测流程 ──────────────────────────────


def test_detect_subtitle_regions_runs_full_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")
    captured: dict[str, object] = {}
    progress: list[tuple[float, str]] = []

    def fake_extract(ffmpeg_path, video_path, timestamp, output_path):  # noqa: ANN001, ANN202
        output_path.write_bytes(b"png")
        return True

    def fake_run(tesseract_path, list_file, *, language, session_dir, timeout=600.0, cancel_event=None):  # noqa: ANN001, ANN202
        captured["session_dir"] = Path(session_dir)
        captured["list_text"] = Path(list_file).read_text(encoding="utf-8")
        captured["language"] = language
        rows = [HEADER]
        for page in range(1, 5):
            rows.append(tsv_row(1, page, 0, 0, 0, 0, 0, 0, 640, 360, -1, ""))
        for page in range(1, 5):
            rows.append(tsv_row(5, page, 1, 1, 1, 1, 64, 252, 128, 36, 82, "字幕"))
        return "\n".join(rows)

    monkeypatch.setattr(ocr_module, "_extract_frame", fake_extract)
    monkeypatch.setattr(ocr_module, "_run_tesseract", fake_run)

    segments = detect_subtitle_regions(
        tmp_path / "ffmpeg",
        video,
        duration=2.0,
        tesseract_path=tmp_path / "tesseract",
        temp_directory=tmp_path,
        on_progress=lambda percent, text: progress.append((percent, text)),
    )

    assert len(segments) == 1
    segment = segments[0]
    assert segment.x_percent == pytest.approx(10.0)
    assert segment.y_percent == pytest.approx(86.5)
    assert segment.width_percent == pytest.approx(20.0)
    assert segment.height_percent == pytest.approx(4.5)
    assert segment.start_seconds == pytest.approx(0.0)
    assert segment.end_seconds == pytest.approx(1.5)
    assert segment.confidence == pytest.approx(0.82)

    session_dir = captured["session_dir"]
    assert isinstance(session_dir, Path)
    assert session_dir.name.startswith("jingxu-ocr-")
    list_lines = [line for line in str(captured["list_text"]).splitlines() if line]
    assert len(list_lines) == 4
    for line in list_lines:
        assert Path(line).parent == session_dir
        assert Path(line).name.startswith("frame_")
    assert captured["language"] == "chi_sim+eng"
    assert not session_dir.exists()
    assert progress[0][0] == pytest.approx(1.0)
    assert progress[-1][0] == pytest.approx(100.0)
    assert "抽帧" in progress[1][1]


def test_detect_subtitle_regions_scales_by_page_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")

    def fake_extract(ffmpeg_path, video_path, timestamp, output_path):  # noqa: ANN001, ANN202
        output_path.write_bytes(b"png")
        return True

    def fake_run(tesseract_path, list_file, *, language, session_dir, timeout=600.0, cancel_event=None):  # noqa: ANN001, ANN202
        return "\n".join(
            (
                HEADER,
                tsv_row(1, 1, 0, 0, 0, 0, 0, 0, 1280, 720, -1, ""),
                tsv_row(5, 1, 1, 1, 1, 1, 128, 576, 256, 72, 90, "字幕"),
                tsv_row(1, 2, 0, 0, 0, 0, 0, 0, 1280, 720, -1, ""),
                tsv_row(5, 2, 1, 1, 1, 1, 128, 576, 256, 72, 90, "字幕"),
            )
        )

    monkeypatch.setattr(ocr_module, "_extract_frame", fake_extract)
    monkeypatch.setattr(ocr_module, "_run_tesseract", fake_run)

    segments = detect_subtitle_regions(
        tmp_path / "ffmpeg",
        video,
        duration=0.5,
        tesseract_path=tmp_path / "tesseract",
        scan_region=(0.0, 0.0, 1.0, 1.0),
        temp_directory=tmp_path,
    )

    assert len(segments) == 1
    assert segments[0].x_percent == pytest.approx(10.0)
    assert segments[0].y_percent == pytest.approx(80.0)
    assert segments[0].width_percent == pytest.approx(20.0)
    assert segments[0].height_percent == pytest.approx(10.0)


def test_detect_subtitle_regions_raises_when_frames_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")

    monkeypatch.setattr(ocr_module, "_extract_frame", lambda *args, **kwargs: False)

    with pytest.raises(OcrError, match="抽帧失败"):
        detect_subtitle_regions(
            tmp_path / "ffmpeg",
            video,
            duration=1.0,
            tesseract_path=tmp_path / "tesseract",
            temp_directory=tmp_path,
        )
    assert list(tmp_path.glob("jingxu-ocr-*")) == []


def test_detect_subtitle_regions_requires_ffprobe_for_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")
    monkeypatch.setattr(ocr_module.shutil, "which", lambda name: None)

    with pytest.raises(OcrError, match="FFprobe"):
        detect_subtitle_regions(
            tmp_path / "ffmpeg",
            video,
            tesseract_path=tmp_path / "tesseract",
            temp_directory=tmp_path,
        )


def test_detect_subtitle_regions_honors_preset_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")
    cancel_event = threading.Event()
    cancel_event.set()
    monkeypatch.setattr(ocr_module, "_extract_frame", lambda *args, **kwargs: pytest.fail("不应抽帧"))

    with pytest.raises(OcrCancelled):
        detect_subtitle_regions(
            tmp_path / "ffmpeg",
            video,
            duration=2.0,
            tesseract_path=tmp_path / "tesseract",
            temp_directory=tmp_path,
            cancel_event=cancel_event,
        )
    assert list(tmp_path.glob("jingxu-ocr-*")) == []
