"""字幕页设置读写回归（含 Qt 字符串枚举退化问题）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSpinBox  # noqa: E402

import jingxu.ui.subtitle_page as subtitle_page_module  # noqa: E402
from jingxu.domain.subtitles import (  # noqa: E402
    DetectedSubtitleSegment,
    RemovalMode,
    SubtitleCue,
    SubtitlePosition,
)
from jingxu.infrastructure.subtitle_store import SubtitleStore  # noqa: E402
from jingxu.ui.subtitle_page import SubtitlePage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def test_style_and_removal_roundtrip(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    store_path = tmp_path / "subtitle-lab.json"
    store = SubtitleStore(store_path)
    page = SubtitlePage(store, Path("ffmpeg"))

    assert page.burn_spec() is None  # 无字幕时不烧录

    page._cues = [SubtitleCue(0.0, 1.0, "嗨")]
    page._position.setCurrentIndex(page._position.findData("top"))
    page._removal_mode.set_value(RemovalMode.COVER)
    page._removal_enable.setChecked(True)
    page._persist()

    burn = page.burn_spec()
    assert burn is not None
    assert burn.style.position is SubtitlePosition.TOP

    removal = page.removal_spec()
    assert removal is not None and removal.mode is RemovalMode.COVER

    reloaded = SubtitleStore(store_path)
    assert reloaded.document.cues[0].text == "嗨"
    assert reloaded.document.style.position is SubtitlePosition.TOP
    assert reloaded.document.removal.mode is RemovalMode.COVER

    page._removal_enable.setChecked(False)
    assert page.removal_spec() is None


def test_region_spins_are_percent_spinboxes(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(subtitle_page_module, "find_tesseract", lambda: None)
    page = SubtitlePage(SubtitleStore(tmp_path / "subtitle-lab.json"), Path("ffmpeg"))

    for key in ("x", "y", "w", "h"):
        spin = page._region_spins[key]
        assert isinstance(spin, QSpinBox)
        assert (spin.minimum(), spin.maximum()) == (0, 100)
        assert spin.singleStep() == 1
    assert [page._region_spins[key].value() for key in ("x", "y", "w", "h")] == [8, 76, 84, 18]


def test_ocr_button_disabled_without_tesseract(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(subtitle_page_module, "find_tesseract", lambda: None)
    page = SubtitlePage(SubtitleStore(tmp_path / "subtitle-lab.json"), Path("ffmpeg"))

    assert page._ocr_button.isEnabled() is False
    assert "Tesseract" in page._ocr_status.text()
    assert page._detected_list.isVisible() is False
    assert page._apply_detected.isVisible() is False


def test_apply_detected_segment_updates_removal_and_persists(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(subtitle_page_module, "find_tesseract", lambda: None)
    store_path = tmp_path / "subtitle-lab.json"
    page = SubtitlePage(SubtitleStore(store_path), Path("ffmpeg"))
    segment = DetectedSubtitleSegment(
        x_percent=12.4,
        y_percent=70.6,
        width_percent=63.5,
        height_percent=17.5,
        start_seconds=1.0,
        end_seconds=3.5,
        confidence=0.91,
        requires_review=False,
    )

    page._apply_detected_segment(segment)

    removal = page.removal_spec()
    assert removal is not None
    assert removal.enabled is True
    assert removal.x_percent == pytest.approx(12.0)
    assert removal.y_percent == pytest.approx(71.0)
    assert removal.width_percent == pytest.approx(64.0)
    assert removal.height_percent == pytest.approx(18.0)

    reloaded = SubtitleStore(store_path)
    assert reloaded.document.removal.enabled is True
    assert reloaded.document.removal.x_percent == pytest.approx(12.0)
    assert reloaded.document.removal.width_percent == pytest.approx(64.0)
    assert "复核" not in page._ocr_status.text()


def test_apply_low_confidence_segment_mentions_review(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(subtitle_page_module, "find_tesseract", lambda: None)
    page = SubtitlePage(SubtitleStore(tmp_path / "subtitle-lab.json"), Path("ffmpeg"))
    segment = DetectedSubtitleSegment(
        x_percent=8.0,
        y_percent=76.0,
        width_percent=84.0,
        height_percent=18.0,
        start_seconds=0.0,
        end_seconds=2.0,
        confidence=0.4,
        requires_review=True,
    )

    page._apply_detected_segment(segment)

    assert "复核" in page._ocr_status.text()
    assert page.removal_spec() is not None


def test_segment_row_text_includes_region_and_review_flag(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(subtitle_page_module, "find_tesseract", lambda: None)
    page = SubtitlePage(SubtitleStore(tmp_path / "subtitle-lab.json"), Path("ffmpeg"))
    segment = DetectedSubtitleSegment(
        x_percent=10.0,
        y_percent=86.5,
        width_percent=20.0,
        height_percent=4.5,
        start_seconds=0.0,
        end_seconds=2.5,
        confidence=0.82,
        requires_review=True,
    )

    text = page._segment_row_text(segment)

    assert text == "0.0s–2.5s · 区域 10%,86%,20%,4% · 置信度 82%（待复核）"


def test_ocr_full_frame_region_selection(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(subtitle_page_module, "find_tesseract", lambda: Path("tesseract"))
    page = SubtitlePage(SubtitleStore(tmp_path / "subtitle-lab.json"), Path("ffmpeg"))

    assert page._ocr_button.isEnabled() is True

    captured: dict[str, object] = {}

    def fake_detect(_ffmpeg, _video, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return []

    monkeypatch.setattr(subtitle_page_module, "detect_subtitle_regions", fake_detect)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"stub")
    page.set_source_material(source)

    page.start_ocr_detection()
    worker = page._ocr_worker
    assert worker is not None
    worker.join(timeout=5)
    assert captured["scan_region"] == (0.0, 0.55, 1.0, 0.45)

    page._ocr_full_frame.setChecked(True)
    page.start_ocr_detection()
    worker = page._ocr_worker
    assert worker is not None
    worker.join(timeout=5)
    assert captured["scan_region"] == (0.0, 0.0, 1.0, 1.0)


def test_ocr_finished_fills_list_and_applies_selection(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(subtitle_page_module, "find_tesseract", lambda: Path("tesseract"))
    page = SubtitlePage(SubtitleStore(tmp_path / "subtitle-lab.json"), Path("ffmpeg"))
    segments = [
        DetectedSubtitleSegment(10.0, 86.0, 20.0, 5.0, 0.0, 2.5, 0.82, True),
        DetectedSubtitleSegment(60.0, 90.0, 30.0, 6.0, 3.0, 6.0, 0.95, False),
    ]

    page._on_ocr_finished(segments)

    assert page._detected_list.count() == 2
    assert page._detected_list.item(0).text() == "0.0s–2.5s · 区域 10%,86%,20%,5% · 置信度 82%（待复核）"
    assert page._detected_list.isHidden() is False
    assert page._apply_detected.isHidden() is False
    assert page._ocr_button.isEnabled() is True

    page._detected_list.setCurrentRow(1)
    page._apply_selected_segment()

    assert page._region_spins["x"].value() == 60
    assert page._region_spins["y"].value() == 90
    assert page._region_spins["w"].value() == 30
    assert page._region_spins["h"].value() == 6
    assert page.removal_spec() is not None
    assert "复核" not in page._ocr_status.text()
