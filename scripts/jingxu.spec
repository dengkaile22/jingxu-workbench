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
* **爬虫登录组件必须显式收集**：扫码登录由应用进程内 ``from core.browser_manager
  import BrowserManager`` 完成，而它 ``import DrissionPage``。PyInstaller 的静态
  分析看不到这种运行期动态导入，**默认不会把 DrissionPage 打进包**；实测打包版
  点「抖音登录 / 快手登录」直接报 ``No module named 'DrissionPage'``，
  即 MSI 版的扫码登录根本不可用。因此下面用 ``collect_all`` 显式收集。
  构建机没装 DrissionPage 时只告警、不中断构建（源码运行仍可用，界面会给出
  「缺哪个组件、怎么装」的准确提示）。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

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

# 扫码登录（在应用进程内完成）所需的爬虫依赖。缺任何一个，登录按钮就是死的。
LOGIN_HIDDEN_IMPORTS = [
    "DrissionPage",
    "DrissionPage.common",
    "DrissionPage.errors",
    "DrissionPage.items",
    "DrissionPage._base",
    "DrissionPage._configs",
    "DrissionPage._elements",
    "DrissionPage._functions",
    "DrissionPage._pages",
    "DrissionPage._units",
    "websocket",
    "lxml",
    "lxml.etree",
    "cssselect",
    "tldextract",
    "filelock",
    "psutil",
]

LOGIN_DATAS: list = []
LOGIN_BINARIES: list = []
for _module in ("DrissionPage", "websocket", "lxml", "cssselect", "tldextract", "filelock", "psutil"):
    try:
        _datas, _binaries, _hidden = collect_all(_module)
    except Exception as _error:  # noqa: BLE001 - 构建机缺该依赖时只告警
        print(f"[spec] 警告：未能收集 {_module}（{_error}）")
        continue
    LOGIN_DATAS += _datas
    LOGIN_BINARIES += _binaries
    LOGIN_HIDDEN_IMPORTS += _hidden

LOGIN_HIDDEN_IMPORTS = sorted(set(LOGIN_HIDDEN_IMPORTS))

analysis = Analysis(  # noqa: F821
    [str(PACKAGE_DIR / "jingxu" / "__main__.py")],
    pathex=[str(PACKAGE_DIR)],
    binaries=LOGIN_BINARIES,
    datas=BRAND_DATAS + LOGIN_DATAS,
    # 爬虫/下载相关为可选依赖，缺失时功能降级而非启动失败，因此不强制收集；
    # 但扫码登录是界面上的按钮，缺了就是「点了报错」，故上面显式收集。
    hiddenimports=[
        "jingxu.ui.icons",
        "jingxu.ui.theme",
        "jingxu.ui.widgets",
        *LOGIN_HIDDEN_IMPORTS,
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
