"""浏览器档案占用检测（``src/JingXu.Workbench.Py/JingXu.Spider/core/profile_lock.py`` 的逐字副本）。

**请勿直接修改本文件**：唯一真源在爬虫项目的 ``core/profile_lock.py``——爬虫与
工作台必须对同一件事给出同一答案。改完真源后运行 ``python tools/sync_profile_lock.py``
重新同步；工作台测试 ``tests/test_spider_profile_lock_parity.py`` 断言两份文件正文
逐字节相同。

"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Callable, Iterable, Sequence

# 会独占 user_data_dir 的内核进程名（小写，含 .exe）。
BROWSER_PROCESS_NAMES = frozenset(
    {
        "chrome.exe",
        "msedge.exe",
        "chromium.exe",
        "brave.exe",
        "vivaldi.exe",
        "opera.exe",
        "360se.exe",
        "360chrome.exe",
    }
)

# Chromium 在档案目录留下的锁文件名（Windows 上都是 0 字节普通文件）。
LOCK_FILE_NAMES = ("SingletonLock", "lockfile")

# 进程枚举子命令的超时。真实占用时枚举很快；这里只防外部命令挂死。
_PROBE_TIMEOUT = 20.0


def normalize_directory(path: str | os.PathLike[str]) -> str:
    """档案目录的规范形式（绝对路径 + 平台大小写规则），用于命令行比对。"""
    try:
        return os.path.normcase(os.path.abspath(os.fspath(path)))
    except (OSError, ValueError):
        return os.path.normcase(os.fspath(path))


def argument_uses_profile(argument: str, target: str) -> bool:
    """单个命令行参数是否指向目标档案目录。

    必须处理 ``--user-data-dir=<路径>`` 这种**带前缀**的形式：Chromium 从不把
    档案目录作为独立参数传，只写成 ``--user-data-dir=C:\\...\\browser_profile``。
    早期实现直接对整个参数做路径规范化，于是它变成
    ``<当前目录>\\--user-data-dir=c:\\...``，**永远不可能等于目标目录**——
    占用探测因此恒为「未占用」。
    """
    if not argument:
        return False
    value = str(argument).strip()
    if value.startswith("-"):
        _, separator, tail = value.partition("=")
        if not separator or not tail:
            return False
        value = tail
    value = value.strip().strip('"')
    if not value:
        return False
    try:
        return normalize_directory(value) == target
    except (OSError, ValueError):
        return False


def command_line_uses_profile(cmdline: Sequence[str] | str, target: str) -> bool:
    """命令行里是否出现了目标档案目录。

    逐参数比对而不是子串匹配：``…\\browser_profile2`` 不应命中
    ``…\\browser_profile``，带引号的 ``--user-data-dir="C:\\…\\browser_profile"``
    必须命中。参数内部可能还有空格（浏览器子进程的 ``--flag=带 空格 的值``），
    因此调用方传入整条命令行字符串时按引号切分。
    """
    if isinstance(cmdline, str):
        arguments: Iterable[str] = _split_command_line(cmdline)
    else:
        arguments = cmdline
    return any(argument_uses_profile(str(argument), target) for argument in arguments)


def _split_command_line(text: str) -> list[str]:
    """把整条命令行拆成参数（尊重双引号）。"""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
            current.append(char)
        elif char.isspace() and not quoted:
            if current:
                parts.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def parse_pid_payload(text: str) -> tuple[int, ...]:
    """解析探测输出中的 PID 列表；任何异常都当作「查不到」。"""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, list):
            continue
        pids: list[int] = []
        for item in payload:
            try:
                pids.append(int(item))
            except (TypeError, ValueError):
                continue
        return tuple(pids)
    return ()


def _hidden_kwargs() -> dict:
    """抑制控制台窗口（工作台是 GUI 程序，不能弹黑框）。"""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def _run(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PROBE_TIMEOUT,
            check=False,
            **_hidden_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout or ""


def _name_filter(prefix: str = "name") -> str:
    return " or ".join(f"{prefix}='{name}'" for name in sorted(BROWSER_PROCESS_NAMES))


# ── 手段 1：psutil（进程内）──────────────────────────────────────────────────


def _holders_via_psutil(target: str) -> tuple[int, ...] | None:
    """返回 PID 元组；``None`` 表示「这条路不可用」，需继续尝试下一条。"""
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - 没装就走别的路
        return None

    found: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in BROWSER_PROCESS_NAMES:
                continue
            if command_line_uses_profile(proc.info.get("cmdline") or [], target):
                found.append(int(proc.info["pid"]))
        except Exception:  # noqa: BLE001 - 单个进程读不到就跳过
            continue
    return tuple(found)


# ── 手段 2：wmic（Windows）───────────────────────────────────────────────────


def _holders_via_wmic(target: str) -> tuple[int, ...] | None:
    if os.name != "nt":
        return None
    output = _run(["wmic", "process", "where", f"({_name_filter()})", "get", "ProcessId,CommandLine", "/format:csv"])
    if not output.strip():
        return None

    found: list[int] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("node,"):
            continue
        # CSV：Node,CommandLine,ProcessId —— CommandLine 自身可能含逗号，
        # 因此 PID 从右侧取，命令行用 split 后再逐参数比对。
        head, _, pid_text = line.rpartition(",")
        if not pid_text.strip().isdigit():
            continue
        command_line = head.split(",", 1)[1] if "," in head else ""
        if command_line_uses_profile(command_line.split(), target):
            found.append(int(pid_text.strip()))
    return tuple(found)


# ── 手段 3：PowerShell CIM（Windows）─────────────────────────────────────────


def _holders_via_powershell(target: str) -> tuple[int, ...] | None:
    if os.name != "nt":
        return None
    script = (
        f"Get-CimInstance Win32_Process -Filter \"{_name_filter()}\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    output = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
    if not output.strip():
        return None
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return None

    found: list[int] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        try:
            pid = int(entry.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        if command_line_uses_profile(str(entry.get("CommandLine") or "").split(), target):
            found.append(pid)
    return tuple(found)


_PROBES: tuple[Callable[[str], tuple[int, ...] | None], ...] = (
    _holders_via_psutil,
    _holders_via_wmic,
    _holders_via_powershell,
)


def probe_holder_pids(
    profile_directory: str | os.PathLike[str],
    *,
    probe: Callable[[str], tuple[int, ...]] | None = None,
) -> tuple[int, ...]:
    """返回正在占用该档案目录的浏览器进程 PID。

    ``probe`` 可注入（测试用）：接收规范化的档案目录，返回 PID 元组。
    无法判断时返回空元组——**宁可放行让 Chromium 自己报错，也不要因为
    探测不到就把用户永久挡住**。

    探测链按可靠性顺序短路：某条手段**跑成功**（哪怕结果是空）就采信它，
    不再尝试后面的。否则在配了 psutil 的机器上还要白跑一次 PowerShell
    （实测 0.06s → 0.55s），而界面会在切页时调用本函数。
    返回 ``None`` 表示"这条手段不可用"（模块缺失/命令不存在），继续下一条。
    """
    target = normalize_directory(profile_directory)
    if probe is not None:
        try:
            return tuple(probe(target))
        except Exception:  # noqa: BLE001 - 探测失败不阻断
            return ()

    for candidate in _PROBES:
        try:
            pids = candidate(target)
        except Exception:  # noqa: BLE001 - 单条手段失败就换下一条
            continue
        if pids is None:
            continue
        if pids:
            return pids
        # 手段可用且结论是「没有占用者」：采信，不再跑更慢的兜底。
        return ()
    return ()


def lock_files_present(profile_directory: str | os.PathLike[str]) -> tuple[str, ...]:
    """档案目录里存在哪些 Chromium 锁文件（仅用于判断"有残留痕迹"）。"""
    directory = os.fspath(profile_directory)
    if not os.path.isdir(directory):
        return ()
    return tuple(
        name for name in LOCK_FILE_NAMES if os.path.exists(os.path.join(directory, name))
    )


def remove_stale_locks(profile_directory: str | os.PathLike[str]) -> tuple[str, ...]:
    """删除确认无主进程持有的锁文件，返回被删列表。

    只允许在 :func:`probe_holder_pids` 返回空之后调用：这时锁文件是崩溃残留，
    留着只会让 Chromium 误判"另一个实例在运行"，从而拒绝启动。
    """
    directory = os.fspath(profile_directory)
    removed: list[str] = []
    for name in lock_files_present(directory):
        path = os.path.join(directory, name)
        try:
            os.remove(path)
        except OSError:
            continue
        removed.append(name)
    return tuple(removed)
