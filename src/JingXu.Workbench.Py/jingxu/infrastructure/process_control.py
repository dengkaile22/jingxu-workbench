"""子进程生命周期：进程树终止（Windows Job Object / POSIX 进程组）。

取消渲染时必须连带终止 FFmpeg 及其子进程，否则残留进程会继续占用
输出文件与硬件编码器。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any


class ProcessTreeGuard:
    """把子进程绑定到可整体终止的进程树。

    Windows 使用 Job Object（KILL_ON_JOB_CLOSE），POSIX 使用独立进程组。
    """

    def __init__(self) -> None:
        self._job_handle: Any = None

    # ────────────────────────────── 创建 ──────────────────────────────

    def spawn_kwargs(self) -> dict:
        """传给 ``subprocess.Popen`` 的附加参数。"""
        if os.name == "nt":
            return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        return {"start_new_session": True}

    def attach(self, process: subprocess.Popen) -> None:
        """进程创建后立即绑定（Windows 作业对象）。"""
        if os.name != "nt":
            return
        try:
            self._job_handle = _create_job_object()
            if self._job_handle:
                _assign_process(self._job_handle, process)
        except OSError:
            self._job_handle = None

    # ────────────────────────────── 终止 ──────────────────────────────

    def terminate(self, process: subprocess.Popen, *, timeout: float = 5.0) -> None:
        """终止整个进程树；失败时回退到单进程终止。"""
        if self._job_handle:
            try:
                _terminate_job(self._job_handle)
            except OSError:
                pass
            finally:
                _close_job(self._job_handle)
                self._job_handle = None
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
            ("Affinity", ctypes.POINTER(wintypes.ULONG)),
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
        _KERNEL32.AssignProcessToJobObject(job_handle, wintypes.HANDLE(int(handle)))

    def _terminate_job(job_handle: Any) -> None:
        _KERNEL32.TerminateJobObject(job_handle, 1)

    def _close_job(job_handle: Any) -> None:
        _KERNEL32.CloseHandle(job_handle)

else:

    def _create_job_object() -> Any:  # pragma: no cover - 非 Windows 占位
        return None
