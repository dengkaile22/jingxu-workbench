"""Cookie persistence, fresh-environment thresholds, ownership and isolation."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.browser_environment import validate_session_directory
from core.browser_errors import BrowserEnvironmentRotated, BrowserSessionStopped
from core.browser_manager import BrowserManager
from core.browser_recovery import maintain_browser_cache
from core.cookie_store import CookieStore, normalize_login_cookies


def cookie(name="sessionid", value="synthetic-login", domain=".douyin.com", **extra):
    return {"name": name, "value": value, "domain": domain, "path": "/", "session": True, **extra}


def test_cookie_file_survives_environment_replacement(owned_browser):
    manager = owned_browser.make_manager(rotate_pages=2)
    first = manager.get_page()
    first.cookies = [cookie(), cookie("msToken", "synthetic-environment"), cookie("ks_auth", domain=".kuaishou.com")]
    first_profile = Path(manager.user_data_dir)
    manager.mark_page_processed()
    assert not manager.rotate_if_due()
    manager.mark_page_processed()
    assert manager.rotate_if_due()
    second = manager.get_page()
    assert second.process_id != first.process_id and manager.environment_generation == 2
    assert not first_profile.exists()
    assert {item["name"] for item in second.cookies} == {"sessionid", "ks_auth"}
    assert manager.cookie_store.path.is_file()


def test_elapsed_time_replaces_environment_independently_of_page_count(owned_browser):
    manager = owned_browser.make_manager(rotate_seconds=60, rotate_pages=100)
    clock = [0.0]
    manager._clock = lambda: clock[0]
    first = manager.get_page()
    clock[0] = 59.9
    assert not manager.rotate_if_due()
    clock[0] = 60.0
    assert manager.rotate_if_due()
    assert manager.get_page().process_id != first.process_id and manager._page_units == 0


def test_checkpoint_signals_rotation_to_crawler(owned_browser):
    manager = owned_browser.make_manager(rotate_pages=1)
    manager.get_page()
    manager.mark_page_processed()
    with pytest.raises(BrowserEnvironmentRotated):
        maintain_browser_cache(manager, 1)
    assert manager.environment_generation == 2


def test_cookie_save_failure_prevents_rotation_and_keeps_live_environment(owned_browser, monkeypatch):
    manager = owned_browser.make_manager(rotate_pages=1)
    page = manager.get_page()
    page.cookies = [cookie()]
    profile = Path(manager.user_data_dir)
    monkeypatch.setattr(manager.cookie_store, "save", lambda *_args: (_ for _ in ()).throw(OSError("synthetic write failure")))
    manager.mark_page_processed()
    with pytest.raises(OSError):
        manager.rotate_if_due()
    assert manager._page is page and page.states.is_alive and profile.exists()
    assert manager.environment_generation == 1


def test_unverified_page_is_disconnected_without_closing_other_browser(owned_browser, monkeypatch):
    from core import browser_runtime
    manager = owned_browser.make_manager()
    original = owned_browser.Page
    foreign = []
    def connect(**kwargs):
        page = original(**kwargs)
        page.process_id += 999
        foreign.append(page)
        return page
    monkeypatch.setattr(browser_runtime, "ChromiumPage", connect)
    with pytest.raises(RuntimeError, match="归属未确认"):
        manager.get_page()
    assert foreign[0].states.is_alive
    assert owned_browser.quit_count == 0
    assert all(process.poll() is not None for process in owned_browser.processes)
    assert not any(method == "Network.setCookies" for method, _ in foreign[0].calls)


def test_same_cookie_store_has_single_writer_with_independent_profiles(owned_browser):
    first = owned_browser.make_manager()
    first.get_page()
    second = owned_browser.make_manager()
    with pytest.raises(RuntimeError, match="Cookie 存储"):
        second.get_page()
    first.close()
    second.get_page()
    assert second.environment_generation == 1


def test_personal_browser_data_directory_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    personal = tmp_path / "Microsoft/Edge/User Data"
    with pytest.raises(ValueError, match="个人资料"):
        validate_session_directory(personal)
    with pytest.raises(ValueError):
        validate_session_directory(personal / "Default")


def test_saved_credentials_are_filtered_and_expiry_is_preserved():
    payload = [cookie(), cookie("msToken"), cookie("ttwid"), cookie("s_v_web_id"),
               cookie(domain=".douyin.com.foreign.example"),
               cookie("expired", session=False, expires=99), cookie("valid", session=False, expires=1000)]
    normalized = normalize_login_cookies(payload, now=100)
    assert {item["name"] for item in normalized} == {"sessionid", "valid"}
    assert next(item for item in normalized if item["name"] == "valid")["expires"] == 1000


def test_environment_cleanup_retries_short_file_lock_after_partial_delete(tmp_path, monkeypatch):
    from core import browser_environment
    root = tmp_path / "session"
    path, token = browser_environment.create_environment(root)
    (path / "locked.sqlite").write_bytes(b"synthetic")
    actual = browser_environment.shutil.rmtree
    calls = []
    def temporarily_locked(target):
        calls.append(target)
        if len(calls) == 1:
            (path / ".jingxu-environment.json").unlink()
            raise PermissionError("synthetic short file lock")
        return actual(target)
    monkeypatch.setattr(browser_environment.shutil, "rmtree", temporarily_locked)
    monkeypatch.setattr("core.profile_lock.profile_holder_state", lambda _root: ())
    assert browser_environment.remove_environment(root, path, token)
    assert len(calls) == 2 and not path.exists()


def test_environment_cleanup_refuses_external_unmarked_directory(tmp_path):
    from core.browser_environment import remove_environment
    root, outside = tmp_path / "session", tmp_path / "external-browser"
    outside.mkdir()
    marker = outside / "Cookies"
    marker.write_bytes(b"synthetic-external-login")
    assert not remove_environment(root, outside, "untrusted-token")
    assert marker.read_bytes() == b"synthetic-external-login"


def test_unchanged_import_does_not_replace_new_login_after_rotation(tmp_path, monkeypatch):
    source = tmp_path / "cookies-import.json"
    source.write_text(json.dumps([cookie()]), encoding="utf-8")
    monkeypatch.setenv("JINGXU_SPIDER_COOKIES", str(source))
    store = CookieStore(tmp_path / "session")
    assert store.seed_import()[0]["value"] == "synthetic-login"
    store.save([cookie(value="synthetic-updated-login")])
    reloaded = CookieStore(tmp_path / "session")
    assert reloaded.seed_import()[0]["value"] == "synthetic-updated-login"


@pytest.mark.integration
def test_real_rotations_restore_cookies_reset_storage_and_leave_other_browser_alive(tmp_path, monkeypatch):
    from DrissionPage import ChromiumPage, ChromiumOptions
    from core import cookie_store
    from core.browser_manager import find_browser_path
    browser = find_browser_path()
    if not browser:
        pytest.skip("Chromium browser required")
    monkeypatch.setattr(cookie_store, "COOKIE_ROOTS", (*cookie_store.COOKIE_ROOTS, "127.0.0.1"))
    monkeypatch.setenv("JINGXU_SPIDER_COOKIES", str(tmp_path / "unused-import.json"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_GET(self):
            body = b"<html><head><title>owned profile fixture</title></head><body>author profile</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f"http://127.0.0.1:{server.server_port}/author"
    # Simulates an already-running local browser, deliberately outside the
    # crawler's session root, with its own login and storage.
    import socket
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
    external_options = ChromiumOptions(read_file=False).set_browser_path(browser).set_user_data_path(tmp_path / "external-browser").set_local_port(port).headless()
    external = ChromiumPage(addr_or_opts=external_options)
    manager = BrowserManager(headless=True, user_data_dir=str(tmp_path / "crawler"), browser_path=browser, rotate_pages=2, rotate_seconds=60)
    try:
        external.get(url)
        external.run_js("document.cookie='sessionid=external-synthetic-login; path=/'; localStorage.setItem('external','unchanged');")
        external_pid = external.process_id
        # An unrelated live debugger must be rejected using a read-only call,
        # before any browser-control object or cookie restore is created.
        import os
        from types import SimpleNamespace
        probe = BrowserManager(headless=True, user_data_dir=str(tmp_path / "rejected-connection"), browser_path=browser)
        probe._process = SimpleNamespace(pid=os.getpid())
        probe._debugger_url = f"ws://127.0.0.1:{port}/devtools/browser/{external.browser.id}"
        with pytest.raises(RuntimeError, match="拒绝连接"):
            probe._verify_debugger_owner()
        probe._process = None
        probe.close()
        assert external.states.is_alive and "sessionid=external-synthetic-login" in external.run_js("return document.cookie;")
        first = manager.get_page(); first.get(url)
        first.run_js("document.cookie='sessionid=crawler-synthetic-login; path=/'; document.cookie='msToken=old-environment; path=/'; localStorage.setItem('old-environment','discard');")
        first_pid, first_path = first.process_id, Path(manager.user_data_dir)
        assert first_pid != external_pid
        assert manager.save_cookies()
        manager.mark_page_processed(); manager.mark_page_processed()
        assert manager.rotate_if_due()
        second = manager.get_page(); second.get(url)
        second_pid, second_path = second.process_id, Path(manager.user_data_dir)
        assert second_pid not in (first_pid, external_pid) and not first_path.exists()
        assert "sessionid=crawler-synthetic-login" in second.run_js("return document.cookie;")
        assert "msToken=old-environment" not in second.run_js("return document.cookie;")
        assert second.run_js("return localStorage.getItem('old-environment');") is None
        manager._clock = lambda: manager._started_at + 61
        assert manager.rotate_if_due()
        manager._clock = __import__('time').monotonic
        third = manager.get_page(); third.get(url)
        assert third.process_id not in (first_pid, second_pid, external_pid) and not second_path.exists()
        assert "sessionid=crawler-synthetic-login" in third.run_js("return document.cookie;")
        manager.stop()
        assert external.process_id == external_pid and external.states.is_alive
        assert "sessionid=external-synthetic-login" in external.run_js("return document.cookie;")
        assert external.run_js("return localStorage.getItem('external');") == "unchanged"
        assert not list((manager.session_directory / 'environments').glob('env-*'))
        assert manager.cookie_store.path.is_file()
        with pytest.raises(BrowserSessionStopped): manager.get_page()
    finally:
        manager.close(); external.quit()
        server.shutdown(); server.server_close(); thread.join(timeout=2)
