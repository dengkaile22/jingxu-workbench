"""Cache maintenance must never remove cookies or other persistent login state."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.browser_cache import CACHE_DIRECTORIES, ProfileSessionLock, cleanup_profile_cache
from core.browser_manager import BrowserManager
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


def test_browser_lifecycle_automatically_cleans_without_losing_cookies(tmp_path, monkeypatch):
    cookie = write(tmp_path,'Default/Network/Cookies')
    cache = write(tmp_path,'Default/Cache/before')
    monkeypatch.setattr('core.profile_lock.profile_holder_state',lambda _root: ())
    page = SimpleNamespace(quit=lambda: None)
    monkeypatch.setattr('core.browser_manager.ChromiumPage',lambda **_kwargs: page)
    manager = BrowserManager(user_data_dir=str(tmp_path))
    assert manager.get_page() is page
    assert not cache.exists()
    cache = write(tmp_path,'Default/Cache/during')
    manager.close()
    assert not cache.exists()
    assert cookie.read_bytes() == b'fake-login-state'
    manager.get_page(); manager.close()


def test_port_selection_retains_original_login_profile(tmp_path):
    manager=BrowserManager(user_data_dir=str(tmp_path))
    options=manager.get_options()
    assert Path(options.user_data_path).resolve() == tmp_path.resolve()
    assert not options.is_auto_port
    assert options.address.startswith('127.0.0.1:')


def test_browser_start_failure_releases_session_lease(tmp_path, monkeypatch):
    monkeypatch.setattr('core.profile_lock.profile_holder_state',lambda _root: ())
    def fail(**_kwargs):
        raise RuntimeError('synthetic browser failure')
    monkeypatch.setattr('core.browser_manager.ChromiumPage',fail)
    manager=BrowserManager(user_data_dir=str(tmp_path))
    with pytest.raises(RuntimeError): manager.get_page()
    lock=ProfileSessionLock(tmp_path)
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


def test_cached_disconnected_page_reopens_same_profile_and_preserves_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr('core.profile_lock.profile_holder_state', lambda _root: ())
    cookie = write(tmp_path, 'Default/Network/Cookies')
    pages = []
    options = []
    def create(**kwargs):
        options.append(kwargs['addr_or_opts'])
        page = SimpleNamespace(states=SimpleNamespace(is_alive=True), quit=lambda: None)
        pages.append(page)
        return page
    monkeypatch.setattr('core.browser_manager.ChromiumPage', create)
    manager = BrowserManager(user_data_dir=str(tmp_path))
    first = manager.get_page()
    first.states.is_alive = False
    try:
        second = manager.get_page()
        assert second is not first and len(pages) == 2
        assert all(Path(option.user_data_path).resolve() == tmp_path.resolve() for option in options)
        assert cookie.read_bytes() == b'fake-login-state'
    finally:
        manager.close()


def test_stop_is_permanent_and_does_not_relaunch(tmp_path, monkeypatch):
    monkeypatch.setattr('core.profile_lock.profile_holder_state', lambda _root: ())
    launches = []
    def create(**_kwargs):
        launches.append(1)
        return SimpleNamespace(quit=lambda: None)
    monkeypatch.setattr('core.browser_manager.ChromiumPage', create)
    manager = BrowserManager(user_data_dir=str(tmp_path))
    manager.get_page()
    manager.stop()
    with pytest.raises(BrowserSessionStopped):
        manager.get_page(force_new=True)
    assert len(launches) == 1
    lock = ProfileSessionLock(tmp_path)
    assert lock.acquire()
    lock.close()


def test_close_releases_lease_even_when_page_properties_and_quit_fail(tmp_path, monkeypatch):
    monkeypatch.setattr('core.profile_lock.profile_holder_state', lambda _root: ())
    class DeadPage:
        @property
        def process_id(self):
            raise PageDisconnectedError()
        def quit(self):
            raise PageDisconnectedError()
    monkeypatch.setattr('core.browser_manager.ChromiumPage', lambda **_kwargs: DeadPage())
    manager = BrowserManager(user_data_dir=str(tmp_path))
    manager.get_page()
    monkeypatch.setattr('core.profile_lock.profile_holder_state', lambda _root: (_ for _ in ()).throw(OSError()))
    manager.close()
    assert manager._page is None
    lock = ProfileSessionLock(tmp_path)
    assert lock.acquire()
    lock.close()


def test_cancel_during_startup_closes_created_browser_without_orphan(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    monkeypatch.setattr('core.profile_lock.profile_holder_state', lambda _root: ())
    launching = threading.Event()
    continue_launch = threading.Event()
    quit_calls = []
    def create(**_kwargs):
        launching.set()
        assert continue_launch.wait(3)
        return SimpleNamespace(quit=lambda: quit_calls.append(1))
    monkeypatch.setattr('core.browser_manager.ChromiumPage', create)
    manager = BrowserManager(user_data_dir=str(tmp_path))
    with ThreadPoolExecutor(max_workers=2) as pool:
        start = pool.submit(manager.get_page)
        assert launching.wait(3)
        cancel = pool.submit(manager.stop)
        assert manager._stopped.wait(3)
        continue_launch.set()
        with pytest.raises(BrowserSessionStopped):
            start.result(timeout=3)
        cancel.result(timeout=3)
    assert quit_calls == [1] and manager._page is None
    lock = ProfileSessionLock(tmp_path)
    assert lock.acquire()
    lock.close()
