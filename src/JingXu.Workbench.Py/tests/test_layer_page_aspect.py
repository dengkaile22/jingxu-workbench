"""图层页画幅模式与宽高比锁定（offscreen Qt）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import (  # noqa: E402
    LayerAspectMode,
    LayerFixedRatio,
    LayerKind,
)
from jingxu.infrastructure.layer_store import LayerStore  # noqa: E402
from jingxu.ui.layer_page import LayerPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page(tmp_path: Path) -> LayerPage:
    store = LayerStore(LayerKind.STICKER, store_path=tmp_path / "stickers.json")
    source = tmp_path / "贴纸.png"
    source.write_bytes(b"stub")
    store.add(source)
    return LayerPage(store, title="贴纸轨道", file_filter="*", hint="测试", ffmpeg=Path("ffmpeg"))


def _select_ratio(page: LayerPage, ratio: LayerFixedRatio) -> None:
    index = page._fixed_ratio.findData(ratio.value)
    assert index >= 0
    page._fixed_ratio.setCurrentIndex(index)


def test_aspect_mode_defaults_to_follow_composition(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    assert page._selected_aspect_mode() is LayerAspectMode.FOLLOW_COMPOSITION
    assert "跟随混剪" in page._ratio_hint.text()


def test_aspect_mode_switch_changes_preview_canvas(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    index = page._aspect_mode.findData(LayerAspectMode.RATIO_1X1.value)
    page._aspect_mode.setCurrentIndex(index)

    assert page._aspect == "1:1"
    assert "1:1 方形" in page._ratio_hint.text()


def test_follow_mode_resumes_composition_aspect(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """切到独立画幅再切回跟随，应恢复混剪页画幅而不是永久停留在独立值。"""
    page = _page(tmp_path)
    page.set_canvas_aspect("16:9")

    page._aspect_mode.setCurrentIndex(page._aspect_mode.findData(LayerAspectMode.RATIO_1X1.value))
    assert page._aspect == "1:1"

    page._aspect_mode.setCurrentIndex(
        page._aspect_mode.findData(LayerAspectMode.FOLLOW_COMPOSITION.value)
    )
    assert page._aspect == "16:9"


def test_composition_aspect_update_ignored_in_independent_mode(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """用户选了独立画幅后，混剪页改设置不应把编辑视角拽走。"""
    page = _page(tmp_path)
    page._aspect_mode.setCurrentIndex(page._aspect_mode.findData(LayerAspectMode.RATIO_1X1.value))

    page.set_canvas_aspect("16:9")

    assert page._aspect == "1:1"
    # 但跟随模式下仍能拿到最新画幅。
    page._aspect_mode.setCurrentIndex(
        page._aspect_mode.findData(LayerAspectMode.FOLLOW_COMPOSITION.value)
    )
    assert page._aspect == "16:9"


def test_locking_ratio_adjusts_height_and_persists(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._width.setValue(40)
    _select_ratio(page, LayerFixedRatio.RATIO_1X1)

    layer = page._store.layers[0]
    assert layer.fixed_aspect_ratio == LayerFixedRatio.RATIO_1X1.value
    # 1:1 且中心锚点 (50,50)：宽度 40% → 高度 40%。
    assert layer.width_percent == pytest.approx(40.0, abs=1.0)
    assert layer.height_percent == pytest.approx(40.0, abs=1.0)
    assert page._height.value() == int(round(layer.height_percent))


def test_width_change_drives_height_when_locked(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    _select_ratio(page, LayerFixedRatio.RATIO_1X1)

    page._width.setValue(25)

    layer = page._store.layers[0]
    assert layer.width_percent == pytest.approx(25.0, abs=1.0)
    assert layer.height_percent == pytest.approx(25.0, abs=1.0)


def test_height_change_drives_width_when_locked(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    _select_ratio(page, LayerFixedRatio.RATIO_1X1)

    page._height.setValue(20)

    layer = page._store.layers[0]
    assert layer.height_percent == pytest.approx(20.0, abs=1.0)
    assert layer.width_percent == pytest.approx(20.0, abs=1.0)


def test_unlocked_width_change_leaves_height_alone(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._height.setValue(40)
    before = page._store.layers[0].height_percent

    page._width.setValue(60)

    assert page._store.layers[0].height_percent == pytest.approx(before)


def test_unlocking_keeps_current_size(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    _select_ratio(page, LayerFixedRatio.RATIO_1X1)
    page._width.setValue(30)
    locked_height = page._store.layers[0].height_percent

    _select_ratio(page, LayerFixedRatio.NONE)

    layer = page._store.layers[0]
    assert layer.fixed_aspect_ratio == LayerFixedRatio.NONE.value
    assert layer.height_percent == pytest.approx(locked_height)
    assert "未锁定宽高比" in page._ratio_hint.text()


def test_ratio_roundtrip_through_page_reload(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """锁定值落盘后重新打开页面应恢复（走 store 往返）。"""
    page = _page(tmp_path)
    _select_ratio(page, LayerFixedRatio.RATIO_9X16)

    reopened = LayerPage(
        LayerStore(LayerKind.STICKER, store_path=tmp_path / "stickers.json"),
        title="贴纸轨道",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
    )
    layer = reopened._store.layers[0]
    assert layer.fixed_aspect_ratio == LayerFixedRatio.RATIO_9X16.value
    assert reopened._selected_fixed_ratio() is LayerFixedRatio.RATIO_9X16


def test_row_text_shows_ratio_marker(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    _select_ratio(page, LayerFixedRatio.RATIO_1X1)

    item = page._list.item(0)
    assert item is not None
    assert "锁定 1:1" in item.text()
