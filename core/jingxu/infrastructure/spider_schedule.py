"""Daily selection jobs registered with Windows and launched without a UI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from jingxu.infrastructure.paths import data_directory
from jingxu.infrastructure.process_control import no_window_kwargs

TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
RUN_BUSY_MESSAGE = "已有选品抓取任务正在运行，已跳过本次启动。"


class ScheduleError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DailySchedule:
    enabled: bool = False
    time: str = "02:00"
    task_id: str = ""
    task_name: str = ""

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return cls()
        clock = str(value.get("time") or "02:00")
        return cls(enabled=value.get("enabled") is True, time=clock if TIME_RE.fullmatch(clock) else "02:00",
                   task_id=str(value.get("taskId") or ""), task_name=str(value.get("taskName") or ""))

    def to_dict(self):
        return {"schemaVersion": 1, "enabled": self.enabled, "time": self.time,
                "taskId": self.task_id, "taskName": self.task_name}

    def next_run(self, now=None):
        now = now or datetime.now()
        hours, minutes = map(int, self.time.split(":"))
        next_ = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        return next_ if next_ > now else next_ + timedelta(days=1)


def _atomic_json(file, value):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(f".{file.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, file)
    finally:
        temporary.unlink(missing_ok=True)


class DailyScheduleStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "Spider/daily_schedule.json"
        self.state_path = self.path.with_name("daily_schedule_state.json")

    def load(self):
        try:
            return DailySchedule.from_dict(json.loads(self.path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            return DailySchedule()

    def save(self, schedule):
        _atomic_json(self.path, schedule.to_dict())

    def load_state(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self, state):
        _atomic_json(self.state_path, state)


class CrawlRunLease:
    """One selection run across manual jobs and scheduled processes."""
    def __init__(self, root=None):
        self.root = Path(root) if root else data_directory() / "Spider"
        self._file = None

    def acquire(self):
        self.root.mkdir(parents=True, exist_ok=True)
        file = self.root / ".crawl-run.lock"
        if file.is_symlink():
            return False
        handle = file.open("a+b")
        try:
            if file.stat().st_size == 0:
                handle.write(b"0"); handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def close(self):
        handle, self._file = self._file, None
        if handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def scheduled_command(schedule, store, config_path, *, executable=None, frozen=None):
    executable = Path(executable or sys.executable).resolve()
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    core_root = Path(__file__).resolve().parents[2]
    bootstrap = f"import sys;sys.path.insert(0,{str(core_root)!r});from jingxu.__main__ import main;sys.exit(main())"
    arguments = [] if frozen else ["-c", bootstrap]
    arguments += ["--scheduled-spider", "--schedule-file", str(store.path.resolve()),
                  "--spider-config", str(Path(config_path).resolve()),
                  "--data-directory", str(data_directory().resolve()), "--schedule-id", schedule.task_id]
    return str(executable), arguments


def task_xml(schedule, command, arguments, *, now=None):
    ET.register_namespace("", TASK_NAMESPACE)
    node = lambda name: f"{{{TASK_NAMESPACE}}}{name}"
    task = ET.Element(node("Task"), {"version": "1.2"})
    info = ET.SubElement(task, node("RegistrationInfo"))
    ET.SubElement(info, node("Description")).text = "清影快速混剪：每天自动抓取已保存的选品账号和筛选报表。"
    trigger = ET.SubElement(ET.SubElement(task, node("Triggers")), node("CalendarTrigger"))
    ET.SubElement(trigger, node("StartBoundary")).text = schedule.next_run(now).isoformat(timespec="seconds")
    ET.SubElement(trigger, node("Enabled")).text = "true"
    ET.SubElement(ET.SubElement(trigger, node("ScheduleByDay")), node("DaysInterval")).text = "1"
    principal = ET.SubElement(ET.SubElement(task, node("Principals")), node("Principal"), {"id": "Author"})
    ET.SubElement(principal, node("LogonType")).text = "InteractiveToken"
    ET.SubElement(principal, node("RunLevel")).text = "LeastPrivilege"
    settings = ET.SubElement(task, node("Settings"))
    for key, value in (("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                       ("StopIfGoingOnBatteries", "false"), ("StartWhenAvailable", "true"),
                       ("AllowStartOnDemand", "true"), ("Enabled", "true"), ("ExecutionTimeLimit", "PT0S")):
        ET.SubElement(settings, node(key)).text = value
    action = ET.SubElement(ET.SubElement(task, node("Actions"), {"Context": "Author"}), node("Exec"))
    ET.SubElement(action, node("Command")).text = command
    ET.SubElement(action, node("Arguments")).text = subprocess.list2cmdline(arguments)
    ET.SubElement(action, node("WorkingDirectory")).text = str(Path(command).parent)
    # Task Scheduler accepts a Unicode BSTR; an UTF-8 declaration inside that
    # string makes its XML reader attempt an invalid encoding switch.
    return ET.tostring(task, encoding="unicode", xml_declaration=False)


REGISTER_SCRIPT = r"""param([string]$TaskName, [string]$XmlPath, [string]$Operation)
$ErrorActionPreference = 'Stop'
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
if ($Operation -eq 'delete') {
    try { $null = $folder.GetTask($TaskName) } catch { exit 0 }
    $folder.DeleteTask($TaskName, 0)
    exit 0
}
$definition = $service.NewTask(0)
$definition.XmlText = [IO.File]::ReadAllText($XmlPath, [Text.Encoding]::UTF8)
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$definition.Principal.UserId = $userSid
$null = $folder.RegisterTaskDefinition($TaskName, $definition, 6, $userSid, $null, 3, $null)
$registered = $folder.GetTask($TaskName)
if (-not $registered.Enabled) { throw 'Scheduled task was not enabled.' }
"""


class WindowsDailyTaskScheduler:
    def __init__(self, *, run_command=None):
        self._run_command = run_command or subprocess.run

    def task_name(self, store):
        fingerprint = hashlib.sha256(str(store.path.resolve()).casefold().encode("utf-8")).hexdigest()[:16]
        return f"JingXu-Spider-Daily-{fingerprint}"

    def _invoke(self, name, xml="", operation="register"):
        if os.name != "nt":
            raise ScheduleError("每日自动抓取目前需要 Windows 任务计划。")
        with tempfile.TemporaryDirectory(prefix="jingxu-daily-task-") as temporary:
            folder = Path(temporary).resolve()
            if not folder.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not folder.name.startswith("jingxu-daily-task-"):
                raise ScheduleError("定时任务临时目录无法确认。")
            script, definition = folder / "register.ps1", folder / "task.xml"
            script.write_text(REGISTER_SCRIPT, encoding="utf-8-sig")
            definition.write_text(xml, encoding="utf-8")
            result = self._run_command(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                        "-TaskName", name, "-XmlPath", str(definition), "-Operation", operation],
                                       capture_output=True, text=True, timeout=25, **no_window_kwargs())
            if result.returncode:
                raise ScheduleError("Windows 定时任务设置失败，请检查任务计划服务和当前账号权限。")

    def configure(self, schedule, store, config_path):
        name = self.task_name(store)
        if not schedule.enabled:
            # The worker checks this setting too, so disabling is effective
            # even if Windows cannot remove the old task immediately.
            disabled = replace(schedule, enabled=False, task_name=name)
            store.save(disabled)
            self._invoke(name, operation="delete")
            return disabled
        if not TIME_RE.fullmatch(schedule.time):
            raise ScheduleError("请设置有效的每日抓取时间。")
        configured = replace(schedule, task_id=schedule.task_id or uuid4().hex, task_name=name)
        command, arguments = scheduled_command(configured, store, config_path)
        previous = store.load()
        store.save(replace(configured, enabled=False))
        try:
            self._invoke(name, task_xml(configured, command, arguments))
            store.save(configured)
        except Exception:
            try:
                store.save(previous)
            except OSError:
                pass
            raise
        return configured


def run_scheduled_crawl(schedule_file, config_file, task_id, *, runner=None, now=None):
    lease = CrawlRunLease(Path(schedule_file).parent / "scheduled-worker")
    if not lease.acquire():
        return 0
    try:
        return _run_scheduled_crawl_once(schedule_file, config_file, task_id, runner=runner, now=now)
    finally:
        lease.close()


def _run_scheduled_crawl_once(schedule_file, config_file, task_id, *, runner=None, now=None):
    """No window or modal confirmation: one daily run, status and reports on disk."""
    from jingxu.infrastructure.spider import SpiderConfigStore, SpiderRunner, SpiderRunResult
    store = DailyScheduleStore(schedule_file)
    schedule = store.load()
    if not schedule.enabled or not task_id or schedule.task_id != task_id:
        return 0
    now = now or datetime.now()
    today = now.date().isoformat()
    state = store.load_state()
    if state.get("attemptDate") == today:
        return 0
    config_store = SpiderConfigStore(Path(config_file))
    config = config_store.load()
    state = {"attemptDate": today, "startedAt": now.isoformat(timespec="seconds"),
             "status": "running", "message": "定时抓取已开始", "taskId": task_id}
    store.save_state(state)
    logs = store.path.parent / "scheduled-logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"daily-{now.strftime('%Y%m%d-%H%M%S')}.log"
    try:
        with log_path.open("a", encoding="utf-8") as log:
            def on_log(line):
                log.write(str(line) + "\n"); log.flush()
            result = (runner or SpiderRunner()).run(config, on_log=on_log)
    except Exception as error:
        result = SpiderRunResult(success=False, message=f"定时抓取失败（{type(error).__name__}），请查看运行日志。")
    if result.has_payload:
        try:
            config_store.save_result(result)
        except OSError:
            result = replace(result, success=False, message="抓取结果已生成，但最近结果缓存保存失败，请到报表目录查看文件。")
    state.update(finishedAt=datetime.now().isoformat(timespec="seconds"),
                 status="skipped" if result.message == RUN_BUSY_MESSAGE else
                        "complete" if result.success and result.crawl_complete else "partial" if result.has_payload else "failed",
                 message=result.message, excelPath=result.excel_path, logPath=str(log_path))
    store.save_state(state)
    return 0 if result.success else 1
