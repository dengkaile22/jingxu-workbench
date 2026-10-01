"""入口：``python -m jingxu``。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="jingxu", description="炳恒快速混剪 · Python 跨平台版")
    parser.add_argument("--self-test", action="store_true", help="无界面自检后退出（CI 用）")
    parser.add_argument("--import-smoke", metavar="PATH", help="探测单个素材并输出 JSON 报告（无界面）")
    parser.add_argument("--overlay-smoke", metavar="PATH", help="用蒙版素材合成静帧预览并输出 JSON 报告")
    parser.add_argument(
        "--overlay-preset",
        choices=("free", "full", "shape"),
        default="free",
        help="--overlay-smoke 使用的蒙版预设",
    )
    parser.add_argument("--overlay-output", metavar="PATH", help="--overlay-smoke 的图片输出路径")
    parser.add_argument("--verify-hashes", action="store_true", help="自检时校验运行时清单 SHA-256")
    parser.add_argument(
        "--import-check",
        action="store_true",
        help=(
            "检查运行期动态导入的组件是否真的可用（如扫码登录所需的 DrissionPage）。"
            "PyInstaller 静态分析看不到这类导入，缺收集时只在点按钮那一刻才暴露，"
            "因此发布前需要一条可自动化的检查。"
        ),
    )
    parser.add_argument(
        "--ui-probe",
        action="store_true",
        help=(
            "无界面启动主窗口并测量关键控件的真实几何（JSON 报告）。"
            "用于验证 UI 修复确实进了打包产物——源码测试覆盖不到冻结后的情况。"
        ),
    )
    parser.add_argument(
        "--report-file",
        metavar="PATH",
        help=(
            "把自检 JSON 报告写入指定文件（UTF-8）。窗口模式下 stdout 不可靠"
            "（管道关闭时刷新会失败），发布脚本应使用本选项。"
        ),
    )
    return parser.parse_args(argv)


def _run_startup_maintenance() -> None:
    """后台执行启动孤儿清理：临时目录、过期半成品与下载残片。"""
    try:
        from jingxu.infrastructure.diagnostics import cleanup_startup_orphans
        from jingxu.infrastructure.downloader import default_download_directory

        cleanup_startup_orphans(download_directories=[default_download_directory()])
    except Exception:  # noqa: BLE001 - 启动清理失败不应阻断应用启动
        pass


def _import_check_report() -> tuple[dict, int]:
    """逐个真实导入运行期动态依赖，报告可用的组件。

    为什么需要它：扫码登录由 ``from core.browser_manager import BrowserManager``
    在运行期导入，它 ``import DrissionPage``。PyInstaller 的静态分析看不到这种
    动态导入，**默认不会打进去**——实测打包版点「抖音登录」直接报
    ``No module named 'DrissionPage'``，即装机版的扫码登录完全不可用。
    构建脚本据此在发布前给出结论，而不是等用户点按钮。
    """
    import importlib

    from jingxu.infrastructure.spider import (
        _missing_login_modules,
        find_browser,
        spider_directory,
    )

    checks: list[dict[str, object]] = []

    directory = spider_directory()
    checks.append(
        {
            "name": "爬虫源码目录",
            "available": directory is not None,
            "detail": str(directory) if directory is not None else "未找到 cli.py",
        }
    )

    missing = _missing_login_modules()
    checks.append(
        {
            "name": "扫码登录依赖（DrissionPage）",
            "available": not missing,
            "detail": "已就绪" if not missing else "缺失：" + "、".join(missing),
        }
    )

    browser = find_browser()
    checks.append(
        {
            "name": "Chromium 内核浏览器",
            "available": browser is not None,
            "detail": str(browser) if browser is not None else "未找到 Chrome/Edge",
        }
    )

    if directory is not None:
        # 注意：不要在这里再 `import sys` —— 那会让整个函数里的 sys 变成局部名，
        # 于是下面的 `sys.frozen` 在未走本分支时抛 UnboundLocalError。
        added = str(directory) not in sys.path
        if added:
            sys.path.insert(0, str(directory))
        try:
            importlib.import_module("core.browser_manager")
            checks.append(
                {"name": "爬虫浏览器组件", "available": True, "detail": "core.browser_manager"}
            )
        except Exception as error:  # noqa: BLE001 - 报告需要把异常转成结论
            checks.append(
                {
                    "name": "爬虫浏览器组件",
                    "available": False,
                    "detail": f"{type(error).__name__}: {error}",
                }
            )

    report = {
        "schemaVersion": 1,
        "appRoot": str(_app_root_for_report()),
        "frozen": bool(getattr(sys, "frozen", False)),
        "checks": checks,
        "success": all(bool(item["available"]) for item in checks),
    }
    return report, 0 if report["success"] else 1


def _app_root_for_report() -> Path:
    from jingxu.infrastructure.app_paths import app_root

    return app_root()


def _ui_probe_report(*, width: int = 1280, height: int = 900) -> tuple[dict, int]:
    """启动主窗口，测量蒙版/贴纸页预览画布的真实几何。

    为什么需要它：图层预览画布的尺寸与内容问题（"预览框不对"）只在**真实布局**
    里才暴露——单独渲染控件、或只跑源码，都验证不到冻结后的实际观感。
    这里把关键数字变成可自动断言的报告，构建/验收时直接跑。
    """
    from PySide6.QtWidgets import QApplication

    from jingxu.infrastructure.queue import RenderQueue
    from jingxu.infrastructure.runtime import require_tool
    from jingxu.ui.shell_window import MODULE_OVERLAYS, MODULE_STICKERS, ShellWindow
    from jingxu.ui.theme import apply_application_theme

    app = QApplication.instance() or QApplication(["jingxu"])
    apply_application_theme(app)
    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")

    window = ShellWindow(ffmpeg, ffprobe, RenderQueue(ffmpeg))
    window.resize(width, height)
    window.show()
    app.processEvents()

    pages: list[dict[str, object]] = []
    for name, module_id, page in (
        ("蒙版", MODULE_OVERLAYS, window._overlay_page),
        ("贴纸", MODULE_STICKERS, window._sticker_page),
    ):
        window._select_module(module_id)
        for _ in range(5):
            app.processEvents()

        canvas = page._canvas
        rect = canvas._canvas_rect()
        area = max(canvas.width() * canvas.height(), 1)
        entry: dict[str, object] = {
            "page": name,
            "canvasWidget": [canvas.width(), canvas.height()],
            "canvasDrawn": [round(rect.width()), round(rect.height())],
            "spaceUsedPercent": round(rect.width() * rect.height() / area * 100),
            "listHeight": page._list.height(),
            "canvasBottom": canvas.y() + canvas.height(),
            "viewportHeight": page._scroll_area.viewport().height(),
            "showsReferenceRegion": canvas.show_reference,
            "previewHint": page._preview_hint.text(),
            "effectiveCanvasSize": list(page.effective_canvas_size()),
        }
        crop = getattr(page, "_source_crop_preview", None)
        if crop is not None:
            crop_rect = crop._canvas_rect()
            entry["sourceCropCanvas"] = [round(crop_rect.width()), round(crop_rect.height())]
        pages.append(entry)

    subtitle = window._subtitle_page
    subtitle_play_res = [int(subtitle._canvas_width), int(subtitle._canvas_height)]

    window.close()
    report = {
        "schemaVersion": 1,
        "window": [width, height],
        "pages": pages,
        "subtitlePlayRes": subtitle_play_res,
        # 判据：两个页面的画布都要够大（>=200x380），否则用户看不清素材
        "success": all(
            entry["canvasDrawn"][0] >= 200 and entry["canvasDrawn"][1] >= 380
            for entry in pages
        ),
    }
    return report, 0 if report["success"] else 1


def _self_test_report(*, verify_hashes: bool) -> tuple[dict, int]:
    """生成自检报告（对齐 .NET SelfTestReport 字段）并返回退出码。"""
    from jingxu.infrastructure.app_paths import app_root
    from jingxu.infrastructure.runtime import ToolNotFoundError, require_tool
    from jingxu.infrastructure.runtime_manifest import (
        diagnose_components,
        load_manifest,
        missing_required,
    )

    report: dict[str, object] = {
        "schemaVersion": 1,
        "success": False,
        "appRoot": str(app_root()),
        "manifestValid": False,
        "manifestIssues": [],
        "components": [],
        "missingRequired": [],
        "window": False,
        "ffmpeg": None,
        "ffprobe": None,
        "error": None,
    }

    manifest = load_manifest()
    components = diagnose_components(manifest, verify_hashes=verify_hashes)
    report["manifestValid"] = manifest.is_valid
    report["manifestIssues"] = list(manifest.issues)
    report["components"] = [
        {
            "kind": status.kind,
            "displayName": status.display_name,
            "available": status.is_available,
            "required": status.is_required,
            "message": status.message,
            "suggestedAction": status.suggested_action,
            "resolvedPath": status.resolved_path,
            "source": status.source,
        }
        for status in components
    ]
    missing = missing_required(manifest, components)

    try:
        ffmpeg = require_tool("ffmpeg")
        ffprobe = require_tool("ffprobe")
    except ToolNotFoundError as error:
        report["error"] = str(error)
        if "FFmpeg" not in missing:
            missing.append("FFmpeg")
        if "FFprobe" not in missing:
            missing.append("FFprobe")
        report["missingRequired"] = missing
        return report, 1

    report["ffmpeg"] = str(ffmpeg)
    report["ffprobe"] = str(ffprobe)

    try:
        from PySide6.QtWidgets import QApplication

        from jingxu.infrastructure.queue import RenderQueue
        from jingxu.ui.shell_window import ShellWindow

        app = QApplication.instance() or QApplication(["jingxu"])
        queue = RenderQueue(ffmpeg)
        window = ShellWindow(ffmpeg, ffprobe, queue)
        report["window"] = window is not None
        window.close()
        queue.stop()
        app.processEvents()
        app.quit()
    except Exception as error:  # noqa: BLE001 - 自检需要把异常转成报告
        report["error"] = f"界面构建失败：{error}"

    report["missingRequired"] = missing
    report["success"] = not missing and report["error"] is None and bool(report["window"])
    return report, 0 if report["success"] else 1


def _emit_report(payload: str, report_file: str | None) -> None:
    """输出 JSON 报告：优先写文件，stdout 仅作尽力输出。

    窗口模式（PyInstaller ``--windowed``）下没有控制台，管道被关闭时 Python
    刷新 stdout 缓冲会抛 ``OSError: Invalid argument``，因此发布流程必须走
    ``--report-file``。
    """
    if report_file:
        Path(report_file).write_text(payload, encoding="utf-8")
    try:
        print(payload)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.self_test or args.import_smoke or args.overlay_smoke or args.import_check or args.ui_probe:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QMessageBox

    from jingxu.infrastructure.diagnostics import install_crash_logging
    from jingxu.infrastructure.runtime import ToolNotFoundError, require_tool

    install_crash_logging()

    if args.ui_probe:
        report, code = _ui_probe_report()
        try:
            _emit_report(json.dumps(report, ensure_ascii=False), args.report_file)
        except OSError as error:
            report["success"] = False
            report["error"] = f"无法写入报告文件：{error}"
            return 1
        return code

    if args.import_check:
        app = QApplication.instance() or QApplication(["jingxu"])
        report, code = _import_check_report()
        try:
            _emit_report(json.dumps(report, ensure_ascii=False), args.report_file)
        except OSError as error:
            report["success"] = False
            report["error"] = f"无法写入报告文件：{error}"
            app.quit()
            return 1
        app.quit()
        return code

    if args.self_test:
        app = QApplication.instance() or QApplication(["jingxu"])
        report, code = _self_test_report(verify_hashes=args.verify_hashes)
        try:
            _emit_report(json.dumps(report, ensure_ascii=False), args.report_file)
        except OSError as error:
            # 报告写不出去就意味着发布脚本无法取证，必须显式失败。
            report["error"] = f"无法写入报告文件：{error}"
            app.quit()
            return 1
        app.quit()
        return code

    if args.import_smoke:
        from jingxu.application.smoke import import_smoke

        try:
            ffprobe = require_tool("ffprobe")
        except ToolNotFoundError as error:
            _emit_report(json.dumps({"schemaVersion": 1, "error": str(error)}, ensure_ascii=False), args.report_file)
            return 1
        report = import_smoke(Path(args.import_smoke), ffprobe)
        _emit_report(json.dumps(report, ensure_ascii=False), args.report_file)
        return 0 if report.get("asset") else 1

    if args.overlay_smoke:
        from jingxu.application.smoke import overlay_smoke

        try:
            ffmpeg = require_tool("ffmpeg")
            ffprobe = require_tool("ffprobe")
        except ToolNotFoundError as error:
            _emit_report(json.dumps({"schemaVersion": 1, "error": str(error)}, ensure_ascii=False), args.report_file)
            return 1
        source = Path(args.overlay_smoke)
        output = Path(args.overlay_output) if args.overlay_output else source.with_name(f"{source.stem}-overlay.jpg")
        report = overlay_smoke(source, ffmpeg, ffprobe, output, args.overlay_preset)
        _emit_report(json.dumps(report, ensure_ascii=False), args.report_file)
        return 0 if report.get("rendered") else 1

    app = QApplication.instance() or QApplication(["jingxu"])

    result: dict[str, object] = {"ok": False, "ffmpeg": None, "ffprobe": None, "window": False, "error": None}
    try:
        ffmpeg = require_tool("ffmpeg")
        ffprobe = require_tool("ffprobe")
    except ToolNotFoundError as error:
        result["error"] = str(error)
        QMessageBox.critical(None, "缺少 FFmpeg", str(error))
        return 2

    from jingxu.infrastructure.queue import RenderQueue
    from jingxu.ui.assets_loader import register_bundled_fonts
    from jingxu.ui.shell_window import ShellWindow
    from jingxu.ui.theme import apply_application_theme

    # 必须先注册随包字体，再应用主题（主题按族名引用）。
    register_bundled_fonts()
    apply_application_theme(app)
    queue = RenderQueue(ffmpeg)
    window = ShellWindow(ffmpeg, ffprobe, queue)
    result.update(ok=True, ffmpeg=str(ffmpeg), ffprobe=str(ffprobe), window=True)

    threading.Thread(target=_run_startup_maintenance, name="jingxu-startup-cleanup", daemon=True).start()
    queue.start()
    window.show()
    exit_code = app.exec()
    queue.stop()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
