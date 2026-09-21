"""主壳层：标题栏 / 模块栏 / 素材栏 / 中央工作区 / 检查器 / 底部队列条。"""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jingxu.application.composition_service import build_requests
from jingxu.domain.layers import LayerKind
from jingxu.domain.media import MediaAsset
from jingxu.domain.render import ProcessingMode, RenderSettings
from jingxu.infrastructure.audio_library import AudioLibrary
from jingxu.infrastructure.downloader import DownloadQueue, default_download_directory
from jingxu.infrastructure.encoders import default_registry
from jingxu.infrastructure.ffprobe import ProbeError, probe_media
from jingxu.infrastructure.layer_store import LayerStore
from jingxu.infrastructure.paths import data_directory
from jingxu.infrastructure.project_store import (
    CURRENT_SCHEMA_VERSION,
    PROJECT_SUFFIX,
    ProjectDocument,
    ProjectError,
    load_project,
    save_project,
)
from jingxu.infrastructure.queue import JobState, RenderJob, RenderQueue
from jingxu.infrastructure.subtitle_store import SubtitleStore
from jingxu.infrastructure.sticker_library import StickerLibrary
from jingxu.ui import icons, theme
from jingxu.ui.audio_page import AudioPage
from jingxu.ui.brand import app_icon, build_logo_widget
from jingxu.ui.composition_page import CompositionPage
from jingxu.ui.download_page import DownloadPage
from jingxu.ui.layer_page import LayerPage
from jingxu.ui.queue_page import QueuePage
from jingxu.ui.settings_page import SettingsPage
from jingxu.ui.spider_page import SpiderPage
from jingxu.ui.subtitle_page import SubtitlePage
from jingxu.ui.widgets import (
    Caption,
    CountBadge,
    Divider,
    GlyphButton,
    MaterialList,
    ModuleRail,
    PrimaryButton,
    SecondaryButton,
    SectionExpander,
    SectionHeader,
    render_svg_path,
)

MODULE_COMPOSITION = "composition"
MODULE_OVERLAYS = "overlays"
MODULE_STICKERS = "stickers"
MODULE_SUBTITLES = "subtitles"
MODULE_QUEUE = "queue"
MODULE_AUDIO = "audio"
MODULE_DOWNLOADS = "downloads"
MODULE_SPIDER = "spider"
MODULE_SETTINGS = "settings"

WINDOW_MAXIMIZE_PADDING = 8  # 最大化时补偿系统边框，避免内容贴边被裁切

MODULE_TABS = (
    ("混剪", icons.MODULE_COMPOSITION, MODULE_COMPOSITION, True),
    ("蒙版", icons.MODULE_OVERLAYS, MODULE_OVERLAYS, True),
    ("贴纸", icons.MODULE_STICKERS, MODULE_STICKERS, True),
    ("字幕", icons.MODULE_SUBTITLES, MODULE_SUBTITLES, True),
    ("音频", icons.MODULE_AUDIO, MODULE_AUDIO, True),
    ("下载", icons.MODULE_DOWNLOADS, MODULE_DOWNLOADS, True),
    ("选品", icons.MODULE_SPIDER, MODULE_SPIDER, True),
    ("队列", icons.MODULE_QUEUE, MODULE_QUEUE, True),
    ("设置", icons.MODULE_SETTINGS, MODULE_SETTINGS, True),
)

VIDEO_FILTER = "视频文件 (*.mp4 *.mov *.mkv *.avi *.flv *.wmv *.m4v *.ts);;所有文件 (*)"

PROJECT_FILTER = "镜序项目 (*.jxproj);;所有文件 (*)"

OUTPUT_RULE_TEXT = (
    "输出规则：单一来源任务默认输出到源目录下的「分镜输出」；多来源任务输出到桌面「分镜输出」。"
    "可按项目或任务自定义目录。"
)


class QueueBridge(QObject):
    """把工作线程的队列事件切回 UI 线程。"""

    event = Signal(str, object)


class TitleBar(QFrame):
    """44px 自绘标题栏：拖动移动、双击最大化。"""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.setObjectName("TitleBar")
        self.setFixedHeight(theme.TITLE_BAR_HEIGHT)
        self._window = window

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.showNormal() if self._window.isMaximized() else self._window.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class GateWell(QFrame):
    """中央取景井（唯一深色区域）：素材首帧预览、加载态与空闲水印。"""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("GateWell")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(0)

        caption = QLabel("取景井")
        caption.setObjectName("GateCaption")
        layout.addWidget(caption)
        layout.addStretch(1)

        # 预览图（选中素材后异步生成首帧；空闲时隐藏，显示水印）
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setVisible(False)
        self._has_preview = False
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignCenter)

        self._watermark = QWidget()
        watermark_layout = QVBoxLayout(self._watermark)
        watermark_layout.setContentsMargins(0, 0, 0, 0)
        watermark_layout.setSpacing(0)
        logo = QLabel("炳恒")
        logo.setStyleSheet(f"color: {theme.BRAND_BLOOM}; font-size: 30px; font-weight: 700;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        watermark_layout.addWidget(logo)
        title = QLabel("炳恒快速混剪")
        title.setObjectName("GateTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setContentsMargins(0, 16, 0, 0)
        watermark_layout.addWidget(title)
        layout.addWidget(self._watermark, alignment=Qt.AlignmentFlag.AlignCenter)

        self._caption = QLabel("监视器空闲")
        self._caption.setObjectName("GateCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self._caption)

        self._hint = QLabel("离线就绪 · 导入素材后在此预览画面")
        self._hint.setObjectName("GateCaption")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setContentsMargins(0, 3, 0, 0)
        layout.addWidget(self._hint)
        layout.addStretch(1)

    def set_idle(self, caption: str, hint: str) -> None:
        self._preview.clear()
        self._preview.setVisible(False)
        self._watermark.setVisible(True)
        self._has_preview = False
        self._caption.setText(caption)
        self._hint.setText(hint)

    def set_loading(self, caption: str = "正在生成预览…") -> None:
        self._preview.clear()
        self._preview.setVisible(False)
        self._watermark.setVisible(True)
        self._has_preview = False
        self._caption.setText(caption)
        self._hint.setText("首帧提取中，请稍候")

    def set_preview(self, pixmap: QPixmap, caption: str, hint: str) -> None:
        scaled = pixmap.scaled(
            360,
            640,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(scaled)
        self._preview.setVisible(True)
        self._watermark.setVisible(False)
        self._has_preview = True
        self._caption.setText(caption)
        self._hint.setText(hint)

    def has_preview(self) -> bool:
        return self._has_preview


def rotated_text_pixmap(text: str, color: str, *, pixel_size: int = 11) -> QPixmap:
    """渲染竖排文字（用于折叠态检查器标签）。"""
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(pixel_size)
    probe = QPixmap(1, 1)
    painter = QPainter(probe)
    painter.setFont(font)
    bounds = painter.boundingRect(0, 0, 400, 400, int(Qt.AlignmentFlag.AlignLeft), text)
    painter.end()

    pixmap = QPixmap(bounds.height() + 4, bounds.width() + 4)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.translate(pixmap.width(), 0)
    painter.rotate(90)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(2, bounds.height(), text)
    painter.end()
    return pixmap


class ShellWindow(QMainWindow):
    def __init__(self, ffmpeg: Path, ffprobe: Path, queue: RenderQueue) -> None:
        super().__init__()
        self.setWindowTitle("炳恒快速混剪")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        # 窗口/任务栏图标（.NET 版为 Assets/AppIcon.ico）。
        # 无边框窗口仍需要它，任务栏与 Alt+Tab 才会显示正确图标。
        window_icon = app_icon()
        if window_icon is not None:
            self.setWindowIcon(window_icon)
        self.resize(1600, 920)
        self.setMinimumSize(1120, 720)
        self._ffmpeg = Path(ffmpeg)
        self._ffprobe = Path(ffprobe)
        self._queue = queue
        self._materials: list[list[MediaAsset]] = [[], []]
        self._group = 0
        self._request_counter = 0
        self._queue_expanded = True
        self._inspector_expanded = True
        self._gate_generation = 0
        self._gate_preview_path: str | None = None
        self._resize_margin = 6
        self._project_path: Path | None = None
        self._project_name = ""
        self._project_created_at = ""
        self._project_read_only = False
        self._dirty = False
        self._suppress_close_prompt = False
        self._encoder_registry = default_registry(ffmpeg)
        self._audio_library = AudioLibrary()
        self._download_queue = DownloadQueue(default_download_directory())
        self._overlay_store = LayerStore(LayerKind.OVERLAY)
        self._sticker_store = LayerStore(LayerKind.STICKER)
        # 贴纸素材库与轨道分离（对齐 .NET 贴纸页）：库里放素材，轨道从库中添加。
        self._sticker_library = StickerLibrary()
        self._subtitle_store = SubtitleStore()

        bridge = QueueBridge(self)
        bridge.event.connect(self._on_queue_event)
        self._bridge = bridge
        self._queue.add_listener(lambda event, job: self._bridge.event.emit(event, job))

        self._build_ui()
        self._install_shortcuts()
        self._refresh_materials()
        self._refresh_queue_summary()
        self._sync_audio_library()
        self._sync_overlay_summary()
        self._update_project_labels()
        self._warm_encoders()

    def _sync_audio_library(self) -> None:
        self._composition_page.set_audio_library([track.path for track in self._audio_page.tracks()])

    def _sync_overlay_summary(self) -> None:
        enabled = len(self._overlay_page.enabled_layers())
        self._composition_page.set_overlay_summary(enabled)
        aspect = str(self._composition_page._aspect.currentData())
        self._overlay_page.set_canvas_aspect(aspect)
        self._sticker_page.set_canvas_aspect(aspect)

    def _select_module(self, module_id: str) -> None:
        self._module_rail.select(module_id)
        self._on_module_changed(module_id)

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("RootSurface")
        self.setCentralWidget(root)
        self._root = root

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_title_bar())
        layout.addWidget(self._build_body(), stretch=1)
        layout.addWidget(self._build_queue_bar())

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """最大化/还原时补偿系统边框内边距并切换窗口按钮字形。"""
        if event.type() == QEvent.Type.WindowStateChange:
            self._apply_window_chrome()
        super().changeEvent(event)

    def _apply_window_chrome(self) -> None:
        maximized = self.isMaximized()
        padding = WINDOW_MAXIMIZE_PADDING if maximized else 0
        if hasattr(self, "_root"):
            self._root.setContentsMargins(padding, padding, padding, padding)
        button = getattr(self, "_maximize_button", None)
        if button is not None:
            button.set_icon_path(icons.WIN_RESTORE if maximized else icons.WIN_MAXIMIZE)
            button.setToolTip("还原" if maximized else "最大化")
            button.setAccessibleName("还原窗口" if maximized else "最大化窗口")

    def _build_title_bar(self) -> QWidget:
        bar = TitleBar(self)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 0, 0)
        row.setSpacing(0)

        # 品牌 logo：优先用 .NET 版同款 AppLogo.png（对齐 ShellWindow.xaml）。
        # 资源缺失时回退到文字标记，界面功能不受影响。
        row.addWidget(build_logo_widget(size=28))
        row.addSpacing(12)
        divider = Divider(horizontal=False)
        divider.setFixedHeight(20)
        divider.setStyleSheet(f"background: {theme.LINE_DEFAULT};")
        row.addWidget(divider)
        row.addSpacing(12)

        wordmark = QLabel("炳恒快速混剪")
        wordmark.setObjectName("Wordmark")
        row.addWidget(wordmark)

        row.addStretch(1)
        self._project_label = QLabel("未打开项目")
        row.addWidget(self._project_label)
        self._save_state_label = Caption("—")
        self._save_state_label.setContentsMargins(10, 0, 0, 0)
        row.addWidget(self._save_state_label)
        row.addStretch(1)

        offline = QHBoxLayout()
        offline.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {theme.BRAND_BLOOM}; font-size: 9px;")
        offline.addWidget(dot)
        offline.addWidget(Caption("离线"))
        offline.addSpacing(10)
        row.addLayout(offline)

        minimize = GlyphButton(icons.WIN_MINIMIZE)
        minimize.clicked.connect(self.showMinimized)
        row.addWidget(minimize)

        maximize = GlyphButton(icons.WIN_MAXIMIZE)
        maximize.clicked.connect(self._toggle_maximized)
        row.addWidget(maximize)
        self._maximize_button = maximize

        close = GlyphButton(icons.WIN_CLOSE, close=True)
        close.clicked.connect(self.close)
        row.addWidget(close)
        return bar

    def _build_body(self) -> QWidget:
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("Rail")
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        self._module_rail = ModuleRail(MODULE_TABS)
        self._module_rail.selected_changed.connect(self._on_module_changed)
        rail_layout.addWidget(self._module_rail)
        row.addWidget(rail)

        row.addWidget(self._build_material_rail())
        row.addWidget(self._build_center(), stretch=1)
        row.addWidget(self._build_inspector())
        return body

    def _build_material_rail(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SidePanel")
        panel.setFixedWidth(theme.MATERIAL_RAIL_WIDTH)
        panel.setStyleSheet(f"border-right: 1px solid {theme.LINE_DEFAULT};")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"border-bottom: 1px solid {theme.LINE_DEFAULT};")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 14, 16, 14)
        title = QLabel("素材")
        title.setObjectName("Title")
        header_row.addWidget(title)
        header_row.addStretch(1)
        self._material_count = CountBadge("0")
        header_row.addWidget(self._material_count)
        layout.addWidget(header)

        self._material_list = MaterialList()
        self._material_list.files_dropped.connect(self._add_materials)
        self._material_list.currentRowChanged.connect(self._on_material_selected)
        layout.addWidget(self._material_list, stretch=1)

        self._material_empty = QWidget()
        empty_layout = QVBoxLayout(self._material_empty)
        empty_layout.setContentsMargins(24, 0, 24, 0)
        empty_layout.addStretch(1)
        mark = QLabel()
        mark.setPixmap(render_svg_path(icons.MODULE_COMPOSITION, 30, theme.LINE_STRONG, stroke_width=1.4))
        empty_layout.addWidget(mark, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_title = QLabel("暂无素材")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setStyleSheet("font-size: 12px; font-weight: 600;")
        empty_title.setContentsMargins(0, 10, 0, 4)
        empty_layout.addWidget(empty_title)
        hint = Caption("暂无素材。拖放视频到此处，或在混剪模块中导入以添加素材。")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint)
        empty_layout.addStretch(1)
        layout.addWidget(self._material_empty, stretch=1)
        return panel

    def _build_center(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._gate_well = GateWell()
        self._gate_holder = QWidget()
        gate_layout = QVBoxLayout(self._gate_holder)
        gate_layout.setContentsMargins(16, 16, 16, 8)
        gate_layout.addWidget(self._gate_well)
        layout.addWidget(self._gate_holder, stretch=13)

        self._composition_page = CompositionPage()
        self._composition_page.import_requested.connect(self._choose_materials)
        self._composition_page.clear_requested.connect(self._clear_materials)
        self._composition_page.enqueue_requested.connect(self._enqueue)
        self._composition_page.workspace_changed.connect(self._switch_group)
        self._composition_page._material_list.currentRowChanged.connect(self._on_page_material_selected)

        self._queue_page = QueuePage(self._queue)
        self._audio_page = AudioPage(self._audio_library, self._ffprobe)
        self._audio_page.library_changed.connect(self._sync_audio_library)
        self._download_page = DownloadPage(self._download_queue)
        self._download_page.files_downloaded.connect(self._add_materials)
        # 选品抓取是独立模块，但界面用主程序自己的控件与主题（不再内嵌爬虫 GUI）。
        self._spider_page = SpiderPage()
        self._spider_page.videos_discovered.connect(self._on_spider_videos)
        self._settings_page = SettingsPage(self._ffmpeg, self._ffprobe, self._encoder_registry, self._queue)
        self._overlay_page = LayerPage(
            self._overlay_store,
            title="蒙版模板",
            file_filter="蒙版视频 (*.mp4 *.mov *.mkv *.webm *.png);;所有文件 (*)",
            hint="蒙版素材叠在成片之上：设置出现时段、中心位置与宽度；黑底蒙版可勾选「黑底抠除」。",
            ffmpeg=self._ffmpeg,
            base_video_provider=self._base_material,
        )
        self._overlay_page.layers_changed.connect(self._refresh_layer_summary)
        self._overlay_page.layers_changed.connect(self._sync_overlay_summary)
        self._overlay_page.layers_changed.connect(self._mark_dirty)
        self._composition_page.overlay_module_requested.connect(
            lambda: self._select_module(MODULE_OVERLAYS)
        )
        self._sticker_page = LayerPage(
            self._sticker_store,
            title="贴纸轨道",
            file_filter="贴纸素材 (*.png *.webp *.gif *.mp4 *.mov);;所有文件 (*)",
            hint="贴纸素材来自上方「贴纸素材库」；视频贴纸会循环播放并只在时段内显示。",
            ffmpeg=self._ffmpeg,
            base_video_provider=self._base_material,
            sticker_library=self._sticker_library,
        )
        self._sticker_page.layers_changed.connect(self._refresh_layer_summary)
        self._sticker_page.layers_changed.connect(self._mark_dirty)
        self._subtitle_page = SubtitlePage(self._subtitle_store, self._ffmpeg)

        self._module_stack = QStackedWidget()
        for page in (
            self._composition_page,
            self._overlay_page,
            self._sticker_page,
            self._subtitle_page,
            self._audio_page,
            self._download_page,
            self._spider_page,
            self._queue_page,
            self._settings_page,
        ):
            self._module_stack.addWidget(page)
        layout.addWidget(self._module_stack, stretch=10)
        return center

    def _build_inspector(self) -> QWidget:
        self._inspector = QFrame()
        self._inspector.setObjectName("SidePanel")
        self._inspector.setStyleSheet(f"border-left: 1px solid {theme.LINE_DEFAULT};")

        self._inspector_stack = QStackedWidget()
        self._inspector_stack.addWidget(self._build_inspector_expanded())
        self._inspector_stack.addWidget(self._build_inspector_collapsed())

        layout = QVBoxLayout(self._inspector)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._inspector_stack)
        self._inspector.setFixedWidth(theme.INSPECTOR_WIDTH)
        return self._inspector

    def _build_inspector_expanded(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"border-bottom: 1px solid {theme.LINE_DEFAULT};")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 12, 16, 12)
        header_row.addWidget(SectionHeader("属性"))
        header_row.addStretch(1)
        collapse = GlyphButton(icons.UI_COLLAPSE, icon_size=16, stroke=1.4, button_size=(28, 28))
        collapse.clicked.connect(self._toggle_inspector)
        header_row.addWidget(collapse)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 4, 16, 8)
        body_layout.setSpacing(0)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 8)
        workspace_layout.setSpacing(6)
        project_row, self._inspector_project_label = self._info_row("项目", "未打开项目")
        workspace_layout.addLayout(project_row)
        save_row, self._inspector_save_label = self._info_row("保存", "—")
        workspace_layout.addLayout(save_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        new_button = SecondaryButton("新建项目")
        new_button.clicked.connect(lambda: self.new_project())
        button_row.addWidget(new_button)
        open_button = SecondaryButton("打开项目…")
        open_button.clicked.connect(lambda: self.open_project())
        button_row.addWidget(open_button)
        save_button = PrimaryButton("保存项目…")
        save_button.clicked.connect(lambda: self.save_project())
        button_row.addWidget(save_button)
        button_row.addStretch(1)
        workspace_layout.addLayout(button_row)
        body_layout.addWidget(SectionExpander("工作区", workspace))

        output = QWidget()
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(0, 0, 0, 8)
        output_layout.addWidget(Caption(OUTPUT_RULE_TEXT))
        body_layout.addWidget(SectionExpander("输出", output))

        data = QWidget()
        data_layout = QVBoxLayout(data)
        data_layout.setContentsMargins(0, 0, 0, 8)
        data_path = QLabel(str(data_directory()))
        data_path.setObjectName("Mono")
        data_path.setWordWrap(True)
        data_layout.addWidget(data_path)
        body_layout.addWidget(SectionExpander("数据目录", data))

        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

        footer = QFrame()
        footer.setStyleSheet(f"border-top: 1px solid {theme.LINE_DEFAULT};")
        footer_row = QVBoxLayout(footer)
        footer_row.setContentsMargins(16, 12, 16, 12)
        open_button = PrimaryButton("打开数据目录")
        open_button.clicked.connect(lambda: self._open_path(data_directory()))
        footer_row.addWidget(open_button)
        layout.addWidget(footer)
        return content

    def _build_inspector_collapsed(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._make_collapsed_expand_button(), alignment=Qt.AlignmentFlag.AlignHCenter)

        label = QLabel()
        label.setPixmap(rotated_text_pixmap("属性", theme.INK_MUTED))
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return content

    def _make_collapsed_expand_button(self) -> GlyphButton:
        button = GlyphButton(icons.UI_EXPAND_LEFT, icon_size=14, stroke=1.4, button_size=(30, 30))
        button.clicked.connect(self._toggle_inspector)
        return button

    @staticmethod
    def _info_row(label: str, value: str) -> tuple[QHBoxLayout, QLabel]:
        row = QHBoxLayout()
        row.setSpacing(0)
        caption = Caption(label)
        caption.setFixedWidth(56)
        row.addWidget(caption)
        value_label = QLabel(value)
        row.addWidget(value_label)
        row.addStretch(1)
        return row, value_label

    def _build_queue_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("QueueBar")
        self._queue_bar = bar

        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(theme.QUEUE_COLLAPSED_HEIGHT)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 0, 16, 0)
        header_row.setSpacing(14)
        header_row.addWidget(SectionHeader("任务队列"))
        self._queue_summary = Caption("队列空闲 · 暂无任务")
        self._queue_summary.setWordWrap(False)
        header_row.addWidget(self._queue_summary)
        header_row.addStretch(1)
        self._queue_toggle = GlyphButton(icons.UI_CHEVRON, icon_size=16, stroke=1.4, button_size=(30, 30))
        self._queue_toggle.clicked.connect(lambda: self._set_queue_expanded(not self._queue_expanded))
        header_row.addWidget(self._queue_toggle)
        layout.addWidget(header)

        self._queue_panel = QFrame()
        self._queue_panel.setObjectName("PanelMuted")
        panel_row = QHBoxLayout(self._queue_panel)
        panel_row.setContentsMargins(14, 10, 14, 10)
        panel_row.setSpacing(10)

        icon = QLabel()
        icon.setPixmap(render_svg_path(icons.STATUS_DRAFT, 16, theme.INK_MUTED, stroke_width=2))
        panel_row.addWidget(icon, alignment=Qt.AlignmentFlag.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(6)
        self._queue_detail = QLabel("队列空闲 · 暂无任务")
        column.addWidget(self._queue_detail)
        self._queue_progress = QProgressBar()
        self._queue_progress.setRange(0, 100)
        self._queue_progress.setFixedHeight(5)
        self._queue_progress.setTextVisible(False)
        self._queue_progress.setFixedWidth(220)
        self._queue_progress.setVisible(False)
        column.addWidget(self._queue_progress)
        panel_row.addLayout(column)

        queue_hint = Caption("· 完成编排后加入队列，可在此跟踪阶段、进度并取消或重试。")
        queue_hint.setWordWrap(False)
        panel_row.addWidget(queue_hint)
        panel_row.addStretch(1)

        wrapper = QWidget()
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(16, 0, 16, 12)
        wrapper_layout.addWidget(self._queue_panel)
        layout.addWidget(wrapper)

        bar.setFixedHeight(theme.QUEUE_HEIGHT)
        return bar

    # ────────────────────────────── 素材 ──────────────────────────────

    @property
    def _assets(self) -> list[MediaAsset]:
        return self._materials[self._group]

    def _switch_group(self, group: int) -> None:
        if group == self._group:
            return
        self._group = group
        self._refresh_materials()

    def _choose_materials(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择视频素材", "", VIDEO_FILTER)
        if files:
            self._add_materials(files)

    def _add_materials(self, paths: list[str]) -> None:
        added = 0
        failures: list[str] = []
        known = {asset.path for asset in self._assets}

        for raw_path in paths:
            path = Path(raw_path)
            if path in known:
                continue
            try:
                asset = probe_media(path, self._ffprobe)
            except ProbeError as error:
                failures.append(f"{path.name}：{error}")
                continue
            self._assets.append(asset)
            known.add(path)
            added += 1

        if added:
            self._refresh_materials()
            self._composition_page.set_status(f"已添加 {added} 个素材，共 {len(self._assets)} 个。")
            self._mark_dirty()
        if failures:
            self._composition_page.set_status("；".join(failures[:3]), warn=True)
            QMessageBox.warning(self, "部分素材无法导入", "\n".join(failures[:8]))

    def _clear_materials(self) -> None:
        if not self._assets:
            return
        self._assets.clear()
        self._refresh_materials()
        self._composition_page.set_status("已清空当前商品组素材。")
        self._mark_dirty()

    def _refresh_materials(self) -> None:
        assets = self._assets
        self._material_list.blockSignals(True)
        self._material_list.clear()
        for index, asset in enumerate(assets, start=1):
            item = QListWidgetItem(
                f"{asset.display_name}\n{index:02d} · {asset.duration_text} · {asset.resolution_text}"
            )
            item.setToolTip(str(asset.path))
            self._material_list.addItem(item)
        self._material_list.blockSignals(False)

        self._material_count.setText(str(len(assets)))
        self._material_empty.setVisible(not assets)
        self._material_list.setVisible(bool(assets))

        self._composition_page.set_materials(assets)
        self._sync_subtitle_source()
        if assets:
            total = sum(asset.duration for asset in assets)
            minutes, seconds = divmod(int(round(total)), 60)
            self._gate_well.set_idle(
                f"{len(assets)} 个片段 · 预计时长 {minutes:02d}:{seconds:02d}",
                "设置编排与画幅后点击「加入队列」开始渲染。",
            )
            # 导入后自动为当前素材生成首帧预览（后台线程，不阻塞界面）。
            self._refresh_gate_preview()
        else:
            self._gate_well.set_idle("监视器空闲", "离线就绪 · 导入素材后在此预览画面")

    def _base_material(self) -> MediaAsset | None:
        """合成预览的基准素材：当前商品组第一个素材。"""
        return self._assets[0] if self._assets else None

    def _enabled_layers(self) -> list:
        """蒙版在前、贴纸在后（叠加顺序与列表一致）；蒙版开关关闭时不含蒙版层。"""
        overlays = self._overlay_page.enabled_layers() if self._composition_page.overlay_included() else []
        return [*overlays, *self._sticker_page.enabled_layers()]

    def _refresh_layer_summary(self) -> None:
        overlays = len(self._overlay_page.enabled_layers())
        stickers = len(self._sticker_page.enabled_layers())
        self._gate_well.set_idle(
            f"{len(self._assets)} 个片段 · 预计时长 "
            f"{self._duration_text()}",
            f"启用图层：蒙版 {overlays} 个 · 贴纸 {stickers} 个",
        )

    def _duration_text(self) -> str:
        total = sum(asset.duration for asset in self._assets)
        minutes, seconds = divmod(int(round(total)), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _on_material_selected(self, row: int) -> None:
        self._composition_page.select_material(row)
        self._sync_subtitle_source()
        self._refresh_gate_preview()

    def _refresh_gate_preview(self) -> None:
        """取景井首帧预览：选中素材后在后台提取一帧（带代际守卫与临时文件清理）。"""
        asset = self._base_material()
        if asset is None:
            self._gate_well.set_idle("监视器空闲", "离线就绪 · 导入素材后在此预览画面")
            return

        self._gate_generation += 1
        generation = self._gate_generation
        width, height = self._composition_page.canvas_size()
        self._gate_well.set_loading()

        def work() -> None:
            import tempfile

            from jingxu.infrastructure.frame_preview import FramePreviewError, render_composite_frame

            directory = Path(tempfile.gettempdir()) / "jingxu-gate-preview"
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"gate-{asset.asset_id or generation}.jpg"
            try:
                render_composite_frame(
                    self._ffmpeg,
                    asset,
                    (),
                    RenderSettings(width=width, height=height, fps=30),
                    target,
                    at_seconds=0.0,
                )
            except (FramePreviewError, OSError, ValueError) as error:
                self._bridge.event.emit("gate-preview-failed", (generation, str(error)))
                return
            self._bridge.event.emit("gate-preview", (generation, str(target)))

    def _on_gate_preview(self, generation: int, path: str) -> None:
        """收到首帧预览：丢弃过期结果（代际守卫）并把旧图清理掉。"""
        if generation != self._gate_generation:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
            return

        previous = self._gate_preview_path
        if previous and previous != path:
            try:
                Path(previous).unlink(missing_ok=True)
            except OSError:
                pass

        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._gate_well.set_idle("预览不可用", "无法读取首帧，请检查素材文件")
            return
        self._gate_preview_path = path
        asset = self._base_material()
        name = asset.display_name if asset is not None else ""
        self._gate_well.set_preview(pixmap, f"预览：{name}", "选中素材的首帧（随成片画幅适配）")

    def _on_gate_preview_failed(self, generation: int, message: str) -> None:
        if generation != self._gate_generation:
            return
        self._gate_well.set_idle("预览不可用", message[:80])

    def _sync_subtitle_source(self) -> None:
        """把当前选中的素材同步给字幕实验室（识别对象）。"""
        source = None
        row = self._material_list.currentRow()
        if 0 <= row < len(self._assets):
            source = self._assets[row].path
        elif self._assets:
            source = self._assets[0].path
        self._subtitle_page.set_source_material(source)

    def _on_page_material_selected(self, row: int) -> None:
        if row != self._material_list.currentRow():
            self._material_list.setCurrentRow(row)

    # ────────────────────────────── 项目 ──────────────────────────────

    def _install_shortcuts(self) -> None:
        save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        save_shortcut.activated.connect(lambda: self.save_project())
        open_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        open_shortcut.activated.connect(lambda: self.open_project())

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_project_labels()

    def _update_project_labels(self) -> None:
        name = self._project_name or "未打开项目"
        self._project_label.setText(name)
        self._inspector_project_label.setText(name)
        if self._project_read_only:
            state = "只读（更高版本）"
        elif self._dirty:
            state = "● 未保存"
        elif not self._project_name:
            state = "—"
        else:
            state = "已保存"
        self._save_state_label.setText(state)
        self._inspector_save_label.setText(state)
        self.setWindowTitle(f"炳恒快速混剪 — {self._project_name}" if self._project_name else "炳恒快速混剪")

    def _collect_project_document(self, name: str | None = None) -> ProjectDocument:
        """把当前界面状态收拢为项目文档（不落盘）。"""
        recent_jobs = tuple(
            {
                "name": job.display_name,
                "state": job.state.value,
                "output_path": str(job.output_path),
                "message": job.message,
            }
            for job in self._queue.jobs[-50:]
        )
        state = self._composition_page.project_state()
        return ProjectDocument(
            schema_version=CURRENT_SCHEMA_VERSION,
            name=name or self._project_name or "未命名项目",
            groups=(
                tuple(str(asset.path) for asset in self._materials[0]),
                tuple(str(asset.path) for asset in self._materials[1]),
            ),
            output_directory=str(state.get("output_directory") or ""),
            composition=dict(state.get("composition") or {}),
            overlays=tuple(self._overlay_store.export_layers()),
            stickers=tuple(self._sticker_store.export_layers()),
            subtitles=self._subtitle_store.export_document(),
            recent_jobs=recent_jobs,
            created_at=self._project_created_at,
            read_only=self._project_read_only,
        )

    def _apply_project(self, document: ProjectDocument) -> int:
        """用项目文档覆盖界面；返回素材缺失或无法读取的数量。"""
        self._project_name = document.name or "未命名项目"
        self._project_created_at = document.created_at
        self._project_read_only = bool(document.read_only)

        self._overlay_store.import_layers(list(document.overlays))
        self._sticker_store.import_layers(list(document.stickers))
        self._subtitle_store.import_document(dict(document.subtitles))
        self._overlay_page.refresh_from_store()
        self._sticker_page.refresh_from_store()
        self._subtitle_page.refresh_from_store()

        failures = 0
        for index in range(2):
            entries = document.groups[index] if index < len(document.groups) else ()
            assets: list[MediaAsset] = []
            for raw_path in entries:
                path = Path(str(raw_path))
                if not path.is_file():
                    failures += 1
                    continue
                try:
                    assets.append(probe_media(path, self._ffprobe))
                except ProbeError:
                    failures += 1
            self._materials[index] = assets
        self._refresh_materials()

        self._composition_page.apply_project_state(
            {
                "composition": dict(document.composition or {}),
                "output_directory": document.output_directory,
            }
        )
        self._sync_overlay_summary()
        self._sync_subtitle_source()
        self._request_counter = 0
        self._update_project_labels()
        return failures

    def new_project(self) -> None:
        """新建空白项目（默认名「未命名项目」，不弹输入框）。"""
        self._apply_project(ProjectDocument())
        self._project_path = None
        self._project_read_only = False
        self._dirty = False
        self._update_project_labels()
        self._composition_page.set_status("已新建项目。")

    def open_project(self, path: Path | None = None) -> bool:
        """打开项目；``path`` 为空时弹出文件对话框。"""
        target = Path(path) if path is not None else self._choose_open_path()
        if target is None:
            return False
        try:
            document = load_project(target)
        except ProjectError as error:
            self._composition_page.set_status(str(error), warn=True)
            if path is None:
                QMessageBox.warning(self, "无法打开项目", str(error))
            return False

        failures = self._apply_project(document)
        self._project_path = target
        self._project_read_only = bool(document.read_only)
        self._dirty = False
        self._update_project_labels()
        message = f"已打开项目：{document.name}"
        if document.read_only:
            message += "（由更高版本保存，只读打开，保存时请另存为）"
        elif failures:
            message += f"；{failures} 个素材缺失或无法读取"
        self._composition_page.set_status(message, warn=bool(failures))
        return True

    def save_project(self, path: Path | None = None) -> bool:
        """保存项目；``path`` 为空时弹出文件对话框。只读项目拒绝覆盖原文件。"""
        target = Path(path) if path is not None else self._choose_save_path()
        if target is None:
            return False
        if target.suffix.lower() != PROJECT_SUFFIX:
            target = target.with_name(target.name + PROJECT_SUFFIX)

        try:
            document = self._collect_project_document()
        except ValueError as error:
            self._composition_page.set_status(f"无法保存项目：{error}", warn=True)
            return False

        try:
            saved = save_project(target, document, source_path=self._project_path)
        except ProjectError as error:
            self._update_project_labels()
            self._composition_page.set_status(str(error), warn=True)
            if path is None:
                QMessageBox.warning(self, "无法保存项目", str(error))
            return False

        self._project_path = target
        self._project_name = saved.name
        self._project_created_at = saved.created_at
        self._project_read_only = False
        self._dirty = False
        self._update_project_labels()
        self._composition_page.set_status(f"已保存项目：{target.name}")
        return True

    def _choose_open_path(self) -> Path | None:
        start = str(self._project_path.parent) if self._project_path else str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(self, "打开项目", start, PROJECT_FILTER)
        return Path(selected) if selected else None

    def _choose_save_path(self) -> Path | None:
        if self._project_path is not None:
            start = str(self._project_path)
        else:
            start = str(Path.home() / f"{self._project_name or '未命名项目'}{PROJECT_SUFFIX}")
        selected, _ = QFileDialog.getSaveFileName(self, "保存项目", start, PROJECT_FILTER)
        return Path(selected) if selected else None

    # ────────────────────────────── 渲染 ──────────────────────────────

    def _enqueue(self) -> None:
        if not self._assets:
            QMessageBox.information(self, "没有素材", "请先导入至少一个视频素材。")
            return

        try:
            draft = replace(
                self._composition_page.draft(),
                layers=tuple(self._enabled_layers()),
                subtitles=self._subtitle_page.burn_spec(),
                removal=self._subtitle_page.removal_spec(),
                # 「随机贴纸库」：开启后每条成片从贴纸素材库确定性替换轨道素材
                # （对齐 .NET StickerEditorViewModel.TryBuildEnabledTracksForPlan）。
                randomize_sticker_library=self._sticker_page.random_library_enabled,
                sticker_library=tuple(self._sticker_library.sources),
            )
            subtitle_issues = self._subtitle_page.timeline_issues()
            if subtitle_issues:
                self._composition_page.set_status(subtitle_issues[0], warn=True)
                return
            requests = build_requests(
                assets=self._assets,
                draft=draft,
                output_directory=self._composition_page.output_directory(),
                start_index=self._request_counter + 1,
                pool=self._materials[self._group],
            )
        except ValueError as error:
            self._composition_page.set_status(str(error), warn=True)
            return

        for request in requests:
            self._queue.enqueue(request)
        self._request_counter += len(requests)

        if len(requests) == 1:
            message = f"已加入队列：{requests[0].output_path.name}"
        else:
            message = f"已加入 {len(requests)} 条成片：{requests[0].output_path.name} …"
        self._composition_page.set_status(message)
        self._set_queue_expanded(True)
        self._mark_dirty()

    # ────────────────────────────── 队列事件 ──────────────────────────────

    def _on_queue_event(self, event: str, job: RenderJob) -> None:
        if event == "encoder-ready":
            choice, note = job  # 事件负载为 (EncoderChoice, note)
            self._composition_page.set_processing_note(f"{note}自动模式将使用：{choice.label}。")
            return
        if event == "gate-preview":
            generation, path = job  # 事件负载为 (generation, path)
            self._on_gate_preview(int(generation), str(path))
            return
        if event == "gate-preview-failed":
            generation, message = job
            self._on_gate_preview_failed(int(generation), str(message))
            return
        self._queue_page.refresh()
        self._refresh_queue_summary()

    def _refresh_queue_summary(self) -> None:
        jobs = self._queue.jobs
        active = [job for job in jobs if job.is_active]
        finished = [job for job in jobs if not job.is_active]
        failed = [job for job in jobs if job.state is JobState.FAILED]

        if not jobs:
            self._queue_summary.setText("队列空闲 · 暂无任务")
            self._queue_detail.setText("队列空闲 · 暂无任务")
            self._queue_progress.setVisible(False)
        else:
            self._queue_summary.setText(
                f"共 {len(jobs)} 个 · 进行中 {len(active)} · 已结束 {len(finished)} · 失败 {len(failed)}"
            )
            running = next((job for job in jobs if job.state is JobState.RUNNING), None)
            if running is not None:
                self._queue_detail.setText(f"渲染中：{running.display_name} · {running.percent:.0f}%")
                self._queue_progress.setVisible(True)
                self._queue_progress.setValue(int(running.percent))
            else:
                last = jobs[-1]
                suffix = f" · {last.message}" if last.message else ""
                self._queue_detail.setText(
                    f"最近任务：{last.display_name} · {last.state.display_text}{suffix}"
                )
                self._queue_progress.setVisible(False)

    def _set_queue_expanded(self, expanded: bool) -> None:
        self._queue_expanded = expanded
        self._queue_panel.setVisible(expanded)
        self._queue_bar.setFixedHeight(theme.QUEUE_HEIGHT if expanded else theme.QUEUE_COLLAPSED_HEIGHT)
        self._refresh_queue_summary()

    # ────────────────────────────── 模块切换 ──────────────────────────────

    def _on_module_changed(self, module_id: str) -> None:
        pages = {
            MODULE_COMPOSITION: self._composition_page,
            MODULE_OVERLAYS: self._overlay_page,
            MODULE_STICKERS: self._sticker_page,
            MODULE_SUBTITLES: self._subtitle_page,
            MODULE_QUEUE: self._queue_page,
            MODULE_AUDIO: self._audio_page,
            MODULE_DOWNLOADS: self._download_page,
            MODULE_SPIDER: self._spider_page,
            MODULE_SETTINGS: self._settings_page,
        }
        page = pages.get(module_id)
        if page is None:
            return

        is_composition = module_id == MODULE_COMPOSITION
        self._gate_holder.setVisible(is_composition)
        self._module_stack.setCurrentWidget(page)
        if module_id == MODULE_QUEUE:
            self._queue_page.refresh()

    def _on_spider_videos(self, urls: list[str]) -> None:
        """选品结果 → 批量下载：入队并切到下载模块。"""
        count = self._download_page.enqueue_urls(list(urls))
        if count:
            self._select_module(MODULE_DOWNLOADS)
            self._composition_page.set_status(f"选品结果已加入 {count} 个下载任务。")

    def _warm_encoders(self) -> None:
        """后台预热硬件编码器探针，并把结论显示在混剪页。"""

        def work() -> None:
            choice = self._encoder_registry.resolve(ProcessingMode.AUTO)
            note = self._encoder_registry.note(ProcessingMode.AUTO)
            self._bridge.event.emit("encoder-ready", (choice, note))

        threading.Thread(target=work, name="jingxu-encoder-warmup", daemon=True).start()

    def _toggle_inspector(self) -> None:
        self._inspector_expanded = not self._inspector_expanded
        self._inspector_stack.setCurrentIndex(0 if self._inspector_expanded else 1)
        self._inspector.setFixedWidth(theme.INSPECTOR_WIDTH if self._inspector_expanded else 44)

    # ────────────────────────────── 窗口行为 ──────────────────────────────

    def _toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges is not None:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def _edges_at(self, position):  # noqa: ANN001, ANN202
        margin = self._resize_margin
        edges = Qt.Edge(0)
        if position.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - margin:
            edges |= Qt.Edge.RightEdge
        if position.y() <= margin:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - margin:
            edges |= Qt.Edge.BottomEdge
        # 注意：PySide6 6.x 里 Qt.Edge 是 Flag 枚举，**不能直接 int()**，
        # 否则每次鼠标左键按下都会抛
        # 「TypeError: int() argument must be ... not 'Edge'」，
        # 表现为窗口边缘拖拽调整大小失效并刷满崩溃日志。用 .value 取数值。
        return edges if int(edges.value) else None

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._dirty and not self._suppress_close_prompt:
            answer = QMessageBox.question(
                self,
                "项目尚未保存",
                "当前项目有未保存的更改，关闭前要保存吗？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save and not self.save_project():
                event.ignore()
                return
        self._queue.stop()
        self._download_queue.stop()
        # 选品抓取与扫码登录都跑在子进程里，必须一并收掉。
        self._spider_page.shutdown()
        # 设置页有后台探测线程（编码器/运行时）；页面销毁后它会向已释放的信号源
        # emit 并抛「Signal source has been deleted」——实测关闭窗口必现。
        self._settings_page.shutdown()
        super().closeEvent(event)
