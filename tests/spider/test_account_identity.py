"""Offline identity tests: browser pages and HTTP redirects are all simulated."""

import json
from types import SimpleNamespace
from urllib.parse import quote

import pytest
import requests
from core.account_identity import (
    AccountResolutionError,
    extract_douyin_sec_uid,
    extract_douyin_user_matches,
    resolve_douyin_identity,
)

SEC_UID = "MS4wLjABAAAA_account_one"
OTHER_SEC_UID = "MS4wLjABAAAA_account_two"
HANDLE = "rlct1314"
SHARE = "https://v.douyin.com/XAjBnRG3SXk/"


@pytest.fixture(autouse=True)
def forbid_real_requests(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("This test must not access the network")

    monkeypatch.setattr("core.account_identity.requests.get", denied)


class FakeListener:
    def __init__(self, payloads=()):
        self.packets = [SimpleNamespace(response=SimpleNamespace(body=value)) for value in payloads]
        self.started = []
        self.stopped = False
        self.wait_timeouts = []

    def start(self, targets):
        self.started.append(targets)

    def wait(self, timeout=1):
        self.wait_timeouts.append(timeout)
        return self.packets.pop(0) if self.packets else None

    def stop(self):
        self.stopped = True


class FakePage:
    def __init__(self, payloads=(), packets=(), body="", redirect=None, source=""):
        self.payloads = list(payloads)
        self.listen = FakeListener(packets)
        self.body = body
        self.redirect = redirect
        self.html = source
        self.title = "抖音用户搜索"
        self.url = ""
        self.visited = []

    def get(self, url, timeout=15):
        self.visited.append(url)
        self.url = self.redirect or url
        return True

    def run_js(self, script):
        if "document.body" in script:
            return self.body
        return self.payloads


def user(handle=HANDLE, identity=SEC_UID, nickname="池恩陈."):
    return {"unique_id": handle, "sec_uid": identity, "nickname": nickname}


@pytest.mark.parametrize("raw", [
    SEC_UID,
    f"https://www.douyin.com/user/{SEC_UID}",
    f"https://www.douyin.com/user/{SEC_UID}/?from=share#fragment",
    f"https://www.iesdouyin.com/share/user/{SEC_UID}/",
    f"https://www.iesdouyin.com/share/user/?sec_uid={SEC_UID}",
    f"https://www.iesdouyin.com/share/user/123456789/?sec_uid={SEC_UID}",
    f"https://www.douyin.com/?sec_user_id={SEC_UID}",
    f"分享账号主页 https://www.douyin.com/user/{SEC_UID}。打开抖音查看",
])
def test_direct_sec_uid_and_profile_urls_are_network_free(raw):
    assert extract_douyin_sec_uid(raw) == SEC_UID
    assert resolve_douyin_identity(raw) == SEC_UID


@pytest.mark.parametrize("raw", [
    HANDLE,
    "123456789",
    "test_sec_uid",
    "MS4wLjABAAAA",
    "MS4wLjABAAAA_invalid/token",
    SHARE,
    f"https://example.com/user/{SEC_UID}",
    f"https://douyin.com.example.com/user/{SEC_UID}",
    f"https://notdouyin.com/user/{SEC_UID}",
    f"https://www.douyin.com/user/{HANDLE}",
    f"https://www.douyin.com/user/{SEC_UID}/extra",
    f"https://www.douyin.com/video/12345?sec_uid={SEC_UID}",
    f"https://www.douyin.com/search/{HANDLE}?sec_uid={SEC_UID}",
    f"https://v.douyin.com/short_token/?sec_uid={SEC_UID}",
])
def test_extract_never_mistakes_handles_share_links_or_other_hosts_for_sec_uids(raw):
    assert extract_douyin_sec_uid(raw) == ""


def test_conflicting_query_sec_uids_are_not_accepted():
    assert extract_douyin_sec_uid(f"https://www.douyin.com/?sec_uid={SEC_UID}&sec_user_id={OTHER_SEC_UID}") == ""


def test_conflicting_profile_path_and_query_ids_fail_instead_of_guessing():
    raw = f"https://www.douyin.com/user/{SEC_UID}?sec_uid={OTHER_SEC_UID}"
    assert extract_douyin_sec_uid(raw) == ""
    with pytest.raises(AccountResolutionError):
        resolve_douyin_identity(raw)


def test_share_links_with_different_tokens_resolve_to_same_identity(monkeypatch):
    observed = []

    def get(url, **kwargs):
        observed.append((url, kwargs))
        return SimpleNamespace(url=f"https://www.douyin.com/user/{SEC_UID}", status_code=200)

    monkeypatch.setattr("core.account_identity.requests.get", get)
    assert resolve_douyin_identity(SHARE) == SEC_UID
    assert resolve_douyin_identity("https://v.douyin.com/DZPat40y50A/") == SEC_UID
    assert len(observed) == 2
    assert all(kwargs["allow_redirects"] and kwargs["timeout"] == 8 for _, kwargs in observed)


def test_share_request_failure_uses_supplied_browser(monkeypatch):
    def get(*_args, **_kwargs):
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr("core.account_identity.requests.get", get)
    page = FakePage(redirect=f"https://www.douyin.com/user/{SEC_UID}")
    logs = []
    assert resolve_douyin_identity(SHARE, page=page, log=logs.append) == SEC_UID
    assert page.visited == [SHARE]
    assert any("浏览器" in line for line in logs)


def test_share_redirect_to_login_uses_browser_fallback(monkeypatch):
    monkeypatch.setattr("core.account_identity.requests.get", lambda *_args, **_kwargs: SimpleNamespace(
        url="https://www.douyin.com/passport/login", status_code=200,
    ))
    page = FakePage(redirect=f"https://www.douyin.com/user/{SEC_UID}")
    assert resolve_douyin_identity(SHARE, page=page) == SEC_UID


@pytest.mark.parametrize("destination", [SHARE, "https://www.douyin.com/", "https://www.douyin.com/video/12345"])
def test_unresolved_share_never_returns_the_share_token(monkeypatch, destination):
    monkeypatch.setattr("core.account_identity.requests.get", lambda *_args, **_kwargs: SimpleNamespace(
        url=destination, status_code=200,
    ))
    with pytest.raises(AccountResolutionError, match="分享短链"):
        resolve_douyin_identity(SHARE)


def test_browser_share_fallback_must_reach_an_actual_profile(monkeypatch):
    monkeypatch.setattr("core.account_identity.requests.get", lambda *_args, **_kwargs: SimpleNamespace(
        url=SHARE, status_code=200,
    ))
    with pytest.raises(AccountResolutionError, match="未跳转"):
        resolve_douyin_identity(SHARE, page=FakePage(redirect="https://www.douyin.com/video/123"))


@pytest.mark.parametrize("raw", ["", "   ", "MS4wLjABAAAA", "a handle with spaces", "https://example.com/user/123", "https://www.douyin.com/user/rlct1314"])
def test_invalid_inputs_fail_explicitly_without_network_or_browser(raw):
    with pytest.raises(AccountResolutionError):
        resolve_douyin_identity(raw)


def test_public_handle_requires_a_browser_and_never_becomes_a_sec_uid():
    with pytest.raises(AccountResolutionError, match="浏览器"):
        resolve_douyin_identity(HANDLE)


def test_exact_handle_matching_ignores_nicknames_partial_ids_and_invalid_ids():
    payload = {"data": {"users": [
        user(handle="someone_else", nickname=HANDLE),
        user(handle=HANDLE + "extra"),
        user(identity="invalid_sec_uid"),
        user(),
    ]}}
    assert extract_douyin_user_matches(payload, HANDLE) == {SEC_UID}


def test_same_identity_repeated_in_search_data_is_one_match():
    assert extract_douyin_user_matches([user(), {"user_info": user()}], HANDLE) == {SEC_UID}


def test_conflicting_id_aliases_are_exposed_as_ambiguous():
    payload = user()
    payload["sec_user_id"] = OTHER_SEC_UID
    assert extract_douyin_user_matches(payload, HANDLE) == {SEC_UID, OTHER_SEC_UID}


def test_encoded_search_payload_can_be_parsed():
    assert extract_douyin_user_matches(quote(json.dumps({"user_info": user()})), HANDLE) == {SEC_UID}


@pytest.mark.parametrize("payload", [
    json.dumps({"user_info": user()}, ensure_ascii=False).encode("utf-8"),
    json.dumps({"user_info": user()}, ensure_ascii=False).encode("utf-8-sig"),
    bytearray(json.dumps({"user_info": user()}, ensure_ascii=False).encode("utf-8")),
])
def test_utf8_byte_payloads_support_exact_user_matching(payload):
    assert extract_douyin_user_matches(payload, HANDLE) == {SEC_UID}


def test_invalid_utf8_payload_is_not_partially_decoded_or_guessed():
    payload = b"\xff" + json.dumps({"user_info": user()}).encode("utf-8")
    assert extract_douyin_user_matches(payload, HANDLE) == set()


def test_nested_byte_payload_is_decoded():
    payload = {"response": json.dumps({"user_info": user()}).encode("utf-8")}
    assert extract_douyin_user_matches(payload, HANDLE) == {SEC_UID}


@pytest.mark.parametrize("raw", [HANDLE, "@" + HANDLE, "抖音号：" + HANDLE])
def test_public_handle_resolves_from_exact_structured_browser_data(raw):
    page = FakePage(payloads=[{"data": {"users": [user(handle="other"), user()]}}])
    assert resolve_douyin_identity(raw, page=page) == SEC_UID
    assert page.visited == [f"https://www.douyin.com/search/{HANDLE}?type=user"]
    assert page.listen.stopped


def test_public_handle_resolves_from_search_response_packet():
    page = FakePage(packets=[json.dumps({"user_list": [{"user_info": user()}]})])
    assert resolve_douyin_identity(HANDLE, page=page) == SEC_UID
    assert page.listen.stopped


def test_public_handle_resolves_from_utf8_search_response_packet():
    page = FakePage(packets=[json.dumps({"user_list": [{"user_info": user()}]}).encode("utf-8")])
    assert resolve_douyin_identity(HANDLE, page=page) == SEC_UID


def test_public_handle_with_invalid_byte_data_fails_explicitly():
    page = FakePage(packets=[b"\xff" + json.dumps({"user_info": user()}).encode("utf-8")])
    with pytest.raises(AccountResolutionError, match="完全匹配"):
        resolve_douyin_identity(HANDLE, page=page)


def test_public_handle_resolves_from_html_ssr_data():
    encoded = quote(json.dumps({"user_info": user()}))
    page = FakePage(source=f'<html><script id="RENDER_DATA">{encoded}</script></html>')
    assert resolve_douyin_identity(HANDLE, page=page) == SEC_UID


def test_nickname_only_search_result_is_not_used():
    page = FakePage(payloads=[{"users": [user(handle="different", nickname=HANDLE)]}])
    with pytest.raises(AccountResolutionError, match="完全匹配"):
        resolve_douyin_identity(HANDLE, page=page)
    assert page.listen.stopped


def test_multiple_exact_handle_ids_fail_instead_of_guessing():
    page = FakePage(payloads=[user()], packets=[{"user_info": user(identity=OTHER_SEC_UID)}])
    with pytest.raises(AccountResolutionError, match="多个匹配"):
        resolve_douyin_identity(HANDLE, page=page)
    assert page.listen.stopped


@pytest.mark.parametrize("body", ["请完成验证码验证", "安全验证", "请先登录后继续", "登录后搜索用户"])
def test_verification_or_login_gate_blocks_even_valid_matching_data(body):
    page = FakePage(body=body, payloads=[user()])
    with pytest.raises(AccountResolutionError, match="登录|验证码"):
        resolve_douyin_identity(HANDLE, page=page)
    assert page.listen.stopped


def test_verification_redirect_fails_explicitly():
    page = FakePage(redirect="https://www.douyin.com/passport/login", payloads=[user()])
    with pytest.raises(AccountResolutionError, match="登录或验证"):
        resolve_douyin_identity(HANDLE, page=page)


def test_unexpected_search_redirect_cannot_reuse_unrelated_page_data():
    page = FakePage(redirect="https://www.douyin.com/", payloads=[user()])
    with pytest.raises(AccountResolutionError, match="预期"):
        resolve_douyin_identity(HANDLE, page=page)


@pytest.mark.parametrize("destination", [
    f"https://example.com/search/{HANDLE}?type=user",
    "https://www.douyin.com/search/someone_else?type=user",
    f"https://www.douyin.com/search/{HANDLE}?type=video",
    "",
])
def test_search_requires_the_exact_verified_user_search_location(destination):
    page = FakePage(payloads=[user()])

    def get(url, **_kwargs):
        page.url = destination
        return True

    page.get = get
    with pytest.raises(AccountResolutionError, match="预期"):
        resolve_douyin_identity(HANDLE, page=page)


def test_search_location_is_rechecked_after_packet_wait():
    page = FakePage(payloads=[user()])

    def wait(timeout=1):
        page.url = "https://www.douyin.com/"

    page.listen.wait = wait
    with pytest.raises(AccountResolutionError, match="预期"):
        resolve_douyin_identity(HANDLE, page=page)


def test_search_packet_wait_is_bounded():
    page = FakePage(payloads=[user()])
    assert resolve_douyin_identity(HANDLE, page=page) == SEC_UID
    assert page.listen.wait_timeouts == [1, 1, 1]


def test_optional_browser_js_failure_can_use_html_ssr():
    page = FakePage(source=f'<script id="RENDER_DATA">{json.dumps({"user_info": user()})}</script>')

    def run_js(*_args):
        raise RuntimeError("browser JS transport disconnected")

    page.run_js = run_js
    assert resolve_douyin_identity(HANDLE, page=page) == SEC_UID


def test_optional_listener_failure_can_use_structured_page_data():
    page = FakePage(payloads=[user()])

    def start(*_args):
        raise RuntimeError("browser listener disconnected")

    page.listen.start = start
    assert resolve_douyin_identity(HANDLE, page=page) == SEC_UID


def test_failed_navigation_is_not_reported_as_success():
    page = FakePage(payloads=[user()])
    page.get = lambda *_args, **_kwargs: False
    with pytest.raises(AccountResolutionError, match="加载失败"):
        resolve_douyin_identity(HANDLE, page=page)
    assert page.listen.stopped


def test_navigation_exception_is_a_readable_resolution_error():
    page = FakePage(payloads=[user()])

    def get(*_args, **_kwargs):
        raise RuntimeError("browser transport disconnected")

    page.get = get
    with pytest.raises(AccountResolutionError, match="加载失败"):
        resolve_douyin_identity(HANDLE, page=page)


def test_browser_transport_failure_does_not_expose_exception_tokens():
    page = FakePage(payloads=[user()])
    logs = []

    def get(*_args, **_kwargs):
        raise RuntimeError("disconnected from https://example.com/?access_token=PRIVATE_TEST_TOKEN")

    page.get = get
    with pytest.raises(AccountResolutionError) as captured:
        resolve_douyin_identity(HANDLE, page=page, log=logs.append)
    assert "PRIVATE_TEST_TOKEN" not in str(captured.value)
    assert "PRIVATE_TEST_TOKEN" not in "\n".join(logs)
    assert captured.value.__suppress_context__
