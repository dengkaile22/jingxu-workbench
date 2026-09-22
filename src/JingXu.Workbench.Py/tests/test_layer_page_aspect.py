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


# ── 贴纸页与蒙版页的分工（对齐 .NET）────────────────────────────────────────


def _sticker_page(tmp_path: Path, name: str = "sticker-tracks.json"):  # noqa: ANN202
    from jingxu.infrastructure.sticker_library import StickerLibrary

    library = StickerLibrary(tmp_path / "sticker-library.json")
    source = tmp_path / "贴纸.png"
    source.write_bytes(b"stub")
    library.add([source])
    return LayerPage(
        LayerStore(LayerKind.STICKER, store_path=tmp_path / name),
        title="贴纸轨道",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
        sticker_library=library,
    )


def test_sticker_page_has_material_library(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """贴纸页应是「素材库 + 轨道」两段式：轨道从库里「添加」生成。

    Python 版此前没有素材库，只能靠「导入素材」直接建轨道，用起来像蒙版页的
    简化版——用户反馈「贴纸功能怎么和蒙版一样了」。
    """
    page = _sticker_page(tmp_path)

    assert page._is_sticker is True
    assert page._library_list.count() == 1
    assert "贴纸库 1 项" in page._library_caption.text()

    page._library_list.setCurrentRow(0)
    page._add_track_from_library()

    assert page._list.count() == 1
    assert "已从素材库添加轨道" in page._status.text()


def test_sticker_page_hides_mask_only_controls(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """贴纸只保留画法（位置/尺寸/透明度/旋转/宽高比），不显示蒙版专属参数。"""
    page = _sticker_page(tmp_path)

    for attribute in (
        "_feather",
        "_fit",
        "_split_position",
        "_remove_black",
        "_mix_audio",
        "_source_crop_canvas",
        "_source_crop_y",
        "_start_clip",
    ):
        assert getattr(page, attribute) is None, f"{attribute} 不应出现在贴纸页"

    for attribute in ("_x", "_y", "_width", "_height", "_opacity", "_rotation", "_fixed_ratio"):
        assert getattr(page, attribute) is not None, f"{attribute} 应保留"


def test_sticker_page_has_no_composition_preview(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「合成预览」渲染主片+蒙版静帧，是蒙版专属；.NET 贴纸页没有该区块。"""
    page = _sticker_page(tmp_path)
    assert page._preview_button is None


def test_mask_page_keeps_its_own_controls(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """蒙版页参数集必须保持不变，改造不能伤到它。"""
    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "overlay-tracks.json")
    source = tmp_path / "蒙版.png"
    source.write_bytes(b"stub")
    store.add(source)
    page = LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
    )

    assert page._is_sticker is False
    # 蒙版页现在也有素材库（对齐 .NET「蒙版素材库」）：它是「蒙版随机替换」的抽取来源。
    # 但蒙版专属参数控件必须仍在，不能被素材库改造挤掉。
    assert page._library_list is not None
    assert "蒙版素材库" in page._library_caption.text()
    for attribute in ("_feather", "_fit", "_split_position", "_remove_black"):
        assert getattr(page, attribute) is not None
    assert page._preview_button is not None


def test_random_library_toggle_reports_empty_library(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """开启随机替换但素材库为空时要提示，否则渲染时静默不替换。"""
    from jingxu.infrastructure.sticker_library import StickerLibrary

    library = StickerLibrary(tmp_path / "empty-library.json")
    page = LayerPage(
        LayerStore(LayerKind.STICKER, store_path=tmp_path / "tracks.json"),
        title="贴纸轨道",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
        sticker_library=library,
    )

    page._random_library.setChecked(True)

    assert page.random_library_enabled is True
    assert "素材库为空" in page._status.text()
    assert page._status.objectName() == "CaptionWarn"


def test_random_library_toggle_with_entries(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _sticker_page(tmp_path)
    page._random_library.setChecked(True)

    assert page.random_library_enabled is True
    assert "已开启随机贴纸库" in page._status.text()


def test_clear_library_keeps_tracks(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """清空素材库不应影响已建好的轨道。"""
    from PySide6.QtWidgets import QMessageBox

    page = _sticker_page(tmp_path)
    page._library_list.setCurrentRow(0)
    page._add_track_from_library()
    assert page._list.count() == 1

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    page._clear_library()

    assert page._library_list.count() == 0
    assert page._list.count() == 1, "轨道应保留"
    assert "轨道未改动" in page._status.text()


# ── 源素材取景（对齐 .NET「源素材取景（独立于输出叠层框）」）────────────────


def _mask_page(tmp_path: Path, name: str = "mask-tracks.json"):  # noqa: ANN202
    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / name)
    source = tmp_path / "蒙版.png"
    source.write_bytes(b"stub")
    store.add(source)
    return LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
    )


def test_mask_page_has_source_crop_controls(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """源取景此前只在后端与持久化里存在，界面没有入口。"""
    page = _mask_page(tmp_path)

    for attribute in ("_crop_x", "_crop_y", "_crop_width", "_crop_height", "_crop_reset"):
        assert getattr(page, attribute) is not None, f"{attribute} 应存在"

    assert "自动取景" in page._crop_hint.text()
    assert page._store.layers[0].source_crop_bounds is None


def test_setting_source_crop_persists_bounds(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _mask_page(tmp_path)

    page._crop_x.setValue(10)
    page._crop_y.setValue(20)
    page._crop_width.setValue(80)
    page._crop_height.setValue(70)

    assert page._store.layers[0].source_crop_bounds == pytest.approx((0.1, 0.2, 0.8, 0.7))
    assert "已手动取景" in page._crop_hint.text()


def test_zero_width_means_automatic(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """宽或高置 0 视为「不手动取景」，回到自动。"""
    page = _mask_page(tmp_path)
    page._crop_x.setValue(10)
    page._crop_width.setValue(80)
    assert page._store.layers[0].source_crop_bounds is not None

    page._crop_width.setValue(0)

    assert page._store.layers[0].source_crop_bounds is None


def test_reset_source_crop_restores_automatic(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _mask_page(tmp_path)
    page._crop_x.setValue(30)
    page._crop_width.setValue(50)
    assert page._store.layers[0].source_crop_bounds is not None

    page._reset_source_crop()

    assert page._store.layers[0].source_crop_bounds is None
    assert page._crop_x.value() == 0
    assert page._crop_width.value() == 100
    assert "已重置" in page._status.text()


def test_source_crop_backfills_from_layer(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """持久化的取景值要能回填到控件，否则用户看不到已保存的设置。"""
    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "backfill.json")
    source = tmp_path / "蒙版.png"
    source.write_bytes(b"stub")
    layer = store.add(source)
    store.replace(layer.with_changes(source_crop_bounds=(0.2, 0.1, 0.5, 0.4)))

    page = LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
    )

    assert page._crop_x.value() == 20
    assert page._crop_y.value() == 10
    assert page._crop_width.value() == 50
    assert page._crop_height.value() == 40


def test_sticker_page_has_no_source_crop(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """贴纸本身就是素材，没有「源素材取景」概念。"""
    page = _sticker_page(tmp_path)
    assert page._crop_x is None
    assert page._crop_reset is None
    assert page._crop_hint is None
