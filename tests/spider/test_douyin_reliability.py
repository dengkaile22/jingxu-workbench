"""Offline regressions for stable account identity and incomplete Douyin responses."""
import json
from types import SimpleNamespace

import pytest
from core.account_identity import AccountResolutionError
from core.douyin_crawler import (
    DouyinCrawler,
    DouyinResponseError,
    _decode_douyin_response,
    _fetch_douyin_post_api_via_browser,
    resolve_douyin_url_or_secuid,
)
from core.models import AccountTarget, TimeFilterConfig
from DrissionPage.errors import PageDisconnectedError

SEC_UID = "MS4wLjABAAAAtest-account-identity"
OTHER_UID = "MS4wLjABAAAAother-account-identity"


def aweme(video_id="video-1", *, owner=SEC_UID, timestamp=1710000000):
    return {
        "aweme_id": video_id,
        "desc": "好物推荐",
        "create_time": timestamp,
        "author": {"sec_uid": owner, "nickname": "测试账号"},
        "statistics": {"digg_count": 128},
        "anchor_info": {
            "extra": json.dumps({"title": "天然茶籽洗衣液5kg", "product_id": "product-1", "price": 4990}),
        },
    }


def payload(items=None, *, has_more=0, cursor=0):
    return {"status_code": 0, "aweme_list": [] if items is None else items, "has_more": has_more, "max_cursor": cursor}


def packet(body, *, status=200, failed=False):
    return SimpleNamespace(response=SimpleNamespace(body=body, status=status), is_failed=failed)


class Listener:
    def __init__(self, packets=()):
        self.packets = list(packets)
        self.wait_count = 0

    def start(self, _targets):
        pass

    def wait(self, timeout):
        self.wait_count += 1
        return self.packets.pop(0) if self.packets else None


class Page:
    """Imitates only the existing crawler APIs; never creates a browser."""

    def __init__(self, api=(), packets=(), cards=(), ssr=None):
        self.api = list(api)
        self.listen = Listener(packets)
        self.cards = list(cards)
        self.ssr = ssr
        self.api_count = 0
        self.visits = []

    def get(self, url, **_kwargs):
        self.visits.append(url)

    def ele(self, *_args, **_kwargs):
        return None

    def eles(self, *_args, **_kwargs):
        return self.cards

    def run_js(self, script, **_kwargs):
        if "aweme/post" in script:
            self.api_count += 1
            return self.api.pop(0) if self.api else {"ok": False, "code": "network_error"}
        if "RENDER_DATA" in script and self.ssr is not None:
            return json.dumps({"aweme_list": self.ssr})
        return ""


@pytest.fixture(autouse=True)
def no_network_or_delays(monkeypatch):
    monkeypatch.setattr("core.douyin_crawler.time.sleep", lambda _duration: None)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline regression must not issue a network request")
    monkeypatch.setattr("requests.get", forbidden)


def make_crawler(page):
    logs = []
    return DouyinCrawler(SimpleNamespace(get_page=lambda: page), log_callback=logs.append), logs


def target(**kwargs):
    return AccountTarget(platform="douyin", url_or_id=SEC_UID, name="测试账号", **kwargs)


@pytest.mark.parametrize("body,status,failed,code", [
    ("", 200, False, "empty_response"),
    ("  ", 200, False, "empty_response"),
    (None, 200, False, "empty_response"),
    ("<html>private-token</html>", 200, False, "html_response"),
    ("private-token", 200, False, "invalid_json"),
    ({}, 403, False, "http_error"),
    (None, None, True, "network_error"),
    ({"status_code": 8, "status_msg": "private-token"}, 200, False, "business_error"),
    ({"has_more": 0}, 200, False, "missing_video_list"),
    ({"aweme_list": None, "has_more": 0}, 200, False, "invalid_video_list"),
    ([], 200, False, "invalid_payload"),
    (b"\xff", 200, False, "invalid_encoding"),
])
def test_invalid_responses_have_safe_diagnostics(body, status, failed, code):
    with pytest.raises(DouyinResponseError) as captured:
        _decode_douyin_response(body, status=status, failed=failed)
    assert captured.value.code == code
    assert "private-token" not in str(captured.value)
    assert captured.value.suggestion


def test_byte_encoded_json_is_valid_and_extracted():
    page = Page(packets=[packet(json.dumps(payload([aweme()])).encode("utf-8"))])
    crawler, _ = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=2)
    assert len(items) == 1
    assert account.status == "已完成"
    assert account.scraped_videos == account.found_products == 1


def test_invalid_packet_can_recover_to_valid_response():
    page = Page(packets=[packet(""), packet("<html>verify</html>"), packet(payload([aweme()]))])
    crawler, logs = make_crawler(page)
    account = target()
    assert len(crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=4)) == 1
    assert account.status == "已完成"
    assert {issue["code"] for issue in crawler.response_issues} >= {"empty_response", "html_response"}
    assert all("Expecting value" not in line for line in logs)


def test_direct_api_retries_empty_response_then_recovers():
    page = Page(api=[{"ok": True, "body": ""}, {"ok": True, "body": json.dumps(payload([aweme()]))}])
    crawler, _ = make_crawler(page)
    account = target()
    assert len(crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=2)) == 1
    assert page.api_count == 2
    assert account.status == "已完成"


def test_direct_api_successful_page_then_failures_is_partial():
    first_page = [aweme(str(index)) for index in range(20)]
    page = Page(api=[{"ok": True, "data": payload(first_page, has_more=1, cursor=123)}])
    crawler, _ = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=6)
    assert len(items) == 20
    assert account.status == "部分完成"
    assert account.scraped_videos == account.found_products == 20
    assert page.api_count == 4  # One success, three retries at the failing cursor.
    assert "no_new_videos" in {issue["code"] for issue in crawler.response_issues}


@pytest.mark.parametrize("source", ["api", "packet"])
def test_empty_list_with_explicit_end_is_complete(source):
    page = Page(api=[{"ok": True, "data": payload()}] if source == "api" else [],
                packets=[packet(payload())] if source == "packet" else [])
    crawler, _ = make_crawler(page)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=2) == []
    assert account.status == "已完成"
    assert account.scraped_videos == account.found_products == 0


def test_zero_cursor_with_more_videos_does_not_report_complete():
    page = Page(api=[{"ok": True, "data": payload([aweme()], has_more=1, cursor=0)}])
    crawler, _ = make_crawler(page)
    account = target()
    crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=2)
    assert account.status == "部分完成"
    assert "pagination_stalled" in {issue["code"] for issue in crawler.response_issues}


def test_page_limit_preserves_partial_data_and_statistics():
    page = Page(api=[{"ok": True, "data": payload([aweme()], has_more=1, cursor=123)}])
    crawler, _ = make_crawler(page)
    account = target()
    assert len(crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=1)) == 1
    assert account.status == "部分完成"
    assert account.scraped_videos == account.found_products == 1
    assert "page_limit" in {issue["code"] for issue in crawler.response_issues}
    assert page.listen.wait_count == 0  # Direct API used the configured page budget.


def test_continuous_invalid_packets_stop_at_three_and_are_failed():
    page = Page(packets=[packet("private-token") for _ in range(8)])
    crawler, logs = make_crawler(page)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=20) == []
    assert account.status == "抓取失败"
    assert page.api_count == 3
    assert page.listen.wait_count == 3
    assert account.scraped_videos == account.found_products == 0
    assert all("private-token" not in json.dumps(issue) for issue in crawler.response_issues)
    assert all("private-token" not in line for line in logs)


def test_dom_discovery_does_not_prevent_complete_network_record(monkeypatch):
    # DOM extraction searches numeric Douyin IDs; patch a discovery result so
    # the regression focuses on the crawler's separate identity tracking.
    monkeypatch.setattr("core.douyin_crawler._extract_douyin_dom_video_cards",
                        lambda _page: [{"aweme_id": "video-1", "create_time": 0, "_from_dom": True}])
    page = Page(packets=[None, packet(payload([aweme()]))])
    crawler, logs = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="range", start_date="2024-03-01", end_date="2024-03-31"), max_scrolls=3)
    assert len(items) == 1
    assert items[0].publish_time == 1710000000
    assert account.status == "已完成"
    assert any("等待完整视频及商品数据" in line for line in logs)


def test_dom_only_discovery_cannot_bypass_date_filter(monkeypatch):
    monkeypatch.setattr("core.douyin_crawler._extract_douyin_dom_video_cards",
                        lambda _page: [dict(aweme(), _from_dom=True, create_time=0)])
    page = Page()
    crawler, _ = make_crawler(page)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="days", days=3), max_scrolls=2) == []
    assert account.status == "抓取失败"
    assert account.scraped_videos == 0


def test_wrong_account_packet_cannot_complete_current_account():
    page = Page(packets=[packet(payload([aweme(owner=OTHER_UID)])), packet(payload([aweme()]))])
    crawler, _ = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=3)
    assert len(items) == 1
    assert items[0].account_id == SEC_UID
    assert page.listen.wait_count == 2
    assert account.status == "已完成"
    assert "wrong_account" in {issue["code"] for issue in crawler.response_issues}


def test_same_secuid_two_short_links_are_crawled_once(monkeypatch):
    inputs = []
    def resolve(raw, **_kwargs):
        inputs.append(raw)
        return SEC_UID
    monkeypatch.setattr("core.douyin_crawler.resolve_douyin_identity", resolve)
    page = Page(api=[{"ok": True, "data": payload([aweme()])}])
    crawler, _ = make_crawler(page)
    first = AccountTarget("douyin", "https://v.douyin.com/first/", name="测试账号")
    second = AccountTarget("douyin", "https://v.douyin.com/second/", name="测试账号")
    assert len(crawler.crawl_account(first, TimeFilterConfig(mode="all"), max_scrolls=2)) == 1
    assert crawler.crawl_account(second, TimeFilterConfig(mode="all"), max_scrolls=2) == []
    assert first.sec_uid == second.sec_uid == SEC_UID
    assert second.status == "重复账号，已跳过"
    assert second.scraped_videos == second.found_products == 0
    assert page.api_count == 1
    assert len(page.visits) == 1
    assert inputs == [first.url_or_id, second.url_or_id]


def test_cached_stable_identity_has_priority_over_expired_link(monkeypatch):
    inputs = []
    def resolve(raw, **_kwargs):
        inputs.append(raw)
        return SEC_UID
    monkeypatch.setattr("core.douyin_crawler.resolve_douyin_identity", resolve)
    page = Page(api=[{"ok": True, "data": payload()}])
    crawler, _ = make_crawler(page)
    account = AccountTarget("douyin", "https://v.douyin.com/expired/", sec_uid=SEC_UID)
    crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=1)
    assert inputs == [SEC_UID]
    assert account.status == "已完成"


def test_unresolved_account_is_not_used_as_profile_identifier(monkeypatch):
    def resolve(*_args, **_kwargs):
        raise AccountResolutionError("无法确认账号")
    monkeypatch.setattr("core.douyin_crawler.resolve_douyin_identity", resolve)
    page = Page()
    crawler, _ = make_crawler(page)
    account = AccountTarget("douyin", "nlc1314")
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all")) == []
    assert account.status == "解析失败"
    assert page.visits == []
    assert page.api_count == 0
    assert resolve_douyin_url_or_secuid("nlc1314") == ""


def test_fetch_diagnostic_does_not_echo_javascript_error():
    page = SimpleNamespace(run_js=lambda *_args, **_kwargs: {"ok": False, "error": "https://api?msToken=private-token"})
    issues = []
    assert _fetch_douyin_post_api_via_browser(page, SEC_UID, issue_callback=issues.append) is None
    assert issues[0].code == "network_error"
    assert "private-token" not in str(issues[0])


def test_ssr_partial_product_data_is_enriched_by_full_api_without_double_counting():
    partial = {"aweme_id": "video-1", "desc": "首页摘要", "create_time": 1710000000,
               "author": {"sec_uid": SEC_UID}}
    page = Page(ssr=[partial], api=[{"ok": True, "data": payload([aweme()])}])
    crawler, _ = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=2)
    assert len(items) == 1
    assert len(crawler.diagnostics) == 1
    assert crawler.diagnostics[0].extracted == 1
    assert account.scraped_videos == account.found_products == 1
    assert account.status == "已完成"


def test_ssr_missing_date_is_enriched_in_selected_time_range():
    page = Page(ssr=[aweme(timestamp=0)], api=[{"ok": True, "data": payload([aweme()])}])
    crawler, _ = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="range", start_date="2024-03-01", end_date="2024-03-31"), max_scrolls=2)
    assert len(items) == 1
    assert items[0].publish_time == 1710000000
    assert account.status == "已完成"
    assert account.scraped_videos == account.found_products == 1
    assert len(crawler.diagnostics) == 1


def test_missing_date_packet_is_enriched_by_repeated_complete_data():
    page = Page(packets=[packet(payload([aweme(timestamp=0)], has_more=1)),
                         packet(payload([aweme()], has_more=1)), packet(payload([aweme()]))])
    crawler, _ = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="range", start_date="2024-03-01", end_date="2024-03-31"), max_scrolls=4)
    assert len(items) == 1
    assert len(crawler.diagnostics) == 1
    assert account.scraped_videos == account.found_products == 1
    assert account.status == "已完成"


def test_explicit_end_with_missing_required_date_is_partial():
    page = Page(api=[{"ok": True, "data": payload([aweme(timestamp=0)])}])
    crawler, _ = make_crawler(page)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="days", days=3), max_scrolls=2) == []
    assert account.status == "部分完成"
    assert account.scraped_videos == 1
    assert account.found_products == 0
    assert "incomplete_video_data" in {issue["code"] for issue in crawler.response_issues}


def test_repeated_product_payload_updates_likes_without_duplicate_records():
    initial = aweme()
    later = aweme()
    later["statistics"]["digg_count"] = 1000
    page = Page(ssr=[initial], api=[{"ok": True, "data": payload([later])}])
    crawler, _ = make_crawler(page)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), max_scrolls=1)
    assert len(items) == len(crawler.diagnostics) == 1
    assert items[0].like_count == 1000
    assert account.scraped_videos == account.found_products == 1


def test_navigation_false_does_not_attempt_video_fetches():
    page = Page()
    page.get = lambda *_args, **_kwargs: False
    crawler, _ = make_crawler(page)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all")) == []
    assert account.status == "抓取失败"
    assert page.api_count == page.listen.wait_count == 0
    assert "navigation_error" in {issue["code"] for issue in crawler.response_issues}


@pytest.mark.parametrize("url,code", [
    ("https://www.douyin.com/user/" + OTHER_UID, "wrong_profile"),
    ("https://www.douyin.com/passport/login?msToken=private-token", "profile_verification"),
    ("https://www.douyin.com/verify", "profile_verification"),
    ("https://other.example/?msToken=private-token", "wrong_profile"),
])
def test_profile_redirect_is_rejected_before_fetch(url, code):
    page = Page()
    page.url = url
    crawler, logs = make_crawler(page)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all")) == []
    assert account.status == "抓取失败"
    assert page.api_count == page.listen.wait_count == 0
    assert code in {issue["code"] for issue in crawler.response_issues}
    assert all("private-token" not in line for line in logs)


def test_profile_verification_text_is_rejected_before_fetch():
    page = Page()
    page.url = "https://www.douyin.com/user/" + SEC_UID
    page.run_js = lambda *_args, **_kwargs: "请完成验证后继续"
    crawler, _ = make_crawler(page)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all")) == []
    assert account.status == "抓取失败"
    assert page.api_count == page.listen.wait_count == 0
    assert "profile_verification" in {issue["code"] for issue in crawler.response_issues}


class RecoveringManager:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.restarts = 0

    def get_page(self, force_new=False):
        if force_new:
            self.restarts += 1
            self.pages.pop(0)
        return self.pages[0]


class DisconnectedUrlPage(Page):
    @property
    def url(self):
        raise PageDisconnectedError("synthetic-private-token")


def test_exact_url_property_disconnect_recovers_once():
    manager = RecoveringManager(
        DisconnectedUrlPage(), Page(api=[{"ok": True, "data": payload([aweme()])}])
    )
    logs = []
    crawler = DouyinCrawler(manager, log_callback=logs.append)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), 2)
    assert len(items) == account.found_products == account.scraped_videos == 1
    assert manager.restarts == 1
    assert account.status == "已完成"
    assert all("synthetic-private-token" not in line for line in logs)


def test_second_disconnect_is_reported_without_unbounded_restarts():
    manager = RecoveringManager(DisconnectedUrlPage(), DisconnectedUrlPage())
    crawler = DouyinCrawler(manager)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all"), 2) == []
    assert manager.restarts == 1
    assert account.status == "抓取失败"
    assert [issue["code"] for issue in crawler.response_issues] == ["page_disconnected"]


def test_pagination_disconnect_keeps_checkpoint_and_deduplicates_retry():
    class MidPageDisconnect(Page):
        def run_js(self, script, **kwargs):
            if "aweme/post" in script and self.api_count == 1:
                raise PageDisconnectedError()
            return super().run_js(script, **kwargs)
    first = MidPageDisconnect(api=[{"ok": True, "data": payload([aweme()], has_more=1, cursor=1)}])
    second = Page(api=[{"ok": True, "data": payload([aweme(), aweme("video-2")])}])
    manager = RecoveringManager(first, second)
    crawler = DouyinCrawler(manager)
    checkpoints = []
    callback = lambda items: checkpoints.append([item.video_id for item in items])
    crawler.on_checkpoint = callback
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), 2)
    assert {item.video_id for item in items} == {"video-1", "video-2"}
    assert account.scraped_videos == account.found_products == len(crawler.diagnostics) == 2
    assert manager.restarts == 1 and account.status == "已完成"
    assert checkpoints[0] == ["video-1"]
    assert set(checkpoints[-1]) == {"video-1", "video-2"}
    assert crawler.on_checkpoint is callback


def test_cancel_during_url_read_stops_without_reopening():
    cancelled = False
    class CancelledUrlPage(Page):
        @property
        def url(self):
            nonlocal cancelled
            cancelled = True
            raise PageDisconnectedError()
    manager = RecoveringManager(CancelledUrlPage())
    crawler = DouyinCrawler(manager, stop_check=lambda: cancelled)
    account = target()
    assert crawler.crawl_account(account, TimeFilterConfig(mode="all"), 2) == []
    assert account.status == "已停止"
    assert manager.restarts == 0
    assert crawler.response_issues == []


def test_disconnect_during_cancellation_retains_obtained_rows():
    cancelled = False
    class CancelledApiPage(Page):
        def run_js(self, script, **kwargs):
            nonlocal cancelled
            if "aweme/post" in script and self.api_count == 1:
                cancelled = True
                raise PageDisconnectedError()
            return super().run_js(script, **kwargs)
    manager = RecoveringManager(CancelledApiPage(api=[{
        "ok": True, "data": payload([aweme()], has_more=1, cursor=1)
    }]))
    crawler = DouyinCrawler(manager, stop_check=lambda: cancelled)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode="all"), 2)
    assert len(items) == account.found_products == account.scraped_videos == 1
    assert account.status == "已停止" and manager.restarts == 0


@pytest.mark.parametrize('stage', ['navigation', 'ssr', 'api', 'listener', 'scroll'])
def test_disconnect_in_optional_page_operations_reaches_recovery(stage):
    class InterruptedPage(Page):
        def get(self, *args, **kwargs):
            if stage == 'navigation':
                raise PageDisconnectedError()
            return super().get(*args, **kwargs)
        def run_js(self, script, **kwargs):
            if (stage == 'ssr' and 'RENDER_DATA' in script
                or stage == 'api' and 'aweme/post' in script
                or stage == 'scroll' and script.startswith('window.scrollBy')):
                raise PageDisconnectedError()
            return super().run_js(script, **kwargs)
    first = InterruptedPage()
    if stage == 'listener':
        def fail_wait(**_kwargs):
            raise PageDisconnectedError()
        first.listen.wait = fail_wait
    manager = RecoveringManager(first, Page(api=[{'ok': True, 'data': payload([aweme()])}]))
    crawler = DouyinCrawler(manager)
    account = target()
    assert len(crawler.crawl_account(account, TimeFilterConfig(mode='all'), 2)) == 1
    assert manager.restarts == 1 and account.status == '已完成'


def test_retry_enriches_title_only_product_without_counting_it_twice():
    class InterruptedApiPage(Page):
        def run_js(self, script, **kwargs):
            if 'aweme/post' in script:
                raise PageDisconnectedError()
            return super().run_js(script, **kwargs)
    initial = aweme()
    initial['anchor_info']['extra'] = json.dumps({'title': '天然茶籽洗衣液5kg'})
    manager = RecoveringManager(
        InterruptedApiPage(ssr=[initial]), Page(api=[{'ok': True, 'data': payload([aweme()])}])
    )
    crawler = DouyinCrawler(manager)
    account = target()
    items = crawler.crawl_account(account, TimeFilterConfig(mode='all'), 2)
    assert len(items) == account.found_products == account.scraped_videos == 1
    assert items[0].product_id == 'product-1'
    assert items[0].price
    assert len(crawler.diagnostics) == 1 and account.status == '已完成'
