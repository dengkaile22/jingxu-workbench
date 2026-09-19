"""与 .NET 版一致的通用控件与矢量图标渲染。"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from jingxu.ui import theme
from jingxu.ui.icons import SECTION_CHEVRON


def render_svg_path(
    path_data: str,
    size: int,
    color: str,
    *,
    stroke_width: float = 1.5,
    view_box: int = 24,
) -> QPixmap:
    """把 24x24 视图盒路径渲染为指定像素大小的位图。"""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {view_box} {view_box}">'
        f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap


class SectionHeader(QLabel):
    """小节标题：11px 半粗、墨色次强调。"""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setObjectName("SectionHeader")


class Caption(QLabel):
    """说明文字：11px 次要墨色，自动换行。"""

    def __init__(self, text: str = "", *, warn: bool = False) -> None:
        super().__init__(text)
        self.setObjectName("CaptionWarn" if warn else "Caption")
        self.setWordWrap(True)


class CountBadge(QLabel):
    """数量徽标：沉底小圆角。"""

    def __init__(self, text: str = "0") -> None:
        super().__init__(text)
        self.setObjectName("CountBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class Divider(QFrame):
    def __init__(self, *, horizontal: bool = True) -> None:
        super().__init__()
        self.setObjectName("DividerH" if horizontal else "DividerV")
        if horizontal:
            self.setFixedHeight(1)
        else:
            self.setFixedWidth(1)


class PrimaryButton(QPushButton):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setObjectName("Primary")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class SecondaryButton(QPushButton):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class GlyphButton(QPushButton):
    """标题栏/工具条图标按钮：16px 描边字形，悬停换色。"""

    def __init__(
        self,
        icon_path: str,
        *,
        icon_size: int = 16,
        stroke: float = 1.3,
        button_size: tuple[int, int] = (46, 44),
        close: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("CloseButton" if close else "TitleBarButton")
        self.setFixedSize(*button_size)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_size = icon_size
        self._stroke = stroke
        self._close = close
        self._pixmaps = {
            "idle": render_svg_path(icon_path, icon_size, theme.INK_MUTED, stroke_width=stroke, view_box=14),
            "hover": render_svg_path(
                icon_path,
                icon_size,
                theme.ON_BRAND if close else theme.INK_PRIMARY,
                stroke_width=stroke,
                view_box=14,
            ),
        }
        self.setIcon(QIcon(self._pixmaps["idle"]))
        self.setIconSize(self._pixmaps["idle"].size())

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self.setIcon(QIcon(self._pixmaps["hover"]))
        super().enterEvent(event)

    def set_icon_path(self, icon_path: str) -> None:
        """替换字形（最大化 ↔ 还原），保持悬停配色。"""
        self._pixmaps = {
            "idle": render_svg_path(icon_path, self._icon_size, theme.INK_MUTED, stroke_width=self._stroke, view_box=14),
            "hover": render_svg_path(
                icon_path,
                self._icon_size,
                theme.ON_BRAND if self._close else theme.INK_PRIMARY,
                stroke_width=self._stroke,
                view_box=14,
            ),
        }
        self.setIcon(QIcon(self._pixmaps["idle"]))
        self.setIconSize(self._pixmaps["idle"].size())

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.setIcon(QIcon(self._pixmaps["idle"]))
        super().leaveEvent(event)


class ModuleRailItem(QWidget):
    """模块导航条目：22px 图标 + 10.5px 标签 + 选中粉色指示条。"""

    clicked = Signal(str)

    def __init__(self, label: str, icon_path: str, module_id: str, *, enabled: bool = True) -> None:
        super().__init__()
        self.module_id = module_id
        self._enabled = enabled
        self._selected = False
        self._hovered = False

        self.setFixedHeight(52)
        if enabled:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._accent = QFrame()
        self._accent.setFixedWidth(3)
        self._accent.setStyleSheet(f"background: {theme.BRAND_PRIMARY};")
        self._accent.setVisible(False)
        layout.addWidget(self._accent)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setFixedSize(22, 22)
        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(3)
        content.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        content.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(content, stretch=1)

        self._pixmaps = {
            "idle": render_svg_path(icon_path, 22, theme.INK_MUTED, stroke_width=1.5),
            "active": render_svg_path(icon_path, 22, theme.BRAND_PRIMARY, stroke_width=1.5),
        }

        if not enabled:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.38)
            self.setGraphicsEffect(effect)

        self._apply_state()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_state()

    def _apply_state(self) -> None:
        self._icon.setPixmap(self._pixmaps["active" if self._selected else "idle"])
        self._label.setStyleSheet(
            f"font-size: 11px; color: {theme.INK_PRIMARY if self._selected else theme.INK_MUTED};"
        )
        self._accent.setVisible(self._selected)
        if self._selected:
            background = theme.SURFACE_PANEL
        elif self._hovered:
            background = theme.SURFACE_SUNK
        else:
            background = "transparent"
        self.setStyleSheet(f"background: {background};")

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._enabled:
            self._hovered = True
            self._apply_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._apply_state()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.module_id)
            event.accept()
            return
        super().mousePressEvent(event)


class ModuleRail(QWidget):
    """模块导航栏：条目点击切换，选中态由壳层同步。"""

    selected_changed = Signal(str)

    def __init__(self, items: Sequence[tuple[str, str, str, bool]]) -> None:
        super().__init__()
        self.setFixedWidth(theme.RAIL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)

        self._items: dict[str, ModuleRailItem] = {}
        for label, icon_path, module_id, enabled in items:
            item = ModuleRailItem(label, icon_path, module_id, enabled=enabled)
            item.clicked.connect(self._on_item_clicked)
            layout.addWidget(item)
            self._items[module_id] = item
        layout.addStretch(1)

        self._current = next(iter(self._items), "")
        if self._current:
            self._items[self._current].set_selected(True)

    def _on_item_clicked(self, module_id: str) -> None:
        self.select(module_id)
        self.selected_changed.emit(module_id)

    def select(self, module_id: str) -> None:
        if module_id == self._current or module_id not in self._items:
            return
        self._items[self._current].set_selected(False)
        self._current = module_id
        self._items[module_id].set_selected(True)

    @property
    def current_id(self) -> str:
        return self._current


class SectionExpander(QWidget):
    """检查器可折叠区块：小节标题 + 旋转箭头 + 内容。"""

    def __init__(self, title: str, content: QWidget, *, expanded: bool = True) -> None:
        super().__init__()
        self.setObjectName("InspectorSection")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = _ExpanderHeader(title, self.toggle)
        layout.addWidget(header)

        self._content = content
        self._content.setContentsMargins(0, 0, 0, 12)
        layout.addWidget(self._content)

        self._header = header
        self._expanded = expanded
        self._apply_expanded()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded()

    def _apply_expanded(self) -> None:
        self._content.setVisible(self._expanded)
        self._header.set_chevron_rotated(self._expanded)


class _ExpanderHeader(QWidget):
    def __init__(self, title: str, on_click) -> None:  # noqa: ANN001
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_click = on_click

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(0)
        layout.addWidget(SectionHeader(title))
        layout.addStretch(1)

        self._chevron = QLabel()
        self._chevron_down = render_svg_path(
            SECTION_CHEVRON,
            10,
            theme.INK_MUTED,
            stroke_width=1.4,
            view_box=10,
        )
        self._chevron_up = self._chevron_down.transformed(QTransform().rotate(180))
        self._chevron.setPixmap(self._chevron_down)
        layout.addWidget(self._chevron)

    def set_chevron_rotated(self, rotated: bool) -> None:
        self._chevron.setPixmap(self._chevron_up if rotated else self._chevron_down)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


class SegmentedControl(QFrame):
    """分段单选：与 .NET ``Segmented.Container`` 视觉一致。"""

    changed = Signal(object)

    def __init__(self, options: Sequence[tuple[str, object]]) -> None:
        super().__init__()
        self.setObjectName("Segmented")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._index_by_value: dict[int, object] = {}

        for index, (label, value) in enumerate(options):
            button = QRadioButton(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(button)
            self._group.addButton(button, index)
            self._index_by_value[index] = value

        self._value = options[0][1] if options else None
        if options:
            self._group.button(0).setChecked(True)

        self._group.idClicked.connect(self._on_clicked)

    def _on_clicked(self, index: int) -> None:
        value = self._index_by_value.get(index)
        if value is not None and value != self._value:
            self._value = value
            self.changed.emit(value)

    def value(self) -> object:
        return self._value

    def set_value(self, value: object) -> None:
        for index, option_value in self._index_by_value.items():
            if option_value == value:
                button = self._group.button(index)
                if button is not None:
                    button.setChecked(True)
                self._value = value
                return

    def set_option_enabled(self, value: object, enabled: bool, tooltip: str = "") -> None:
        for index, option_value in self._index_by_value.items():
            if option_value == value:
                button = self._group.button(index)
                if button is not None:
                    button.setEnabled(enabled)
                    button.setToolTip(tooltip)


class MaterialList(QListWidget):
    """支持文件拖入的素材列表（选中卡片样式由主题提供）。"""

    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
