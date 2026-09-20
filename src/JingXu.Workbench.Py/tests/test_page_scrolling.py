"""回归测试：内容较长的页面必须可滚动。

问题背景（用户实测）：「蒙版和贴纸的设置处不能上下滑动」「下面选项够不到」。
原因是 ``layer_page`` 把内容直接堆在页面纵向布局里，没有滚动容器；窗口高度
不足时下方控件（旋转、上淡入、羽化、预设、画幅等）被直接截断，且无法滚动。

这里用静态扫描 + 实际构造双重守住：既检查源码里有 QScrollArea，也确认构造
出来的页面确实带滚动区（避免只 import 不用）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

os_platform = __import__("os").environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

UI_ROOT = Path(__file__).resolve().parents[1] / "jingxu" / "ui"

# 这些页面内容明显超过一屏，必须可滚动
SCROLLABLE_PAGES = {
    "composition_page.py": "composition_page",
    "layer_page.py": "layer_page",
    "subtitle_page.py": "subtitle_page",
    "spider_page.py": "spider_page",
}


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


@pytest.mark.parametrize("filename", sorted(SCROLLABLE_PAGES))
def test_long_page_source_uses_scroll_area(filename: str) -> None:
    """静态检查：源码里必须真的构造 QScrollArea。"""
    source = (UI_ROOT / filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    constructed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "QScrollArea"
    ]
    assert constructed, f"{filename} 没有构造 QScrollArea，长内容会被截断"


@pytest.mark.parametrize("filename", sorted(SCROLLABLE_PAGES))
def test_long_page_configures_resizable_scroll(filename: str) -> None:
    """``setWidgetResizable(True)`` 不能漏，否则内容不会随窗口宽度自适应。"""
    source = (UI_ROOT / filename).read_text(encoding="utf-8")
    assert "setWidgetResizable(True)" in source, f"{filename} 未启用 setWidgetResizable"


def test_layer_page_is_scrollable(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """实际构造蒙版页（用户报告的那一个），确认带滚动区且预览区有高度下限。"""
    from jingxu.domain.layers import LayerKind
    from jingxu.infrastructure.layer_store import LayerStore
    from jingxu.ui.layer_page import LayerPage

    page = LayerPage(
        LayerStore(LayerKind.STICKER, store_path=tmp_path / "l.json"),
        title="贴纸轨道",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
    )
    assert page.findChildren(QScrollArea)
    # 滚动区里 stretch 不再分配高度，必须给下限
    assert page._list.minimumHeight() > 0
    assert page._canvas.minimumHeight() > 0


def test_spider_page_is_scrollable(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from jingxu.infrastructure.spider import SpiderConfigStore, SpiderEnvironment
    from jingxu.ui.spider_page import SpiderPage

    page = SpiderPage(
        store=SpiderConfigStore(tmp_path / "c.json"),
        check_environment=lambda: SpiderEnvironment(available=True, message="ok"),
    )
    assert page.findChildren(QScrollArea)
