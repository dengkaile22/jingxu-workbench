"""图层页高度上限 / 分割位置与合成预览可用性测试（offscreen Qt）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_asset

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.infrastructure.layer_store import LayerStore  # noqa: E402
from jingxu.ui.layer_page import LayerPage  # noqa: E402
from jingxu.ui.layer_preview import layer_box  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page(tmp_path: Path, *, provider=None, name: str = "overlays.json") -> LayerPage:  # noqa: ANN001
    """构造蒙版页。

    本文件测的是「高度上限 / 分割位置 / 合成预览」——这些是**蒙版专属**能力。
    贴纸页按 .NET 结构只保留贴纸画法（位置/尺寸/透明度/旋转/宽高比锁定），
    因此这里必须用 OVERLAY，否则测的是不存在的控件。
    """
    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / name)
    source = tmp_path / "蒙版.png"
    source.write_bytes(b"stub")
    store.add(source)
    # 新建蒙版现在走 .NET 的叠影预设（落点在上半红框区、半透明带渐变）。
    # 本文件测的是分割位置与高度上限，需要一条"居中、不透明"的基准层，
    # 否则先把参数归一到测试假设的状态。
    layer = store.layers[0]
    store.replace(
        layer.with_changes(x_percent=50.0, y_percent=50.0, width_percent=60.0, opacity=1.0, top_fade=0.0, feather=0.0)
    )
    return LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
        base_video_provider=provider,
    )


def test_preview_button_disabled_without_base_material(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, provider=None)

    assert page._preview_button.isEnabled() is False
    assert "请先在混剪页导入素材" in page._preview_status.text()
    assert page._preview_status.isHidden() is False


def test_preview_button_enabled_with_base_material(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, provider=lambda: make_asset())

    assert page._preview_button.isEnabled() is True
    assert page._preview_status.text() == ""


def test_height_spin_persists_and_enables_split(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, provider=lambda: make_asset())
    layer = page._store.layers[0]

    page._height.setValue(40)

    updated = page._store.find(layer.id)
    assert updated is not None
    assert updated.height_percent == pytest.approx(40.0)
    assert page._split_position.isEnabled() is True
    assert page._split_position.value() == 70  # 底边 = 中心 y(50) + 高度上限(40)/2
    assert "高度上限 40%" in page._list.item(0).text()


def test_height_zero_disables_split(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, provider=lambda: make_asset())
    layer = page._store.layers[0]

    page._height.setValue(40)
    page._height.setValue(0)

    updated = page._store.find(layer.id)
    assert updated is not None
    assert updated.height_percent == pytest.approx(0.0)
    assert page._split_position.isEnabled() is False


def test_split_position_moves_bottom_edge_only(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """对齐 .NET SplitPosition：只移动覆盖区底边，顶边保持不变。

    起始 中心 y=50 / 高度 40 → 顶边 30、底边 70；
    底边拉到 80 后高度应为 50、中心应下移到 55，顶边仍为 30。
    """
    page = _page(tmp_path, provider=lambda: make_asset())
    layer = page._store.layers[0]
    page._height.setValue(40)
    top_before = layer.y_percent - 40 / 2.0

    page._split_position.setValue(80)

    updated = page._store.find(layer.id)
    assert updated is not None
    assert updated.height_percent == pytest.approx(50.0)  # 80 - 30
    assert updated.y_percent == pytest.approx(55.0)  # 30 + 50/2
    assert updated.y_percent - updated.height_percent / 2.0 == pytest.approx(top_before)
    assert page._height.value() == 50
    assert page._split_position.value() == 80


def test_split_below_center_clamps_to_minimum(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """底边不得比顶边浅于 5%（.NET MinNormalizedSize = 0.05）。"""
    page = _page(tmp_path, provider=lambda: make_asset())
    layer = page._store.layers[0]
    page._height.setValue(40)  # 顶边 30

    page._split_position.setValue(30)  # 低于 顶边 + 5 = 35，被钳制

    updated = page._store.find(layer.id)
    assert updated is not None
    assert updated.height_percent == pytest.approx(5.0)
    assert updated.y_percent == pytest.approx(32.5)  # 30 + 5/2
    assert page._split_position.value() == 35
    assert page._height.value() == 5


def test_layer_box_respects_height_percent() -> None:
    limited = LayerSpec(
        kind=LayerKind.STICKER,
        source=Path("s.png"),
        x_percent=50,
        y_percent=50,
        width_percent=40,
        height_percent=25,
    )
    box = layer_box(limited, canvas_ratio=1.0)
    assert box.width == pytest.approx(0.40)
    assert box.height == pytest.approx(0.25)
    assert box.y == pytest.approx(0.375)

    natural = LayerSpec(
        kind=LayerKind.STICKER,
        source=Path("s.png"),
        x_percent=50,
        y_percent=50,
        width_percent=20,
        height_percent=80,
    )
    box = layer_box(natural, canvas_ratio=1.0)
    assert box.height == pytest.approx(0.20)  # 上限高于自然高度时不放大


def test_refresh_from_store_reflects_external_change(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, provider=lambda: make_asset())
    layer = page._store.layers[0]

    page._store.replace(layer.with_changes(y_percent=20.0, height_percent=30.0))
    page.refresh_from_store()

    assert page._y.value() == 20
    assert page._height.value() == 30
    assert page._split_position.value() == 35  # 底边 = 20 + 30/2
    assert page._split_position.isEnabled() is True
