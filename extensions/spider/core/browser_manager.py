"""
Browser management and session persistence using DrissionPage.
"""

import os
from typing import List, Optional
from core.browser_errors import BrowserSessionStopped, BrowserSessionAbnormal, BrowserEnvironmentRotated, BROWSER_SESSION_ERRORS
from core.browser_environment import DEFAULT_ROTATE_SECONDS, DEFAULT_ROTATE_PAGES
from core.browser_runtime import CookieBrowserRuntime

BROWSER_PATH_ENV = "JINGXU_BROWSER_PATH"
__all__ = ["BrowserManager", "BrowserSessionStopped", "BrowserSessionAbnormal", "BrowserEnvironmentRotated", "BROWSER_SESSION_ERRORS", "find_browser_path"]


PLATFORM_COOKIE_DOMAINS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "kuaishou": ("kuaishou.com", "kwai.com"),
}


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
            const originalQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
            window.navigator.permissions.query = (parameters) => (
                parameters && parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        }
    } catch (e) {}
})();
"""


class BrowserManager(CookieBrowserRuntime):
    """Launch owned processes with disposable environments and portable cookies."""

    def __init__(self, headless=False, user_data_dir=None, browser_path=None, log_callback=None,
                 *, rotate_seconds=DEFAULT_ROTATE_SECONDS, rotate_pages=DEFAULT_ROTATE_PAGES):
        super().__init__(headless=headless, user_data_dir=user_data_dir,
                         browser_path=find_browser_path(browser_path), log_callback=log_callback,
                         rotate_seconds=rotate_seconds, rotate_pages=rotate_pages, stealth_js=STEALTH_JS)
