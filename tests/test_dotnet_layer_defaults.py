"""导入蒙版默认值与预览画布尺寸：逐值对齐 .NET。

用户要求「改动和 .NET 一致」，因此这里把两侧的**具体取值**钉死：

* 导入蒙版默认 = .NET ``CreateGhostOverlayPreset``（上半红框区 + 28% 透明 + 中间→上渐变）；
* 画布尺寸优先级 = .NET ``StickerEditorViewModel.GetEffectiveCanvasSize``
  （固定比例 > 跟随混剪真实尺寸 > 画幅模式参考尺寸）；
* 旧项目里已保存的图层**不得**被新默认值改写。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import (  # noqa: E402
    GHOST_OVERLAY_FEATHER,
    GHOST_OVERLAY_OPACITY,
    GHOST_OVERLAY_TOP_FADE,
    IMPORTED_MASK_BOUNDS,
    LayerAspectMode,
    LayerFixedRatio,
    LayerKind,
    imported_mask_layer,
)
from jingxu.infrastructure.layer_store import LayerStore  # noqa: E402
from jingxu.ui.layer_page import PREVIEW_ASPECT_SIZES, LayerPage  # noqa: E402
from jingxu.ui.layer_preview import IMPORTED_MASK_BOUNDS as PREVIEW_REFERENCE_BOUNDS  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page(tmp_path: Path, kind: LayerKind = LayerKind.OVERLAY, name: str = "layers.json") -> LayerPage:
    store = LayerStore(kind, store_path=tmp_path / name)
    source = tmp_path / "素材.png"
    source.write_bytes(b"stub")
    store.add(source)
    return LayerPage(store, title="t", file_filter="*", hint="测试")


# ── 导入蒙版默认值（.NET CreateGhostOverlayPreset） ──────────────────────────


def test_constants_match_dotnet_overlay_models() -> None:
    """取值必须与 .NET ``OverlayModels.cs`` 的常量逐值一致。"""
    assert IMPORTED_MASK_BOUNDS == (0.05, 0.05, 0.90, 0.42)
    assert GHOST_OVERLAY_OPACITY == 0.28
    assert GHOST_OVERLAY_TOP_FADE == 1.0
    assert GHOST_OVERLAY_FEATHER == 0.28


def test_preview_reference_region_uses_same_bounds() -> None:
    """预览里的暗红参考区与新建蒙版的落点必须是同一组数字。"""
    assert PREVIEW_REFERENCE_BOUNDS == IMPORTED_MASK_BOUNDS


def test_imported_mask_layer_converts_bounds_to_center() -> None:
    """「左上角 + 宽高」→「中心 + 宽高百分比」的换算必须正确。

    x 中心 = 0.05 + 0.90/2 = 0.50；y 中心 = 0.05 + 0.42/2 = 0.26。
    """
    layer = imported_mask_layer(Path("mask.mp4"))

    assert layer.kind is LayerKind.OVERLAY
    assert layer.x_percent == pytest.approx(50.0)
    assert layer.y_percent == pytest.approx(26.0)
    assert layer.width_percent == pytest.approx(90.0)
    assert layer.height_percent == 0.0  # 不限制高度
    assert layer.opacity == pytest.approx(GHOST_OVERLAY_OPACITY)
    assert layer.top_fade == pytest.approx(GHOST_OVERLAY_TOP_FADE)
    assert layer.feather == pytest.approx(GHOST_OVERLAY_FEATHER)
    assert layer.fit == "fill_crop"


def test_store_add_applies_ghost_defaults_for_overlay(tmp_path: Path) -> None:
    """蒙版导入即套用 .NET 叠影默认（不是不透明铺满）。"""
    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "o.json")
    source = tmp_path / "m.png"
    source.write_bytes(b"stub")

    layer = store.add(source)

    assert layer.opacity == pytest.approx(0.28)
    assert layer.top_fade == pytest.approx(1.0)
    assert layer.feather == pytest.approx(0.28)
    assert layer.y_percent == pytest.approx(26.0)
    assert layer.width_percent == pytest.approx(90.0)


def test_store_add_keeps_plain_defaults_for_sticker(tmp_path: Path) -> None:
    """贴纸没有红框区概念，保持朴素默认（不透明、无渐变）。"""
    store = LayerStore(LayerKind.STICKER, store_path=tmp_path / "s.json")
    source = tmp_path / "s.png"
    source.write_bytes(b"stub")

    layer = store.add(source)

    assert layer.opacity == pytest.approx(1.0)
    assert layer.top_fade == 0.0
    assert layer.feather == 0.0
    assert layer.kind is LayerKind.STICKER


def test_existing_layers_are_not_rewritten(tmp_path: Path) -> None:
    """已保存的图层必须原样读回——新默认只作用于**新增**，绝不改老项目。"""
    path = tmp_path / "o.json"
    store = LayerStore(LayerKind.OVERLAY, store_path=path)
    source = tmp_path / "m.png"
    source.write_bytes(b"stub")
    layer = store.add(source)
    store.replace(layer.with_changes(opacity=1.0, top_fade=0.0, feather=0.0, y_percent=50.0))

    reopened = LayerStore(LayerKind.OVERLAY, store_path=path)

    assert len(reopened.layers) == 1
    assert reopened.layers[0].opacity == pytest.approx(1.0)
    assert reopened.layers[0].top_fade == 0.0
    assert reopened.layers[0].y_percent == pytest.approx(50.0)


# ── 预览画布尺寸优先级（.NET GetEffectiveCanvasSize） ────────────────────────


def test_canvas_size_follows_composition_dimensions(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「跟随混剪画幅」要用混剪页的真实尺寸，不能只取比例。"""
    page = _page(tmp_path)

    page.set_canvas_aspect("9:16", width=720, height=1280)

    assert page.effective_canvas_size() == (720, 1280)
    assert page._composition_size == (720, 1280)


def test_canvas_size_falls_back_to_ratio_preset(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """壳层没给尺寸时退回该比例的参考尺寸。"""
    page = _page(tmp_path)

    page.set_canvas_aspect("16:9")

    assert page.effective_canvas_size() == PREVIEW_ASPECT_SIZES["16:9"]


def test_canvas_size_uses_custom_composition_size(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """自定义宽高也必须原样生效（.NET 同样直接用混剪页给的像素尺寸）。"""
    page = _page(tmp_path)

    page.set_canvas_aspect("custom", width=1080, height=1441)

    assert page.effective_canvas_size() == (1080, 1441)


def test_fixed_ratio_overrides_aspect_mode(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """固定比例优先于画幅模式——.NET ``GetEffectiveCanvasSize`` 的第一优先级。"""
    page = _page(tmp_path)
    layer = page._store.layers[0]
    page._store.replace(layer.with_changes(fixed_aspect_ratio=LayerFixedRatio.RATIO_4X3.value))
    page.refresh_from_store()

    assert page.effective_canvas_size() == (1440, 1080)


def test_uncertain_fixed_ratio_falls_through(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """固定比例为「无」时继续按画幅模式走。"""
    page = _page(tmp_path)
    layer = page._store.layers[0]
    page._store.replace(layer.with_changes(fixed_aspect_ratio=LayerFixedRatio.NONE.value))
    page.refresh_from_store()
    page.set_canvas_aspect("1:1", width=1080, height=1080)

    assert page.effective_canvas_size() == (1080, 1080)


def test_independent_aspect_mode_ignores_composition_once_selected(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """用户选了独立画幅后，混剪页改设置不得把编辑视角拽走。"""
    page = _page(tmp_path)
    index = page._aspect_mode.findData(LayerAspectMode.RATIO_16X9.value)
    page._aspect_mode.setCurrentIndex(index)

    page.set_canvas_aspect("9:16", width=720, height=1280)

    assert page.effective_canvas_size() == PREVIEW_ASPECT_SIZES["16:9"]


def test_follow_composition_recovers_after_switch_back(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """切回「跟随混剪画幅」要恢复混剪页尺寸（与 _composition_aspect 分开保存的目的）。"""
    page = _page(tmp_path)
    page.set_canvas_aspect("9:16", width=720, height=1280)
    page._aspect_mode.setCurrentIndex(page._aspect_mode.findData(LayerAspectMode.RATIO_1X1.value))
    assert page.effective_canvas_size() == PREVIEW_ASPECT_SIZES["1:1"]

    page._aspect_mode.setCurrentIndex(
        page._aspect_mode.findData(LayerAspectMode.FOLLOW_COMPOSITION.value)
    )
    page.set_canvas_aspect("9:16", width=720, height=1280)

    assert page.effective_canvas_size() == (720, 1280)


def test_composition_canvas_signal_is_emitted(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """混剪页改画幅要发信号，否则预览跟不上（此前完全没有这条链路）。"""
    from jingxu.ui.composition_page import CompositionPage  # noqa: PLC0415

    page = CompositionPage()
    received: list[int] = []
    page.canvas_changed.connect(lambda: received.append(1))

    page._refresh_aspect_state()

    assert received, "改画幅未发出 canvas_changed 信号"


def test_custom_size_controls_trigger_refresh(qapp) -> None:  # noqa: ANN001
    """自定义宽高此前没有接槽：改尺寸既不刷新描述也不通知预览。"""
    from jingxu.ui.composition_page import CompositionPage  # noqa: PLC0415

    page = CompositionPage()
    received: list[int] = []
    page.canvas_changed.connect(lambda: received.append(1))
    page._aspect_enable.setChecked(True)
    page._aspect.setCurrentIndex(page._aspect.findData("custom"))
    received.clear()

    page._custom_width.setValue(720)

    assert received, "改自定义宽度没有触发画幅刷新"


def test_shell_syncs_real_composition_size_to_layer_pages(qapp, monkeypatch) -> None:  # noqa: ANN001
    """壳层必须把**真实成片尺寸**同步给蒙版/贴纸页（对齐 .NET SyncCompositionCanvas）。

    只传比例不够：混剪页可以是 720×1280 或任意自定义尺寸，
    「跟随混剪画幅」的预览与合成预览都要按真实尺寸走。
    """
    from jingxu.infrastructure.queue import RenderQueue  # noqa: PLC0415
    from jingxu.infrastructure.runtime import require_tool  # noqa: PLC0415
    from jingxu.ui.shell_window import ShellWindow  # noqa: PLC0415
    from jingxu.ui.theme import apply_application_theme  # noqa: PLC0415

    apply_application_theme(QApplication.instance())
    ffmpeg = require_tool("ffmpeg")
    window = ShellWindow(ffmpeg, require_tool("ffprobe"), RenderQueue(ffmpeg))
    try:
        monkeypatch.setattr(window._composition_page, "canvas_size", lambda: (720, 1280))
        window._composition_page.canvas_changed.emit()

        assert window._overlay_page.effective_canvas_size() == (720, 1280)
        assert window._sticker_page.effective_canvas_size() == (720, 1280)
    finally:
        window.close()


def test_shell_syncs_canvas_size_to_subtitle_page(qapp, monkeypatch) -> None:  # noqa: ANN001
    """字幕页的 ASS ``PlayResX/Y`` 必须跟随成片画幅。

    回归：``SubtitlePage.set_canvas_size`` 此前**没有任何调用者**，PlayRes 恒为
    1080×1920；画幅是 720×1280 或自定义时导出的 ASS 字号/边距基准就是错的。
    """
    from jingxu.infrastructure.queue import RenderQueue  # noqa: PLC0415
    from jingxu.infrastructure.runtime import require_tool  # noqa: PLC0415
    from jingxu.infrastructure.subtitles import build_ass  # noqa: PLC0415
    from jingxu.domain.subtitles import SubtitleCue, SubtitleStyle  # noqa: PLC0415
    from jingxu.ui.shell_window import ShellWindow  # noqa: PLC0415
    from jingxu.ui.theme import apply_application_theme  # noqa: PLC0415

    apply_application_theme(QApplication.instance())
    ffmpeg = require_tool("ffmpeg")
    window = ShellWindow(ffmpeg, require_tool("ffprobe"), RenderQueue(ffmpeg))
    try:
        monkeypatch.setattr(window._composition_page, "canvas_size", lambda: (720, 1280))
        window._composition_page.canvas_changed.emit()

        page = window._subtitle_page
        assert (page._canvas_width, page._canvas_height) == (720, 1280)

        script = build_ass(
            [SubtitleCue(start=0.0, end=1.0, text="测试")],
            SubtitleStyle(),
            page._canvas_width,
            page._canvas_height,
        )
        assert "PlayResX: 720" in script
        assert "PlayResY: 1280" in script
    finally:
        window.close()


def test_composition_aspect_change_updates_subtitle_playres(qapp) -> None:  # noqa: ANN001
    """真实链路：在混剪页改自定义宽高，字幕页 PlayRes 要跟着变。"""
    from jingxu.infrastructure.queue import RenderQueue  # noqa: PLC0415
    from jingxu.infrastructure.runtime import require_tool  # noqa: PLC0415
    from jingxu.ui.shell_window import ShellWindow  # noqa: PLC0415
    from jingxu.ui.theme import apply_application_theme  # noqa: PLC0415

    apply_application_theme(QApplication.instance())
    ffmpeg = require_tool("ffmpeg")
    window = ShellWindow(ffmpeg, require_tool("ffprobe"), RenderQueue(ffmpeg))
    try:
        page = window._composition_page
        page._aspect_enable.setChecked(True)
        page._aspect.setCurrentIndex(page._aspect.findData("custom"))
        page._custom_width.setValue(720)
        page._custom_height.setValue(1280)
        qapp.processEvents()

        subtitle = window._subtitle_page
        assert (subtitle._canvas_width, subtitle._canvas_height) == (720, 1280)
    finally:
        window.close()
