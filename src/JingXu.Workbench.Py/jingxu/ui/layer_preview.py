"""图层预览画布：成片画面示意 + 真实素材缩略图 + 拖拽移动 / 滚轮缩放。

对齐 .NET 的拖拽体验与"所见即所得"程度（``OverlayEditorView.xaml`` /
``StickerEditorView.xaml``）：框内不只是位置示意，还会画出蒙版/贴纸素材本身，
并套用透明度与旋转，这样位置、大小、画法一眼就能核对。

**画布尺寸的关键约束**：画布是固定宽高比的（9:16 等），而它所在的控件通常是
"宽而扁"的一行。因此必须**按可用区域等比放到最大**，而不是"先按宽度算、
放不下再退回按高度算"——后者在宽扁区域里会取到极小解：曾经 950×240 的控件里
9:16 画布只画出 117×208（占 11%），看起来就是一个孤零零的小黑框，四周全是空白。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QSizePolicy, QWidget

from jingxu.domain.layers import LayerSpec
from jingxu.ui import theme

CANVAS_ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (9, 16),
    "16:9": (16, 9),
    "1:1": (1, 1),
    "3:4": (3, 4),
}

# 拖拽命中区的角/边判定厚度（像素）。对齐 .NET ``PreviewHitTester.HandleThickness = 10``。
HANDLE_THICKNESS = 10.0
# 图层归一化最小边长（5%）。逐值对齐 .NET ``OverlayEditorViewModel.MinNormalizedSize = 0.05``；
# 蒙版页「分割位置」的底边下限（``MIN_SPLIT_HEIGHT_PERCENT = 5``）也是同一个值，
# 两者必须一致，否则拖角与拖分割线能得到不同结果。
MIN_NORMALIZED_SIZE = 0.05

# 导入蒙版的默认覆盖区（归一化 x, y, w, h）。
# 与 .NET ``OverlayLayer.ImportedMaskBounds``（0.05, 0.05, 0.90, 0.42）逐值一致：
# 预览里画成暗红参考区，让用户一眼看到"不调参数时蒙版会落在哪"。
IMPORTED_MASK_BOUNDS: tuple[float, float, float, float] = (0.05, 0.05, 0.90, 0.42)

# 源素材取景框的颜色（对齐 .NET 的白框）。
SOURCE_CROP_FRAME_COLOR = "#FFFFFF"

# 画布四周留白：太大则画布被压小，太小则贴着控件边看着局促。
CANVAS_MARGIN = 10.0
# 拖拽区最小高度：9:16 画布在这时约 146×260。
CANVAS_MIN_HEIGHT = 280
# 拖拽区最大高度：再高就会把列表与「叠加参数」挤出首屏。
CANVAS_MAX_HEIGHT = 420
# 目标画布高度：决定 sizeHint，即布局默认给多大。
# 384 与 .NET 版的预览画布（216×384）同尺寸，9:16 下即 216×384。
# 取这个值而不是"越大越好"：列表 160 + 画布 404 在 700px 高的窗口里仍能同屏，
# 120% 缩放下也不会把预览挤到折叠线以下。
CANVAS_TARGET_HEIGHT = 384
# 画布本身的最大宽度：横屏画幅按高度算会过宽，限制一下更像"画面示意"。
CANVAS_MAX_WIDTH = 360.0
# 缩略图缓存上限（按路径+mtime 失效），避免长会话里无限增长。
IMAGE_CACHE_LIMIT = 64


@dataclass(frozen=True, slots=True)
class LayerBox:
    """图层在画面示意中的矩形（相对画布的比例）。"""

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


class PreviewHitZone(str, Enum):
    """预览框命中区域：中心平移，边/角缩放。

    与 .NET ``PreviewHitZone`` 同名同义（``PreviewHitTester.cs:6-18``）。
    """

    NONE = "none"
    MOVE = "move"
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTH_EAST = "north_east"
    NORTH_WEST = "north_west"
    SOUTH_EAST = "south_east"
    SOUTH_WEST = "south_west"

    @property
    def is_resize(self) -> bool:
        return self not in (PreviewHitZone.NONE, PreviewHitZone.MOVE)


def hit_test_box(
    point: tuple[float, float],
    box: LayerBox,
    canvas_width: float,
    canvas_height: float,
    *,
    handle_thickness: float = HANDLE_THICKNESS,
) -> PreviewHitZone:
    """命中测试：返回该点落在框的哪个区域。

    逐行移植 .NET ``PreviewHitTester.HitTest``：先判四角，再判四边，最后判内部；
    四条边在**角区**优先，与 .NET 的判定顺序一致（否则角上永远命中边）。
    """
    if box.width <= 0 or box.height <= 0:
        return PreviewHitZone.NONE

    canvas_x, canvas_y = point
    left = box.x * canvas_width
    top = box.y * canvas_height
    right = left + box.width * canvas_width
    bottom = top + box.height * canvas_height

    near_left = abs(canvas_x - left) <= handle_thickness
    near_right = abs(canvas_x - right) <= handle_thickness
    near_top = abs(canvas_y - top) <= handle_thickness
    near_bottom = abs(canvas_y - bottom) <= handle_thickness
    inside_x = left - handle_thickness <= canvas_x <= right + handle_thickness
    inside_y = top - handle_thickness <= canvas_y <= bottom + handle_thickness

    if not inside_x or not inside_y:
        return PreviewHitZone.NONE

    if near_top and near_left:
        return PreviewHitZone.NORTH_WEST
    if near_top and near_right:
        return PreviewHitZone.NORTH_EAST
    if near_bottom and near_left:
        return PreviewHitZone.SOUTH_WEST
    if near_bottom and near_right:
        return PreviewHitZone.SOUTH_EAST
    if near_top and left <= canvas_x <= right:
        return PreviewHitZone.NORTH
    if near_bottom and left <= canvas_x <= right:
        return PreviewHitZone.SOUTH
    if near_left and top <= canvas_y <= bottom:
        return PreviewHitZone.WEST
    if near_right and top <= canvas_y <= bottom:
        return PreviewHitZone.EAST
    if left <= canvas_x <= right and top <= canvas_y <= bottom:
        return PreviewHitZone.MOVE
    return PreviewHitZone.NONE


def move_box(
    box: LayerBox,
    delta_x: float,
    delta_y: float,
    canvas_width: float,
    canvas_height: float,
) -> LayerBox:
    """平移矩形并夹取在画布内（逐行移植 .NET ``PreviewRectangleManipulator.Move``）。"""
    if canvas_width <= 0 or canvas_height <= 0:
        return box
    x = min(max(box.x + delta_x / canvas_width, 0.0), max(0.0, 1.0 - box.width))
    y = min(max(box.y + delta_y / canvas_height, 0.0), max(0.0, 1.0 - box.height))
    return LayerBox(round(x, 4), round(y, 4), box.width, box.height)


def resize_box(
    box: LayerBox,
    zone: PreviewHitZone,
    delta_x: float,
    delta_y: float,
    canvas_width: float,
    canvas_height: float,
    *,
    minimum_size: float = MIN_NORMALIZED_SIZE,
) -> LayerBox:
    """按边/角缩放矩形（逐行移植 .NET ``PreviewRectangleManipulator.Resize``）。

    关键语义（与 .NET 一致，别"顺手优化"）：

    * **对边拖拽只改一个方向**：拖右边只改宽度、拖上边只改高度；
      ``BoundsY`` 保持不变的那条注释指的就是这个（对应 Python 的 ``y_percent``）。
    * 越界时把该边夹在 ``[0, 对边 - 最小值]``，矩形整体不会翻面。
    * 结果四舍五入到 4 位小数。
    """
    if not zone.is_resize or canvas_width <= 0 or canvas_height <= 0:
        return box

    delta_nx = delta_x / canvas_width
    delta_ny = delta_y / canvas_height
    x, y = box.x, box.y
    width, height = box.width, box.height

    if zone is PreviewHitZone.EAST:
        width = min(max(width + delta_nx, minimum_size), 1.0 - x)
    elif zone is PreviewHitZone.WEST:
        next_x = min(max(x + delta_nx, 0.0), x + width - minimum_size)
        width += x - next_x
        x = next_x
    elif zone is PreviewHitZone.SOUTH:
        height = min(max(height + delta_ny, minimum_size), 1.0 - y)
    elif zone is PreviewHitZone.NORTH:
        next_y = min(max(y + delta_ny, 0.0), y + height - minimum_size)
        height += y - next_y
        y = next_y
    elif zone is PreviewHitZone.SOUTH_EAST:
        width = min(max(width + delta_nx, minimum_size), 1.0 - x)
        height = min(max(height + delta_ny, minimum_size), 1.0 - y)
    elif zone is PreviewHitZone.SOUTH_WEST:
        next_x = min(max(x + delta_nx, 0.0), x + width - minimum_size)
        width += x - next_x
        x = next_x
        height = min(max(height + delta_ny, minimum_size), 1.0 - y)
    elif zone is PreviewHitZone.NORTH_EAST:
        width = min(max(width + delta_nx, minimum_size), 1.0 - x)
        next_y = min(max(y + delta_ny, 0.0), y + height - minimum_size)
        height += y - next_y
        y = next_y
    elif zone is PreviewHitZone.NORTH_WEST:
        next_x = min(max(x + delta_nx, 0.0), x + width - minimum_size)
        next_y = min(max(y + delta_ny, 0.0), y + height - minimum_size)
        width += x - next_x
        height += y - next_y
        x = next_x
        y = next_y

    x = min(max(x, 0.0), 1.0 - minimum_size)
    y = min(max(y, 0.0), 1.0 - minimum_size)
    width = min(max(width, minimum_size), 1.0 - x)
    height = min(max(height, minimum_size), 1.0 - y)
    return LayerBox(round(x, 4), round(y, 4), round(width, 4), round(height, 4))


def apply_box_drag(
    box: LayerBox,
    zone: PreviewHitZone,
    delta_x: float,
    delta_y: float,
    canvas_width: float,
    canvas_height: float,
) -> LayerBox:
    """把一次拖拽应用到矩形：按区域平移或缩放。

    .NET 侧对应 ``ApplyPreviewDragDelta`` / ``ApplySourceCropDragDelta``，
    两个画布用的是同一套 ``PreviewRectangleManipulator``；Python 也共用本函数，
    避免成片框与源取景框各写一份、行为慢慢分叉。
    """
    if zone is PreviewHitZone.MOVE:
        return move_box(box, delta_x, delta_y, canvas_width, canvas_height)
    if zone.is_resize:
        return resize_box(box, zone, delta_x, delta_y, canvas_width, canvas_height)
    return box


def cursor_for_zone(zone: PreviewHitZone) -> Qt.CursorShape:
    """命中区域对应的鼠标指针形状（对齐 .NET ``OverlayEditorView.ToCursor``）。"""
    return {
        PreviewHitZone.NORTH: Qt.CursorShape.SizeVerCursor,
        PreviewHitZone.SOUTH: Qt.CursorShape.SizeVerCursor,
        PreviewHitZone.EAST: Qt.CursorShape.SizeHorCursor,
        PreviewHitZone.WEST: Qt.CursorShape.SizeHorCursor,
        PreviewHitZone.NORTH_EAST: Qt.CursorShape.SizeBDiagCursor,
        PreviewHitZone.SOUTH_WEST: Qt.CursorShape.SizeBDiagCursor,
        PreviewHitZone.NORTH_WEST: Qt.CursorShape.SizeFDiagCursor,
        PreviewHitZone.SOUTH_EAST: Qt.CursorShape.SizeFDiagCursor,
        PreviewHitZone.MOVE: Qt.CursorShape.SizeAllCursor,
    }.get(zone, Qt.CursorShape.ArrowCursor)


def layer_box(layer: LayerSpec, canvas_ratio: float) -> LayerBox:
    """按图层参数计算示意矩形（宽度为画布宽度百分比，高度按画布比例缩放）。

    ``height_percent > 0`` 时高度上限为画布高度的百分比（与滤镜图裁剪一致）。

    **中心点 = ``x_percent``/``y_percent`` + ``offset_x``/``offset_y``**，
    与滤镜图 ``main_w*(x_percent/100 + offset_x) - overlay_w/2`` 完全一致。
    早期版本漏掉 offset，于是拖「位置 X/Y」时画面会动、预览不动。

    位移之后的矩形**不做画布内夹取**：滤镜图也不夹，画面确实会有一部分移出
    画布。若在预览里夹回去，用户会看到"预览不动但成片动了"，比越界显示更糟。
    """
    width = max(0.01, layer.width_percent / 100.0)
    height = max(0.01, min(width * canvas_ratio, 1.0))
    if layer.height_percent > 0.0:
        height = max(0.01, min(height, layer.height_percent / 100.0))
    center_x = layer.x_percent / 100.0 + max(-1.0, min(layer.offset_x, 1.0))
    center_y = layer.y_percent / 100.0 + max(-1.0, min(layer.offset_y, 1.0))
    return LayerBox(x=center_x - width / 2, y=center_y - height / 2, width=width, height=height)


def percent_from_point(point: QPointF, canvas: QRectF) -> tuple[float, float]:
    """把画布内坐标换算为图层中心百分比（0-100，自动夹取）。"""
    if canvas.width() <= 0 or canvas.height() <= 0:
        return 50.0, 50.0
    x = (point.x() - canvas.left()) / canvas.width() * 100.0
    y = (point.y() - canvas.top()) / canvas.height() * 100.0
    return max(0.0, min(x, 100.0)), max(0.0, min(y, 100.0))


def reference_region_box() -> LayerBox:
    """导入蒙版的默认覆盖区（画成暗红参考区）。

    对齐 .NET ``OverlayLayer.ImportedMaskBounds``：只有显示值，不参与渲染；
    作用是让用户在不调任何参数时就看清默认会盖到哪里。
    """
    x, y, width, height = IMPORTED_MASK_BOUNDS
    return LayerBox(x=x, y=y, width=width, height=height)


def source_crop_box(layer: LayerSpec | None) -> LayerBox | None:
    """源素材取景框（白框，源素材归一化坐标）。

    返回 ``None`` 表示该图层没有可显示的取景信息：
    - 没有图层；
    - 未手动指定取景（``source_crop_bounds`` 为空）且未启用按画幅自动取景——
      此时由渲染器自动选取，预览不画框，避免"画了个假框"。
    """
    if layer is None:
        return None
    bounds = layer.source_crop_bounds
    if bounds is None:
        if not layer.source_crop_canvas:
            return None
        # 自动取景：按成片画幅比例从源素材中心裁切（与 _source_crop_filters 同义）。
        # 这里只知道比例，不知道源尺寸，故按整帧显示并提示由渲染器决定实际裁剪。
        return LayerBox(x=0.0, y=0.0, width=1.0, height=1.0)
    x, y, width, height = (max(0.0, min(float(value), 1.0)) for value in bounds)
    return LayerBox(
        x=x,
        y=y,
        width=max(0.01, width),
        height=max(0.01, height),
    )


class LayerPreviewCanvas(QWidget):
    """成片画面示意：显示所有启用图层的位置，可拖拽与滚轮缩放。

    ``show_reference`` 打开时，额外画出导入蒙版的默认覆盖区（暗红参考区），
    对齐 .NET「蒙版区域预览」里的红框；``source_crop_layer`` 不为空时画白框
    表示该图层的源素材取景范围。
    """

    layer_moved = Signal(str, float, float)
    layer_scaled = Signal(str, float)
    # 拖边/角改尺寸：与「滚轮改宽度」分开，语义不同（一个改单边，一个按中心缩放）。
    layer_resized = Signal(str, float, float)
    # 源素材取景白框被拖动：携带新的归一化 (x, y, w, h)。
    # 对齐 .NET：白框拖拽只改取景，不动输出叠层框。
    source_crop_moved = Signal(float, float, float, float)

    def __init__(self, *, show_reference: bool = False, show_source_crop: bool = False) -> None:
        super().__init__()
        self._show_reference = show_reference
        self._show_source_crop = show_source_crop
        self.setMinimumHeight(CANVAS_MIN_HEIGHT)
        self.setMaximumHeight(CANVAS_MAX_HEIGHT)
        # 让控件自己长成目标宽高比，而不是占满一整行：否则画布两侧会留下大片空白
        # （用户实测反馈"预览框不对"的直接观感）。
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        # 不自动填充背景：画布四周应显示容器（页面）底色，而不是 Qt 默认的窗口色。
        # 贴纸多为透明 PNG，一旦控件自带不透明底色，透明区域就会被涂成灰块。
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self._layers: list[LayerSpec] = []
        self._selected_id: str | None = None
        self._aspect = "9:16"
        self._dragging = False
        self._drag_last: QPointF | None = None
        self._active_zone = PreviewHitZone.NONE
        # 素材缩略图缓存：key = 规范化路径，value = (mtime, 原图)
        self._image_cache: dict[str, tuple[float, QPixmap | None]] = {}

    # ────────────────────────────── 尺寸 ──────────────────────────────

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt 命名
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt 命名
        """给定宽度时，能完整放下画布所需的最小高度。"""
        ratio_w, ratio_h = CANVAS_ASPECTS[self._aspect]
        target_ratio = ratio_w / ratio_h
        canvas_width = min(max(width - CANVAS_MARGIN * 2, 10.0), CANVAS_MAX_WIDTH)
        canvas_height = canvas_width / target_ratio
        return max(CANVAS_MIN_HEIGHT, int(round(canvas_height + CANVAS_MARGIN * 2)))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """把控件宽度收口到"画布宽度 + 留白"。

        控件被放进一整行时会被拉得很宽（实测 950×420），而 9:16 画布受高度限制
        只有 225 宽——多出来的宽度全变成画布两侧的空白，正是用户看到的"预览框
        周围一大片空"。这里按高度反推应有的宽度并立即改回，让控件贴合画布。
        """
        super().resizeEvent(event)
        target = self._preferred_width_for_height(self.height())
        if target > 0 and abs(self.width() - target) > 1:
            self.resize(target, self.height())

    def _preferred_width_for_height(self, height: int) -> int:
        ratio_w, ratio_h = CANVAS_ASPECTS[self._aspect]
        canvas_height = max(float(height) - CANVAS_MARGIN * 2, 10.0)
        canvas_width = min(canvas_height * ratio_w / ratio_h, CANVAS_MAX_WIDTH)
        return int(round(canvas_width + CANVAS_MARGIN * 2))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        """优先尺寸：按"目标画布尺寸"算控件尺寸，保证预览足够大且能落在首屏内。

        **必须是纯函数**（只依赖画幅与常量）。早期版本在高度超过最小值时改用
        ``self.height()`` 反推宽度，结果 ``sizeHint().height()`` 被自己上一次的
        返回值顶住，永远停在最小值，布局跟着算错（16:9 拿到 380×400 的控件、
        画布却只有 360×202，控件内 48% 是空白）。
        实际高度由布局决定后，宽度交给 :meth:`resizeEvent` 收口。
        """
        ratio_w, ratio_h = CANVAS_ASPECTS[self._aspect]
        target_ratio = ratio_w / ratio_h
        canvas_height = float(CANVAS_TARGET_HEIGHT)
        canvas_width = canvas_height * target_ratio
        if canvas_width > CANVAS_MAX_WIDTH:
            canvas_width = CANVAS_MAX_WIDTH
            canvas_height = canvas_width / target_ratio
        return QSize(
            int(round(canvas_width + CANVAS_MARGIN * 2)),
            int(round(canvas_height + CANVAS_MARGIN * 2)),
        )

    # ────────────────────────────── 对外 ──────────────────────────────

    def set_layers(self, layers: list[LayerSpec], *, aspect: str | None = None) -> None:
        self._layers = [layer for layer in layers if layer.enabled]
        if aspect in CANVAS_ASPECTS:
            self._aspect = aspect
        if self._selected_id not in {layer.id for layer in self._layers}:
            self._selected_id = self._layers[-1].id if self._layers else None
        # 画幅变了 → 控件应占的尺寸随之变化，重新按尺寸策略收口。
        self.updateGeometry()
        self.update()

    def set_selected(self, layer_id: str | None) -> None:
        self._selected_id = layer_id
        self.update()

    @property
    def aspect(self) -> str:
        return self._aspect

    @property
    def show_reference(self) -> bool:
        return self._show_reference

    @property
    def show_source_crop(self) -> bool:
        return self._show_source_crop

    def selected_layer(self) -> LayerSpec | None:
        """当前选中的图层（供源素材取景白框使用）。"""
        return self._selected_layer()

    # ────────────────────────────── 素材缩略图 ──────────────────────────────

    def _source_pixmap(self, layer: LayerSpec) -> QPixmap | None:
        """加载图层素材用于预览；视频/自叠影/缺失文件返回 ``None``（只画框）。

        只处理静态图片：paintEvent 里不能起 ffmpeg 抽帧，否则拖拽会卡死。
        失败结果同样缓存，避免每次重绘都去敲一次磁盘。
        """
        if layer.is_self_source:
            return None
        path = Path(layer.source)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            return None

        key = str(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        cached = self._image_cache.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        pixmap = QPixmap(key)
        loaded: QPixmap | None = pixmap if not pixmap.isNull() else None
        if len(self._image_cache) >= IMAGE_CACHE_LIMIT:
            self._image_cache.pop(next(iter(self._image_cache)), None)
        self._image_cache[key] = (mtime, loaded)
        return loaded

    def invalidate_images(self) -> None:
        """丢弃缩略图缓存（素材被替换后调用）。"""
        self._image_cache.clear()
        self.update()

    # ────────────────────────────── 绘制 ──────────────────────────────

    def _canvas_rect(self) -> QRectF:
        """画布矩形：在可用区域内按宽高比**放到最大**并居中。

        取 ``min(按宽度缩放, 按高度缩放)``——这正是"contain"语义。早期写成
        "先按宽度、超高再退回按高度"，在宽扁控件里会得到极小宽度（见模块 docstring）。
        """
        available = QRectF(
            CANVAS_MARGIN,
            CANVAS_MARGIN,
            max(self.width() - CANVAS_MARGIN * 2, 10.0),
            max(self.height() - CANVAS_MARGIN * 2, 10.0),
        )
        ratio_w, ratio_h = CANVAS_ASPECTS[self._aspect]
        target_ratio = ratio_w / ratio_h
        width = min(available.width(), available.height() * target_ratio)
        height = width / target_ratio
        left = available.left() + (available.width() - width) / 2
        top = available.top() + (available.height() - height) / 2
        return QRectF(left, top, width, height)

    def _layer_rect(self, layer: LayerSpec, canvas: QRectF) -> QRectF:
        ratio = canvas.height() / canvas.width() if canvas.width() else 1.0
        box = layer_box(layer, ratio)
        return self._box_rect(box, canvas)

    def _box_rect(self, box: LayerBox, canvas: QRectF) -> QRectF:
        return QRectF(
            canvas.left() + box.x * canvas.width(),
            canvas.top() + box.y * canvas.height(),
            box.width * canvas.width(),
            box.height * canvas.height(),
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 先铺满控件底色，再画画布。
        # 为什么显式铺：Qt 在部分平台会无视 setAutoFillBackground(False)，用调色板的
        # 窗口色填充，结果是一块灰底。贴纸多为透明 PNG，底色不明确时观感很差。
        painter.fillRect(self.rect(), QColor(theme.SURFACE_CANVAS))

        canvas = self._canvas_rect()
        painter.fillRect(canvas, QColor(theme.GATE_WELL))
        painter.setPen(QPen(QColor(theme.BRAND_BLOOM), 1.2))
        painter.drawRect(canvas)

        painter.setPen(QPen(QColor(theme.ON_GATE_MUTED), 1, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(canvas.center().x(), canvas.top()),
            QPointF(canvas.center().x(), canvas.bottom()),
        )
        painter.drawLine(
            QPointF(canvas.left(), canvas.center().y()),
            QPointF(canvas.right(), canvas.center().y()),
        )

        # 参考区先画（在图层之下），与 .NET 的 Z 序一致：红框在下、蓝框在上。
        if self._show_reference:
            self._paint_reference_region(painter, canvas)

        for layer in self._layers:
            rect = self._layer_rect(layer, canvas)
            selected = layer.id == self._selected_id

            pixmap = self._source_pixmap(layer)
            if pixmap is not None:
                self._paint_artwork(painter, pixmap, rect, layer)

            painter.setBrush(
                Qt.BrushStyle.NoBrush
                if pixmap is not None
                else QColor(242, 138, 156, 60 if selected else 30)
            )
            painter.setPen(
                QPen(QColor(theme.BRAND_PRIMARY if selected else theme.INK_MUTED), 1.6 if selected else 1.0)
            )
            painter.drawRect(rect)
            # 名称画在框底：框内上半部分通常是素材主体，画在上方会糊在画面上。
            painter.setPen(QColor(theme.ON_GATE))
            painter.drawText(
                rect.adjusted(3, 2, -3, -2),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                layer.display_name[:14],
            )

        if self._show_source_crop:
            self._paint_source_crop(painter, canvas)
        painter.end()

    def _paint_reference_region(self, painter: QPainter, canvas: QRectF) -> None:
        """导入蒙版的默认覆盖区：暗红描边 + 半透明填充（对齐 .NET 的红框）。"""
        rect = self._box_rect(reference_region_box(), canvas)
        if rect.width() < 1 or rect.height() < 1:
            return
        painter.setBrush(QColor(232, 93, 92, 0x22))
        painter.setPen(QPen(QColor(232, 93, 92, 0x99), 1.5))
        painter.drawRect(rect)

    def _paint_source_crop(self, painter: QPainter, canvas: QRectF) -> None:
        """源素材取景框：白框 + 半透明白填充（对齐 .NET 的白框）。

        只对**选中**图层画：源取景是逐图层的，同时画多条会互相干扰。
        """
        box = source_crop_box(self._selected_layer())
        if box is None:
            return
        rect = self._box_rect(box, canvas)
        if rect.width() < 1 or rect.height() < 1:
            return
        painter.setBrush(QColor(255, 255, 255, 0x22))
        painter.setPen(QPen(QColor(SOURCE_CROP_FRAME_COLOR), 2))
        painter.drawRect(rect)

    def _paint_artwork(self, painter: QPainter, pixmap: QPixmap, rect: QRectF, layer: LayerSpec) -> None:
        """把素材按"填满并居中裁切"画进图层框，套用透明度与旋转。

        与滤镜图的 ``scale=w:-2`` + 居中裁切语义一致，因此预览与成片对得上。
        """
        if rect.width() < 1 or rect.height() < 1:
            return

        scaled = pixmap.scaled(
            max(1, int(round(rect.width()))),
            max(1, int(round(rect.height()))),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # KeepAspectRatioByExpanding 会超出目标框，按中心裁切后再画。
        source = QRectF(
            max(0.0, (scaled.width() - rect.width()) / 2),
            max(0.0, (scaled.height() - rect.height()) / 2),
            min(scaled.width(), rect.width()),
            min(scaled.height(), rect.height()),
        )

        painter.save()
        painter.setOpacity(max(0.0, min(layer.opacity, 1.0)))
        if abs(layer.rotation_degrees) >= 0.1:
            center = rect.center()
            transform = QTransform()
            transform.translate(center.x(), center.y())
            transform.rotate(layer.rotation_degrees)
            transform.translate(-center.x(), -center.y())
            painter.setTransform(transform, True)
        painter.drawPixmap(rect, scaled, source)
        painter.restore()

    # ────────────────────────────── 交互 ──────────────────────────────
    #
    # 与 .NET ``OverlayEditorView.xaml.cs`` 一致的三点语义：
    # 1. 按下时把指针位置换算成**连续增量**（记录上一次位置），不是「跳到指针处」——
    #    否则小步拖拽会被量化成跳变；
    # 2. 拖边/角按命中区域**只改对应方向**，拖中心才平移（见 resize_box）；
    # 3. 悬停时按命中区域切换指针形状，让用户知道这里能拉伸。

    def _canvas_point(self, point: QPointF) -> tuple[float, float]:
        """控件坐标 → 画布内坐标（左上为原点，单位像素）。"""
        canvas = self._canvas_rect()
        return point.x() - canvas.left(), point.y() - canvas.top()

    def _selected_box(self) -> LayerBox | None:
        layer = self._selected_layer() or (self._layers[-1] if self._layers else None)
        if layer is None:
            return None
        canvas = self._canvas_rect()
        ratio = canvas.height() / canvas.width() if canvas.width() else 1.0
        return layer_box(layer, ratio)

    def _crop_box(self) -> LayerBox | None:
        """源取景白框；未手动取景时返回 ``None``（没有可拖的目标）。"""
        return source_crop_box(self._selected_layer())

    def _active_box(self) -> LayerBox | None:
        """当前画布上可交互的矩形。

        取景画布只操作白框，成片画布只操作蓝框——.NET 也是两张画布各自
        ``HitTest``，这样两个框不会互相抢命中。
        """
        return self._crop_box() if self._show_source_crop else self._selected_box()

    def hit_zone(self, point: QPointF) -> PreviewHitZone:
        """当前指针落在可交互矩形的哪个区域（供鼠标形状与按下判定共用）。"""
        box = self._active_box()
        if box is None:
            return PreviewHitZone.NONE
        canvas = self._canvas_rect()
        return hit_test_box(self._canvas_point(point), box, canvas.width(), canvas.height())

    def _layer_at(self, point: QPointF) -> LayerSpec | None:
        canvas = self._canvas_rect()
        for layer in reversed(self._layers):
            if self._layer_rect(layer, canvas).contains(point):
                return layer
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        if self._show_source_crop:
            # 取景画布：没有白框（自动取景）时先落一个"整幅"框，用户才有东西可拖。
            if self._crop_box() is None:
                layer = self._selected_layer()
                if layer is None:
                    super().mousePressEvent(event)
                    return
                self.source_crop_moved.emit(0.0, 0.0, 1.0, 1.0)
        else:
            # 点在某个未选中的图层上 → 先切选中，再按该图层的框开始拖。
            layer = self._layer_at(event.position())
            if layer is not None and layer.id != self._selected_id:
                self._selected_id = layer.id
                self.update()

        zone = self.hit_zone(event.position())
        if zone is PreviewHitZone.NONE:
            # 与 .NET 一致：点在框外时仍允许从画布开始，按中心平移处理，
            # 否则用户必须精准点在框上才能拖动，手感很差。
            zone = PreviewHitZone.MOVE
        if not self._show_source_crop and self._selected_layer() is None and self._layers:
            self._selected_id = self._layers[-1].id

        self._active_zone = zone
        self._drag_last = event.position()
        self._dragging = True
        self.setCursor(cursor_for_zone(zone))
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            # 悬停反馈：让用户看出边角可拉伸。
            self.setCursor(cursor_for_zone(self.hit_zone(event.position())))
            super().mouseMoveEvent(event)
            return

        box = self._active_box()
        if box is None or self._drag_last is None:
            super().mouseMoveEvent(event)
            return

        canvas = self._canvas_rect()
        if canvas.width() <= 0 or canvas.height() <= 0:
            return
        current = event.position()
        delta_x = current.x() - self._drag_last.x()
        delta_y = current.y() - self._drag_last.y()
        if abs(delta_x) < 0.01 and abs(delta_y) < 0.01:
            return
        self._drag_last = current

        if self._show_source_crop:
            moved = apply_box_drag(box, self._active_zone, delta_x, delta_y, canvas.width(), canvas.height())
            self.source_crop_moved.emit(moved.x, moved.y, moved.width, moved.height)
            event.accept()
            return

        layer = self._selected_layer()
        if layer is None:
            super().mouseMoveEvent(event)
            return
        ratio = canvas.height() / canvas.width()
        if self._active_zone is PreviewHitZone.MOVE:
            moved = apply_box_drag(box, self._active_zone, delta_x, delta_y, canvas.width(), canvas.height())
            self.layer_moved.emit(layer.id, (moved.x + moved.width / 2) * 100, (moved.y + moved.height / 2) * 100)
        else:
            resized = apply_box_drag(box, self._active_zone, delta_x, delta_y, canvas.width(), canvas.height())
            self.layer_resized.emit(
                layer.id,
                resized.width * 100,
                self._height_limit_after_resize(box, resized, ratio),
            )
        event.accept()

    @staticmethod
    def _height_limit_after_resize(original: LayerBox, resized: LayerBox, ratio: float) -> float:
        """按 .NET 语义决定缩放后要写回的「高度上限」百分比。

        ``LayerSpec.height_percent == 0`` 表示**不限制**（高度跟随素材自然比例）。
        判定只看两件事：

        1. 原来有没有高度上限（``height ≈ width × 画布高宽比`` 就是没有）；
        2. 这次拖拽有没有动到高度（只拖左右边时高度像素值不变）。

        两者都成立 → 继续发 ``0``，让高度保持"跟随宽度"。
        若此处发真实百分比，只拖一次右边就会把高度**冻结**成固定值，
        之后改宽度比例再也不跟随——这是很容易踩的坑。
        """
        had_limit = abs(original.height - original.width * ratio) > 1e-6
        # 容差取 1e-4：.NET 的 Resize 会把结果四舍五入到 4 位小数，因此"没动高度"
        # 在数值上可能是 0.888888… → 0.8889 这种量级的差，用 1e-6 会把"没动"判成"动了"。
        height_untouched = abs(resized.height - original.height) <= 1e-4

        if not had_limit and height_untouched:
            return 0.0
        return resized.height * 100

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False
        self._drag_last = None
        self._active_zone = PreviewHitZone.NONE
        self.setCursor(cursor_for_zone(self.hit_zone(event.position())))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            self.unsetCursor()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """滚轮按中心等比缩放宽度（.NET 无此交互，作为便捷补充保留）。"""
        layer = self._layer_at(event.position()) or self._selected_layer()
        if layer is None:
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y() / 120.0
        new_width = max(2.0, min(layer.width_percent + steps * 3.0, 200.0))
        self._selected_id = layer.id
        self.layer_scaled.emit(layer.id, new_width)
        event.accept()

    def _selected_layer(self) -> LayerSpec | None:
        return next((layer for layer in self._layers if layer.id == self._selected_id), None)
