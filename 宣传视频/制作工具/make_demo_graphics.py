"""用 Qt 生成演示贴纸与蒙版形状（PNG，带透明通道）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
)


ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
STICKERS = DEMO / "stickers"
MASKS = DEMO / "masks"


def _save(image: QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path)):
        raise RuntimeError(f"无法保存 {path}")
    print("OK", path.name)


def make_sticker(
    name: str,
    text: str,
    *,
    fill: str,
    edge: str,
    text_color: str = "#FFFFFF",
    size: tuple[int, int] = (520, 200),
    tilt: float = -5.0,
    accent: str | None = None,
) -> None:
    width, height = size
    image = QImage(width + 40, height + 40, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.translate((width + 40) / 2, (height + 40) / 2)
    painter.rotate(tilt)

    rect = QRectF(-width / 2, -height / 2, width, height)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor(fill))
    gradient.setColorAt(1.0, QColor(accent or fill))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor(edge), 10))
    painter.drawRoundedRect(rect, 44, 44)

    font = QFont("Microsoft YaHei")
    font.setBold(True)
    font.setPixelSize(int(height * 0.48))
    painter.setFont(font)
    painter.setPen(QColor(text_color))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    _save(image, STICKERS / f"{name}.png")


def make_star(name: str, points: int = 5, outer: float = 120, inner: float = 52, color: str = "#FFC53D") -> None:
    from math import cos, pi, sin

    size = int(outer * 2 + 40)
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(size / 2, size / 2)
    painter.setBrush(QColor(color))
    painter.setPen(QPen(QColor("#FFFFFF"), 8))

    path_points = []
    for index in range(points * 2):
        radius = outer if index % 2 == 0 else inner
        angle = -pi / 2 + index * pi / points
        path_points.append(QPointF(cos(angle) * radius, sin(angle) * radius))
    from PySide6.QtGui import QPolygonF

    painter.drawPolygon(QPolygonF(path_points))
    painter.end()
    _save(image, STICKERS / f"{name}.png")


def make_circle_mask(name: str, size: int = 640) -> None:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor("#FFFFFF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(0, 0, size, size))
    painter.end()
    _save(image, MASKS / f"{name}.png")


def make_roundrect_mask(name: str, width: int = 560, height: int = 900) -> None:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor("#FFFFFF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, width, height), 120, 120)
    painter.end()
    _save(image, MASKS / f"{name}.png")


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyhbd.ttc")
    make_sticker("贴纸_爆款", "爆款", fill="#FF4D4F", edge="#FFFFFF", accent="#C8181C")
    make_sticker("贴纸_限时秒杀", "限时秒杀", fill="#FF8A00", edge="#FFFFFF", accent="#E85D04", size=(560, 200))
    make_sticker("贴纸_关注有礼", "关注有礼", fill="#E86F8A", edge="#FFFFFF", accent="#C34A68", size=(560, 200))
    make_sticker("贴纸_品质严选", "品质严选", fill="#2F9E68", edge="#FFFFFF", accent="#1F7A50", size=(560, 200), tilt=4.0)
    make_star("贴纸_五角星")
    make_circle_mask("shape_circle")
    make_roundrect_mask("shape_roundrect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
