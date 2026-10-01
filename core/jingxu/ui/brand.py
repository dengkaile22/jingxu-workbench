"""品牌控件：logo 与窗口图标的 Qt 封装。

单独成模块是为了避免循环导入：``shell_window`` 与 ``settings_page`` 都要用 logo，
而前者又导入后者（``shell_window → settings_page``）。若把构造函数放在
``shell_window``，``settings_page`` 反向导入就会形成环。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QLabel

from jingxu.ui import theme
from jingxu.ui.assets_loader import icon_path, logo_path


def build_logo_widget(*, size: int = 28) -> QLabel:
    """品牌 logo 控件：优先用 AppLogo.png，缺失时回退到「炳」文字标记。

    .NET 版 ShellWindow.xaml 用 ``<Image Source="Assets/AppLogo.png">``，
    这里保持一致；资源不可用时不能让界面空一块，故保留文字降级。
    """
    label = QLabel()
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    path = logo_path()
    if path is not None:
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            label.setToolTip("炳恒快速混剪")
            return label
    label.setText("炳")
    label.setStyleSheet(
        f"background: {theme.BRAND_PRIMARY}; color: {theme.ON_BRAND};"
        f"border-radius: {max(4, size // 4)}px; font-weight: 700;"
        f"font-size: {max(10, size // 2)}px;"
    )
    return label


def app_icon() -> QIcon | None:
    """窗口/任务栏图标（.NET 版为 Assets/AppIcon.ico）。"""
    path = icon_path()
    if path is None:
        return None
    icon = QIcon(str(path))
    return icon if not icon.isNull() else None
