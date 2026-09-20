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
from jingxu.infrastructure.layer_store import LayerStore
from jingxu.infrastructure.sticker_library import StickerLibrary
from jingxu.ui import theme
from jingxu.ui.layer_preview import LayerPreviewCanvas
from jingxu.ui.widgets import Caption, PrimaryButton, SecondaryButton, SectionHeader

# .NET 预设：画中画（右下角）与顶部横幅（截图类场景）。
PIP_PRESET = {"x_percent": 73.0, "y_percent": 73.0, "width_percent": 42.0, "height_percent": 0.0, "fit": "contain"}
SCREENSHOT_PRESET = {"x_percent": 50.0, "y_percent": 24.0, "width_percent": 100.0, "height_percent": 48.0, "fit": "stretch"}

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
        self._library = sticker_library or (StickerLibrary() if self._is_sticker else None)
        self._use_random_library = False
        self._layers: list[LayerSpec] = []
        self._updating = False
        self._aspect = "9:16"
        # 混剪页画幅（供「跟随混剪画幅」模式使用）；与 _aspect 分开保存，
        # 以便用户选择独立画幅后仍能在切回跟随模式时恢复。
        self._composition_aspect = "9:16"
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

        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        self._list = QListWidget()
        self._list.setObjectName("CompositionMaterials")
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.itemChanged.connect(self._on_item_changed)
        # 滚动区里 stretch 不再分配高度，必须给下限，否则列表会被压成一条。
        self._list.setMinimumHeight(240)
        preview_row.addWidget(self._list, stretch=1)

        self._canvas = LayerPreviewCanvas()
        self._canvas.setMinimumHeight(240)
        self._canvas.layer_moved.connect(self._on_layer_moved)
        self._canvas.layer_scaled.connect(self._on_layer_scaled)
        preview_row.addWidget(self._canvas, stretch=1)
        layout.addLayout(preview_row)

        layout.addSpacing(6)
        layout.addWidget(Caption("拖拽预览中的图层可调整位置，滚轮调整宽度。"))

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

        # 合成预览（真实滤镜静帧）是蒙版专属：贴纸页没有该区块，
        # 因此贴纸模式下把按钮置空，其余代码统一以 None 判断跳过。
        if self._is_sticker:
            self._preview_button = None
            self._refresh_library()
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
        """素材库工具条：导入贴纸 / 添加到轨道 / 清空素材库。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        import_button = SecondaryButton("导入贴纸…")
        import_button.setToolTip("把 PNG/GIF/WebP 或视频贴纸导入素材库（不会直接生成轨道）。")
        import_button.clicked.connect(self._import_to_library)
        row.addWidget(import_button)

        self._add_from_library = PrimaryButton("添加到轨道")
        self._add_from_library.setToolTip("用素材库里选中的贴纸生成一条贴纸轨道。")
        self._add_from_library.clicked.connect(self._add_track_from_library)
        self._add_from_library.setEnabled(False)
        row.addWidget(self._add_from_library)

        clear_button = SecondaryButton("清空素材库")
        clear_button.clicked.connect(self._clear_library)
        row.addWidget(clear_button)

        self._library_caption = Caption("")
        row.addWidget(self._library_caption, stretch=1)
        return row

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
        grid.addWidget(Caption("中心 X (%)"), 1, 0)
        grid.addWidget(self._x, 1, 1)
        grid.addWidget(Caption("中心 Y (%)"), 1, 2)
        grid.addWidget(self._y, 1, 3)

        self._width = self._make_percent_spin(30)
        self._height = QSpinBox()
        self._height.setRange(0, 100)
        self._height.setSuffix("%")
        self._height.setSpecialValueText("自然高度")
        grid.addWidget(Caption("宽度 (%)"), 2, 0)
        grid.addWidget(self._width, 2, 1)
        grid.addWidget(Caption("高度 (%)"), 2, 2)
        grid.addWidget(self._height, 2, 3)

        self._opacity = QSpinBox()
        self._opacity.setRange(0, 100)
        self._opacity.setValue(100)
        self._opacity.setSuffix("%")
        self._rotation = QSpinBox()
        self._rotation.setRange(-180, 180)
        self._rotation.setSuffix("°")
        grid.addWidget(Caption("透明度（%）"), 3, 0)
        grid.addWidget(self._opacity, 3, 1)
        grid.addWidget(Caption("旋转（±180°）"), 3, 2)
        grid.addWidget(self._rotation, 3, 3)

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

        self._ratio_hint = Caption("")
        ratio_row.addWidget(self._ratio_hint)
        ratio_row.addStretch(1)
        grid.addLayout(ratio_row, 4, 0, 1, 4)

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
        grid.addLayout(options, 5, 0, 1, 4)

        for spin in (self._start, self._end, self._x, self._y, self._opacity, self._rotation):
            spin.valueChanged.connect(self._on_form_changed)
        self._width.valueChanged.connect(self._on_width_changed)
        self._height.valueChanged.connect(self._on_height_changed)
        self._enabled.stateChanged.connect(self._on_form_changed)

        self._split_position = None
        self._top_fade = None
        self._feather = None
        self._source_crop_y = None
        self._fit = None
        self._remove_black = None
        self._mix_audio = None
        self._source_crop_canvas = None
        self._start_clip = None
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
        self._library_caption.setText(
            f"素材库 {len(entries)} 项" if entries else "素材库为空，点「导入贴纸…」添加"
        )
        self._add_from_library.setEnabled(bool(entries))
        if self._random_library.isChecked() and not entries:
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
        if self._use_random_library and self._library is not None and not self._library.entries:
            self._set_status(
                "已开启随机贴纸库，但素材库为空。请先导入贴纸，否则渲染时不会替换。",
                warn=True,
            )
            return
        self._set_status(
            "已开启随机贴纸库：每次成片会按种子从素材库替换贴纸。"
            if self._use_random_library
            else "已关闭随机贴纸库：轨道使用各自绑定的素材。"
        )

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
        self._opacity.setValue(28)
        self._opacity.setSuffix("%")
        grid.addWidget(Caption("宽度 (%)"), 2, 0)
        grid.addWidget(self._width, 2, 1)
        grid.addWidget(Caption("透明度（0=不透明）"), 2, 2)
        grid.addWidget(self._opacity, 2, 3)

        self._height = QSpinBox()
        self._height.setRange(0, 100)
        self._height.setSuffix("%")
        self._height.setSpecialValueText("自然高度")
        self._split_position = QSpinBox()
        self._split_position.setRange(0, 100)
        self._split_position.setSuffix("%")
        grid.addWidget(Caption("高度上限（0=自然）"), 3, 0)
        grid.addWidget(self._height, 3, 1)
        grid.addWidget(Caption("分割位置"), 3, 2)
        grid.addWidget(self._split_position, 3, 3)

        self._rotation = QSpinBox()
        self._rotation.setRange(-180, 180)
        self._rotation.setSuffix("°")
        grid.addWidget(Caption("旋转 (±180°)"), 4, 0)
        grid.addWidget(self._rotation, 4, 1)
        self._start_clip = QSpinBox()
        self._start_clip.setRange(1, 999)
        self._start_clip.setSuffix(" 起生效")
        grid.addWidget(Caption("起始片段"), 4, 2)
        grid.addWidget(self._start_clip, 4, 3)

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
        fade_row.addWidget(Caption("源上下偏移"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._source_crop_y = QDoubleSpinBox()
        self._source_crop_y.setRange(-1.0, 1.0)
        self._source_crop_y.setSingleStep(0.1)
        self._source_crop_y.setDecimals(2)
        fade_row.addWidget(self._source_crop_y)
        fade_row.addStretch(1)
        grid.addLayout(fade_row, 5, 0, 1, 4)

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
        grid.addLayout(options, 6, 0, 1, 4)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        for label, handler in (
            ("画中画预设", self._apply_pip_preset),
            ("顶部横幅预设", self._apply_screenshot_preset),
            ("统一尺寸到全部层", self._apply_unified_size),
            ("统一起始片段", self._apply_start_clip_to_all),
        ):
            button = SecondaryButton(label)
            button.clicked.connect(handler)
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        grid.addLayout(preset_row, 7, 0, 1, 4)

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

        self._ratio_hint = Caption("")
        ratio_row.addWidget(self._ratio_hint)
        ratio_row.addStretch(1)
        grid.addLayout(ratio_row, 8, 0, 1, 4)

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
        ):
            spin.valueChanged.connect(self._on_form_changed)
        # 宽高走专用处理：锁定比例时需要联动另一个方向。
        self._width.valueChanged.connect(self._on_width_changed)
        self._height.valueChanged.connect(self._on_height_changed)
        self._split_position.valueChanged.connect(self._on_split_changed)
        self._fit.currentIndexChanged.connect(self._on_form_changed)
        self._remove_black.stateChanged.connect(self._on_form_changed)
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
    def _make_percent_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 200)
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

        self._canvas.set_layers(self._layers)
        self._canvas.set_selected(self._selected().id if self._selected() else None)
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
            # 透明度语义（对齐 .NET）：0 = 完全不透明，100 = 完全透明。
            self._opacity.setValue(int(round((1.0 - max(0.0, min(layer.opacity, 1.0))) * 100)))
            self._rotation.setValue(int(round(layer.rotation_degrees)))
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
        self._canvas.set_selected(layer.id if layer else None)

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
        self._canvas.set_layers(self._layers)
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
        self._canvas.set_layers(self._layers)
        self._set_status(f"已把 {layer.display_name} 的尺寸与适配统一到 {len(self._layers) - 1} 个图层。")
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

    def set_canvas_aspect(self, aspect: str) -> None:
        """由壳层同步成片画幅（9:16 / 16:9 / 1:1 / 3:4）。

        在「跟随混剪画幅」模式下沿用同画幅；用户选了独立画幅则保持不动，
        避免混剪页一改设置就把用户的编辑视角拽走（对齐 .NET 的
        ``SyncCompositionCanvas`` 只在 FollowComposition 时刷新尺寸）。
        """
        if aspect in PREVIEW_ASPECT_SIZES:
            self._composition_aspect = aspect
        if self._selected_aspect_mode() is LayerAspectMode.FOLLOW_COMPOSITION:
            self._aspect = self._composition_aspect
        self._canvas.set_layers(self._layers, aspect=self._aspect)
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
        self._canvas.set_layers(self._layers, aspect=self._aspect)
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
            self._canvas.set_layers(self._layers)
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
        self._canvas.set_layers(self._layers)
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
        self._canvas.set_layers(self._layers)
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
            # 透明度语义（对齐 .NET）：0 = 不透明，100 = 完全透明。
            opacity=1.0 - self._opacity.value() / 100.0,
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
            self._canvas.set_layers(self._layers)
            self.layers_changed.emit()

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
        self._canvas.set_layers(self._layers)
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
        width, height = PREVIEW_ASPECT_SIZES.get(self._aspect, PREVIEW_ASPECT_SIZES["9:16"])
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

    def refresh_from_store(self) -> None:
        """外部替换 store 内容（如打开项目）后重建列表与表单。"""
        self._reload(keep_selection=False)
        self._refresh_preview_availability()
