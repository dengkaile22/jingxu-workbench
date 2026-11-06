"""Daily scheduling configuration, native task definitions and unattended runs."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from jingxu.infrastructure import spider as service
from jingxu.infrastructure import spider_schedule as schedules
from jingxu.infrastructure.spider_schedule import (
    DailySchedule, DailyScheduleStore, CrawlRunLease, WindowsDailyTaskScheduler,
    RUN_BUSY_MESSAGE, run_scheduled_crawl, scheduled_command, task_xml,
)


def configured(tmp_path, *, clock="02:30"):
    store = DailyScheduleStore(tmp_path / "Spider/daily_schedule.json")
    schedule = DailySchedule(True, clock, "test-daily-id")
    store.save(schedule)
    config_store = service.SpiderConfigStore(tmp_path / "Spider/config.json")
    config_store.save(service.SpiderConfig(accounts=(service.SpiderAccount("douyin", "test-author"),),
        report_tasks=(service.SpiderFilters(filter_by="accounts"),)))
    return store, schedule, config_store


def test_schedule_and_next_daily_time_survive_reload(tmp_path):
    store, schedule, _ = configured(tmp_path)
    assert store.load() == schedule
    assert schedule.next_run(datetime(2026, 10, 4, 1, 30)) == datetime(2026, 10, 4, 2, 30)
    assert schedule.next_run(datetime(2026, 10, 4, 3, 30)) == datetime(2026, 10, 5, 2, 30)
    assert DailySchedule.from_dict({"time": "99:99"}).time == "02:00"


def test_native_task_is_daily_interactive_nonoverlapping_and_unlimited(tmp_path):
    store, schedule, cfg = configured(tmp_path)
    command, args = scheduled_command(schedule, store, cfg.path, executable="C:/Program Files/清影/清影.exe", frozen=True)
    xml = ET.fromstring(task_xml(schedule, command, args, now=datetime(2026, 10, 4, 1)))
    ns = {"t": schedules.TASK_NAMESPACE}
    assert xml.findtext("t:Triggers/t:CalendarTrigger/t:ScheduleByDay/t:DaysInterval", namespaces=ns) == "1"
    assert xml.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=ns) == "IgnoreNew"
    assert xml.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=ns) == "PT0S"
    assert xml.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) == "InteractiveToken"
    assert "--scheduled-spider" in xml.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns)
    assert "--schedule-id" in args and "test-daily-id" in args


def test_native_registration_and_saved_setting_are_transactional(tmp_path, monkeypatch):
    store, previous, cfg = configured(tmp_path)
    scheduler = WindowsDailyTaskScheduler()
    calls = []
    def register(name, xml="", operation="register"):
        assert store.load().enabled is False
        calls.append((name, xml, operation))
    monkeypatch.setattr(scheduler, "_invoke", register)
    changed = scheduler.configure(DailySchedule(True, "05:15", previous.task_id), store, cfg.path)
    assert changed.time == "05:15" and store.load().enabled
    assert calls[0][0].startswith("JingXu-Spider-Daily-")
    monkeypatch.setattr(scheduler, "_invoke", lambda *_args, **_kwargs: (_ for _ in ()).throw(schedules.ScheduleError("synthetic")))
    with pytest.raises(schedules.ScheduleError):
        scheduler.configure(DailySchedule(True, "08:00", changed.task_id), store, cfg.path)
    assert store.load() == changed


def test_disable_prevents_crawl_even_when_native_task_delete_fails(tmp_path, monkeypatch):
    store, schedule, cfg = configured(tmp_path)
    scheduler = WindowsDailyTaskScheduler()
    monkeypatch.setattr(scheduler, "_invoke", lambda *_args, **_kwargs: (_ for _ in ()).throw(schedules.ScheduleError("synthetic")))
    with pytest.raises(schedules.ScheduleError):
        scheduler.configure(DailySchedule(False, schedule.time, schedule.task_id), store, cfg.path)
    assert store.load().enabled is False
    assert run_scheduled_crawl(store.path, cfg.path, schedule.task_id, runner=SimpleNamespace(run=lambda *_args, **_kwargs: pytest.fail("disabled job ran"))) == 0


def test_daily_run_saves_report_and_result_without_ui_and_runs_once_per_day(tmp_path):
    store, schedule, cfg = configured(tmp_path)
    calls = []
    excel = tmp_path / "daily-report.xlsx"; excel.write_bytes(b"synthetic report")
    result = service.SpiderRunResult(True, "定时完成", retained=({"商品名称": "测试商品"},), excel_path=str(excel))
    def run(config, *, on_log):
        calls.append(config)
        on_log("synthetic safe log")
        return result
    runner = SimpleNamespace(run=run)
    assert run_scheduled_crawl(store.path, cfg.path, schedule.task_id, runner=runner, now=datetime(2026, 10, 4, 2, 30)) == 0
    assert cfg.load_result().excel_path == str(excel)
    assert store.load_state()["status"] == "complete"
    assert Path(store.load_state()["logPath"]).read_text(encoding="utf-8") == "synthetic safe log\n"
    assert run_scheduled_crawl(store.path, cfg.path, schedule.task_id, runner=runner, now=datetime(2026, 10, 4, 3, 30)) == 0
    assert len(calls) == 1
    assert run_scheduled_crawl(store.path, cfg.path, schedule.task_id, runner=runner, now=datetime(2026, 10, 5, 2, 30)) == 0
    assert len(calls) == 2


def test_busy_manual_job_is_skipped_without_overlapping(tmp_path):
    store, schedule, cfg = configured(tmp_path)
    result = service.SpiderRunResult(False, RUN_BUSY_MESSAGE, crawl_complete=False)
    assert run_scheduled_crawl(store.path, cfg.path, schedule.task_id, runner=SimpleNamespace(run=lambda *_args, **_kwargs: result)) == 1
    assert store.load_state()["status"] == "skipped"
    lease = CrawlRunLease(tmp_path / "mutual-exclusion")
    other = CrawlRunLease(tmp_path / "mutual-exclusion")
    assert lease.acquire() and not other.acquire()
    lease.close()
    assert other.acquire(); other.close()


def test_scheduled_entry_returns_before_importing_ui(tmp_path, monkeypatch):
    from jingxu import __main__
    calls = []
    monkeypatch.setattr(schedules, "run_scheduled_crawl", lambda *args: calls.append(args) or 0)
    assert __main__.main(["--scheduled-spider", "--schedule-file", str(tmp_path / "daily.json"),
                        "--spider-config", str(tmp_path / "config.json"), "--schedule-id", "daily-id"]) == 0
    assert calls[0][-1] == "daily-id"


def test_schedule_dialog_and_button_exist_and_duplicate_filters_are_removed(qapp, tmp_path):
    from jingxu.ui.spider_page import SpiderPage
    from jingxu.ui.spider_schedule_dialog import SpiderScheduleDialog
    view = SpiderPage(store=service.SpiderConfigStore(tmp_path / "Spider/config.json"),
                      check_environment=lambda: service.SpiderEnvironment(True, "test"))
    try:
        assert view._schedule_button.text() == "定时抓取"
        assert view._tasks_table.rowCount() == 3
        assert not hasattr(view, "_multi_reports") and not hasattr(view, "_time_mode")
        dialog = SpiderScheduleDialog(DailySchedule(True, "04:20"), view)
        assert dialog.schedule().time == "04:20"
        assert dialog.schedule().enabled
        dialog._enabled.setChecked(False)
        assert not dialog.schedule().enabled
        dialog.close()
    finally:
        view.shutdown()


def test_ui_schedule_save_persists_current_tasks_and_returns_from_worker(qapp, tmp_path):
    from PySide6.QtWidgets import QApplication
    from jingxu.ui.spider_page import SpiderPage
    import time
    store, schedule, cfg = configured(tmp_path)
    calls = []
    class Scheduler:
        def configure(self, selected, schedule_store, config_path):
            saved = service.SpiderConfigStore(config_path).load()
            calls.append(saved)
            schedule_store.save(selected)
            return selected
    view = SpiderPage(store=cfg, schedule_store=store, scheduler=Scheduler(),
                      check_environment=lambda: service.SpiderEnvironment(True, "test"))
    try:
        view._task_widgets["accounts"]["threshold"].setValue(9)
        view._save_schedule(schedule)
        deadline = time.monotonic() + 3
        while view._schedule_busy and time.monotonic() < deadline:
            QApplication.processEvents(); time.sleep(.01)
        assert not view._schedule_busy and view._schedule_button.isEnabled()
        assert calls[0].report_tasks[0].min_accounts == 9
        assert "02:30" in view._schedule_caption.text()
    finally:
        view.shutdown()


def test_manual_start_leaves_running_scheduled_job_untouched(qapp, tmp_path, monkeypatch):
    from jingxu.ui.spider_page import SpiderPage
    lease = CrawlRunLease()
    assert lease.acquire()
    view = SpiderPage(store=service.SpiderConfigStore(tmp_path / "config.json"),
                      check_environment=lambda: service.SpiderEnvironment(True, "test"))
    monkeypatch.setattr(service, "terminate_profile_holders", lambda: pytest.fail("scheduled browser was terminated"))
    try:
        view._start_crawl()
        assert not view.is_running and RUN_BUSY_MESSAGE in view._result_caption.text()
    finally:
        lease.close(); view.shutdown()
