"""浏览器档案占用检测：真实 Chromium 命令行形态与「陈旧锁 vs 真占用」判定。

为什么这些测试必须存在
----------------------
用户实测遇到两个问题，根因都在这里：

1. 点「开始抓取」总是报 ``[profile_locked]`` 浏览器档案正被另一个浏览器占用；
2. 界面从不提前警告，只有等失败后才看到。

旧实现用「能否打开 ``Default/LOCK``」判断占用，在 Windows 上**恒为 False**
（那是 0 字节普通文件，可反复打开）；而崩溃残留的 ``SingletonLock`` 又会让
判定恒为 True，把用户永久挡住。改按进程判定后，又必须先正确处理 Chromium
真实的参数形态 ``--user-data-dir=<路径>``——早期实现拿整个参数去规范化，
于是它变成 ``<当前目录>\\--user-data-dir=c:\\...``，永远匹配不上。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# tests/test_spider_profile_lock.py → parents[0]=tests, [1]=仓库根。
REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "core"
SPIDER_ROOT = REPO_ROOT / "extensions" / "spider"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


_SPIDER_PATH_ADDED = False


def _spider_preflight():
    """导入爬虫的 ``core.diagnostics.run_preflight``。

    爬虫目录必须插到 ``sys.path`` **最前**（``core`` 是常见顶层名，顺序错了会
    import 到别人）。插入后保留：模块本身已被缓存，而反复插删容易在用例之间
    产生顺序依赖。
    """
    global _SPIDER_PATH_ADDED
    if not _SPIDER_PATH_ADDED:
        if str(SPIDER_ROOT) not in sys.path:
            sys.path.insert(0, str(SPIDER_ROOT))
        _SPIDER_PATH_ADDED = True
    from core.diagnostics import run_preflight  # noqa: PLC0415

    return run_preflight

from jingxu.infrastructure import spider as spider_service  # noqa: E402
from jingxu.infrastructure.profile_lock import (  # noqa: E402
    BROWSER_PROCESS_NAMES,
    argument_uses_profile,
    command_line_uses_profile,
    lock_files_present,
    normalize_directory,
    parse_pid_payload,
    probe_holder_pids,
    remove_stale_locks,
)

PROFILE = r"C:\Users\tester\AppData\Local\JingXu\Spider\browser_profile"


def _norm(path: str) -> str:
    return normalize_directory(path)


# ── 参数解析：必须认得出 Chromium 的真实形态 ─────────────────────────────────


@pytest.mark.parametrize(
    ("argument", "expected", "label"),
    [
        (f"--user-data-dir={PROFILE}", True, "Chromium 真实形态（带前缀等号）"),
        (f'--user-data-dir="{PROFILE}"', True, "带引号的值"),
        (PROFILE, True, "裸路径（某些工具会这么传）"),
        (f"--user-data-dir={PROFILE}2", False, "同前缀的兄弟目录不得误命中"),
        (f"--user-data-dir={PROFILE}\\..\\other", False, "上跳目录不得误命中"),
        ("--type=gpu-process", False, "无关参数"),
        ("--user-data-dir=", False, "空值"),
        ("", False, "空参数"),
        ("-", False, "只有一个连字符"),
    ],
)
def test_argument_uses_profile(argument: str, expected: bool, label: str) -> None:
    assert argument_uses_profile(argument, _norm(PROFILE)) is expected, label


def test_matches_whole_command_line_string() -> None:
    """wmic/PowerShell 路径拿到的是整条命令行字符串，必须也能认出来。"""
    command_line = (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe "
        r"--type=gpu-process --user-data-dir=" + PROFILE + r" --flag=value with space"
    )
    assert command_line_uses_profile(command_line, _norm(PROFILE)) is True


def test_matches_command_line_with_spaces_in_profile_path() -> None:
    """路径中含有空格（如用户名为 John Doe 或 Program Files）时必须正确解析。"""
    profile_with_space = r"C:\Users\John Doe\AppData\Local\JingXu\Spider\browser_profile"
    command_line = (
        r'"C:\Program Files\Microsoft\Edge\Application\msedge.exe" '
        f'--user-data-dir="{profile_with_space}" --flag=1'
    )
    assert command_line_uses_profile(command_line, _norm(profile_with_space)) is True


def test_wmic_probe_parses_quoted_command_line_with_spaces(monkeypatch) -> None:
    from jingxu.infrastructure import profile_lock

    profile_with_space = r"C:\Users\John Doe\AppData\Local\JingXu\Spider\browser_profile"
    fake_csv = (
        "Node,CommandLine,ProcessId\r\n"
        f'MYPC,"msedge.exe --user-data-dir=""{profile_with_space}"" --headless",8888\r\n'
    )
    monkeypatch.setattr(profile_lock.os, "name", "nt")
    monkeypatch.setattr(profile_lock, "_run", lambda cmd: fake_csv)

    holders = profile_lock._holders_via_wmic(_norm(profile_with_space))
    assert holders == (8888,)


def test_powershell_probe_parses_quoted_command_line_with_spaces(monkeypatch) -> None:
    import json
    from jingxu.infrastructure import profile_lock

    profile_with_space = r"C:\Users\John Doe\AppData\Local\JingXu\Spider\browser_profile"
    payload = json.dumps([
        {
            "ProcessId": 9999,
            "CommandLine": f'"C:\\Program Files\\Edge\\msedge.exe" --user-data-dir="{profile_with_space}"',
        }
    ])
    monkeypatch.setattr(profile_lock.os, "name", "nt")
    monkeypatch.setattr(profile_lock, "_run", lambda cmd: payload)

    holders = profile_lock._holders_via_powershell(_norm(profile_with_space))
    assert holders == (9999,)


def test_matches_argument_sequence() -> None:
    """psutil 路径拿到的是参数列表。"""
    cmdline = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        f"--user-data-dir={PROFILE}",
        "--headless=new",
    ]
    assert command_line_uses_profile(cmdline, _norm(PROFILE)) is True


def test_does_not_match_other_profile_in_same_argv() -> None:
    """真实机器上同时开着普通 Edge（另一个档案）时不得误判。"""
    cmdline = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"--user-data-dir=C:\Users\tester\AppData\Local\Microsoft\Edge\User Data",
    ]
    assert command_line_uses_profile(cmdline, _norm(PROFILE)) is False


def test_browser_process_names_cover_edge_and_chrome() -> None:
    assert "msedge.exe" in BROWSER_PROCESS_NAMES
    assert "chrome.exe" in BROWSER_PROCESS_NAMES


# ── PID 负载解析 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[]", ()),
        ("[1234]", (1234,)),
        ("[1, 2, 3]", (1, 2, 3)),
        ("noise line\n[42]\n", (42,)),
        ("", ()),
        ("not json", ()),
        ('{"a":1}', ()),
        ('["x", 7]', (7,)),
    ],
)
def test_parse_pid_payload(text: str, expected: tuple[int, ...]) -> None:
    assert parse_pid_payload(text) == expected


# ── 探测注入：占用 / 空闲 ────────────────────────────────────────────────────


def test_probe_holder_pids_uses_injected_probe() -> None:
    assert probe_holder_pids(PROFILE, probe=lambda target: (99, 100)) == (99, 100)


def test_probe_holder_pids_swallows_probe_failure() -> None:
    """探测失败必须放行，而不是把用户永久挡住。"""

    def boom(target: str) -> tuple[int, ...]:
        raise RuntimeError("probe exploded")

    assert probe_holder_pids(PROFILE, probe=boom) == ()


# ── 真实进程：起一个浏览器占用档案，验证探测确实能发现 ──────────────────────


def _find_real_browser() -> str | None:
    for candidate in (
        Path(os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")),
        Path(os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")),
        Path(os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe")),
        Path(os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe")),
        Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


@pytest.mark.integration
def test_detects_real_browser_holding_profile(tmp_path: Path) -> None:
    """真机回归：用真实浏览器占用档案，探测必须报「被占用」。

    这条用例是本次缺陷的核心回归——旧的锁文件判定在 Windows 上恒为 False，
    只有真正起一个浏览器才能暴露。
    """
    browser = _find_real_browser()
    if browser is None:
        pytest.skip("本机没有 Chrome/Edge，无法做真实占用验证")

    profile = tmp_path / "browser_profile"
    profile.mkdir()

    process = subprocess.Popen(
        [
            browser,
            f"--user-data-dir={profile}",
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        pids = _wait_for_holder(profile)
        assert pids, "真实浏览器正在使用该档案，探测却报未占用"
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()


def _wait_for_holder(profile: Path, *, attempts: int = 20) -> tuple[int, ...]:
    """等待浏览器真正起来（进程启动后需要一点时间才出现在进程表里）。"""
    import time

    for _ in range(attempts):
        pids = probe_holder_pids(profile)
        if pids:
            return pids
        time.sleep(1.0)
    return ()


@pytest.mark.integration
def test_terminate_profile_holders_releases_real_browser_tree(tmp_path: Path) -> None:
    """确认用户授权结束档案占用后，真实浏览器进程树会退出。"""
    from jingxu.infrastructure.profile_lock import terminate_profile_holders

    browser = _find_real_browser()
    if browser is None:
        pytest.skip("本机没有 Chrome/Edge，无法验证占用进程的关闭")

    profile = tmp_path / "browser_profile"
    profile.mkdir()
    process = subprocess.Popen(
        [
            browser,
            f"--user-data-dir={profile}",
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _wait_for_holder(profile), "真实浏览器启动后应被识别为档案占用者"
        remaining = terminate_profile_holders(profile, timeout=2)
        assert remaining == ()
        assert not probe_holder_pids(profile)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


# ── 陈旧锁：有锁文件但没有活进程 ─────────────────────────────────────────────


def test_lock_files_present_reports_chromium_locks(tmp_path: Path) -> None:
    profile = tmp_path / "browser_profile"
    profile.mkdir()
    assert lock_files_present(profile) == ()

    (profile / "SingletonLock").write_text("", encoding="utf-8")
    assert lock_files_present(profile) == ("SingletonLock",)

    (profile / "lockfile").write_text("", encoding="utf-8")
    assert set(lock_files_present(profile)) == {"SingletonLock", "lockfile"}


def test_lock_files_present_on_missing_directory(tmp_path: Path) -> None:
    assert lock_files_present(tmp_path / "nope") == ()


def test_remove_stale_locks_deletes_residue(tmp_path: Path) -> None:
    profile = tmp_path / "browser_profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("", encoding="utf-8")

    removed = remove_stale_locks(profile)

    assert removed == ("SingletonLock",)
    assert lock_files_present(profile) == ()


def test_remove_stale_locks_is_idempotent(tmp_path: Path) -> None:
    profile = tmp_path / "browser_profile"
    profile.mkdir()
    assert remove_stale_locks(profile) == ()


def test_terminate_profile_holders_stops_only_the_requested_browser_tree(
    monkeypatch, tmp_path: Path
) -> None:  # noqa: ANN001
    import psutil
    from jingxu.infrastructure import profile_lock

    profile = tmp_path / "browser_profile"
    profile.mkdir()
    other_profile = tmp_path / "browser_profile_backup"
    other_profile.mkdir()

    class FakeProcess:
        def __init__(self, pid: int, name: str, cmdline: list[str], children=()) -> None:  # noqa: ANN001
            self.pid = pid
            self.info = {"pid": pid, "name": name, "cmdline": cmdline}
            self._children = list(children)
            self.terminated = False
            self.killed = False

        def children(self, recursive: bool = False) -> list["FakeProcess"]:
            return self._children

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    helper = FakeProcess(102, "chrome.exe", ["chrome.exe", "--type=renderer"])
    browser = FakeProcess(
        101,
        "chrome.exe",
        ["chrome.exe", f"--user-data-dir={profile}"],
        children=(helper,),
    )
    unrelated = FakeProcess(
        201,
        "chrome.exe",
        ["chrome.exe", f"--user-data-dir={other_profile}"],
    )
    non_browser = FakeProcess(
        301,
        "python.exe",
        ["python.exe", f"--user-data-dir={profile}"],
    )
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda _attrs: [browser, helper, unrelated, non_browser],
    )
    monkeypatch.setattr(psutil, "wait_procs", lambda processes, timeout: (processes, []))

    remaining = profile_lock.terminate_profile_holders(profile)

    assert remaining == ()
    assert browser.terminated is True
    assert helper.terminated is True
    assert unrelated.terminated is False
    assert non_browser.terminated is False


def test_terminate_profile_holders_taskkill_fallback_when_psutil_missing(
    monkeypatch, tmp_path: Path
) -> None:
    """无 psutil 时（如便携包），必须通过 Windows taskkill 兜底强杀并自愈锁文件。"""
    from jingxu.infrastructure import profile_lock

    profile = tmp_path / "browser_profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("", encoding="utf-8")

    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(profile_lock.os, "name", "nt")

    probed_pids = [10001]

    def fake_probe(target):
        # 第一次返回 10001，强杀后返回空
        if probed_pids:
            return tuple(probed_pids)
        return ()

    killed: list[int] = []

    def fake_kill(pid):
        killed.append(pid)
        probed_pids.clear()
        return True

    monkeypatch.setattr(profile_lock, "probe_holder_pids", fake_probe)
    monkeypatch.setattr(profile_lock, "_kill_pid_windows", fake_kill)

    remaining = profile_lock.terminate_profile_holders(profile)

    assert remaining == ()
    assert killed == [10001]
    assert (profile / "SingletonLock").exists() is False


# ── 工作台服务层：陈旧锁自愈、真占用拦住 ─────────────────────────────────────


def test_service_clears_stale_lock_and_reports_not_busy(monkeypatch, tmp_path: Path) -> None:
    """崩溃残留的锁文件必须被清理，否则 Chromium 会拒绝启动、用户被永久挡住。"""
    profile = tmp_path / "browser_profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("", encoding="utf-8")
    monkeypatch.setattr(spider_service, "profile_directory", lambda: profile)

    state = spider_service.profile_lock_state(probe=lambda target: ())

    assert state.busy is False
    assert state.stale_locks == ("SingletonLock",)
    assert state.cleared_locks == ("SingletonLock",)
    assert "已清理" in state.message
    assert lock_files_present(profile) == ()


def test_service_reports_busy_when_holder_alive(monkeypatch, tmp_path: Path) -> None:
    profile = tmp_path / "browser_profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("", encoding="utf-8")
    monkeypatch.setattr(spider_service, "profile_directory", lambda: profile)

    state = spider_service.profile_lock_state(probe=lambda target: (4242,))

    assert state.busy is True
    assert state.holder_pids == (4242,)
    assert "4242" in state.message
    # 真占用时绝不能删锁文件——那会让第二个实例真的去抢同一个档案
    assert lock_files_present(profile) == ("SingletonLock",)


def test_service_profile_in_use_follows_holder(monkeypatch, tmp_path: Path) -> None:
    profile = tmp_path / "browser_profile"
    profile.mkdir()
    monkeypatch.setattr(spider_service, "profile_directory", lambda: profile)

    monkeypatch.setattr(
        spider_service, "probe_holder_pids", lambda directory, probe=None: ()
    )
    assert spider_service.profile_in_use() is False

    monkeypatch.setattr(
        spider_service, "probe_holder_pids", lambda directory, probe=None: (777,)
    )
    assert spider_service.profile_in_use() is True


def test_service_profile_in_use_on_missing_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(spider_service, "profile_directory", lambda: tmp_path / "absent")
    assert spider_service.profile_in_use() is False


def test_service_terminates_only_the_app_profile_holders(monkeypatch, tmp_path: Path) -> None:
    profile = tmp_path / "browser_profile"
    captured: list[Path] = []
    monkeypatch.setattr(spider_service, "profile_directory", lambda: profile)
    monkeypatch.setattr(
        spider_service,
        "_terminate_profile_holders",
        lambda directory: captured.append(directory) or (),
        raising=False,
    )

    assert spider_service.terminate_profile_holders() == ()
    assert captured == [profile]


def test_service_probe_failure_does_not_block(monkeypatch, tmp_path: Path) -> None:
    """探测整体抛错时不得阻断用户操作。"""
    profile = tmp_path / "browser_profile"
    profile.mkdir()
    monkeypatch.setattr(spider_service, "profile_directory", lambda: profile)

    def boom(directory, probe=None):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(spider_service, "probe_holder_pids", boom)
    assert spider_service.profile_in_use() is False


# ── 登录入口：依赖缺失要给出准确提示，而不是含糊的「组件加载失败」 ──────────


def test_open_login_window_blocks_when_profile_busy(monkeypatch, tmp_path: Path) -> None:
    """档案被占用时必须在开浏览器之前拦住，否则新进程会直接崩（0xc0000142）。"""
    monkeypatch.setattr(spider_service, "spider_directory", lambda: tmp_path)
    monkeypatch.setattr(spider_service, "find_browser", lambda: Path("C:/fake/msedge.exe"))
    monkeypatch.setattr(
        spider_service,
        "profile_lock_state",
        lambda **kwargs: spider_service.ProfileLockState(busy=True, holder_pids=(1234,)),
    )

    with pytest.raises(spider_service.SpiderError) as error:
        spider_service.open_login_window("douyin")

    assert "1234" in str(error.value)
    assert "关闭" in str(error.value)


def test_open_login_window_reports_missing_dependency(monkeypatch, tmp_path: Path) -> None:
    """缺 DrissionPage 时必须说清「缺什么、怎么装」。

    打包版曾把「PyInstaller 没收集 DrissionPage」报成「请安装爬虫依赖」，
    用户在已安装的 MSI 里照做无从下手。
    """
    monkeypatch.setattr(spider_service, "spider_directory", lambda: tmp_path)
    monkeypatch.setattr(spider_service, "find_browser", lambda: Path("C:/fake/msedge.exe"))
    monkeypatch.setattr(
        spider_service,
        "profile_lock_state",
        lambda **kwargs: spider_service.ProfileLockState(busy=False),
    )
    monkeypatch.setattr(spider_service, "_missing_login_modules", lambda: ("DrissionPage",))

    with pytest.raises(spider_service.SpiderError) as error:
        spider_service.open_login_window("douyin")

    message = str(error.value)
    assert "DrissionPage" in message
    assert "缺失" in message


def test_missing_login_modules_is_empty_in_dev_environment() -> None:
    """当前开发环境装了 DrissionPage，因此不该报缺失。"""
    assert spider_service._missing_login_modules() == ()


def test_open_login_window_rejects_unknown_platform(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(spider_service, "spider_directory", lambda: tmp_path)
    with pytest.raises(spider_service.SpiderError):
        spider_service.open_login_window("weibo")


# ── 与爬虫项目的一致性 ───────────────────────────────────────────────────────


def test_app_copy_matches_spider_source() -> None:
    """工作台副本必须是爬虫真源的逐字副本（正文部分）。

    两边对「档案是否被占用」必须给出同一答案；允许的唯一差异是工作台副本多一段
    说明用的模块 docstring（由 tools/sync_profile_lock.py 生成）。
    """
    source = (SPIDER_ROOT / "core" / "profile_lock.py").read_text(encoding="utf-8")
    mirror = (APP_ROOT / "jingxu" / "infrastructure" / "profile_lock.py").read_text(
        encoding="utf-8"
    )
    marker = "from __future__ import annotations"
    assert marker in source and marker in mirror
    assert source[source.index(marker) :] == mirror[mirror.index(marker) :], (
        "工作台副本与爬虫真源不一致；请运行 python tools/sync_profile_lock.py"
    )
    assert "sync_profile_lock" in mirror[: mirror.index(marker)]


def test_spider_preflight_detects_injected_holder(tmp_path: Path) -> None:
    """爬虫侧同样按进程判定：注入一个「活着的占用者」应产生 blocker。"""
    run_preflight = _spider_preflight()

    profile = tmp_path / "browser_profile"
    profile.mkdir()

    report = run_preflight(
        headless=False,
        profile_dir=str(profile),
        probe_profile=True,
        profile_holder_probe=lambda target: (5555,),
    )

    codes = {item.code for item in report.blockers}
    assert "profile_locked" in codes
    assert any("5555" in item.message for item in report.blockers)


def test_spider_preflight_clears_stale_lock_instead_of_blocking(tmp_path: Path) -> None:
    """旧的锁文件判定会把残留锁当成真占用，用户被永久挡住；现在应自愈。"""
    run_preflight = _spider_preflight()

    profile = tmp_path / "browser_profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("", encoding="utf-8")

    report = run_preflight(
        headless=False,
        profile_dir=str(profile),
        probe_profile=True,
        profile_holder_probe=lambda target: (),
    )

    assert report.ok is True
    assert not any(item.code == "profile_locked" for item in report.blockers)
    assert (profile / "SingletonLock").exists() is False
    assert report.info.get("staleLocksRemoved") == ["SingletonLock"]


def test_spider_preflight_can_skip_profile_probe(tmp_path: Path) -> None:
    """关掉探测时不得去读进程表（测试与无 GUI 环境用）。"""
    run_preflight = _spider_preflight()

    profile = tmp_path / "browser_profile"
    profile.mkdir()

    report = run_preflight(headless=False, profile_dir=str(profile), probe_profile=False)

    assert "profileLocked" not in report.info
    assert report.ok is True
