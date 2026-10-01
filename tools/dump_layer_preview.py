"""把图层预览画布离屏渲染成 PNG，用于核对实际观感（诊断脚本）。

用法：python tools/dump_layer_preview.py [输出目录]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "core"))

from PySide6.QtCore import QPoint, QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.ui.layer_preview import LayerPreviewCanvas  # noqa: E402


def make_source(directory: Path) -> Path:
    """造一张可辨认的测试素材（红底 + 白框 + 对角斜线）。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "蒙版素材.png"
    image = QImage(QSize(240, 360), QImage.Format.Format_RGB32)
    image.fill(QColor("#D9534F"))
    painter = QPainter(image)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawRect(8, 8, 224, 344)
    painter.drawLine(8, 8, 232, 352)
    painter.drawLine(232, 8, 8, 352)
    painter.end()
    image.save(str(path))
    return path


def render(size: QSize, layers: list[LayerSpec], aspect: str, out: Path) -> None:
    canvas = LayerPreviewCanvas()
    canvas.resize(size)
    canvas.set_layers(layers, aspect=aspect)
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor("#F5F2EC"))
    painter = QPainter(image)
    canvas.render(painter, QPoint(0, 0))
    painter.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(out))
    rect = canvas._canvas_rect()
    used = (rect.width() * rect.height()) / (size.width() * size.height()) * 100
    print(
        f"{out.name}: widget={size.width()}x{size.height()} aspect={canvas.aspect} "
        f"canvas={rect.width():.0f}x{rect.height():.0f} ({used:.0f}% of widget) "
        f"hint={canvas.sizeHint().width()}x{canvas.sizeHint().height()}"
    )


def hint_for(aspect: str) -> QSize:
    canvas = LayerPreviewCanvas()
    canvas.set_layers([], aspect=aspect)
    return canvas.sizeHint()


def main() -> int:
    app = QApplication.instance() or QApplication(["preview-dump"])  # noqa: F841
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get("TEMP", ".")) / "jingxu-preview-dump"
    source = make_source(out_dir / "assets")
    print("source =", source, source.stat().st_size, "bytes")

    overlay = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=source,
        x_percent=50,
        y_percent=35,
        width_percent=80,
        height_percent=50,
    )
    sticker = LayerSpec(
        kind=LayerKind.STICKER,
        source=source,
        x_percent=70,
        y_percent=70,
        width_percent=25,
        opacity=0.75,
        rotation_degrees=12,
    )
    missing = LayerSpec(kind=LayerKind.STICKER, source=Path("不存在的贴纸.png"))

    render(hint_for("9:16"), [overlay], "9:16", out_dir / "overlay-9x16.png")
    render(hint_for("9:16"), [sticker], "9:16", out_dir / "sticker-9x16.png")
    render(hint_for("9:16"), [missing], "9:16", out_dir / "missing-source.png")
    render(hint_for("16:9"), [overlay], "16:9", out_dir / "overlay-16x9.png")
    render(hint_for("1:1"), [sticker], "1:1", out_dir / "sticker-1x1.png")
    render(QSize(950, 420), [overlay, sticker], "9:16", out_dir / "two-layers-wide-row.png")

    print("dumped to", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
