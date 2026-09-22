"""源素材取景拖拽 + 透明度刻度：对齐 .NET 的最后两处差异。

用户要求「继续对齐」，这里钉住两条 .NET 语义：

1. **源取景白框可拖拽**（.NET ``SourceCropPreviewCanvas`` + ``ApplySourceCropDragDelta``）：
   拖框内平移、拖边/角缩放，只改 ``SourceCropBounds``，**绝不动输出叠层框**。
2. **两页的透明度刻度方向相反**（.NET 就是反的，别"统一"掉）：
   * 蒙版页 ``OpacityPercent = (1 - Opacity) * 100``：0 = 不透明、100 = 全透明；
   * 贴纸页 ``StickerOpacity = Opacity * 100``：0 = 全透明、100 = 不透明。
   曾把贴纸页套上蒙版页的换算，于是「透明度 100%」把贴纸整个变没了。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.infrastructure.layer_store import LayerStore  # noqa: E402
from jingxu.ui.layer_page import LayerPage  # noqa: E402
from jingxu.ui.layer_preview import (  # noqa: E402
    MIN_NORMALIZED_SIZE,
    LayerPreviewCanvas,
    PreviewHitZone,
    apply_box_drag,
    source_crop_box,
)


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page(tmp_path: Path, kind: LayerKind, name: str) -> LayerPage:
    store = LayerStore(kind, store_path=tmp_path / name)
    source = tmp_path / "素材.png"
    source.write_bytes(b"stub")
    store.add(source)
    return LayerPage(store, title="t", file_filter="*", hint="测试", ffmpeg=Path("ffmpeg"))


# ── 源取景白框拖拽 ──────────────────────────────────────────────────────────


def test_apply_box_drag_dispatches_by_zone() -> None:
    """共用助手：平移走 move、边角走 resize、None 原样返回。"""
    from jingxu.ui.layer_preview import LayerBox

    box = LayerBox(0.25, 0.25, 0.5, 0.5)
    moved = apply_box_drag(box, PreviewHitZone.MOVE, 21.6, 0.0, 216.0, 384.0)
    assert moved.x == pytest.approx(0.35)

    resized = apply_box_drag(box, PreviewHitZone.EAST, 21.6, 0.0, 216.0, 384.0)
    assert resized.width == pytest.approx(0.6)
    assert resized.x == box.x

    assert apply_box_drag(box, PreviewHitZone.NONE, 99, 99, 216.0, 384.0) == box


def test_crop_canvas_creates_full_frame_box_when_automatic(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """自动取景时白框不存在；点一下画布先落一个"整幅"框，用户才有东西可拖。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "o1.json")
    layer = page._store.layers[0]
    page._store.replace(layer.with_changes(source_crop_bounds=None))
    page.refresh_from_store()

    canvas = page._source_crop_preview
    assert canvas is not None
    assert source_crop_box(page._selected()) is None

    received: list[tuple] = []
    canvas.source_crop_moved.connect(lambda *args: received.append(args))

    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(30, 30),
        QPointF(30, 30),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event)

    assert received, "自动取景下点击画布没有建立初始白框"
    assert received[0] == (0.0, 0.0, 1.0, 1.0)


def test_dragging_crop_frame_updates_bounds_and_not_output_box(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """拖白框只改取景；输出叠层框（x/y/宽/高）必须原封不动。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "o2.json")
    layer = page._store.layers[0]
    # 造一个居中、与输出框明显不同的取景框
    page._store.replace(
        layer.with_changes(
            source_crop_bounds=(0.2, 0.2, 0.5, 0.5),
            x_percent=50.0,
            y_percent=26.0,
            width_percent=90.0,
        )
    )
    page.refresh_from_store()
    before = page._store.find(layer.id)
    assert before is not None

    page._on_canvas_source_crop_moved(0.3, 0.35, 0.4, 0.4)

    after = page._store.find(layer.id)
    assert after is not None
    assert after.source_crop_bounds == pytest.approx((0.3, 0.35, 0.4, 0.4))
    # 输出框不得被改动
    assert after.x_percent == pytest.approx(before.x_percent)
    assert after.y_percent == pytest.approx(before.y_percent)
    assert after.width_percent == pytest.approx(before.width_percent)
    assert after.height_percent == pytest.approx(before.height_percent)


def test_crop_drag_syncs_the_numeric_controls(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """拖白框后下方四个数值要跟着变，否则两处显示会互相矛盾。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "o3.json")
    layer = page._store.layers[0]
    page._store.replace(layer.with_changes(source_crop_bounds=(0.2, 0.2, 0.5, 0.5)))
    page.refresh_from_store()

    page._on_canvas_source_crop_moved(0.3, 0.35, 0.4, 0.45)

    assert page._crop_x.value() == 30
    assert page._crop_y.value() == 35
    assert page._crop_width.value() == 40
    assert page._crop_height.value() == 45


def test_crop_drag_clamps_out_of_range_values(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, LayerKind.OVERLAY, "o4.json")
    layer = page._store.layers[0]
    page._store.replace(layer.with_changes(source_crop_bounds=(0.2, 0.2, 0.5, 0.5)))
    page.refresh_from_store()

    page._on_canvas_source_crop_moved(-1.0, 2.0, 0.0, 5.0)

    bounds = page._store.find(layer.id).source_crop_bounds
    assert bounds[0] == 0.0
    assert bounds[1] == 1.0
    assert bounds[2] == 0.01  # 不允许退化为 0
    assert bounds[3] == 1.0


def test_numeric_edit_refreshes_the_crop_canvas(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """数值编辑也要刷新白框（此前只刷新提示行，白框停在旧位置）。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "o5.json")
    layer = page._store.layers[0]
    page._store.replace(layer.with_changes(source_crop_bounds=(0.1, 0.1, 0.3, 0.3)))
    page.refresh_from_store()

    page._crop_x.setValue(40)

    bounds = page._store.find(layer.id).source_crop_bounds
    assert bounds[0] == pytest.approx(0.4)
    # 画布上的白框应同步到新值
    box = source_crop_box(page._store.find(layer.id))
    assert box is not None
    assert box.x == pytest.approx(0.4)


def test_composition_canvas_does_not_drag_the_crop_frame(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """成片画布不画白框，也不该响应取景拖拽——两张画布职责分离（同 .NET）。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "o6.json")
    assert page._canvas.show_source_crop is False
    assert page._source_crop_preview.show_source_crop is True


def test_crop_min_size_matches_dotnet() -> None:
    """最小边长 5%，对齐 .NET ``MinNormalizedSize = 0.05``。"""
    assert MIN_NORMALIZED_SIZE == 0.05

    from jingxu.ui.layer_preview import LayerBox

    shrunk = apply_box_drag(
        LayerBox(0.2, 0.2, 0.3, 0.3), PreviewHitZone.SOUTH_EAST, -999, -999, 216.0, 384.0
    )
    assert shrunk.width == pytest.approx(MIN_NORMALIZED_SIZE)
    assert shrunk.height == pytest.approx(MIN_NORMALIZED_SIZE)


# ── 透明度刻度 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("percent", "expected"),
    [(0, 1.0), (28, 0.72), (72, 0.28), (100, 0.0)],
)
def test_overlay_opacity_inverts(qapp, tmp_path: Path, percent: int, expected: float) -> None:  # noqa: ANN001
    """蒙版页：0 = 不透明、100 = 全透明（对齐 .NET ``OpacityPercent``）。"""
    page = _page(tmp_path, LayerKind.OVERLAY, f"op{percent}.json")
    layer = page._store.layers[0]

    page._opacity.setValue(percent)

    assert page._store.find(layer.id).opacity == pytest.approx(expected)


@pytest.mark.parametrize(
    ("percent", "expected"),
    [(0, 0.0), (50, 0.5), (100, 1.0)],
)
def test_sticker_opacity_is_direct(qapp, tmp_path: Path, percent: int, expected: float) -> None:  # noqa: ANN001
    """贴纸页：100 = 不透明，直接对应（对齐 .NET ``StickerOpacity``）。

    回归：曾套用蒙版页的取反公式，于是「透明度 100%」把贴纸整个变没了。
    """
    page = _page(tmp_path, LayerKind.STICKER, f"sp{percent}.json")
    layer = page._store.layers[0]

    page._opacity.setValue(percent)

    assert page._store.find(layer.id).opacity == pytest.approx(expected)


def test_sticker_default_control_is_fully_opaque(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """贴纸控件默认 100% ＝ 完全不透明，与 .NET 新建贴纸的 opacity=1.0 一致。"""
    page = _page(tmp_path, LayerKind.STICKER, "sd.json")
    assert page._opacity.value() == 100
    assert page._store.layers[0].opacity == pytest.approx(1.0)


def test_overlay_form_default_is_ghost_transparency(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """蒙版表单默认刻度要与 .NET 蒙版默认不透明度 0.28 自洽（即 72% 透明）。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "od.json")
    assert page._opacity.value() == 72
    assert page._store.layers[0].opacity == pytest.approx(0.28)


def test_populate_round_trips_both_scales(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """回填 → 不做修改 → 再读回，不得漂移（两页各自的方向都要对）。"""
    for kind, name, opacity in (
        (LayerKind.OVERLAY, "rt-o.json", 0.28),
        (LayerKind.STICKER, "rt-s.json", 0.28),
    ):
        page = _page(tmp_path, kind, name)
        layer = page._store.layers[0]
        page._store.replace(layer.with_changes(opacity=opacity))
        page.refresh_from_store()

        # 触发一次写回：值不变时 Qt 不发信号，因此显式走同一个换算
        assert page._opacity_from_percent() == pytest.approx(opacity), name
        assert page._opacity_percent_from_layer(page._store.find(layer.id)) == page._opacity.value()


def test_sticker_summary_shows_opacity_percent(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """摘要行与 .NET 一致用「透明度」，不再另造「可见度」。"""
    page = _page(tmp_path, LayerKind.STICKER, "sum.json")
    layer = page._store.layers[0]
    page._store.replace(layer.with_changes(opacity=0.6))
    page.refresh_from_store()

    text = page._sticker_summary.text()
    assert "透明度：60%" in text
    assert "可见度" not in text


def test_overlay_page_has_no_sticker_summary(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """摘要行是贴纸页专属（.NET 蒙版页没有它）。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "nosum.json")
    assert not hasattr(page, "_sticker_summary")


def test_crop_canvas_without_selection_is_inert(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """没有选中图层时点取景画布不得崩，也不得发出信号。"""
    canvas = LayerPreviewCanvas(show_source_crop=True)
    canvas.set_layers([])
    canvas.resize(canvas.sizeHint())
    received: list[tuple] = []
    canvas.source_crop_moved.connect(lambda *args: received.append(args))

    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event)

    assert received == []


# ── 控件措辞/取值域与 .NET 对齐 ──────────────────────────────────────────────


def test_auto_vertical_offset_matches_dotnet_range(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「自动上下偏移」＝ .NET ``SourceCropY``：-1 偏上 / 0 居中 / 1 偏下。

    此前标签写作「源上下偏移」，容易被理解成另一个参数；.NET 的 ``OffsetY``
    （蓝框位置 Y）与 ``SourceCropY`` 是两个不同的东西，取值域恰好都是 -1~1。
    """
    page = _page(tmp_path, LayerKind.OVERLAY, "off.json")
    spin = page._source_crop_y
    assert spin is not None
    assert spin.minimum() == pytest.approx(-1.0)
    assert spin.maximum() == pytest.approx(1.0)

    layer = page._store.layers[0]
    spin.setValue(0.5)
    assert page._store.find(layer.id).source_crop_y == pytest.approx(0.5)


def test_offset_control_absent_from_sticker_page(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """自动上下偏移是蒙版专属（贴纸没有「源素材」概念）。"""
    page = _page(tmp_path, LayerKind.STICKER, "soff.json")
    assert page._source_crop_y is None
    assert page._crop_x is None
    assert page._source_crop_preview is None


def test_mask_page_has_both_canvases(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """蒙版页两张画布、贴纸页一张，与 .NET 的页面结构一致。"""
    mask = _page(tmp_path, LayerKind.OVERLAY, "two.json")
    sticker = _page(tmp_path, LayerKind.STICKER, "one.json")

    assert mask._source_crop_preview is not None
    assert mask._canvas.show_reference is True
    assert mask._canvas.show_source_crop is False

    assert sticker._source_crop_preview is None
    assert sticker._canvas.show_reference is False


# ── 「尺寸」＝内容在边界框内的相对缩放（.NET OverlayLayer.Scale） ─────────────


def test_scale_filter_emitted_above_100(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """>100%：放大后中心裁回边界框（对齐 .NET ``BuildRelativeScale``）。"""
    script = _layer_script(scale_percent=150.0, height_percent=42.0)

    assert "scale=iw*1.5:ih*1.5" in script
    assert "crop=324:min(ih\\,806):(iw-ow)/2:(ih-oh)/2" in script


def test_scale_filter_emitted_below_100(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """<100%：缩小后用**透明** pad 补回边界框，而不是拉伸或填黑边。"""
    script = _layer_script(scale_percent=50.0, height_percent=42.0)

    assert "scale=iw*0.5:ih*0.5" in script
    assert "color=0x00000000" in script, "缩小必须留透明边（.NET 用 0x00000000）"
    assert "pad=324:min(ih\\,806)" in script


def test_scale_absent_at_100_percent(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """100% 不产生任何缩放滤镜（避免无谓的滤镜链开销）。"""
    script = _layer_script(scale_percent=100.0, height_percent=42.0)
    assert "scale=iw*" not in script


def test_scale_works_without_height_limit(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """高度不限制（height_percent=0）时也要生效。

    回归：早先的实现直接跳过缩放，理由是"边界框高度未知"；但
    ``scale=iw*s:ih*s`` 保持比例，此时边界框高度就是缩放后的 ``ih``。
    """
    script = _layer_script(scale_percent=50.0, height_percent=0.0)

    assert "scale=iw*0.5:ih*0.5" in script
    assert "pad=324:ih:" in script


@pytest.mark.parametrize("kind", [LayerKind.OVERLAY, LayerKind.STICKER])
def test_scale_control_round_trips(qapp, tmp_path: Path, kind: LayerKind) -> None:  # noqa: ANN001
    """「尺寸」控件在两种图层上都可用，且写入/回填一致。"""
    page = _page(tmp_path, kind, f"sc-{kind.value}.json")
    layer = page._store.layers[0]

    assert page._scale.value() == pytest.approx(100.0)
    assert page._scale.minimum() == pytest.approx(1.0)
    assert page._scale.maximum() == pytest.approx(400.0)  # 对齐 .NET 滑杆 0.01–4

    page._scale.setValue(150.0)
    assert page._store.find(layer.id).scale_percent == pytest.approx(150.0)

    page.refresh_from_store()
    assert page._scale.value() == pytest.approx(150.0)


def test_scale_control_clamps_out_of_range(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """控件上下限与 .NET 一致，超范围由控件本身收口。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "sc-clamp.json")
    layer = page._store.layers[0]

    page._scale.setValue(9999.0)
    assert page._store.find(layer.id).scale_percent == pytest.approx(400.0)

    page._scale.setValue(0.0)
    assert page._store.find(layer.id).scale_percent == pytest.approx(1.0)


# ── 「位置 X / 位置 Y」＝输出框整体位移（.NET OffsetX/OffsetY） ───────────────


def test_offset_shifts_overlay_without_moving_center(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """位移叠加在中心定位之上：公式为 ``center + offset``（对齐 .NET）。

    .NET：``overlayX = px + OffsetX * targetWidth``，其中 px 由 Bounds 推出。
    Python 的对应写法是「框中心百分比 + 归一化位移」。
    """
    script = _layer_script(scale_percent=100.0, height_percent=42.0, offset_x=0.25, offset_y=-0.5)

    # x_percent=50 → 0.50，加 0.25 = 0.75；y_percent=50 → 0.50，减 0.5 = 0.00
    assert "main_w*0.7500-overlay_w/2" in script
    assert "main_h*0.0000-overlay_h/2" in script


def test_zero_offset_keeps_legacy_position(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """默认位移为 0 时落点与迁移前完全一致（老项目观感不变）。"""
    script = _layer_script(scale_percent=100.0, height_percent=42.0)

    assert "main_w*0.5000-overlay_w/2" in script
    assert "main_h*0.5000-overlay_h/2" in script


def test_offset_clamped_to_dotnet_range(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """位移越界夹到 -1~1（对齐 .NET ``MinOffset``/``MaxOffset``）。"""
    script = _layer_script(scale_percent=100.0, height_percent=42.0, offset_x=5.0, offset_y=-9.0)

    assert "main_w*1.5000-overlay_w/2" in script  # 0.5 + 夹取后的 1.0
    assert "main_h*-0.5000-overlay_h/2" in script  # 0.5 + 夹取后的 -1.0


def test_offset_persists_and_clamps_on_load(tmp_path: Path) -> None:
    """持久化往返 + 旧项目缺键回落 0 + 非法值收口。"""
    from jingxu.infrastructure.layer_store import LayerStore  # noqa: PLC0415

    path = tmp_path / "off.json"
    store = LayerStore(LayerKind.OVERLAY, store_path=path)
    source = tmp_path / "m.png"
    source.write_bytes(b"stub")
    layer = store.add(source)
    store.replace(layer.with_changes(offset_x=0.3, offset_y=-0.4))

    reopened = LayerStore(LayerKind.OVERLAY, store_path=path)
    assert reopened.layers[0].offset_x == pytest.approx(0.3)
    assert reopened.layers[0].offset_y == pytest.approx(-0.4)

    # 旧项目：手工写一条没有 offset 键的图层
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        '{"kind":"overlay","layers":[{"source":"%s","x_percent":40,"y_percent":30}]}'
        % str(source).replace("\\", "\\\\"),
        encoding="utf-8",
    )
    old = LayerStore(LayerKind.OVERLAY, store_path=legacy)
    assert old.layers[0].offset_x == 0.0
    assert old.layers[0].offset_y == 0.0


def test_offset_control_only_on_mask_page(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「位置 X/Y」是蒙版专属（贴纸页没有输出叠层框这一层）。"""
    mask = _page(tmp_path, LayerKind.OVERLAY, "offmask.json")
    sticker = _page(tmp_path, LayerKind.STICKER, "offsticker.json")

    assert mask._offset_x is not None and mask._offset_y is not None
    assert sticker._offset_x is None and sticker._offset_y is None


def test_offset_control_range_matches_dotnet(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """控件范围 -1~1，与 .NET 滑杆 Minimum/Maximum 一致。"""
    page = _page(tmp_path, LayerKind.OVERLAY, "offrange.json")

    assert page._offset_x.minimum() == pytest.approx(-1.0)
    assert page._offset_x.maximum() == pytest.approx(1.0)
    assert page._offset_y.minimum() == pytest.approx(-1.0)
    assert page._offset_y.maximum() == pytest.approx(1.0)


def test_preview_box_follows_offset(qapp) -> None:  # noqa: ANN001
    """预览框中心必须含 offset，否则画面会动、预览不动。"""
    from jingxu.ui.layer_preview import layer_box  # noqa: PLC0415

    base = dict(
        kind=LayerKind.OVERLAY,
        source=Path("m.png"),
        x_percent=50.0,
        y_percent=50.0,
        width_percent=30.0,
    )
    plain = layer_box(LayerSpec(**base), 1.7778)
    shifted = layer_box(LayerSpec(**base, offset_x=0.25, offset_y=-0.2), 1.7778)

    assert (plain.x + plain.width / 2) == pytest.approx(0.5)
    assert (shifted.x + shifted.width / 2) == pytest.approx(0.75)
    assert (shifted.y + shifted.height / 2) == pytest.approx(0.3)
    # 尺寸不受位移影响
    assert shifted.width == pytest.approx(plain.width)
    assert shifted.height == pytest.approx(plain.height)


def test_preview_and_filter_agree_on_offset(qapp) -> None:  # noqa: ANN001
    """预览与滤镜图必须给出同一个落点（这是最容易分叉的一处）。"""
    from jingxu.ui.layer_preview import layer_box  # noqa: PLC0415

    script = _layer_script(scale_percent=100.0, height_percent=42.0, offset_x=0.25, offset_y=-0.5)
    box = layer_box(
        LayerSpec(
            kind=LayerKind.OVERLAY,
            source=Path("m.png"),
            x_percent=50.0,
            y_percent=50.0,
            width_percent=30.0,
            height_percent=42.0,
            offset_x=0.25,
            offset_y=-0.5,
        ),
        1.7778,
    )

    # 滤镜图：main_w*0.7500 / main_h*0.0000；预览：中心 0.75 / 0.00
    assert "main_w*0.7500-overlay_w/2" in script
    assert "main_h*0.0000-overlay_h/2" in script
    assert (box.x + box.width / 2) == pytest.approx(0.75)
    assert (box.y + box.height / 2) == pytest.approx(0.0)


def _layer_script(
    *,
    scale_percent: float,
    height_percent: float,
    width_percent: float = 30.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> str:
    """编译单个图层的滤镜脚本，返回整份脚本。"""
    from jingxu.domain.composition import CompositionPlan, OrderMode  # noqa: PLC0415
    from jingxu.domain.render import RenderSettings  # noqa: PLC0415
    from jingxu.infrastructure.filter_graph import build_filter_graph  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conftest import make_asset  # noqa: PLC0415

    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.png"),
        x_percent=50.0,
        y_percent=50.0,
        width_percent=width_percent,
        height_percent=height_percent,
        scale_percent=scale_percent,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    plan = CompositionPlan(assets=(make_asset("a.mp4"),), mode=OrderMode.SEQUENTIAL)
    graph = build_filter_graph(plan, RenderSettings(width=1080, height=1920), layers=(layer,))
    # 返回**整份脚本**：缩放写在图层自身滤镜链上，位移写在 overlay 那一行，
    # 两者分布在不同行；按单行取会漏掉其中一半。具体断言各自搜自己关心的片段。
    return graph.script
