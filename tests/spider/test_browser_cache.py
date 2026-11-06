"""Cache maintenance must never remove cookies or other persistent login state."""
import hashlib
from pathlib import Path

import pytest
from core.browser_cache import CACHE_DIRECTORIES, ProfileSessionLock, cleanup_profile_cache
from core.browser_manager import BrowserSessionStopped
from DrissionPage.errors import PageDisconnectedError


def write(root, relative, content=b'fake-login-state'):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_cleans_cache_and_preserves_all_login_storage(tmp_path):
    protected = [write(tmp_path, p) for p in (
        'Default/Cookies', 'Default/Cookies-wal', 'Default/Network/Cookies',
        'Default/Local Storage/leveldb/state', 'Default/Session Storage/state',
        'Default/IndexedDB/auth/state', 'Default/Service Worker/CacheStorage/state',
        'Default/Preferences', 'Local State', 'login_state.json',
        'Profile 1/Network/Cookies', 'Default/Cache/Cookies',
    )]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    caches = [write(tmp_path, f'{profile}/{name}/data/file', b'cache')
              for profile in ('Default', 'Profile 1') for name in CACHE_DIRECTORIES]
    unknown = write(tmp_path, 'UnrecognizedProfile/Cache/data')
    result = cleanup_profile_cache(tmp_path, probe=lambda _root: ())
    assert result.files_removed == len(caches)
    assert result.bytes_removed == 5 * len(caches)
    assert all(not p.exists() for p in caches)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p,digest in before.items())
    assert unknown.exists()
    assert cleanup_profile_cache(tmp_path, probe=lambda _root: ()).files_removed == 0


@pytest.mark.parametrize('holders', [(12,), None])
def test_skips_active_or_unknown_browser(tmp_path, holders):
    cache = write(tmp_path, 'Default/Cache/a')
    result = cleanup_profile_cache(tmp_path, probe=lambda _root: holders)
    assert result.skipped and cache.exists()


def test_session_lease_prevents_concurrent_cleanup(tmp_path):
    cache = write(tmp_path, 'Default/Cache/a')
    lock = ProfileSessionLock(tmp_path)
    assert lock.acquire()
    try:
        assert cleanup_profile_cache(tmp_path, probe=lambda _root: ()).skipped
        assert cache.exists()
    finally:
        lock.close()
    assert cleanup_profile_cache(tmp_path, probe=lambda _root: ()).files_removed == 1


def test_refuses_cache_links_to_external_content(tmp_path):
    profile = tmp_path/'profile'; profile.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    protected = write(outside, 'Cookies')
    cache = profile/'Default'/'Cache'; cache.parent.mkdir()
    try:
        cache.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('OS does not allow this test user to create symbolic links')
    assert cleanup_profile_cache(profile, probe=lambda _root: ()).files_removed == 0
    assert protected.read_bytes() == b'fake-login-state'


def test_browser_lifecycle_uses_fresh_profiles_and_saved_cookies(tmp_path, owned_browser):
    import json
    manager = owned_browser.make_manager()
    first = manager.get_page()
    first.cookies = [{'name': 'sessionid', 'value': 'synthetic-login', 'domain': '.douyin.com', 'path': '/', 'session': True}]
    profile = Path(manager.user_data_dir)
    cache = write(profile, 'Default/Cache/old', b'cache')
    manager.close()
    assert not profile.exists() and not cache.exists()
    stored = json.loads(manager.cookie_store.path.read_text(encoding='utf-8'))
    assert stored['cookies'][0]['value'] == 'synthetic-login'
    second = manager.get_page()
    assert Path(manager.user_data_dir) != profile
    assert second.cookies[0]['value'] == 'synthetic-login'
    assert second.process_id != first.process_id


def test_port_selection_uses_disposable_profile_and_owned_connection(tmp_path, owned_browser):
    manager = owned_browser.make_manager()
    options = manager.get_options()
    assert Path(options.user_data_path).parent == manager.session_directory/'environments'
    assert Path(options.user_data_path) != manager.session_directory
    assert not options.is_auto_port and options.is_existing_only
    assert options.address.startswith('127.0.0.1:')
    manager.close()


def test_browser_start_failure_releases_session_lease(tmp_path, monkeypatch, owned_browser):
    manager = owned_browser.make_manager()
    def fail(_options): raise RuntimeError('synthetic browser failure')
    monkeypatch.setattr(manager, '_launch_owned_browser', fail)
    with pytest.raises(RuntimeError): manager.get_page()
    lock = ProfileSessionLock(manager.session_directory)
    assert lock.acquire()
    lock.close()


def test_keeps_configured_cookie_import_even_if_placed_inside_cache(tmp_path,monkeypatch):
    cookie_source=write(tmp_path,'Default/Cache/private-login.json')
    ordinary=write(tmp_path,'Default/Cache/ordinary.bin',b'cache')
    monkeypatch.setenv('JINGXU_SPIDER_COOKIES',str(cookie_source))
    result=cleanup_profile_cache(tmp_path,probe=lambda _root:())
    assert result.files_removed==1 and not ordinary.exists()
    assert cookie_source.read_bytes()==b'fake-login-state'


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows junction regression')
def test_windows_cache_junction_cannot_remove_external_login_data(tmp_path):
    import subprocess
    profile=tmp_path/'profile'; profile.mkdir()
    outside=tmp_path/'outside'; outside.mkdir()
    cookie=write(outside,'Cookies')
    link=profile/'Default'/'Cache'; link.parent.mkdir()
    assert link.absolute().is_relative_to(tmp_path.absolute())
    assert outside.resolve().is_relative_to(tmp_path.resolve())
    quote=lambda path:"'"+str(path).replace("'","''")+"'"
    script=f'New-Item -ItemType Junction -Path {quote(link)} -Target {quote(outside)} | Out-Null'
    completed=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
    if completed.returncode:
        pytest.skip('OS does not permit junction creation for this user')
    assert cleanup_profile_cache(profile,probe=lambda _root:()).files_removed==0
    assert cookie.read_bytes()==b'fake-login-state'


def test_disconnected_page_reopens_fresh_environment_and_restores_cookies(tmp_path, owned_browser):
    manager = owned_browser.make_manager()
    first = manager.get_page()
    first.cookies = [{'name': 'sessionid', 'value': 'synthetic-login', 'domain': '.douyin.com', 'session': True}]
    assert manager.save_cookies()
    profile = Path(manager.user_data_dir)
    first.states.is_alive = False
    second = manager.get_page()
    assert second is not first and Path(manager.user_data_dir) != profile
    assert second.cookies[0]['value'] == 'synthetic-login'
    assert not profile.exists()


def test_stop_is_permanent_and_does_not_relaunch(tmp_path, owned_browser):
    manager = owned_browser.make_manager()
    manager.get_page()
    manager.stop()
    with pytest.raises(BrowserSessionStopped): manager.get_page()
    assert len(owned_browser.processes) == 1
    assert all(process.poll() is not None for process in owned_browser.processes)


def test_close_releases_lease_even_when_quit_fails(tmp_path, monkeypatch, owned_browser):
    manager = owned_browser.make_manager()
    page = manager.get_page()
    monkeypatch.setattr(page, 'quit', lambda **_kwargs: (_ for _ in ()).throw(PageDisconnectedError()))
    manager.close()
    assert manager._page is None and all(process.poll() is not None for process in owned_browser.processes)
    lock = ProfileSessionLock(manager.session_directory)
    assert lock.acquire()
    lock.close()


def test_cancel_during_startup_closes_created_browser_without_orphan(tmp_path, monkeypatch, owned_browser):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    manager = owned_browser.make_manager()
    launching, continue_launch = threading.Event(), threading.Event()
    def launch(options):
        launching.set()
        assert continue_launch.wait(3)
        owned_browser.launch(manager, options)
    monkeypatch.setattr(manager, '_launch_owned_browser', launch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        start = pool.submit(manager.get_page)
        assert launching.wait(3)
        stop = pool.submit(manager.stop)
        assert manager._stopped.wait(3)
        continue_launch.set()
        with pytest.raises(BrowserSessionStopped): start.result(timeout=3)
        stop.result(timeout=3)
    assert manager._page is None
    assert all(process.poll() is not None for process in owned_browser.processes)
    lock = ProfileSessionLock(manager.session_directory)
    assert lock.acquire()
    lock.close()
