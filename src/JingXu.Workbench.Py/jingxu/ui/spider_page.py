"""选品爬虫页：内嵌 src/JingXu.Spider 的 PySide6 组件（不可用时回退独立窗口）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from jingxu.ui.widgets import Caption, PrimaryButton, SecondaryButton


def find_spider_directory() -> Path | None:
    candidates: list[Path] = []

    configured = os.environ.get("JINGXU_SPIDER_DIR", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    from jingxu.infrastructure.app_paths import search_roots

    for parent in search_roots():
        candidates.append(parent / "runtime" / "spider")          # 便携包布局
        candidates.append(parent / "src" / "JingXu.Spider")
        candidates.append(parent / "JingXu.Spider")

    for candidate in candidates:
        if (candidate / "run.py").is_file():
            return candidate
    return None


def extract_video_urls(items: list) -> list[str]:
    """从爬虫结果条目中提取视频链接（去重、保序）。"""
    seen: set[str] = set()
    urls: list[str] = []
    for item in items or []:
        url = ""
        if isinstance(item, dict):
            url = str(item.get("video_url") or item.get("videoUrl") or "")
        else:
            url = str(getattr(item, "video_url", "") or "")
        # 兼容 nested items（RetainedProduct.items）
        nested = getattr(item, "items", None)
        if isinstance(nested, (list, tuple)):
            for child in nested:
                child_url = str(getattr(child, "video_url", "") or "")
                if child_url and child_url not in seen:
                    seen.add(child_url)
                    urls.append(child_url)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


class SpiderPage(QWidget):
    """懒加载爬虫组件：导入失败时给出安装提示与独立窗口入口。"""

    videos_discovered = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 16, 20, 16)
        self._loaded = False
        self._widget = None
        self._last_urls: list[str] = []

        self._placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.addStretch(1)
        self._message = Caption("正在加载选品爬虫组件…")
        self._message.setWordWrap(True)
        placeholder_layout.addWidget(self._message)

        send = SecondaryButton("把最近结果送入下载")
        send.clicked.connect(self.send_last_results)
        placeholder_layout.addWidget(send, alignment=Qt.AlignmentFlag.AlignLeft)

        button = PrimaryButton("打开独立爬虫界面")
        button.clicked.connect(self._launch_standalone)
        placeholder_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        placeholder_layout.addStretch(1)
        self._layout.addWidget(self._placeholder)

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        directory = find_spider_directory()
        if directory is None:
            self._message.setText(
                "未在仓库或 runtime/spider 中找到选品爬虫。请保留爬虫源码目录，或使用独立界面。"
            )
            return

        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))

        try:
            from ecommerce_spider import EcommerceCrawlerWidget  # type: ignore[import-not-found]
        except Exception as error:  # noqa: BLE001 - 依赖缺失时给出可操作提示
            self._message.setText(
                f"爬虫组件加载失败：{error}\n请安装依赖：pip install -e \".[spider]\"（DrissionPage 等）。"
            )
            return

        try:
            widget = EcommerceCrawlerWidget()
        except Exception as error:  # noqa: BLE001
            self._message.setText(f"爬虫界面初始化失败：{error}")
            return

        self._layout.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._layout.addWidget(widget)
        self._widget = widget
        self._loaded = True

        # 抓取完成后自动把视频链接送入下载页（对齐 .NET「发送到下载」）。
        try:
            widget.crawl_finished.connect(self._on_crawl_finished)
        except Exception:  # noqa: BLE001 - 组件版本不匹配时不阻断加载
            pass

    def _on_crawl_finished(self, retained: list, items: list) -> None:
        urls = extract_video_urls(list(items or []) + list(retained or []))
        self._last_urls = urls
        if urls:
            self.videos_discovered.emit(urls)

    def send_last_results(self) -> None:
        """把最近一次抓取结果送入下载（无结果时提示）。"""
        if not self._last_urls:
            QMessageBox.information(self, "暂无结果", "还没有抓取到可下载的视频链接。")
            return
        self.videos_discovered.emit(list(self._last_urls))

    def _launch_standalone(self) -> None:
        directory = find_spider_directory()
        if directory is None:
            QMessageBox.information(self, "未找到选品爬虫", "未找到选品爬虫入口 run.py。")
            return
        try:
            subprocess.Popen([sys.executable, str(directory / "run.py")], cwd=str(directory))
        except OSError as error:
            QMessageBox.warning(self, "启动失败", str(error))
