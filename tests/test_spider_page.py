"""选品页交互（offscreen Qt）：账号管理、门槛表单、抓取流程与结果送入下载。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from jingxu.infrastructure import spider as spider_service  # noqa: E402
from jingxu.infrastructure.spider import (  # noqa: E402
    SpiderAccount,
    SpiderConfig,
    SpiderConfigStore,
    SpiderEnvironment,
    SpiderRunResult,
)
from jingxu.ui.spider_page import (  # noqa: E402
    RESULT_CHECK_COLUMN,
    RESULT_NAME_COLUMN,
    SpiderPage,
)


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


def test_accounts_can_be_exported_in_reimportable_text_format(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    config = SpiderConfig(
        accounts=(
            SpiderAccount(platform="douyin", url_or_id="https://www.douyin.com/user/a", name="达人A"),
            SpiderAccount(platform="kuaishou", url_or_id="https://www.kuaishou.com/profile/b", enabled=False),
        )
    )
    page = _page(tmp_path, config=config)
    target = tmp_path / "accounts.txt"
    monkeypatch.setattr(
        "jingxu.ui.spider_page.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(target), "文本文件 (*.txt)"),
    )

    page._export_accounts()

    assert target.read_text(encoding="utf-8").splitlines() == [
        "达人A=https://www.douyin.com/user/a",
        "https://www.kuaishou.com/profile/b",
    ]


def test_bulk_import_skips_account_urls_with_tracking_variants(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(
        tmp_path,
        config=SpiderConfig(
            accounts=(SpiderAccount(platform="douyin", url_or_id="https://www.douyin.com/user/abc/"),)
        ),
    )
    page._import_text.setPlainText("https://www.douyin.com/user/abc?from=share")

    page._apply_import()

    assert len(page.accounts) == 1
    assert "跳过 1 个重复" in page._result_caption.text()


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
        retained=({"name": "生姜洗发水", "account_count": 3, "sample_video_url": "https://v/1"},),
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
    assert page._results_table.item(0, RESULT_NAME_COLUMN).text() == "生姜洗发水"
    assert page._send_button.isEnabled() is True
    assert "测试日志" in page._log.toPlainText()


def test_run_result_feeds_download_signal(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    result = SpiderRunResult(
        success=True,
        message="ok",
        retained=({"video_url": "https://v/1"}, {"video_url": "https://v/2"}),
        items=({"video_url": "https://v/rejected"},),
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


def test_locked_profile_can_be_closed_after_user_confirmation(
    qapp, tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    runner = _FakeRunner(SpiderRunResult(success=True, message="ok"))
    page = _page(tmp_path, runner=runner)
    _import_one_account(page)
    terminated: list[bool] = []
    questions: list[str] = []
    busy = spider_service.ProfileLockState(busy=True, holder_pids=(321, 654))
    free = spider_service.ProfileLockState(busy=False)

    monkeypatch.setattr(
        spider_service,
        "profile_lock_state",
        lambda **_kwargs: free if terminated else busy,
    )
    monkeypatch.setattr(
        spider_service,
        "terminate_profile_holders",
        lambda: (terminated.append(True), ())[1],
        raising=False,
    )

    def confirm(*args, **kwargs):  # noqa: ANN002, ANN003
        questions.append(str(args[2]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)

    page._start_crawl()
    _wait_finished(page)

    assert terminated == [True]
    assert questions and "321" in questions[0] and "654" in questions[0]
    assert len(runner.calls) == 1


def test_locked_profile_remains_untouched_when_user_declines(
    qapp, tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    runner = _FakeRunner(SpiderRunResult(success=True, message="ok"))
    page = _page(tmp_path, runner=runner)
    _import_one_account(page)
    terminated: list[bool] = []
    busy = spider_service.ProfileLockState(busy=True, holder_pids=(321,))
    monkeypatch.setattr(spider_service, "profile_lock_state", lambda **_kwargs: busy)
    monkeypatch.setattr(
        spider_service,
        "terminate_profile_holders",
        lambda: terminated.append(True),
        raising=False,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )

    page._start_crawl()

    assert terminated == []
    assert runner.calls == []
    assert page.is_running is False


def test_locked_profile_does_not_start_if_confirmed_close_fails(
    qapp, tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    runner = _FakeRunner(SpiderRunResult(success=True, message="ok"))
    page = _page(tmp_path, runner=runner)
    _import_one_account(page)
    busy = spider_service.ProfileLockState(busy=True, holder_pids=(321,))
    monkeypatch.setattr(spider_service, "profile_lock_state", lambda **_kwargs: busy)
    monkeypatch.setattr(spider_service, "terminate_profile_holders", lambda: (321,))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    page._start_crawl()

    assert runner.calls == []
    assert page.is_running is False
    assert "仍有进程无法关闭" in page._result_caption.text()


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
    assert page._log_toggle.text() == "📋 运行日志"  # 收起态用 .NET 的区块名
    page._toggle_log()
    assert page._log.isHidden() is False
    assert page._log_toggle.text() == "隐藏运行日志"
    page._toggle_log()
    assert page._log.isHidden() is True
    assert page._log_toggle.text() == "📋 运行日志"


# ── 结果落盘与恢复 ──────────────────────────────────────────────────────────


def _two_product_result() -> SpiderRunResult:
    return SpiderRunResult(
        success=True,
        message="抓取完成：保留 2 款商品",
        finished_at="2026-09-19T22:50:00",
        retained=(
            {"name": "商品A", "account_count": 3, "total_occurrences": 5, "video_url": "https://v/a"},
            {"name": "商品B", "account_count": 2, "video_url": "https://v/b"},
        ),
    )


def test_finished_run_is_persisted(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)

    page._on_run_finished(_two_product_result())

    restored = SpiderConfigStore(page._store.path).load_result()
    assert restored is not None
    assert len(restored.retained) == 2


def test_page_restores_last_result(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """抓取耗时以分钟计，重开应用应看到上次结果而不是空表。"""
    store = _store(tmp_path)
    store.save_result(_two_product_result())

    page = SpiderPage(
        store=store,
        check_environment=lambda: SpiderEnvironment(available=True, message="就绪"),
    )

    assert page._results_table.rowCount() == 2
    assert "上次抓取（09-19 22:50）" in page._result_caption.text()
    assert page.last_result is not None
    assert page._send_button.isEnabled() is True


def test_page_without_saved_result_stays_empty(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    assert page._results_table.rowCount() == 0
    assert page.last_result is None
    assert page._send_button.isEnabled() is False


# ── 结果勾选：只送选中商品 ──────────────────────────────────────────────────


def test_results_carry_checkboxes_selected_by_default(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from PySide6.QtCore import Qt

    page = _page(tmp_path)
    page._on_run_finished(_two_product_result())

    for row in range(page._results_table.rowCount()):
        item = page._results_table.item(row, RESULT_CHECK_COLUMN)
        assert item is not None
        assert item.checkState() == Qt.CheckState.Checked
    assert "已选 2/2 款" in page._selection_caption.text()


def test_unchecking_row_narrows_selection_and_send(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """此前「结果送入下载」强制全发，无法只下载其中几款。"""
    from PySide6.QtCore import Qt

    page = _page(tmp_path)
    page._on_run_finished(_two_product_result())
    captured: list[list[str]] = []
    page.videos_discovered.connect(lambda urls: captured.append(list(urls)))

    page._results_table.item(1, RESULT_CHECK_COLUMN).setCheckState(Qt.CheckState.Unchecked)
    page._send_last_result()

    assert captured == [["https://v/a"]]
    assert "已送入下载 1 个链接" in page._result_caption.text()


def test_select_all_becomes_partial_then_checked(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """全选框必须与行状态同步，否则再点它不触发信号、看起来像坏了。"""
    from PySide6.QtCore import Qt

    page = _page(tmp_path)
    page._on_run_finished(_two_product_result())

    page._results_table.item(1, RESULT_CHECK_COLUMN).setCheckState(Qt.CheckState.Unchecked)
    assert page._select_all.checkState() == Qt.CheckState.PartiallyChecked

    page._select_all.click()  # 部分选中时点击 = 全选
    assert page._select_all.checkState() == Qt.CheckState.Checked
    assert "已选 2/2 款" in page._selection_caption.text()


def test_select_all_clears_selection(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from PySide6.QtCore import Qt

    page = _page(tmp_path)
    page._on_run_finished(_two_product_result())

    page._select_all.click()  # 已全选时点击 = 清空
    assert page._select_all.checkState() == Qt.CheckState.Unchecked
    assert "已选 0/2 款" in page._selection_caption.text()


def test_send_with_nothing_checked_warns(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._on_run_finished(_two_product_result())
    captured: list[list[str]] = []
    page.videos_discovered.connect(lambda urls: captured.append(list(urls)))

    page._select_all.click()  # 清空全部
    page._send_last_result()

    assert captured == []
    assert page._result_caption.objectName() == "CaptionWarn"
    assert "勾选" in page._result_caption.text()


def test_bad_date_range_blocks_run(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """日期格式错误应在本地拦下，不启动浏览器。"""
    from jingxu.infrastructure.spider import SpiderFilters

    runner = _FakeRunner(SpiderRunResult(success=True, message="ok"))
    config = SpiderConfig(
        accounts=(SpiderAccount(platform="douyin", url_or_id="a"),),
        filters=SpiderFilters(time_mode="range", start_date="2026/01/01"),
    )
    page = _page(tmp_path, runner=runner, config=config)

    page._start_crawl()

    assert runner.calls == []
    assert "YYYY-MM-DD" in page._result_caption.text()


def test_results_stay_empty_when_nothing_retained(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """没有达标商品时保持空表并禁用发送，恢复结果后也不能绕过筛选。"""
    page = _page(tmp_path)
    page._on_run_finished(
        SpiderRunResult(
            success=True,
            message="无保留商品",
            items=({"video_url": "https://v/only"},),
        )
    )

    assert page._results_table.rowCount() == 0
    assert page._send_button.isEnabled() is False
    assert "没有符合当前筛选条件" in page._result_caption.text()
    captured = []
    page.videos_discovered.connect(captured.append)
    page._send_last_result()
    assert captured == []
    restored = _page(tmp_path)
    assert restored._results_table.rowCount() == 0
    assert restored._send_button.isEnabled() is False


def test_result_table_shows_dash_for_missing_counts(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._on_run_finished(
        SpiderRunResult(success=True, message="ok", retained=({"name": "只有名字"},))
    )

    assert page._results_table.item(0, RESULT_NAME_COLUMN).text() == "只有名字"
    # 缺失值显示破折号，便于分辨「没有」与「取不到」
    assert page._results_table.item(0, RESULT_NAME_COLUMN + 1).text() == "—"


# ── 扫码登录入口（此前 CLI 有 --login，但界面没有入口）──────────────────────


def test_login_buttons_exist_for_both_platforms(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    assert set(page._login_buttons) == {"douyin", "kuaishou"}
    assert "抖音" in page._login_buttons["douyin"].text()
    assert "快手" in page._login_buttons["kuaishou"].text()


def test_login_status_reports_browser_and_profile(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from pathlib import Path as _Path

    monkeypatch.setattr(
        spider_service, "find_browser", lambda: _Path("C:/fake/msedge.exe")
    )
    monkeypatch.setattr(spider_service, "profile_status", lambda: (True, "浏览器档案已存在"))

    page = _page(tmp_path)
    page._refresh_login_status()

    assert "msedge.exe" in page._login_status.text()
    assert "浏览器档案已存在" in page._login_status.text()


def test_missing_browser_disables_login_with_warning(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """找不到浏览器时抓取必然失败，必须提前提示并禁用入口。"""
    monkeypatch.setattr(spider_service, "find_browser", lambda: None)

    page = _page(tmp_path)
    page._refresh_login_status()

    assert page._login_status.objectName() == "CaptionWarn"
    assert "未找到 Chrome/Edge" in page._login_status.text()
    assert all(not button.isEnabled() for button in page._login_buttons.values())


def test_login_opens_window_and_offers_finish(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """登录不能再依赖爬虫 CLI 的 --login：它的 input() 在无终端时立即失败。"""

    class _FakeSession:
        platform_label = "抖音"

        def is_running(self) -> bool:
            return True

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        spider_service, "open_login_window", lambda platform: _FakeSession()
    )

    page = _page(tmp_path)
    assert page._login_done.isEnabled() is False
    page._open_login("douyin")

    assert "已打开抖音登录页" in page._result_caption.text()
    assert "我已登录" in page._result_caption.text()
    assert page._result_caption.objectName() == "Caption"
    # 必须等用户确认后才能保存登录态
    assert page._login_done.isEnabled() is True


def test_finish_login_closes_browser_and_reports(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """关闭浏览器才会把 Cookie 落盘，因此「我已登录」必须真的 close()。"""
    closed: list[bool] = []

    class _FakeSession:
        platform_label = "快手"

        def is_running(self) -> bool:
            return True

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        spider_service, "open_login_window", lambda platform: _FakeSession()
    )

    page = _page(tmp_path)
    page._open_login("kuaishou")
    page._finish_login()

    assert closed == [True]
    assert page._login_session is None
    assert page._login_done.isEnabled() is False
    assert "快手登录态已保存" in page._result_caption.text()


def test_finish_login_without_session_is_safe(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._finish_login()
    assert page._login_done.isEnabled() is False


def test_login_failure_is_reported_not_raised(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    def _boom(platform: str):  # noqa: ANN202
        raise spider_service.SpiderError("未找到 Chromium 内核浏览器。")

    monkeypatch.setattr(spider_service, "open_login_window", _boom)

    page = _page(tmp_path)
    page._open_login("kuaishou")

    assert "未找到 Chromium" in page._result_caption.text()
    assert page._result_caption.objectName() == "CaptionWarn"
    assert page._login_done.isEnabled() is False


def test_login_reuses_open_window(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """登录窗口已开着时不应重复弹出第二个。"""
    opened: list[str] = []

    class _FakeSession:
        platform_label = "抖音"

        def is_running(self) -> bool:
            return True

    def _open(platform: str):  # noqa: ANN202
        opened.append(platform)
        return _FakeSession()

    monkeypatch.setattr(spider_service, "open_login_window", _open)

    page = _page(tmp_path)
    page._open_login("douyin")
    page._open_login("douyin")

    assert opened == ["douyin"]
    assert "已打开" in page._result_caption.text()


def test_shutdown_closes_login_window(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """不清理的话，关掉应用后扫码浏览器会残留在后台。"""
    closed: list[bool] = []

    class _FakeSession:
        platform_label = "抖音"

        def is_running(self) -> bool:
            return True

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        spider_service, "open_login_window", lambda platform: _FakeSession()
    )
    page = _page(tmp_path)
    page._open_login("douyin")

    page.shutdown()

    assert closed == [True]
    assert page._login_session is None


def test_release_profile_button_cleans_and_updates_status(qapp, tmp_path: Path, monkeypatch) -> None:
    terminated = []
    monkeypatch.setattr(spider_service, "terminate_profile_holders", lambda: terminated.append(True) or ())
    page = _page(tmp_path)
    page._release_profile_btn.click()
    assert terminated == [True]
    assert "成功释放" in page._result_caption.text()


def test_open_login_prompts_when_busy_and_closes_holders(qapp, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    page = _page(tmp_path)

    terminated = []
    busy = [True]

    def _fake_terminate():
        terminated.append(True)
        busy[0] = False
        return ()

    monkeypatch.setattr(spider_service, "terminate_profile_holders", _fake_terminate)
    monkeypatch.setattr(
        spider_service,
        "profile_lock_state",
        lambda **kwargs: spider_service.ProfileLockState(
            busy=busy[0], holder_pids=(8888,) if busy[0] else ()
        ),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    opened = []

    class _FakeSession:
        platform_label = "抖音"

        def is_running(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr(
        spider_service,
        "open_login_window",
        lambda platform: opened.append(platform) or _FakeSession(),
    )

    page._open_login("douyin")

    assert terminated == [True]
    assert opened == ["douyin"]
    assert "已打开抖音登录页" in page._result_caption.text()


def test_shutdown_cancels_running_crawl(qapp, tmp_path: Path) -> None:
    import time

    class _SlowRunner:
        def run(self, config, *, on_log=None, cancel_event=None):  # noqa: ANN001
            time.sleep(1.5)
            return SpiderRunResult(success=False, message="已取消。")

    page = _page(tmp_path, runner=_SlowRunner())
    _import_one_account(page)
    page._start_crawl()
    assert page.is_running is True

    page.shutdown()

    assert page._cancel.is_set() is True


def test_shutdown_is_safe_without_session_or_run(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page.shutdown()  # 不应抛异常


# ── 抓取完成但零结果时的提示 ────────────────────────────────────────────────


def test_empty_success_result_explains_likely_causes(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「累计发现带货商品 0 件」时只说「抓取完成」会让人以为程序坏了。"""
    page = _page(tmp_path)

    page._on_run_finished(
        SpiderRunResult(success=True, message="抓取完成：保留 0 款商品，共 0 条带货记录。")
    )

    caption = page._result_caption.text()
    assert page._result_caption.objectName() == "CaptionWarn"
    assert "没有发现有带货商品的视频" in caption
    assert "时间范围" in caption
    assert page._send_button.isEnabled() is False


def test_nonempty_result_keeps_plain_message(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._on_run_finished(_two_product_result())

    assert "保留 2 款商品" in page._result_caption.text()
    assert page._result_caption.objectName() == "Caption"


def test_failed_run_keeps_failure_message(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._on_run_finished(SpiderRunResult(success=False, message="抓取失败：超时，已终止。"))

    assert "抓取失败" in page._result_caption.text()
    assert "没有发现有带货商品" not in page._result_caption.text()


# ── 单条添加对标账号（对齐 .NET「添加对标账号」）──────────────────────────


def test_single_add_detects_platform_from_link(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """默认必须自动识别平台。

    此前下拉框默认「抖音」被当成强制平台，粘贴快手链接会被存成抖音账号。
    """
    page = _page(tmp_path)
    assert page._platform_combo.currentData() == ""

    page._account_input.setText(
        "https://v.kuaishou.com/KoL53UgI 看了这么多快手，还是「牛奶巧巧」最好玩了！"
    )
    page._add_single_account()

    assert len(page.accounts) == 1
    assert page.accounts[0].platform == "kuaishou"
    assert page.accounts[0].name == "牛奶巧巧"


def test_single_add_accepts_douyin_link(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._account_input.setText("https://www.douyin.com/user/MS4wLjABAAAAxyz")
    page._add_single_account()

    assert page.accounts[0].platform == "douyin"


def test_single_add_honours_manual_platform(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """手动选平台时应覆盖自动识别（用于纯 ID 这类无法判断的输入）。"""
    page = _page(tmp_path)
    page._platform_combo.setCurrentIndex(page._platform_combo.findData("kuaishou"))
    page._account_input.setText("abc123")
    page._add_single_account()

    assert page.accounts[0].platform == "kuaishou"


def test_single_add_applies_note_name(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._account_input.setText("https://www.douyin.com/user/MS4wLjABAAAAxyz")
    page._account_name_input.setText("达人A")
    page._add_single_account()

    assert page.accounts[0].name == "达人A"
    # 输入框应清空，便于连续添加
    assert page._account_input.text() == ""
    assert page._account_name_input.text() == ""


def test_single_add_rejects_duplicate(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._account_input.setText("https://v.kuaishou.com/KoL53UgI")
    page._add_single_account()
    page._account_input.setText("https://v.kuaishou.com/KoL53UgI")
    page._add_single_account()

    assert len(page.accounts) == 1
    assert page._result_caption.objectName() == "CaptionWarn"
    assert "已在列表中" in page._result_caption.text()


def test_single_add_warns_on_empty_input(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._account_input.setText("   ")
    page._add_single_account()

    assert page.accounts == []
    assert page._result_caption.objectName() == "CaptionWarn"
    assert "请输入" in page._result_caption.text()


def test_single_add_persists(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(tmp_path)
    page._account_input.setText("https://www.douyin.com/user/MS4wLjABAAAAxyz")
    page._add_single_account()

    assert len(SpiderConfigStore(page._store.path).load().accounts) == 1


def test_spider_page_matches_net_wording(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """关键文案对齐 .NET SpiderView。"""
    page = _page(tmp_path)

    assert page._import_toggle.text() == "批量导入"
    assert page._enable_fuzzy.text() == "开启智能去噪与同款商品模糊合并"
    assert page._platform_combo.itemText(0) == "自动识别"


def test_accounts_table_keeps_readable_minimum_width(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """实测窄窗口下「平台」列被挤没，账号串到链接列，看着像平台识别错了。"""
    from jingxu.ui.spider_page import ACCOUNT_COLUMN_WIDTHS

    page = _page(tmp_path)
    assert page._accounts_table.minimumWidth() >= sum(ACCOUNT_COLUMN_WIDTHS)


def test_results_table_keeps_readable_minimum_width(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from jingxu.ui.spider_page import RESULT_COLUMN_WIDTHS

    page = _page(tmp_path)
    assert page._results_table.minimumWidth() >= sum(RESULT_COLUMN_WIDTHS)


# ── 爬虫诊断透出到界面 ──────────────────────────────────────────────────────


def test_diagnostics_view_parses_payload() -> None:
    """爬虫写入 --json-out 的 diagnostics 段应被解析成界面可用的视图。"""
    from jingxu.infrastructure.spider import SpiderDiagnosticsView

    view = SpiderDiagnosticsView.from_payload(
        {
            "extraction": {"videosScanned": 57, "videosWithProducts": 0},
            "issues": [
                {
                    "level": "blocker",
                    "code": "no_products",
                    "message": "一个带货商品都没提取到",
                    "suggestion": "换有带货的账号",
                }
            ],
            "loginState": {"douyin": {"status": "required"}},
        }
    )
    assert view is not None
    assert view.videos_scanned == 57
    assert view.blocked is True
    assert "带货商品" in view.blocking_message
    assert "换有带货的账号" in view.blocking_message
    assert view.login_states == (("douyin", "required"),)


def test_diagnostics_view_ignores_empty_payload() -> None:
    from jingxu.infrastructure.spider import SpiderDiagnosticsView

    assert SpiderDiagnosticsView.from_payload(None) is None
    assert SpiderDiagnosticsView.from_payload({}) is None


def test_blocking_diagnosis_is_shown_instead_of_completion_message(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """环境/登录/提取异常必须压过「抓取完成」，否则用户要从日志里找原因。"""
    from jingxu.infrastructure.spider import SpiderDiagnosticsView

    page = _page(tmp_path)
    result = SpiderRunResult(
        success=True,
        message="抓取完成：保留 0 款商品，共 0 条带货记录。",
        diagnostics=SpiderDiagnosticsView(
            issues=(
                {
                    "level": "blocker",
                    "code": "no_products",
                    "message": "一个带货商品都没提取到",
                    "suggestion": "请把 [未提取到商品] 日志行提供给开发者",
                },
            ),
            videos_scanned=57,
        ),
    )

    page._on_run_finished(result)

    caption = page._result_caption.text()
    assert "✗" in caption
    assert "一个带货商品都没提取到" in caption
    assert "提供给开发者" in caption
    assert page._result_caption.objectName() == "CaptionWarn"
    # 扫描统计也一并展示
    assert "扫描 57 个视频" in page._export_label.text()


def test_warning_diagnosis_uses_normal_style(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    from jingxu.infrastructure.spider import SpiderDiagnosticsView

    page = _page(tmp_path)
    page._on_run_finished(
        SpiderRunResult(
            success=True,
            message="ok",
            retained=({"name": "A"},),
            diagnostics=SpiderDiagnosticsView(
                issues=({"level": "warning", "code": "no_retained", "message": "没有交集", "suggestion": "增加账号"},),
                videos_scanned=10,
                videos_with_products=4,
            ),
        )
    )

    assert page._result_caption.objectName() == "Caption"
    assert "!" in page._result_caption.text()
