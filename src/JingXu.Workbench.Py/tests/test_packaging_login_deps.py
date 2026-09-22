"""打包约束：扫码登录依赖必须被 PyInstaller 收集。

背景（真实缺陷）
----------------
扫码登录由应用**进程内**执行 ``from core.browser_manager import BrowserManager``，
而它 ``import DrissionPage``。PyInstaller 的静态分析看不到这种运行期动态导入，
``jingxu.spec`` 原先既没有 ``hiddenimports`` 也没有 ``collect_all``，
于是打包版点「抖音登录 / 快手登录」报 ``No module named 'DrissionPage'`` ——
**MSI 版的扫码登录完全不可用**，而源码运行却是好的，因此只在装机版上暴露。

这类问题不能靠"记得改 spec"来防：本文件把「登录所需模块」与「spec 收集范围」
绑成断言，新增登录依赖却忘了写进 spec 时会直接失败。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "scripts" / "jingxu.spec"
APP_ROOT = REPO_ROOT / "src" / "JingXu.Workbench.Py"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _spec_text() -> str:
    assert SPEC_PATH.is_file(), f"找不到打包规格：{SPEC_PATH}"
    return SPEC_PATH.read_text(encoding="utf-8")


def test_spec_is_valid_python() -> None:
    """spec 是构建脚本，语法错会以晦涩方式失败，先静态解析一次。"""
    ast.parse(_spec_text())


def test_spec_collects_drissionpage() -> None:
    """DrissionPage 必须被显式收集（静态分析发现不了它）。"""
    text = _spec_text()
    assert "DrissionPage" in text, "jingxu.spec 没有收集 DrissionPage，打包版的扫码登录会报 No module named"
    assert "collect_all" in text, "应使用 collect_all 收集 DrissionPage 及其数据/子模块"
    assert "hiddenimports" in text


def test_spec_collects_login_support_modules() -> None:
    """DrissionPage 的运行时依赖同样要收集，否则 import 时才会炸。"""
    text = _spec_text()
    for module in ("lxml", "websocket", "cssselect", "tldextract", "filelock", "psutil"):
        assert module in text, f"jingxu.spec 未收集 {module}（DrissionPage 的运行时依赖）"


def test_spec_keeps_brand_assets() -> None:
    """品牌资源不能被这次改动挤掉。"""
    text = _spec_text()
    assert "jingxu/ui/assets" in text
    assert "AppIcon.ico" in text


def test_login_requirement_matches_spec_coverage() -> None:
    """登录入口检查的每个模块，spec 里都必须有。

    这是本文件存在的核心理由：``_missing_login_modules`` 决定"登录能不能用"，
    spec 决定"打包版有没有"。两者一旦脱节，装机版就会静默缺功能。
    """
    from jingxu.infrastructure.spider import _missing_login_modules  # noqa: PLC0415

    # 源码环境应齐全（否则本机的开发/测试都跑不了登录）
    assert _missing_login_modules() == (), "源码环境缺少登录依赖，先 pip install -e \".[spider]\""

    import inspect  # noqa: PLC0415

    source = inspect.getsource(_missing_login_modules)
    # 从实现里抽出被检查的模块名，逐一对齐 spec
    checked = [
        name
        for name in ("DrissionPage", "requests", "openpyxl", "websocket", "lxml")
        if f'"{name}"' in source
    ]
    assert checked, "未能从 _missing_login_modules 提取出被检查的模块名"
    spec = _spec_text()
    for name in checked:
        assert name in spec, f"登录入口要求 {name}，但 jingxu.spec 没有收集它"


def test_spec_does_not_exclude_login_modules() -> None:
    """别忘了 excludes 会覆盖 hiddenimports：被排除的模块仍然打不进包。

    用 AST **解析出 excludes 列表里的实际字符串**再比对，而不是在源码文本里
    找关键字：后者会把注释里提到模块名误判成"被排除"，并且一旦列表换行或
    出现嵌套结构就会静默截断。
    """
    excluded = _spec_excludes()
    assert excluded, "spec 应显式声明 excludes"

    for module in ("DrissionPage", "lxml", "websocket", "psutil", "tldextract"):
        assert module not in excluded, (
            f"{module} 被 excludes 排除了，扫码登录会在打包版失效"
        )


def _spec_excludes() -> set[str]:
    """从 jingxu.spec 里取出 Analysis(excludes=[...]) 的字符串项。

    spec 是 Python 源码（虽然由 PyInstaller 执行），可以直接 parse；
    用 ``ast.literal_eval`` 取值，避免手工处理引号与注释。
    """
    import ast  # noqa: PLC0415

    tree = ast.parse(_spec_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "excludes":
                continue
            try:
                value = ast.literal_eval(keyword.value)
            except ValueError:  # pragma: no cover - 列表里出现非字面量时跳过
                continue
            found.update(str(item) for item in value)
    return found


def test_spec_excludes_trims_unused_heavy_payload() -> None:
    """体积裁剪：产品不用的重量级包必须显式排除。

    cv2 是构建机装了、产品代码与爬虫都没 import 的包，却会被传递依赖拖进产物
    （cv2.pyd 85 MB + opencv_videoio_ffmpeg 27 MB）。排除它不影响任何功能：
    DrissionPage 只在 screencast.py（浏览器录屏）里用 cv2，本应用不使用录屏。
    """
    excluded = _spec_excludes()

    for module in ("cv2", "opencv", "numpy", "matplotlib", "scipy", "pandas"):
        assert module in excluded, f"{module} 未排除，打包产物会白白变大"
