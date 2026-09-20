"""混剪编排页：按 .NET CompositionView 章节顺序组织。"""

from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jingxu.application.composition_service import CompositionDraft
from jingxu.domain.composition import OrderMode, has_duplicate_sequence_indices
from jingxu.domain.effects import (
    DoubleScreenEffectPlan,
    DoubleScreenPlacementMode,
    DoubleScreenSourceMode,
    EffectPlanError,
    FourScreenEffectPlan,
    FourScreenSourceMode,
    MainMaterialBoostMode,
    MainMaterialBoostPlan,
)
from jingxu.domain.media import MediaAsset
from jingxu.domain.render import (
    BgmSource,
    FitMode,
    OutputCanvasPreset,
    OutputFrameRatePreset,
    OutputResolutionPreset,
    OutputVideoSettings,
    OverlayFitMode,
    ProcessingMode,
    QualityPreset,
    RenderSettings,
    TransitionSettings,
    UnifiedAspectPolicy,
    VariationSettings,
    legacy_bgm_percent_to_percent,
    validate_transition,
)
from jingxu.domain.splitscreen import SplitMode, SplitScreenSpec
from jingxu.infrastructure.effect_templates import EffectTemplateStore
from jingxu.infrastructure.paths import default_output_directory
from jingxu.infrastructure.sequence_templates import SequenceTemplateStore
from jingxu.ui.widgets import (
    Caption,
    PrimaryButton,
    SecondaryButton,
    SectionHeader,
    SegmentedControl,
)

QUALITY_OPTIONS = (
    ("无损直拷", "lossless"),
    ("高质量", "high"),
    ("平衡", "balanced"),
    ("小体积", "small"),
    ("快速", "fast"),
)

QUALITY_SETTINGS: dict[str, tuple[int, str, str]] = {
    "lossless": (23, "veryfast", "无损直拷：需无分屏/蒙版/贴纸/字幕/BGM/差异化，且素材画幅与音量一致；不满足时自动回退普通转码。"),
    "high": (20, "medium", "高质量：CRF 20 / medium，画质优先，体积较大。"),
    "balanced": (23, "veryfast", "平衡：CRF 23 / veryfast，画质与速度均衡（推荐）。"),
    "small": (26, "veryfast", "小体积：CRF 26 / veryfast，适合快速分发。"),
    "fast": (28, "ultrafast", "快速：CRF 28 / ultrafast，仅用于预览。"),
}

QUALITY_DEFAULT = "balanced"

# 音量语义版本：模板/项目里 < 2 的音量按旧「百分数即增益」（0..200）解释。
COMPOSITION_VOLUME_SEMANTICS = 2


def _migrate_volume_percent(raw: object, legacy_default: int, is_legacy: bool) -> int:
    """读取模板/项目中的音量百分比；旧版语义先换算为 −100..+100。"""
    if raw in (None, ""):
        return legacy_bgm_percent_to_percent(legacy_default) if is_legacy else 0
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return 0
    if not is_legacy:
        return max(-100, min(value, 100))
    return max(-100, min(legacy_bgm_percent_to_percent(value), 100))

ASPECT_OPTIONS = (
    ("继承首段", "inherit"),
    ("9:16 竖屏", "9:16"),
    ("16:9 横屏", "16:9"),
    ("1:1 方形", "1:1"),
    ("3:4 竖屏", "3:4"),
    ("自定义", "custom"),
)

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
}

RESOLUTION_OPTIONS = (
    # 文案对齐 .NET CompositionView「输出分辨率」。
    # 保留 480P 作为额外档位（.NET 只有三档，多一档不影响既有选择）。
    ("原画（保持当前画幅）", "original"),
    ("1080P", "p1080"),
    ("720P", "p720"),
    ("480P", "p480"),
)

FPS_OPTIONS = (
    # 文案对齐 .NET CompositionView「输出帧率」。
    ("原帧率（跟随首段）", "original"),
    ("24 fps", "24"),
    ("25 fps", "25"),
    ("30 fps", "30"),
    ("50 fps", "50"),
    ("60 fps", "60"),
)

VIDEO_FILTER = "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v *.ts);;所有文件 (*)"
AUDIO_FILTER = "音频文件 (*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.wma);;所有文件 (*)"


def _even(value: float) -> int:
    number = max(2, int(round(value)))
    return number if number % 2 == 0 else number - 1


def _percent_spin(value: float) -> QDoubleSpinBox:
    """100%–110% 的百分比输入框（步进 0.5，对齐 .NET）。"""
    spin = QDoubleSpinBox()
    spin.setRange(100.0, 110.0)
    spin.setSingleStep(0.5)
    spin.setDecimals(1)
    spin.setValue(value)
    spin.setSuffix("%")
    return spin


def _duplicate_indices(assets: list[MediaAsset]) -> set[int]:
    """返回出现次数超过一次的素材序号集合。"""
    counts: dict[int, int] = {}
    for asset in assets:
        if asset.sequence_index is None:
            continue
        counts[asset.sequence_index] = counts.get(asset.sequence_index, 0) + 1
    return {index for index, count in counts.items() if count > 1}


class CompositionPage(QWidget):
    """混剪编排：素材 / 编排 / 预览 / 输出 / 质量 / 处理器 / 兼容性 / 统一比例 / 覆盖 / 模板 / 效果与音频 / 音频库 / BGM。"""

    import_requested = Signal()
    clear_requested = Signal()
    enqueue_requested = Signal()
    workspace_changed = Signal(int)
    overlay_module_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._assets: list[MediaAsset] = []
        self._output_directory: Path | None = None
        self._aux_paths: list[Path] = []
        self._bgm_file: Path | None = None
        self._audio_library: list[Path] = []
        self._template_store = EffectTemplateStore()
        self._sequence_store = SequenceTemplateStore()
        self._updating_template = False
        self._overlay_enabled = True
        self._overlay_count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        layout.addLayout(self._build_header())
        self._status = Caption("")
        self._status.setVisible(False)
        layout.addWidget(self._status)

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("商品工作组"))
        layout.addSpacing(8)
        self._workspace = SegmentedControl((("商品组 A", 0), ("商品组 B", 1)))
        self._workspace.changed.connect(lambda value: self.workspace_changed.emit(int(value)))
        layout.addWidget(self._workspace, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(Caption("两组可分别导入不同商品素材并各自「加入队列」；开启并发后可同时渲染。"))

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("素材"))
        layout.addSpacing(6)
        layout.addWidget(Caption("同一商品组内重复导入会追加素材并可能打乱序号；做下一商品前请先「清理素材」。"))
        layout.addSpacing(8)
        self._material_container = QFrame()
        self._material_container.setObjectName("PanelMuted")
        container_layout = QVBoxLayout(self._material_container)
        container_layout.setContentsMargins(12, 8, 12, 8)
        self._material_list = QListWidget()
        self._material_list.setObjectName("CompositionMaterials")
        self._material_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._material_list.setMaximumHeight(180)
        container_layout.addWidget(self._material_list)
        self._material_empty = Caption(
            "暂无素材。点击「导入素材」选择视频文件，系统将自动探测时长、分辨率并解析文件名序号。"
        )
        self._material_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self._material_empty)
        layout.addWidget(self._material_container)

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("编排"))
        layout.addSpacing(8)
        self._mode = SegmentedControl((("随机批量", OrderMode.RANDOM), ("自定义序号", OrderMode.CUSTOM)))
        self._mode.changed.connect(self._refresh_mode)
        layout.addWidget(self._mode, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(10)
        layout.addWidget(self._build_random_fields())
        layout.addWidget(self._build_custom_fields())
        layout.addSpacing(10)
        layout.addLayout(self._build_transition_row())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("编排预览"))
        layout.addSpacing(8)
        self._preview_list = QListWidget()
        self._preview_list.setObjectName("CompositionMaterials")
        self._preview_list.setMaximumHeight(150)
        layout.addWidget(self._preview_list)
        self._plan_summary = Caption("")
        layout.addWidget(self._plan_summary)

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("输出"))
        layout.addSpacing(8)
        layout.addLayout(self._build_output_row())
        layout.addSpacing(10)
        layout.addLayout(self._build_prefix_row())
        layout.addSpacing(6)
        layout.addWidget(
            Caption(
                "单条成片使用「前缀.mp4」；批量时自动追加 _001、_002 等序号。"
                "默认输出到源目录「分镜输出」（多来源则用桌面）。"
            )
        )

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("输出质量"))
        layout.addSpacing(8)
        self._quality = SegmentedControl(QUALITY_OPTIONS)
        self._quality.set_value(QUALITY_DEFAULT)
        self._quality.changed.connect(lambda _: self._refresh_quality_hint())
        layout.addWidget(self._quality, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(8)
        self._quality_hint = Caption("")
        layout.addWidget(self._quality_hint)

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("处理器"))
        layout.addSpacing(8)
        self._processing = SegmentedControl(
            (
                ("自动（推荐）", ProcessingMode.AUTO),
                ("CPU（兼容稳定）", ProcessingMode.CPU),
                ("GPU（硬件加速）", ProcessingMode.GPU),
            )
        )
        layout.addWidget(self._processing, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(8)
        self._processing_hint = Caption("自动模式会探测 NVENC / QSV / AMF 等硬件编码器，不可用时回退 CPU。")
        layout.addWidget(self._processing_hint)

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("导出兼容性"))
        layout.addSpacing(8)
        layout.addLayout(self._build_export_row())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("统一比例"))
        layout.addSpacing(8)
        layout.addLayout(self._build_aspect_row())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("蒙版覆盖"))
        layout.addSpacing(8)
        overlay_column = QVBoxLayout()
        overlay_column.setSpacing(6)
        self._overlay_enable = QCheckBox("启用蒙版覆盖到成片")
        self._overlay_enable.setChecked(True)
        self._overlay_enable.stateChanged.connect(lambda _: self._refresh_overlay_state())
        overlay_column.addWidget(self._overlay_enable)
        self._overlay_label = Caption("未启用蒙版图层")
        overlay_column.addWidget(self._overlay_label)
        self._overlay_random = QCheckBox("每条成片随机替换 1 个素材库蒙版")
        self._overlay_random.setEnabled(False)
        overlay_column.addWidget(self._overlay_random)
        self._overlay_hint = Caption("蒙版图层在「蒙版」模块编辑；勾选随机替换时按任务种子从蒙版库抽取。")
        overlay_column.addWidget(self._overlay_hint)
        open_overlay = SecondaryButton("打开蒙版模块")
        open_overlay.clicked.connect(self.overlay_module_requested.emit)
        overlay_column.addWidget(open_overlay, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(overlay_column)

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("效果模板"))
        layout.addSpacing(8)
        layout.addLayout(self._build_template_row())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("效果与音频"))
        layout.addSpacing(8)
        layout.addLayout(self._build_variation_block())
        layout.addSpacing(12)
        layout.addLayout(self._build_split_block())
        layout.addSpacing(12)
        layout.addLayout(self._build_main_audio_row())
        layout.addSpacing(12)
        layout.addLayout(self._build_boost_block())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("音频库"))
        layout.addSpacing(8)
        layout.addLayout(self._build_audio_library_block())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("背景音乐（单文件）"))
        layout.addSpacing(8)
        layout.addLayout(self._build_bgm_row())

        layout.addSpacing(16)
        layout.addWidget(SectionHeader("封面"))
        layout.addSpacing(8)
        layout.addLayout(self._build_cover_row())

        layout.addSpacing(18)
        self._enqueue = PrimaryButton("加入队列")
        self._enqueue.setMinimumHeight(36)
        self._enqueue.clicked.connect(self.enqueue_requested.emit)
        layout.addWidget(self._enqueue)
        self._enqueue_hint = Caption("")
        self._enqueue_hint.setObjectName("CaptionWarn")
        self._enqueue_hint.setVisible(False)
        layout.addWidget(self._enqueue_hint)
        layout.addSpacing(12)

        self._refresh_mode()
        self._refresh_quality_hint()
        self._refresh_split_state()
        self._refresh_aspect_state()
        self._refresh_audio_library_state()
        self._refresh_templates()
        self.set_materials([])

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        column = QVBoxLayout()
        column.setSpacing(6)
        title = QLabel("批量混剪")
        title.setObjectName("Title")
        column.addWidget(title)
        self._summary = Caption("当前无法生成预览，请检查素材与编排参数。")
        column.addWidget(self._summary)
        row.addLayout(column, stretch=1)

        clear = SecondaryButton("清理素材")
        clear.clicked.connect(self.clear_requested.emit)
        row.addWidget(clear, alignment=Qt.AlignmentFlag.AlignTop)
        import_button = SecondaryButton("导入素材")
        import_button.clicked.connect(self.import_requested.emit)
        row.addWidget(import_button, alignment=Qt.AlignmentFlag.AlignTop)
        return row

    def _build_random_fields(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self._batch_count = QSpinBox()
        self._batch_count.setRange(1, 50)
        self._batch_count.setValue(1)
        grid.addWidget(Caption("批量数量"), 0, 0)
        grid.addWidget(self._batch_count, 0, 1)

        self._seed = QSpinBox()
        self._seed.setRange(0, 999_999)
        self._seed.setValue(2026)
        grid.addWidget(Caption("随机种子"), 0, 2)
        grid.addWidget(self._seed, 0, 3)

        self._clips_per_plan = QLineEdit()
        self._clips_per_plan.setPlaceholderText("留空=使用全部素材")
        self._clips_per_plan.setFixedWidth(140)
        grid.addWidget(Caption("每片素材数"), 1, 0)
        grid.addWidget(self._clips_per_plan, 1, 1)
        grid.addWidget(Caption("相同种子结果可复现；批量时种子按序号递增。"), 1, 2, 1, 2)
        grid.setColumnStretch(4, 1)

        self._random_widget = widget
        return widget

    def _build_custom_fields(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(Caption("序号表达式（一条成片的片段顺序）"))
        self._sequence = QPlainTextEdit()
        self._sequence.setPlaceholderText("例如 264513 或 2,6,4,5,1,3；多任务用换行或分号分隔")
        self._sequence.setFixedHeight(64)
        layout.addWidget(self._sequence)
        layout.addWidget(Caption("序号必须是 1..N 的不重复排列（不重不漏），对应左侧素材序号；允许重复序号以拉长片段。"))

        template_row = QHBoxLayout()
        template_row.setSpacing(8)
        template_row.addWidget(Caption("序号模板"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._sequence_template = QComboBox()
        self._sequence_template.setMinimumWidth(160)
        template_row.addWidget(self._sequence_template)

        for label, handler in (
            ("刷新", self._refresh_sequence_templates),
            ("应用", self._apply_sequence_template),
            ("保存当前", self._save_sequence_template),
            ("重命名", self._rename_sequence_template),
            ("删除", self._delete_sequence_template),
        ):
            button = SecondaryButton(label)
            button.clicked.connect(handler)
            template_row.addWidget(button)
        template_row.addStretch(1)
        layout.addLayout(template_row)
        layout.addWidget(Caption("把常用序号存成命名模板，后续一键套用；多任务表达式（换行/分号）会生成多条成片。"))

        widget.setVisible(False)
        self._custom_widget = widget
        self._refresh_sequence_templates()
        return widget

    def _build_transition_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._transition_enable = QCheckBox("交叉转场（片段重叠）")
        row.addWidget(self._transition_enable)

        self._transition_seconds = QDoubleSpinBox()
        self._transition_seconds.setRange(0.1, 5.0)
        self._transition_seconds.setSingleStep(0.1)
        self._transition_seconds.setValue(0.5)
        self._transition_seconds.setSuffix(" s")
        self._transition_seconds.setEnabled(False)
        row.addWidget(self._transition_seconds)

        self._transition_enable.stateChanged.connect(self._on_transition_changed)
        self._transition_seconds.valueChanged.connect(self._on_transition_changed)

        row.addWidget(
            Caption("默认硬切；启用后相邻片段重叠，成片时长按重叠量扣减。"),
            stretch=1,
        )
        return row

    def _build_output_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(Caption("输出目录"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("默认：素材目录/分镜输出")
        row.addWidget(self._output_edit, stretch=1)
        browse = SecondaryButton("浏览…")
        browse.clicked.connect(self._pick_output_directory)
        row.addWidget(browse)
        return row

    def _build_prefix_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(Caption("文件名前缀"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._prefix = QLineEdit("混剪")
        self._prefix.setFixedWidth(240)
        row.addWidget(self._prefix)
        row.addStretch(1)
        return row

    def _build_export_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(Caption("输出分辨率"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._resolution = QComboBox()
        for label, value in RESOLUTION_OPTIONS:
            self._resolution.addItem(label, value)
        row.addWidget(self._resolution)

        row.addSpacing(12)
        row.addWidget(Caption("帧率"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._fps = QComboBox()
        for label, value in FPS_OPTIONS:
            self._fps.addItem(label, value)
        self._fps.setCurrentIndex(3)
        row.addWidget(self._fps)

        row.addSpacing(12)
        row.addWidget(Caption("非原画时按短边等比缩放输出画幅（1080P / 720P / 480P）。"), stretch=1)
        return row

    def _build_aspect_row(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)

        self._aspect_enable = QCheckBox("启用统一比例")
        self._aspect_enable.setChecked(True)
        self._aspect_enable.stateChanged.connect(lambda _: self._refresh_aspect_state())
        column.addWidget(self._aspect_enable)

        aspect_row = QHBoxLayout()
        aspect_row.setSpacing(8)
        aspect_row.addWidget(Caption("目标画幅"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._aspect = QComboBox()
        for label, value in ASPECT_OPTIONS:
            self._aspect.addItem(label, value)
        self._aspect.currentIndexChanged.connect(lambda _: self._refresh_aspect_state())
        aspect_row.addWidget(self._aspect)

        self._custom_width = QSpinBox()
        self._custom_width.setRange(64, 7680)
        self._custom_width.setValue(1080)
        self._custom_height = QSpinBox()
        self._custom_height.setRange(64, 7680)
        self._custom_height.setValue(1920)
        self._custom_width.setEnabled(False)
        self._custom_height.setEnabled(False)
        aspect_row.addWidget(self._custom_width)
        aspect_row.addWidget(QLabel("×"))
        aspect_row.addWidget(self._custom_height)
        aspect_row.addStretch(1)
        column.addLayout(aspect_row)

        fit_row = QHBoxLayout()
        fit_row.setSpacing(8)
        fit_row.addWidget(Caption("拼接素材适配"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._fit_mode = SegmentedControl(
            (
                ("居中裁切", FitMode.CROP),
                ("黑边", FitMode.PAD),
                ("拉伸", FitMode.STRETCH),
                ("模糊背景", FitMode.BLUR),
            )
        )
        self._fit_mode.set_value(FitMode.PAD)
        self._fit_mode.changed.connect(lambda _: self._refresh_aspect_state())
        fit_row.addWidget(self._fit_mode)
        fit_row.addStretch(1)
        column.addLayout(fit_row)

        overlay_fit_row = QHBoxLayout()
        overlay_fit_row.setSpacing(8)
        overlay_fit_row.addWidget(Caption("蒙版素材适配"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._overlay_fit_mode = QComboBox()
        for mode in OverlayFitMode:
            self._overlay_fit_mode.addItem(mode.display_text, mode.value)
        self._overlay_fit_mode.setCurrentIndex(
            max(0, self._overlay_fit_mode.findData(OverlayFitMode.FILL_CROP.value))
        )
        overlay_fit_row.addWidget(self._overlay_fit_mode)
        overlay_fit_row.addStretch(1)
        column.addLayout(overlay_fit_row)

        self._aspect_preview = Caption("")
        column.addWidget(self._aspect_preview)
        return column

    def _build_template_row(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._template_name = QLineEdit()
        self._template_name.setPlaceholderText("模板名称")
        self._template_name.setFixedWidth(200)
        top.addWidget(self._template_name)

        save_button = SecondaryButton("保存为模板")
        save_button.clicked.connect(self._save_template)
        top.addWidget(save_button)

        apply_button = SecondaryButton("应用到当前")
        apply_button.clicked.connect(self._apply_template)
        top.addWidget(apply_button)

        rename_button = SecondaryButton("重命名")
        rename_button.clicked.connect(self._rename_template)
        top.addWidget(rename_button)

        delete_button = SecondaryButton("删除")
        delete_button.clicked.connect(self._delete_template)
        top.addWidget(delete_button)
        top.addStretch(1)
        column.addLayout(top)

        self._template_list = QListWidget()
        self._template_list.setObjectName("CompositionMaterials")
        self._template_list.setMaximumHeight(96)
        self._template_list.currentTextChanged.connect(self._on_template_selected)
        column.addWidget(self._template_list)
        column.addWidget(Caption("模板保存画幅、质量、分辨率、差异化、分屏与音频设置，可一键套用到后续批次。"))
        return column

    def _build_variation_block(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Caption("差异化滤镜"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._variation_enable = QCheckBox("启用差异化滤镜")
        self._variation_enable.stateChanged.connect(lambda _: self._refresh_variation_state())
        row.addWidget(self._variation_enable)
        self._variation_mirror = QCheckBox("镜像")
        self._variation_mirror.setChecked(True)
        self._variation_crop = QCheckBox("轻裁切")
        self._variation_crop.setChecked(True)
        self._variation_color = QCheckBox("调色")
        self._variation_color.setChecked(True)
        self._variation_denoise = QCheckBox("降噪")
        self._variation_rotate = QCheckBox("旋转")
        self._variation_rotate.setChecked(True)
        self._variation_rotate.stateChanged.connect(lambda _: self._refresh_variation_state())
        for box in (
            self._variation_mirror,
            self._variation_crop,
            self._variation_color,
            self._variation_denoise,
            self._variation_rotate,
        ):
            row.addWidget(box)
        row.addStretch(1)
        column.addLayout(row)

        intensity_row = QHBoxLayout()
        intensity_row.setSpacing(8)
        intensity_row.addWidget(Caption("差异化强度"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._variation_intensity = QSpinBox()
        self._variation_intensity.setRange(1, 200)
        self._variation_intensity.setValue(100)
        self._variation_intensity.setSuffix("%")
        intensity_row.addWidget(self._variation_intensity)
        intensity_row.addWidget(Caption("最大角度"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._variation_rotation_max = QDoubleSpinBox()
        self._variation_rotation_max.setRange(0.0, 15.0)
        self._variation_rotation_max.setSingleStep(0.5)
        self._variation_rotation_max.setValue(15.0)
        self._variation_rotation_max.setSuffix("°")
        intensity_row.addWidget(self._variation_rotation_max)
        self._variation_hint = Caption("镜像、轻裁切、调色、降噪、旋转按种子随机组合，批量成片互不相同且可复现。")
        intensity_row.addWidget(self._variation_hint, stretch=1)
        column.addLayout(intensity_row)
        self._refresh_variation_state()
        return column

    def _build_split_block(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)

        self._double_enable = QCheckBox("双屏（左右 2 格）")
        self._double_enable.stateChanged.connect(lambda _: self._on_split_toggled(SplitMode.DOUBLE_H))
        self._double_v_enable = QCheckBox("双屏（上下 2 格）")
        self._double_v_enable.stateChanged.connect(lambda _: self._on_split_toggled(SplitMode.DOUBLE_V))
        self._four_enable = QCheckBox("四屏（2×2）")
        self._four_enable.stateChanged.connect(lambda _: self._on_split_toggled(SplitMode.FOUR))
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(self._double_enable)
        head.addWidget(self._double_v_enable)
        head.addWidget(self._four_enable)
        head.addWidget(Caption("左右双屏、上下双屏与四屏只能选一项。"), stretch=1)
        column.addLayout(head)

        start_row = QHBoxLayout()
        start_row.setSpacing(8)
        start_row.addWidget(Caption("从第"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._split_start = QSpinBox()
        self._split_start.setRange(1, 999)
        self._split_start.setSuffix(" 个视频开始至结尾")
        start_row.addWidget(self._split_start)
        start_row.addWidget(Caption("四屏从第"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._four_start = QSpinBox()
        self._four_start.setRange(1, 999)
        self._four_start.setSuffix(" 个视频开始")
        start_row.addWidget(self._four_start)
        self._split_random = QCheckBox("随机抽取主素材所在文件夹")
        start_row.addWidget(self._split_random)
        start_row.addStretch(1)
        column.addLayout(start_row)

        feather_row = QHBoxLayout()
        feather_row.setSpacing(8)
        self._split_feather = QCheckBox("横竖缝羽化")
        self._split_feather.setChecked(True)
        self._split_feather.stateChanged.connect(lambda _: self._refresh_split_state())
        feather_row.addWidget(self._split_feather)
        feather_row.addWidget(Caption("羽化强度"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._split_feather_px = QSpinBox()
        self._split_feather_px.setRange(0, 256)
        self._split_feather_px.setSingleStep(8)
        self._split_feather_px.setValue(48)
        self._split_feather_px.setSuffix(" px")
        self._split_feather_px.valueChanged.connect(lambda _: self._refresh_split_state())
        feather_row.addWidget(self._split_feather_px)
        self._split_feather_label = Caption("")
        feather_row.addWidget(self._split_feather_label)
        feather_row.addStretch(1)
        column.addLayout(feather_row)

        self._split_hint = Caption(
            "普通分屏同源同步；随机分屏保留一个主格，其余格从主素材所在文件夹抽取，素材不足时允许重复。"
            "上下双屏与四屏使用确定性随机袋，同一种子结果可复现。"
        )
        column.addWidget(self._split_hint)
        self._refresh_split_state()
        return column

    def _build_main_audio_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(Caption("原声音量"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._main_volume = QSpinBox()
        self._main_volume.setRange(0, 200)
        self._main_volume.setValue(100)
        self._main_volume.setSuffix("%")
        row.addWidget(self._main_volume)
        row.addWidget(Caption("仅调整素材原声；背景音乐音量在下方单独设置。"), stretch=1)
        return row

    def _build_boost_block(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        column.addWidget(Caption("拼接主素材增强（100%–110%）：只作用于主轨拼接，蒙版/贴纸/BGM 不受影响。"))

        self._boost_volume_enable = QCheckBox("音量调大")
        self._boost_volume_enable.stateChanged.connect(lambda _: self._refresh_boost_state())
        self._boost_volume_mode = SegmentedControl((("固定", MainMaterialBoostMode.FIXED), ("随机区间", MainMaterialBoostMode.RANDOM)))
        self._boost_volume_mode.changed.connect(lambda _: self._refresh_boost_state())
        self._boost_volume_fixed = _percent_spin(105.0)
        self._boost_volume_min = _percent_spin(100.0)
        self._boost_volume_max = _percent_spin(110.0)
        volume_row = QHBoxLayout()
        volume_row.setSpacing(8)
        volume_row.addWidget(self._boost_volume_enable)
        volume_row.addWidget(self._boost_volume_mode)
        volume_row.addWidget(self._boost_volume_fixed)
        volume_row.addWidget(Caption("区间"))
        volume_row.addWidget(self._boost_volume_min)
        volume_row.addWidget(QLabel("–"))
        volume_row.addWidget(self._boost_volume_max)
        volume_row.addWidget(Caption("启用音量时先做 loudnorm 统一响度再放大。"))
        volume_row.addStretch(1)
        column.addLayout(volume_row)

        self._boost_scale_enable = QCheckBox("画面缩放")
        self._boost_scale_enable.stateChanged.connect(lambda _: self._refresh_boost_state())
        self._boost_scale_mode = SegmentedControl((("固定", MainMaterialBoostMode.FIXED), ("随机区间", MainMaterialBoostMode.RANDOM)))
        self._boost_scale_mode.changed.connect(lambda _: self._refresh_boost_state())
        self._boost_scale_fixed = _percent_spin(105.0)
        self._boost_scale_min = _percent_spin(100.0)
        self._boost_scale_max = _percent_spin(110.0)
        scale_row = QHBoxLayout()
        scale_row.setSpacing(8)
        scale_row.addWidget(self._boost_scale_enable)
        scale_row.addWidget(self._boost_scale_mode)
        scale_row.addWidget(self._boost_scale_fixed)
        scale_row.addWidget(Caption("区间"))
        scale_row.addWidget(self._boost_scale_min)
        scale_row.addWidget(QLabel("–"))
        scale_row.addWidget(self._boost_scale_max)
        scale_row.addWidget(Caption("先缩小再居中裁切回画幅，等效轻微放大更稳。"))
        scale_row.addStretch(1)
        column.addLayout(scale_row)

        self._boost_hint = Caption("")
        column.addWidget(self._boost_hint)
        self._refresh_boost_state()
        return column

    def _build_audio_library_block(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        self._library_enable = QCheckBox("启用音频库随机抽取")
        self._library_enable.stateChanged.connect(lambda _: self._refresh_audio_library_state())
        head.addWidget(self._library_enable)
        self._library_label = Caption("音频库为空（可在「音频」模块导入）")
        head.addWidget(self._library_label, stretch=1)
        column.addLayout(head)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        # 对齐 .NET：固定音量与随机区间可同时勾选，随机优先。
        self._library_fixed_enable = QCheckBox("自定义固定音量")
        self._library_fixed_enable.setChecked(True)
        self._library_fixed_enable.stateChanged.connect(lambda _: self._refresh_audio_library_state())
        mode_row.addWidget(self._library_fixed_enable)

        self._library_volume = QSpinBox()
        self._library_volume.setRange(-100, 100)
        self._library_volume.setValue(0)
        self._library_volume.setSuffix("%")
        self._library_volume.setToolTip("0% = 默认背景音乐音量；负值更轻，−100% 静音，+100% 最大。")
        mode_row.addWidget(self._library_volume)

        self._library_random_enable = QCheckBox("随机音量区间（优先）")
        self._library_random_enable.stateChanged.connect(lambda _: self._refresh_audio_library_state())
        mode_row.addWidget(self._library_random_enable)

        self._library_min = QSpinBox()
        self._library_min.setRange(-100, 100)
        self._library_min.setValue(-10)
        self._library_min.setSuffix("%")
        self._library_max = QSpinBox()
        self._library_max.setRange(-100, 100)
        self._library_max.setValue(10)
        self._library_max.setSuffix("%")
        mode_row.addWidget(Caption("最小值"), alignment=Qt.AlignmentFlag.AlignVCenter)
        mode_row.addWidget(self._library_min)
        mode_row.addWidget(Caption("最大值"), alignment=Qt.AlignmentFlag.AlignVCenter)
        mode_row.addWidget(self._library_max)
        mode_row.addStretch(1)
        column.addLayout(mode_row)

        self._library_hint = Caption("启用后每个渲染任务从音频库随机抽取一条背景音乐，时长不够自动循环、超出自动裁剪。")
        column.addWidget(self._library_hint)
        return column

    def _build_bgm_row(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)

        self._bgm_enable = QCheckBox("混入背景音乐（单文件优先于音频库随机抽取）")
        self._bgm_enable.stateChanged.connect(lambda _: self._refresh_bgm_state())
        column.addWidget(self._bgm_enable)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._bgm_edit = QLineEdit()
        self._bgm_edit.setPlaceholderText("选择单个背景音乐文件（与音频库随机抽取互不影响，单文件优先）")
        self._bgm_edit.setReadOnly(True)
        row.addWidget(self._bgm_edit, stretch=1)

        pick = SecondaryButton("选择…")
        pick.clicked.connect(self._pick_bgm)
        row.addWidget(pick)

        clear = SecondaryButton("清除")
        clear.clicked.connect(self._clear_bgm)
        row.addWidget(clear)

        row.addWidget(Caption("音量"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._bgm_volume = QSpinBox()
        self._bgm_volume.setRange(-100, 100)
        self._bgm_volume.setValue(0)
        self._bgm_volume.setSuffix("%")
        self._bgm_volume.setToolTip("0% = 默认背景音乐音量；负值更轻，−100% 静音，+100% 最大。")
        row.addWidget(self._bgm_volume)

        row.addWidget(Caption("淡出"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._bgm_fade = QDoubleSpinBox()
        self._bgm_fade.setRange(0.0, 20.0)
        self._bgm_fade.setValue(1.0)
        self._bgm_fade.setSuffix(" s")
        row.addWidget(self._bgm_fade)

        self._bgm_loop = QCheckBox("循环补足")
        self._bgm_loop.setChecked(True)
        row.addWidget(self._bgm_loop)
        row.addStretch(1)
        column.addLayout(row)

        self._bgm_hint = Caption("音量 0% = 默认背景音乐音量（负值更轻、−100% 静音、+100% 最大）；片尾淡出 1 秒、自动循环补足。")
        column.addWidget(self._bgm_hint)
        self._refresh_bgm_state()
        return column

    def _refresh_bgm_state(self) -> None:
        enabled = self._bgm_enable.isChecked()
        for widget in (self._bgm_edit, self._bgm_volume, self._bgm_fade, self._bgm_loop):
            widget.setEnabled(enabled)
        self._bgm_hint.setEnabled(True)

    def _build_cover_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._cover_enable = QCheckBox("导出封面图（从成片取帧，输出同目录同名 .jpg）")
        row.addWidget(self._cover_enable)
        row.addSpacing(12)
        row.addWidget(Caption("取帧时间"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._cover_time = QDoubleSpinBox()
        self._cover_time.setRange(0.0, 600.0)
        self._cover_time.setSingleStep(0.5)
        self._cover_time.setValue(1.0)
        self._cover_time.setSuffix(" s")
        self._cover_time.setEnabled(False)
        self._cover_enable.stateChanged.connect(lambda _: self._cover_time.setEnabled(self._cover_enable.isChecked()))
        row.addWidget(self._cover_time)
        row.addStretch(1)
        return row

    # ────────────────────────────── 素材 ──────────────────────────────

    def set_materials(self, assets: list[MediaAsset]) -> None:
        self._assets = list(assets)
        self._material_list.clear()
        duplicates = _duplicate_indices(self._assets)
        for index, asset in enumerate(self._assets, start=1):
            sequence_text = f"序号 {asset.sequence_index}" if asset.sequence_index is not None else "无序号"
            if asset.sequence_index is not None and asset.sequence_index in duplicates:
                sequence_text += "（重复，自定义序号前需处理）"
            item = QListWidgetItem(
                f"{index:02d}    {asset.display_name}    {sequence_text}    "
                f"{asset.duration_text}    {asset.resolution_text}"
            )
            item.setToolTip(str(asset.path))
            self._material_list.addItem(item)

        self._material_list.setVisible(bool(self._assets))
        self._material_empty.setVisible(not self._assets)

        if self._assets:
            total = sum(asset.duration for asset in self._assets)
            minutes, seconds = divmod(int(round(total)), 60)
            duplicate_hint = " · 存在重复序号" if duplicates else ""
            self._summary.setText(
                f"共 {len(self._assets)} 个素材 · 总时长 {minutes:02d}:{seconds:02d}{duplicate_hint}"
            )
        else:
            self._summary.setText("当前无法生成预览，请检查素材与编排参数。")

        if self._output_directory is None and self._assets:
            self._output_directory = default_output_directory(self._assets)
            self._output_edit.setText(str(self._output_directory))

        self._refresh_aspect_state()
        self._refresh_preview()

    def set_audio_library(self, tracks: list[Path]) -> None:
        self._audio_library = [Path(track) for track in tracks if Path(track).is_file()]
        self._refresh_audio_library_state()

    def set_overlay_summary(self, enabled: int) -> None:
        self._overlay_count = int(enabled)
        self._refresh_overlay_state()

    def overlay_included(self) -> bool:
        """成片是否包含蒙版图层（受「启用蒙版覆盖到成片」控制）。"""
        return self._overlay_enable.isChecked()

    def overlay_random_replace(self) -> bool:
        """是否在每条成片随机替换 1 个素材库蒙版。"""
        return self._overlay_enable.isChecked() and self._overlay_random.isChecked()

    def set_processing_note(self, text: str) -> None:
        self._processing_hint.setText(text)

    def set_status(self, text: str, *, warn: bool = False) -> None:
        self._status.setObjectName("CaptionWarn" if warn else "Caption")
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def selected_material_index(self) -> int:
        return self._material_list.currentRow()

    def select_material(self, index: int) -> None:
        if 0 <= index < self._material_list.count():
            self._material_list.setCurrentRow(index)

    def output_directory(self) -> Path:
        text = self._output_edit.text().strip()
        if text:
            return Path(text).expanduser()
        if self._output_directory is not None:
            return self._output_directory
        self._output_directory = default_output_directory(self._assets)
        self._output_edit.setText(str(self._output_directory))
        return self._output_directory

    def canvas_size(self) -> tuple[int, int]:
        """当前成片画幅（供取景井/预览等复用）。"""
        return self._canvas_size()

    # ────────────────────────────── 草稿 ──────────────────────────────

    def _canvas_size(self) -> tuple[int, int]:
        if not self._aspect_enable.isChecked():
            if self._assets:
                first = self._assets[0]
                return _even(first.width or 1080), _even(first.height or 1920)
            return 1080, 1920
        aspect = str(self._aspect.currentData())
        if aspect == "custom":
            return _even(self._custom_width.value()), _even(self._custom_height.value())
        if aspect == "inherit" and self._assets:
            first = self._assets[0]
            return _even(first.width or 1080), _even(first.height or 1920)
        width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["9:16"])
        return width, height

    def _variation_settings(self) -> VariationSettings | None:
        if not self._variation_enable.isChecked():
            return None
        return VariationSettings(
            mirror=self._variation_mirror.isChecked(),
            light_crop=self._variation_crop.isChecked(),
            color=self._variation_color.isChecked(),
            denoise=self._variation_denoise.isChecked(),
            rotate=self._variation_rotate.isChecked(),
            rotation_max_degrees=float(self._variation_rotation_max.value()),
            intensity=int(self._variation_intensity.value()),
        )

    def _split_spec(self) -> SplitScreenSpec | None:
        """左右双屏沿用视觉分屏计划；上下双屏与四屏在草稿里用领域效果计划。"""
        if not self._double_enable.isChecked():
            return None

        same_source = not self._split_random.isChecked()
        aux: tuple[Path, ...] = ()
        if not same_source:
            aux = tuple(self._sample_auxiliary(SplitMode.DOUBLE_H))
            if not aux:
                same_source = True

        return SplitScreenSpec(
            mode=SplitMode.DOUBLE_H,
            same_source=same_source,
            aux_paths=aux,
            start_index=max(0, int(self._split_start.value()) - 1),
            feather=self._split_feather.isChecked(),
            feather_px=int(self._split_feather_px.value()),
        )

    def _double_screen_plan(self) -> DoubleScreenEffectPlan | None:
        if not self._double_v_enable.isChecked():
            return None
        return DoubleScreenEffectPlan(
            start_clip_index=max(1, int(self._split_start.value())),
            source_mode=(
                DoubleScreenSourceMode.RANDOM_CURRENT_FOLDER
                if self._split_random.isChecked()
                else DoubleScreenSourceMode.CURRENT_CLIP
            ),
            placement_mode=DoubleScreenPlacementMode.RANDOM,
            feather_enabled=self._split_feather.isChecked(),
            feather_pixels=int(self._split_feather_px.value()),
        )

    def _four_screen_plan(self) -> FourScreenEffectPlan | None:
        if not self._four_enable.isChecked():
            return None
        return FourScreenEffectPlan(
            start_clip_index=max(1, int(self._four_start.value())),
            source_mode=(
                FourScreenSourceMode.RANDOM_CURRENT_FOLDER
                if self._split_random.isChecked()
                else FourScreenSourceMode.CURRENT_CLIP
            ),
            feather_enabled=self._split_feather.isChecked(),
            feather_pixels=int(self._split_feather_px.value()),
        )

    def _sample_auxiliary(self, mode: SplitMode) -> list[Path]:
        """从主素材所在文件夹随机抽取其余格素材（可复现）。"""
        if not self._assets:
            return []
        source_directory = self._assets[0].path.parent
        known = {asset.path for asset in self._assets}
        candidates = [
            path
            for path in sorted(source_directory.glob("*"))
            if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv"}
            and path not in known
        ]
        needed = max(1, mode.cell_count - 1)
        if not candidates:
            return []
        generator = random.Random(int(self._seed.value()) * 17 + 3)
        if len(candidates) >= needed:
            return generator.sample(candidates, needed)
        return [generator.choice(candidates) for _ in range(needed)]

    def _bgm_source(self) -> BgmSource | None:
        # 音频库与单文件 BGM 是两个独立开关（对齐 .NET）；音频库优先抽取。
        if self._library_enable.isChecked() and self._audio_library:
            # 随机优先（对齐 .NET）：同时勾选固定与随机时使用随机区间。
            random_mode = self._library_random_enable.isChecked()
            fixed_mode = self._library_fixed_enable.isChecked()
            return BgmSource(
                kind="library",
                volume_mode="random" if random_mode else "fixed",
                volume_percent=int(self._library_volume.value() if fixed_mode else 0),
                volume_min=int(self._library_min.value()),
                volume_max=int(self._library_max.value()),
                fade_out_seconds=float(self._bgm_fade.value()),
                loop=self._bgm_loop.isChecked(),
            )
        if not self._bgm_enable.isChecked():
            return None
        if self._bgm_file is not None and self._bgm_file.is_file():
            return BgmSource(
                kind="file",
                path=self._bgm_file,
                volume_mode="fixed",
                volume_percent=int(self._bgm_volume.value()),
                fade_out_seconds=float(self._bgm_fade.value()),
                loop=self._bgm_loop.isChecked(),
            )
        return None

    def draft(self) -> CompositionDraft:
        """从界面读取草稿；输入不合法时抛出 ``ValueError``。"""
        crf, preset, _ = QUALITY_SETTINGS.get(str(self._quality.value()), QUALITY_SETTINGS[QUALITY_DEFAULT])
        width, height = self._canvas_size()

        clips_text = self._clips_per_plan.text().strip()
        clips: int | None = None
        if clips_text:
            if not clips_text.isdigit() or int(clips_text) < 1:
                raise ValueError("「每片素材数」必须是正整数，或留空使用全部素材。")
            clips = int(clips_text)

        resolution = str(self._resolution.currentData() or "original")
        frame_rate = str(self._fps.currentData() or "original")
        first_fps = float(self._assets[0].fps) if self._assets and self._assets[0].fps > 0 else 30.0
        output_video = OutputVideoSettings(
            resolution=OutputResolutionPreset(resolution),
            frame_rate=OutputFrameRatePreset(frame_rate),
        )
        resolved_fps = output_video.resolve_frame_rate(first_fps)

        return CompositionDraft(
            mode=self._mode.value(),
            seed=int(self._seed.value()),
            sequence_text=self._sequence.toPlainText().strip(),
            settings=RenderSettings(
                width=width,
                height=height,
                fps=resolved_fps,
                crf=crf,
                preset=preset,
                processing=self._processing.value(),
                fit_mode=self._fit_mode.value(),
                output_video=output_video,
                quality=QualityPreset(str(self._quality.value())),
                main_volume_percent=int(self._main_volume.value()),
                variation=self._variation_settings(),
                stream_copy=(str(self._quality.value()) == "lossless"),
                boost=self._boost_plan(),
                transition=(
                    TransitionSettings(
                        enabled=True,
                        duration_seconds=float(self._transition_seconds.value()),
                    )
                    if self._transition_enable.isChecked()
                    else None
                ),
            ),
            output_prefix=self._prefix.text().strip() or "混剪",
            batch_count=int(self._batch_count.value()),
            clips_per_plan=clips,
            bgm_source=self._bgm_source(),
            bgm_tracks=tuple(self._audio_library),
            cover_enabled=self._cover_enable.isChecked(),
            cover_at_seconds=float(self._cover_time.value()),
            split=self._split_spec(),
            double_screen=self._double_screen_plan(),
            four_screen=self._four_screen_plan(),
        )

    # ────────────────────────────── 项目 ──────────────────────────────

    def project_state(self) -> dict:
        """混剪页的可序列化状态（项目文档 导出设置 + 模板引用）。"""
        return {
            "composition": self._template_payload(),
            "output_directory": str(self.output_directory()),
        }

    def apply_project_state(self, state: dict) -> None:
        """用项目文档中的混剪状态覆盖界面（缺字段沿用默认）。"""
        output_directory = str(state.get("output_directory") or "").strip()
        if output_directory:
            self._output_edit.setText(output_directory)
            self._output_directory = Path(output_directory)
        payload = state.get("composition")
        if isinstance(payload, dict):
            self._apply_template_payload(payload)

    # ────────────────────────────── 刷新 ──────────────────────────────

    def _refresh_mode(self, *_: object) -> None:
        is_random = self._mode.value() is OrderMode.RANDOM
        self._random_widget.setVisible(is_random)
        self._custom_widget.setVisible(not is_random)

    def _on_transition_changed(self, *_: object) -> None:
        """转场开关/时长变更：联动可用性并实时刷新预览时长。"""
        self._transition_seconds.setEnabled(self._transition_enable.isChecked())
        if not self._updating_template:
            self._refresh_preview()

    def _refresh_quality_hint(self) -> None:
        _, _, hint = QUALITY_SETTINGS.get(str(self._quality.value()), QUALITY_SETTINGS[QUALITY_DEFAULT])
        self._quality_hint.setText(hint)

    def _refresh_variation_state(self, *_: object) -> None:
        enabled = self._variation_enable.isChecked()
        for box in (
            self._variation_mirror,
            self._variation_crop,
            self._variation_color,
            self._variation_denoise,
            self._variation_rotate,
        ):
            box.setEnabled(enabled)
        self._variation_intensity.setEnabled(enabled)
        self._variation_rotation_max.setEnabled(enabled and self._variation_rotate.isChecked())
        self._variation_hint.setEnabled(True)

    def _refresh_split_state(self, *_: object) -> None:
        active = (
            self._double_enable.isChecked()
            or self._double_v_enable.isChecked()
            or self._four_enable.isChecked()
        )
        for widget in (self._split_start, self._split_random, self._split_feather):
            widget.setEnabled(active)
        self._four_start.setEnabled(self._four_enable.isChecked())
        self._split_feather_px.setEnabled(active and self._split_feather.isChecked())
        if active and self._split_feather.isChecked():
            self._split_feather_label.setText(f"{int(self._split_feather_px.value())} 像素")
        else:
            self._split_feather_label.setText("关闭")

    def _refresh_boost_state(self, *_: object) -> None:
        volume_enabled = self._boost_volume_enable.isChecked()
        scale_enabled = self._boost_scale_enable.isChecked()
        volume_random = self._boost_volume_mode.value() is MainMaterialBoostMode.RANDOM
        scale_random = self._boost_scale_mode.value() is MainMaterialBoostMode.RANDOM

        for widget in (self._boost_volume_mode, self._boost_volume_fixed, self._boost_volume_min, self._boost_volume_max):
            widget.setEnabled(volume_enabled)
        self._boost_volume_fixed.setVisible(not volume_random)
        self._boost_volume_min.setVisible(volume_random)
        self._boost_volume_max.setVisible(volume_random)

        for widget in (self._boost_scale_mode, self._boost_scale_fixed, self._boost_scale_min, self._boost_scale_max):
            widget.setEnabled(scale_enabled)
        self._boost_scale_fixed.setVisible(not scale_random)
        self._boost_scale_min.setVisible(scale_random)
        self._boost_scale_max.setVisible(scale_random)

        if not volume_enabled and not scale_enabled:
            self._boost_hint.setText("未启用主素材增强。")
            return
        parts: list[str] = []
        if volume_enabled:
            if volume_random:
                if self._boost_volume_min.value() > self._boost_volume_max.value():
                    parts.append("音量随机下限不能大于上限")
                else:
                    parts.append(f"音量 {self._boost_volume_min.value():g}%–{self._boost_volume_max.value():g}% 随机")
            else:
                parts.append(f"音量 {self._boost_volume_fixed.value():g}%")
        if scale_enabled:
            if scale_random:
                if self._boost_scale_min.value() > self._boost_scale_max.value():
                    parts.append("缩放随机下限不能大于上限")
                else:
                    parts.append(f"缩放 {self._boost_scale_min.value():g}%–{self._boost_scale_max.value():g}% 随机")
            else:
                parts.append(f"缩放 {self._boost_scale_fixed.value():g}%")
        self._boost_hint.setText(" · ".join(parts) + "（须在 100%–110% 范围内）")

    def _refresh_overlay_state(self, *_: object) -> None:
        enabled = self._overlay_enable.isChecked()
        self._overlay_random.setEnabled(enabled and self._overlay_count > 0)
        if not enabled:
            self._overlay_label.setText("已关闭 · 成片不含蒙版")
            return
        if self._overlay_count:
            self._overlay_label.setText(f"已启用 {self._overlay_count} 图层（在「蒙版」模块编辑参数）。")
        else:
            self._overlay_label.setText("未启用蒙版图层。")

    def _on_split_toggled(self, mode: SplitMode) -> None:
        """三个分屏复选框互斥；用显式 mode 参数而非 sender()（lambda 连接会丢失 sender）。"""
        boxes = {
            SplitMode.DOUBLE_H: self._double_enable,
            SplitMode.DOUBLE_V: self._double_v_enable,
            SplitMode.FOUR: self._four_enable,
        }
        active = boxes[mode]
        if active.isChecked():
            for other_mode, box in boxes.items():
                if other_mode is not mode and box.isChecked():
                    box.setChecked(False)
        self._refresh_split_state()

    def _refresh_aspect_state(self) -> None:
        """统一比例开关、画幅与描述联动（3:4 时蒙版推荐先裁成画幅再覆盖）。"""
        enabled = self._aspect_enable.isChecked()
        custom = self._aspect.currentData() == "custom"
        self._aspect.setEnabled(enabled)
        self._custom_width.setEnabled(enabled and custom)
        self._custom_height.setEnabled(enabled and custom)
        self._fit_mode.setEnabled(enabled)
        self._overlay_fit_mode.setEnabled(enabled)

        if enabled and self._aspect.currentData() == "3:4":
            recommended = UnifiedAspectPolicy.recommended_overlay_fit(OutputCanvasPreset.PORTRAIT_3X4)
            index = self._overlay_fit_mode.findData(recommended.value)
            if index >= 0:
                self._overlay_fit_mode.setCurrentIndex(index)

        policy = self._aspect_policy()
        first_width = self._assets[0].width if self._assets else None
        first_height = self._assets[0].height if self._assets else None
        self._aspect_preview.setText(policy.build_preview_description(first_width, first_height))

    def _aspect_policy(self) -> UnifiedAspectPolicy:
        preset_map = {
            "inherit": OutputCanvasPreset.INHERIT_FIRST,
            "9:16": OutputCanvasPreset.VERTICAL_9X16,
            "16:9": OutputCanvasPreset.HORIZONTAL_16X9,
            "1:1": OutputCanvasPreset.SQUARE_1X1,
            "3:4": OutputCanvasPreset.PORTRAIT_3X4,
            "custom": OutputCanvasPreset.CUSTOM,
        }
        preset = preset_map.get(str(self._aspect.currentData()), OutputCanvasPreset.VERTICAL_9X16)
        overlay_fit = self._overlay_fit_mode.currentData()
        return UnifiedAspectPolicy(
            is_enabled=self._aspect_enable.isChecked(),
            preset=preset,
            custom_width=int(self._custom_width.value()),
            custom_height=int(self._custom_height.value()),
            clip_fit_mode=self._fit_mode.value(),
            overlay_fit_mode=OverlayFitMode(overlay_fit) if overlay_fit else OverlayFitMode.FILL_CROP,
        )

    def _boost_plan(self) -> MainMaterialBoostPlan | None:
        volume_enabled = self._boost_volume_enable.isChecked()
        scale_enabled = self._boost_scale_enable.isChecked()
        if not volume_enabled and not scale_enabled:
            return None

        volume_mode = self._boost_volume_mode.value()
        scale_mode = self._boost_scale_mode.value()
        volume_fixed = float(self._boost_volume_fixed.value())
        scale_fixed = float(self._boost_scale_fixed.value())
        try:
            return MainMaterialBoostPlan(
                enable_volume=volume_enabled,
                volume_mode=volume_mode,
                volume_min_percent=volume_fixed if volume_mode is MainMaterialBoostMode.FIXED else float(self._boost_volume_min.value()),
                volume_max_percent=volume_fixed if volume_mode is MainMaterialBoostMode.FIXED else float(self._boost_volume_max.value()),
                enable_scale=scale_enabled,
                scale_mode=scale_mode,
                scale_min_percent=scale_fixed if scale_mode is MainMaterialBoostMode.FIXED else float(self._boost_scale_min.value()),
                scale_max_percent=scale_fixed if scale_mode is MainMaterialBoostMode.FIXED else float(self._boost_scale_max.value()),
            )
        except EffectPlanError as error:
            raise ValueError(str(error)) from error

    def _refresh_audio_library_state(self) -> None:
        has_tracks = bool(self._audio_library)
        self._library_enable.setEnabled(has_tracks)
        if not has_tracks:
            self._library_enable.setChecked(False)
        self._library_label.setText(
            f"音频库：{len(self._audio_library)} 条可用" if has_tracks else "音频库为空（可在「音频」模块导入）"
        )

        enabled = has_tracks and self._library_enable.isChecked()
        fixed_mode = self._library_fixed_enable.isChecked()
        random_mode = self._library_random_enable.isChecked()

        # 随机优先（对齐 .NET）：两者同时勾选时使用随机区间。
        self._library_fixed_enable.setEnabled(enabled)
        self._library_volume.setEnabled(enabled and fixed_mode)
        self._library_random_enable.setEnabled(enabled)
        self._library_min.setEnabled(enabled and random_mode)
        self._library_max.setEnabled(enabled and random_mode)

        if not enabled:
            self._library_hint.setText("未启用音频库随机抽取。")
        elif random_mode:
            low, high = sorted((self._library_min.value(), self._library_max.value()))
            self._library_hint.setText(f"当前使用随机音量区间 {low}%–{high}%（随机优先于固定音量）。")
        elif fixed_mode:
            self._library_hint.setText(f"当前使用固定音量 {self._library_volume.value()}%。")
        else:
            self._library_hint.setText("未勾选任何音量模式，将使用默认音量 18%。")

    def _refresh_preview(self) -> None:
        self._preview_list.clear()
        self._plan_summary.setText("")
        if not self._assets:
            self._preview_list.addItem(QListWidgetItem("暂无素材，导入后显示编排预览。"))
            self._set_enqueue_state(False, "请先导入至少一个视频素材。")
            return
        try:
            draft = self.draft()
        except ValueError as error:
            self._preview_list.addItem(QListWidgetItem(str(error)))
            self._set_enqueue_state(False, str(error))
            return

        from jingxu.application.composition_service import build_plan

        try:
            plan = build_plan(self._assets, draft)
        except ValueError as error:
            self._preview_list.addItem(QListWidgetItem(str(error)))
            self._set_enqueue_state(False, str(error))
            return

        for index, asset in enumerate(plan.assets, start=1):
            self._preview_list.addItem(
                QListWidgetItem(
                    f"{index:02d}    {asset.display_name}    {asset.duration_text}    {asset.resolution_text}"
                )
            )

        transition = draft.settings.transition
        transition_error = validate_transition(plan, transition)
        if transition_error is not None:
            self._plan_summary.setText(transition_error)
            self._set_enqueue_state(False, transition_error)
            return

        total = plan.total_duration
        if transition is not None and transition.enabled and len(plan.assets) > 1:
            total = max(0.0, total - transition.duration_seconds * (len(plan.assets) - 1))
        minutes, seconds = divmod(int(round(total)), 60)
        self._plan_summary.setText(f"共 {len(plan.assets)} 段 · 成片时长 {minutes:02d}:{seconds:02d}")
        self._set_enqueue_state(True, "")

    def _set_enqueue_state(self, enabled: bool, message: str) -> None:
        self._enqueue.setEnabled(enabled)
        self._enqueue_hint.setText(message)
        self._enqueue_hint.setVisible(bool(message))

    # ────────────────────────────── 模板 ──────────────────────────────

    def _template_payload(self) -> dict:
        draft = self.draft()
        return {
            "mode": draft.mode.value,
            "seed": draft.seed,
            "batch_count": draft.batch_count,
            "clips_per_plan": draft.clips_per_plan,
            "sequence_text": draft.sequence_text,
            "aspect": str(self._aspect.currentData()),
            "custom_width": int(self._custom_width.value()),
            "custom_height": int(self._custom_height.value()),
            "fit_mode": draft.settings.fit_mode.value,
            "fps": draft.settings.fps,
            "crf": draft.settings.crf,
            "preset": draft.settings.preset,
            "quality": str(self._quality.value()),
            "processing": draft.settings.processing.value,
            "output_resolution": draft.settings.output_video.resolution.value,
            "output_fps": draft.settings.output_video.frame_rate.value,
            "main_volume": draft.settings.main_volume_percent,
            "transition_enabled": self._transition_enable.isChecked(),
            "transition_seconds": float(self._transition_seconds.value()),
            "variation": None
            if draft.settings.variation is None
            else {
                "mirror": draft.settings.variation.mirror,
                "light_crop": draft.settings.variation.light_crop,
                "color": draft.settings.variation.color,
                "denoise": draft.settings.variation.denoise,
                "rotate": draft.settings.variation.rotate,
                "rotation_max_degrees": draft.settings.variation.rotation_max_degrees,
                "intensity": draft.settings.variation.intensity,
            },
            "split_enabled": self._double_enable.isChecked()
            or self._double_v_enable.isChecked()
            or self._four_enable.isChecked(),
            "split_mode": (
                "four"
                if self._four_enable.isChecked()
                else "double_v"
                if self._double_v_enable.isChecked()
                else "double_h"
                if self._double_enable.isChecked()
                else ""
            ),
            "split_four": self._four_enable.isChecked(),
            "split_start": int(self._split_start.value()),
            "split_feather": self._split_feather.isChecked(),
            "split_feather_px": int(self._split_feather_px.value()),
            "split_random": self._split_random.isChecked(),
            "library_enabled": self._library_enable.isChecked(),
            "library_fixed_enabled": self._library_fixed_enable.isChecked(),
            "library_random_enabled": self._library_random_enable.isChecked(),
            "library_volume": int(self._library_volume.value()),
            "library_min": int(self._library_min.value()),
            "library_max": int(self._library_max.value()),
            "bgm_enabled": self._bgm_enable.isChecked(),
            "bgm_volume": int(self._bgm_volume.value()),
            "bgm_fade": float(self._bgm_fade.value()),
            "bgm_loop": self._bgm_loop.isChecked(),
            # 音量语义版本：2 = −100..+100（0 为默认 BGM 音量）。缺省视为旧版 0..200。
            "volume_semantics": COMPOSITION_VOLUME_SEMANTICS,
            "aspect_enabled": self._aspect_enable.isChecked(),
            "overlay_fit": str(self._overlay_fit_mode.currentData() or OverlayFitMode.FILL_CROP.value),
            "overlay_enabled": self._overlay_enable.isChecked(),
            "overlay_random": self._overlay_random.isChecked(),
            "four_start": int(self._four_start.value()),
            "boost": self._boost_payload(),
            "output_prefix": draft.output_prefix,
        }

    def _boost_payload(self) -> dict:
        return {
            "volume_enabled": self._boost_volume_enable.isChecked(),
            "volume_mode": self._boost_volume_mode.value().value,
            "volume_fixed": float(self._boost_volume_fixed.value()),
            "volume_min": float(self._boost_volume_min.value()),
            "volume_max": float(self._boost_volume_max.value()),
            "scale_enabled": self._boost_scale_enable.isChecked(),
            "scale_mode": self._boost_scale_mode.value().value,
            "scale_fixed": float(self._boost_scale_fixed.value()),
            "scale_min": float(self._boost_scale_min.value()),
            "scale_max": float(self._boost_scale_max.value()),
        }

    def _apply_template_payload(self, payload: dict) -> None:
        self._updating_template = True
        try:
            mode_value = str(payload.get("mode") or OrderMode.RANDOM.value)
            self._mode.set_value(OrderMode.CUSTOM if mode_value == "custom" else OrderMode.RANDOM)
            self._refresh_mode()
            self._seed.setValue(int(payload.get("seed") or 0))
            self._batch_count.setValue(int(payload.get("batch_count") or 1))
            clips = payload.get("clips_per_plan")
            self._clips_per_plan.setText("" if clips in (None, "") else str(int(clips)))
            self._sequence.setPlainText(str(payload.get("sequence_text") or ""))

            aspect = str(payload.get("aspect") or "9:16")
            index = self._aspect.findData(aspect)
            self._aspect.setCurrentIndex(index if index >= 0 else 0)
            self._custom_width.setValue(int(payload.get("custom_width") or 1080))
            self._custom_height.setValue(int(payload.get("custom_height") or 1920))

            fit = str(payload.get("fit_mode") or "pad")
            self._fit_mode.set_value(FitMode(fit) if fit in {mode.value for mode in FitMode} else FitMode.PAD)

            fps_value = str(payload.get("output_fps") or "")
            if not fps_value:
                legacy_fps = payload.get("fps")
                fps_value = "original" if legacy_fps in (None, "") else str(int(float(legacy_fps)))
            fps_index = self._fps.findData(fps_value)
            self._fps.setCurrentIndex(fps_index if fps_index >= 0 else 0)

            quality = str(payload.get("quality") or QUALITY_DEFAULT)
            self._quality.set_value(quality)
            self._refresh_quality_hint()

            processing = str(payload.get("processing") or "auto")
            self._processing.set_value(ProcessingMode(processing))

            resolution_value = str(payload.get("output_resolution") or "")
            if not resolution_value:
                legacy_height = payload.get("output_height")
                resolution_value = {1080: "p1080", 720: "p720", 480: "p480"}.get(legacy_height, "original")
            resolution_index = self._resolution.findData(resolution_value)
            self._resolution.setCurrentIndex(resolution_index if resolution_index >= 0 else 0)

            self._main_volume.setValue(int(payload.get("main_volume") or 100))

            self._transition_enable.setChecked(bool(payload.get("transition_enabled", False)))
            self._transition_seconds.setValue(float(payload.get("transition_seconds") or 0.5))
            self._transition_seconds.setEnabled(self._transition_enable.isChecked())

            variation = payload.get("variation")
            if isinstance(variation, dict):
                self._variation_enable.setChecked(True)
                self._variation_mirror.setChecked(bool(variation.get("mirror", True)))
                self._variation_crop.setChecked(bool(variation.get("light_crop", True)))
                self._variation_color.setChecked(bool(variation.get("color", True)))
                self._variation_denoise.setChecked(bool(variation.get("denoise", False)))
                self._variation_rotate.setChecked(bool(variation.get("rotate", False)))
                self._variation_rotation_max.setValue(float(variation.get("rotation_max_degrees", 2.0)))
                self._variation_intensity.setValue(int(variation.get("intensity") or 50))
            else:
                self._variation_enable.setChecked(False)
            self._refresh_variation_state()

            split_mode = str(payload.get("split_mode") or "")
            if not split_mode:
                split_enabled = bool(payload.get("split_enabled", False))
                if split_enabled:
                    split_mode = "four" if bool(payload.get("split_four", False)) else "double_h"
            self._double_enable.setChecked(split_mode == "double_h")
            self._double_v_enable.setChecked(split_mode == "double_v")
            self._four_enable.setChecked(split_mode == "four")
            self._split_start.setValue(int(payload.get("split_start") or 1))
            self._split_feather.setChecked(bool(payload.get("split_feather", True)))
            feather_px = payload.get("split_feather_px")
            self._split_feather_px.setValue(48 if feather_px in (None, "") else int(feather_px))
            self._split_random.setChecked(bool(payload.get("split_random", False)))
            self._refresh_split_state()

            is_legacy_volume = int(payload.get("volume_semantics") or 0) < COMPOSITION_VOLUME_SEMANTICS
            self._library_volume.setValue(_migrate_volume_percent(payload.get("library_volume"), 30, is_legacy_volume))
            self._library_min.setValue(_migrate_volume_percent(payload.get("library_min"), 15, is_legacy_volume))
            self._library_max.setValue(_migrate_volume_percent(payload.get("library_max"), 45, is_legacy_volume))
            # 兼容旧模板的 library_volume_mode 字段。
            legacy_mode = str(payload.get("library_volume_mode") or "")
            if "library_fixed_enabled" in payload:
                self._library_fixed_enable.setChecked(bool(payload.get("library_fixed_enabled")))
            else:
                self._library_fixed_enable.setChecked(legacy_mode != "random")
            if "library_random_enabled" in payload:
                self._library_random_enable.setChecked(bool(payload.get("library_random_enabled")))
            else:
                self._library_random_enable.setChecked(legacy_mode == "random")
            if self._audio_library:
                self._library_enable.setChecked(bool(payload.get("library_enabled", False)))
            self._refresh_audio_library_state()

            if "bgm_enabled" in payload:
                self._bgm_enable.setChecked(bool(payload.get("bgm_enabled")))
            else:
                self._bgm_enable.setChecked(True)
            self._bgm_volume.setValue(_migrate_volume_percent(payload.get("bgm_volume"), 18, is_legacy_volume))
            self._bgm_fade.setValue(float(payload.get("bgm_fade") or 1.0))
            self._bgm_loop.setChecked(bool(payload.get("bgm_loop", True)))
            self._refresh_bgm_state()

            self._aspect_enable.setChecked(bool(payload.get("aspect_enabled", True)))
            overlay_fit = str(payload.get("overlay_fit") or OverlayFitMode.FILL_CROP.value)
            overlay_index = self._overlay_fit_mode.findData(overlay_fit)
            if overlay_index >= 0:
                self._overlay_fit_mode.setCurrentIndex(overlay_index)
            self._overlay_enable.setChecked(bool(payload.get("overlay_enabled", True)))
            self._overlay_random.setChecked(bool(payload.get("overlay_random", False)))
            self._four_start.setValue(int(payload.get("four_start") or 1))
            self._refresh_aspect_state()
            self._refresh_overlay_state()
            self._refresh_split_state()

            boost = payload.get("boost")
            if isinstance(boost, dict):
                self._apply_boost_payload(boost)

            prefix = str(payload.get("output_prefix") or "混剪")
            self._prefix.setText(prefix)
        finally:
            self._updating_template = False
        self._refresh_preview()

    def _apply_boost_payload(self, boost: dict) -> None:
        self._boost_volume_enable.setChecked(bool(boost.get("volume_enabled", False)))
        self._boost_volume_mode.set_value(
            MainMaterialBoostMode.RANDOM if str(boost.get("volume_mode")) == "random" else MainMaterialBoostMode.FIXED
        )
        self._boost_volume_fixed.setValue(float(boost.get("volume_fixed") or 105.0))
        self._boost_volume_min.setValue(float(boost.get("volume_min") or 100.0))
        self._boost_volume_max.setValue(float(boost.get("volume_max") or 110.0))
        self._boost_scale_enable.setChecked(bool(boost.get("scale_enabled", False)))
        self._boost_scale_mode.set_value(
            MainMaterialBoostMode.RANDOM if str(boost.get("scale_mode")) == "random" else MainMaterialBoostMode.FIXED
        )
        self._boost_scale_fixed.setValue(float(boost.get("scale_fixed") or 105.0))
        self._boost_scale_min.setValue(float(boost.get("scale_min") or 100.0))
        self._boost_scale_max.setValue(float(boost.get("scale_max") or 110.0))
        self._refresh_boost_state()

    def _refresh_templates(self) -> None:
        self._template_list.blockSignals(True)
        self._template_list.clear()
        for name in self._template_store.names:
            self._template_list.addItem(QListWidgetItem(name))
        self._template_list.setVisible(self._template_list.count() > 0)
        self._template_list.blockSignals(False)

    def _on_template_selected(self, name: str) -> None:
        if not self._updating_template and name:
            self._template_name.setText(name)

    def _save_template(self) -> None:
        name = self._template_name.text().strip()
        if not name:
            self.set_status("请先填写模板名称。", warn=True)
            return
        try:
            self._template_store.save(name, self._template_payload())
        except ValueError as error:
            self.set_status(str(error), warn=True)
            return
        self._refresh_templates()
        self.set_status(f"已保存模板：{name}")

    def _apply_template(self) -> None:
        name = self._template_name.text().strip() or (
            self._template_list.currentItem().text() if self._template_list.currentItem() else ""
        )
        payload = self._template_store.get(name) if name else None
        if payload is None:
            self.set_status("未找到该模板，请先选择或保存。", warn=True)
            return
        self._apply_template_payload(payload)
        self.set_status(f"已应用模板：{name}")

    def _rename_template(self) -> None:
        current = self._template_list.currentItem()
        new_name = self._template_name.text().strip()
        if current is None or not new_name:
            self.set_status("请选择模板并填写新名称。", warn=True)
            return
        if self._template_store.rename(current.text(), new_name):
            self._refresh_templates()
            self.set_status(f"已重命名为：{new_name}")
        else:
            self.set_status("重命名失败（模板不存在或名称为空）。", warn=True)

    def _delete_template(self) -> None:
        current = self._template_list.currentItem()
        if current is None:
            self.set_status("请先选择要删除的模板。", warn=True)
            return
        name = current.text()
        self._template_store.delete(name)
        self._refresh_templates()
        self.set_status(f"已删除模板：{name}")

    # ────────────────────────────── 序号模板 ──────────────────────────────

    def _refresh_sequence_templates(self) -> None:
        self._sequence_template.clear()
        names = self._sequence_store.names
        if not names:
            self._sequence_template.addItem("（暂无模板）", "")
            return
        for name in names:
            self._sequence_template.addItem(name, name)

    def _apply_sequence_template(self) -> None:
        name = str(self._sequence_template.currentData() or "")
        template = self._sequence_store.get(name) if name else None
        if template is None:
            self.set_status("请先选择要应用的序号模板。", warn=True)
            return
        self._sequence.setPlainText(template.expression)
        self._mode.set_value(OrderMode.CUSTOM)
        self._refresh_mode()
        self._refresh_preview()
        self.set_status(f"已应用序号模板：{template.display_name}")

    def _save_sequence_template(self) -> None:
        expression = self._sequence.toPlainText().strip()
        if not expression:
            self.set_status("请先填写序号表达式再保存为模板。", warn=True)
            return
        name = self._sequence_template.currentText().strip()
        if not name or name.startswith("（"):
            name = self._template_name.text().strip()
        if not name:
            self.set_status("请在「模板名称」或序号模板框填写名称。", warn=True)
            return
        try:
            self._sequence_store.save(name, expression)
        except ValueError as error:
            self.set_status(str(error), warn=True)
            return
        self._refresh_sequence_templates()
        self.set_status(f"已保存序号模板：{name}")

    def _rename_sequence_template(self) -> None:
        name = str(self._sequence_template.currentData() or "")
        new_name = self._template_name.text().strip()
        if not name or not new_name:
            self.set_status("请选择序号模板并在「模板名称」填写新名称。", warn=True)
            return
        try:
            renamed = self._sequence_store.rename(name, new_name)
        except ValueError as error:
            self.set_status(str(error), warn=True)
            return
        if renamed:
            self._refresh_sequence_templates()
            self.set_status(f"序号模板已重命名为：{new_name}")
        else:
            self.set_status("重命名失败（模板不存在或名称为空）。", warn=True)

    def _delete_sequence_template(self) -> None:
        name = str(self._sequence_template.currentData() or "")
        if not name:
            self.set_status("请先选择要删除的序号模板。", warn=True)
            return
        self._sequence_store.delete(name)
        self._refresh_sequence_templates()
        self.set_status(f"已删除序号模板：{name}")

    # ────────────────────────────── 交互 ──────────────────────────────

    def _pick_output_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择成片输出目录", str(self.output_directory()))
        if chosen:
            self._output_edit.setText(chosen)
            self._output_directory = Path(chosen)

    def _pick_bgm(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择背景音乐", "", AUDIO_FILTER)
        if path:
            self._bgm_file = Path(path)
            self._bgm_edit.setText(path)

    def _clear_bgm(self) -> None:
        self._bgm_file = None
        self._bgm_edit.clear()
