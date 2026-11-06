"""Cookie-backed browser lifecycle with owned processes and fresh profiles."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from DrissionPage import ChromiumOptions, ChromiumPage
from websocket import create_connection
from core.browser_cache import ProfileSessionLock
from core.browser_environment import (
    DEFAULT_ROTATE_PAGES, DEFAULT_ROTATE_SECONDS, active_environment,
    create_environment, default_session_directory, remove_environment, validate_session_directory,
)
from core.browser_errors import BROWSER_SESSION_ERRORS, BrowserSessionStopped, BrowserSessionAbnormal
from core.cookie_store import CookieStore
from core.process_control import ProcessTreeGuard


class CookieBrowserRuntime:
    def __init__(self, *, headless=False, user_data_dir=None, browser_path=None, log_callback=None,
                 rotate_seconds=DEFAULT_ROTATE_SECONDS, rotate_pages=DEFAULT_ROTATE_PAGES, stealth_js=""):
        self.headless = bool(headless)
        self.browser_path = browser_path
        self.log = log_callback or (lambda _message: None)
        self.session_directory = validate_session_directory(user_data_dir or default_session_directory())
        self.cookie_store = CookieStore(self.session_directory)
        self.rotate_seconds = max(30.0, float(rotate_seconds))
        self.rotate_pages = max(1, int(rotate_pages))
        self._stealth_js = stealth_js
        self._page = None
        self._process = None
        self._guard = None
        self._owned_pid = None
        self._verified_owned = False
        self._session_lock = None
        self._environment_path = None
        self._environment_token = None
        self._close_lock = threading.RLock()
        self._stopped = threading.Event()
        self._cookie_stop = threading.Event()
        self._cookie_thread = None
        self._clock = time.monotonic
        self._started_at = 0.0
        self._page_units = 0
        self._login_mode = False
        self._active_headful = False
        self._debugger_url = ""
        self.environment_generation = 0
        self.last_cache_cleanup = None

    @property
    def user_data_dir(self):
        """Actual disposable profile; the stable cookie directory is separate."""
        return str(self._environment_path or self.session_directory)

    def get_options(self, force_headful=False):
        if self._environment_path is None:
            self._environment_path, self._environment_token = create_environment(self.session_directory)
        co = ChromiumOptions(read_file=False).clear_arguments().clear_prefs()
        co.set_user_data_path(self._environment_path)
        with socket.socket() as socket_:
            socket_.bind(("127.0.0.1", 0))
            co.set_local_port(socket_.getsockname()[1])
        co.set_timeouts(base=15, page_load=15, script=15).set_retry(0)
        if self.browser_path:
            co.set_browser_path(self.browser_path)
        co.headless(self.headless and not force_headful)
        co.use_system_user_path(False)
        co.existing_only(True)
        for flag in ("--no-first-run", "--no-default-browser-check", "--disable-gpu",
                     "--disable-blink-features=AutomationControlled", "--disable-infobars"):
            co.set_argument(flag)
        co.set_argument("--lang", "zh-CN")
        co.set_argument("--window-size", "1280,800")
        if os.name != "nt" and getattr(os, "geteuid", lambda: 1)() == 0:
            co.set_argument("--no-sandbox")
        return co

    def _launch_owned_browser(self, options):
        if self._stopped.is_set():
            raise BrowserSessionStopped("抓取已停止。")
        if not self.browser_path:
            raise RuntimeError("未找到 Chrome/Edge 内核，无法启动独立浏览器进程。")
        default = self._environment_path / "Default"
        default.mkdir(exist_ok=True)
        (default / "Preferences").write_text(json.dumps({"credentials_enable_service": False,
            "profile": {"password_manager_enabled": False, "default_content_setting_values": {"notifications": 2}}}), encoding="utf-8")
        arguments = [self.browser_path, *options.arguments,
                     "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={options.address.rsplit(':', 1)[1]}", "about:blank"]
        self._guard = ProcessTreeGuard()
        self._process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, **self._guard.spawn_kwargs())
        self._guard.attach(self._process)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = self._clock() + 15
        while self._clock() < deadline:
            if self._stopped.is_set():
                raise BrowserSessionStopped("抓取已停止。")
            if self._process.poll() is not None:
                raise RuntimeError("独立浏览器进程启动后提前退出。")
            try:
                with opener.open(f"http://{options.address}/json/version", timeout=0.5) as response:
                    metadata = json.load(response)
                if isinstance(metadata.get("webSocketDebuggerUrl"), str):
                    debugger = metadata["webSocketDebuggerUrl"]
                    if urlsplit(debugger).netloc != options.address:
                        raise RuntimeError("浏览器调试地址不属于本次独立进程。")
                    self._debugger_url = debugger
                    self._verify_debugger_owner()
                    return
            except (OSError, ValueError):
                pass
            self._stopped.wait(0.05)
        raise RuntimeError("独立浏览器启动超时，请检查浏览器内核。")

    def _verify_debugger_owner(self):
        """Check PID using a read-only CDP call before DrissionPage can connect."""
        connection = create_connection(self._debugger_url, suppress_origin=True, timeout=2)
        try:
            connection.send(json.dumps({"id": 1, "method": "SystemInfo.getProcessInfo"}))
            while True:
                message = json.loads(connection.recv())
                if message.get("id") == 1:
                    processes = message.get("result", {}).get("processInfo", [])
                    browser_pid = next((item.get("id") for item in processes if item.get("type") == "browser"), None)
                    if browser_pid is None or int(browser_pid) != self._process.pid:
                        raise RuntimeError("浏览器进程归属未确认，拒绝连接本机其他浏览器。")
                    return
        finally:
            connection.close()

    def _verify_owned_browser(self, page):
        actual = getattr(page, "process_id", None)
        if self._process is None or actual is None or int(actual) != self._process.pid:
            raise RuntimeError("浏览器进程归属未确认，已停止连接，避免接管本机浏览器。")
        self._owned_pid = int(actual)
        self._verified_owned = True

    def _write_active_environment(self):
        document = {"schemaVersion": 1, "directory": str(self._environment_path),
                    "token": self._environment_token, "browserPid": self._owned_pid,
                    "ownerPid": os.getpid(), "startedAt": time.time()}
        file = self.session_directory / "active-environment.json"
        temporary = self.session_directory / f".active-{self._environment_token}.tmp"
        temporary.write_text(json.dumps(document), encoding="utf-8")
        os.replace(temporary, file)

    def _ensure_lease(self):
        if self._session_lock is None:
            lock = ProfileSessionLock(self.session_directory)
            if not lock.acquire():
                raise RuntimeError("该 Cookie 存储正在用于登录或抓取，请结束软件内的会话后重试。")
            self._session_lock = lock

    def get_page(self, force_new=False, force_headful=False):
        with self._close_lock:
            if self._stopped.is_set():
                raise BrowserSessionStopped("抓取已停止。")
            if self._page is not None and not force_new:
                try:
                    force_new = getattr(getattr(self._page, "states", None), "is_alive", True) is False
                except BROWSER_SESSION_ERRORS:
                    force_new = True
                if not force_new and not self._login_mode and self.rotation_due():
                    force_new = True
                    self.log("[环境] 已达到更换周期，保存 Cookie 并启动新的独立浏览器进程。")
            if force_new:
                if self._page is not None and self._verified_owned:
                    try:
                        alive = getattr(getattr(self._page, "states", None), "is_alive", True) is not False
                        if alive:
                            self.save_cookies(strict=True)
                    except BrowserSessionAbnormal:
                        # Keep the last healthy login snapshot, never the bad
                        # environment's transient verification cookies.
                        pass
                    except BROWSER_SESSION_ERRORS:
                        pass
                self._close_environment(persist=False)
            if self._page is None:
                self._ensure_lease()
                try:
                    options = self.get_options(force_headful=force_headful)
                    self._active_headful = bool(force_headful)
                    self._launch_owned_browser(options)
                    # A websocket-only connection prevents the library from
                    # restarting a browser based on inherited mode settings.
                    options.set_address(self._debugger_url)
                    candidate = ChromiumPage(addr_or_opts=options)
                    self._page = candidate
                    self._verify_owned_browser(candidate)
                    if self._stopped.is_set():
                        raise BrowserSessionStopped("抓取已停止。")
                    count = self.cookie_store.restore(candidate)
                    if self._stealth_js:
                        candidate.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=self._stealth_js)
                    self._started_at = self._clock()
                    self._page_units = 0
                    self.environment_generation += 1
                    self._write_active_environment()
                    self._start_cookie_saver()
                    self.log(f"[环境] 第 {self.environment_generation} 个独立环境已启动；加载 {count} 条保存的登录 Cookie。")
                except Exception:
                    self._close_environment(persist=False)
                    if self._session_lock:
                        self._session_lock.close()
                        self._session_lock = None
                    raise
            return self._page

    def save_cookies(self, *, strict=False):
        if self._page is None or not self._verified_owned:
            return False
        try:
            from core.browser_recovery import check_browser_session
            check_browser_session(self._page)
            count = self.cookie_store.capture(self._page)
            return count >= 0
        except Exception:
            if strict:
                raise
            return False

    def _start_cookie_saver(self):
        stop = threading.Event()
        self._cookie_stop = stop
        def save_loop():
            while not stop.wait(1.0):
                if not self._close_lock.acquire(timeout=0.1):
                    continue
                try:
                    if stop.is_set():
                        break
                    if self._process is not None and self._process.poll() is not None:
                        self._close_environment(persist=False)
                        if self._session_lock is not None:
                            self._session_lock.close()
                            self._session_lock = None
                        return
                    self.save_cookies()
                finally:
                    self._close_lock.release()
        self._cookie_thread = threading.Thread(target=save_loop, name="jingxu-cookie-save", daemon=True)
        self._cookie_thread.start()

    def mark_page_processed(self):
        with self._close_lock:
            self._page_units += 1

    def rotation_due(self):
        return self._page is not None and not self._login_mode and (
            self._page_units >= self.rotate_pages or self._clock() - self._started_at >= self.rotate_seconds
        )

    def rotate_if_due(self):
        with self._close_lock:
            if self._stopped.is_set():
                raise BrowserSessionStopped("抓取已停止。")
            if not self.rotation_due():
                return False
            self.log(f"[环境] 已累计抓取 {self._page_units} 页或达到时间周期，正在更换全新环境。")
            self.get_page(force_new=True, force_headful=self._active_headful)
            return True

    def open_login_window(self, platform="douyin"):
        urls = {"douyin": "https://www.douyin.com/", "kuaishou": "https://www.kuaishou.com/"}
        if platform not in urls:
            raise ValueError("不支持的平台。")
        self._login_mode = True
        page = self.get_page(force_new=True, force_headful=True)
        page.get(urls[platform])
        return "已打开独立登录窗口，请扫码；登录 Cookie 将单独保存，抓取时使用新的浏览器环境。"

    def clear_runtime_cache(self):
        with self._close_lock:
            if self._stopped.is_set():
                raise BrowserSessionStopped("抓取已停止。")
            if self._page is None:
                return False
            self._page.run_cdp("Network.clearBrowserCache")
            return True

    def clear_site_session(self, platform):
        if platform not in ("douyin", "kuaishou"):
            raise ValueError("不支持的平台。")
        with self._close_lock:
            if self._stopped.is_set():
                raise BrowserSessionStopped("抓取已停止。")
            # The saved login cookies are separate from the contaminated
            # environment cookies. Never export an abnormal page's cookies.
            self._close_environment(persist=False)
            self.get_page(force_headful=self._active_headful)
            return True

    def _close_environment(self, *, persist):
        self._cookie_stop.set()
        thread, self._cookie_thread = self._cookie_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.3)
        saved = self.save_cookies() if persist and self._page is not None else True
        page, self._page = self._page, None
        path, token = self._environment_path, self._environment_token
        self._environment_path = self._environment_token = None
        try:
            if page is not None and self._verified_owned:
                try:
                    page.quit(timeout=2)
                except Exception:
                    pass
            elif page is not None:
                # Unverified connections must never send Browser.close.
                driver = getattr(getattr(page, "browser", None), "_driver", None)
                if driver is not None:
                    driver.stop()
            if self._guard is not None and self._process is not None:
                self._guard.terminate(self._process, timeout=2)
            if path is not None and token and saved:
                if remove_environment(self.session_directory, path, token):
                    current = active_environment(self.session_directory)
                    if current is None or current.get("token") == token:
                        (self.session_directory / "active-environment.json").unlink(missing_ok=True)
            elif path is not None and not saved:
                self.log("[Cookie] 本次保存未完成，已保留上次 Cookie 和当前环境资料，请检查数据目录后重新登录。")
        finally:
            if self._guard is not None:
                self._guard.close()
            self._guard = self._process = None
            self._owned_pid = None
            self._verified_owned = False
        return saved

    def close(self):
        with self._close_lock:
            try:
                return self._close_environment(persist=True)
            finally:
                if self._session_lock is not None:
                    self._session_lock.close()
                    self._session_lock = None

    def stop(self):
        self._stopped.set()
        self.close()
