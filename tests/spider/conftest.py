"""让爬虫自身的测试可以 ``import core.*``。"""

import importlib.util
import sys
from pathlib import Path
import copy
from types import SimpleNamespace
import pytest

SPIDER_ROOT = Path(__file__).resolve().parents[2] / "extensions" / "spider"
if str(SPIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIDER_ROOT))

# 暴露外层 tests/conftest.py 中的共用辅助，防止 pytest 遍历子目录时同名 conftest 模块互相覆盖
_parent_conftest = Path(__file__).resolve().parents[1] / "conftest.py"
if _parent_conftest.is_file():
    _spec = importlib.util.spec_from_file_location("_parent_conftest", _parent_conftest)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        make_asset = getattr(_mod, "make_asset", None)
        wait_until = getattr(_mod, "wait_until", None)


@pytest.fixture
def owned_browser(monkeypatch, tmp_path):
    """An owned-process double; lifecycle tests never launch a user's browser."""
    from core import browser_runtime
    from core.browser_manager import BrowserManager
    from DrissionPage.errors import PageDisconnectedError
    state = SimpleNamespace(processes=[], pages=[], managers=[], quit_count=0)
    monkeypatch.setenv("JINGXU_SPIDER_COOKIES", str(tmp_path / "unused-import.json"))
    monkeypatch.setattr("core.profile_lock.profile_holder_state", lambda _root, **_kwargs: ())

    class Process:
        def __init__(self):
            self.pid = 50000 + len(state.processes)
            self.returncode = None
            state.processes.append(self)
        def poll(self): return self.returncode
        def terminate(self): self.returncode = 0
        def kill(self): self.returncode = 0
        def wait(self, **_kwargs): self.returncode = 0; return 0

    class Guard:
        def __init__(self): self.terminated = False; self.closed = False
        def terminate(self, process, **_kwargs): self.terminated = True; process.terminate()
        def close(self): self.closed = True

    class Page:
        def __init__(self, *, addr_or_opts):
            self.process = state.processes[-1]
            self.process_id = self.process.pid
            self.options = addr_or_opts
            self.states = SimpleNamespace(is_alive=True)
            self.cookies = []
            self.calls = []
            self.title = "正常主页"
            self.url = "about:blank"
            self.body = "正常主页"
            self.browser = SimpleNamespace(_driver=SimpleNamespace(stop=lambda: self.calls.append(("disconnect", {}))))
            self.listen = SimpleNamespace(listening=False, start=lambda *_args: None, stop=lambda: None)
            state.pages.append(self)
        def run_cdp(self, method, **kwargs):
            if not self.states.is_alive:
                raise PageDisconnectedError()
            self.calls.append((method, kwargs))
            if method == "Network.getAllCookies": return {"cookies": copy.deepcopy(self.cookies)}
            if method == "Network.setCookies": self.cookies = copy.deepcopy(kwargs["cookies"])
            return {}
        def run_js(self, script, **_kwargs):
            if not self.states.is_alive: raise PageDisconnectedError()
            return {"text": self.body, "hasVideos": False} if "hasVideos" in script else ""
        def get(self, url, **_kwargs): self.url = url; return True
        def quit(self, **_kwargs):
            state.quit_count += 1
            self.states.is_alive = False
            self.process.terminate()

    def launch(manager, options):
        if manager not in state.managers: state.managers.append(manager)
        manager._process = Process()
        manager._guard = Guard()
        manager._debugger_url = f"ws://{options.address}/devtools/browser/test-{manager._process.pid}"
    monkeypatch.setattr(browser_runtime.CookieBrowserRuntime, "_launch_owned_browser", launch)
    monkeypatch.setattr(browser_runtime, "ChromiumPage", Page)
    state.Page = Page
    state.launch = launch
    state.make_manager = lambda **kwargs: BrowserManager(user_data_dir=str(tmp_path / "session"), **kwargs)
    yield state
    for manager in state.managers:
        manager.close()
