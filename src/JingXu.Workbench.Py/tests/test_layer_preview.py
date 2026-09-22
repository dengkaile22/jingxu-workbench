"""图层预览画布与旋转叠加测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.layers import LayerKind, LayerSpec
from jingxu.domain.render import RenderSettings
from jingxu.infrastructure.filter_graph import build_filter_graph

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF  # noqa: E402

from jingxu.ui.layer_preview import layer_box, percent_from_point  # noqa: E402


def test_layer_rotation_adds_rotate_filter() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), rotation_degrees=90)
    graph = build_filter_graph(
        CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL),
        RenderSettings(),
        layers=(layer,),
    )
    assert "rotate=1.570796:ow=rotw(iw):oh=roth(ih):c=none" in graph.script


def test_layer_without_rotation_skips_rotate() -> None:
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"))
    graph = build_filter_graph(
        CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL),
        RenderSettings(),
        layers=(layer,),
    )
    assert "rotate=" not in graph.script


def test_layer_box_uses_center_without_clamping() -> None:
    """框中心取自 ``x_percent``/``y_percent``，**不做画布内夹取**。

    滤镜图按同一个中心公式定位、同样不夹取（框可以有一部分移出画布）。
    预览若在这里夹回去，用户会看到"预览不动但成片动了"。
    """
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), x_percent=50, y_percent=50, width_percent=40)
    box = layer_box(layer, canvas_ratio=1.0)
    assert box.x == pytest.approx(0.30)
    assert box.y == pytest.approx(0.30)
    assert box.width == pytest.approx(0.40)
    assert box.height == pytest.approx(0.40)

    # 中心贴到画布右缘：框有一半在画布外，与渲染一致
    edge = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), x_percent=100, y_percent=0, width_percent=60)
    at_edge = layer_box(edge, canvas_ratio=1.0)
    assert at_edge.x + at_edge.width / 2 == pytest.approx(1.0)
    assert at_edge.x == pytest.approx(0.70)
    assert at_edge.y + at_edge.height / 2 == pytest.approx(0.0)


def test_percent_from_point_maps_and_clamps() -> None:
    canvas = QRectF(100, 50, 200, 400)
    x, y = percent_from_point(QPointF(200, 250), canvas)
    assert x == pytest.approx(50.0)
    assert y == pytest.approx(50.0)

    clamped_x, clamped_y = percent_from_point(QPointF(0, 1000), canvas)
    assert clamped_x == 0.0
    assert clamped_y == 100.0


def test_preview_canvas_drag_updates_store(tmp_path: Path, qapp=None) -> None:  # noqa: ANN001
    from PySide6.QtWidgets import QApplication

    from jingxu.infrastructure.layer_store import LayerStore
    from jingxu.ui.layer_page import LayerPage

    if QApplication.instance() is None:
        QApplication(["jingxu-tests"])

    store = LayerStore(LayerKind.STICKER, store_path=tmp_path / "stickers.json")
    source = tmp_path / "贴纸.png"
    source.write_bytes(b"stub")
    store.add(source)

    page = LayerPage(store, title="贴纸轨道", file_filter="*", hint="测试")
    layer = store.layers[0]
    page._canvas.layer_moved.emit(layer.id, 80.0, 20.0)

    updated = store.find(layer.id)
    assert updated is not None
    assert updated.x_percent == pytest.approx(80.0)
    assert updated.y_percent == pytest.approx(20.0)
    assert page._x.value() == 80

    page._canvas.layer_scaled.emit(layer.id, 55.0)
    assert store.find(layer.id).width_percent == pytest.approx(55.0)
    assert page._width.value() == 55
