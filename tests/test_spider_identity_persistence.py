"""Resolved account identity survives the CLI, UI, and saved configuration."""

from __future__ import annotations

import os

import pytest
from jingxu.infrastructure.spider import (
    SpiderAccount,
    SpiderConfig,
    SpiderConfigStore,
    SpiderEnvironment,
    SpiderRunResult,
    _cli_config_document,
    account_identity_key,
    parse_result_payload,
)

UID = "MS4wLjABAAAAshared_identity"
LINKS = ("https://v.douyin.com/first-share/", "https://v.douyin.com/second-share/")


def test_stable_id_and_profile_url_have_one_identity():
    accounts = (
        SpiderAccount("douyin", LINKS[0], resolved_id=UID),
        SpiderAccount("douyin", f"https://www.douyin.com/user/{UID}/?tracking=1"),
        SpiderAccount("douyin", UID),
    )
    assert len({account_identity_key(account) for account in accounts}) == 1


@pytest.mark.parametrize("url", [
    f"https://www.douyin.com/video/123?sec_uid={UID}",
    f"https://www.douyin.com/user/{UID}?sec_uid=MS4wLjABAAAAdifferent_identity",
])
def test_identity_parameter_does_not_override_wrong_or_conflicting_page(url):
    assert account_identity_key(SpiderAccount("douyin", url)) != account_identity_key(SpiderAccount("douyin", UID))


def test_different_kuaishou_query_ids_are_not_merged():
    accounts = [SpiderAccount("kuaishou", f"https://www.kuaishou.com/?userId={identity}") for identity in ("account-a", "account-b")]
    assert account_identity_key(accounts[0]) != account_identity_key(accounts[1])
    assert account_identity_key(accounts[0]) == account_identity_key(SpiderAccount("kuaishou", "https://www.kuaishou.com/profile/account-a"))


def test_unknown_identity_query_parameters_are_preserved():
    first = SpiderAccount("douyin", "https://www.douyin.com/?account=first&from=share")
    second = SpiderAccount("douyin", "https://www.douyin.com/?account=second&from=share")
    assert account_identity_key(first) != account_identity_key(second)


def test_resolved_identity_is_saved_and_reused_by_cli(tmp_path):
    store = SpiderConfigStore(tmp_path / "config.json")
    account = SpiderAccount("douyin", LINKS[0], resolved_id=UID)
    store.save(SpiderConfig(accounts=(account,)))
    loaded = store.load()
    assert loaded.accounts == (account,)
    assert _cli_config_document(loaded)["accounts"][0]["sec_uid"] == UID


def test_partial_result_message_and_identity_survive_archiving():
    result = parse_result_payload({
        "retained_products": [{"name": "known product"}],
        "all_items": [], "crawl_complete": False,
        "account_resolutions": [{"platform": "douyin", "url_or_id": LINKS[0], "sec_uid": UID}],
    })
    assert "未完整" in result.message
    restored = SpiderRunResult.from_dict(result.to_dict())
    assert restored.crawl_complete is False
    assert restored.accounts == result.accounts
    assert restored.message == result.message


@pytest.fixture
def page(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jingxu.ui.spider_page import SpiderPage
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path / "data"))
    store = SpiderConfigStore(tmp_path / "config.json")
    store.save(SpiderConfig(accounts=tuple(SpiderAccount("douyin", url) for url in LINKS)))
    page = SpiderPage(
        store=store, check_environment=lambda: SpiderEnvironment(available=True, message="test"),
    )
    yield page, store
    page.close()
    page.deleteLater()
    app.processEvents()


def test_ui_merges_aliases_and_preserves_identity_when_toggled(page):
    from PySide6.QtCore import Qt

    page, store = page
    page._on_run_finished(SpiderRunResult(
        success=True, message="抓取完成", accounts=tuple(
            {"platform": "douyin", "url_or_id": url, "sec_uid": UID, "name": "actual account"}
            for url in LINKS
        ),
    ))
    assert page._accounts_table.rowCount() == 1
    assert page._rows[0].resolved_id == UID
    assert page._rows[0].url_or_id == f"https://www.douyin.com/user/{UID}"
    page._accounts_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert store.load().accounts[0].resolved_id == UID
    assert store.load().accounts[0].enabled is False


def test_unresolved_account_is_not_replaced_by_none_string(page):
    page, _store = page
    page._apply_account_resolutions(SpiderRunResult(
        success=True, message="failed identity", accounts=(
            {"platform": "douyin", "url_or_id": LINKS[0], "sec_uid": None},
        ),
    ))
    assert len(page._rows) == 2
    assert all(not account.resolved_id for account in page._rows)


def test_partial_ui_result_is_not_reported_as_complete(page):
    page, store = page
    page._on_run_finished(SpiderRunResult(
        success=True, message="抓取未完整结束，已保留当前数据", crawl_complete=False,
        retained=({"name": "product", "sample_video_url": "https://example.com/video"},),
    ))
    assert "未完整" in page._result_caption.text()
    assert store.load_result().crawl_complete is False
