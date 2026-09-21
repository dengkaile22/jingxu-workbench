"""高 DPI / 布局截断检查：按设计规格 13.3「125%/150% 缩放下无控件截断」。

规格原文：「1920×1080、1600×900 和 125%/150% 缩放下无控件截断。」

**关于缩放模型（重要）**：主题字号与控件高度都用**逻辑像素**（Qt 设备无关像素）
给定，两者随风缩放比同步放大，因此「字号 30 + 标题栏 44」这类组合在所有缩放比
下比例不变。真正的截断风险来自两处：

1. **固定高度小于自身字体行高**——与缩放比无关，在 1x 下就已经切字；
2. **内容总高超过可视高且没有滚动兜底**——窗口不够高时下半部分直接看不到。

因此本文件断言这两件事，而不是把同一个量乘以缩放比再比较（那样是恒真式）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget  # noqa: E402

from jingxu.ui import theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _line_height(font) -> int:  # noqa: ANN001
    return QFontMetrics(font).height()


def _iter_widgets(root: QWidget):  # noqa: ANN202
    """只遍历 QWidget（QLayout 也有 children 但没有 height）。"""
    for child in root.findChildren(QWidget):
        yield child


# ── 1) 固定高度必须容得下自身字体（与缩放比无关，1x 就能判定）──────────────


def test_title_bar_fits_wordmark(qapp) -> None:  # noqa: ANN001
    """标题栏固定高 44px，品牌字「炳恒」字号 30px：行高必须放得下。"""
    line = _line_height(theme.body_font(30))
    assert line <= theme.TITLE_BAR_HEIGHT, (
        f"标题栏文字行高 {line}px 超过栏高 {theme.TITLE_BAR_HEIGHT}px，会被纵向截断"
    )


def test_default_body_font_fits_row(qapp) -> None:  # noqa: ANN001
    """正文 12px 的行高应小于常规单行控件高度（28px）。"""
    assert _line_height(theme.body_font(12)) <= 28


def test_mono_font_fits_input_row(qapp) -> None:  # noqa: ANN001
    """等宽 12px 的行高应小于输入框常规高度。"""
    assert _line_height(theme.mono_font(12)) <= 28


def test_all_fixed_heights_fit_their_fonts(qapp) -> None:  # noqa: ANN001
    """实例化真实标题栏与队列条，逐个比对「高度 vs 行高」。

    只检查**会渲染文字**的控件：细进度条（高 5–6px、``setTextVisible(False)``）
    这类纯装饰条没有文字可截断，按字体度量判它会得出假阳性。
    """
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QProgressBar

    from jingxu.infrastructure.queue import RenderQueue
    from jingxu.ui.shell_window import ShellWindow

    window = ShellWindow(Path("ffmpeg"), Path("ffprobe"), RenderQueue(Path("ffmpeg")))
    window.resize(1600, 900)
    window.show()
    qapp.processEvents()

    text_widgets = (QLabel, QAbstractButton, QLineEdit, QComboBox)
    offenders: list[str] = []
    for widget in _iter_widgets(window):
        height = widget.height()
        if height <= 0:
            continue
        if isinstance(widget, QProgressBar):
            # 只有显示百分比文字时才可能截断
            if not widget.isTextVisible():
                continue
        elif not isinstance(widget, text_widgets):
            continue
        line = QFontMetrics(widget.font()).height()
        if line > height:
            offenders.append(
                f"{type(widget).__name__}({widget.objectName() or '-'}) 高 {height} < 行高 {line}"
            )

    window.close()
    assert offenders == [], f"文字被容器高度截断：{offenders[:6]}"


# ── 2) 参数很长的页面必须有滚动兜底 ─────────────────────────────────────────


def _mask_page(tmp_path: Path):  # noqa: ANN202
    from jingxu.domain.layers import LayerKind
    from jingxu.infrastructure.layer_store import LayerStore
    from jingxu.ui.layer_page import LayerPage

    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "o.json")
    source = tmp_path / "m.png"
    source.write_bytes(b"stub")
    store.add(source)
    return LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
    )


@pytest.mark.parametrize("size", [(1920, 1080), (1600, 900), (1280, 720)])
def test_layer_page_has_scroll_fallback(qapp, tmp_path: Path, size: tuple[int, int]) -> None:  # noqa: ANN001
    """蒙版/贴纸参数区很长，窗口再矮也要能滚动到，不能被裁掉。"""
    page = _mask_page(tmp_path)
    page.resize(*size)
    page.show()
    qapp.processEvents()

    areas = page.findChildren(QScrollArea)
    assert areas, "参数很长的页面必须有滚动区，否则矮窗口下内容直接缺失"
    assert areas[0].viewport().height() > 0

    page.close()


def test_long_pages_content_can_scroll(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """滚动区的可滚动范围必须大于 0，否则等于没有滚动。"""
    page = _mask_page(tmp_path)
    page.resize(1280, 720)
    page.show()
    qapp.processEvents()

    area = page.findChildren(QScrollArea)[0]
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0, "内容比视口高时应出现可滚动范围"

    page.close()


def test_shell_has_no_stray_placeholder_buttons(qapp) -> None:  # noqa: ANN001
    """设计规格第 12 节：不得保留占位按钮、空命令或「稍后实现」界面。"""
    from PySide6.QtWidgets import QAbstractButton

    from jingxu.infrastructure.queue import RenderQueue
    from jingxu.ui.shell_window import ShellWindow

    window = ShellWindow(Path("ffmpeg"), Path("ffprobe"), RenderQueue(Path("ffmpeg")))
    window.resize(1600, 900)
    window.show()
    qapp.processEvents()

    suspicious: list[str] = []
    keywords = ("稍后", "TODO", "待实现", "占位", "coming soon", "暂未")
    for button in window.findChildren(QAbstractButton):
        text = (button.text() or "").strip()
        if any(key in text for key in keywords):
            suspicious.append(f"{type(button).__name__}({text})")

    window.close()
    assert suspicious == [], f"存在占位式按钮：{suspicious}"
