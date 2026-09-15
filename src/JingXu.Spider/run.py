"""
Main entry point for Douyin & Kuaishou e-commerce crawler and analyzer.
Default: launches PySide6 desktop GUI.
Pass `--cli` to run in command-line mode.
"""
import sys
import os

# Ensure current directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def main():
    if "--cli" in sys.argv:
        # Run CLI
        sys.argv.remove("--cli")
        from cli import run_cli
        run_cli()
    else:
        # Run PySide6 GUI
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow

        # Support high DPI displays
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
        app = QApplication(sys.argv)
        app.setApplicationName("抖音快手短视频带货商品爬取分析系统")

        window = MainWindow()
        window.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
