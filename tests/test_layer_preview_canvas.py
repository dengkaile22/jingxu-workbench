"""图层预览画布的尺寸与素材绘制回归测试。

用户实测反馈「蒙版和贴纸的这个预览框不对」。排查后是两个独立问题：

1. **画布被压到极小**：``_canvas_rect`` 写成"先按宽度算、放不下再退回按高度算"，
   在"宽而扁"的控件里取到极小解——950×240 的控件里 9:16 画布只画出 117×208，
   占 11%，看起来就是一个孤零零的小黑框，四周全是空白。
2. **框内什么都不画**：只有黑底 + 十字虚线，看不出蒙版/贴纸长什么样。

本文件守住这两条：画布要按可用区域等比**放到最大**，且框内要画出真实素材
（含透明度与旋转），素材缺失时降级为空心框而不是崩掉。
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

from PySide6.QtCore import QPoint, QPointF, QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.ui.layer_preview import (  # noqa: E402
    CANVAS_MARGIN,
    IMPORTED_MASK_BOUNDS,
    LayerPreviewCanvas,
    reference_region_box,
    source_crop_box,
)


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _canvas(width: int, height: int, aspect: str = "9:16") -> LayerPreviewCanvas:
    canvas = LayerPreviewCanvas()
    canvas.resize(QSize(width, height))
    canvas.set_layers([], aspect=aspect)
    return canvas


def _make_image(path: Path, color: str = "#D9534F", size: QSize = QSize(120, 180)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    image.save(str(path))
    return path


# ── 画布尺寸：必须按可用区域放到最大 ─────────────────────────────────────────


def test_canvas_fills_height_when_widget_is_wide_and_short(qapp) -> None:  # noqa: ANN001
    """宽扁控件里画布必须顶满高度——这正是"只占 11%"的回归点。"""
    canvas = _canvas(950, 300)
    rect = canvas._canvas_rect()

    assert rect.height() == pytest.approx(300 - CANVAS_MARGIN * 2, abs=0.5)
    assert rect.width() == pytest.approx(rect.height() * 9 / 16, abs=0.5)


def test_canvas_ratio_is_exact_for_every_aspect(qapp) -> None:  # noqa: ANN001
    for aspect, (ratio_w, ratio_h) in {
        "9:16": (9, 16),
        "16:9": (16, 9),
        "1:1": (1, 1),
        "3:4": (3, 4),
    }.items():
        rect = _canvas(900, 300, aspect)._canvas_rect()
        assert rect.width() / rect.height() == pytest.approx(ratio_w / ratio_h, rel=1e-6), aspect


def test_canvas_fits_inside_available_area(qapp) -> None:  # noqa: ANN001
    rect = _canvas(400, 400)._canvas_rect()
    assert rect.left() >= CANVAS_MARGIN - 0.5
    assert rect.top() >= CANVAS_MARGIN - 0.5
    assert rect.right() <= 400 - CANVAS_MARGIN + 0.5
    assert rect.bottom() <= 400 - CANVAS_MARGIN + 0.5


def test_canvas_at_hint_is_readable_size(qapp) -> None:  # noqa: ANN001
    """按 sizeHint 布局时，画布必须有可读尺寸。

    这条防的是"改回小尺寸"的回归：曾经 9:16 画布只有 146×260，用户反馈"预览框
    不对"；现在对齐 .NET 版预览画布（216×384）。
    """
    canvas = LayerPreviewCanvas()
    canvas.set_layers([], aspect="9:16")
    canvas.resize(canvas.sizeHint())
    rect = canvas._canvas_rect()

    assert rect.width() >= 200, f"9:16 画布只有 {rect.width():.0f} 宽，看不清素材"
    assert rect.height() >= 380, f"9:16 画布只有 {rect.height():.0f} 高"


def test_canvas_stays_reachable_within_a_typical_viewport(qapp) -> None:  # noqa: ANN001
    """画布连同上方图层列表必须能落进 700px 高的窗口，否则预览又要靠滚动才看得到。

    实测窗口高 700 → 页面视口约 700；列表 160 + 画布 + 间距必须放得下。
    """
    canvas = LayerPreviewCanvas()
    canvas.set_layers([], aspect="9:16")
    hint = canvas.sizeHint()

    list_height = 160
    spacings = 30
    assert list_height + hint.height() + spacings <= 700, (
        f"列表 {list_height} + 画布 {hint.height()} 超出首屏，预览会被挤到折叠线下"
    )


def test_canvas_never_collapses(qapp) -> None:  # noqa: ANN001
    """退化尺寸（布局尚未给够空间）下也不能算出 0 宽。"""
    rect = _canvas(10, 10)._canvas_rect()
    assert rect.width() > 0
    assert rect.height() > 0


def test_unknown_aspect_keeps_previous_value(qapp) -> None:  # noqa: ANN001
    """传入未知画幅（如"跟随混剪画幅"解析失败）时保持原值，不得变成 0 比例。"""
    canvas = _canvas(400, 400, "16:9")
    canvas.set_layers([], aspect="inherit")
    assert canvas.aspect == "16:9"


def test_size_hint_matches_contain_algorithm(qapp) -> None:  # noqa: ANN001
    """画布必须按"contain"铺满可用区域：至少一个方向顶满，另一个方向等比适配。

    这条守住 sizeHint 的"纯函数"性质：一旦它去读自身当前高度，返回值会被上一次
    的结果顶住，布局与画布尺寸就会长期错位（16:9 曾得到 380×400 的控件、
    画布只有 360×202，控件内近一半是空白）。
    """
    for aspect, (ratio_w, ratio_h) in {
        "9:16": (9, 16),
        "16:9": (16, 9),
        "1:1": (1, 1),
        "3:4": (3, 4),
    }.items():
        canvas = _canvas(400, 400, aspect)
        hint = canvas.sizeHint()
        # sizeHint 必须与控件当前尺寸无关
        canvas.resize(120, 900)
        assert canvas.sizeHint() == hint, f"{aspect}: sizeHint 随控件尺寸变化了"

        sized = LayerPreviewCanvas()
        sized.resize(hint)
        sized.set_layers([], aspect=aspect)
        rect = sized._canvas_rect()

        assert rect.width() / rect.height() == pytest.approx(ratio_w / ratio_h, rel=1e-6), aspect
        assert rect.width() <= sized.width() - CANVAS_MARGIN * 2 + 1.0, aspect
        assert rect.height() <= sized.height() - CANVAS_MARGIN * 2 + 1.0, aspect

        # contain：宽度或高度至少有一个顶满可用区域（另一个等比缩小）
        fills_width = rect.width() == pytest.approx(sized.width() - CANVAS_MARGIN * 2, abs=1.0)
        fills_height = rect.height() == pytest.approx(sized.height() - CANVAS_MARGIN * 2, abs=1.0)
        assert fills_width or fills_height, (
            f"{aspect}: 画布既没顶满宽度也没顶满高度 -> 会留下一圈空白"
        )


def test_size_hint_is_pure(qapp) -> None:  # noqa: ANN001
    """sizeHint 不得依赖控件当前尺寸，否则会被自己上一次的返回值顶住。"""
    canvas = LayerPreviewCanvas()
    canvas.set_layers([], aspect="16:9")
    first = canvas.sizeHint()

    canvas.resize(900, 700)
    canvas.set_layers([], aspect="16:9")
    assert canvas.sizeHint() == first, "sizeHint 结果随控件尺寸变化，说明它不是纯函数"


def test_minimum_height_is_generous_enough_to_read_artwork(qapp) -> None:  # noqa: ANN001
    """9:16 画布在最小高度下也要有可辨认的宽度（此前 240 高时只有 117 宽）。"""
    canvas = LayerPreviewCanvas()
    assert canvas.minimumHeight() >= 280
    canvas.resize(QSize(400, canvas.minimumHeight()))
    canvas.set_layers([], aspect="9:16")
    assert canvas._canvas_rect().width() >= 140


# ── 素材绘制：框内要画出真实素材 ─────────────────────────────────────────────


def _render(canvas: LayerPreviewCanvas, size: QSize) -> QImage:
    """把画布画进透明底图。

    底图必须是透明的：控件自身不填充背景，若底图预先填色就分不清
    "画布画的" 与 "底图本来就有的"，透明贴纸的断言会失真。
    """
    canvas.resize(size)
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    canvas.render(painter, QPoint(0, 0))
    painter.end()
    return image


def _has_color(image: QImage, color: QColor, tolerance: int = 40) -> bool:
    target = (color.red(), color.green(), color.blue())
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            pixel = image.pixelColor(x, y)
            if (
                abs(pixel.red() - target[0]) <= tolerance
                and abs(pixel.green() - target[1]) <= tolerance
                and abs(pixel.blue() - target[2]) <= tolerance
            ):
                return True
    return False


def test_image_layer_is_painted_into_the_box(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """图片素材必须真的画进画布——这是"框里什么都没有"的回归点。"""
    source = _make_image(tmp_path / "蒙版.png", "#D9534F")
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=source,
        x_percent=50,
        y_percent=50,
        width_percent=60,
        height_percent=60,
    )
    canvas = LayerPreviewCanvas()
    canvas.set_layers([layer], aspect="9:16")
    image = _render(canvas, QSize(240, 400))

    assert _has_color(image, QColor("#D9534F")), "画布上找不到素材颜色，说明没有绘制缩略图"


def test_layer_outline_still_drawn_without_source(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """素材缺失/视频类素材：只画框（描边仍然可见），不得抛异常。"""
    layer = LayerSpec(kind=LayerKind.STICKER, source=tmp_path / "不存在.mp4")
    canvas = LayerPreviewCanvas()
    canvas.set_layers([layer], aspect="9:16")

    image = _render(canvas, QSize(240, 400))  # 不应抛异常
    rect = canvas._layer_rect(layer, canvas._canvas_rect())
    assert rect.width() > 0 and rect.height() > 0

    # 没有素材时框内是半透明填充 + 描边，因此框中心必须与画布底色不同
    background = image.pixelColor(1, 1)
    inside = image.pixelColor(int(rect.center().x()), int(rect.center().y()))
    assert inside.name() != background.name(), "素材缺失时连位置框都没画出来"


def test_rotation_and_opacity_do_not_break_painting(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    source = _make_image(tmp_path / "贴纸.png", "#3F7A55")
    layer = LayerSpec(
        kind=LayerKind.STICKER,
        source=source,
        x_percent=40,
        y_percent=40,
        width_percent=40,
        opacity=0.5,
        rotation_degrees=25,
    )
    canvas = LayerPreviewCanvas()
    canvas.set_layers([layer], aspect="9:16")

    image = _render(canvas, QSize(240, 400))
    assert image.width() == 240  # 渲染过程完成


def test_transparent_png_keeps_surface_colour(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """带透明通道的贴纸：透明区域必须露出页面底色，而不是被涂成灰块。

    贴纸绝大多数是 PNG 透明素材，所以画布必须自己铺页面底色——
    依赖 ``setAutoFillBackground(False)`` 不够：Qt 在部分平台仍会用调色板的
    窗口色填充，观感是一整块灰。
    """
    path = tmp_path / "透明贴纸.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(QSize(100, 100), QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.fillRect(40, 40, 20, 20, QColor("#D9534F"))
    painter.end()
    image.save(str(path))

    layer = LayerSpec(
        kind=LayerKind.STICKER,
        source=path,
        x_percent=50,
        y_percent=50,
        width_percent=90,
        height_percent=90,
    )
    canvas = LayerPreviewCanvas()
    canvas.set_layers([layer], aspect="9:16")

    rendered = _render(canvas, QSize(240, 400))

    # 取画布之外的角落（画布居中，边距处才是背景）
    from jingxu.ui import theme

    canvas_rect = canvas._canvas_rect()
    corner_x = max(1, int(canvas_rect.left()) - 3)
    corner_y = max(1, int(canvas_rect.top()) - 3)
    assert rendered.pixelColor(corner_x, corner_y).name().lower() == theme.SURFACE_CANVAS.lower(), (
        "画布外的底色不是页面底色——说明控件仍在用 Qt 默认调色板填充"
    )

    # 贴纸的不透明部分确实画上去了
    assert _has_color(rendered, QColor("#D9534F")), "透明贴纸的不透明部分未被绘制"


# ── 缓存 ────────────────────────────────────────────────────────────────────


def test_source_cache_hits_and_invalidates_by_mtime(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    source = _make_image(tmp_path / "a.png", "#D9534F")
    layer = LayerSpec(kind=LayerKind.STICKER, source=source)
    canvas = LayerPreviewCanvas()

    first = canvas._source_pixmap(layer)
    second = canvas._source_pixmap(layer)
    assert first is not None and first is second, "同一素材应命中缓存"

    source.write_bytes(_make_image(tmp_path / "b.png", "#3F7A55").read_bytes())
    os.utime(source, (0, 0))
    refreshed = canvas._source_pixmap(layer)
    assert refreshed is not None and refreshed is not first, "素材变更后应重新加载"


def test_missing_source_caches_negative_result(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    layer = LayerSpec(kind=LayerKind.STICKER, source=tmp_path / "none.png")
    canvas = LayerPreviewCanvas()

    assert canvas._source_pixmap(layer) is None
    assert canvas._source_pixmap(layer) is None


def test_video_source_is_not_loaded(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """视频素材不在 paintEvent 里抽帧：只画框，避免拖拽卡死。"""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"stub")
    layer = LayerSpec(kind=LayerKind.STICKER, source=video)

    assert LayerPreviewCanvas()._source_pixmap(layer) is None


def test_self_source_layer_is_not_loaded(qapp) -> None:  # noqa: ANN001
    """自叠影没有独立素材文件，不应尝试加载。"""
    from jingxu.domain.layers import SELF_SOURCE

    layer = LayerSpec(kind=LayerKind.STICKER, source=Path(SELF_SOURCE))
    assert LayerPreviewCanvas()._source_pixmap(layer) is None


def test_invalidate_images_clears_cache(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    source = _make_image(tmp_path / "a.png")
    layer = LayerSpec(kind=LayerKind.STICKER, source=source)
    canvas = LayerPreviewCanvas()
    canvas._source_pixmap(layer)
    assert canvas._image_cache

    canvas.invalidate_images()
    assert canvas._image_cache == {}


# ── 与 .NET 预览的形态对齐 ───────────────────────────────────────────────────


def test_reference_region_matches_dotnet_imported_bounds() -> None:
    """默认覆盖区必须与 .NET ``OverlayLayer.ImportedMaskBounds`` 逐值一致。

    这是预览里"暗红参考区"的位置；对不上就等于告诉用户错误的默认落点。
    """
    assert IMPORTED_MASK_BOUNDS == (0.05, 0.05, 0.90, 0.42)

    box = reference_region_box()
    assert (box.x, box.y, box.width, box.height) == IMPORTED_MASK_BOUNDS


def test_reference_region_painted_only_when_enabled(qapp) -> None:  # noqa: ANN001
    """蒙版页画暗红参考区，贴纸页不画（.NET 贴纸页没有这一层）。"""
    with_ref = LayerPreviewCanvas(show_reference=True)
    without_ref = LayerPreviewCanvas(show_reference=False)
    assert with_ref.show_reference is True
    assert without_ref.show_reference is False

    for canvas in (with_ref, without_ref):
        canvas.set_layers([], aspect="9:16")
        canvas.resize(canvas.sizeHint())

    with_image = _render(with_ref, with_ref.size())
    without_image = _render(without_ref, without_ref.size())

    assert _has_color(with_image, QColor("#E85D5C"), tolerance=60), "开启参考区后画布上找不到红色"
    assert not _has_color(without_image, QColor("#E85D5C"), tolerance=40), "未开启参考区却画了红色"


def test_reference_region_uses_full_width_upper_area(qapp) -> None:  # noqa: ANN001
    """参考区在画布上方：y 从 5% 起、高 42%（默认上半叠区）。"""
    canvas = LayerPreviewCanvas(show_reference=True)
    canvas.set_layers([], aspect="9:16")
    canvas.resize(canvas.sizeHint())
    rect = canvas._box_rect(reference_region_box(), canvas._canvas_rect())

    assert rect.top() > canvas._canvas_rect().top()
    assert rect.bottom() < canvas._canvas_rect().center().y() + 40


def test_source_crop_box_from_manual_bounds() -> None:
    """手动指定取景时，白框用该归一化矩形。"""
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.png"),
        source_crop_bounds=(0.1, 0.2, 0.6, 0.5),
    )
    box = source_crop_box(layer)
    assert box is not None
    assert (box.x, box.y, box.width, box.height) == (0.1, 0.2, 0.6, 0.5)


def test_source_crop_box_empty_when_automatic() -> None:
    """未手动取景且未启用按画幅自动取景时不画白框——避免画一个"假框"。"""
    layer = LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.png"))
    assert source_crop_box(layer) is None
    assert source_crop_box(None) is None


def test_source_crop_box_full_frame_when_canvas_crop_enabled() -> None:
    """启用「按画幅比例自动取景」时按整帧显示（实际裁剪由渲染器按画幅决定）。"""
    layer = LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.png"), source_crop_canvas=True)
    box = source_crop_box(layer)
    assert box is not None
    assert (box.x, box.y, box.width, box.height) == (0.0, 0.0, 1.0, 1.0)


def test_source_crop_box_clamps_out_of_range_values() -> None:
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.png"),
        source_crop_bounds=(1.5, -0.2, 0.0, 2.0),
    )
    box = source_crop_box(layer)
    assert box is not None
    assert box.x == 1.0
    assert box.y == 0.0
    assert box.width == 0.01  # 只保证不退化，不为 0
    assert box.height == 1.0


def test_source_crop_frame_not_painted_on_composition_canvas(qapp) -> None:  # noqa: ANN001
    """白框只画在「源素材取景」画布上。

    .NET 把源取景放在独立 Canvas：它是源素材坐标系，混进成片画布会与输出框
    互相干扰，让人误以为白框也是输出位置。
    """
    layer = LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("mask.png"),
        source_crop_bounds=(0.2, 0.2, 0.5, 0.5),
    )
    composition = LayerPreviewCanvas(show_source_crop=False)
    crop_canvas = LayerPreviewCanvas(show_source_crop=True)

    for canvas in (composition, crop_canvas):
        canvas.set_layers([layer], aspect="9:16")
        canvas.resize(canvas.sizeHint())
        canvas.set_selected(layer.id)

    assert composition.show_source_crop is False
    assert crop_canvas.show_source_crop is True
    # 取景画布能取到选中图层（白框依赖它）
    assert crop_canvas.selected_layer() is not None
    assert crop_canvas.selected_layer().id == layer.id


def test_crop_canvas_without_layers_has_no_frame(qapp) -> None:  # noqa: ANN001
    """取景画布没有图层/未选中时不画框，只显示空画布。"""
    canvas = LayerPreviewCanvas(show_source_crop=True)
    canvas.set_layers([], aspect="9:16")
    canvas.resize(canvas.sizeHint())
    image = _render(canvas, canvas.size())
    assert image.width() == canvas.width()


# ── 拖拽命中：几何变了，命中判定必须跟着变 ───────────────────────────────────


def test_hit_test_matches_drawn_rect(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    layer = LayerSpec(
        kind=LayerKind.STICKER,
        source=tmp_path / "s.png",
        x_percent=50,
        y_percent=50,
        width_percent=40,
    )
    canvas = LayerPreviewCanvas()
    canvas.resize(QSize(300, 500))
    canvas.set_layers([layer], aspect="9:16")

    rect = canvas._layer_rect(layer, canvas._canvas_rect())
    assert canvas._layer_at(rect.center()) is layer
    assert canvas._layer_at(QPointF(rect.left() - 5, rect.top() - 5)) is None
