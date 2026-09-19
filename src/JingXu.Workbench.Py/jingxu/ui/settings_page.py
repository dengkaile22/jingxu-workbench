"""设置页：运行时诊断、硬件编码器、数据目录与维护。"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jingxu import __version__
from jingxu.infrastructure.diagnostics import (
    RuntimeInfo,
    cleanup_workspace,
    collect_runtime_info,
    runtime_tesseract,
)
from jingxu.infrastructure.encoders import EncoderRegistry
from jingxu.infrastructure.ffmpeg_runner import PART_SUFFIX
from jingxu.infrastructure.paths import data_directory
from jingxu.infrastructure.queue import RenderQueue
from jingxu.infrastructure.whisper import find_whisper
from jingxu.ui import theme
from jingxu.ui.widgets import Caption, PrimaryButton, SecondaryButton, SectionExpander


class SettingsBridge(QObject):
    ready = Signal(object)


class SettingsPage(QWidget):
    """设置与诊断（编码器探针在后台线程执行）。"""

    def __init__(self, ffmpeg: Path, ffprobe: Path, registry: EncoderRegistry, queue: RenderQueue) -> None:
        super().__init__()
        self._ffmpeg = Path(ffmpeg)
        self._ffprobe = Path(ffprobe)
        self._registry = registry
        self._queue = queue

        bridge = SettingsBridge(self)
        bridge.ready.connect(self._apply_runtime_info)
        self._bridge = bridge

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

        title = QLabel("设置")
        title.setObjectName("Title")
        layout.addWidget(title)
        subtitle = Caption("运行时诊断、硬件编码与本地数据维护。编码器探针会执行一次极小的试编码，稍等几秒。")
        subtitle.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(subtitle)

        layout.addSpacing(16)
        layout.addWidget(self._build_application_section())
        layout.addSpacing(4)
        layout.addWidget(self._build_concurrency_section())
        layout.addSpacing(4)
        layout.addWidget(self._build_runtime_section())
        layout.addSpacing(4)
        layout.addWidget(self._build_encoder_section())
        layout.addSpacing(4)
        layout.addWidget(self._build_maintenance_section())
        layout.addSpacing(4)
        layout.addWidget(self._build_about_section())
        layout.addStretch(1)

        self._load_runtime_info()

    # ────────────────────────────── 区块 ──────────────────────────────

    def _build_application_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)
        layout.addWidget(Caption("版本"))
        layout.addWidget(QLabel(__version__))
        layout.addWidget(Caption("数据目录"))
        self._data_label = self._mono_label(str(data_directory()))
        layout.addWidget(self._data_label)
        layout.addWidget(Caption("完全离线：不上传素材，不联网校验。"))
        return SectionExpander("应用", body)

    def _build_concurrency_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(Caption("同时渲染任务数"), alignment=Qt.AlignmentFlag.AlignVCenter)
        self._concurrency = QSpinBox()
        self._concurrency.setRange(1, 4)
        self._concurrency.setValue(self._queue.max_concurrency)
        self._concurrency.valueChanged.connect(self._on_concurrency_changed)
        row.addWidget(self._concurrency)
        row.addStretch(1)
        layout.addLayout(row)

        self._concurrency_status = Caption(
            "全屏分屏或大画幅任务会自动串行执行，避免同时占用过多内存与硬件编码器。"
        )
        layout.addWidget(self._concurrency_status)
        return SectionExpander("渲染并发", body)

    def _build_runtime_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)
        self._ffmpeg_label = self._mono_label(str(self._ffmpeg))
        self._ffprobe_label = self._mono_label(str(self._ffprobe))
        self._version_label = Caption("正在读取版本…")
        self._component_label = Caption("正在检测组件…")
        layout.addWidget(Caption("FFmpeg"))
        layout.addWidget(self._ffmpeg_label)
        layout.addWidget(Caption("FFprobe"))
        layout.addWidget(self._ffprobe_label)
        layout.addWidget(self._version_label)
        layout.addWidget(Caption("外部运行时解析顺序"))
        layout.addWidget(
            Caption("1. 应用目录 runtime/ · 2. 用户指定目录 · 3. 系统 PATH（Whisper 与 Tesseract 为可选组件）")
        )
        layout.addWidget(self._component_label)

        layout.addWidget(Caption("组件清单（runtime-manifest.json）"))
        self._component_table = QTableWidget(0, 4)
        self._component_table.setHorizontalHeaderLabels(["组件", "状态", "来源", "路径 / 建议"])
        self._component_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._component_table.setColumnWidth(0, 120)
        self._component_table.setColumnWidth(1, 90)
        self._component_table.setColumnWidth(2, 120)
        self._component_table.setMaximumHeight(170)
        self._component_table.verticalHeader().setVisible(False)
        self._component_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._component_table)

        refresh = SecondaryButton("重新检测")
        refresh.clicked.connect(self._load_runtime_info)
        layout.addWidget(refresh, alignment=Qt.AlignmentFlag.AlignLeft)
        return SectionExpander("运行时诊断", body)

    def _load_component_table(self) -> None:
        """按运行时清单填充逐组件诊断表（必需组件缺失时给出建议操作）。"""
        try:
            from jingxu.infrastructure.runtime_manifest import diagnose_components, load_manifest
        except Exception:  # noqa: BLE001 - 诊断不可用不应阻断设置页
            return

        manifest = load_manifest()
        statuses = diagnose_components(manifest)
        self._component_table.setRowCount(len(statuses))
        for row, status in enumerate(statuses):
            name = status.display_name + ("" if status.is_required else "（可选）")
            state = "已就绪" if status.is_available else ("缺失" if status.is_required else "未安装")
            detail = status.resolved_path or status.suggested_action or status.message
            for column, text in enumerate((name, state, status.source or "-", detail)):
                item = QTableWidgetItem(text)
                if column == 1 and not status.is_available and status.is_required:
                    item.setForeground(QColor(theme.STATUS_FAILED))
                self._component_table.setItem(row, column, item)
        if manifest.issues and self._component_label.text():
            self._component_label.setText(self._component_label.text() + "；清单提示：" + manifest.issues[0])

    def _build_encoder_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)
        self._encoder_available = Caption("正在探测硬件编码器…")
        self._encoder_resolved = Caption("")
        layout.addWidget(Caption("可用编码器"))
        layout.addWidget(self._encoder_available)
        layout.addWidget(Caption("处理器选择"))
        layout.addWidget(self._encoder_resolved)
        return SectionExpander("硬件编码", body)

    def _build_maintenance_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)

        layout.addWidget(Caption("数据目录（配置、音频库、结果快照）"))
        self._data_label = self._mono_label("")
        layout.addWidget(self._data_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        open_button = PrimaryButton("打开数据目录")
        open_button.clicked.connect(self._open_data_directory)
        buttons.addWidget(open_button)

        cleanup_button = SecondaryButton("清理临时文件")
        cleanup_button.clicked.connect(self._cleanup_temp)
        buttons.addWidget(cleanup_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._cleanup_result = Caption("")
        layout.addWidget(self._cleanup_result)
        return SectionExpander("维护", body)

    def _build_about_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)
        self._platform_label = Caption("")
        layout.addWidget(Caption(f"炳恒快速混剪 · Python 跨平台版 {__version__}"))
        layout.addWidget(self._platform_label)
        layout.addWidget(Caption("与 .NET 版共用 FFmpeg 语义与业务规则；离线运行，不上传任何素材。"))
        return SectionExpander("关于", body)

    # ────────────────────────────── 数据 ──────────────────────────────

    def _load_runtime_info(self) -> None:
        self._version_label.setText("正在探测编码器（首次约几秒）…")
        self._encoder_available.setText("正在探测硬件编码器…")
        self._encoder_resolved.setText("")
        self._load_component_table()

        def work() -> None:
            info = collect_runtime_info(self._ffmpeg, self._ffprobe, self._registry)
            self._bridge.ready.emit(info)

        threading.Thread(target=work, name="jingxu-settings-probe", daemon=True).start()

    def _apply_runtime_info(self, info: RuntimeInfo) -> None:
        self._ffmpeg_label.setText(info.ffmpeg_path)
        self._ffprobe_label.setText(info.ffprobe_path)
        self._version_label.setText(f"{info.ffmpeg_version}")
        available = info.available_encoders or ["（无，使用 CPU 编码）"]
        self._encoder_available.setText("、".join(available))
        lines = [f"{mode}：{detail}" for mode, detail in info.resolved_encoders.items()]
        self._encoder_resolved.setText("\n".join(lines))
        self._data_label.setText(info.data_directory)
        self._platform_label.setText(f"Python {info.python_version} · {info.platform_text}")
        self._component_label.setText(self._component_summary())

    def _component_summary(self) -> str:
        whisper = find_whisper()
        whisper_text = f"Whisper 已就绪（{whisper.label}）" if whisper else "Whisper 未安装（可选）"
        tesseract = runtime_tesseract()
        tesseract_text = f"Tesseract 已就绪（{tesseract.name}）" if tesseract else "Tesseract 未安装（可选）"
        return f"{whisper_text} · {tesseract_text}"

    def _on_concurrency_changed(self, value: int) -> None:
        self._queue.set_max_concurrency(int(value))
        self._concurrency_status.setText(
            f"已设置为 {value} 个并发；有任务运行时该值在本批结束后生效。"
        )

    def _open_data_directory(self) -> None:
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _cleanup_temp(self) -> None:
        protected_paths: list[Path] = []
        output_directories: list[Path] = []
        for job in self._queue.jobs:
            output = Path(job.output_path)
            output_directories.append(output.parent)
            if job.is_active:
                protected_paths.append(output)
                protected_paths.append(output.with_name(output.name + PART_SUFFIX))

        from jingxu.infrastructure.downloader import default_download_directory

        report = cleanup_workspace(
            protected_paths=tuple(protected_paths),
            output_directories=tuple(dict.fromkeys(output_directories)),
            download_directories=(default_download_directory(),),
        )
        megabytes = report.freed_bytes / (1024 * 1024)
        text = f"已清理 {report.deleted} 项临时内容，约释放 {megabytes:.1f} MB"
        if report.skipped:
            text += f"（跳过保护项 {report.skipped} 个）"
        self._cleanup_result.setText(text + "。")

    @staticmethod
    def _mono_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Mono")
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.INK_PRIMARY};")
        return label
