"""字幕区域框选画布：在预览帧上拖拽选择字幕区域。

对齐 .NET 字幕实验室的「预览与区域选择」：导入视频后可在画面上框选字幕区域，
而不必手填百分比。Python 版此前只有百分比输入框，用户很难填对——这是
「字幕功能不用」的主要原因。

坐标系约定：区域用**相对整帧的归一化比例**（0–1）表示，与
``SubtitleRemovalSpec`` 的 ``x_percent`` / ``y_percent`` / ``width_percent`` /
``height_percent`` 一一对应。画面按原始宽高比居中显示，因此归一化值与控件像素
之间需要经「显示矩形」换算。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from jingxu.ui import theme

# 命中判定半径（像素）：靠近边/角即可拖拽缩放
HANDLE_MARGIN = 10
# 允许的最小区域（归一化），避免拖成零面积后无法再选中
MIN_REGION = 0.02
# 区域默认值（与 SubtitleRemovalSpec 默认一致：底部整宽一条）
DEFAULT_REGION = (0.08, 0.76, 0.84, 0.18)


class SubtitleRegionCanvas(QWidget):
    """预览帧 + 可拖拽的字幕区域选框。"""

    region_changed = Signal(float, float, float, float)
    region_committed = Signal(float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self._pixmap: QPixmap | None = None
        self._placeholder = "导入视频后可在此框选字幕区域"
        self._region = DEFAULT_REGION
        self._drag_mode: str | None = None
        self._drag_origin = QPoint()
        self._drag_start_region = DEFAULT_REGION

    # ────────────────────────────── 数据 ──────────────────────────────

    def set_frame(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def has_frame(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def region(self) -> tuple[float, float, float, float]:
        return self._region

    def set_region(self, x: float, y: float, width: float, height: float) -> None:
        self._region = _clamp_region((x, y, width, height))
        self.update()

    # ────────────────────────────── 几何 ──────────────────────────────

    def _display_rect(self) -> QRect:
        """画面在控件内的显示矩形（保持原始宽高比并居中）。"""
        if not self.has_frame():
            return self.rect()
        assert self._pixmap is not None
        frame_w = self._pixmap.width()
        frame_h = self._pixmap.height()
        if frame_w <= 0 or frame_h <= 0:
            return self.rect()
        scale = min(self.width() / frame_w, self.height() / frame_h)
        width = max(1, int(frame_w * scale))
        height = max(1, int(frame_h * scale))
        left = (self.width() - width) // 2
        top = (self.height() - height) // 2
        return QRect(left, top, width, height)

    def _region_rect(self) -> QRect:
        display = self._display_rect()
        x, y, width, height = self._region
        return QRect(
            display.left() + int(round(x * display.width())),
            display.top() + int(round(y * display.height())),
            max(1, int(round(width * display.width()))),
            max(1, int(round(height * display.height()))),
        )

    def _mode_at(self, point: QPoint) -> str | None:
        """判断落点属于哪个拖拽模式：move / nw / ne / sw / se / None。"""
        rect = self._region_rect()
        near_left = abs(point.x() - rect.left()) <= HANDLE_MARGIN
        near_right = abs(point.x() - rect.right()) <= HANDLE_MARGIN
        near_top = abs(point.y() - rect.top()) <= HANDLE_MARGIN
        near_bottom = abs(point.y() - rect.bottom()) <= HANDLE_MARGIN

        if near_left and near_top:
            return "nw"
        if near_right and near_top:
            return "ne"
        if near_left and near_bottom:
            return "sw"
        if near_right and near_bottom:
            return "se"
        if near_left:
            return "w"
        if near_right:
            return "e"
        if near_top:
            return "n"
        if near_bottom:
            return "s"
        if rect.contains(point):
            return "move"
        return None

    # ────────────────────────────── 交互 ──────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() != Qt.MouseButton.LeftButton or not self.has_frame():
            super().mousePressEvent(event)
            return
        point = event.position().toPoint()
        self._drag_mode = self._mode_at(point)
        if self._drag_mode is None:
            # 空白处按下：以该点为中心新建一个小区域，方便快速框选
            display = self._display_rect()
            if display.contains(point):
                nx = (point.x() - display.left()) / max(1, display.width())
                ny = (point.y() - display.top()) / max(1, display.height())
                self.set_region(nx - 0.2, ny - 0.06, 0.4, 0.12)
                self._drag_mode = "move"
                self.region_changed.emit(*self._region)
        self._drag_origin = point
        self._drag_start_region = self._region
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        point = event.position().toPoint()
        if self._drag_mode is None:
            self._update_cursor(point)
            return
        display = self._display_rect()
        if display.width() <= 0 or display.height() <= 0:
            return
        dx = (point.x() - self._drag_origin.x()) / display.width()
        dy = (point.y() - self._drag_origin.y()) / display.height()
        x, y, width, height = self._drag_start_region

        if self._drag_mode == "move":
            x += dx
            y += dy
        else:
            if "w" in self._drag_mode:
                x += dx
                width -= dx
            if "e" in self._drag_mode:
                width += dx
            if "n" in self._drag_mode:
                y += dy
                height -= dy
            if "s" in self._drag_mode:
                height += dy

        self._region = _clamp_region((x, y, width, height))
        self.region_changed.emit(*self._region)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_mode is not None:
            self._drag_mode = None
            self.region_committed.emit(*self._region)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _update_cursor(self, point: QPoint) -> None:
        mode = self._mode_at(point)
        cursors = {
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
            "w": Qt.CursorShape.SizeHorCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "move": Qt.CursorShape.SizeAllCursor,
        }
        self.setCursor(cursors.get(mode or "", Qt.CursorShape.CrossCursor))

    # ────────────────────────────── 绘制 ──────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        display = self._display_rect()

        if self.has_frame():
            assert self._pixmap is not None
            painter.drawPixmap(display, self._pixmap)
        else:
            painter.fillRect(display, QColor(theme.GATE_WELL))
            painter.setPen(QColor(theme.ON_GATE_MUTED))
            painter.drawText(display, Qt.AlignmentFlag.AlignCenter, self._placeholder)

        # 区域遮罩：区域外压暗，区域本身画描边与四角把手
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        region = self._region_rect()
        painter.setPen(QPen(QColor(theme.BRAND_PRIMARY), 2))
        painter.drawRect(region)
        painter.fillRect(region, QColor(232, 111, 138, 48))

        handle = 4
        painter.setBrush(QColor(theme.BRAND_PRIMARY))
        for corner in (
            region.topLeft(),
            region.topRight(),
            region.bottomLeft(),
            region.bottomRight(),
        ):
            painter.drawRect(
                QRect(corner.x() - handle, corner.y() - handle, handle * 2, handle * 2)
            )
        painter.end()


def _clamp_region(
    region: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """把区域收进 [0,1] 并保证最小尺寸与右/下边界不越界。"""
    x, y, width, height = region
    width = max(MIN_REGION, min(width, 1.0))
    height = max(MIN_REGION, min(height, 1.0))
    x = max(0.0, min(x, 1.0 - width))
    y = max(0.0, min(y, 1.0 - height))
    return (round(x, 4), round(y, 4), round(width, 4), round(height, 4))
