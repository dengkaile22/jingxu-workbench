"""端到端验证：真实浏览器占用档案时，探测必须能发现（在打包前的真机环境）。

这是本次缺陷的决定性验证——旧的锁文件判定在 Windows 上恒为 False，
只有真正起一个浏览器占用档案才能暴露。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "core"))

from jingxu.infrastructure.profile_lock import (  # noqa: E402
    lock_files_present,
    probe_holder_pids,
)
from jingxu.infrastructure.spider import profile_lock_state  # noqa: E402


def find_browser() -> str | None:
    for candidate in (
        Path(os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")),
        Path(os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")),
        Path(os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe")),
        Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def main() -> int:
    import tempfile

    browser = find_browser()
    if browser is None:
        print("SKIP: 本机没有 Chrome/Edge")
        return 1
    print("browser =", browser)

    profile = Path(tempfile.mkdtemp(prefix="jingxu-locktest-")) / "browser_profile"
    profile.mkdir(parents=True)
    print("profile =", profile)

    print("\n[1] 未启动浏览器时：")
    print("    probe       =", probe_holder_pids(profile))
    print("    lock_files  =", lock_files_present(profile))

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
    print("\n[2] 已启动浏览器 pid =", process.pid, "，等待其占用档案…")

    found: tuple[int, ...] = ()
    for attempt in range(25):
        found = probe_holder_pids(profile)
        if found:
            print(f"    第 {attempt + 1} 次探测命中：{found}")
            break
        time.sleep(1.0)
    if not found:
        print("    FAIL: 浏览器在跑，探测却报未占用")
        process.kill()
        return 1

    print("    lock_files  =", lock_files_present(profile))

    print("\n[3] 服务层判定（真实探测，不注入）：")
    state = profile_lock_state(directory=profile)
    print("    busy    =", state.busy)
    print("    pids    =", state.holder_pids)
    print("    message =", state.message)

    print("\n[3b] 陈旧锁自愈：造一个残留 SingletonLock，应被清理而不是挡住用户")
    (profile / "SingletonLock").write_text("", encoding="utf-8")
    stale_busy = profile_lock_state(directory=profile, probe=lambda target: ())
    print("    busy         =", stale_busy.busy)
    print("    cleared      =", stale_busy.cleared_locks)
    print("    message      =", stale_busy.message)
    print("    锁文件还在？ =", (profile / "SingletonLock").exists())

    process.terminate()
    try:
        process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        process.kill()

    print("\n[4] 关闭浏览器后：")
    for _ in range(15):
        if not probe_holder_pids(profile):
            break
        time.sleep(1.0)
    print("    probe       =", probe_holder_pids(profile))
    print("    lock_files  =", lock_files_present(profile))

    ok = bool(found) and state.busy
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
