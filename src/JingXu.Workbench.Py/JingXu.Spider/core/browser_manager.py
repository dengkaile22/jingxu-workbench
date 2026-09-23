"""
Browser management and session persistence using DrissionPage.
"""
import os
from typing import List, Optional
from DrissionPage import ChromiumPage, ChromiumOptions

BROWSER_PATH_ENV = "JINGXU_BROWSER_PATH"


def find_browser_path(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve a Chromium-based browser executable: explicit flag > env var > Chrome > Edge."""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)

    env_path = os.environ.get(BROWSER_PATH_ENV)
    if env_path:
        candidates.append(env_path)

    candidates.extend([
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ])

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


class BrowserManager:
    """Manages DrissionPage Chromium instance with persistent session profile."""

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        browser_path: Optional[str] = None,
    ):
        self.headless = headless
        if user_data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.user_data_dir = os.path.join(base_dir, "data", "browser_profile")
        else:
            self.user_data_dir = user_data_dir

        self.browser_path = find_browser_path(browser_path)
        os.makedirs(self.user_data_dir, exist_ok=True)
        self._page: Optional[ChromiumPage] = None

    def get_options(self, force_headful: bool = False) -> ChromiumOptions:
        """Create and configure ChromiumOptions."""
        co = ChromiumOptions()
        co.set_user_data_path(self.user_data_dir)

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
        co.set_argument("--window-size=1280,800")
        co.set_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        return co

    def get_page(self, force_new: bool = False, force_headful: bool = False) -> ChromiumPage:
        """Get or create ChromiumPage instance."""
        if force_new and self._page:
            self.close()

        if self._page is None:
            co = self.get_options(force_headful=force_headful)
            self._page = ChromiumPage(addr_or_opts=co)

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
        if self._page:
            try:
                self._page.quit()
            except Exception:
                pass
            finally:
                self._page = None
