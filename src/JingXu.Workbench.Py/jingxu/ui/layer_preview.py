"""图层预览画布：成片画面示意 + 拖拽移动 / 滚轮缩放（与 .NET 的拖拽体验对齐）。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from jingxu.domain.layers import LayerSpec
from jingxu.ui import theme

CANVAS_ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (9, 16),
    "16:9": (16, 9),
    "1:1": (1, 1),
    "3:4": (3, 4),
}


@dataclass(frozen=True, slots=True)
class LayerBox:
    """图层在画面示意中的矩形（相对画布的比例）。"""

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


def layer_box(layer: LayerSpec, canvas_ratio: float) -> LayerBox:
    """按图层参数计算示意矩形（宽度为画布宽度百分比，高度按画布比例缩放）。

    ``height_percent > 0`` 时高度上限为画布高度的百分比（与滤镜图裁剪一致）。
    """
    width = max(0.01, layer.width_percent / 100.0)
    height = max(0.01, min(width * canvas_ratio, 1.0))
    if layer.height_percent > 0.0:
        height = max(0.01, min(height, layer.height_percent / 100.0))
    x = max(0.0, min(layer.x_percent / 100.0 - width / 2, 1.0 - width))
    y = max(0.0, min(layer.y_percent / 100.0 - height / 2, 1.0 - height))
    return LayerBox(x=x, y=y, width=width, height=height)


def percent_from_point(point: QPointF, canvas: QRectF) -> tuple[float, float]:
    """把画布内坐标换算为图层中心百分比（0-100，自动夹取）。"""
    if canvas.width() <= 0 or canvas.height() <= 0:
        return 50.0, 50.0
    x = (point.x() - canvas.left()) / canvas.width() * 100.0
    y = (point.y() - canvas.top()) / canvas.height() * 100.0
    return max(0.0, min(x, 100.0)), max(0.0, min(y, 100.0))


class LayerPreviewCanvas(QWidget):
    """成片画面示意：显示所有启用图层的位置，可拖拽与滚轮缩放。"""

    layer_moved = Signal(str, float, float)
    layer_scaled = Signal(str, float)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self._layers: list[LayerSpec] = []
        self._selected_id: str | None = None
        self._aspect = "9:16"
        self._dragging = False

    # ────────────────────────────── 对外 ──────────────────────────────

    def set_layers(self, layers: list[LayerSpec], *, aspect: str | None = None) -> None:
        self._layers = [layer for layer in layers if layer.enabled]
        if aspect in CANVAS_ASPECTS:
            self._aspect = aspect
        if self._selected_id not in {layer.id for layer in self._layers}:
            self._selected_id = self._layers[-1].id if self._layers else None
        self.update()

    def set_selected(self, layer_id: str | None) -> None:
        self._selected_id = layer_id
        self.update()

    @property
    def aspect(self) -> str:
        return self._aspect

    # ────────────────────────────── 绘制 ──────────────────────────────

    def _canvas_rect(self) -> QRectF:
        margin = 16.0
        available = QRectF(margin, margin, max(self.width() - margin * 2, 10), max(self.height() - margin * 2, 10))
        ratio_w, ratio_h = CANVAS_ASPECTS[self._aspect]
        target_ratio = ratio_w / ratio_h
        width = available.width()
        height = width / target_ratio
        if height > available.height():
            height = available.height()
            width = height * target_ratio
        left = available.left() + (available.width() - width) / 2
        top = available.top() + (available.height() - height) / 2
        return QRectF(left, top, width, height)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        canvas = self._canvas_rect()
        painter.fillRect(canvas, QColor(theme.GATE_WELL))
        painter.setPen(QPen(QColor(theme.BRAND_BLOOM), 1.2))
        painter.drawRect(canvas)

        painter.setPen(QPen(QColor(theme.ON_GATE_MUTED), 1, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(canvas.center().x(), canvas.top()),
            QPointF(canvas.center().x(), canvas.bottom()),
        )
        painter.drawLine(
            QPointF(canvas.left(), canvas.center().y()),
            QPointF(canvas.right(), canvas.center().y()),
        )

        ratio = canvas.height() / canvas.width() if canvas.width() else 1.0
        for layer in self._layers:
            box = layer_box(layer, ratio)
            rect = QRectF(
                canvas.left() + box.x * canvas.width(),
                canvas.top() + box.y * canvas.height(),
                box.width * canvas.width(),
                box.height * canvas.height(),
            )
            selected = layer.id == self._selected_id
            painter.setBrush(QColor(242, 138, 156, 60 if selected else 30))
            painter.setPen(QPen(QColor(theme.BRAND_PRIMARY if selected else theme.INK_MUTED), 1.6 if selected else 1.0))
            painter.drawRect(rect)
            painter.setPen(QColor(theme.ON_GATE))
            painter.drawText(
                rect.adjusted(3, 2, -3, -2),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                layer.display_name[:14],
            )
        painter.end()

    # ────────────────────────────── 交互 ──────────────────────────────

    def _layer_at(self, point: QPointF) -> LayerSpec | None:
        canvas = self._canvas_rect()
        ratio = canvas.height() / canvas.width() if canvas.width() else 1.0
        for layer in reversed(self._layers):
            box = layer_box(layer, ratio)
            rect = QRectF(
                canvas.left() + box.x * canvas.width(),
                canvas.top() + box.y * canvas.height(),
                box.width * canvas.width(),
                box.height * canvas.height(),
            )
            if rect.contains(point):
                return layer
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            layer = self._layer_at(event.position())
            if layer is not None:
                self._selected_id = layer.id
                self._dragging = True
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging and self._selected_id:
            x, y = percent_from_point(event.position(), self._canvas_rect())
            self.layer_moved.emit(self._selected_id, x, y)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        layer = self._layer_at(event.position()) or self._selected_layer()
        if layer is None:
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y() / 120.0
        new_width = max(2.0, min(layer.width_percent + steps * 3.0, 200.0))
        self._selected_id = layer.id
        self.layer_scaled.emit(layer.id, new_width)
        event.accept()

    def _selected_layer(self) -> LayerSpec | None:
        return next((layer for layer in self._layers if layer.id == self._selected_id), None)
