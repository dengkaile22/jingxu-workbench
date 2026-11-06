"""Fresh REST request fields and cursor continuity across browser generations."""

import json
from types import SimpleNamespace

import pytest

from core.profile_requests import learn_kuaishou_feed_request, fetch_kuaishou_profile_feed


def packet(body=None, *, url="https://www.kuaishou.com/rest/v/profile/feed", method="POST"):
    return SimpleNamespace(request=SimpleNamespace(url=url, method=method, postData=body))


def test_profile_request_is_learned_only_for_target_account():
    template = learn_kuaishou_feed_request(packet({"userId": "author", "pcursor": "next", "nonce": "fresh"}), "author")
    assert template["cursorPath"] == ["pcursor"]
    assert learn_kuaishou_feed_request(packet({"userId": "other", "pcursor": "next"}), "author") is None
    assert learn_kuaishou_feed_request(packet({"userId": "author", "pcursor": "next"}, url="https://other.example/rest/v/profile/feed"), "author") is None
    assert learn_kuaishou_feed_request(packet({"userId": "author", "pcursor": "next"}, url="https://www.kuaishou.com/rest/v/recommend/feed"), "author") is None


def test_first_page_can_relearn_cursor_field_from_previous_valid_request():
    old = learn_kuaishou_feed_request(packet({"userId": "author", "pcursor": "next", "nonce": "old"}), "author")
    fresh = learn_kuaishou_feed_request(packet({"userId": "author", "nonce": "new"}), "author", old)
    scripts = []
    page = SimpleNamespace(run_js=lambda script, **_kwargs: scripts.append(script) or {"ok": True, "data": {"result": 1}})
    assert fetch_kuaishou_profile_feed(page, fresh, "saved-cursor") == {"result": 1}
    assert "saved-cursor" in scripts[0] and "new" in scripts[0] and "old" not in scripts[0]
    assert "authorization" not in scripts[0].casefold()


@pytest.mark.parametrize("method,body,url", [
    ("POST", "userId=author&pcursor=next", "https://www.kuaishou.com/rest/v/profile/feed"),
    ("GET", None, "https://www.kuaishou.com/rest/v/profile/feed?userId=author&pcursor=next"),
])
def test_form_and_get_requests_preserve_their_encoding(method, body, url):
    template = learn_kuaishou_feed_request(packet(body, method=method, url=url), "author")
    scripts = []
    page = SimpleNamespace(run_js=lambda script, **_kwargs: scripts.append(script) or {"ok": True, "data": {"result": 1}})
    assert fetch_kuaishou_profile_feed(page, template, "resumed") == {"result": 1}
    assert "resumed" in scripts[0] and 'credentials: \'include\'' in scripts[0]


def test_crawlers_survive_multiple_quantity_rotations_without_losing_or_double_counting(monkeypatch):
    from core.douyin_crawler import DouyinCrawler
    from core.kuaishou_crawler import KuaishouCrawler
    from core.models import AccountTarget, TimeFilterConfig
    from test_browser_recovery import Page, Manager, payload, video, SEC_UID, USER_ID
    monkeypatch.setattr("core.douyin_crawler.time.sleep", lambda _duration: None)
    for platform, crawler_type in (("douyin", DouyinCrawler), ("kuaishou", KuaishouCrawler)):
        page = Page(platform, [payload(platform, [video(platform, str(index))], more=index < 6, cursor=index + 1) for index in range(7)])
        manager = Manager(page)
        manager.units = manager.rotations = 0
        def mark(): manager.units += 1
        def rotate():
            if manager.units < 2: return False
            manager.units = 0; manager.rotations += 1
            return True
        manager.mark_page_processed = mark
        manager.rotate_if_due = rotate
        crawler = crawler_type(manager)
        target = AccountTarget(platform, SEC_UID if platform == "douyin" else USER_ID)
        items = crawler.crawl_account(target, TimeFilterConfig(mode="all"), max_scrolls=10)
        assert target.status == "已完成" and len(items) == target.scraped_videos == target.found_products == 7
        assert manager.rotations == 3 and len(page.visits) == 4
        expected = list(range(7)) if platform == "douyin" else [""] + [str(index) for index in range(1, 7)]
        assert page.api_cursors == expected


def test_modern_kuaishou_rest_resumes_with_fresh_fields_after_rotation(monkeypatch):
    from core.kuaishou_crawler import KuaishouCrawler
    from core.models import AccountTarget, TimeFilterConfig
    from test_browser_recovery import Page, Manager, video, USER_ID
    monkeypatch.setattr("core.kuaishou_crawler.time.sleep", lambda _duration: None)
    def response(index):
        return {"result": 1, "feeds": [{"photo": video("kuaishou", str(index))}],
                "pcursor": str(index + 1) if index < 4 else "no_more", "hasMore": index < 4}
    class ModernPage(Page):
        def __init__(self):
            super().__init__("kuaishou")
            self.generation = 0
            self.packets = []
            self.rest_scripts = []
            self.listen = SimpleNamespace(start=lambda _targets: None, wait=lambda **_kwargs: self.packets.pop(0) if self.packets else None)
        def get(self, url, **kwargs):
            super().get(url, **kwargs)
            self.generation += 1
            count = 2 if self.generation == 1 else 1
            self.packets = [SimpleNamespace(response=SimpleNamespace(body=response(index)),
                request=SimpleNamespace(url="https://www.kuaishou.com/rest/v/profile/feed", method="POST",
                    postData={"userId": USER_ID, "pcursor": str(index), "nonce": f"environment-{self.generation}"}))
                for index in range(count)]
        def run_js(self, script, **kwargs):
            if "'/ks-web/'" in script: return True
            if "window.fetch" in script:
                import re
                cursor = json.loads(re.search(r'const pcursor = ("[^";]*");', script).group(1))
                self.api_cursors.append(cursor)
                self.rest_scripts.append(script)
                return {"ok": True, "data": response(int(cursor))}
            return super().run_js(script, **kwargs)
    page = ModernPage()
    manager = Manager(page)
    manager.units = manager.rotations = 0
    manager.mark_page_processed = lambda: setattr(manager, "units", manager.units + 1)
    def rotate():
        if manager.units < 2: return False
        manager.units = 0; manager.rotations += 1
        return True
    manager.rotate_if_due = rotate
    target = AccountTarget("kuaishou", USER_ID)
    items = KuaishouCrawler(manager).crawl_account(target, TimeFilterConfig(mode="all"), max_scrolls=8)
    assert target.status == "已完成" and len(items) == target.scraped_videos == 5
    assert manager.rotations == 2 and page.api_cursors == ["2", "3", "4"]
    assert "environment-2" in page.rest_scripts[0] and "environment-1" not in page.rest_scripts[0]
    assert "environment-3" in page.rest_scripts[-1]
