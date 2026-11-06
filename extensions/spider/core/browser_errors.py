"""Browser lifecycle signals shared by managers and crawlers."""
from DrissionPage.errors import PageDisconnectedError


class BrowserSessionStopped(RuntimeError):
    """Cancellation closed the browser and forbids relaunch."""


class BrowserSessionAbnormal(RuntimeError):
    """An abnormal-access page requires a fresh environment."""


class BrowserEnvironmentRotated(RuntimeError):
    """Continue the crawl checkpoint in the newly created environment."""


BROWSER_SESSION_ERRORS = (PageDisconnectedError, BrowserSessionStopped)
