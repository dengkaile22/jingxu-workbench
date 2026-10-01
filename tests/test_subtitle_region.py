"""字幕区域框选：几何映射、边界收口与「确认手动区域」流程。

对齐 .NET 字幕实验室的「预览与区域选择」——导入视频后可在画面上框选字幕区域。
Python 版此前只有百分比输入框，很难填对，是「字幕功能不用」的主因。

这些用例覆盖两类风险：
1. **几何**：画面按原始宽高比居中显示，归一化值与控件像素之间的换算必须正确，
   否则框选位置与写入的百分比会不一致；
2. **写回**：确认后必须写入 ``SubtitleRemovalSpec`` 的四个百分比并启用去除，
   且手改百分比时画布要跟着同步（否则画面与数值互相矛盾）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.ui.subtitle_region import (  # noqa: E402
    DEFAULT_REGION,
    MIN_REGION,
    SubtitleRegionCanvas,
    _clamp_region,
)


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _canvas(width: int = 400, height: int = 300, frame: tuple[int, int] | None = (1080, 1920)):  # noqa: ANN202
    canvas = SubtitleRegionCanvas()
    canvas.resize(width, height)
    if frame is not None:
        pixmap = QPixmap(*frame)
        pixmap.fill(Qt.GlobalColor.black)
        canvas.set_frame(pixmap)
    return canvas


# ── 边界收口 ────────────────────────────────────────────────────────────────


def test_clamp_keeps_region_inside_frame() -> None:
    assert _clamp_region((0.9, 0.9, 0.5, 0.5)) == (0.5, 0.5, 0.5, 0.5)


def test_clamp_enforces_minimum_size() -> None:
    x, y, width, height = _clamp_region((0.5, 0.5, 0.0, -1.0))
    assert width >= MIN_REGION
    assert height >= MIN_REGION


def test_clamp_handles_negative_origin() -> None:
    assert _clamp_region((-0.2, -0.3, 1.4, 1.5)) == (0.0, 0.0, 1.0, 1.0)


def test_clamp_preserves_valid_region() -> None:
    region = (0.1, 0.7, 0.8, 0.2)
    assert _clamp_region(region) == region


# ── 几何：显示矩形保持宽高比 ────────────────────────────────────────────────


def test_display_rect_letterboxes_wide_frame(qapp) -> None:  # noqa: ANN001
    """1080x1920 竖屏帧放在 400x300 控件里，应按高度铺满并水平居中。"""
    canvas = _canvas(400, 300, frame=(1080, 1920))
    rect = canvas._display_rect()

    assert rect.height() == 300
    # 1080/1920 * 300 = 168.75
    assert abs(rect.width() - 169) <= 1
    assert abs(rect.center().x() - 200) <= 1


def test_display_rect_without_frame_fills_widget(qapp) -> None:  # noqa: ANN001
    canvas = _canvas(400, 300, frame=None)
    assert canvas._display_rect() == canvas.rect()


# ── 命中判定 ────────────────────────────────────────────────────────────────


def test_mode_detects_corners_and_edges(qapp) -> None:  # noqa: ANN001
    canvas = _canvas()
    rect = canvas._region_rect()

    assert canvas._mode_at(rect.topLeft()) == "nw"
    assert canvas._mode_at(rect.topRight()) == "ne"
    assert canvas._mode_at(rect.bottomLeft()) == "sw"
    assert canvas._mode_at(rect.bottomRight()) == "se"
    assert canvas._mode_at(QPoint(rect.left(), rect.center().y())) == "w"
    assert canvas._mode_at(QPoint(rect.right(), rect.center().y())) == "e"
    assert canvas._mode_at(QPoint(rect.center().x(), rect.top())) == "n"
    assert canvas._mode_at(QPoint(rect.center().x(), rect.bottom())) == "s"


def test_mode_detects_inside_as_move(qapp) -> None:  # noqa: ANN001
    canvas = _canvas()
    assert canvas._mode_at(canvas._region_rect().center()) == "move"


def test_mode_returns_none_far_away(qapp) -> None:  # noqa: ANN001
    canvas = _canvas()
    assert canvas._mode_at(QPoint(2, 2)) is None


# ── 拖拽：区域随鼠标变化且始终合法 ──────────────────────────────────────────


def _drag(canvas: SubtitleRegionCanvas, start: QPoint, end: QPoint) -> None:
    """用非弃用构造方式合成鼠标事件（避免 QMouseEvent 的 DeprecationWarning）。"""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    device = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(start),
        QPointF(start),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ).pointingDevice()

    def make(kind, point, button, buttons):  # noqa: ANN001, ANN202
        return QMouseEvent(
            kind,
            QPointF(point),
            QPointF(point),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
            device,
        )

    canvas.mousePressEvent(
        make(
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseMoveEvent(
        make(QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    canvas.mouseReleaseEvent(
        make(
            QEvent.Type.MouseButtonRelease,
            end,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )


def test_dragging_inside_moves_region(qapp) -> None:  # noqa: ANN001
    canvas = _canvas()
    canvas.set_region(*DEFAULT_REGION)
    before = canvas.region()

    rect = canvas._region_rect()
    _drag(canvas, rect.center(), rect.center() + QPoint(0, -40))

    after = canvas.region()
    assert after[1] < before[1], "向上拖动应让区域上移"
    # 尺寸不变（纯平移）
    assert after[2] == pytest.approx(before[2], abs=1e-3)
    assert after[3] == pytest.approx(before[3], abs=1e-3)


def test_dragging_never_leaves_frame(qapp) -> None:  # noqa: ANN001
    """拖到画外时区域必须被收口，否则会写出越界百分比。"""
    canvas = _canvas()
    canvas.set_region(*DEFAULT_REGION)
    rect = canvas._region_rect()

    _drag(canvas, rect.center(), QPoint(10000, 10000))

    x, y, width, height = canvas.region()
    assert x >= 0.0 and y >= 0.0
    assert x + width <= 1.0 + 1e-6
    assert y + height <= 1.0 + 1e-6


def test_press_on_empty_area_creates_region(qapp) -> None:  # noqa: ANN001
    """空白处按下应新建一个小区域，便于快速框选。"""
    canvas = _canvas()
    canvas.set_region(0.05, 0.05, 0.1, 0.05)

    _drag(canvas, QPoint(200, 150), QPoint(200, 150))

    x, y, width, height = canvas.region()
    assert width > 0.1, "应新建比原区域更宽的选框"
    assert 0.0 <= x and 0.0 <= y


def test_set_region_clamps(qapp) -> None:  # noqa: ANN001
    canvas = _canvas()
    canvas.set_region(0.95, 0.95, 0.5, 0.5)
    x, y, width, height = canvas.region()
    assert x + width <= 1.0 + 1e-6
    assert y + height <= 1.0 + 1e-6


def test_canvas_reports_frame_presence(qapp) -> None:  # noqa: ANN001
    assert _canvas(frame=None).has_frame() is False
    assert _canvas().has_frame() is True


# ── 页面集成：确认手动区域写回参数 ──────────────────────────────────────────


def _subtitle_page(tmp_path: Path):  # noqa: ANN202
    from jingxu.infrastructure.subtitle_store import SubtitleStore
    from jingxu.ui.subtitle_page import SubtitlePage

    return SubtitlePage(SubtitleStore(tmp_path / "subtitle.json"), Path("ffmpeg"))


def test_confirm_without_frame_warns(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _subtitle_page(tmp_path)

    page._commit_manual_region()

    assert "请先点" in page._status.text()
    assert page._status.objectName() == "CaptionWarn"


def test_confirm_writes_removal_spec(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)
    page._region_canvas.set_region(0.2, 0.1, 0.6, 0.25)

    page._commit_manual_region()

    spec = page._current_removal()
    assert (spec.x_percent, spec.y_percent) == (20.0, 10.0)
    assert (spec.width_percent, spec.height_percent) == (60.0, 25.0)
    assert spec.enabled is True, "确认区域后应自动启用硬字幕去除"
    assert "已应用手动区域" in page._status.text()


def test_confirm_persists(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from jingxu.infrastructure.subtitle_store import SubtitleStore

    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)
    page._region_canvas.set_region(0.3, 0.6, 0.4, 0.2)

    page._commit_manual_region()

    saved = SubtitleStore(tmp_path / "subtitle.json").document.removal
    assert saved is not None
    assert saved.width_percent == 40.0


def test_editing_spins_syncs_canvas(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """手改百分比时画布选框必须跟着动，否则画面与数值矛盾。"""
    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)

    page._region_spins["x"].setValue(25)
    page._region_spins["w"].setValue(50)

    x, _y, width, _height = page._region_canvas.region()
    assert x == pytest.approx(0.25, abs=1e-3)
    assert width == pytest.approx(0.50, abs=1e-3)


def test_load_frame_without_source_warns(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _subtitle_page(tmp_path)

    page._load_region_frame()

    assert "选中一个素材" in page._status.text()
    assert page._status.objectName() == "CaptionWarn"


def test_page_has_preview_section(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """区块名与 .NET 一致。"""
    page = _subtitle_page(tmp_path)

    from jingxu.ui.widgets import SectionHeader

    headers = [
        child.text() for child in page.findChildren(SectionHeader)
    ]
    assert "预览与区域选择" in headers
    assert page._region_canvas is not None


# ── 实际去除区域的可视标记（防止「框选偏了却看不出来」）────────────────────


def test_removal_overlay_is_drawn_after_confirm(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """确认手动区域后，画布必须标出**实际生效**的去除范围。

    只让用户拖框、却不显示真正会被去掉的范围，就无法发现框偏了——
    实测出现过模糊只盖住文字上半截、下半截仍然清晰的情况。
    """
    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)
    page._region_canvas.set_region(0.3, 0.84, 0.4, 0.05)

    page._commit_manual_region()

    overlay = page._region_canvas.removal_region()
    assert overlay is not None, "画布应标出实际去除区域"
    assert overlay == pytest.approx((0.30, 0.84, 0.40, 0.05), abs=1e-3)
    assert "实际去除区域" in page._region_canvas._removal_label


def test_removal_overlay_clears_when_disabled(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """关闭「启用硬字幕去除」后不应再显示去除标记（否则误导）。"""
    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)
    page._region_canvas.set_region(0.2, 0.8, 0.5, 0.06)
    page._commit_manual_region()
    assert page._region_canvas.removal_region() is not None

    page._removal_enable.setChecked(False)

    assert page._region_canvas.removal_region() is None


def test_removal_overlay_follows_manual_percent_edits(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """手改百分比时标记要跟着动，否则标记与真实参数不一致。"""
    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)
    page._removal_enable.setChecked(True)

    page._region_spins["y"].setValue(70)
    page._region_spins["h"].setValue(12)

    overlay = page._region_canvas.removal_region()
    assert overlay is not None
    assert overlay[1] == pytest.approx(0.70, abs=1e-3)
    assert overlay[3] == pytest.approx(0.12, abs=1e-3)


def test_removal_overlay_label_names_the_mode(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """标签要写清用哪种方式去除，便于判断效果差异。"""
    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)
    page._removal_enable.setChecked(True)
    page._region_spins["w"].setValue(50)
    page._region_spins["h"].setValue(10)

    label = page._region_canvas._removal_label
    assert label.startswith("实际去除区域")
    assert any(key in label for key in ("模糊", "遮盖", "裁切", "去标"))


# ── 无帧时不得假装可拖拽 ────────────────────────────────────────────────────


def test_canvas_does_not_draw_region_without_frame(qapp) -> None:
    """没有预览帧时不画选框。

    此前无帧仍画出选区，看起来已就绪却拖不动——实测用户就是卡在这里
    （「字幕那个怎么移动不了」）。
    """
    canvas = SubtitleRegionCanvas()
    canvas.resize(800, 400)

    assert canvas.has_frame() is False
    # 无帧时 _region_rect 仍有几何值，但绘制流程会在有帧判断处提前返回；
    # 这里断言拖拽被拒绝（不产生状态变化）。
    before = canvas.region()
    _drag(canvas, QPoint(400, 200), QPoint(400, 120))
    assert canvas.region() == before, "无帧时不应响应拖拽"


def test_drag_works_once_frame_is_loaded(qapp) -> None:
    """加载画面后拖拽必须生效。"""
    canvas = _canvas()
    canvas.set_region(0.2, 0.8, 0.5, 0.08)
    before = canvas.region()
    rect = canvas._region_rect()

    _drag(canvas, rect.center(), rect.center() + QPoint(0, -30))

    assert canvas.region()[1] < before[1]


# ── 自动加载预览帧 ──────────────────────────────────────────────────────────


def test_set_source_material_clears_previous_frame(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """换素材时先清掉旧画面，避免拿上一个素材的帧选框。"""
    page = _subtitle_page(tmp_path)
    pixmap = QPixmap(1080, 1920)
    pixmap.fill(Qt.GlobalColor.black)
    page._region_canvas.set_frame(pixmap)
    page._region_canvas.set_removal_region((0.1, 0.8, 0.5, 0.1))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")
    monkeypatch.setattr(page, "_load_region_frame_async", lambda source: None)

    page.set_source_material(video)

    assert page._region_canvas.has_frame() is False
    assert page._region_canvas.removal_region() is None
    assert "正在读取预览帧" in page._region_hint.text()


def test_same_source_does_not_reload(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """重复传同一素材不应反复抽帧（切页频繁触发）。"""
    page = _subtitle_page(tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")
    calls: list[str] = []
    monkeypatch.setattr(page, "_load_region_frame_async", lambda source: calls.append(str(source)))

    page.set_source_material(video)
    page.set_source_material(video)

    assert len(calls) == 1


def test_frame_result_from_stale_source_is_ignored(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """过期结果必须丢弃：否则快速切素材会显示上一个素材的画面。"""
    page = _subtitle_page(tmp_path)
    stale = tmp_path / "old.mp4"
    stale.write_bytes(b"stub")
    page._source = tmp_path / "new.mp4"
    pixmap = QPixmap(100, 100)
    pixmap.fill(Qt.GlobalColor.red)

    page._on_region_frame_ready(str(stale), pixmap, "")

    assert page._region_canvas.has_frame() is False, "过期帧不得上屏"


def test_frame_failure_reports_message(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """抽帧失败要给可读提示，不能静默。"""
    page = _subtitle_page(tmp_path)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"stub")
    page._source = source

    page._on_region_frame_ready(str(source), None, "抽取预览帧失败：素材损坏。")

    assert "抽取预览帧失败" in page._region_hint.text()
    assert page._status.objectName() == "CaptionWarn"
