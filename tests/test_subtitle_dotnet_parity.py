"""字幕页与 .NET 的结构对齐（分区名、措辞、脚本范围提示）。

对照来源：``Features/Subtitles/SubtitleLabView.xaml`` + ``SubtitleLabViewModel.cs``。

.NET 字幕页的分区顺序是：
预览与区域选择 → 检测与识别 → 去字幕方式 → 字幕列表 → 烧录并入队。

Python 版把 OCR 与 Whisper 合并进「检测与识别」，并在其后加了自己增强的
「烧录样式」（.NET 字幕页没有样式设置）。本文件守住"该对齐的部分确实对齐"，
同时**记录哪些是 Python 的刻意超集**，避免以后被当成差异"修正"掉。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.subtitles import RemovalMode  # noqa: E402
from jingxu.infrastructure.subtitle_store import SubtitleStore  # noqa: E402
from jingxu.ui.subtitle_page import SubtitlePage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page(tmp_path: Path) -> SubtitlePage:
    return SubtitlePage(SubtitleStore(store_path=tmp_path / "subtitles.json"), Path("ffmpeg"))


def _section_titles(page: SubtitlePage) -> list[str]:
    from jingxu.ui.widgets import SectionHeader  # noqa: PLC0415

    return [header.text() for header in page.findChildren(SectionHeader)]


# ── 分区名与顺序 ────────────────────────────────────────────────────────────


def test_sections_follow_dotnet_order(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """分区顺序对齐 .NET：预览 → 检测与识别 → 去字幕方式 → 字幕列表。"""
    titles = _section_titles(_page(tmp_path))

    expected = ["预览与区域选择", "检测与识别", "去字幕方式", "字幕列表"]
    positions = []
    for name in expected:
        assert name in titles, f"缺少分区「{name}」（当前：{titles}）"
        positions.append(titles.index(name))
    assert positions == sorted(positions), f"分区顺序与 .NET 不一致：{titles}"


def test_ocr_section_is_renamed_to_detection(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """旧的「OCR 自动定位」应并入「检测与识别」（.NET 的区块名）。"""
    titles = _section_titles(_page(tmp_path))
    assert "OCR 自动定位" not in titles
    assert "硬字幕去除" not in titles


def test_burn_style_is_a_documented_superset(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「烧录样式」是 Python 增强：.NET 字幕页没有样式设置，但本版保留它。"""
    assert "烧录样式" in _section_titles(_page(tmp_path))


# ── 措辞 ────────────────────────────────────────────────────────────────────


def test_removal_mode_labels_match_dotnet(qapp) -> None:  # noqa: ANN001
    """三种模式用 .NET 的原文（区域模糊 / Delogo 修补 / 裁切重构）。

    「遮盖」是本版多出来的第四种模式（.NET 只有三种），属刻意超集。
    """
    assert RemovalMode.BLUR.display_text == "区域模糊"
    assert RemovalMode.DELOGO.display_text == "Delogo 修补"
    assert RemovalMode.CROP_AND_REFRAME.display_text == "裁切重构"
    assert RemovalMode.COVER.display_text == "遮盖"


def test_ocr_button_label_matches_dotnet(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    assert _page(tmp_path)._ocr_button.text() == "OCR 检测硬字幕"


def test_scan_region_hint_tracks_the_checkbox(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """扫描范围提示对齐 .NET ``ScanRegionDescription``。

    回归：此前完全没有这行提示，用户不知道不勾「全画面扫描」时到底扫哪儿。
    """
    page = _page(tmp_path)

    assert page._ocr_full_frame.isChecked() is False
    assert page._scan_region_hint.text() == "下方 45% 扫描"

    page._ocr_full_frame.setChecked(True)
    qapp.processEvents()
    assert page._scan_region_hint.text() == "全画面扫描"

    page._ocr_full_frame.setChecked(False)
    qapp.processEvents()
    assert page._scan_region_hint.text() == "下方 45% 扫描"


def test_confirm_all_lives_in_the_detection_row(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「确认全部区域」应在检测区内（.NET 把它和 OCR/Whisper 放一起）。"""
    page = _page(tmp_path)

    assert page._confirm_all.text() == "确认全部区域"
    assert page._confirm_all.isHidden() is True  # 没有待复核区域时不显示

    # 它在检测行里：与 OCR 按钮同属一个父布局所在控件
    assert page._confirm_all.parent() is page._ocr_button.parent()


# ── 表格与 OCR 范围仍然可用 ─────────────────────────────────────────────────


def test_table_and_controls_still_wired(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """重排布局不能把表格或 OCR 控件弄丢。"""
    page = _page(tmp_path)

    assert page._table is not None
    assert page._table.columnCount() == 3
    assert page._region_canvas is not None
    assert page._apply_detected is not None
    assert page._ocr_progress is not None
    assert page._detected_list is not None


def test_scan_region_constants_unchanged(qapp) -> None:  # noqa: ANN001
    """扫描范围仍是「下方 45%」，与 .NET 的默认一致。"""
    from jingxu.ui.subtitle_page import DEFAULT_SCAN_REGION, FULL_FRAME_SCAN_REGION  # noqa: PLC0415

    assert FULL_FRAME_SCAN_REGION == (0.0, 0.0, 1.0, 1.0)
    assert DEFAULT_SCAN_REGION == (0.0, 0.55, 1.0, 0.45)
