"""选品爬虫运行环境：真机 smoke（封版用）。

爬虫的三个真实前置条件必须现场核一遍，而不是只看单元测试的 mock：

1. **内置解释器可用** —— ``spider_python()`` 指向的 Python 能起来（随包 runtime/python）；
2. **依赖齐全** —— DrissionPage / requests / openpyxl 在该解释器里真实可导入；
   ``check_environment`` 用 ``find_spec`` 只证明"包在"，这里补一次**真正 import**，
   因为打包漏收集时 ``find_spec`` 仍可能为真（历史缺陷）；
3. **浏览器可用** —— 找到 Chromium 内核浏览器（扫码登录与抓取都依赖它）。

注意：**不验证真实抓取**。抖音/快手有反爬且需要登录态与真实对标账号，
``docs/spider-rewrite-status.md`` 已明确声明该项无法在本机验证；
本文件只保证"环境本身是好的"。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jingxu.infrastructure.spider import (  # noqa: E402
    REQUIRED_MODULES,
    check_environment,
    find_browser,
    spider_directory,
    spider_python,
)
from jingxu.infrastructure.process_control import no_window_kwargs  # noqa: E402


def test_spider_source_directory_is_present() -> None:
    """爬虫源码目录（随包 runtime/spider 或源码 extensions/spider）必须找得到。"""
    directory = spider_directory()

    assert directory is not None, "未找到选品爬虫源码目录"
    assert (directory / "cli.py").is_file(), f"{directory} 下没有 cli.py"


def test_bundled_interpreter_starts() -> None:
    """内置解释器必须能真实启动并报出版本。"""
    python = spider_python()
    assert python.is_file(), f"内置解释器不存在：{python}"

    completed = subprocess.run(
        [str(python), "-B", "-c", "import sys; print(sys.version.split()[0])"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        **no_window_kwargs(),
    )

    assert completed.returncode == 0, f"内置解释器启动失败：{completed.stderr}"
    assert completed.stdout.strip().count(".") >= 1, f"版本号异常：{completed.stdout!r}"


def test_required_modules_really_import() -> None:
    """依赖必须**真正 import** 成功，而不只是 find_spec 找得到。

    历史缺陷：打包版 ``find_spec('DrissionPage')`` 有结果，真正 import 才炸；
    因此这里跑一次真实导入并如实列出失败的模块。
    """
    python = spider_python()
    probe = (
        "import json\n"
        f"mods = {list(REQUIRED_MODULES)!r}\n"
        "failed = {}\n"
        "for name in mods:\n"
        "    try:\n"
        "        __import__(name)\n"
        "    except Exception as exc:\n"
        "        failed[name] = f'{type(exc).__name__}: {exc}'\n"
        "print(json.dumps(failed, ensure_ascii=False))\n"
    )

    completed = subprocess.run(
        [str(python), "-B", "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        **no_window_kwargs(),
    )

    assert completed.returncode == 0, f"导入探测本身失败：{completed.stderr}"
    failed = json.loads(completed.stdout.strip().splitlines()[-1])
    assert failed == {}, f"以下爬虫依赖无法真正导入：{failed}"


def test_check_environment_reports_ready() -> None:
    """应用启动时用的那个检测函数必须报「可用」。"""
    environment = check_environment()

    assert environment.available is True, f"爬虫环境不可用：{environment.message}"
    assert environment.message


def test_chromium_browser_is_available() -> None:
    """必须找得到 Chromium 内核浏览器（扫码登录与抓取都依赖它）。"""
    browser = find_browser()

    assert browser is not None, "未找到 Chrome/Edge；扫码登录与抓取都无法工作"
    assert browser.is_file(), f"解析到的浏览器路径不存在：{browser}"


def test_environment_probe_writes_no_bytecode() -> None:
    """探测不得往安装目录写 ``__pycache__``。

    随包运行时位于安装目录，写字节码会污染安装目录且卸载不清理
    （docstring 里记录的历史缺陷：文件数 2693 vs 清单 2680）。
    """
    directory = spider_directory()
    assert directory is not None
    before = {path for path in directory.rglob("__pycache__")}

    check_environment()

    after = {path for path in directory.rglob("__pycache__")}
    assert after == before, f"环境探测新增了字节码目录：{after - before}"
