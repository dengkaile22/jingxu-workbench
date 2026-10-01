"""
Browser management and session persistence using DrissionPage.
"""

import os
import socket
import time
import threading
from typing import List, Optional, Callable
from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError
from core.browser_cache import ProfileSessionLock, cleanup_profile_cache
from core.cookie_import import import_cookie_file

BROWSER_PATH_ENV = "JINGXU_BROWSER_PATH"


class BrowserSessionStopped(RuntimeError):
    """Cancellation closed the browser; it must not be reopened by recovery."""


BROWSER_SESSION_ERRORS = (PageDisconnectedError, BrowserSessionStopped)


def find_browser_path(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve a Chromium-based browser executable: explicit flag > env var > Chrome > Edge."""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)

    env_path = os.environ.get(BROWSER_PATH_ENV)
    if env_path:
        candidates.append(env_path)

    candidates.extend(
        [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
            ),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
            ),
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
    )

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


STEALTH_JS = """
(() => {
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        delete Object.getPrototypeOf(navigator).webdriver;
    } catch (e) {}

    try {
        if (!window.chrome) {
            window.chrome = {};
        }
        window.chrome.app = window.chrome.app || {
            isInstalled: false,
            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
        };
        window.chrome.runtime = window.chrome.runtime || {
            PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
            PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
            OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' }
        };
        window.chrome.loadTimes = window.chrome.loadTimes || function() {};
        window.chrome.csi = window.chrome.csi || function() {};
    } catch (e) {}

    try {
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en'],
            configurable: true
        });
    } catch (e) {}

    try {
        const fakePlugins = [
            { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
        ];
        fakePlugins.item = (i) => fakePlugins[i];
        fakePlugins.namedItem = (name) => fakePlugins.find(p => p.name === name) || null;
        fakePlugins.refresh = () => {};
        Object.defineProperty(navigator, 'plugins', {
            get: () => fakePlugins,
            configurable: true
        });
    } catch (e) {}

    try {
        if (window.navigator.permissions && window.navigator.permissions.query) {
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters && parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        }
    } catch (e) {}
})();
"""


class BrowserManager:
    """Manages DrissionPage Chromium instance with persistent session profile and environment stealth."""

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        browser_path: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.headless = headless
        self.log = log_callback or (lambda _message: None)
        if user_data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.user_data_dir = os.path.join(base_dir, "data", "browser_profile")
        else:
            self.user_data_dir = user_data_dir

        self.browser_path = find_browser_path(browser_path)
        os.makedirs(self.user_data_dir, exist_ok=True)
        self._page: Optional[ChromiumPage] = None
        self._session_lock = None
        self._close_lock = threading.RLock()
        self._stopped = threading.Event()
        self._owned_pid = None
        self.last_cache_cleanup = None

    def get_options(self, force_headful: bool = False) -> ChromiumOptions:
        """Create and configure ChromiumOptions with full anti-detection flags."""
        co = ChromiumOptions()
        co.set_user_data_path(self.user_data_dir)
        # DrissionPage auto_port replaces the persistent profile with a temp
        # profile. Select a free local port explicitly to retain login cookies.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            co.set_local_port(sock.getsockname()[1])
        co.set_timeouts(base=15, page_load=15, script=15)
        co.set_retry(0)

        if self.browser_path:
            co.set_browser_path(self.browser_path)

        if self.headless and not force_headful:
            co.set_argument("--headless=new")
        else:
            co.headless(False)

        co.set_argument("--no-first-run")
        co.set_argument("--no-default-browser-check")
        co.set_argument("--disable-gpu")
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--lang=zh-CN")
        co.set_argument("--disable-infobars")
        co.set_argument("--window-size=1280,800")
        co.set_pref("credentials_enable_service", False)
        co.set_pref("profile.password_manager_enabled", False)
        co.set_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        return co

    def get_page(
        self, force_new: bool = False, force_headful: bool = False
    ) -> ChromiumPage:
        """Get or create ChromiumPage instance with automated stealth script injection."""
        with self._close_lock:
            if self._stopped.is_set():
                raise BrowserSessionStopped("抓取已停止。")
            return self._get_page(force_new, force_headful)

    def _get_page(self, force_new: bool, force_headful: bool) -> ChromiumPage:
        if self._page is not None and not force_new:
            try:
                states = getattr(self._page, "states", None)
                force_new = states is not None and states.is_alive is False
            except PageDisconnectedError:
                force_new = True
            if force_new:
                self.log("[浏览器] 连接已断开，正在使用原登录资料重新打开。")
        if force_new:
            self._close_owned_page()
        if self._stopped.is_set():
            raise BrowserSessionStopped("抓取已停止。")

        if self._page is None:
            lock = ProfileSessionLock(self.user_data_dir)
            if not lock.acquire():
                raise RuntimeError("浏览器档案正在用于登录或抓取，请结束该会话后重试。")
            self._session_lock = lock
            try:
                from core.profile_lock import (
                    profile_holder_state,
                    lock_files_present,
                    remove_stale_locks,
                )

                holders = profile_holder_state(self.user_data_dir)
                if holders:
                    raise RuntimeError(
                        "登录浏览器仍在使用该档案，请关闭登录窗口后重试。"
                    )
                self._cleanup_cache(lock)
                if holders == () and lock_files_present(self.user_data_dir):
                    remove_stale_locks(self.user_data_dir)
                co = self.get_options(force_headful=force_headful)
                if self._stopped.is_set():
                    raise BrowserSessionStopped("抓取已停止。")
                self._page = ChromiumPage(addr_or_opts=co)
                try:
                    self._owned_pid = self._page.process_id
                except Exception:
                    self._owned_pid = None
                if self._stopped.is_set():
                    raise BrowserSessionStopped("抓取已停止。")
                try:
                    count = import_cookie_file(self._page, self.user_data_dir)
                    if count:
                        self.log(
                            f"[登录] 已导入 {count} 条登录 Cookie，内容仅保存在本机登录资料中。"
                        )
                except Exception:
                    self.log(
                        "[登录] Cookie 文件无法导入，已保留原有登录态，请检查文件格式。"
                    )
            except Exception:
                self._close_owned_page()
                raise

            # 注入环境隐藏防检测脚本到新文档生命周期中
            if hasattr(self._page, "run_cdp"):
                try:
                    self._page.run_cdp(
                        "Page.addScriptToEvaluateOnNewDocument", source=STEALTH_JS
                    )
                except Exception:
                    pass

        return self._page

    def open_login_window(self, platform: str = "douyin") -> str:
        """
        Open a visible browser window for the user to log in and save cookies.
        Platform can be 'douyin' or 'kuaishou'.
        """
        page = self.get_page(force_new=True, force_headful=True)
        if platform == "douyin":
            target_url = "https://www.douyin.com/"
        elif platform == "kuaishou":
            target_url = "https://www.kuaishou.com/"
        else:
            target_url = "https://www.douyin.com/"

        page.get(target_url)
        return f"已打开 {platform} 登录页面，请在弹出的浏览器中扫码或短信登录。登录完成后即可直接关闭窗口或继续使用。"

    def close(self):
        """Close browser instance safely."""
        with self._close_lock:
            self._close_owned_page()

    def stop(self):
        """Mark cancellation before closing, including during browser startup."""
        self._stopped.set()
        self.close()

    def _cleanup_cache(self, lock):
        self.last_cache_cleanup = cleanup_profile_cache(
            self.user_data_dir, session_lock=lock
        )
        result = self.last_cache_cleanup
        if result.files_removed:
            self.log(
                f"[缓存] 自动清理 {result.files_removed} 个缓存文件（{result.bytes_removed / 1024**2:.1f} MiB），Cookies 与登录资料保留。"
            )
        elif result.skipped:
            self.log(f"[缓存] 暂不清理：{result.reason}；Cookies 与登录资料保留。")

    def _close_owned_page(self):
        from core.profile_lock import profile_holder_state, terminate_profile_holders

        page, self._page = self._page, None
        owned_pid, self._owned_pid = self._owned_pid, None
        lock, self._session_lock = self._session_lock, None
        try:
            if page is not None:
                try:
                    page.quit()
                except Exception:
                    pass
                # Keep the lease until the owned process releases its profile.
                try:
                    deadline = time.monotonic() + 3.0
                    holders = profile_holder_state(self.user_data_dir)
                    while holders and time.monotonic() < deadline:
                        time.sleep(0.05)
                        holders = profile_holder_state(self.user_data_dir)
                    if holders and owned_pid is not None and owned_pid in holders:
                        terminate_profile_holders(self.user_data_dir, timeout=1.0)
                except Exception:
                    self.log("[浏览器] 无法确认退出状态，已保留档案；重新打开前会再次检查占用。")
            if lock is not None:
                try:
                    self._cleanup_cache(lock)
                except Exception:
                    self.log("[缓存] 本次清理未完成，Cookies 与登录资料保留。")
        finally:
            if lock is not None:
                lock.close()
        if self.user_data_dir:
            try:
                from core.profile_lock import (
                    lock_files_present,
                    probe_holder_pids,
                    remove_stale_locks,
                )

                if not probe_holder_pids(self.user_data_dir) and lock_files_present(
                    self.user_data_dir
                ):
                    remove_stale_locks(self.user_data_dir)
            except Exception:
                pass
