"""与 .NET 版一致的设计令牌：暖灰机身 + 品牌粉 + 深色取景井。"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

FONT_BODY = "Microsoft YaHei UI"
FONT_MONO = "Consolas"

SURFACE_CANVAS = "#F3F1EA"
SURFACE_PANEL = "#FCFBF7"
SURFACE_PANEL_MUTED = "#FBFAF5"
SURFACE_RAIL = "#ECEAE1"
SURFACE_SUNK = "#E6E3DA"

GATE_WELL = "#1A1A1A"
GATE_WELL_DEEP = "#101010"
BRAND_BLOOM = "#F28A9C"
ON_GATE = "#C6CEC8"
ON_GATE_MUTED = "#7E8C85"

BRAND_PRIMARY = "#E86F8A"
BRAND_HOVER = "#D85A78"
BRAND_PRESSED = "#C34A68"
ON_BRAND = "#F4F6F1"

INK_PRIMARY = "#17231F"
INK_MUTED = "#68736E"

LINE_DEFAULT = "#D6D5CF"
LINE_STRONG = "#C3C2B9"

STATUS_RUNNING = "#C9823C"
STATUS_RUNNING_TEXT = "#8A5A28"
STATUS_FAILED = "#A8463F"

FOCUS_RING = "#E86F8A"

TITLE_BAR_HEIGHT = 44
RAIL_WIDTH = 56
MATERIAL_RAIL_WIDTH = 260
INSPECTOR_WIDTH = 300
QUEUE_HEIGHT = 144
QUEUE_COLLAPSED_HEIGHT = 36

RADIUS_STANDARD = 10
RADIUS_SMALL = 6


def body_font(pixel_size: int = 12, *, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies([FONT_BODY, "Microsoft YaHei", "SimSun", "Segoe UI", "sans-serif"])
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    font.setPixelSize(pixel_size)
    return font


def mono_font(pixel_size: int = 12) -> QFont:
    font = QFont(FONT_MONO)
    font.setPixelSize(pixel_size)
    return font


def apply_application_theme(app) -> None:  # noqa: ANN001 - QApplication
    app.setFont(body_font(12))
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    return f"""
    QWidget {{
        color: {INK_PRIMARY};
        background: transparent;
    }}
    QMainWindow, QWidget#RootSurface {{
        background: {SURFACE_CANVAS};
        border: 1px solid {LINE_STRONG};
    }}

    /* ── 容器 ───────────────────────────────────────────── */
    QFrame#Panel {{
        background: {SURFACE_PANEL};
        border: 1px solid {LINE_DEFAULT};
        border-radius: {RADIUS_STANDARD}px;
    }}
    QFrame#PanelMuted {{
        background: {SURFACE_PANEL_MUTED};
        border: 1px solid {LINE_DEFAULT};
        border-radius: {RADIUS_STANDARD}px;
    }}
    QFrame#TitleBar {{
        background: {SURFACE_PANEL};
        border-bottom: 1px solid {LINE_DEFAULT};
    }}
    QFrame#Rail {{
        background: {SURFACE_RAIL};
        border-right: 1px solid {LINE_DEFAULT};
    }}
    QFrame#SidePanel {{
        background: {SURFACE_PANEL};
    }}
    QFrame#QueueBar {{
        background: {SURFACE_PANEL};
        border-top: 1px solid {LINE_DEFAULT};
    }}
    QWidget#DividerV {{ background: {LINE_DEFAULT}; }}
    QWidget#DividerH {{ background: {LINE_DEFAULT}; }}

    /* ── 文本 ───────────────────────────────────────────── */
    QLabel#Wordmark {{ font-size: 17px; font-weight: 700; }}
    QLabel#Title {{ font-size: 15px; font-weight: 600; }}
    QLabel#SectionHeader {{ font-size: 11px; font-weight: 600; color: {INK_MUTED}; }}
    QLabel#Caption {{ font-size: 11px; color: {INK_MUTED}; }}
    QLabel#CaptionWarn {{ font-size: 11px; color: {STATUS_RUNNING_TEXT}; }}
    QLabel#Mono, QLabel#CountBadge {{
        font-family: "{FONT_MONO}";
        font-size: 11px;
        color: {INK_PRIMARY};
    }}
    QLabel#CountBadge {{
        background: {SURFACE_SUNK};
        border-radius: {RADIUS_SMALL}px;
        padding: 2px 8px;
    }}
    QLabel#GateCaption {{
        font-family: "{FONT_MONO}";
        font-size: 11px;
        color: {ON_GATE_MUTED};
    }}
    QLabel#GateTitle {{ font-size: 13px; color: {ON_GATE}; }}

    /* ── 按钮 ───────────────────────────────────────────── */
    QPushButton {{
        background: {SURFACE_PANEL};
        border: 1px solid {LINE_STRONG};
        border-radius: {RADIUS_STANDARD}px;
        padding: 8px 14px;
        font-size: 12px;
    }}
    QPushButton:hover {{ background: {SURFACE_PANEL_MUTED}; border-color: {BRAND_PRIMARY}; }}
    QPushButton:pressed {{ background: {SURFACE_SUNK}; }}
    QPushButton:disabled {{ color: {INK_MUTED}; background: {SURFACE_PANEL}; border-color: {LINE_DEFAULT}; }}
    QPushButton#Primary {{
        background: {BRAND_PRIMARY};
        color: {ON_BRAND};
        border: 1px solid {BRAND_PRIMARY};
        border-radius: {RADIUS_STANDARD}px;
        padding: 9px 16px;
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {BRAND_HOVER}; border-color: {BRAND_HOVER}; }}
    QPushButton#Primary:pressed {{ background: {BRAND_PRESSED}; border-color: {BRAND_PRESSED}; }}
    QPushButton#Primary:disabled {{ background: {SURFACE_SUNK}; color: {INK_MUTED}; border-color: {SURFACE_SUNK}; }}
    QPushButton#TitleBarButton {{
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
    }}
    QPushButton#TitleBarButton:hover {{ background: {SURFACE_SUNK}; }}
    QPushButton#CloseButton {{
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
    }}
    QPushButton#CloseButton:hover {{ background: {STATUS_FAILED}; }}

    /* ── 检查器区块分隔 ─────────────────────────────────── */
    QFrame#InspectorSection {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {LINE_DEFAULT};
    }}

    /* ── 分段选择（Segmented）──────────────────────────── */
    QFrame#Segmented {{
        background: {SURFACE_SUNK};
        border: 1px solid {LINE_DEFAULT};
        border-radius: {RADIUS_SMALL}px;
    }}
    QFrame#Segmented QRadioButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_SMALL}px;
        padding: 5px 14px;
        font-size: 12px;
        color: {INK_MUTED};
    }}
    QFrame#Segmented QRadioButton:hover {{ color: {INK_PRIMARY}; }}
    QFrame#Segmented QRadioButton:checked {{
        background: {SURFACE_PANEL};
        border-color: {LINE_DEFAULT};
        color: {INK_PRIMARY};
        font-weight: 600;
    }}
    QFrame#Segmented QRadioButton:disabled {{ color: {LINE_STRONG}; }}

    /* ── 输入 ───────────────────────────────────────────── */
    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background: {SURFACE_PANEL};
        border: 1px solid {LINE_DEFAULT};
        border-radius: {RADIUS_SMALL}px;
        padding: 6px 8px;
        font-size: 12px;
        selection-background-color: {BRAND_BLOOM};
        selection-color: {INK_PRIMARY};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
        border: 1px solid {FOCUS_RING};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
        background: {SURFACE_SUNK};
        color: {INK_MUTED};
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE_PANEL};
        border: 1px solid {LINE_DEFAULT};
        selection-background-color: {SURFACE_SUNK};
        selection-color: {INK_PRIMARY};
        outline: none;
    }}

    /* ── 列表 ───────────────────────────────────────────── */
    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QListWidget::item {{
        background: {SURFACE_PANEL_MUTED};
        border: 1px solid {LINE_DEFAULT};
        border-radius: {RADIUS_SMALL}px;
        padding: 8px 10px;
        margin: 0 0 4px 0;
    }}
    QListWidget::item:selected {{
        background: {SURFACE_SUNK};
        border: 1px solid {BRAND_BLOOM};
        color: {INK_PRIMARY};
    }}
    QListWidget#CompositionMaterials::item {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {LINE_DEFAULT};
        border-radius: 0;
        padding: 7px 2px;
        margin: 0;
    }}
    QListWidget#CompositionMaterials::item:selected {{
        background: {SURFACE_SUNK};
        border: none;
        border-bottom: 1px solid {LINE_DEFAULT};
        color: {INK_PRIMARY};
    }}
    QListWidget#ModuleRail::item {{
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }}

    /* ── 表格 ───────────────────────────────────────────── */
    QTableWidget {{
        background: transparent;
        border: none;
        gridline-color: transparent;
        outline: none;
    }}
    QTableWidget::item {{ padding: 6px 4px; border-bottom: 1px solid {LINE_DEFAULT}; }}
    QTableWidget::item:selected {{ background: {SURFACE_SUNK}; color: {INK_PRIMARY}; }}
    QHeaderView::section {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {LINE_DEFAULT};
        padding: 6px 4px;
        color: {INK_MUTED};
        font-size: 11px;
        font-weight: 600;
    }}

    /* ── 进度条 ─────────────────────────────────────────── */
    QProgressBar {{
        background: {SURFACE_SUNK};
        border: none;
        border-radius: 3px;
        text-align: center;
        font-size: 10px;
        color: {INK_MUTED};
    }}
    QProgressBar::chunk {{ background: {BRAND_PRIMARY}; border-radius: 3px; }}

    /* ── 滚动条 ─────────────────────────────────────────── */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {LINE_STRONG}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {INK_MUTED}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {LINE_STRONG}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ── 取景井 ─────────────────────────────────────────── */
    QFrame#GateWell {{
        background: {GATE_WELL};
        border: 1px solid {BRAND_BLOOM};
        border-radius: {RADIUS_STANDARD}px;
    }}
    QFrame#GateWell QLabel {{ background: transparent; }}
    """
