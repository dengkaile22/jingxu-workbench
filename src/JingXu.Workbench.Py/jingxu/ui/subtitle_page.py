"""字幕实验室：Whisper 识别、字幕编辑、样式与硬字幕去除。"""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jingxu.domain.subtitles import (
    DetectedSubtitleSegment,
    RemovalMode,
    SubtitleBurnSpec,
    SubtitleCue,
    SubtitlePosition,
    SubtitleRemovalSpec,
    SubtitleStyle,
    has_pending_reviews,
    validate_timeline,
)
from jingxu.infrastructure.frame_preview import FramePreviewError, extract_single_frame
from jingxu.infrastructure.ocr import (
    OcrCancelled,
    OcrError,
    detect_subtitle_regions,
    find_tesseract,
)
from jingxu.infrastructure.subtitles import build_ass, format_srt, load_subtitle_file
from jingxu.infrastructure.subtitle_store import SubtitleStore
from jingxu.infrastructure.whisper import (
    WhisperCancelled,
    WhisperError,
    WhisperRuntime,
    find_whisper,
    transcribe,
)
from jingxu.ui.subtitle_region import SubtitleRegionCanvas
from jingxu.ui.widgets import Caption, PrimaryButton, SecondaryButton, SectionHeader, SegmentedControl

COLUMNS = ("起点", "终点", "字幕文本")
COLOR_OPTIONS = (("白色", "#FFFFFF"), ("黄色", "#FFE066"), ("黑色", "#101010"), ("粉色", "#F28A9C"))
POSITION_OPTIONS = (
    ("底部", SubtitlePosition.BOTTOM),
    ("居中", SubtitlePosition.MIDDLE),
    ("顶部", SubtitlePosition.TOP),
)
REMOVAL_OPTIONS = tuple((mode.display_text, mode) for mode in RemovalMode)
TESSERACT_MISSING_TEXT = "未找到 Tesseract（放入 runtime/tesseract 后可用）"
SOURCE_MISSING_TEXT = "请先在「混剪」页选中素材"
FULL_FRAME_SCAN_REGION = (0.0, 0.0, 1.0, 1.0)
DEFAULT_SCAN_REGION = (0.0, 0.55, 1.0, 0.45)


class SubtitleBridge(QObject):
    progress = Signal(float, str)
    finished = Signal(object, str)
    failed = Signal(str)


class OcrBridge(QObject):
    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(str)


class RegionFrameBridge(QObject):
    """预览帧抽帧结果回主线程（跨线程必须走信号，不能用 QTimer）。"""

    done = Signal(str, object, str)


def _coerce(enum_type, value):  # noqa: ANN001, ANN202
    """Qt 会把 str 枚举退化成普通字符串（如 QComboBox 数据），这里统一还原。"""
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))


class SubtitlePage(QWidget):
    """识别 + 编辑 + 样式 + 硬字幕去除，参数即改即存。"""

    def __init__(self, store: SubtitleStore, ffmpeg: Path, ffmpeg_runner_available: bool = True) -> None:
        super().__init__()
        self._store = store
        self._ffmpeg = Path(ffmpeg)
        self._whisper: WhisperRuntime | None = find_whisper()
        self._tesseract: Path | None = find_tesseract()
        self._cues: list[SubtitleCue] = list(store.document.cues)
        self._updating = False
        self._worker: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._ocr_worker: threading.Thread | None = None
        self._ocr_cancel_event = threading.Event()
        self._detected_segments: list[DetectedSubtitleSegment] = []
        self._canvas_width = 1080
        self._canvas_height = 1920

        bridge = SubtitleBridge(self)
        bridge.progress.connect(self._on_progress)
        bridge.finished.connect(self._on_transcribed)
        bridge.failed.connect(self._on_failed)
        self._bridge = bridge

        ocr_bridge = OcrBridge(self)
        ocr_bridge.progress.connect(self._on_ocr_progress)
        ocr_bridge.finished.connect(self._on_ocr_finished)
        ocr_bridge.failed.connect(self._on_ocr_failed)
        self._ocr_bridge = ocr_bridge

        # 预览帧抽帧结果回主线程（跨线程不能用 QTimer，见 _load_region_frame_async）。
        self._frame_bridge = RegionFrameBridge(self)

        # 整页放进滚动区：字幕表 + 烧录样式 + 硬字幕去除 + OCR 定位很长，
        # 窗口不够高时下方区块会被截断且无法滚动到。与合成页保持同一写法。
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

        layout.addSpacing(12)
        layout.addLayout(self._build_recognition_row())
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # 「预览与区域选择」：对齐 .NET 字幕实验室——导入视频后可直接在画面上
        # 框选字幕区域，而不必手填百分比（手填很难填对，是此前「字幕功能不用」的主因）。
        layout.addSpacing(12)
        layout.addWidget(SectionHeader("预览与区域选择"))
        layout.addSpacing(6)
        self._region_canvas = SubtitleRegionCanvas()
        layout.addWidget(self._region_canvas)
        layout.addSpacing(6)
        layout.addLayout(self._build_region_actions())

        # 「检测与识别」：对齐 .NET——OCR 与 Whisper 放在同一区块，且「确认全部区域」
        # 也在这里（检测完就地确认），而不是散落在页面底部。
        layout.addSpacing(14)
        layout.addWidget(SectionHeader("检测与识别"))
        layout.addSpacing(8)
        layout.addLayout(self._build_recognition_row())
        layout.addLayout(self._build_ocr_row())
        self._ocr_progress = QProgressBar()
        self._ocr_progress.setRange(0, 100)
        self._ocr_progress.setFixedHeight(6)
        self._ocr_progress.setTextVisible(False)
        self._ocr_progress.setVisible(False)
        layout.addWidget(self._ocr_progress)

        self._detected_list = QListWidget()
        self._detected_list.setMaximumHeight(90)
        self._detected_list.setVisible(False)
        layout.addWidget(self._detected_list)

        self._apply_detected = SecondaryButton("应用检测区域")
        self._apply_detected.setVisible(False)
        self._apply_detected.clicked.connect(self._apply_selected_segment)
        layout.addWidget(self._apply_detected)

        self._review_hint = Caption("")
        self._review_hint.setObjectName("CaptionWarn")
        self._review_hint.setVisible(False)
        layout.addWidget(self._review_hint)

        # 「去字幕方式」：对齐 .NET 的区块名。
        layout.addSpacing(14)
        layout.addWidget(SectionHeader("去字幕方式"))
        layout.addSpacing(8)
        layout.addLayout(self._build_removal_row())

        # 「烧录样式」是 Python 版增强（.NET 字幕页没有样式设置）。
        layout.addSpacing(14)
        layout.addWidget(SectionHeader("烧录样式"))
        layout.addSpacing(8)
        layout.addLayout(self._build_style_row())

        # 「字幕列表」：新增/导入/导出/清空 + 表格。
        layout.addSpacing(14)
        layout.addWidget(SectionHeader("字幕列表"))
        layout.addSpacing(8)
        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 130)
        self._table.setColumnWidth(1, 130)
        self._table.itemChanged.connect(self._on_cue_edited)
        # 滚动区里 stretch 不再分配高度，必须给下限，否则字幕表会被压成一条。
        self._table.setMinimumHeight(200)
        layout.addWidget(self._table)

        self._refresh_table()
        self._load_style_controls()
        self._refresh_whisper_status()
        self._refresh_ocr_status()

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel("字幕实验室")
        title.setObjectName("Title")
        row.addWidget(title)
        row.addStretch(1)

        add_button = SecondaryButton("添加一行")
        add_button.clicked.connect(self._add_cue)
        row.addWidget(add_button)

        remove_button = SecondaryButton("删除选中")
        remove_button.clicked.connect(self._remove_selected)
        row.addWidget(remove_button)

        import_button = SecondaryButton("导入 SRT…")
        import_button.clicked.connect(self._import_srt)
        row.addWidget(import_button)

        export_button = SecondaryButton("导出 SRT…")
        export_button.clicked.connect(self._export_srt)
        row.addWidget(export_button)

        clear_button = SecondaryButton("清空")
        clear_button.clicked.connect(self._clear_cues)
        row.addWidget(clear_button)
        return row

    def _build_recognition_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._language = QComboBox()
        for label, value in (("自动检测", "auto"), ("中文", "zh"), ("英语", "en")):
            self._language.addItem(label, value)
        row.addWidget(Caption("识别语言"), alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._language)

        self._start_button = PrimaryButton("识别当前选中素材")
        self._start_button.clicked.connect(self.start_transcription)
        row.addWidget(self._start_button)

        self._cancel_button = SecondaryButton("取消")
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self.cancel_transcription)
        row.addWidget(self._cancel_button)

        # 「确认全部区域」放在检测区（对齐 .NET：检测完就地确认，不用滚到页面底部）。
        self._confirm_all = SecondaryButton("确认全部区域")
        self._confirm_all.setVisible(False)
        self._confirm_all.clicked.connect(self.confirm_all_segments)
        row.addWidget(self._confirm_all)

        self._whisper_label = Caption("")
        row.addWidget(self._whisper_label, stretch=1)
        return row

    def _build_style_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._size = QComboBox()
        for size in (16, 18, 20, 22, 26, 30, 36, 42):
            self._size.addItem(f"{size}px", size)
        row.addWidget(Caption("字号"), alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._size)

        self._color = QComboBox()
        for label, value in COLOR_OPTIONS:
            self._color.addItem(label, value)
        row.addWidget(Caption("颜色"), alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._color)

        self._outline = QComboBox()
        for width in (0, 1, 2, 3, 4):
            self._outline.addItem(f"描边 {width}", width)
        row.addWidget(self._outline)

        self._position = QComboBox()
        for label, value in POSITION_OPTIONS:
            self._position.addItem(label, value)
        row.addWidget(Caption("位置"), alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._position)

        self._margin = QComboBox()
        for margin in (20, 40, 60, 90, 120):
            self._margin.addItem(f"边距 {margin}", margin)
        row.addWidget(self._margin)
        row.addStretch(1)

        for combo in (self._size, self._color, self._outline, self._position, self._margin):
            combo.currentIndexChanged.connect(self._on_style_changed)
        return row

    def _build_removal_row(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._removal_enable = QCheckBox("启用硬字幕去除")
        self._removal_enable.stateChanged.connect(self._on_removal_changed)
        top.addWidget(self._removal_enable)

        self._removal_mode = SegmentedControl(REMOVAL_OPTIONS)
        self._removal_mode.changed.connect(lambda _: self._on_removal_changed())
        top.addWidget(self._removal_mode)
        top.addStretch(1)
        column.addLayout(top)

        region = QHBoxLayout()
        region.setSpacing(8)
        self._region_spins: dict[str, QSpinBox] = {}
        for key, label, default in (
            ("x", "左 %", 8),
            ("y", "上 %", 76),
            ("w", "宽 %", 84),
            ("h", "高 %", 18),
        ):
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setSingleStep(1)
            spin.setValue(default)
            spin.valueChanged.connect(self._on_removal_changed)
            self._region_spins[key] = spin
            region.addWidget(Caption(label), alignment=Qt.AlignmentFlag.AlignVCenter)
            region.addWidget(spin)
            region.addSpacing(6)
        region.addStretch(1)
        column.addLayout(region)

        column.addWidget(
            Caption("区域按成片宽高百分比；模糊模式对区域降采样，遮盖为纯黑块，去标用邻域插值。")
        )
        return column

    def _build_region_actions(self) -> QHBoxLayout:
        """框选区工具条：加载预览帧 / 确认手动区域 / 全画面 OCR 扫描。"""
        row = QHBoxLayout()
        row.setSpacing(8)

        self._region_load = SecondaryButton("加载预览帧")
        self._region_load.setToolTip("从当前选中素材抽取一帧作为框选底图。")
        self._region_load.clicked.connect(self._load_region_frame)
        row.addWidget(self._region_load)

        self._region_confirm = PrimaryButton("确认手动区域")
        self._region_confirm.setToolTip("把画面上框选的区域应用到「硬字幕去除」的区域参数。")
        self._region_confirm.clicked.connect(self._commit_manual_region)
        row.addWidget(self._region_confirm)

        self._region_hint = Caption("导入视频后可在此框选字幕区域")
        row.addWidget(self._region_hint, stretch=1)
        return row

    def _load_region_frame(self) -> None:
        """抽取当前素材首帧作为框选底图。"""
        source = getattr(self, "_source", None)
        if source is None or not Path(source).is_file():
            self._set_status("请先在「混剪」页选中一个素材，再回到本页框选区域。", warn=True)
            return
        if self._ffmpeg is None:
            self._set_status("未找到 FFmpeg，无法抽取预览帧。", warn=True)
            return
        try:
            frame_path = extract_single_frame(
                Path(self._ffmpeg),
                Path(source),
                self._frame_directory() / f"subtitle-frame-{uuid4().hex[:8]}.png",
            )
        except FramePreviewError as error:
            self._set_status(str(error), warn=True)
            return
        pixmap = QPixmap(str(frame_path))
        if pixmap.isNull():
            self._set_status("预览帧无法读取。", warn=True)
            return
        self._region_canvas.set_frame(pixmap)
        # 同步当前区域参数到画布，避免画面与数值不一致
        self._region_canvas.set_region(
            self._region_spins["x"].value() / 100.0,
            self._region_spins["y"].value() / 100.0,
            self._region_spins["w"].value() / 100.0,
            self._region_spins["h"].value() / 100.0,
        )
        self._region_hint.setText(
            f"预览帧 {pixmap.width()}×{pixmap.height()}：拖拽选框调整区域，完成后点「确认手动区域」。"
        )
        # 载入帧后立即标出当前生效的去字幕区域，便于先看偏差再调整。
        self._refresh_removal_overlay()

    def _frame_directory(self) -> Path:
        from jingxu.infrastructure.paths import data_directory

        directory = data_directory() / "subtitle-frames"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _commit_manual_region(self) -> None:
        """把画布上的框选结果写入区域参数（对齐 .NET「确认手动区域」）。"""
        if not self._region_canvas.has_frame():
            self._set_status("请先点「加载预览帧」，再在画面上框选区域。", warn=True)
            return
        x, y, width, height = self._region_canvas.region()
        self._updating = True
        try:
            self._region_spins["x"].setValue(int(round(x * 100)))
            self._region_spins["y"].setValue(int(round(y * 100)))
            self._region_spins["w"].setValue(int(round(width * 100)))
            self._region_spins["h"].setValue(int(round(height * 100)))
        finally:
            self._updating = False
        if not self._removal_enable.isChecked():
            self._removal_enable.setChecked(True)
        self._on_removal_changed()
        self._set_status(
            f"已应用手动区域：左 {int(round(x * 100))}% / 上 {int(round(y * 100))}% / "
            f"宽 {int(round(width * 100))}% / 高 {int(round(height * 100))}%。"
        )

    def _sync_region_canvas_from_spins(self) -> None:
        """手改百分比时同步画布选框，并刷新「实际去除区域」标记。"""
        if not hasattr(self, "_region_canvas"):
            return
        self._refresh_removal_overlay()
        if not self._region_canvas.has_frame():
            return
        self._region_canvas.set_region(
            self._region_spins["x"].value() / 100.0,
            self._region_spins["y"].value() / 100.0,
            self._region_spins["w"].value() / 100.0,
            self._region_spins["h"].value() / 100.0,
        )

    def _refresh_removal_overlay(self) -> None:
        """把**实际生效**的去字幕区域画到预览帧上。

        只让用户拖框、却不显示「真正会被去掉的范围」，就无法发现框偏了——
        实测出现过模糊只盖住文字上半截、下半截仍然清晰的情况。
        """
        canvas = getattr(self, "_region_canvas", None)
        if canvas is None:
            return
        if not self._removal_enable.isChecked():
            canvas.set_removal_region(None)
            return
        x = self._region_spins["x"].value() / 100.0
        y = self._region_spins["y"].value() / 100.0
        width = self._region_spins["w"].value() / 100.0
        height = self._region_spins["h"].value() / 100.0
        if width <= 0 or height <= 0:
            canvas.set_removal_region(None)
            return
        mode = _coerce(RemovalMode, self._removal_mode.value())
        canvas.set_removal_region(
            (x, y, width, height),
            label=f"实际去除区域 · {mode.display_text}",
        )

    def _build_ocr_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._ocr_button = SecondaryButton("OCR 检测硬字幕")
        self._ocr_button.clicked.connect(self.start_ocr_detection)
        row.addWidget(self._ocr_button)

        self._ocr_full_frame = QCheckBox("全画面扫描")
        self._ocr_full_frame.stateChanged.connect(lambda _: self._refresh_scan_region_hint())
        row.addWidget(self._ocr_full_frame)

        # 对齐 .NET ``ScanRegionDescription``：明确当前扫的是全画面还是下方 45%，
        # 否则用户不知道「全画面扫描」没勾时到底扫哪儿。
        self._scan_region_hint = Caption("")
        row.addWidget(self._scan_region_hint)

        self._ocr_cancel = SecondaryButton("取消 OCR")
        self._ocr_cancel.setEnabled(False)
        self._ocr_cancel.clicked.connect(self.cancel_ocr)
        row.addWidget(self._ocr_cancel)

        self._ocr_status = Caption("")
        row.addWidget(self._ocr_status, stretch=1)
        self._refresh_scan_region_hint()
        return row

    def _refresh_scan_region_hint(self) -> None:
        """显示当前 OCR 扫描范围（对齐 .NET ``ScanRegionDescription``）。"""
        hint = getattr(self, "_scan_region_hint", None)
        if hint is None:
            return
        hint.setText("全画面扫描" if self._ocr_full_frame.isChecked() else "下方 45% 扫描")

    # ────────────────────────────── 字幕表 ──────────────────────────────

    def _refresh_table(self) -> None:
        self._updating = True
        self._table.setRowCount(len(self._cues))
        for row, cue in enumerate(self._cues):
            for column, text in enumerate((cue.start_text, cue.end_text, cue.text.replace("\n", " "))):
                item = self._table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self._table.setItem(row, column, item)
                item.setText(text)
        self._updating = False

    def _on_cue_edited(self, _item: QTableWidgetItem) -> None:
        if self._updating:
            return
        cues: list[SubtitleCue] = []
        for row in range(self._table.rowCount()):
            start = self._parse_time(self._table.item(row, 0).text() if self._table.item(row, 0) else "")
            end = self._parse_time(self._table.item(row, 1).text() if self._table.item(row, 1) else "")
            text = (self._table.item(row, 2).text() if self._table.item(row, 2) else "").strip()
            if start is None or end is None or not text:
                continue
            cues.append(SubtitleCue(start=start, end=max(end, start + 0.01), text=text))
        self._cues = cues
        self._persist()

    @staticmethod
    def _parse_time(text: str) -> float | None:
        raw = (text or "").replace(",", ".").strip()
        parts = raw.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            return float(raw)
        except ValueError:
            return None

    def _add_cue(self) -> None:
        start = self._cues[-1].end if self._cues else 0.0
        self._cues.append(SubtitleCue(start=start, end=start + 2.0, text="新字幕"))
        self._refresh_table()
        self._persist()

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._cues):
                self._cues.pop(row)
        self._refresh_table()
        self._persist()

    def _clear_cues(self) -> None:
        if not self._cues:
            return
        self._cues = []
        self._refresh_table()
        self._persist()

    def _import_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入字幕", "", "字幕文件 (*.srt *.ass *.ssa);;所有文件 (*)"
        )
        if not path:
            return
        try:
            cues = load_subtitle_file(Path(path))
        except OSError as error:
            QMessageBox.warning(self, "导入失败", str(error))
            return
        if not cues:
            self._set_status("未解析到字幕条目。", warn=True)
            return
        self._cues = cues
        self._refresh_table()
        self._persist()
        self._set_status(f"已导入 {len(cues)} 条字幕。")

    def _export_srt(self) -> None:
        if not self._cues:
            self._set_status("没有可导出的字幕。", warn=True)
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出字幕", "字幕.srt", "SRT 字幕 (*.srt);;ASS 字幕 (*.ass)"
        )
        if not path:
            return
        target = Path(path)
        want_ass = target.suffix.lower() in {".ass", ".ssa"} or "ASS" in (selected_filter or "").upper()
        if want_ass and target.suffix.lower() not in {".ass", ".ssa"}:
            target = target.with_suffix(".ass")
        if want_ass:
            target.write_text(
                build_ass(self._cues, self._current_style(), self._canvas_width, self._canvas_height),
                encoding="utf-8-sig",
            )
        else:
            target.write_text(format_srt(self._cues), encoding="utf-8-sig")
        self._set_status(f"已导出：{target}")

    def timeline_issues(self) -> list[str]:
        """字幕时间轴与 OCR 复核的阻断问题（空表示可以入队烧录）。"""
        issues = validate_timeline(self._cues)
        if has_pending_reviews(self._detected_segments):
            issues.append("存在待复核的 OCR 字幕区域，请先确认区域后再烧录。")
        return issues

    def confirm_all_segments(self) -> None:
        """把全部待复核区域标记为已确认（对齐 .NET「确认全部区域」）。"""
        if not self._detected_segments:
            self._set_status("还没有检测结果。", warn=True)
            return
        self._detected_segments = [
            replace(segment, review_state="confirmed", requires_review=False)
            if segment.review_state == "pending"
            else segment
            for segment in self._detected_segments
        ]
        self._detected_list.clear()
        for segment in self._detected_segments:
            self._detected_list.addItem(self._segment_row_text(segment))
        self._refresh_review_hint()
        self._set_status(f"已确认 {len(self._detected_segments)} 个区域。")

    def set_canvas_size(self, width: int, height: int) -> None:
        """由壳层同步成片画幅（导出 ASS 时用作 PlayRes）。

        为什么要传真实像素尺寸而不是只传比例：``build_ass`` 直接把它写进
        ``PlayResX/Y``，字幕字号与边距都以此为基准。画幅是 720×1280 或自定义时
        若仍按 1080×1920 导出，用户把 ASS 导入别的工具就会出现字号与位置偏差。
        """
        if width > 0 and height > 0:
            self._canvas_width = int(width)
            self._canvas_height = int(height)

    def _refresh_review_hint(self) -> None:
        pending = [segment for segment in self._detected_segments if segment.requires_review and segment.review_state == "pending"]
        self._review_hint.setVisible(bool(pending))
        self._confirm_all.setVisible(bool(pending))
        if pending:
            self._review_hint.setText(f"有 {len(pending)} 个低置信区域待复核，确认后才能烧录。")

    # ────────────────────────────── 识别 ──────────────────────────────

    def set_source_material(self, path: Path | None) -> None:
        """接收混剪页选中的素材，并**自动加载预览帧**。

        此前需要用户手动点「加载预览帧」才出现画面；没加载时画布只有占位提示，
        区域框却仍然显示，看起来像已就绪但拖不动——实测用户会卡在这里。
        现在换素材即自动取帧（后台线程，不阻塞界面）。
        """
        previous = getattr(self, "_source", None)
        self._source = Path(path) if path else None
        self._refresh_whisper_status()
        if self._source is None or self._source == previous:
            return
        if not self._source.is_file():
            return
        # 先清掉旧画面，避免显示上一个素材的帧造成误判。
        self._region_canvas.set_frame(None)
        self._region_canvas.set_removal_region(None)
        self._region_hint.setText(f"正在读取预览帧：{self._source.name} …")
        self._load_region_frame_async(self._source)

    def _load_region_frame_async(self, source: Path) -> None:
        """后台抽帧并通过信号回主线程上屏（避免大文件阻塞界面，也避免跨线程改界面）。

        注意：不能在**工作线程**里用 ``QTimer.singleShot`` 回调主线程——该线程
        没有事件循环，回调永不执行（实测帧一直加载不出来）。必须用 Qt 信号跨线程。
        """
        import threading

        bridge = self._frame_bridge
        bridge.done.connect(self._on_region_frame_ready)

        def work() -> None:
            pixmap: QPixmap | None = None
            message = ""
            try:
                frame_path = extract_single_frame(
                    Path(self._ffmpeg),
                    source,
                    self._frame_directory() / f"subtitle-frame-{uuid4().hex[:8]}.png",
                )
                loaded = QPixmap(str(frame_path))
                if loaded.isNull():
                    message = "预览帧无法读取。"
                else:
                    pixmap = loaded
            except FramePreviewError as error:
                message = str(error)
            except Exception as error:  # noqa: BLE001 - 后台线程不得抛出
                message = f"读取预览帧失败：{error}"
            # 信号跨线程投递，由主线程执行 _on_region_frame_ready
            bridge.done.emit(str(source), pixmap, message)

        threading.Thread(target=work, name="jingxu-subtitle-frame", daemon=True).start()

    def _on_region_frame_ready(
        self,
        source_text: str,
        pixmap: object,
        message: str,
    ) -> None:
        """主线程接收抽帧结果。期间又换了素材则丢弃本次结果。"""
        if self._source is None or str(self._source) != source_text:
            return
        if not isinstance(pixmap, QPixmap) or pixmap.isNull():
            text = message or "读取预览帧失败。"
            self._region_hint.setText(text)
            self._set_status(text, warn=True)
            return
        self._region_canvas.set_frame(pixmap)
        self._region_hint.setText(
            f"预览帧 {pixmap.width()}×{pixmap.height()}：拖拽选框调整区域，"
            "橙框为实际去除范围。"
        )
        self._refresh_removal_overlay()

    def start_transcription(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        source = getattr(self, "_source", None)
        if source is None or not Path(source).is_file():
            self._set_status("请先在「混剪」页选中一个素材，再回到本页识别。", warn=True)
            return
        if self._whisper is None:
            self._set_status("未找到 Whisper 组件（runtime/whisper/whisper-cli.exe + 模型）。", warn=True)
            return

        self._cancel_event = threading.Event()
        self._start_button.setEnabled(False)
        self._cancel_button.setEnabled(True)
        self._progress.setVisible(True)
        self._progress.setValue(0)

        language = str(self._language.currentData())
        self._set_status(f"开始识别：{Path(source).name}")

        def work() -> None:
            try:
                cues = transcribe(
                    Path(source),
                    ffmpeg_path=self._ffmpeg,
                    runtime=self._whisper,
                    language=language,
                    on_progress=lambda percent, text: self._bridge.progress.emit(percent, text),
                    cancel_event=self._cancel_event,
                )
                self._bridge.finished.emit(cues, "")
            except WhisperCancelled:
                self._bridge.failed.emit("识别已取消。")
            except (WhisperError, OSError) as error:
                self._bridge.failed.emit(str(error))

        self._worker = threading.Thread(target=work, name="jingxu-whisper", daemon=True)
        self._worker.start()

    def cancel_transcription(self) -> None:
        self._cancel_event.set()

    def _on_progress(self, percent: float, text: str) -> None:
        self._progress.setVisible(True)
        self._progress.setValue(int(percent))
        self._set_status(text)

    def _on_transcribed(self, cues: list[SubtitleCue], _message: str) -> None:
        self._cues = list(cues)
        self._refresh_table()
        self._persist()
        self._finish_worker()
        self._set_status(f"识别完成：{len(self._cues)} 条字幕（已写入列表，可编辑）。")

    def _on_failed(self, message: str) -> None:
        self._finish_worker()
        self._set_status(message, warn=True)

    def _finish_worker(self) -> None:
        self._start_button.setEnabled(True)
        self._cancel_button.setEnabled(False)
        self._progress.setVisible(False)

    def _refresh_whisper_status(self) -> None:
        if self._whisper is None:
            self._whisper_label.setText("Whisper：未安装（放入 runtime/whisper 后可用）")
            self._start_button.setEnabled(False)
            return
        source = getattr(self, "_source", None)
        material = f"当前素材：{Path(source).name}" if source else "请先在混剪页选中素材"
        self._whisper_label.setText(f"Whisper：{self._whisper.label} · {material}")

    # ────────────────────────────── OCR ──────────────────────────────

    def _refresh_ocr_status(self) -> None:
        if self._tesseract is None:
            self._ocr_button.setEnabled(False)
            self._ocr_status.setText(TESSERACT_MISSING_TEXT)
            return
        self._ocr_button.setEnabled(True)
        self._ocr_status.setText("")

    def start_ocr_detection(self) -> None:
        if self._ocr_worker is not None and self._ocr_worker.is_alive():
            return
        if self._tesseract is None:
            self._set_ocr_status(TESSERACT_MISSING_TEXT, warn=True)
            return
        source = getattr(self, "_source", None)
        if source is None or not Path(source).is_file():
            self._set_ocr_status(SOURCE_MISSING_TEXT, warn=True)
            return

        scan_region = FULL_FRAME_SCAN_REGION if self._ocr_full_frame.isChecked() else DEFAULT_SCAN_REGION
        self._ocr_cancel_event = threading.Event()
        self._ocr_button.setEnabled(False)
        self._ocr_cancel.setEnabled(True)
        self._ocr_progress.setVisible(True)
        self._ocr_progress.setValue(0)
        self._detected_list.clear()
        self._detected_list.setVisible(False)
        self._apply_detected.setVisible(False)
        self._set_ocr_status(f"正在检测：{Path(source).name}")

        def work() -> None:
            try:
                segments = detect_subtitle_regions(
                    self._ffmpeg,
                    Path(source),
                    duration=None,
                    tesseract_path=self._tesseract,
                    scan_region=scan_region,
                    on_progress=lambda percent, text: self._ocr_bridge.progress.emit(percent, text),
                    cancel_event=self._ocr_cancel_event,
                )
                self._ocr_bridge.finished.emit(segments)
            except OcrCancelled:
                self._ocr_bridge.failed.emit("OCR 检测已取消。")
            except (OcrError, OSError) as error:
                self._ocr_bridge.failed.emit(str(error))

        self._ocr_worker = threading.Thread(target=work, name="jingxu-ocr", daemon=True)
        self._ocr_worker.start()

    def cancel_ocr(self) -> None:
        self._ocr_cancel_event.set()

    def _on_ocr_progress(self, percent: float, text: str) -> None:
        self._ocr_progress.setVisible(True)
        self._ocr_progress.setValue(int(percent))
        self._set_ocr_status(text)

    def _on_ocr_finished(self, segments: list[DetectedSubtitleSegment]) -> None:
        self._detected_segments = list(segments)
        self._detected_list.clear()
        for segment in self._detected_segments:
            self._detected_list.addItem(self._segment_row_text(segment))
        self._detected_list.setVisible(bool(self._detected_segments))
        self._apply_detected.setVisible(bool(self._detected_segments))
        self._refresh_review_hint()
        self._finish_ocr_worker()
        if self._detected_segments:
            self._set_ocr_status(f"检测完成：{len(self._detected_segments)} 个区域，选中后点击「应用检测区域」。")
        else:
            self._set_ocr_status("未检测到字幕区域，可勾选「全画面扫描」重试。")

    def _on_ocr_failed(self, message: str) -> None:
        self._finish_ocr_worker()
        self._set_ocr_status(message, warn=True)

    def _finish_ocr_worker(self) -> None:
        self._ocr_button.setEnabled(self._tesseract is not None)
        self._ocr_cancel.setEnabled(False)
        self._ocr_progress.setVisible(False)

    @staticmethod
    def _segment_row_text(segment: DetectedSubtitleSegment) -> str:
        region = ",".join(
            f"{round(value)}%"
            for value in (
                segment.x_percent,
                segment.y_percent,
                segment.width_percent,
                segment.height_percent,
            )
        )
        text = (
            f"{segment.start_seconds:.1f}s–{segment.end_seconds:.1f}s"
            f" · 区域 {region} · 置信度 {round(segment.confidence * 100)}%"
        )
        return f"{text}（待复核）" if segment.requires_review else text

    def _apply_selected_segment(self) -> None:
        row = self._detected_list.currentRow()
        if row < 0 and self._detected_segments:
            row = 0
        if 0 <= row < len(self._detected_segments):
            self._apply_detected_segment(self._detected_segments[row])

    def _apply_detected_segment(self, segment: DetectedSubtitleSegment) -> None:
        self._updating = True
        try:
            self._region_spins["x"].setValue(int(round(segment.x_percent)))
            self._region_spins["y"].setValue(int(round(segment.y_percent)))
            self._region_spins["w"].setValue(int(round(segment.width_percent)))
            self._region_spins["h"].setValue(int(round(segment.height_percent)))
            self._removal_enable.setChecked(True)
            # 应用即视为人工复核通过（对齐 .NET ApplyManualRegionAsDetected）。
            for index, candidate in enumerate(self._detected_segments):
                if candidate == segment:
                    self._detected_segments[index] = replace(candidate, review_state="confirmed")
                    item = self._detected_list.item(index)
                    if item is not None:
                        item.setText(self._segment_row_text(self._detected_segments[index]))
                    break
        finally:
            self._updating = False
        self._persist()
        self._refresh_review_hint()
        self._refresh_removal_overlay()
        span = f"{segment.start_seconds:.1f}s–{segment.end_seconds:.1f}s"
        if segment.requires_review:
            self._set_ocr_status(f"已应用检测区域（{span}），低置信区域已记录并完成人工复核。")
        else:
            self._set_ocr_status(f"已应用检测区域（{span}）。")

    def _set_ocr_status(self, text: str, *, warn: bool = False) -> None:
        self._ocr_status.setObjectName("CaptionWarn" if warn else "Caption")
        self._ocr_status.setText(text)
        self._ocr_status.setVisible(bool(text))
        self._ocr_status.style().unpolish(self._ocr_status)
        self._ocr_status.style().polish(self._ocr_status)

    # ────────────────────────────── 样式 / 去除 ──────────────────────────────

    def _load_style_controls(self) -> None:
        style = self._store.document.style
        self._updating = True
        self._select_by_data(self._size, style.font_size)
        self._select_by_data(self._color, style.color)
        self._select_by_data(self._outline, style.outline)
        self._select_by_data(self._position, _coerce(SubtitlePosition, style.position).value)
        self._select_by_data(self._margin, style.margin_v)
        removal = self._store.document.removal
        self._removal_enable.setChecked(removal.enabled)
        self._removal_mode.set_value(removal.mode)
        self._region_spins["x"].setValue(int(round(removal.x_percent)))
        self._region_spins["y"].setValue(int(round(removal.y_percent)))
        self._region_spins["w"].setValue(int(round(removal.width_percent)))
        self._region_spins["h"].setValue(int(round(removal.height_percent)))
        self._updating = False

    @staticmethod
    def _select_by_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _current_style(self) -> SubtitleStyle:
        return SubtitleStyle(
            font_size=int(self._size.currentData()),
            color=str(self._color.currentData()),
            outline=int(self._outline.currentData()),
            position=_coerce(SubtitlePosition, self._position.currentData()),
            margin_v=int(self._margin.currentData()),
        )

    def _on_style_changed(self, *_args: object) -> None:
        if self._updating:
            return
        self._store.document.style = self._current_style()
        self._persist()

    def _current_removal(self) -> SubtitleRemovalSpec:
        return SubtitleRemovalSpec(
            mode=_coerce(RemovalMode, self._removal_mode.value()),
            x_percent=float(self._region_spins["x"].value()),
            y_percent=float(self._region_spins["y"].value()),
            width_percent=float(self._region_spins["w"].value()),
            height_percent=float(self._region_spins["h"].value()),
            enabled=self._removal_enable.isChecked(),
        )

    def _on_removal_changed(self, *_args: object) -> None:
        if self._updating:
            return
        # 裁切重构仅适用于贴顶或贴底的字幕带：自动收敛到贴底区域，避免入队才报错。
        if _coerce(RemovalMode, self._removal_mode.value()) is RemovalMode.CROP_AND_REFRAME:
            y = self._region_spins["y"].value()
            height = self._region_spins["h"].value()
            if y > 1 and y + height < 99:
                self._updating = True
                try:
                    self._region_spins["y"].setValue(82)
                    self._region_spins["h"].setValue(18)
                finally:
                    self._updating = False
        self._store.document.removal = self._current_removal()
        self._persist()
        self._sync_region_canvas_from_spins()

    # ────────────────────────────── 输出 ──────────────────────────────

    def burn_spec(self) -> SubtitleBurnSpec | None:
        if not self._cues:
            return None
        return SubtitleBurnSpec(cues=tuple(self._cues), style=self._current_style())

    def removal_spec(self) -> SubtitleRemovalSpec | None:
        spec = self._current_removal()
        return spec if spec.enabled else None

    def refresh_from_store(self) -> None:
        """外部替换 store 内容（如打开项目）后重建表格与样式控件。"""
        self._cues = list(self._store.document.cues)
        self._refresh_table()
        self._load_style_controls()

    def _persist(self) -> None:
        self._store.document.cues = list(self._cues)
        self._store.document.style = self._current_style()
        self._store.document.removal = self._current_removal()
        self._store.save()

    def _set_status(self, text: str, *, warn: bool = False) -> None:
        self._status.setObjectName("CaptionWarn" if warn else "Caption")
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
