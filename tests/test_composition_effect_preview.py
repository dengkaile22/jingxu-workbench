"""混剪页「效果预览」：对齐 .NET ``CompositionView`` 的同名区块。

.NET 在「蒙版覆盖」之后有一个独立区块：选预览主片 → 「刷新合成预览」→
用**真实滤镜链**渲染一张叠层静帧，并明确提示"不会用蒙版缩略图冒充合成预览"。

Python 原先把这个能力只放在蒙版页（同一个 ``render_composite_frame``），
混剪页没有入口。本文件守住新增入口的行为。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from jingxu.infrastructure.ffprobe import probe_media  # noqa: E402
from jingxu.infrastructure.queue import RenderQueue  # noqa: E402
from jingxu.infrastructure.runtime import find_tool, require_tool  # noqa: E402
from jingxu.ui.composition_page import CompositionPage  # noqa: E402
from jingxu.ui.shell_window import ShellWindow  # noqa: E402
from jingxu.ui.theme import apply_application_theme  # noqa: E402
from jingxu.ui.widgets import SectionHeader  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


# ── 结构：区块存在、顺序在「蒙版覆盖」之后 ──────────────────────────────────


def test_section_present_after_overlay_cover(qapp) -> None:  # noqa: ANN001
    page = CompositionPage()
    titles = [header.text() for header in page.findChildren(SectionHeader)]

    assert "效果预览" in titles, f"缺少「效果预览」区块（当前：{titles}）"
    assert titles.index("效果预览") > titles.index("蒙版覆盖"), "区块顺序与 .NET 不一致"


def test_preview_uses_a_real_canvas_label(qapp) -> None:  # noqa: ANN001
    """预览位是固定尺寸的画布占位（与 .NET 的 220 高预览区等价）。"""
    page = CompositionPage()
    label = page._overlay_preview_image

    assert isinstance(label, QLabel)
    assert label.size().toTuple() == (216, 384)
    assert label.text() == "生成中或暂无预览"


def test_refresh_button_emits_request(qapp) -> None:  # noqa: ANN001
    page = CompositionPage()
    received: list[int] = []
    page.overlay_preview_requested.connect(lambda: received.append(1))

    page._overlay_preview_button.click()

    assert received, "点「刷新效果预览」没有发出请求"


def test_preview_size_follows_output_settings(qapp) -> None:  # noqa: ANN001
    """预览画幅与帧率取自「统一比例」与「输出帧率」，不是写死的。"""
    page = CompositionPage()
    width, height, fps = page.preview_render_size()

    assert (width, height) == page.canvas_size()
    assert fps > 0


def test_no_material_gives_readable_hint(qapp, monkeypatch) -> None:  # noqa: ANN001
    """没有素材时给可读提示，而不是崩溃或空白。"""
    apply_application_theme(qapp)
    ffmpeg = find_tool("ffmpeg")
    if ffmpeg is None:
        pytest.skip("本机没有 FFmpeg")

    window = ShellWindow(ffmpeg, require_tool("ffprobe"), RenderQueue(ffmpeg))
    try:
        window._composition_page.set_overlay_preview(None, "")
        window._composition_page.overlay_preview_requested.emit()
        qapp.processEvents()

        assert "导入素材" in window._composition_page._overlay_preview_status.text()
    finally:
        window.close()


# ── 真实渲染：图片确实生成，临时文件归位 ────────────────────────────────────


@pytest.mark.integration
def test_renders_composite_with_real_media(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """真机：带一条蒙版跑一次效果预览，必须产出非空图片。

    这条是本次改动的核心回归——只断言"按钮发信号"不足以证明滤镜链真的跑通。
    """
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("本机没有 FFmpeg/FFprobe")

    base = tmp_path / "base.mp4"
    mask = tmp_path / "mask.png"
    _make_clip(ffmpeg, base)
    _make_image(ffmpeg, mask)

    apply_application_theme(qapp)
    window = ShellWindow(ffmpeg, ffprobe, RenderQueue(ffmpeg))
    try:
        window._materials[window._group].append(probe_media(base, ffprobe))
        window._composition_page.set_materials(window._assets)
        window._overlay_page._store.add(mask)
        window._overlay_page.refresh_from_store()
        qapp.processEvents()

        page = window._composition_page
        page.overlay_preview_requested.emit()
        _wait_until_idle(qapp, page)

        assert page._overlay_preview_status.text() == "已刷新效果预览。"
        pixmap = page._overlay_preview_image.pixmap()
        assert pixmap is not None and not pixmap.isNull(), "效果预览没有生成图片"

        produced = window._overlay_preview_path
        assert produced is not None
        assert Path(produced).is_file()
        assert Path(produced).stat().st_size > 0
    finally:
        window.close()


def _make_clip(ffmpeg: Path, target: Path) -> None:
    subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x480:d=1",
            "-pix_fmt", "yuv420p", str(target),
        ],
        check=True,
    )


def _make_image(ffmpeg: Path, target: Path) -> None:
    subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=200x300:d=1",
            "-frames:v", "1", str(target),
        ],
        check=True,
    )


def _wait_until_idle(qapp, page: CompositionPage, timeout: float = 60.0) -> None:  # noqa: ANN001
    """轮询到按钮重新可用（渲染在后台线程完成）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if page._overlay_preview_button.isEnabled():
            return
        time.sleep(0.1)
    raise AssertionError("效果预览超时未完成")
