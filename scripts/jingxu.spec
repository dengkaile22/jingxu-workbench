# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格：炳恒快速混剪 · Python 版（Windows x64）。

设计取舍：

* **onedir 而非 onefile**：onefile 每次启动都要把上百 MB 解包到临时目录，
  启动慢且杀软误报率高；onedir 也便于把 ``runtime/`` 放在 exe 同级，
  与 ``app_paths.search_roots()`` 的解析顺序一致。
* **runtime 不打进 exe**：FFmpeg（430+ MB）等二进制由构建脚本复制到
  ``runtime/`` 同级目录。这样既避免重复占用体积，也让用户可以单独替换
  FFmpeg 版本而无需重新打包。
* 无外部数据文件依赖：模块图标与主题色都以 Python 字面量内联在
  ``jingxu/ui/icons.py`` / ``theme.py``。
* **品牌资源例外**：``AppLogo.png`` 与 ``AppIcon.ico`` 是位图，无法内联为字面量，
  因此打进 ``datas``（包内路径 ``jingxu/ui/assets/``）。同时把它作为 exe 图标，
  否则任务栏与资源管理器会显示 PyInstaller 默认图标（此前即如此）。
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent          # noqa: F821 - PyInstaller 注入
PACKAGE_DIR = PROJECT_ROOT / "src" / "JingXu.Workbench.Py"
APP_NAME = "炳恒快速混剪"

ASSET_DIR = PACKAGE_DIR / "jingxu" / "ui" / "assets"
# 注意：目标目录必须保留 jingxu/ui/assets 层级，
# 与 assets_loader 的 ``_MEIPASS/jingxu/ui/assets`` 解析路径一致。
BRAND_DATAS = [
    (str(path), "jingxu/ui/assets")
    for path in sorted(ASSET_DIR.glob("*"))
    if path.is_file()
]
APP_ICON = ASSET_DIR / "AppIcon.ico"

analysis = Analysis(  # noqa: F821
    [str(PACKAGE_DIR / "jingxu" / "__main__.py")],
    pathex=[str(PACKAGE_DIR)],
    binaries=[],
    datas=BRAND_DATAS,
    # 爬虫/下载相关为可选依赖，缺失时功能降级而非启动失败，因此不强制收集。
    hiddenimports=[
        "jingxu.ui.icons",
        "jingxu.ui.theme",
        "jingxu.ui.widgets",
    ],
    hookspath=[],
    runtime_hooks=[],
    # 明确排除与桌面工具无关的重量级模块，避免把科学计算栈打进来。
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "IPython",
        "pytest",
        "setuptools",
        "pip",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无控制台窗口；自检模式由 --self-test 输出到 stdout（重定向时仍可用）
    # exe 图标：Windows 资源管理器与任务栏使用它（此前未设置 → 显示 PyInstaller 默认图标）
    icon=str(APP_ICON) if APP_ICON.is_file() else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
