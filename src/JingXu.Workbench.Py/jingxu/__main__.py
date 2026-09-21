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
        del app
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

    if args.self_test or args.import_smoke or args.overlay_smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QMessageBox

    from jingxu.infrastructure.diagnostics import install_crash_logging
    from jingxu.infrastructure.runtime import ToolNotFoundError, require_tool

    install_crash_logging()

    if args.self_test:
        QApplication.instance() or QApplication(["jingxu"])
        report, code = _self_test_report(verify_hashes=args.verify_hashes)
        try:
            _emit_report(json.dumps(report, ensure_ascii=False), args.report_file)
        except OSError as error:
            # 报告写不出去就意味着发布脚本无法取证，必须显式失败。
            report["error"] = f"无法写入报告文件：{error}"
            return 1
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
