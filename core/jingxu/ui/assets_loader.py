"""应用品牌资源：logo 与窗口图标。

.NET 版把 ``Assets/AppLogo.png`` 与 ``Assets/AppIcon.ico`` 作为 WPF Resource 使用
（ShellWindow 标题栏与启动画面显示 logo，窗口图标用 ico）。Python 迁移版此前
**完全没有图片资源**，标题栏是用一个画成色块的「炳」字代替 logo，exe 也没有
设置图标（显示为 PyInstaller 默认图标）。本模块把这两个资源接回来。

解析顺序（开发态与打包态都可用）：

1. 包内资源目录 ``jingxu/ui/assets/``（源仓库布局）；
2. PyInstaller 解包目录 ``sys._MEIPASS/jingxu/ui/assets/``（onedir 打包后）；
3. 应用目录同级 ``assets/``（允许用户替换成自己的 logo）。
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

LOGO_FILE_NAME = "AppLogo.png"
ICON_FILE_NAME = "AppIcon.ico"
MONO_FONT_FILE_NAME = "IBMPlexMono-Regular.ttf"

_ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"


def _candidate_directories() -> list[Path]:
    directories: list[Path] = [_ASSET_DIRECTORY]
    # PyInstaller 把 datas 解到 _MEIPASS；onedir 下即 exe 同级 _internal。
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        directories.append(Path(bundle) / "jingxu" / "ui" / "assets")
    # 允许在应用目录放同名文件覆盖（便于用户换 logo）。
    executable = Path(sys.executable).resolve().parent
    directories.append(executable / "assets")
    return directories


def asset_path(file_name: str) -> Path | None:
    """定位一个品牌资源文件，找不到返回 ``None``（界面需据此降级）。"""
    for directory in _candidate_directories():
        candidate = directory / file_name
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


@lru_cache(maxsize=1)
def logo_path() -> Path | None:
    return asset_path(LOGO_FILE_NAME)


@lru_cache(maxsize=1)
def icon_path() -> Path | None:
    return asset_path(ICON_FILE_NAME)


@lru_cache(maxsize=1)
def mono_font_path() -> Path | None:
    """随包等宽字体（数字与时间码用）。

    设计规格 6.2 要求「正文使用可随包分发的开源中文字体，数字和时间码使用等宽
    字体」。.NET 版以 WPF Resource 方式随包携带 IBM Plex Mono；Python 版此前直接
    用系统 ``Consolas``，在未安装该字体的机器上会回退到非等宽，时间码与数字列
    无法对齐。这里复用 .NET 版同一份字体文件（同为 Apache-2.0，不新增许可）。
    """
    return asset_path(MONO_FONT_FILE_NAME)


def register_bundled_fonts() -> list[str]:
    """把随包字体注册进 Qt，返回成功注册的族名（供主题选用）。

    必须在创建 QApplication 之后、设置应用字体之前调用。
    """
    from PySide6.QtGui import QFontDatabase

    registered: list[str] = []
    path = mono_font_path()
    if path is None:
        return registered
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(font_id)
        registered.extend(families)
    return registered


def has_logo() -> bool:
    """logo 是否可用（不可用时界面回退到文字标记）。"""
    return logo_path() is not None
