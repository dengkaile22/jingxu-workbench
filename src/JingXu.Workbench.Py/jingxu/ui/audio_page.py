"""音频库页：导入与管理 BGM 素材（背景音乐在混剪页设置）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from jingxu.infrastructure.audio_library import AudioLibrary, AudioProbeError, AudioTrack, probe_audio
from jingxu.ui.widgets import Caption, SecondaryButton, SectionHeader

AUDIO_FILTER = "音频文件 (*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.wma);;所有文件 (*)"


class AudioPage(QWidget):
    """音频库（BGM 素材登记）。"""

    library_changed = Signal()

    def __init__(self, library: AudioLibrary, ffprobe: Path) -> None:
        super().__init__()
        self._library = library
        self._ffprobe = Path(ffprobe)
        self._tracks: list[AudioTrack] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)
        layout.addLayout(self._build_header())
        self._status = Caption("")
        self._status.setVisible(False)
        layout.addWidget(self._status)

        layout.addSpacing(12)
        layout.addWidget(SectionHeader("音频库"))
        layout.addSpacing(8)
        layout.addWidget(
            Caption(
                "导入 MP3、WAV、M4A、AAC、FLAC、OGG 等音频文件后，可在混剪页开启「音频库随机抽取」，"
                "每个渲染任务自动抽取一条背景音乐。"
            )
        )
        layout.addSpacing(8)
        self._list = QListWidget()
        self._list.setObjectName("CompositionMaterials")
        layout.addWidget(self._list, stretch=1)

        self._reload()

    # ────────────────────────────── 构建 ──────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel("音频库")
        title.setObjectName("Title")
        row.addWidget(title)
        row.addStretch(1)

        import_button = SecondaryButton("导入音频…")
        import_button.clicked.connect(self._import_tracks)
        row.addWidget(import_button)

        remove_button = SecondaryButton("移除选中")
        remove_button.clicked.connect(self._remove_selected)
        row.addWidget(remove_button)

        clear_button = SecondaryButton("清空")
        clear_button.clicked.connect(self._clear)
        row.addWidget(clear_button)
        return row

    # ────────────────────────────── 数据 ──────────────────────────────

    def _reload(self) -> None:
        self._tracks = self._library.recent_tracks
        current = self._list.currentRow()
        self._list.blockSignals(True)
        self._list.clear()
        for track in self._tracks:
            detail = (
                f"{track.duration_text} · {track.sample_rate or '?'}Hz · {track.channels or '?'}ch"
                f" · 最近使用 {track.last_used_text}"
            )
            item = QListWidgetItem(f"{track.display_name}    {detail}")
            item.setToolTip(str(track.path))
            self._list.addItem(item)
        if 0 <= current < len(self._tracks):
            self._list.setCurrentRow(current)
        self._list.blockSignals(False)
        self._refresh_state()

    def _refresh_state(self) -> None:
        if not self._tracks:
            empty = QListWidgetItem("音频库为空。点击「导入音频…」添加背景音乐素材。")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.clear()
            self._list.addItem(empty)

    def _import_tracks(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "导入音频", "", AUDIO_FILTER)
        if not files:
            return

        tracks: list[AudioTrack] = []
        failures: list[str] = []
        for raw in files:
            path = Path(raw)
            try:
                tracks.append(probe_audio(path, self._ffprobe))
            except AudioProbeError as error:
                failures.append(str(error))

        added = self._library.add(tracks)
        self._reload()
        if added:
            self.library_changed.emit()
        self._set_status(f"已导入 {added} 个音频。")
        if failures:
            QMessageBox.warning(self, "部分音频无法导入", "\n".join(failures[:6]))

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if not (0 <= row < len(self._tracks)):
            return
        track = self._tracks[row]
        self._library.remove(track.path)
        self._reload()
        self.library_changed.emit()
        self._set_status(f"已移除：{track.display_name}")

    def _clear(self) -> None:
        if not self._tracks:
            return
        # 清空确认（默认「否」），只清空软件音频库，不删除磁盘文件。
        answer = QMessageBox.question(
            self,
            "清空音频库",
            f"确定清空音频库中的 {len(self._tracks)} 条记录吗？\n只清空软件音频库，不会删除电脑中的原音频文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._set_status("已取消清空。")
            return
        removed = self._library.clear()
        self._reload()
        self.library_changed.emit()
        self._set_status(f"已清空音频库（{removed} 条记录）。")

    def tracks(self) -> list[AudioTrack]:
        return list(self._tracks)

    def _set_status(self, text: str, *, warn: bool = False) -> None:
        self._status.setObjectName("CaptionWarn" if warn else "Caption")
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
