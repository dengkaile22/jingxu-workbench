"""Abnormal author pages recover without losing data or clearing other sites."""

import json
import re
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from core.browser_manager import BrowserManager, BrowserSessionAbnormal, BrowserSessionStopped
from core.browser_recovery import check_browser_session
from core.douyin_crawler import DouyinCrawler
from core.kuaishou_crawler import KuaishouCrawler
from core.models import AccountTarget, TimeFilterConfig


SEC_UID = "MS4wLjABAAAArecovery-test-account"
USER_ID = "recovery-test-account"
ABNORMAL = object()


def video(platform, identity="video-1", *, goods=True):
    if platform == "douyin":
        result = {
            "aweme_id": identity, "desc": "测试商品", "create_time": 1710000000,
            "author": {"sec_uid": SEC_UID}, "statistics": {"digg_count": 128},
        }
        if goods:
            result["anchor_info"] = {"extra": json.dumps({"title": "茶籽洗衣液5kg", "product_id": "p1"})}
        return result
    result = {"id": identity, "caption": "测试商品", "timestamp": 1710000000000,
              "userId": USER_ID, "likeCount": 128}
    if goods:
        result["goodsInfo"] = {"goodsId": "p1", "goodsName": "茶籽洗衣液5kg"}
    return result


def payload(platform, items, *, more=False, cursor=0):
    if platform == "douyin":
        return {"status_code": 0, "aweme_list": items, "has_more": int(more), "max_cursor": cursor}
    return {"data": {"visionProfilePhotoList": {
        "result": 1, "feeds": [{"photo": item} for item in items],
        "hasMore": more, "pcursor": str(cursor) if more else "no_more",
    }}}


class Page:
    def __init__(self, platform, api=(), *, abnormal=False):
        self.platform = platform
        self.api = list(api)
        self.abnormal = abnormal
        self.api_cursors = []
        self.visits = []
        self.url = (f"https://www.douyin.com/user/{SEC_UID}" if platform == "douyin"
                    else f"https://www.kuaishou.com/profile/{USER_ID}")
        self.listen = SimpleNamespace(start=lambda _targets: None, wait=lambda **_kwargs: None)

    @property
    def title(self):
        return "访问异常" if self.abnormal else "作者主页"

    def get(self, url, **_kwargs):
        self.visits.append(url)

    def ele(self, *_args, **_kwargs):
        return None

    def eles(self, *_args, **_kwargs):
        return []

    def run_js(self, script, **_kwargs):
        if "window.fetch" in script:
            expression = re.search(r"const cursor = ([0-9]+);", script) if self.platform == "douyin" else re.search(r'const pcursor = ("[^";]*");', script)
            self.api_cursors.append(json.loads(expression.group(1)))
            result = self.api.pop(0) if self.api else None
            if result is ABNORMAL:
                self.abnormal = True
                return {"ok": False, "code": "network_error"}
            return {"ok": True, "data": result} if result is not None else None
        if "hasVideos" in script:
            return {"text": "访问异常，请稍后重试" if self.abnormal else "作者主页", "hasVideos": False}
        return ""


class Manager:
    def __init__(self, page):
        self.page = page
        self.resets = []
        self.cache_clears = 0
        self.after_reset = lambda: None
        self.clear_succeeds = True

    def get_page(self, **_kwargs):
        return self.page

    def clear_runtime_cache(self):
        self.cache_clears += 1
        return True

    def clear_site_session(self, platform):
        self.resets.append(platform)
        self.page.abnormal = False
        self.after_reset()
        return self.clear_succeeds


def crawl(platform, page, *, limit=10, stop=None, checkpoint=None):
    manager = Manager(page)
    logs = []
    crawler_class = DouyinCrawler if platform == "douyin" else KuaishouCrawler
    crawler = crawler_class(manager, log_callback=logs.append, stop_check=stop)
    crawler.on_checkpoint = checkpoint
    target = AccountTarget(platform, SEC_UID if platform == "douyin" else USER_ID)
    return manager, logs, crawler, target


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr("core.douyin_crawler.time.sleep", lambda _duration: None)
    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: pytest.fail("unexpected network"))


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
def test_abnormal_homepage_is_cleaned_and_reopened(platform, offline):
    page = Page(platform, [payload(platform, [video(platform)])], abnormal=True)
    manager, logs, crawler, target = crawl(platform, page)
    items = crawler.crawl_account(target, TimeFilterConfig(mode="all"))
    assert manager.resets == [platform]
    assert len(page.visits) == 2
    assert target.status == "已完成" and len(items) == target.found_products == target.scraped_videos == 1
    assert any("新环境已启动" in line for line in logs)


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
def test_mid_crawl_reset_resumes_cursor_and_preserves_checkpoint(platform, offline):
    checkpoints = []
    page = Page(platform, [payload(platform, [video(platform)], more=True, cursor=33), ABNORMAL,
                           payload(platform, [video(platform), video(platform, "video-2")])])
    manager, _, crawler, target = crawl(platform, page, checkpoint=lambda items: checkpoints.append(list(items)))
    items = crawler.crawl_account(target, TimeFilterConfig(mode="all"), max_scrolls=4)
    expected = [0, 33, 33] if platform == "douyin" else ["", "33", "33"]
    assert page.api_cursors == expected
    assert manager.resets == [platform] and target.status == "已完成"
    assert len(items) == target.found_products == target.scraped_videos == 2
    assert {item.video_id for item in items} == {"video-1", "video-2"}
    assert any(len(snapshot) == 1 for snapshot in checkpoints) and len(checkpoints[-1]) == 2


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
def test_repeated_abnormal_pages_have_bounded_recovery(platform, offline):
    page = Page(platform, [ABNORMAL, ABNORMAL, ABNORMAL, ABNORMAL])
    manager, _, crawler, target = crawl(platform, page)
    assert crawler.crawl_account(target, TimeFilterConfig(mode="all")) == []
    assert manager.resets == [platform, platform]
    assert len(page.api_cursors) == 3 and target.status == "抓取失败"
    assert any(issue["code"] == "browser_session_abnormal" for issue in crawler.response_issues)


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
def test_failed_reset_retains_already_acquired_data(platform, offline):
    page = Page(platform, [payload(platform, [video(platform)], more=True, cursor=1), ABNORMAL])
    manager, _, crawler, target = crawl(platform, page)
    manager.clear_succeeds = False
    items = crawler.crawl_account(target, TimeFilterConfig(mode="all"))
    assert len(items) == target.scraped_videos == target.found_products == 1
    assert target.status == "部分完成" and manager.resets == [platform]


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
def test_cancel_during_reset_keeps_data_and_does_not_reopen(platform, offline):
    stopped = [False]
    page = Page(platform, [payload(platform, [video(platform)], more=True, cursor=1), ABNORMAL])
    manager, _, crawler, target = crawl(platform, page, stop=lambda: stopped[0])
    manager.after_reset = lambda: stopped.__setitem__(0, True)
    items = crawler.crawl_account(target, TimeFilterConfig(mode="all"))
    assert len(items) == 1 and len(page.visits) == 1
    assert target.status == "已停止" and len(page.api_cursors) == 2


@pytest.mark.parametrize("platform", ["douyin", "kuaishou"])
def test_normal_long_crawl_clears_cache_periodically_without_cookie_reset(platform, offline):
    page = Page(platform, [payload(platform, [video(platform, str(index))], more=index < 5, cursor=index + 1)
                           for index in range(6)])
    manager, _, crawler, target = crawl(platform, page)
    items = crawler.crawl_account(target, TimeFilterConfig(mode="all"), max_scrolls=7)
    assert target.status == "已完成" and len(items) == 6
    assert manager.cache_clears == 2 and manager.resets == []


@pytest.mark.parametrize("text", ["请先登录", "请完成安全验证", "请输入验证码", "正常作者主页"])
def test_login_and_verification_do_not_trigger_cookie_deletion(text):
    page = SimpleNamespace(title="作者主页", run_js=lambda _script: {"text": text, "hasVideos": False})
    check_browser_session(page)


def test_video_caption_does_not_trigger_cookie_deletion():
    page = SimpleNamespace(title="作者主页", run_js=lambda _script: {"text": "今天教你处理访问异常", "hasVideos": True})
    check_browser_session(page)


class CDPPage:
    def __init__(self, cookies):
        self.cookies = cookies
        self.calls = []
        self.listen = SimpleNamespace(listening=True, stop=lambda: self.calls.append(("stop-listener", {})))

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return True

    def run_cdp(self, method, **kwargs):
        self.calls.append((method, kwargs))
        return {"cookies": self.cookies} if method == "Network.getAllCookies" else {}


def test_abnormal_environment_replacement_keeps_saved_login_cookies(owned_browser):
    manager = owned_browser.make_manager()
    first = manager.get_page()
    first.cookies = [{'name': 'sessionid', 'value': 'synthetic-login', 'domain': '.douyin.com', 'session': True},
                     {'name': 'ks_session', 'value': 'synthetic-ks-login', 'domain': '.kuaishou.com', 'session': True}]
    assert manager.save_cookies()
    first.cookies.append({'name': 'msToken', 'value': 'synthetic-bad-environment', 'domain': '.douyin.com', 'session': True})
    first.title = first.body = '访问异常'
    profile = Path(manager.user_data_dir)
    assert manager.clear_site_session('douyin')
    second = manager.get_page()
    assert second.process_id != first.process_id and Path(manager.user_data_dir) != profile
    assert {item['name'] for item in second.cookies} == {'sessionid', 'ks_session'}
    assert not profile.exists()


def test_cancelled_manager_does_not_clear_live_cookies_or_cache(tmp_path):
    page = CDPPage([])
    manager = BrowserManager(user_data_dir=str(tmp_path))
    manager._page = page
    manager._stopped.set()
    with pytest.raises(BrowserSessionStopped):
        manager.clear_site_session("douyin")
    with pytest.raises(BrowserSessionStopped):
        manager.clear_runtime_cache()
    assert page.calls == []


def test_background_mode_and_visible_login_options_are_consistent(tmp_path):
    manager = BrowserManager(headless=True, user_data_dir=str(tmp_path))
    assert manager.get_options().is_headless is True
    assert manager.get_options(force_headful=True).is_headless is False


@pytest.mark.integration
def test_real_browser_recovers_cookie_and_cache_error_page(tmp_path, monkeypatch):
    """A local HTTP fixture requires both cache and bad-cookie removal to recover."""
    from core import browser_manager, cookie_store
    monkeypatch.setattr(cookie_store, "COOKIE_ROOTS", (*cookie_store.COOKIE_ROOTS, "127.0.0.1"))
    browser = browser_manager.find_browser_path()
    if not browser:
        pytest.skip("Chromium browser required")
    monkeypatch.setenv("JINGXU_SPIDER_COOKIES", str(tmp_path / "unused-import.json"))
    monkeypatch.setitem(browser_manager.PLATFORM_COOKIE_DOMAINS, "douyin", ("douyin.com", "127.0.0.1"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            broken = "msToken=synthetic" in self.headers.get("Cookie", "")
            title = "访问异常" if broken else "作者主页已恢复"
            body = f"<html><head><meta charset='utf-8'><title>{title}</title></head><body>{title}</body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/author"
    profile = tmp_path / "profile"
    manager = BrowserManager(headless=True, user_data_dir=str(profile), browser_path=browser)
    try:
        page = manager.get_page()
        page.run_cdp("Network.setCookies", cookies=[
            {"name": "audit_bad", "value": "synthetic", "url": url},
            {"name": "audit_douyin", "value": "synthetic", "domain": ".douyin.com", "path": "/", "secure": True},
            {"name": "audit_kuaishou", "value": "synthetic", "domain": ".kuaishou.com", "path": "/", "secure": True},
        ])
        page.run_cdp("Network.deleteCookies", name="audit_bad", domain="127.0.0.1", path="/")
        assert manager.save_cookies()
        page.run_cdp("Network.setCookies", cookies=[{"name":"msToken","value":"synthetic","url":url}])
        page.get(url)
        page.run_js("localStorage.setItem('login-sentinel', 'synthetic-login');")
        with pytest.raises(BrowserSessionAbnormal):
            check_browser_session(page)
        assert manager.clear_runtime_cache()
        page.get(url)
        with pytest.raises(BrowserSessionAbnormal):
            check_browser_session(page)
        marker = profile / ".jingxu-cookie-import.json"
        marker.write_text('{"sha256":"synthetic-fingerprint"}', encoding="utf-8")
        assert manager.clear_site_session("douyin")
        page = manager.get_page()
        cookies = page.run_cdp("Network.getAllCookies")["cookies"]
        assert not any(cookie["name"] == "msToken" for cookie in cookies)
        assert any(cookie["name"] == "audit_kuaishou" for cookie in cookies)
        page.get(url)
        check_browser_session(page)
        page = manager.get_page()
        page.get(url)
        assert page.title == "作者主页已恢复"
        assert page.run_js("return localStorage.getItem('login-sentinel');") is None
        assert manager.cookie_store.path.is_file()
        browser_version = page.run_cdp("Browser.getVersion")["product"].split("/")[-1].split(".")[0]
        agent = page.run_js("return navigator.userAgent;")
        assert re.search(r"Chrome/([0-9]+)", agent).group(1) == browser_version
        permission = page.run_js("return navigator.permissions.query({name:'geolocation'}).then(p=>p.state);")
        assert permission in ("prompt", "granted", "denied")
    finally:
        manager.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
