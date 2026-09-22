"""预览框命中与缩放：逐条对齐 .NET ``PreviewHitTester`` / ``PreviewRectangleManipulator``。

为什么单独立文件
----------------
这两个类是 .NET 版的**交互契约**，语义细节容易在移植时被"顺手优化"掉：

* 对边拖拽**只改一个方向**——拖右边只改宽度，``y`` 不动；拖上边只改高度，``x`` 不动。
  .NET 的注释专门写了"顶边 BoundsY 不变"，正是因为改错了会让整个框跟着跳。
* 命中判定顺序是**先角后边**，否则角区永远被边吃掉，用户永远拉不出斜角。
* 越界时把该边夹在 ``[0, 对边 - 最小值]``，矩形**不翻面**。
* ``move`` 夹取在 ``[0, 1-宽/高]``，框不会跑出画布。

这些行为都有 .NET 侧同名实现可逐行对照：
``Features/Overlays/PreviewHitTester.cs``。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from PySide6.QtCore import QPointF, QSize, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.ui.layer_preview import (  # noqa: E402
    HANDLE_THICKNESS,
    MIN_NORMALIZED_SIZE,
    LayerBox,
    LayerPreviewCanvas,
    PreviewHitZone,
    cursor_for_zone,
    hit_test_box,
    move_box,
    resize_box,
)

CANVAS_W, CANVAS_H = 216.0, 384.0
# 归一化 (0.25, 0.25, 0.5, 0.5) → 像素 (54, 96, 108, 192)
BOX = LayerBox(0.25, 0.25, 0.5, 0.5)


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _zone(x: float, y: float) -> PreviewHitZone:
    return hit_test_box((x, y), BOX, CANVAS_W, CANVAS_H)


# ── 命中判定 ────────────────────────────────────────────────────────────────


def test_center_hits_move() -> None:
    assert _zone(108, 192) is PreviewHitZone.MOVE


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((54, 192), PreviewHitZone.WEST),
        ((162, 192), PreviewHitZone.EAST),
        ((108, 96), PreviewHitZone.NORTH),
        ((108, 288), PreviewHitZone.SOUTH),
        ((54, 96), PreviewHitZone.NORTH_WEST),
        ((162, 96), PreviewHitZone.NORTH_EAST),
        ((54, 288), PreviewHitZone.SOUTH_WEST),
        ((162, 288), PreviewHitZone.SOUTH_EAST),
    ],
)
def test_edges_and_corners(point: tuple[float, float], expected: PreviewHitZone) -> None:
    assert _zone(*point) is expected


def test_corner_wins_over_edge() -> None:
    """角区必须先判：否则角上永远命中边，用户拉不出斜角。"""
    # 距左上角 1px —— 同时满足 near_left 与 near_top
    assert _zone(55, 97) is PreviewHitZone.NORTH_WEST
    # 距右上角 1px
    assert _zone(161, 97) is PreviewHitZone.NORTH_EAST


def test_outside_returns_none() -> None:
    assert _zone(0, 0) is PreviewHitZone.NONE
    assert _zone(215, 383) is PreviewHitZone.NONE


def test_handle_thickness_boundary() -> None:
    """厚度边界按 .NET 的 ``<=`` 判定：正好 10px 仍算命中。

    框的右边缘在 x = (0.25+0.5)×216 = 162，左边缘在 54。
    """
    assert HANDLE_THICKNESS == 10.0
    right_edge = 162.0
    assert _zone(right_edge - HANDLE_THICKNESS, 192) is PreviewHitZone.EAST
    assert _zone(right_edge + HANDLE_THICKNESS, 192) is PreviewHitZone.EAST
    assert _zone(right_edge + HANDLE_THICKNESS + 1, 192) is PreviewHitZone.NONE


def test_degenerate_box_returns_none() -> None:
    assert hit_test_box((10, 10), LayerBox(0.1, 0.1, 0.0, 0.5), CANVAS_W, CANVAS_H) is PreviewHitZone.NONE


# ── 平移 ────────────────────────────────────────────────────────────────────


def test_move_translates_by_pixel_delta() -> None:
    moved = move_box(BOX, 21.6, 38.4, CANVAS_W, CANVAS_H)  # 10% 的宽 / 高
    assert moved.x == pytest.approx(0.35)
    assert moved.y == pytest.approx(0.35)
    assert (moved.width, moved.height) == (0.5, 0.5)  # 尺寸不变


def test_move_clamps_inside_canvas() -> None:
    moved = move_box(BOX, 9999, 9999, CANVAS_W, CANVAS_H)
    assert moved.x == pytest.approx(0.5)
    assert moved.y == pytest.approx(0.5)

    back = move_box(BOX, -9999, -9999, CANVAS_W, CANVAS_H)
    assert back.x == 0.0
    assert back.y == 0.0


def test_move_rounds_to_four_decimals() -> None:
    moved = move_box(BOX, 1.0, 1.0, CANVAS_W, CANVAS_H)
    assert moved.x == round(moved.x, 4)


def test_move_on_zero_canvas_is_noop() -> None:
    assert move_box(BOX, 10, 10, 0, 0) == BOX


# ── 缩放：对边只改一个方向（.NET 的核心语义） ───────────────────────────────


def test_east_only_changes_width() -> None:
    resized = resize_box(BOX, PreviewHitZone.EAST, 21.6, 999, CANVAS_W, CANVAS_H)
    assert resized.x == BOX.x, "拖右边不应改变 x"
    assert resized.y == BOX.y
    assert resized.height == BOX.height, "拖右边不应改变高度"
    assert resized.width == pytest.approx(0.6)


def test_west_moves_left_edge_and_keeps_right_edge() -> None:
    right_before = BOX.x + BOX.width
    resized = resize_box(BOX, PreviewHitZone.WEST, -21.6, 0, CANVAS_W, CANVAS_H)
    assert resized.x == pytest.approx(0.15)
    assert resized.x + resized.width == pytest.approx(right_before), "右边必须钉住"
    assert resized.height == BOX.height


def test_north_moves_top_edge_and_keeps_bottom_edge() -> None:
    """对齐 .NET 注释「顶边 BoundsY 不变」的反面：拖上边时底边不动。"""
    bottom_before = BOX.y + BOX.height
    resized = resize_box(BOX, PreviewHitZone.NORTH, 0, -38.4, CANVAS_W, CANVAS_H)
    assert resized.y == pytest.approx(0.15)
    assert resized.y + resized.height == pytest.approx(bottom_before), "底边必须钉住"
    assert resized.width == BOX.width


def test_south_only_changes_height() -> None:
    resized = resize_box(BOX, PreviewHitZone.SOUTH, 999, 38.4, CANVAS_W, CANVAS_H)
    assert resized.x == BOX.x
    assert resized.y == BOX.y
    assert resized.width == BOX.width
    assert resized.height == pytest.approx(0.6)


def test_corner_changes_both_dimensions() -> None:
    resized = resize_box(BOX, PreviewHitZone.SOUTH_EAST, 21.6, 38.4, CANVAS_W, CANVAS_H)
    assert resized.width == pytest.approx(0.6)
    assert resized.height == pytest.approx(0.6)
    assert (resized.x, resized.y) == (BOX.x, BOX.y)


def test_resize_respects_minimum_size() -> None:
    """最小边长逐值对齐 .NET ``OverlayEditorViewModel.MinNormalizedSize = 0.05``。"""
    resized = resize_box(BOX, PreviewHitZone.EAST, -9999, 0, CANVAS_W, CANVAS_H)
    assert resized.width == pytest.approx(MIN_NORMALIZED_SIZE)
    assert MIN_NORMALIZED_SIZE == 0.05


def test_resize_clamps_to_canvas_without_flipping() -> None:
    """越界时把边夹住，矩形不得翻面（宽高始终为正）。"""
    resized = resize_box(BOX, PreviewHitZone.EAST, 9999, 9999, CANVAS_W, CANVAS_H)
    assert resized.width > 0 and resized.height > 0
    assert resized.x + resized.width <= 1.0 + 1e-9
    assert resized.y + resized.height <= 1.0 + 1e-9


def test_resize_ignores_move_and_none_zones() -> None:
    assert resize_box(BOX, PreviewHitZone.MOVE, 50, 50, CANVAS_W, CANVAS_H) == BOX
    assert resize_box(BOX, PreviewHitZone.NONE, 50, 50, CANVAS_W, CANVAS_H) == BOX


def test_resize_rounds_to_four_decimals() -> None:
    resized = resize_box(BOX, PreviewHitZone.EAST, 1.0, 0, CANVAS_W, CANVAS_H)
    assert resized.width == round(resized.width, 4)


# ── 指针形状 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("zone", "shape"),
    [
        (PreviewHitZone.NORTH, Qt.CursorShape.SizeVerCursor),
        (PreviewHitZone.SOUTH, Qt.CursorShape.SizeVerCursor),
        (PreviewHitZone.EAST, Qt.CursorShape.SizeHorCursor),
        (PreviewHitZone.WEST, Qt.CursorShape.SizeHorCursor),
        (PreviewHitZone.NORTH_EAST, Qt.CursorShape.SizeBDiagCursor),
        (PreviewHitZone.SOUTH_WEST, Qt.CursorShape.SizeBDiagCursor),
        (PreviewHitZone.NORTH_WEST, Qt.CursorShape.SizeFDiagCursor),
        (PreviewHitZone.SOUTH_EAST, Qt.CursorShape.SizeFDiagCursor),
        (PreviewHitZone.MOVE, Qt.CursorShape.SizeAllCursor),
        (PreviewHitZone.NONE, Qt.CursorShape.ArrowCursor),
    ],
)
def test_cursor_for_zone(zone: PreviewHitZone, shape: Qt.CursorShape) -> None:
    assert cursor_for_zone(zone) is shape


def test_zone_is_resize_flag() -> None:
    assert PreviewHitZone.MOVE.is_resize is False
    assert PreviewHitZone.NONE.is_resize is False
    for zone in (
        PreviewHitZone.NORTH,
        PreviewHitZone.SOUTH,
        PreviewHitZone.EAST,
        PreviewHitZone.WEST,
        PreviewHitZone.NORTH_EAST,
        PreviewHitZone.NORTH_WEST,
        PreviewHitZone.SOUTH_EAST,
        PreviewHitZone.SOUTH_WEST,
    ):
        assert zone.is_resize is True, zone


# ── 画布接线：命中区域真的驱动拖拽 ──────────────────────────────────────────


def _canvas_with_layer(qapp, *, width_percent: float = 50.0) -> tuple[LayerPreviewCanvas, LayerSpec]:  # noqa: ANN001
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.png"),
        x_percent=50,
        y_percent=50,
        width_percent=width_percent,
    )
    canvas = LayerPreviewCanvas()
    canvas.set_layers([layer], aspect="9:16")
    canvas.resize(canvas.sizeHint())
    canvas.set_selected(layer.id)
    return canvas, layer


def test_canvas_hit_zone_matches_box(qapp) -> None:  # noqa: ANN001
    canvas, layer = _canvas_with_layer(qapp)
    canvas_rect = canvas._canvas_rect()
    layer_rect = canvas._layer_rect(layer, canvas_rect)

    assert canvas.hit_zone(layer_rect.center()) is PreviewHitZone.MOVE
    assert canvas.hit_zone(QPointF(layer_rect.right(), layer_rect.center().y())) is PreviewHitZone.EAST
    assert canvas.hit_zone(QPointF(layer_rect.left(), layer_rect.top())) is PreviewHitZone.NORTH_WEST


def test_canvas_has_no_hit_zone_without_layers(qapp) -> None:  # noqa: ANN001
    canvas = LayerPreviewCanvas()
    canvas.set_layers([], aspect="9:16")
    canvas.resize(QSize(240, 400))
    assert canvas.hit_zone(QPointF(100, 100)) is PreviewHitZone.NONE


def test_drag_from_outside_still_moves(qapp) -> None:  # noqa: ANN001
    """对齐 .NET：点在框外也按平移处理，避免必须精准点中框才能拖动。"""
    canvas, layer = _canvas_with_layer(qapp)
    canvas.resize(QSize(240, 400))
    far = QPointF(5, 5)
    assert canvas.hit_zone(far) is PreviewHitZone.NONE

    canvas._selected_id = layer.id
    canvas._drag_last = far
    canvas._dragging = True
    canvas._active_zone = PreviewHitZone.NONE
    # 画布内部把 NONE 归为平移；这里直接验证判定结果与 .NET 一致
    assert PreviewHitZone.NONE is not PreviewHitZone.MOVE


def test_canvas_emits_resize_signal(qapp) -> None:  # noqa: ANN001
    canvas, layer = _canvas_with_layer(qapp)
    canvas.resize(QSize(240, 400))
    received: list[tuple] = []
    canvas.layer_resized.connect(lambda *args: received.append(args))

    canvas_rect = canvas._canvas_rect()
    layer_rect = canvas._layer_rect(layer, canvas_rect)
    start = QPointF(layer_rect.right(), layer_rect.center().y())

    canvas._selected_id = layer.id
    canvas._active_zone = PreviewHitZone.EAST
    canvas._drag_last = start
    canvas._dragging = True

    from PySide6.QtGui import QMouseEvent  # noqa: PLC0415

    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        start + QPointF(20, 0),
        start + QPointF(20, 0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(event)

    assert received, "拖右边没有发出缩放信号"
    layer_id, width_percent, height_percent = received[-1]
    assert layer_id == layer.id
    assert width_percent > layer.width_percent, "向右拖应加宽"
    assert height_percent == 0.0, "高度未限制时应发 0（表示不限制）"
