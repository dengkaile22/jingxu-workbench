"""子进程生命周期：进程树终止（Windows Job Object / POSIX 进程组）。

取消渲染时必须连带终止 FFmpeg 及其子进程，否则残留进程会继续占用
输出文件与硬件编码器。

同时提供 :func:`no_window_kwargs`：GUI 程序自身没有控制台，启动任何控制台
子进程都会弹出黑色窗口并闪烁，必须统一抑制。
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def no_window_kwargs() -> dict:
    """抑制子进程控制台窗口的附加参数。

    GUI 程序（PyInstaller ``--windowed``）自身没有控制台，此时再启动任何
    控制台子进程，Windows 都会**新建并弹出一个黑色控制台窗口**，一瞬间
    反复闪烁。实测表现为「导入音频时一直跳黑框」「抓取时黑窗口老是弹出来」。

    因此所有非交互式子进程都必须带上这些参数：
    Windows 用 ``CREATE_NO_WINDOW``；POSIX 用 ``start_new_session``
    （同时避免子进程收到终端的 Ctrl-C）。
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


class ProcessTreeGuard:
    """把子进程绑定到可整体终止的进程树。

    Windows 使用 Job Object（KILL_ON_JOB_CLOSE），POSIX 使用独立进程组。
    """

    def __init__(self) -> None:
        self._job_handle: Any = None

    # ────────────────────────────── 创建 ──────────────────────────────

    def spawn_kwargs(self) -> dict:
        """传给 ``subprocess.Popen`` 的附加参数。"""
        return no_window_kwargs()

    def attach(self, process: subprocess.Popen) -> None:
        """进程创建后立即绑定（Windows 作业对象）。"""
        if os.name != "nt":
            return
        try:
            handle = _create_job_object()
            if handle:
                try:
                    _assign_process(handle, process)
                except OSError:
                    _close_job(handle)
                    raise
                self._job_handle = handle
        except OSError:
            self._job_handle = None

    def close(self) -> None:
        """释放作业对象句柄；调用前应确保任务进程已经退出。"""
        handle, self._job_handle = self._job_handle, None
        if handle:
            try:
                _close_job(handle)
            except OSError:
                pass

    # ────────────────────────────── 终止 ──────────────────────────────

    def terminate(self, process: subprocess.Popen, *, timeout: float = 5.0) -> None:
        """终止整个进程树；失败时回退到单进程终止。"""
        if self._job_handle:
            try:
                _terminate_job(self._job_handle)
            except OSError:
                pass
            finally:
                self.close()
            _wait_quietly(process, timeout)
            return

        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                _wait_quietly(process, timeout)
                if process.poll() is None:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            _wait_quietly(process, timeout)
            return

        try:
            process.terminate()
            _wait_quietly(process, timeout)
            if process.poll() is None:
                process.kill()
        except OSError:
            pass
        _wait_quietly(process, timeout)


def _wait_quietly(process: subprocess.Popen, timeout: float) -> None:
    try:
        process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        pass


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _KERNEL32.CreateJobObjectW.restype = wintypes.HANDLE
    _KERNEL32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _KERNEL32.SetInformationJobObject.restype = wintypes.BOOL
    _KERNEL32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _KERNEL32.AssignProcessToJobObject.restype = wintypes.BOOL
    _KERNEL32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _KERNEL32.TerminateJobObject.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _create_job_object() -> Any:
        handle = _KERNEL32.CreateJobObjectW(None, None)
        if not handle:
            return None
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _KERNEL32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            _KERNEL32.CloseHandle(handle)
            return None
        return handle

    def _assign_process(job_handle: Any, process: subprocess.Popen) -> None:
        handle = getattr(process, "_handle", None)
        if handle is None:
            return
        if not _KERNEL32.AssignProcessToJobObject(
            job_handle, wintypes.HANDLE(int(handle))
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def _terminate_job(job_handle: Any) -> None:
        if not _KERNEL32.TerminateJobObject(job_handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def _close_job(job_handle: Any) -> None:
        if not _KERNEL32.CloseHandle(job_handle):
            raise ctypes.WinError(ctypes.get_last_error())

else:

    def _create_job_object() -> Any:  # pragma: no cover - 非 Windows 占位
        return None
