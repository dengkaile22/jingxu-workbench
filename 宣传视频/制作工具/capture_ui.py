"""启动真实应用（offscreen 1920×1080），注入演示数据，逐页截图 + 记录关键控件几何。

产物：
  shots/<page>.png        每页全窗口截图（1920×1080）
  shots/geometry.json     关键控件在窗口坐标系中的矩形（供宣传片做高亮标注）
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

APP = Path(__file__).resolve().parents[2]  # 仓库根，随仓库移动
ROOT = Path(__file__).resolve().parent.parent
# 注意：不能用 QT_QPA_PLATFORM=offscreen——offscreen 平台插件枚举不到系统字体，
# 中文会全部渲染成方框。这里用真实 Windows 平台 + WA_DontShowOnScreen（窗口不上屏）。
# 演示数据写到系统临时目录：截图里不会出现仓库路径名，也不会污染真实用户数据。
os.environ["JINGXU_DATA_DIRECTORY"] = str(
    Path(os.environ.get("TEMP", str(ROOT))) / "jingxu-promo-appdata"
)
sys.path.insert(0, str(APP / "core"))

SHOTS = ROOT / "shots"
DEMO = ROOT / "demo"

# 输出重定向到文件：shell 管道对此类长任务的捕获不稳定，直接自己写日志。
LOG_PATH = ROOT / "logs" / "capture.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
LOG = LOG_PATH.open("w", encoding="utf-8", buffering=1)
sys.stdout = LOG
sys.stderr = LOG

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QTableWidgetItem  # noqa: E402

from jingxu.infrastructure.audio_library import probe_audio  # noqa: E402
from jingxu.infrastructure.queue import JobState, RenderQueue  # noqa: E402
from jingxu.infrastructure.runtime import require_tool  # noqa: E402
from jingxu.infrastructure.subtitles import load_subtitle_file  # noqa: E402
from jingxu.ui.assets_loader import register_bundled_fonts  # noqa: E402
from jingxu.ui.shell_window import (  # noqa: E402
    MODULE_AUDIO,
    MODULE_COMPOSITION,
    MODULE_DOWNLOADS,
    MODULE_OVERLAYS,
    MODULE_QUEUE,
    MODULE_SETTINGS,
    MODULE_SPIDER,
    MODULE_STICKERS,
    MODULE_SUBTITLES,
    ShellWindow,
)
from jingxu.ui.theme import apply_application_theme  # noqa: E402

GEOMETRY: dict[str, dict[str, list[int]]] = {}

PRODUCTS = sorted((DEMO / "products").glob("*.mp4"))
MASKS = sorted((DEMO / "masks").glob("*.mp4"))
STICKERS = sorted((DEMO / "stickers").glob("*.png"))
AUDIO = sorted((DEMO / "audio").glob("*.mp3"))
SRT = DEMO / "subtitles" / "演示字幕.srt"


def pump(app: QApplication, seconds: float = 0.25) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def pump_until(app: QApplication, predicate, timeout: float = 20.0, label: str = "") -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    print(f"  [warn] 等待超时: {label}")
    return False


def find_button(widget, text: str):
    for button in widget.findChildren(QAbstractButton):
        if button.text().strip() == text and button.isVisible():
            return button
    return None


def rect_of(win, widget) -> list[int] | None:
    if widget is None or not widget.isVisible():
        return None
    point = widget.mapTo(win, QPoint(0, 0))
    return [int(point.x()), int(point.y()), int(widget.width()), int(widget.height())]


def collect(page_key: str, win, entries: dict[str, object]) -> None:
    record: dict[str, list[int]] = {}
    for name, widget in entries.items():
        rect = rect_of(win, widget)
        if rect is not None:
            record[name] = rect
    GEOMETRY[page_key] = record


def shot(app: QApplication, win, page_key: str, *, settle: float = 0.6) -> None:
    pump(app, settle)
    image = win.grab()
    SHOTS.mkdir(parents=True, exist_ok=True)
    image.save(str(SHOTS / f"{page_key}.png"))
    print(f"  [shot] {page_key}: {image.width()}x{image.height()}")


def guarded(label: str, fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - 演示脚本：单页失败不拖垮其余
        print(f"  [error] {label} 注入失败：")
        traceback.print_exc()


# ────────────────────────── 各页注入 ──────────────────────────


def fill_composition(app: QApplication, win) -> None:
    win._add_materials([str(path) for path in PRODUCTS])
    page = win._composition_page
    page._batch_count.setValue(3)
    page._seed.setValue(2026)
    page._clips_per_plan.setText("4")
    page._transition_enable.setChecked(True)
    pump_until(app, lambda: win._gate_well.has_preview(), timeout=30, label="取景井首帧")
    pump(app, 1.2)
    collect(
        "composition",
        win,
        {
            "import_button": find_button(page, "导入素材"),
            "clear_button": find_button(page, "清理素材"),
            "enqueue_button": find_button(page, "加入队列"),
            "material_list": win._material_list,
            "gate_well": win._gate_well,
            "plan_block": page._seed.parentWidget(),
            "plan_summary": page._plan_summary,
            "top_strip": page._batch_count.parentWidget(),
        },
    )
    shot(app, win, "composition")


def fill_spider(app: QApplication, win) -> None:
    page = win._spider_page
    accounts = "\n".join(
        [
            "美妆种草日记=https://v.douyin.com/iRNBho6d/",
            "好物严选馆=https://v.douyin.com/iRNBho72/",
            "零食研究所=https://v.kuaishou.com/s/8XkQm2A",
            "宝妈优选=https://v.douyin.com/iRNBho8k/",
            "居家好物志=https://v.kuaishou.com/s/9LmZ3Bc",
        ]
    )
    page._import_text.setPlainText(accounts)
    page._apply_import()
    tasks = page._task_widgets
    tasks["likes"]["enabled"].setChecked(True)
    tasks["likes"]["threshold"].setValue(5000)
    tasks["total"]["enabled"].setChecked(True)
    tasks["total"]["threshold"].setValue(2)
    tasks["accounts"]["enabled"].setChecked(True)
    tasks["accounts"]["threshold"].setValue(3)
    pump(app, 0.4)
    collect(
        "spider",
        win,
        {
            "accounts_table": page._accounts_table,
            "run_button": page._run_button,
            "schedule_button": page._schedule_button,
            "send_button": page._send_button,
            "tasks_table": page._tasks_table,
            "add_account_button": find_button(page, "+ 添加账号"),
        },
    )
    shot(app, win, "spider")


def fill_subtitles(app: QApplication, win) -> None:
    page = win._subtitle_page
    if PRODUCTS:
        page.set_source_material(PRODUCTS[0])
    load_button = getattr(page, "_region_load", None)
    if load_button is not None:
        load_button.click()
        pump_until(app, lambda: page._region_canvas.has_frame(), timeout=20, label="字幕预览帧")
    else:
        pump(app, 1.0)
    page._cues = load_subtitle_file(SRT)
    page._refresh_table()
    pump(app, 0.4)
    collect(
        "subtitles",
        win,
        {
            "recognize_button": find_button(page, "识别当前选中素材"),
            "ocr_button": find_button(page, "OCR 检测硬字幕"),
            "rows_table": page._table,
            "region_canvas": page._region_canvas,
        },
    )
    shot(app, win, "subtitles")


def fill_overlays(app: QApplication, win) -> None:
    page = win._overlay_page
    page._library.add(MASKS)
    page._refresh_library()
    for mask in MASKS:
        page._store.add(mask)
    page.refresh_from_store()
    pump(app, 0.4)
    if page._preview_button is not None:
        page._preview_button.click()
        pump_until(
            app,
            lambda: page._preview_image.pixmap() is not None and not page._preview_image.pixmap().isNull(),
            timeout=30,
            label="蒙版合成预览",
        )
    collect(
        "overlays",
        win,
        {
            "track_list": page._list,
            "preview_image": page._preview_image,
            "library_list": page._library_list,
            "preview_button": page._preview_button,
        },
    )
    shot(app, win, "overlays")


def fill_stickers(app: QApplication, win) -> None:
    page = win._sticker_page
    page._library.add(STICKERS)
    page._refresh_library()
    for sticker in STICKERS[:3]:
        try:
            page._store.add(sticker)
        except Exception as error:  # noqa: BLE001
            print("    （贴纸轨道跳过）", sticker.name, error)
    page.refresh_from_store()
    pump(app, 0.4)
    collect(
        "stickers",
        win,
        {
            "track_list": page._list,
            # 贴纸页无「合成预览」区（蒙版专属），这两个控件不存在。
            "preview_image": getattr(page, "_preview_image", None),
            "library_list": page._library_list,
        },
    )
    shot(app, win, "stickers")


def fill_audio(app: QApplication, win) -> None:
    page = win._audio_page
    ffprobe_path = require_tool("ffprobe")
    tracks = [probe_audio(path, ffprobe_path) for path in AUDIO]
    page._library.add(tracks)
    page._reload()
    pump(app, 0.4)
    collect(
        "audio",
        win,
        {
            "library_list": getattr(page, "_tracks_view", None) or getattr(page, "_list_view", None),
            "import_button": find_button(page, "导入音频…"),
        },
    )
    shot(app, win, "audio")


def fill_downloads(app: QApplication, win) -> None:
    page = win._download_page
    page._url_input.setPlainText(
        "\n".join(
            [
                "https://www.douyin.com/video/7418529637418529637",
                "https://www.douyin.com/video/7418529637418529638",
                "https://v.kuaishou.com/s/8XkQm2A",
                "https://www.bilibili.com/video/BV1xx411c7mD",
            ]
        )
    )
    table = page._table
    table.blockSignals(True)
    rows = [
        ("1.mp4", "口红测评合集.mp4", "12.4 MB", "已完成", "抖音"),
        ("2.mp4", "面霜开箱.mp4", "8.1 MB", "已完成", "抖音"),
        ("3.mp4", "保温杯直播间.mp4", "24.6 MB", "下载中 62%", "快手"),
        ("4.mp4", "空气炸锅美食.mp4", "—", "排队中", "B 站"),
    ]
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column, text in enumerate(row):
            table.setItem(row_index, column, QTableWidgetItem(text))
    table.blockSignals(False)
    pump(app, 0.4)
    collect(
        "downloads",
        win,
        {
            "url_input": page._url_input,
            "start_button": find_button(page, "开始下载"),
            "send_button": find_button(page, "发送已下载到混剪素材"),
            "table": table,
        },
    )
    shot(app, win, "downloads")


def fill_queue(app: QApplication, win) -> None:
    queue = win._queue
    queue.pause()
    # 字幕页已截图完毕：清空字幕轨，避免「字幕时间轴超出素材时长」让入队被静默拦下，
    # 导致队列页截出空列表。
    win._subtitle_page._cues = []
    win._subtitle_page._refresh_table()
    previous_batches = win._composition_page._batch_count.value()
    win._composition_page._batch_count.setValue(4)
    win._enqueue()
    win._composition_page._batch_count.setValue(previous_batches)
    jobs = queue.jobs
    print(f"  [queue] 入队任务数：{len(jobs)}，状态：{win._composition_page.status_text() if hasattr(win._composition_page, 'status_text') else 'n/a'}")
    order = [job.id for job in jobs]
    with queue._lock:
        internal = [queue._jobs[job_id] for job_id in order]
        snapshots = []
        if internal:
            running = internal[0]
            queue._transition_locked(running, JobState.PREPARING)
            queue._transition_locked(running, JobState.RUNNING, message="渲染中")
            running.percent = 62.0
        if len(internal) >= 3:
            done = internal[2]
            queue._transition_locked(done, JobState.PREPARING)
            queue._transition_locked(done, JobState.RUNNING)
            queue._transition_locked(done, JobState.FINALIZING)
            queue._transition_locked(done, JobState.COMPLETED, message="已完成")
            done.percent = 100.0
        if len(internal) >= 4:
            failed = internal[3]
            queue._transition_locked(failed, JobState.PREPARING)
            queue._transition_locked(failed, JobState.RUNNING)
            queue._transition_locked(failed, JobState.FAILED, message="编码器不可用 · 可重试")
            failed.can_retry = True
        snapshots = [job.snapshot() for job in internal]
    for snapshot in snapshots:
        queue._notify("updated", snapshot)
    pump(app, 0.5)
    collect(
        "queue",
        win,
        {
            "pause_button": getattr(win._queue_page, "_pause", None),
        },
    )
    shot(app, win, "queue")


def fill_settings(app: QApplication, win) -> None:
    pump_until(
        app,
        lambda: "正在" not in win._settings_page._encoder_available.text(),
        timeout=40,
        label="编码器探测",
    )
    pump(app, 0.5)
    settings = win._settings_page
    collect(
        "settings",
        win,
        {
            "refresh_button": find_button(settings, "重新检测"),
            "open_data": find_button(settings, "打开数据目录"),
        },
    )
    shot(app, win, "settings")


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

    steps = [
        ("混剪页", MODULE_COMPOSITION, fill_composition),
        ("选品页", MODULE_SPIDER, fill_spider),
        ("字幕页", MODULE_SUBTITLES, fill_subtitles),
        ("蒙版页", MODULE_OVERLAYS, fill_overlays),
        ("贴纸页", MODULE_STICKERS, fill_stickers),
        ("音频页", MODULE_AUDIO, fill_audio),
        ("下载页", MODULE_DOWNLOADS, fill_downloads),
        ("设置页", MODULE_SETTINGS, fill_settings),
    ]
    for label, module_id, filler in steps:
        print(f"[填充] {label}")
        win._select_module(module_id)
        pump(app, 0.3)
        guarded(label, lambda f=filler: f(app, win))

    print("[填充] 队列页")
    win._select_module(MODULE_QUEUE)
    pump(app, 0.3)
    guarded("队列页", lambda: fill_queue(app, win))

    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / "geometry.json").write_text(
        json.dumps(GEOMETRY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("完成：", SHOTS, flush=True)
    # 后台预览线程可能仍持有 ffmpeg 子进程，直接强制退出避免挂起。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
