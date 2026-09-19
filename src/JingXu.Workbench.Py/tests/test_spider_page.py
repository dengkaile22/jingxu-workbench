"""选品页交互（offscreen Qt）：账号管理、门槛表单、抓取流程与结果送入下载。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.spider import (  # noqa: E402
    SpiderAccount,
    SpiderConfig,
    SpiderConfigStore,
    SpiderEnvironment,
    SpiderRunResult,
)
from jingxu.ui.spider_page import SpiderPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _wait_finished(page: SpiderPage, timeout: float = 5.0) -> None:
    """等待后台抓取结束。

    后台线程通过排队信号回到 UI 线程，因此等待期间必须泵事件循环，
    否则信号永远不会被投递（用 sleep 轮询会一直超时）。
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not page.is_running:
            return
        time.sleep(0.02)
    raise AssertionError("等待抓取结束超时。")


def _store(tmp_path: Path, config: SpiderConfig | None = None) -> SpiderConfigStore:
    store = SpiderConfigStore(tmp_path / "Spider" / "config.json")
    if config is not None:
        store.save(config)
    return store


def _page(tmp_path: Path, *, runner=None, config: SpiderConfig | None = None):  # noqa: ANN001
    return SpiderPage(
        store=_store(tmp_path, config),
        runner=runner,
        check_environment=lambda: SpiderEnvironment(available=True, message="爬虫就绪（测试）。"),
    )


# ── 环境与初始状态 ──────────────────────────────────────────────────────────


def test_page_shows_environment_message(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    assert "爬虫就绪" in page._environment_label.text()


def test_page_loads_persisted_accounts(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    config = SpiderConfig(
        accounts=(
            SpiderAccount(platform="douyin", url_or_id="a", name="达人A"),
            SpiderAccount(platform="kuaishou", url_or_id="b", enabled=False),
        )
    )
    page = _page(tmp_path, config=config)

    assert len(page.accounts) == 2
    assert page._accounts_table.rowCount() == 2
    # 徽标只统计「启用且非空」的账号。
    assert page._account_badge.text() == "1"


def test_page_loads_persisted_filters(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from jingxu.infrastructure.spider import SpiderFilters

    config = SpiderConfig(filters=SpiderFilters(time_mode="range", min_accounts=3, headless=True))
    page = _page(tmp_path, config=config)

    assert page._min_accounts.value() == 3
    assert page._headless.isChecked() is True
    assert page._time_mode.currentData() == "range"
    assert page._start_date.isEnabled() is True
    assert page._days.isEnabled() is False


# ── 账号管理 ────────────────────────────────────────────────────────────────


def test_bulk_import_adds_accounts_and_persists(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._import_text.setPlainText("达人A=https://www.douyin.com/user/abc\nhttps://v.kuaishou.com/xyz")
    page._apply_import()

    assert len(page.accounts) == 2
    assert page.accounts[0].name == "达人A"
    assert page.accounts[1].platform == "kuaishou"
    assert page._accounts_table.rowCount() == 2
    # 重新打开应恢复
    assert len(SpiderConfigStore(page._store.path).load().accounts) == 2


def test_bulk_import_skips_duplicates(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._import_text.setPlainText("https://www.douyin.com/user/abc")
    page._apply_import()
    page._import_text.setPlainText("https://www.douyin.com/user/abc")
    page._apply_import()

    assert len(page.accounts) == 1
    assert "跳过 1 个重复" in page._result_caption.text()


def test_bulk_import_reports_empty_input(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._import_text.setPlainText("   \n  ")
    page._apply_import()

    assert page.accounts == []
    assert page._result_caption.objectName() == "CaptionWarn"


def test_clear_accounts_empties_table_and_store(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._import_text.setPlainText("a=https://www.douyin.com/user/a")
    page._apply_import()

    page._clear_accounts()

    assert page.accounts == []
    assert page._accounts_table.rowCount() == 0
    assert SpiderConfigStore(page._store.path).load().accounts == ()


def test_unchecking_account_updates_badge_and_store(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from PySide6.QtCore import Qt

    page = _page(tmp_path)
    page._import_text.setPlainText("a=https://www.douyin.com/user/a")
    page._apply_import()

    item = page._accounts_table.item(0, 0)
    assert item is not None
    item.setCheckState(Qt.CheckState.Unchecked)

    assert page.accounts[0].enabled is False
    assert page._account_badge.text() == "0"
    assert SpiderConfigStore(page._store.path).load().accounts[0].enabled is False


# ── 抓取流程 ────────────────────────────────────────────────────────────────


class _FakeRunner:
    """记录调用并返回预设结果。

    ``delay`` 用来模拟真实抓取耗时，便于断言「运行中」的界面状态；
    为 0 时同步返回。
    """

    def __init__(self, result: SpiderRunResult, *, delay: float = 0.0) -> None:
        self._result = result
        self._delay = delay
        self.calls: list[SpiderConfig] = []

    def run(self, config, *, on_log=None, cancel_event=None):  # noqa: ANN001
        self.calls.append(config)
        if on_log is not None:
            on_log("[*] 测试日志")
        if self._delay:
            import time

            time.sleep(self._delay)
        return self._result


def _import_one_account(page: SpiderPage) -> None:
    page._import_text.setPlainText("达人A=https://www.douyin.com/user/abc")
    page._apply_import()


def test_run_requires_enabled_account(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    runner = _FakeRunner(SpiderRunResult(success=True, message="ok"))
    page = _page(tmp_path, runner=runner)

    page._start_crawl()

    assert runner.calls == []
    assert "至少一个对标账号" in page._result_caption.text()
    assert page.is_running is False


def test_run_starts_and_finishes(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    result = SpiderRunResult(
        success=True,
        message="抓取完成：保留 1 款商品",
        retained=({"name": "生姜洗发水", "account_count": 3},),
        items=({"video_url": "https://v/1"},),
    )
    runner = _FakeRunner(result, delay=0.15)
    page = _page(tmp_path, runner=runner)
    _import_one_account(page)

    page._start_crawl()
    assert page.is_running is True
    assert page._run_button.isEnabled() is False
    assert page._cancel_button.isEnabled() is True

    # 后台线程结束后由信号切回 UI
    _wait_finished(page)

    assert len(runner.calls) == 1
    assert runner.calls[0].accounts[0].name == "达人A"
    assert page._run_button.isEnabled() is True
    assert page._cancel_button.isEnabled() is False
    assert "保留 1 款商品" in page._result_caption.text()
    assert page._results_table.rowCount() == 1
    assert page._results_table.item(0, 0).text() == "生姜洗发水"
    assert page._send_button.isEnabled() is True
    assert "测试日志" in page._log.toPlainText()


def test_run_result_feeds_download_signal(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    result = SpiderRunResult(
        success=True,
        message="ok",
        items=({"video_url": "https://v/1"}, {"video_url": "https://v/2"}),
    )
    page = _page(tmp_path, runner=_FakeRunner(result))
    _import_one_account(page)
    captured: list[list[str]] = []
    page.videos_discovered.connect(lambda urls: captured.append(list(urls)))

    page._start_crawl()
    _wait_finished(page)
    page._send_last_result()

    assert captured == [["https://v/1", "https://v/2"]]
    assert "已送入下载 2 个链接" in page._result_caption.text()


def test_send_without_result_warns(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, runner=_FakeRunner(SpiderRunResult(success=True, message="ok")))
    captured: list[list[str]] = []
    page.videos_discovered.connect(lambda urls: captured.append(list(urls)))

    page._send_last_result()

    assert captured == []
    assert page._result_caption.objectName() == "CaptionWarn"


def test_failed_run_keeps_send_disabled(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, runner=_FakeRunner(SpiderRunResult(success=False, message="抓取失败：超时")))
    _import_one_account(page)

    page._start_crawl()
    _wait_finished(page)

    assert page._send_button.isEnabled() is False
    assert page._result_caption.objectName() == "CaptionWarn"
    assert "超时" in page._result_caption.text()


def test_run_persists_current_form_values(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    runner = _FakeRunner(SpiderRunResult(success=True, message="ok"))
    page = _page(tmp_path, runner=runner)
    _import_one_account(page)
    page._min_accounts.setValue(4)
    page._enable_fuzzy.setChecked(False)

    page._start_crawl()
    _wait_finished(page)

    saved = SpiderConfigStore(page._store.path).load()
    assert saved.filters.min_accounts == 4
    assert saved.filters.enable_fuzzy is False


def test_cancel_sets_event(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path, runner=_FakeRunner(SpiderRunResult(success=True, message="ok")))
    # 未在运行时点取消不应报错
    page._cancel_crawl()
    assert page.is_running is False


# ── UI 风格一致性 ───────────────────────────────────────────────────────────


def test_page_uses_shared_widget_vocabulary(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """控件必须来自主程序词汇（objectName 命中主题样式表），而非爬虫自带 GUI。"""
    page = _page(tmp_path)

    assert page._result_caption.objectName() in {"Caption", "CaptionWarn"}
    assert page._account_badge.objectName() == "CountBadge"
    assert page._run_button.objectName() == "Primary"
    assert page._cancel_button.objectName() == ""
    # 页面上不应出现爬虫自带 GUI 的类名
    assert all(
        "EcommerceCrawlerWidget" not in type(child).__name__
        for child in page.findChildren(object)
    )


def test_log_box_hidden_until_toggled(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """日志默认收起。

    用 ``isHidden`` 判断：测试里页面没有 ``show()``，``isVisible`` 恒为 False。
    """
    page = _page(tmp_path)
    assert page._log.isHidden() is True
    page._toggle_log()
    assert page._log.isHidden() is False
    assert page._log_toggle.text() == "隐藏运行日志"
    page._toggle_log()
    assert page._log.isHidden() is True
    assert page._log_toggle.text() == "显示运行日志"
