"""补充截图：混剪页滚动到「编排」区域（批次/种子/转场/编排预览），记录该状态几何。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[2]  # 仓库根，随仓库移动
ROOT = Path(__file__).resolve().parent.parent
os.environ["JINGXU_DATA_DIRECTORY"] = str(
    Path(os.environ.get("TEMP", str(ROOT))) / "jingxu-promo-appdata"
)
sys.path.insert(0, str(APP / "core"))

SHOTS = ROOT / "shots"
DEMO = ROOT / "demo"

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.queue import RenderQueue  # noqa: E402
from jingxu.infrastructure.runtime import require_tool  # noqa: E402
from jingxu.ui.assets_loader import register_bundled_fonts  # noqa: E402
from jingxu.ui.shell_window import MODULE_COMPOSITION, ShellWindow  # noqa: E402
from jingxu.ui.theme import apply_application_theme  # noqa: E402

PRODUCTS = sorted((DEMO / "products").glob("*.mp4"))


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    app = QApplication.instance() or QApplication(["jingxu"])
    register_bundled_fonts()
    apply_application_theme(app)
    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")
    queue = RenderQueue(ffmpeg)
    win = ShellWindow(ffmpeg, ffprobe, queue)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(1920, 1080)
    win.show()
    pump(app, 1.0)

    win._select_module(MODULE_COMPOSITION)
    win._add_materials([str(path) for path in PRODUCTS])
    win._composition_page._batch_count.setValue(3)
    win._composition_page._clips_per_plan.setText("4")
    win._composition_page._transition_enable.setChecked(True)
    pump(app, 2.0)

    page = win._composition_page
    from PySide6.QtWidgets import QScrollArea

    scroll = page.findChild(QScrollArea)
    content = scroll.widget()
    plan_grid = page._seed.parentWidget()
    bar = scroll.verticalScrollBar()
    for _ in range(120):
        y = plan_grid.mapTo(win, QPoint(0, 0)).y()
        # 页面内容视口位于取景井下方（约 604），把编排网格停在视口上部。
        if y <= 700:
            break
        if bar.value() >= bar.maximum():
            break
        bar.setValue(min(bar.maximum(), bar.value() + 80))
        app.processEvents()
        time.sleep(0.02)
    pump(app, 0.8)

    image = win.grab()
    image.save(str(SHOTS / "composition_settings.png"))
    print("shot composition_settings", image.width(), image.height())

    def rect_of(widget):
        if widget is None or not widget.isVisible():
            return None
        point = widget.mapTo(win, QPoint(0, 0))
        return [int(point.x()), int(point.y()), int(widget.width()), int(widget.height())]

    record = {
        "plan_grid": rect_of(plan_grid),
        "batch_spin": rect_of(page._batch_count),
        "seed_spin": rect_of(page._seed),
        "clips_spin": rect_of(page._clips_per_plan),
        "transition_enable": rect_of(page._transition_enable),
        "transition_seconds": rect_of(page._transition_seconds),
        "plan_summary": rect_of(page._plan_summary),
        "material_list": rect_of(page._material_list),
    }
    geometry_path = SHOTS / "geometry_extra.json"
    geometry_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))

    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
