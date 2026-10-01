"""取景井预览状态与窗口外壳行为测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.queue import RenderQueue  # noqa: E402
from jingxu.ui import icons  # noqa: E402
from jingxu.ui.shell_window import ShellWindow, WINDOW_MAXIMIZE_PADDING  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _well(qapp):  # noqa: ANN001
    from jingxu.ui.shell_window import GateWell

    return GateWell()


class TestGateWellStates:
    def test_idle_hides_preview(self, qapp) -> None:  # noqa: ANN001
        well = _well(qapp)
        well.set_idle("监视器空闲", "提示")

        assert well.has_preview() is False
        assert well._caption.text() == "监视器空闲"

    def test_loading_then_preview(self, qapp) -> None:  # noqa: ANN001
        well = _well(qapp)
        well.set_loading()
        assert well.has_preview() is False
        assert "生成" in well._caption.text()

        pixmap = QPixmap(200, 100)
        pixmap.fill()
        well.set_preview(pixmap, "预览：a.mp4", "首帧")

        assert well.has_preview() is True
        assert well._caption.text() == "预览：a.mp4"
        assert well._watermark.isHidden() is True
        assert well._preview.isHidden() is False

    def test_idle_after_preview_clears(self, qapp) -> None:  # noqa: ANN001
        well = _well(qapp)
        pixmap = QPixmap(100, 100)
        pixmap.fill()
        well.set_preview(pixmap, "预览", "提示")
        well.set_idle("监视器空闲", "复位")

        assert well.has_preview() is False


class TestWindowChrome:
    def _window(self, tmp_path, monkeypatch):  # noqa: ANN001
        monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
        from jingxu.infrastructure.runtime import find_tool

        ffmpeg = find_tool("ffmpeg")
        ffprobe = find_tool("ffprobe")
        if ffmpeg is None or ffprobe is None:
            pytest.skip("本机未找到 FFmpeg/FFprobe")
        return ShellWindow(ffmpeg, ffprobe, RenderQueue(ffmpeg))

    def test_padding_and_icon_swap_follow_state(self, qapp, tmp_path, monkeypatch) -> None:  # noqa: ANN001
        window = self._window(tmp_path, monkeypatch)
        try:
            window._apply_window_chrome()  # 未最大化：无内边距
            assert window._root.contentsMargins().left() == 0
            assert window._maximize_button.toolTip() == "最大化"

            window.showMaximized()
            window._apply_window_chrome()
            assert window._root.contentsMargins().left() == WINDOW_MAXIMIZE_PADDING
            assert window._maximize_button.toolTip() == "还原"
        finally:
            window.close()

    def test_gate_preview_refresh_without_material(self, qapp, tmp_path, monkeypatch) -> None:  # noqa: ANN001
        window = self._window(tmp_path, monkeypatch)
        try:
            window._refresh_gate_preview()
            assert window._gate_generation == 0  # 无素材时不生成
            assert window._gate_well.has_preview() is False
        finally:
            window.close()

    def test_gate_generation_guard_discards_stale(self, qapp, tmp_path, monkeypatch) -> None:  # noqa: ANN001
        window = self._window(tmp_path, monkeypatch)
        try:
            stale = tmp_path / "stale.jpg"
            stale.write_bytes(b"x")
            window._gate_generation = 5
            window._on_gate_preview(4, str(stale))

            assert not stale.exists()  # 过期结果被丢弃并清理
        finally:
            window.close()

    def test_icons_available_for_swap(self) -> None:
        assert icons.WIN_MAXIMIZE and icons.WIN_RESTORE


@pytest.mark.integration
class TestGatePreviewPipeline:
    def test_gate_preview_renders_first_frame(self, qapp, tmp_path) -> None:  # noqa: ANN001
        """取景井预览链路：真机提取首帧 → 读入 QPixmap → 进入预览态。"""
        import subprocess

        from jingxu.domain.render import RenderSettings
        from jingxu.infrastructure.ffprobe import probe_media
        from jingxu.infrastructure.frame_preview import render_composite_frame
        from jingxu.infrastructure.runtime import find_tool

        ffmpeg = find_tool("ffmpeg")
        ffprobe = find_tool("ffprobe")
        if ffmpeg is None or ffprobe is None:
            pytest.skip("本机未找到 FFmpeg/FFprobe")

        clip = tmp_path / "clip_1.mp4"
        subprocess.run(
            [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=size=320x240:rate=30:duration=1.0",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)],
            check=True, capture_output=True,
        )
        asset = probe_media(clip, ffprobe)
        target = tmp_path / "gate-frame.jpg"

        render_composite_frame(
            ffmpeg,
            asset,
            (),
            RenderSettings(width=360, height=640, fps=30),
            target,
            at_seconds=0.0,
        )

        assert target.is_file() and target.stat().st_size > 500
        pixmap = QPixmap(str(target))
        assert not pixmap.isNull()

        well = _well(qapp)
        well.set_preview(pixmap, "预览：clip_1.mp4", "首帧")
        assert well.has_preview() is True
