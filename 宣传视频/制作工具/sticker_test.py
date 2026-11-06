"""单独测试贴纸页填充，日志写入文件。"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

APP = Path(__file__).resolve().parents[2]  # 仓库根，随仓库移动
ROOT = Path(__file__).resolve().parent.parent
os.environ["JINGXU_DATA_DIRECTORY"] = str(ROOT / "appdata-sticker-test")
sys.path.insert(0, str(APP / "core"))

LOG = ROOT / "logs" / "sticker-test.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
handle = LOG.open("w", encoding="utf-8")


def log(*args) -> None:
    handle.write(" ".join(str(a) for a in args) + "\n")
    handle.flush()


from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.queue import RenderQueue  # noqa: E402
from jingxu.infrastructure.runtime import require_tool  # noqa: E402
from jingxu.ui.assets_loader import register_bundled_fonts  # noqa: E402
from jingxu.ui.shell_window import MODULE_STICKERS, ShellWindow  # noqa: E402
from jingxu.ui.theme import apply_application_theme  # noqa: E402

STICKERS = sorted((ROOT / "demo" / "stickers").glob("*.png"))


def main() -> None:
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
    app.processEvents()
    win._select_module(MODULE_STICKERS)
    app.processEvents()
    page = win._sticker_page
    log("stickers:", [p.name for p in STICKERS])
    try:
        added = page._library.add(STICKERS)
        log("library.add ->", added)
    except Exception:
        log("library.add 异常:\n" + traceback.format_exc())
    try:
        page._refresh_library()
        log("refresh_library OK")
    except Exception:
        log("refresh_library 异常:\n" + traceback.format_exc())
    for sticker in STICKERS[:3]:
        try:
            layer = page._store.add(sticker)
            log("store.add OK", sticker.name, layer.id)
        except Exception:
            log("store.add 异常:\n" + traceback.format_exc())
    try:
        page.refresh_from_store()
        log("refresh_from_store OK, layers =", page._list.count())
    except Exception:
        log("refresh_from_store 异常:\n" + traceback.format_exc())
    try:
        if page._preview_button is not None:
            log("preview_button enabled =", page._preview_button.isEnabled())
            page._preview_button.click()
            log("preview clicked")
    except Exception:
        log("preview click 异常:\n" + traceback.format_exc())
    for _ in range(60):
        app.processEvents()
        time.sleep(0.03)
    image = win.grab()
    out = ROOT / "shots" / "stickers.png"
    image.save(str(out))
    log("saved", out, image.width(), image.height())
    handle.close()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
