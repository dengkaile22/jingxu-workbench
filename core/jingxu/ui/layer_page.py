"""蒙版 / 贴纸图层页：素材列表 + 叠加参数编辑（共用一套界面）。"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jingxu.domain.layers import (
    LayerAspectMode,
    LayerFixedRatio,
    LayerKind,
    LayerShapeMask,
    LayerSpec,
)
from jingxu.domain.media import MediaAsset
from jingxu.domain.render import OverlayFitMode, RenderSettings
from jingxu.infrastructure.frame_preview import FramePreviewError, render_composite_frame
from jingxu.infrastructure.layer_store import LayerStore, overlay_library_path
from jingxu.infrastructure.sticker_library import StickerLibrary
from jingxu.ui import theme
from jingxu.ui.layer_preview import LayerPreviewCanvas
from jingxu.ui.widgets import Caption, PrimaryButton, SecondaryButton, SectionHeader

# .NET 预设：画中画（右下角）与顶部横幅（截图类场景）。
PIP_PRESET = {"x_percent": 73.0, "y_percent": 73.0, "width_percent": 42.0, "height_percent": 0.0, "fit": "contain"}
SCREENSHOT_PRESET = {"x_percent": 50.0, "y_percent": 24.0, "width_percent": 100.0, "height_percent": 48.0, "fit": "stretch"}
# 「统一应用到全部层」复制的字段集，逐条对齐 .NET ``OverlayVisualSettings.FromLayer``：
# 边界(x/y/w/h)、透明度、适配方式、内容缩放、偏移、旋转、羽化、顶部渐隐、
# 源取景开关与自动上下偏移、源取景框。
# **不含** source / 时段 / z_index / enabled——那些不是"画法"；尤其 source，
# 统一过去会让所有轨道指向同一个素材文件。
VISUAL_SETTING_FIELDS = (
    "x_percent",
    "y_percent",
    "width_percent",
    "height_percent",
    "opacity",
    "fit",
    "scale_percent",
    "offset_x",
    "offset_y",
    "rotation_degrees",
    "feather",
    "top_fade",
    "source_crop_canvas",
    "source_crop_y",
    "source_crop_bounds",
)

PREVIEW_ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
}
PREVIEW_IMAGE_SIZE = (216, 384)
PREVIEW_FFMPEG_MISSING_TEXT = "未找到 FFmpeg，无法生成合成预览。"
PREVIEW_MATERIAL_MISSING_TEXT = "请先在混剪页导入素材"
PREVIEW_TEMP_DIRECTORY = "jingxu-gate-preview"

# 对齐 .NET ``OverlayEditorViewModel.MinNormalizedSize``（0.05）：
# 分割位置（= 顶部 Y + 高度上限）与顶部 Y 之间至少保留 5% 的画面高度。
MIN_SPLIT_HEIGHT_PERCENT = 5


class FramePreviewBridge(QObject):
    """合成预览后台线程 → UI 线程的信号桥。"""

    done = Signal(str)
    failed = Signal(str)


class LayerPage(QWidget):
    """图层列表 + 参数表单；修改即保存到数据目录。"""

    layers_changed = Signal()
    # 「随机替换素材库」开关变化。蒙版页的该开关与混剪页里的同名开关是同一语义，
    # 两者必须双向同步（.NET 两处绑同一属性）；用独立信号而不是复用
    # ``layers_changed``，避免"勾一下开关"被当成"轨道变了"而触发全量刷新。
    overlay_random_changed = Signal(bool)

    def __init__(
        self,
        store: LayerStore,
        *,
        title: str,
        file_filter: str,
        hint: str,
        ffmpeg: Path | None = None,
        base_video_provider: Callable[[], object] | None = None,
        sticker_library: StickerLibrary | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._file_filter = file_filter
        self._ffmpeg = Path(ffmpeg) if ffmpeg else None
        self._base_video_provider = base_video_provider
        # 贴纸模式：素材库 + 轨道两段式，参数只保留贴纸画法（对齐 .NET 贴纸页）。
        # 蒙版模式下这些属性不参与，蒙版页保持原有参数集不变。
        self._is_sticker = store.kind is LayerKind.STICKER
        # 两种图层都有素材库（对齐 .NET：蒙版页有「蒙版素材库」，贴纸页有「贴纸素材库」）。
        # 库只负责"有哪些素材"，轨道负责"画法"；蒙版库落在独立文件里。
        self._library = sticker_library or StickerLibrary(
            store_path=None if self._is_sticker else overlay_library_path()
        )
        self._use_random_library = False
        self._layers: list[LayerSpec] = []
        self._updating = False
        self._aspect = "9:16"
        # 混剪页画幅（供「跟随混剪画幅」模式使用）；与 _aspect 分开保存，
        # 以便用户选择独立画幅后仍能在切回跟随模式时恢复。
        self._composition_aspect = "9:16"
        # 混剪页真实成片尺寸（供「跟随混剪画幅」与合成预览使用）；
        # 与 _composition_aspect 分开保存：画幅被用户改成独立模式后仍能恢复。
        self._composition_size: tuple[int, int] = PREVIEW_ASPECT_SIZES["9:16"]
        self._preview_running = False
        self._preview_thread: threading.Thread | None = None

        # 整个页面放进滚动区：蒙版/贴纸的参数区很长，窗口不够高时下方选项
        # （旋转、上淡入、羽化、预设、画幅等）会被直接截断且无法滚动到。
        # 与合成页保持同一写法。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        self._scroll_area = scroll

        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)
        layout.addLayout(self._build_header(title))
        self._status = Caption("")
        self._status.setVisible(False)
        layout.addWidget(self._status)

        layout.addSpacing(12)
        if self._is_sticker:
            # .NET 贴纸页：先「贴纸素材库」，再「贴纸轨道」。轨道由素材库「添加」生成。
            layout.addWidget(SectionHeader("贴纸素材库"))
            layout.addSpacing(6)
            layout.addLayout(self._build_sticker_library_bar())
            layout.addSpacing(6)
            layout.addWidget(self._build_sticker_library_list())
            layout.addSpacing(14)
            layout.addWidget(SectionHeader("贴纸轨道"))
            layout.addSpacing(6)
        else:
            # .NET 蒙版页同样是两段式：先「蒙版素材库」，再轨道列表。
            # 素材库是「蒙版随机替换」的抽取来源，与轨道（画法）分开。
            layout.addWidget(SectionHeader("蒙版素材库"))
            layout.addSpacing(6)
            layout.addLayout(self._build_mask_library_bar())
            layout.addSpacing(6)
            layout.addWidget(self._build_sticker_library_list())
            layout.addSpacing(14)
            layout.addWidget(SectionHeader("蒙版轨道"))
            layout.addSpacing(6)

        # 图层列表在上、预览独占一整行在下。
        # 为什么不是左右并排：预览画布是固定宽高比（9:16 等），并排时它只拿到半宽，
        # 画布被压到极小（实测 950×240 里只画出 117×208，占 11%），看起来就是一个
        # 孤零零的小黑框、四周全是空白。通栏后画布能铺满可用高度，素材看得清。
        self._list = QListWidget()
        self._list.setObjectName("CompositionMaterials")
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.itemChanged.connect(self._on_item_changed)
        # 滚动区里 stretch 不再分配高度，必须给下限，否则列表会被压成一条。
        self._list.setMinimumHeight(160)
        layout.addWidget(self._list)

        layout.addSpacing(10)
        # 蒙版页两张画布并排，对齐 .NET「蒙版区域预览」：
        # 左＝成片画面示意（暗红参考区 + 蓝框输出位置 + 蒙版素材本体），
        # 右＝源素材取景（独立白框）。
        # 白框**只画在右边的取景画布上**：.NET 把它放在独立 Canvas 里，
        # 因为它是"源素材坐标系"，与成片坐标系的输出框叠在一起会互相干扰、
        # 让人误以为白框也是输出位置。
        # 贴纸页只有一张（.NET 贴纸页也只有「成片画面示意」）。
        self._canvas = LayerPreviewCanvas(show_reference=not self._is_sticker)
        self._canvas.layer_moved.connect(self._on_layer_moved)
        self._canvas.layer_scaled.connect(self._on_layer_scaled)
        self._canvas.layer_resized.connect(self._on_layer_resized)

        canvas_row = QHBoxLayout()
        canvas_row.setContentsMargins(0, 0, 0, 0)
        canvas_row.setSpacing(16)
        canvas_row.addStretch(1)
        canvas_row.addWidget(self._canvas, alignment=Qt.AlignmentFlag.AlignTop)
        # 注意：变量名不能叫 _source_crop_canvas —— 蒙版参数表单里已有同名复选框
        # （「按画幅比例自动取景」），重名会把画布覆盖成复选框，启动即报错。
        self._source_crop_preview: LayerPreviewCanvas | None = None
        if not self._is_sticker:
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(4)
            column_layout.addWidget(Caption("源素材取景"))
            # 第二张画布只画白框，不画图层本体：它是"源素材坐标系"，与成片画布不同源。
            self._source_crop_preview = LayerPreviewCanvas(show_source_crop=True)
            self._source_crop_preview.setToolTip(
                "白框为源素材取景范围（源素材坐标系）。可直接拖拽：拖框内平移、拖边或角改大小；"
                "下方「源素材取景」数值会同步。"
            )
            self._source_crop_preview.source_crop_moved.connect(self._on_canvas_source_crop_moved)
            column_layout.addWidget(self._source_crop_preview)
            canvas_row.addWidget(column, alignment=Qt.AlignmentFlag.AlignTop)
        canvas_row.addStretch(1)
        layout.addLayout(canvas_row)

        layout.addSpacing(6)
        # 对齐 .NET 的两行提示：交互方式 + 视觉参数当前值。
        if self._is_sticker:
            self._preview_hint = Caption("拖拽预览中的贴纸可调整位置，滚轮调整宽度。")
        else:
            self._preview_hint = Caption(
                "接近成片的静帧示意：暗红框为默认上半叠区；蓝框控制成片中的输出位置与尺寸，"
                "拖拽中心平移、拖边或角改大小。旁边的白框独立控制源素材取景。"
            )
        layout.addWidget(self._preview_hint)
        self._preview_effect_hint = Caption("")
        layout.addWidget(self._preview_effect_hint)
        # .NET 贴纸页在预览下方给出一行参数摘要（位置/尺寸/透明度/旋转），
        # 便于不看控件也能确认当前画法。
        if self._is_sticker:
            self._sticker_summary = Caption("")
            layout.addWidget(self._sticker_summary)

        if not self._is_sticker:
            # 「合成预览」是蒙版专属：它按真实滤镜链渲染主片+蒙版静帧。
            # 贴纸是叠加元素，.NET 贴纸页没有这一区，故不显示。
            layout.addSpacing(14)
            layout.addWidget(SectionHeader("合成预览"))
            layout.addSpacing(8)
            layout.addLayout(self._build_preview_section())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("叠加参数"))
        layout.addSpacing(8)
        layout.addWidget(Caption(hint))
        layout.addSpacing(8)
        layout.addWidget(self._build_sticker_form() if self._is_sticker else self._build_form())
        layout.addStretch(0)

        # 两种图层的素材库都要初始化列表（蒙版页也有「蒙版素材库」）。
        self._refresh_library()

        # 合成预览（真实滤镜静帧）是蒙版专属：贴纸页没有该区块，
        # 因此贴纸模式下把按钮置空，其余代码统一以 None 判断跳过。
        if self._is_sticker:
            self._preview_button = None
        else:
            bridge = FramePreviewBridge(self)
            bridge.done.connect(self._on_preview_done)
            bridge.failed.connect(self._on_preview_failed)
            self._bridge = bridge
            self._preview_button.clicked.connect(self._start_preview)

        self._reload()
        self._refresh_preview_availability()

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_header(self, title: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("Title")
        row.addWidget(label)
        row.addStretch(1)

        import_button = SecondaryButton("导入素材…")
        import_button.clicked.connect(self._import)
        row.addWidget(import_button)

        remove_button = SecondaryButton("移除选中")
        remove_button.clicked.connect(self._remove_selected)
        row.addWidget(remove_button)

        clear_button = SecondaryButton("清空")
        clear_button.clicked.connect(self._clear)
        row.addWidget(clear_button)
        return row

    def _build_preview_section(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self._preview_image = QLabel("暂无预览")
        self._preview_image.setFixedSize(*PREVIEW_IMAGE_SIZE)
        self._preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_image.setStyleSheet(
            f"background: {theme.GATE_WELL}; border: 1px solid {theme.BRAND_BLOOM};"
            f"border-radius: {theme.RADIUS_STANDARD}px; color: {theme.ON_GATE_MUTED};"
            f"font-size: 11px;"
        )
        row.addWidget(self._preview_image)

        controls = QVBoxLayout()
        controls.setSpacing(8)
        self._preview_button = SecondaryButton("刷新合成预览")
        controls.addWidget(self._preview_button)
        self._preview_status = Caption("")
        controls.addWidget(self._preview_status)
        controls.addStretch(1)
        row.addLayout(controls, stretch=1)
        return row

    def _build_sticker_library_bar(self) -> QHBoxLayout:
        """素材库工具条：导入素材 / 添加到轨道 / 清空素材库。

        蒙版与贴纸共用（对齐 .NET：两页都有「素材库 + 轨道」两段式），
        只是文案不同——贴纸叫「导入贴纸」，蒙版叫「导入蒙版素材」。
        """
        noun = "贴纸" if self._is_sticker else "蒙版素材"
        row = QHBoxLayout()
        row.setSpacing(8)
        import_button = SecondaryButton(f"导入{noun}…")
        import_button.setToolTip(
            f"把素材导入{noun}库（不会直接生成轨道）。" if self._is_sticker
            else "把蒙版素材导入素材库（不会直接生成轨道）。"
        )
        import_button.clicked.connect(self._import_to_library)
        row.addWidget(import_button)

        self._add_from_library = PrimaryButton("添加到轨道")
        self._add_from_library.setToolTip(f"用素材库里选中的{noun}生成一条轨道。")
        self._add_from_library.clicked.connect(self._add_track_from_library)
        self._add_from_library.setEnabled(False)
        row.addWidget(self._add_from_library)

        clear_button = SecondaryButton("清空素材库")
        clear_button.clicked.connect(self._clear_library)
        row.addWidget(clear_button)

        self._library_caption = Caption("")
        row.addWidget(self._library_caption, stretch=1)
        return row

    def _build_mask_library_bar(self) -> QHBoxLayout:
        """蒙版素材库工具条（对齐 .NET 蒙版页的库工具条）。

        .NET 在这里放的是：随机替换开关 + 清理失效 + 清空库 + 导入蒙版素材。
        其中「生成时随机替换 1 个素材库蒙版」与混剪页「蒙版覆盖」里的同名开关
        绑定的是**同一个属性**，因此两处必须同步（见 ``set_overlay_random``）。
        """
        row = QHBoxLayout()
        row.setSpacing(8)

        self._random_library = QCheckBox("生成时随机替换 1 个素材库蒙版")
        self._random_library.setToolTip(
            "每条成片从素材库选择 1 个蒙版，沿用当前选中轨道的位置、尺寸、透明度、羽化与起始片段。"
        )
        self._random_library.stateChanged.connect(self._on_random_library_changed)
        row.addWidget(self._random_library)

        import_button = PrimaryButton("导入蒙版素材")
        import_button.setToolTip("把蒙版素材导入素材库（不会直接生成轨道）。")
        import_button.clicked.connect(self._import_to_library)
        row.addWidget(import_button)

        prune_button = SecondaryButton("清理失效")
        prune_button.setToolTip("移除素材库里文件已丢失的条目（不删除磁盘文件）。")
        prune_button.clicked.connect(self._prune_library)
        row.addWidget(prune_button)

        clear_button = SecondaryButton("清空库")
        clear_button.setToolTip("清空蒙版素材库（不删除磁盘文件）。")
        clear_button.clicked.connect(self._clear_library)
        row.addWidget(clear_button)

        self._library_caption = Caption("")
        row.addWidget(self._library_caption, stretch=1)
        # 蒙版库工具条没有「添加到轨道」（.NET 蒙版页同样没有：蒙版轨道由「导入素材」
        # 或库条目双击生成）；保持属性存在以兼容共用的库刷新逻辑。
        self._add_from_library = None
        return row

    def set_overlay_random(self, enabled: bool) -> None:
        """由混剪页同步「随机替换蒙版」开关（两处绑同一语义）。

        "值相同就返回"的守卫避免与混剪页形成信号循环。
        """
        check = getattr(self, "_random_library", None)
        if check is None or check.isChecked() == bool(enabled):
            return
        check.blockSignals(True)
        check.setChecked(bool(enabled))
        self._use_random_library = bool(enabled)
        check.blockSignals(False)

    @property
    def overlay_random_enabled(self) -> bool:
        check = getattr(self, "_random_library", None)
        return bool(check is not None and check.isChecked())

    def _prune_library(self) -> None:
        """移除素材库里文件已丢失的条目。"""
        assert self._library is not None
        removed = self._library.prune_missing()
        self._refresh_library()
        self._set_status(
            f"已清理 {removed} 条失效素材。" if removed else "没有失效条目。",
            warn=False,
        )

    def _build_sticker_library_list(self) -> QWidget:
        self._library_list = QListWidget()
        self._library_list.setObjectName("CompositionMaterials")
        self._library_list.setMinimumHeight(112)
        self._library_list.setMaximumHeight(150)
        self._library_list.currentRowChanged.connect(self._on_library_selection_changed)
        return self._library_list

    def _build_sticker_form(self) -> QWidget:
        """贴纸参数：只保留「贴纸画法」，不含羽化/蒙版适配/源取景等蒙版专属项。"""
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self._start = self._make_seconds_spin()
        self._end = self._make_seconds_spin()
        grid.addWidget(Caption("起点（秒）"), 0, 0)
        grid.addWidget(self._start, 0, 1)
        grid.addWidget(Caption("终点（0=片尾）"), 0, 2)
        grid.addWidget(self._end, 0, 3)

        self._x = self._make_percent_spin(50)
        self._y = self._make_percent_spin(50)
        grid.addWidget(Caption("X %"), 1, 0)
        grid.addWidget(self._x, 1, 1)
        grid.addWidget(Caption("Y %"), 1, 2)
        grid.addWidget(self._y, 1, 3)

        self._width = self._make_percent_spin(30)
        self._height = QSpinBox()
        self._height.setRange(0, 100)
        self._height.setSuffix("%")
        self._height.setSpecialValueText("自然高度")
        grid.addWidget(Caption("宽 %"), 2, 0)
        grid.addWidget(self._width, 2, 1)
        grid.addWidget(Caption("高 %"), 2, 2)
        grid.addWidget(self._height, 2, 3)

        self._opacity = QSpinBox()
        self._opacity.setRange(0, 100)
        self._opacity.setValue(100)
        self._opacity.setSuffix("%")
        self._opacity.setSuffix("%")
        self._rotation = QSpinBox()
        self._rotation.setRange(-180, 180)
        self._rotation.setSuffix("°")
        grid.addWidget(Caption("透明度 %"), 3, 0)
        grid.addWidget(self._opacity, 3, 1)
        grid.addWidget(Caption("旋转 °"), 3, 2)
        grid.addWidget(self._rotation, 3, 3)

        # 「尺寸」＝内容在边界框内的均匀缩放（对齐 .NET OverlayEditorView「尺寸」滑杆 0.01–4）。
        # 超过 100 放大后中心裁回框内，低于 100 缩小后在框内留透明白边。
        self._scale = QDoubleSpinBox()
        self._scale.setRange(1.0, 400.0)
        self._scale.setSingleStep(5.0)
        self._scale.setDecimals(0)
        self._scale.setValue(100.0)
        self._scale.setSuffix("%")
        self._scale.setToolTip(
            "内容在边框内的均匀缩放：>100% 放大后中心裁回框内，<100% 缩小后在框内留透明边。"
        )
        grid.addWidget(Caption("尺寸 %"), 4, 0)
        grid.addWidget(self._scale, 4, 1)

        # 比例行：预览画幅（只影响本页画布）与宽高比锁定
        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(8)
        ratio_row.addWidget(Caption("预览画幅"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._aspect_mode = QComboBox()
        for mode in LayerAspectMode:
            self._aspect_mode.addItem(mode.display_text, mode.value)
        self._aspect_mode.setToolTip("只影响本页预览画布比例，不改变成片画幅。")
        self._aspect_mode.currentIndexChanged.connect(self._on_aspect_mode_changed)
        ratio_row.addWidget(self._aspect_mode)

        ratio_row.addWidget(Caption("锁定宽高比"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._fixed_ratio = QComboBox()
        for ratio in LayerFixedRatio:
            self._fixed_ratio.addItem(ratio.display_text, ratio.value)
        self._fixed_ratio.setToolTip("锁定后调整宽度或高度会按比例联动另一个方向。")
        self._fixed_ratio.currentIndexChanged.connect(self._on_fixed_ratio_changed)
        ratio_row.addWidget(self._fixed_ratio)

        ratio_row.addStretch(1)
        grid.addLayout(ratio_row, 4, 0, 1, 4)
        self._ratio_hint = Caption("")
        self._ratio_hint.setWordWrap(True)
        grid.addWidget(self._ratio_hint, 5, 0, 1, 4)

        options = QHBoxLayout()
        options.setSpacing(14)
        self._enabled = QCheckBox("启用该图层")
        options.addWidget(self._enabled)
        # 「随机贴纸库」：渲染时把轨道素材替换为素材库里随机一款（确定性洗牌）。
        self._random_library = QCheckBox("随机贴纸库（每次成片从素材库随机替换）")
        self._random_library.setToolTip(
            "开启后，每条轨道会从素材库中按种子确定性选取一款贴纸："
            "同一成片序号结果固定可复现，一个成片内多条轨道不重复。"
        )
        self._random_library.stateChanged.connect(self._on_random_library_changed)
        options.addWidget(self._random_library)
        options.addStretch(1)
        grid.addLayout(options, 6, 0, 1, 4)

        for spin in (self._start, self._end, self._x, self._y, self._opacity, self._rotation, self._scale):
            spin.valueChanged.connect(self._on_form_changed)
        self._width.valueChanged.connect(self._on_width_changed)
        self._height.valueChanged.connect(self._on_height_changed)
        self._enabled.stateChanged.connect(self._on_form_changed)

        self._split_position = None
        self._top_fade = None
        self._feather = None
        self._source_crop_y = None
        self._fit = None
        # 「位置 X/Y」＝输出叠层框整体位移，与源取景一样是蒙版专属控件。
        self._offset_x = None
        self._offset_y = None
        self._remove_black = None
        self._mix_audio = None
        self._source_crop_canvas = None
        self._start_clip = None
        # 源素材取景也是蒙版专属（贴纸没有「源素材」概念，贴纸本身就是素材）。
        self._crop_x = None
        self._crop_y = None
        self._crop_width = None
        self._crop_height = None
        self._crop_reset = None
        self._crop_hint = None
        return widget

    # ─────────────────────────── 贴纸素材库操作 ───────────────────────────

    def _refresh_library(self) -> None:
        if self._library is None:
            return
        self._library.prune_missing()
        entries = self._library.entries
        previous = self._library_list.currentRow()
        self._library_list.blockSignals(True)
        try:
            self._library_list.clear()
            for entry in entries:
                item = QListWidgetItem(f"{entry.display_name} · {entry.kind_text}")
                item.setData(Qt.ItemDataRole.UserRole, entry.id)
                item.setToolTip(f"{entry.path}\n双击可添加到轨道")
                self._library_list.addItem(item)
        finally:
            self._library_list.blockSignals(False)
        if 0 <= previous < len(entries):
            self._library_list.setCurrentRow(previous)
        noun = "贴纸" if self._is_sticker else "蒙版素材"
        self._library_caption.setText(
            f"{noun}库 {len(entries)} 项" if entries else f"{noun}库为空，点「导入{noun}…」添加"
        )
        if getattr(self, "_add_from_library", None) is not None:
            self._add_from_library.setEnabled(bool(entries))
        # 「随机贴纸库」开关只存在于贴纸表单；蒙版页的随机替换开关在混剪页。
        random_toggle = getattr(self, "_random_library", None)
        if random_toggle is not None and random_toggle.isChecked() and not entries:
            self._set_status(
                "已开启随机贴纸库，但素材库为空；渲染时不会替换贴纸。请先导入贴纸。",
                warn=True,
            )

    def _on_library_selection_changed(self, row: int) -> None:
        self._add_from_library.setEnabled(row >= 0)

    def _import_to_library(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "导入贴纸素材", "", self._file_filter)
        if not paths:
            return
        assert self._library is not None
        added = self._library.add([Path(path) for path in paths])
        self._refresh_library()
        skipped = len(paths) - added
        message = f"已导入 {added} 项贴纸素材。"
        if skipped > 0:
            message += f"（{skipped} 项已在库中或格式不支持）"
        self._set_status(message)

    def _add_track_from_library(self) -> None:
        """用素材库里选中的贴纸生成一条轨道（对齐 .NET「添加」）。"""
        if self._library is None:
            return
        row = self._library_list.currentRow()
        entries = self._library.entries
        if not (0 <= row < len(entries)):
            self._set_status("请先在素材库中选择一项贴纸。", warn=True)
            return
        entry = entries[row]
        if not entry.exists():
            self._set_status(f"贴纸文件已不存在：{entry.path}", warn=True)
            return
        self._store.add(entry.path)
        self._reload(keep_selection=False)
        rows = self._list.count()
        if rows:
            self._list.setCurrentRow(rows - 1)
        self._set_status(f"已从素材库添加轨道：{entry.display_name}")

    def _clear_library(self) -> None:
        if self._library is None:
            return
        entries = self._library.entries
        if not entries:
            self._set_status("素材库已经是空的。")
            return
        answer = QMessageBox.question(
            self,
            "清空素材库",
            f"确认清空贴纸素材库（{len(entries)} 项）？已存在的贴纸轨道不会受影响。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self._library.clear()
        self._refresh_library()
        self._set_status(f"已清空 {removed} 项贴纸素材（轨道未改动）。")

    def _on_random_library_changed(self, *_args: object) -> None:
        self._use_random_library = bool(self._random_library.isChecked())
        noun = "贴纸" if self._is_sticker else "蒙版"
        if self._use_random_library and self._library is not None and not self._library.entries:
            self._set_status(
                f"已开启随机{noun}库，但素材库为空。请先导入素材，否则渲染时不会替换。",
                warn=True,
            )
            self.overlay_random_changed.emit(self._use_random_library)
            return
        self._set_status(
            f"已开启随机{noun}库：每次成片会按种子从素材库替换素材。"
            if self._use_random_library
            else f"已关闭随机{noun}库：轨道使用各自绑定的素材。"
        )
        # 蒙版页的开关与混剪页「蒙版覆盖」里的同名开关是同一语义，改动要通知壳层。
        self.overlay_random_changed.emit(self._use_random_library)

    @property
    def random_library_enabled(self) -> bool:
        """是否开启随机贴纸库（供渲染编排读取）。"""
        return self._use_random_library

    def _build_form(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self._start = self._make_seconds_spin()
        self._end = self._make_seconds_spin()
        grid.addWidget(Caption("起点（秒）"), 0, 0)
        grid.addWidget(self._start, 0, 1)
        grid.addWidget(Caption("终点（0=片尾）"), 0, 2)
        grid.addWidget(self._end, 0, 3)

        self._x = self._make_percent_spin(50)
        self._y = self._make_percent_spin(50)
        grid.addWidget(Caption("中心 X (%)"), 1, 0)
        grid.addWidget(self._x, 1, 1)
        grid.addWidget(Caption("中心 Y (%)"), 1, 2)
        grid.addWidget(self._y, 1, 3)

        self._width = self._make_percent_spin(30)
        self._opacity = QSpinBox()
        self._opacity.setRange(0, 100)
        # 默认值取 .NET 蒙版默认的不透明度 0.28 换算成「透明度」刻度 = 72%。
        # 写成 28 会与标签自相矛盾（标签说 0=不透明，却默认给了 28% 透明）。
        self._opacity.setValue(72)
        self._opacity.setSuffix("%")
        grid.addWidget(Caption("宽度 (%)"), 2, 0)
        grid.addWidget(self._width, 2, 1)
        grid.addWidget(Caption("透明度（0–100%）"), 2, 2)
        grid.addWidget(self._opacity, 2, 3)
        # 「尺寸」＝内容在边界框内的均匀缩放（对齐 .NET OverlayEditorView「尺寸」滑杆 0.01–4）
        self._scale = QDoubleSpinBox()
        self._scale.setRange(1.0, 400.0)
        self._scale.setSingleStep(5.0)
        self._scale.setDecimals(0)
        self._scale.setValue(100.0)
        self._scale.setSuffix("%")
        self._scale.setToolTip(
            "内容在边框内的均匀缩放：>100% 放大后中心裁回框内，<100% 缩小后在框内留透明边。"
        )
        # 「位置 X / 位置 Y」＝对输出叠层框的整体位移（对齐 .NET OffsetX/OffsetY，
        # 归一化 -1~1，1 表示平移一个画面宽/高）。与上面「中心 X/Y」是两套参数：
        # 中心决定框先落在哪，位移再整体挪框，互不干扰。
        offset_row = QHBoxLayout()
        offset_row.setSpacing(6)
        self._offset_x = self._make_offset_spin()
        self._offset_y = self._make_offset_spin()
        offset_row.addWidget(Caption("位置 X"), alignment=Qt.AlignmentFlag.AlignVCenter)
        offset_row.addWidget(self._offset_x)
        offset_row.addWidget(Caption("位置 Y"), alignment=Qt.AlignmentFlag.AlignVCenter)
        offset_row.addWidget(self._offset_y)
        offset_row.addStretch(1)
        grid.addLayout(offset_row, 3, 0, 1, 4)

        scale_row = QHBoxLayout()
        scale_row.setSpacing(6)
        scale_row.addWidget(Caption("尺寸"), alignment=Qt.AlignmentFlag.AlignVCenter)
        scale_row.addWidget(self._scale)
        scale_row.addStretch(1)
        grid.addLayout(scale_row, 4, 0, 1, 2)

        self._height = QSpinBox()
        self._height.setRange(0, 100)
        self._height.setSuffix("%")
        self._height.setSpecialValueText("自然高度")
        self._split_position = QSpinBox()
        self._split_position.setRange(0, 100)
        self._split_position.setSuffix("%")
        grid.addWidget(Caption("高度上限（0=自然）"), 5, 0)
        grid.addWidget(self._height, 5, 1)
        grid.addWidget(Caption("分割位置"), 5, 2)
        grid.addWidget(self._split_position, 5, 3)

        self._rotation = QSpinBox()
        self._rotation.setRange(-180, 180)
        self._rotation.setSuffix("°")
        grid.addWidget(Caption("旋转 (±180°)"), 6, 0)
        grid.addWidget(self._rotation, 6, 1)
        self._start_clip = QSpinBox()
        self._start_clip.setRange(1, 999)
        self._start_clip.setSuffix(" 起生效")
        grid.addWidget(Caption("起始片段"), 6, 2)
        grid.addWidget(self._start_clip, 6, 3)

        # 上向淡入 / 底边羽化（.NET 分割线两条滑杆的等价控件）
        fade_row = QHBoxLayout()
        fade_row.setSpacing(8)
        fade_row.addWidget(Caption("上向淡入"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._top_fade = QDoubleSpinBox()
        self._top_fade.setRange(0.0, 1.0)
        self._top_fade.setSingleStep(0.05)
        self._top_fade.setDecimals(2)
        fade_row.addWidget(self._top_fade)
        fade_row.addWidget(Caption("羽化"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._feather = QDoubleSpinBox()
        self._feather.setRange(0.0, 1.0)
        self._feather.setSingleStep(0.05)
        self._feather.setDecimals(2)
        self._feather.setValue(0.0)
        fade_row.addWidget(self._feather)
        fade_row.addWidget(Caption("蒙版适配"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._fit = QComboBox()
        for mode in OverlayFitMode:
            self._fit.addItem(mode.display_text, mode.value)
        fade_row.addWidget(self._fit)
        fade_row.addWidget(Caption("自动上下偏移"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._source_crop_y = QDoubleSpinBox()
        self._source_crop_y.setRange(-1.0, 1.0)
        self._source_crop_y.setSingleStep(0.1)
        self._source_crop_y.setDecimals(2)
        # 与 .NET 同名同义（``SourceCropY``，-1 偏上 / 0 居中 / 1 偏下）：
        # 未手动取景时，蒙版源裁成画幅比例后的上下选取；手动取景优先于它。
        self._source_crop_y.setToolTip(
            "未设置手动源素材取景时，蒙版源裁成画幅比例的上下选取"
            "（-1 偏上 / 0 居中 / 1 偏下）。混剪页选「裁成画幅再覆盖」时生效。"
        )
        fade_row.addWidget(self._source_crop_y)
        fade_row.addStretch(1)
        grid.addLayout(fade_row, 7, 0, 1, 4)

        options = QHBoxLayout()
        options.setSpacing(14)
        self._remove_black = QCheckBox("黑底抠除（把黑色当作透明）")
        self._enabled = QCheckBox("启用该图层")
        self._mix_audio = QCheckBox("混入蒙版音轨")
        self._source_crop_canvas = QCheckBox("按画幅比例自动取景")
        options.addWidget(self._remove_black)
        options.addWidget(self._enabled)
        options.addWidget(self._mix_audio)
        options.addWidget(self._source_crop_canvas)
        options.addStretch(1)
        grid.addLayout(options, 8, 0, 1, 4)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        for label, handler in (
            ("画中画预设", self._apply_pip_preset),
            ("顶部横幅预设", self._apply_screenshot_preset),
            ("统一尺寸到全部层", self._apply_unified_size),
            ("统一起始片段", self._apply_start_clip_to_all),
            ("统一应用到全部层", self._apply_visual_settings_to_all),
        ):
            button = SecondaryButton(label)
            button.clicked.connect(handler)
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        grid.addLayout(preset_row, 9, 0, 1, 4)

        # 源素材取景（独立于输出叠层框）：对齐 .NET 同名的四个数值 + 「重置为自动取景」。
        # 未手动取景时由「蒙版适配」与「自动上下偏移」自动决定；一旦设置即优先生效
        # （见 filter_graph._source_crop_filters）。
        layout_index = 10
        grid.addWidget(SectionHeader("源素材取景（独立于输出叠层框）"), layout_index, 0, 1, 4)
        grid.addWidget(
            Caption("手动填写或拖动白框；手动取景优先于「自动上下偏移」。重置后恢复自动选取。"),
            layout_index + 1,
            0,
            1,
            4,
        )
        crop_row = QHBoxLayout()
        crop_row.setSpacing(6)
        crop_row.addWidget(Caption("X"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._crop_x = self._make_percent_spin(0, minimum=0)
        crop_row.addWidget(self._crop_x)
        crop_row.addWidget(Caption("Y"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._crop_y = self._make_percent_spin(0, minimum=0)
        crop_row.addWidget(self._crop_y)
        crop_row.addWidget(Caption("宽度"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._crop_width = self._make_percent_spin(100, minimum=0)
        crop_row.addWidget(self._crop_width)
        crop_row.addWidget(Caption("高度"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._crop_height = self._make_percent_spin(100, minimum=0)
        crop_row.addWidget(self._crop_height)
        self._crop_reset = SecondaryButton("重置为自动取景")
        self._crop_reset.setToolTip("清除手动取景，改由「蒙版适配」与「自动上下偏移」自动决定。")
        self._crop_reset.clicked.connect(self._reset_source_crop)
        crop_row.addWidget(self._crop_reset)
        crop_row.addStretch(1)
        grid.addLayout(crop_row, layout_index + 2, 0, 1, 4)
        self._crop_hint = Caption("")
        grid.addWidget(self._crop_hint, layout_index + 3, 0, 1, 4)

        # 比例行：预览画幅模式（不改成片）与宽高比锁定（对齐 .NET FixedAspectRatio）。
        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(8)
        ratio_row.addWidget(Caption("预览画幅"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._aspect_mode = QComboBox()
        for mode in LayerAspectMode:
            self._aspect_mode.addItem(mode.display_text, mode.value)
        self._aspect_mode.setToolTip("只影响本页预览画布比例，不改变成片画幅。")
        ratio_row.addWidget(self._aspect_mode)

        ratio_row.addWidget(Caption("锁定宽高比"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._fixed_ratio = QComboBox()
        for ratio in LayerFixedRatio:
            self._fixed_ratio.addItem(ratio.display_text, ratio.value)
        self._fixed_ratio.setToolTip("锁定后调整宽度或高度会按比例联动另一个方向。")
        ratio_row.addWidget(self._fixed_ratio)

        ratio_row.addStretch(1)
        grid.addLayout(ratio_row, layout_index + 3, 0, 1, 4)
        self._ratio_hint = Caption("")
        self._ratio_hint.setWordWrap(True)
        grid.addWidget(self._ratio_hint, layout_index + 4, 0, 1, 4)

        for spin in (
            self._start,
            self._end,
            self._x,
            self._y,
            self._opacity,
            self._rotation,
            self._start_clip,
            self._top_fade,
            self._feather,
            self._source_crop_y,
            self._scale,
            self._offset_x,
            self._offset_y,
        ):
            spin.valueChanged.connect(self._on_form_changed)
        # 宽高走专用处理：锁定比例时需要联动另一个方向。
        self._width.valueChanged.connect(self._on_width_changed)
        self._height.valueChanged.connect(self._on_height_changed)
        self._split_position.valueChanged.connect(self._on_split_changed)
        self._fit.currentIndexChanged.connect(self._on_form_changed)
        self._remove_black.stateChanged.connect(self._on_form_changed)
        # 源素材取景：四个数值任一变化都写回 source_crop_bounds。
        for spin in (self._crop_x, self._crop_y, self._crop_width, self._crop_height):
            spin.valueChanged.connect(self._on_source_crop_changed)
        self._enabled.stateChanged.connect(self._on_form_changed)
        self._mix_audio.stateChanged.connect(self._on_form_changed)
        self._source_crop_canvas.stateChanged.connect(self._on_form_changed)
        self._fixed_ratio.currentIndexChanged.connect(self._on_fixed_ratio_changed)
        self._aspect_mode.currentIndexChanged.connect(self._on_aspect_mode_changed)
        return widget

    @staticmethod
    def _make_seconds_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 3600.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" s")
        return spin

    @staticmethod
    def _make_percent_spin(value: int, *, minimum: int = 1) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, 200)
        spin.setValue(value)
        spin.setSuffix("%")
        return spin

    # ────────────────────────────── 数据 ──────────────────────────────

    def _reload(self, keep_selection: bool = True) -> None:
        current = self._list.currentRow() if keep_selection else -1
        self._layers = self._store.layers

        self._updating = True
        self._list.clear()
        for layer in self._layers:
            item = QListWidgetItem(self._row_text(layer))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.enabled else Qt.CheckState.Unchecked)
            item.setToolTip(str(layer.source))
            self._list.addItem(item)
        if 0 <= current < len(self._layers):
            self._list.setCurrentRow(current)
        elif self._layers:
            self._list.setCurrentRow(0)
        self._updating = False

        self._sync_canvases()
        self._populate_form()

    def _selected(self) -> LayerSpec | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._layers):
            return self._layers[row]
        return None

    def _populate_form(self) -> None:
        layer = self._selected()
        self._updating = True
        has_selection = layer is not None
        for widget in (
            self._start,
            self._end,
            self._x,
            self._y,
            self._width,
            self._height,
            self._opacity,
            self._rotation,
            self._start_clip,
            self._top_fade,
            self._feather,
            self._fit,
            self._source_crop_y,
            self._source_crop_canvas,
            self._mix_audio,
            self._remove_black,
            self._enabled,
            self._fixed_ratio,
            self._aspect_mode,
            self._scale,
            self._offset_x,
            self._offset_y,
            self._crop_x,
            self._crop_y,
            self._crop_width,
            self._crop_height,
            self._crop_reset,
        ):
            # 贴纸模式下蒙版专属控件不存在（值为 None），跳过即可。
            if widget is not None:
                widget.setEnabled(has_selection)

        if layer is not None:
            self._start.setValue(layer.start_seconds)
            self._end.setValue(layer.end_seconds)
            self._x.setValue(int(layer.x_percent))
            self._y.setValue(int(layer.y_percent))
            self._width.setValue(int(layer.width_percent))
            self._height.setValue(int(round(layer.height_percent)))
            self._opacity.setValue(self._opacity_percent_from_layer(layer))
            self._rotation.setValue(int(round(layer.rotation_degrees)))
            self._scale.setValue(max(1.0, min(float(layer.scale_percent), 400.0)))
            if self._offset_x is not None:
                # 对齐 .NET OffsetX/OffsetY：归一化 -1~1 的整体位移。
                self._offset_x.setValue(max(-1.0, min(float(layer.offset_x), 1.0)))
                self._offset_y.setValue(max(-1.0, min(float(layer.offset_y), 1.0)))
            if self._start_clip is not None:
                self._start_clip.setValue(max(1, int(layer.start_clip_index)))
            if self._top_fade is not None:
                self._top_fade.setValue(max(0.0, min(layer.top_fade, 1.0)))
            if self._feather is not None:
                self._feather.setValue(max(0.0, min(layer.feather, 1.0)))
            if self._fit is not None:
                fit_index = self._fit.findData(layer.fit)
                self._fit.setCurrentIndex(fit_index if fit_index >= 0 else 0)
            if self._source_crop_y is not None:
                self._source_crop_y.setValue(max(-1.0, min(layer.source_crop_y, 1.0)))
            if self._source_crop_canvas is not None:
                self._source_crop_canvas.setChecked(layer.source_crop_canvas)
            if self._crop_width is not None:
                # 回填手动取景；未设置时显示为「全幅」（100/100/0/0）并给出自动提示。
                bounds = layer.source_crop_bounds
                if bounds is None:
                    self._crop_x.setValue(0)
                    self._crop_y.setValue(0)
                    self._crop_width.setValue(100)
                    self._crop_height.setValue(100)
                    if self._crop_hint is not None:
                        self._crop_hint.setText("当前为自动取景（由「蒙版适配」与「自动上下偏移」决定）。")
                else:
                    self._crop_x.setValue(int(round(bounds[0] * 100)))
                    self._crop_y.setValue(int(round(bounds[1] * 100)))
                    self._crop_width.setValue(int(round(bounds[2] * 100)))
                    self._crop_height.setValue(int(round(bounds[3] * 100)))
                    self._refresh_source_crop_hint()
            if self._mix_audio is not None:
                self._mix_audio.setChecked((layer.audio_mode or "discard").lower() == "mix")
            if self._remove_black is not None:
                self._remove_black.setChecked(layer.remove_black)
            self._enabled.setChecked(layer.enabled)
            ratio_index = self._fixed_ratio.findData(layer.fixed_ratio.value)
            self._fixed_ratio.setCurrentIndex(ratio_index if ratio_index >= 0 else 0)
        if self._split_position is not None:
            self._sync_split_display(layer.y_percent if layer else 50.0)
        self._updating = False
        self._refresh_ratio_hint()
        self._refresh_sticker_summary(layer)
        self._sync_canvases()

    # ── 透明度语义（两个表单方向相反，对齐 .NET）────────────────────────────
    #
    # .NET 两处的界面刻度是**反的**，移植时必须分开处理：
    #   * 蒙版页 ``OpacityPercent = (1 - Opacity) * 100``：0 = 不透明、100 = 全透明；
    #   * 贴纸页 ``StickerOpacity = Opacity * 100``（``StickerEditorViewModel.cs:590``）：
    #     0 = 全透明、100 = 不透明。
    # 曾把贴纸页也套上蒙版页的换算，于是「透明度 100%」把贴纸整个变没了。

    def _make_offset_spin(self) -> QDoubleSpinBox:
        """归一化位移输入（-1~1，对齐 .NET ``OffsetX``/``OffsetY`` 滑杆）。"""
        spin = QDoubleSpinBox()
        spin.setRange(-1.0, 1.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(0.0)
        spin.setToolTip("对输出叠层框的整体位移（-1~1）；1 表示平移一个画面宽/高。")
        return spin

    def _opacity_percent_from_layer(self, layer: LayerSpec) -> int:
        """图层不透明度 → 本表单控件的百分比刻度。"""
        opacity = max(0.0, min(layer.opacity, 1.0))
        if self._is_sticker:
            return int(round(opacity * 100))
        return int(round((1.0 - opacity) * 100))

    def _opacity_from_percent(self) -> float:
        """本表单控件的百分比刻度 → 图层不透明度。"""
        percent = self._opacity.value() / 100.0
        if self._is_sticker:
            return max(0.0, min(percent, 1.0))
        return max(0.0, min(1.0 - percent, 1.0))

    def _refresh_sticker_summary(self, layer: LayerSpec | None) -> None:
        """刷新贴纸参数摘要（对齐 .NET「成片画面示意」的位置/尺寸/透明度/旋转）。

        贴纸页的「透明度」刻度与 .NET ``StickerOpacity`` 一致（100 = 不透明），
        因此摘要直接显示同一个值，不再另造「可见度」这种第二套说法。
        """
        if not self._is_sticker or not hasattr(self, "_sticker_summary"):
            return
        if layer is None:
            self._sticker_summary.setText("")
            return
        height_text = f"{int(round(layer.height_percent))}%" if layer.height_percent > 0 else "自然"
        opacity_percent = int(round(max(0.0, min(layer.opacity, 1.0)) * 100))
        self._sticker_summary.setText(
            f"位置：({int(round(layer.x_percent))}%, {int(round(layer.y_percent))}%)　"
            f"尺寸：{int(round(layer.width_percent))}% × {height_text}　"
            f"透明度：{opacity_percent}%　"
            f"旋转：{int(round(layer.rotation_degrees))}°"
        )

    def _apply_pip_preset(self) -> None:
        self._apply_preset_to_selected(PIP_PRESET, "已应用画中画预设（右下角，完整适配）。")

    def _apply_screenshot_preset(self) -> None:
        self._apply_preset_to_selected(SCREENSHOT_PRESET, "已应用顶部横幅预设（整宽上半屏）。")

    def _apply_preset_to_selected(self, values: dict, status: str) -> None:
        layer = self._selected()
        if layer is None:
            self._set_status("请先选择要应用预设的图层。", warn=True)
            return
        self._store.replace(layer.with_changes(**values))
        self._layers = self._store.layers
        self._populate_form()
        self._refresh_row_text(layer.id)
        self._sync_canvases()
        self._set_status(status)
        self.layers_changed.emit()

    def _apply_unified_size(self) -> None:
        """把当前图层的宽度与高度上限统一到全部图层（对齐 .NET）。"""
        layer = self._selected()
        if layer is None:
            self._set_status("请先选择作为基准的图层。", warn=True)
            return
        for candidate in list(self._layers):
            if candidate.id == layer.id:
                continue
            self._store.replace(
                candidate.with_changes(
                    width_percent=layer.width_percent,
                    height_percent=layer.height_percent,
                    fit=layer.fit,
                )
            )
        self._layers = self._store.layers
        self._sync_canvases()
        self._set_status(f"已把 {layer.display_name} 的尺寸与适配统一到 {len(self._layers) - 1} 个图层。")
        self.layers_changed.emit()

    def _apply_visual_settings_to_all(self) -> None:
        """把选中图层的**视觉参数**统一到全部图层（对齐 .NET）。

        对应 .NET ``ApplyCurrentVisualSettingsToAllLayersCommand``：复制
        ``OverlayVisualSettings`` 里的全部字段（边界含 x/y、透明度、适配、
        内容缩放、偏移、旋转、羽化、顶部渐隐、源取景与自动上下偏移），
        **并同步起始片段**——.NET 那边也是把 ``StartClipIndex`` 一起带过去的。

        逐条对齐 .NET ``OverlayVisualSettings.FromLayer`` 的字段集；
        素材来源、时段、层级、启用状态**不动**（那不是"画法"）。
        """
        layer = self._selected()
        if layer is None:
            self._set_status("请先选择作为参数来源的图层。", warn=True)
            return
        if len(self._layers) < 2:
            self._set_status("至少需要 2 个图层才能统一参数。", warn=True)
            return

        changes = {name: getattr(layer, name) for name in VISUAL_SETTING_FIELDS}
        changes["start_clip_index"] = layer.start_clip_index
        for candidate in list(self._layers):
            if candidate.id == layer.id:
                continue
            self._store.replace(candidate.with_changes(**changes))
        self._layers = self._store.layers
        self._sync_canvases()
        self._set_status(
            f"已把「{layer.display_name}」的参数（含起始片段 {layer.start_clip_index}）"
            f"统一到其余 {len(self._layers) - 1} 个图层。"
        )
        self.layers_changed.emit()

    def _apply_start_clip_to_all(self) -> None:
        layer = self._selected()
        if layer is None:
            self._set_status("请先选择作为基准的图层。", warn=True)
            return
        for candidate in list(self._layers):
            if candidate.id == layer.id:
                continue
            self._store.replace(candidate.with_changes(start_clip_index=layer.start_clip_index))
        self._layers = self._store.layers
        self._set_status(f"已把起始片段统一为第 {layer.start_clip_index} 个视频。")
        self.layers_changed.emit()

    def effective_canvas_size(self) -> tuple[int, int]:
        """本页预览实际使用的画布像素尺寸。

        逐条对齐 .NET ``StickerEditorViewModel.GetEffectiveCanvasSize`` 的优先级：

        1. 选中轨道的**固定比例**（``FixedAspectRatio``）——它优先于画幅模式；
        2. 「跟随混剪画幅」→ 用混剪页的**真实成片尺寸**（不是只取比例，
           混剪页选 720×1280 时预览与合成预览都必须按 720×1280 走）；
        3. 其余画幅模式 → 该模式的参考尺寸。

        导出合成预览与「跟随混剪」的尺寸都以本函数为准，避免两处各算一套。
        """
        layer = self._selected()
        if layer is not None:
            fixed = layer.fixed_ratio.canvas_size
            if fixed[0] > 0 and fixed[1] > 0:
                return fixed
        if self._selected_aspect_mode() is LayerAspectMode.FOLLOW_COMPOSITION:
            return self._composition_size
        return PREVIEW_ASPECT_SIZES.get(self._aspect, PREVIEW_ASPECT_SIZES["9:16"])

    def set_canvas_aspect(
        self,
        aspect: str,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """由壳层同步混剪页画幅（对齐 .NET ``SyncCompositionCanvas``）。

        ``width``/``height`` 是混剪页的真实成片尺寸；给了就按它算预览画布，
        没给则退回该比例的参考尺寸。用户选了独立画幅时保持不动，避免混剪页
        一改设置就把编辑视角拽走（.NET 同样只在 FollowComposition 时刷新）。
        """
        if aspect in PREVIEW_ASPECT_SIZES:
            self._composition_aspect = aspect
        if width and height and width > 0 and height > 0:
            self._composition_size = (int(width), int(height))
        elif aspect in PREVIEW_ASPECT_SIZES:
            self._composition_size = PREVIEW_ASPECT_SIZES[aspect]
        if self._selected_aspect_mode() is LayerAspectMode.FOLLOW_COMPOSITION:
            self._aspect = self._composition_aspect
        self._sync_canvases(aspect=True)
        self._refresh_preview_availability()

    # ── 画幅模式与宽高比锁定 ────────────────────────────────────────────

    def _selected_aspect_mode(self) -> LayerAspectMode:
        raw = str(self._aspect_mode.currentData() or LayerAspectMode.FOLLOW_COMPOSITION.value)
        try:
            return LayerAspectMode(raw)
        except ValueError:
            return LayerAspectMode.FOLLOW_COMPOSITION

    def _refresh_ratio_hint(self) -> None:
        """显示当前生效的画幅与锁定状态，避免用户误以为改了成片画幅。"""
        mode = self._selected_aspect_mode()
        if mode is LayerAspectMode.FOLLOW_COMPOSITION:
            canvas_text = f"跟随混剪（{self._composition_aspect}）"
        else:
            canvas_text = mode.display_text
        ratio = self._selected_fixed_ratio()
        if ratio is LayerFixedRatio.NONE:
            ratio_text = "未锁定宽高比"
        else:
            ratio_text = f"已锁定 {ratio.display_text}"
        self._ratio_hint.setText(f"预览画幅 {canvas_text} · {ratio_text}")

    def _selected_fixed_ratio(self) -> LayerFixedRatio:
        raw = str(self._fixed_ratio.currentData() or LayerFixedRatio.NONE.value)
        try:
            return LayerFixedRatio(raw)
        except ValueError:
            return LayerFixedRatio.NONE

    def _on_aspect_mode_changed(self, *_args: object) -> None:
        mode = self._selected_aspect_mode()
        if mode is LayerAspectMode.FOLLOW_COMPOSITION:
            self._aspect = self._composition_aspect
        else:
            self._aspect = mode.value
        self._sync_canvases(aspect=True)
        self._refresh_ratio_hint()

    def _on_fixed_ratio_changed(self, *_args: object) -> None:
        """锁定比例立即生效：按当前宽度推出高度并落盘。"""
        if self._updating:
            return
        layer = self._selected()
        ratio = self._selected_fixed_ratio()
        if layer is None:
            self._refresh_ratio_hint()
            return

        width = float(self._width.value())
        if ratio is LayerFixedRatio.NONE:
            updated = layer.with_changes(fixed_aspect_ratio=ratio.value)
            status = "已解除宽高比锁定。"
        else:
            constrained_width, constrained_height = layer.with_changes(
                fixed_aspect_ratio=ratio.value
            ).constrain_size(
                width_percent=width,
                height_percent=float(self._height.value()),
                driven_by="width",
            )
            updated = layer.with_changes(
                fixed_aspect_ratio=ratio.value,
                width_percent=constrained_width,
                height_percent=constrained_height,
            )
            width = constrained_width
            status = f"已锁定 {ratio.display_text}：宽度 {constrained_width:.0f}% → 高度 {constrained_height:.0f}%。"

        if self._store.replace(updated):
            self._updating = True
            self._width.setValue(int(round(width)))
            self._height.setValue(int(round(updated.height_percent)))
            self._sync_split_display(updated.y_percent)
            self._updating = False
            self._layers = self._store.layers
            self._refresh_row_text(updated.id)
            self._sync_canvases()
            self._set_status(status)
            self.layers_changed.emit()
        self._refresh_ratio_hint()

    def _on_width_changed(self, *_args: object) -> None:
        """宽度变更：锁定时按比例联动高度（对齐 .NET OnWidthChanged）。"""
        if self._updating:
            return
        layer = self._selected()
        if layer is None:
            return
        ratio = self._selected_fixed_ratio()
        if ratio is LayerFixedRatio.NONE:
            self._on_form_changed()
            return

        constrained_width, constrained_height = layer.constrain_size(
            width_percent=float(self._width.value()),
            height_percent=float(layer.height_percent),
            driven_by="width",
        )
        self._updating = True
        self._width.setValue(int(round(constrained_width)))
        self._height.setValue(int(round(constrained_height)))
        self._updating = False
        self._on_form_changed()

    def _on_height_changed(self, *_args: object) -> None:
        """高度上限变更：锁定时按比例联动宽度（对齐 .NET OnHeightChanged）。"""
        if self._updating:
            return
        layer = self._selected()
        if layer is None:
            return
        ratio = self._selected_fixed_ratio()
        if ratio is LayerFixedRatio.NONE:
            self._on_form_changed()
            return

        constrained_width, constrained_height = layer.constrain_size(
            width_percent=float(layer.width_percent),
            height_percent=float(self._height.value()),
            driven_by="height",
        )
        self._updating = True
        self._width.setValue(int(round(constrained_width)))
        self._height.setValue(int(round(constrained_height)))
        self._updating = False
        self._on_form_changed()

    def _on_layer_moved(self, layer_id: str, x_percent: float, y_percent: float) -> None:
        layer = self._store.find(layer_id)
        if layer is None:
            return
        self._store.replace(layer.with_changes(x_percent=x_percent, y_percent=y_percent))
        self._layers = self._store.layers
        self._updating = True
        self._x.setValue(int(round(x_percent)))
        self._y.setValue(int(round(y_percent)))
        self._sync_split_display(y_percent)
        self._updating = False
        self._sync_canvases()
        self.layers_changed.emit()

    def _on_layer_scaled(self, layer_id: str, width_percent: float) -> None:
        layer = self._store.find(layer_id)
        if layer is None:
            return
        self._store.replace(layer.with_changes(width_percent=width_percent))
        self._layers = self._store.layers
        self._updating = True
        self._width.setValue(int(round(width_percent)))
        self._updating = False
        self._refresh_row_text(layer_id)
        self._sync_canvases()
        self.layers_changed.emit()

    def _on_layer_resized(self, layer_id: str, width_percent: float, height_percent: float) -> None:
        """拖边/角改尺寸（对齐 .NET ``ApplyPreviewResize``）。

        ``height_percent = 0`` 表示"不限制高度"（保持素材自然比例），
        与高度上限控件的 0 语义一致。
        """
        layer = self._store.find(layer_id)
        if layer is None:
            return
        updated = layer.with_changes(
            width_percent=max(2.0, min(width_percent, 200.0)),
            height_percent=max(0.0, min(height_percent, 100.0)),
        )
        # 固定比例锁定仍然优先：拖角不该悄悄破坏用户锁定的比例。
        if updated.fixed_ratio.aspect_ratio > 0:
            constrained_width, constrained_height = updated.constrain_size(
                width_percent=updated.width_percent,
                height_percent=updated.height_percent or updated.width_percent * 100,
                driven_by="width",
            )
            updated = updated.with_changes(
                width_percent=constrained_width,
                height_percent=0.0 if updated.height_percent == 0.0 else constrained_height,
            )

        self._store.replace(updated)
        self._layers = self._store.layers
        self._updating = True
        self._width.setValue(int(round(updated.width_percent)))
        self._height.setValue(int(round(updated.height_percent)))
        if self._split_position is not None:
            self._sync_split_display(updated.y_percent)
        self._updating = False
        self._refresh_row_text(layer_id)
        self._refresh_sticker_summary(updated)
        self._sync_canvases()
        self.layers_changed.emit()

    def _refresh_row_text(self, layer_id: str) -> None:
        layer = self._store.find(layer_id)
        if layer is None:
            return
        for row, candidate in enumerate(self._layers):
            if candidate.id != layer_id:
                continue
            item = self._list.item(row)
            if item is None:
                continue
            self._updating = True
            item.setText(self._row_text(layer))
            self._updating = False
            return

    @staticmethod
    def _row_text(layer: LayerSpec) -> str:
        rotation = f"    旋转 {layer.rotation_degrees:.0f}°" if abs(layer.rotation_degrees) >= 0.5 else ""
        height = f"    高度上限 {layer.height_percent:.0f}%" if layer.height_percent > 0 else ""
        ratio = layer.fixed_ratio
        ratio_text = f"    锁定 {ratio.display_text}" if ratio is not LayerFixedRatio.NONE else ""
        shape = layer.shape_mask_kind
        shape_text = f"    形状 {shape.value}" if shape is not LayerShapeMask.NONE else ""
        return (
            f"{layer.display_name}    {layer.window_text}    "
            f"位置 {layer.x_percent:.0f}%,{layer.y_percent:.0f}%    宽 {layer.width_percent:.0f}%"
            f"{height}{rotation}{ratio_text}{shape_text}"
        )

    def _on_selection_changed(self, _row: int) -> None:
        if not self._updating:
            self._populate_form()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        row = self._list.row(item)
        if not (0 <= row < len(self._layers)):
            return
        layer = self._layers[row]
        enabled = item.checkState() == Qt.CheckState.Checked
        if layer.enabled != enabled:
            self._store.replace(layer.with_changes(enabled=enabled))
            self._layers = self._store.layers
            self._populate_form()
            self._set_status(f"{layer.display_name}：{'已启用' if enabled else '已停用'}")
            self.layers_changed.emit()

    def _on_form_changed(self, *_args: object) -> None:
        if self._updating:
            return
        layer = self._selected()
        if layer is None:
            return
        fit_value = self._fit.currentData() if self._fit is not None else OverlayFitMode.FILL_CROP.value
        updated = layer.with_changes(
            start_seconds=float(self._start.value()),
            end_seconds=float(self._end.value()),
            x_percent=float(self._x.value()),
            y_percent=float(self._y.value()),
            width_percent=float(self._width.value()),
            height_percent=float(self._height.value()),
            opacity=self._opacity_from_percent(),
            # 尺寸＝边界框内的内容缩放（对齐 .NET OverlayLayer.Scale，1.0 为 100%）。
            scale_percent=float(self._scale.value()),
            # 位置 X/Y＝输出叠层框的整体位移（对齐 .NET OffsetX/OffsetY）；贴纸表单没有这两项。
            offset_x=(
                max(-1.0, min(float(self._offset_x.value()), 1.0))
                if self._offset_x is not None
                else layer.offset_x
            ),
            offset_y=(
                max(-1.0, min(float(self._offset_y.value()), 1.0))
                if self._offset_y is not None
                else layer.offset_y
            ),
            # 以下为蒙版专属项：贴纸模式没有对应控件，保留图层原值不覆盖。
            remove_black=(
                self._remove_black.isChecked() if self._remove_black is not None else layer.remove_black
            ),
            rotation_degrees=float(self._rotation.value()),
            start_clip_index=(
                max(1, int(self._start_clip.value())) if self._start_clip is not None else layer.start_clip_index
            ),
            top_fade=(
                max(0.0, min(float(self._top_fade.value()), 1.0))
                if self._top_fade is not None
                else layer.top_fade
            ),
            feather=(
                max(0.0, min(float(self._feather.value()), 1.0))
                if self._feather is not None
                else layer.feather
            ),
            fit=str(fit_value or OverlayFitMode.FILL_CROP.value),
            source_crop_y=(
                max(-1.0, min(float(self._source_crop_y.value()), 1.0))
                if self._source_crop_y is not None
                else layer.source_crop_y
            ),
            source_crop_canvas=(
                self._source_crop_canvas.isChecked()
                if self._source_crop_canvas is not None
                else layer.source_crop_canvas
            ),
            audio_mode=(
                ("mix" if self._mix_audio.isChecked() else "discard")
                if self._mix_audio is not None
                else layer.audio_mode
            ),
            enabled=self._enabled.isChecked(),
        )
        if self._store.replace(updated):
            row = self._list.currentRow()
            self._updating = True
            item = self._list.item(row)
            if item is not None:
                item.setText(self._row_text(updated))
                item.setCheckState(Qt.CheckState.Checked if updated.enabled else Qt.CheckState.Unchecked)
            if self._split_position is not None:
                self._sync_split_display(updated.y_percent)
            self._updating = False
            self._layers = self._store.layers
            self._sync_canvases()
            self._refresh_sticker_summary(updated)
            self.layers_changed.emit()

    def _on_canvas_source_crop_moved(self, x: float, y: float, width: float, height: float) -> None:
        """拖拽源取景白框 → 写回 ``source_crop_bounds``（对齐 .NET 拖白框）。

        与「输出叠层框」互不影响：白框是源素材坐标系，拖它只改取景。
        """
        layer = self._selected()
        if layer is None:
            return
        bounds = (
            max(0.0, min(float(x), 1.0)),
            max(0.0, min(float(y), 1.0)),
            max(0.01, min(float(width), 1.0)),
            max(0.01, min(float(height), 1.0)),
        )
        if not self._store.replace(layer.with_changes(source_crop_bounds=bounds)):
            return
        self._layers = self._store.layers
        updated = self._store.find(layer.id)
        if updated is not None:
            self._updating = True
            self._crop_x.setValue(int(round(updated.source_crop_bounds[0] * 100)))
            self._crop_y.setValue(int(round(updated.source_crop_bounds[1] * 100)))
            self._crop_width.setValue(int(round(updated.source_crop_bounds[2] * 100)))
            self._crop_height.setValue(int(round(updated.source_crop_bounds[3] * 100)))
            self._updating = False
        self._refresh_source_crop_hint()
        self._sync_canvases()
        self.layers_changed.emit()

    def _on_source_crop_changed(self, *_args: object) -> None:
        """写入手动源素材取景（宽高为 0 视为不设置）。

        与 .NET「源素材取景（独立于输出叠层框）」等价：一旦设置，它就优先于
        「蒙版适配」与「自动上下偏移」生效。
        """
        if self._updating:
            return
        layer = self._selected()
        if layer is None:
            return
        width = self._crop_width.value() / 100.0
        height = self._crop_height.value() / 100.0
        if width <= 0 or height <= 0:
            bounds = None
        else:
            bounds = (
                self._crop_x.value() / 100.0,
                self._crop_y.value() / 100.0,
                width,
                height,
            )
        if self._store.replace(layer.with_changes(source_crop_bounds=bounds)):
            self._layers = self._store.layers
            self._refresh_source_crop_hint()
            self._sync_canvases()
            self.layers_changed.emit()

    def _reset_source_crop(self) -> None:
        """清除手动取景，回到自动（蒙版适配 + 自动上下偏移）。"""
        layer = self._selected()
        if layer is None:
            self._set_status("请先选择一条轨道。", warn=True)
            return
        self._store.replace(layer.with_changes(source_crop_bounds=None))
        self._layers = self._store.layers
        self._populate_form()
        self._set_status("已重置源素材取景为自动（按「蒙版适配」与「自动上下偏移」决定）。")
        self.layers_changed.emit()

    def _refresh_source_crop_hint(self) -> None:
        if self._crop_hint is None:
            return
        self._crop_hint.setText(
            "已手动取景：该设置优先于「蒙版适配」与「自动上下偏移」。"
        )

    def _sync_split_display(self, y_percent: float) -> None:
        """重算分割位置显示：覆盖区底边 = 中心 Y + 高度上限 / 2。

        与 .NET ``OverlayEditorViewModel.SplitPosition``（``BoundsY + BoundsHeight``）
        同为「底边」语义；本页 Y 轴以图层中心为锚点（见 ``filter_graph`` 的
        ``y=main_h*pct-overlay_h/2``），故换算为中心 + 高度/2。
        自然高度时没有底边，该项禁用。

        贴纸页没有「分割位置」（蒙版专属），此时直接返回。
        """
        if self._split_position is None:
            return
        height = self._height.value()
        if height > 0:
            self._split_position.setEnabled(self._selected() is not None)
            split = y_percent + height / 2.0
        else:
            self._split_position.setEnabled(False)
            split = y_percent + MIN_SPLIT_HEIGHT_PERCENT / 2.0
        self._split_position.setValue(max(0, min(int(round(split)), 100)))

    def _on_split_changed(self, *_args: object) -> None:
        """调整分割位置：只移动覆盖区底边，顶边保持不变。

        对齐 .NET ``SplitPosition`` setter 的契约——顶边 ``BoundsY`` 不动、
        只改高度。.NET 在顶边锚点下直接 ``height = bottom - BoundsY``；
        本页以图层中心为锚点，故先按旧高度还原顶边，再反推新高度与新中心。
        """
        if self._updating:
            return
        layer = self._selected()
        if layer is None:
            return
        top = float(layer.y_percent) - float(layer.height_percent) / 2.0
        minimum_bottom = top + MIN_SPLIT_HEIGHT_PERCENT
        maximum_height = max(MIN_SPLIT_HEIGHT_PERCENT, 100.0 - top)
        split = max(float(self._split_position.value()), minimum_bottom)
        height = max(
            MIN_SPLIT_HEIGHT_PERCENT,
            min(round(split - top), maximum_height),
        )
        if abs(height - float(layer.height_percent)) < 0.5:
            self._sync_split_display(layer.y_percent)
            return
        updated = layer.with_changes(
            y_percent=top + height / 2.0,
            height_percent=height,
        )
        if not self._store.replace(updated):
            return
        self._updating = True
        self._y.setValue(int(round(updated.y_percent)))
        self._height.setValue(int(round(height)))
        self._sync_split_display(updated.y_percent)
        self._updating = False
        self._layers = self._store.layers
        self._refresh_row_text(updated.id)
        self._sync_canvases()
        self.layers_changed.emit()

    def _import(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "导入素材", "", self._file_filter)
        if not files:
            return
        added = 0
        for raw in files:
            if Path(raw).is_file():
                self._store.add(Path(raw))
                added += 1
        self._reload(keep_selection=False)
        self._set_status(f"已导入 {added} 个素材。")
        if added:
            self.layers_changed.emit()

    def _remove_selected(self) -> None:
        layer = self._selected()
        if layer is None:
            return
        self._store.remove(layer.id)
        self._reload(keep_selection=False)
        self._set_status(f"已移除：{layer.display_name}")
        self.layers_changed.emit()

    def _clear(self) -> None:
        if not self._layers:
            return
        self._store.clear()
        self._reload(keep_selection=False)
        self._set_status("已清空图层。")
        self.layers_changed.emit()

    def _set_status(self, text: str, *, warn: bool = False) -> None:
        self._status.setObjectName("CaptionWarn" if warn else "Caption")
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    # ────────────────────────────── 合成预览 ──────────────────────────────

    def _base_asset(self) -> MediaAsset | None:
        """调用壳层注入的主片 provider；缺失或返回值非法时返回 None。"""
        if self._base_video_provider is None:
            return None
        try:
            asset = self._base_video_provider()
        except Exception:
            return None
        return asset if isinstance(asset, MediaAsset) else None

    def _refresh_preview_availability(self) -> None:
        """按 FFmpeg 与主片素材可用性刷新预览按钮和提示。

        贴纸页没有「合成预览」区块（该区块渲染主片+蒙版的真实滤镜静帧），
        此时 ``_preview_button`` 为 ``None``，直接跳过。
        """
        if self._preview_button is None:
            return
        if self._ffmpeg is None:
            self._preview_button.setEnabled(False)
            self._set_preview_status(PREVIEW_FFMPEG_MISSING_TEXT)
            return
        if self._base_asset() is None:
            self._preview_button.setEnabled(False)
            self._set_preview_status(PREVIEW_MATERIAL_MISSING_TEXT)
            return
        self._preview_button.setEnabled(not self._preview_running)
        if not self._preview_running:
            self._set_preview_status("")

    def _set_preview_status(self, text: str, *, warn: bool = False) -> None:
        self._preview_status.setObjectName("CaptionWarn" if warn else "Caption")
        self._preview_status.setText(text)
        self._preview_status.setVisible(bool(text))
        self._preview_status.style().unpolish(self._preview_status)
        self._preview_status.style().polish(self._preview_status)

    def _start_preview(self) -> None:
        """按当前画幅与启用图层在后台线程渲染一张合成预览。"""
        if self._preview_running or self._ffmpeg is None:
            return
        base_asset = self._base_asset()
        if base_asset is None:
            self._refresh_preview_availability()
            return
        width, height = self.effective_canvas_size()
        settings = RenderSettings(width=width, height=height, fps=30)
        output_path = Path(tempfile.gettempdir()) / PREVIEW_TEMP_DIRECTORY / f"{uuid4().hex[:8]}.jpg"
        self._preview_running = True
        self._preview_button.setEnabled(False)
        self._set_preview_status("正在合成预览…")
        worker = threading.Thread(
            target=self._render_preview,
            args=(base_asset, tuple(self._store.enabled_layers), settings, output_path),
            daemon=True,
        )
        self._preview_thread = worker
        worker.start()

    def _render_preview(
        self,
        base_asset: MediaAsset,
        layers: tuple[LayerSpec, ...],
        settings: RenderSettings,
        output_path: Path,
    ) -> None:
        try:
            result = render_composite_frame(self._ffmpeg, base_asset, layers, settings, output_path)
        except FramePreviewError as error:
            self._bridge.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - 后台线程兜底，改由状态栏报告
            self._bridge.failed.emit(f"合成预览失败：{error}")
        else:
            self._bridge.done.emit(str(result))

    def _on_preview_done(self, path: str) -> None:
        self._preview_running = False
        self._preview_thread = None
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._on_preview_failed("合成预览文件无法读取。")
            return
        self._preview_image.setText("")
        self._preview_image.setPixmap(
            pixmap.scaled(
                self._preview_image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._refresh_preview_availability()
        self._set_preview_status("已刷新合成预览。")

    def _on_preview_failed(self, message: str) -> None:
        self._preview_running = False
        self._preview_thread = None
        self._refresh_preview_availability()
        self._set_preview_status(message, warn=True)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._refresh_preview_availability()
        super().showEvent(event)

    def enabled_layers(self) -> list[LayerSpec]:
        return self._store.enabled_layers

    def _sync_canvases(self, *, aspect: bool = False) -> None:
        """把图层与选中状态同步到预览画布（两张），并刷新提示行。

        统一入口：此前各处直接调 ``self._canvas.set_layers(...)``，加第二张画布后
        很容易漏掉其中一处，导致源素材取景白框停留在旧状态。
        """
        selected = self._selected()
        selected_id = selected.id if selected else None
        for canvas in (self._canvas, self._source_crop_preview):
            if canvas is None:
                continue
            if aspect:
                canvas.set_layers(self._layers, aspect=self._aspect)
            else:
                canvas.set_layers(self._layers)
            canvas.set_selected(selected_id)
        self._refresh_preview_effect_hint(selected)

    def _refresh_preview_effect_hint(self, layer: LayerSpec | None) -> None:
        """刷新"视觉参数当前值"提示行（对齐 .NET 的 PreviewVisualEffectHint）。"""
        if not hasattr(self, "_preview_effect_hint"):
            return
        if layer is None:
            self._preview_effect_hint.setText("")
            return
        visible = int(round(max(0.0, min(layer.opacity, 1.0)) * 100))
        if self._is_sticker:
            self._preview_effect_hint.setText(
                f"框内示意：可见度 {visible}%，旋转 {int(round(layer.rotation_degrees))}°。"
            )
            return
        self._preview_effect_hint.setText(
            f"框内示意：上向渐变 {int(round(layer.top_fade * 100))}%，"
            f"羽化 {int(round(layer.feather * 100))}%，透明度 {visible}%；"
            "右侧「合成预览」显示真实渲染效果。"
        )

    def refresh_from_store(self) -> None:
        """外部替换 store 内容（如打开项目）后重建列表与表单。"""
        self._reload(keep_selection=False)
        self._refresh_preview_availability()
