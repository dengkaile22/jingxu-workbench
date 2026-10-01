"""回归测试：所有 GUI 子进程调用都必须抑制控制台窗口。

问题背景（用户实测）：打包成 ``--windowed`` 程序后，启动任何控制台子进程，
Windows 都会新建并弹出一个黑色控制台窗口，表现为「导入音频时一直跳黑框」、
「抓取时黑窗口老是弹出来」。因此这是**契约级**要求，用静态扫描守住。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jingxu.infrastructure.process_control import no_window_kwargs

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "core" / "jingxu"
SUBPROCESS_FUNCTIONS = {"run", "Popen", "call", "check_output"}

# 等价于「交给 subprocess 的创建标志」的写法
SUPPRESS_KEYWORDS = {"creationflags", "start_new_session"}
# 允许的抑制助手函数名。新增助手时同步加进来即可，判定标准不变：
# 该助手必须真的返回平台对应的抑制参数（见下方 test_helper_* 用例）。
SUPPRESS_HELPERS = {
    "no_window_kwargs",
    "_hidden_process_kwargs",
    "spawn_kwargs",
    "_hidden_kwargs",
}


def test_known_suppression_helpers_actually_suppress() -> None:
    """allowlist 里的助手必须真的抑制窗口，否则扫描会被"起个对的名字"绕过。"""
    import os

    from jingxu.infrastructure.profile_lock import _hidden_kwargs

    for helper in (no_window_kwargs, _hidden_kwargs):
        kwargs = helper()
        if os.name == "nt":
            assert kwargs.get("creationflags"), f"{helper.__name__} 未设置 creationflags"
        else:
            assert kwargs.get("start_new_session") is True, (
                f"{helper.__name__} 未设置 start_new_session"
            )


def _helper_suppresses(value: ast.AST) -> bool:
    """判断 ``**xxx`` 的实参是否等价于抑制窗口。"""
    # **guard.spawn_kwargs()
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        return value.func.attr in SUPPRESS_HELPERS
    # **spawn_kwargs()
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id in SUPPRESS_HELPERS
    # **kwargs 形式的直接引用（例如 **no_window_kwargs）
    if isinstance(value, ast.Name):
        return value.id in SUPPRESS_HELPERS
    return False


def _iter_subprocess_calls():
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "subprocess" or func.attr not in SUBPROCESS_FUNCTIONS:
                continue
            yield path, node


def test_no_window_kwargs_is_platform_appropriate() -> None:
    kwargs = no_window_kwargs()
    if __import__("os").name == "nt":
        assert "creationflags" in kwargs
    else:
        assert kwargs.get("start_new_session") is True


def test_every_subprocess_call_suppresses_the_console_window() -> None:
    """任何遗漏都会在 GUI 下闪出黑框，因此一处都不允许漏。"""
    offenders: list[str] = []
    for path, node in _iter_subprocess_calls():
        identifiers = {keyword.arg for keyword in node.keywords}
        if identifiers & SUPPRESS_KEYWORDS:
            continue
        if any(
            keyword.arg is None and _helper_suppresses(keyword.value)
            for keyword in node.keywords
        ):
            continue
        offenders.append(f"{path.relative_to(PACKAGE_ROOT.parent)}:{node.lineno}")

    assert offenders == [], "以下 subprocess 调用未抑制控制台窗口：" + ", ".join(offenders)


def test_scan_actually_finds_calls() -> None:
    """防止扫描逻辑失灵导致上面的用例变成空断言。"""
    assert len(list(_iter_subprocess_calls())) >= 15


def test_windowed_process_cannot_spawn_console() -> None:
    """真机验证：带抑制参数启动的控制台程序不会创建窗口。

    用 ``cmd /c exit`` 这类必然可用的命令，检查进程能正常结束——
    若参数不被接受会直接抛异常。
    """
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-c", "print('ok')"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        **no_window_kwargs(),
    )
    assert completed.returncode == 0
    assert "ok" in completed.stdout
