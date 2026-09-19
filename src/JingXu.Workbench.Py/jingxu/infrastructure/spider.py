"""选品爬虫服务：账号配置持久化、环境检测与 CLI 调用。

爬虫引擎是仓库内的独立 Python 项目（``src/JingXu.Spider``，便携包内为
``runtime/spider``），通过其 CLI 以子进程方式驱动，结果经 ``--json-out``
交换。这样做的原因：

* 爬虫依赖 DrissionPage + Chromium，与主程序的可选依赖解耦；
* CLI 是爬虫的稳定契约（``--days``/``--min-accounts``/``--json-out`` 等），
  不需要把爬虫的 GUI 组件塞进主界面——这正是风格不统一的历史成因；
* 子进程可独立取消，不会拖住渲染队列。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from jingxu.infrastructure.app_paths import search_roots
from jingxu.infrastructure.paths import data_directory

SPIDER_ENV_DIR = "JINGXU_SPIDER_DIR"
SPIDER_ENV_PYTHON = "JINGXU_SPIDER_PYTHON"

# 单次抓取的兜底超时（秒）。真实抓取要逐账号翻页，这里只防挂死。
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0

# CLI 依赖模块（缺失时给出可操作提示，与爬虫 requirements.txt 对应）
REQUIRED_MODULES = ("DrissionPage", "requests", "openpyxl")
# 平台识别关键字（对齐爬虫 accounts 的 platform 字段）
PLATFORMS = ("douyin", "kuaishou")
PLATFORM_LABELS = {"douyin": "抖音", "kuaishou": "快手"}

TIME_MODES = (("days", "近 N 天"), ("range", "自定义日期"), ("all", "全部历史"))
FILTER_MODES = (("accounts", "仅按跨账号数"), ("total", "仅按总频次"), ("both", "两者都要满足"))


class SpiderError(RuntimeError):
    """选品爬虫不可用或执行失败。"""


@dataclass(frozen=True, slots=True)
class SpiderAccount:
    """一个对标账号。"""

    platform: str
    url_or_id: str
    name: str = ""
    enabled: bool = True

    @property
    def platform_label(self) -> str:
        return PLATFORM_LABELS.get(self.platform, self.platform)

    @property
    def display_name(self) -> str:
        return self.name or self.url_or_id

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "url_or_id": self.url_or_id,
            "name": self.name,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SpiderAccount":
        return cls(
            platform=str(payload.get("platform") or "douyin").strip().lower(),
            url_or_id=str(payload.get("url_or_id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            enabled=bool(payload.get("enabled", True)),
        )


def detect_platform(raw: str) -> str:
    """按链接/ID 特征识别平台；无法判断时回落抖音。

    识别顺序必须先判快手——抖音的兜底分支会让快手链接被误判（曾因此
    把 ``kuaishou.com/profile/...`` 当成抖音账号）。
    """
    text = (raw or "").strip().lower()
    if "kuaishou" in text or "kwai" in text:
        return "kuaishou"
    if "douyin" in text or "iesdouyin" in text:
        return "douyin"
    # 抖音分享的 sec_uid 以 MS4wLjABAAAA 开头
    if text.startswith("ms4wljabaaaa"):
        return "douyin"
    return "douyin"


@dataclass(frozen=True, slots=True)
class SpiderFilters:
    """抓取范围与保留门槛。"""

    time_mode: str = "days"
    days: int = 7
    start_date: str = ""
    end_date: str = ""
    min_accounts: int = 2
    min_occurrences: int = 1
    filter_by: str = "accounts"
    enable_fuzzy: bool = True
    fuzzy_threshold: float = 0.75
    max_scrolls: int = 25
    headless: bool = False


@dataclass(frozen=True, slots=True)
class SpiderConfig:
    """完整配置：账号 + 过滤条件。"""

    accounts: tuple[SpiderAccount, ...] = ()
    filters: SpiderFilters = field(default_factory=SpiderFilters)

    @property
    def enabled_accounts(self) -> tuple[SpiderAccount, ...]:
        return tuple(account for account in self.accounts if account.enabled and account.url_or_id)

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 1,
            "accounts": [account.to_dict() for account in self.accounts],
            "filters": {
                "timeMode": self.filters.time_mode,
                "days": self.filters.days,
                "startDate": self.filters.start_date,
                "endDate": self.filters.end_date,
                "minAccounts": self.filters.min_accounts,
                "minOccurrences": self.filters.min_occurrences,
                "filterBy": self.filters.filter_by,
                "enableFuzzy": self.filters.enable_fuzzy,
                "fuzzyThreshold": self.filters.fuzzy_threshold,
                "maxScrolls": self.filters.max_scrolls,
                "headless": self.filters.headless,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SpiderConfig":
        raw_accounts = payload.get("accounts") or []
        accounts = tuple(
            account
            for account in (SpiderAccount.from_dict(item) for item in raw_accounts if isinstance(item, dict))
            if account.url_or_id
        )
        raw = payload.get("filters") or {}
        defaults = SpiderFilters()
        filters = SpiderFilters(
            time_mode=_choice(raw.get("timeMode"), {mode for mode, _ in TIME_MODES}, defaults.time_mode),
            days=_int(raw.get("days"), defaults.days, minimum=1),
            start_date=str(raw.get("startDate") or "").strip(),
            end_date=str(raw.get("endDate") or "").strip(),
            min_accounts=_int(raw.get("minAccounts"), defaults.min_accounts, minimum=1),
            min_occurrences=_int(raw.get("minOccurrences"), defaults.min_occurrences, minimum=1),
            filter_by=_choice(raw.get("filterBy"), {mode for mode, _ in FILTER_MODES}, defaults.filter_by),
            enable_fuzzy=bool(raw.get("enableFuzzy", defaults.enable_fuzzy)),
            fuzzy_threshold=_float(raw.get("fuzzyThreshold"), defaults.fuzzy_threshold, 0.0, 1.0),
            max_scrolls=_int(raw.get("maxScrolls"), defaults.max_scrolls, minimum=1),
            headless=bool(raw.get("headless", defaults.headless)),
        )
        return cls(accounts=accounts, filters=filters)


def _choice(value: object, allowed: set[str], fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else fallback


def _int(value: object, fallback: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _float(value: object, fallback: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def spider_directory() -> Path | None:
    """定位爬虫源码目录（含 ``cli.py``）。"""
    candidates: list[Path] = []
    configured = os.environ.get(SPIDER_ENV_DIR, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    for parent in search_roots():
        candidates.append(parent / "runtime" / "spider")      # 便携包布局
        candidates.append(parent / "src" / "JingXu.Spider")   # 源码布局
        candidates.append(parent / "JingXu.Spider")

    for candidate in candidates:
        if (candidate / "cli.py").is_file():
            return candidate
    return None


def spider_python() -> Path | str:
    """爬虫解释器：随包 Python 优先，其次当前解释器。"""
    configured = os.environ.get(SPIDER_ENV_PYTHON, "").strip()
    if configured and Path(configured).is_file():
        return Path(configured)

    for parent in search_roots():
        for name in ("python.exe", "python"):
            candidate = parent / "runtime" / "python" / name
            if candidate.is_file():
                return candidate

    return sys.executable


@dataclass(frozen=True, slots=True)
class SpiderEnvironment:
    """环境自检结果。"""

    available: bool
    message: str
    directory: Path | None = None
    python: str = ""
    missing_modules: tuple[str, ...] = ()


def check_environment(*, timeout: float = 60.0) -> SpiderEnvironment:
    """检测爬虫目录、解释器与依赖模块。"""
    directory = spider_directory()
    if directory is None:
        return SpiderEnvironment(
            available=False,
            message="未找到选品爬虫源码（runtime/spider 或 src/JingXu.Spider）。",
        )

    python = str(spider_python())
    probe = (
        "import importlib.util as u,json;"
        f"mods={list(REQUIRED_MODULES)!r};"
        "print(json.dumps([m for m in mods if u.find_spec(m) is None]))"
    )
    try:
        completed = subprocess.run(
            [python, "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            cwd=str(directory),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return SpiderEnvironment(
            available=False,
            message=f"无法启动爬虫解释器：{error}",
            directory=directory,
            python=python,
        )

    missing: tuple[str, ...] = ()
    for line in reversed((completed.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("["):
            try:
                missing = tuple(str(item) for item in json.loads(line))
            except json.JSONDecodeError:
                missing = ()
            break

    if missing:
        return SpiderEnvironment(
            available=False,
            message=(
                "爬虫依赖缺失："
                + "、".join(missing)
                + "。请在爬虫目录执行 pip install -r requirements.txt。"
            ),
            directory=directory,
            python=python,
            missing_modules=missing,
        )

    return SpiderEnvironment(
        available=True,
        message=f"爬虫就绪（{directory.name}）。",
        directory=directory,
        python=python,
    )


def config_path() -> Path:
    """配置落盘位置：与爬虫自身约定一致（数据目录下 Spider/config.json）。"""
    return data_directory() / "Spider" / "config.json"


def results_path() -> Path:
    """最近一次抓取结果的落盘位置。"""
    return data_directory() / "Spider" / "last_result.json"


def exports_directory() -> Path:
    """报表导出目录（与传给爬虫 --export-dir 的值保持一致）。"""
    return data_directory() / "Spider" / "exports"


def profile_directory() -> Path:
    """浏览器登录态目录（首次扫码登录后复用，无需重复登录）。"""
    return data_directory() / "Spider" / "browser_profile"


# 与爬虫 core/browser_manager.find_browser_path 的探测顺序保持一致：
# 显式指定 > 环境变量 > Chrome（三处安装位置）> Edge（两处）。
# 爬虫跑在子进程里，拿不到它的探测结果，因此这里独立实现一份用于界面提示。
BROWSER_ENV = "JINGXU_BROWSER_PATH"


def find_browser() -> Path | None:
    """定位可用的 Chromium 内核浏览器；找不到时返回 ``None``。

    抖音/快手都需要真实浏览器内核，找不到时抓取必然失败，因此界面要提前
    提示，而不是等用户点了「开始抓取」才报错。
    """
    import os as _os

    candidates: list[str] = []
    configured = _os.environ.get(BROWSER_ENV, "").strip()
    if configured:
        candidates.append(configured)
    for pattern in (
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    ):
        candidates.append(_os.path.expandvars(pattern))

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def profile_status() -> tuple[bool, str]:
    """返回（是否已建立浏览器档案, 可读描述）。

    **注意**：无法从文件可靠判断「是否已成功登录」——``Cookies`` 这类文件
    浏览器首次启动就会生成，空档案也有。因此这里只如实报告档案状态与路径，
    真正的判据是抓取能否读到数据，不向用户做虚假保证。
    """
    directory = profile_directory()
    if not directory.is_dir() or not any(directory.iterdir()):
        return False, "尚未建立浏览器档案（首次抓取会打开浏览器要求扫码）"

    try:
        moment = datetime.fromtimestamp(directory.stat().st_mtime)
    except OSError:
        return True, "浏览器档案已存在"
    return True, f"浏览器档案已存在（{moment.strftime('%m-%d %H:%M')} 更新，若抓取无数据请重新扫码）"


def profile_ready() -> bool:
    """是否已建立可复用的浏览器档案。"""
    return profile_status()[0]


@dataclass(frozen=True, slots=True)
class SpiderLoginSession:
    """一次扫码登录会话：浏览器窗口由用户手动关闭。"""

    process: subprocess.Popen
    platform_label: str

    def is_running(self) -> bool:
        return self.process.poll() is None

    def close(self) -> None:
        if self.is_running():
            self.process.terminate()


def open_login_window(platform: str) -> SpiderLoginSession:
    """打开浏览器让用户扫码登录指定平台。

    登录态写入 :func:`profile_directory`，后续抓取直接复用；这是首次使用
    绕不开的一步，必须在界面上给出入口，否则用户撞到登录墙后无从下手。
    """
    if platform not in PLATFORMS:
        raise SpiderError(f"不支持的平台：{platform}")
    environment = check_environment()
    if not environment.available or environment.directory is None:
        raise SpiderError(environment.message)

    browser = find_browser()
    if browser is None:
        raise SpiderError(
            "未找到 Chromium 内核浏览器。请安装 Chrome 或 Edge，"
            f"或设置环境变量 {BROWSER_ENV} 指向浏览器可执行文件。"
        )

    arguments = [
        str(environment.directory / "cli.py"),
        "--login",
        platform,
        "--profile-dir",
        str(profile_directory()),
        "--browser-path",
        str(browser),
    ]
    environment_variables = dict(os.environ)
    environment_variables.update(
        {"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    )
    try:
        process = subprocess.Popen(
            [environment.python, *arguments],
            cwd=str(environment.directory),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment_variables,
        )
    except OSError as error:
        raise SpiderError(f"无法启动登录窗口：{error}") from error

    return SpiderLoginSession(
        process=process, platform_label=PLATFORM_LABELS.get(platform, platform)
    )


def validate_date_filters(filters: SpiderFilters) -> str:
    """校验自定义日期范围；返回空串表示通过，否则返回中文提示。

    界面用的是自由文本输入，此前不校验就传给爬虫，写错格式只会在抓取中途
    以晦涩错误失败，因此提前拦下。
    """
    if filters.time_mode != "range":
        return ""

    parsed: dict[str, datetime] = {}
    for label, raw in (("起始", filters.start_date), ("结束", filters.end_date)):
        if not raw:
            continue
        try:
            parsed[label] = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return f"{label}日期格式应为 YYYY-MM-DD，当前为「{raw}」。"

    if "起始" in parsed and "结束" in parsed and parsed["起始"] > parsed["结束"]:
        return "起始日期不能晚于结束日期。"
    return ""


class SpiderConfigStore:
    """账号、门槛与最近一次抓取结果的 JSON 持久化。

    结果也要落盘：抓取过程要开浏览器翻页，耗时以分钟计，若应用关闭就丢失，
    用户只能重跑一遍。
    """

    def __init__(self, path: Path | None = None, *, results: Path | None = None) -> None:
        self._path = Path(path) if path else config_path()
        self._results_path = Path(results) if results else self._path.with_name("last_result.json")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def results_path(self) -> Path:
        return self._results_path

    def load(self) -> SpiderConfig:
        if not self._path.is_file():
            return SpiderConfig()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return SpiderConfig()
        return SpiderConfig.from_dict(payload if isinstance(payload, dict) else {})

    def save(self, config: SpiderConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save_result(self, result: SpiderRunResult) -> None:
        """保存抓取结果；无内容的失败结果不覆盖已有结果。"""
        if not result.has_payload:
            return
        self._results_path.parent.mkdir(parents=True, exist_ok=True)
        self._results_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_result(self) -> SpiderRunResult | None:
        """读取上次结果；不存在或损坏时返回 ``None``。"""
        if not self._results_path.is_file():
            return None
        try:
            payload = json.loads(self._results_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        result = SpiderRunResult.from_dict(payload)
        return result if result.has_payload else None


def build_arguments(
    config: SpiderConfig,
    *,
    cli_path: Path,
    profile_dir: Path,
    export_dir: Path,
    json_out: Path,
    config_file: Path | None = None,
) -> list[str]:
    """把配置翻译为 CLI 参数（顺序稳定，便于测试与排查）。"""
    filters = config.filters
    arguments = [str(cli_path)]
    if config_file is not None:
        arguments += ["--config", str(config_file)]
    arguments += [
        "--json-out",
        str(json_out),
        "--profile-dir",
        str(profile_dir),
        "--export-dir",
        str(export_dir),
        "--time-mode",
        filters.time_mode,
        "--min-accounts",
        str(filters.min_accounts),
        "--min-occurrences",
        str(filters.min_occurrences),
        "--filter-by",
        filters.filter_by,
        "--fuzzy-threshold",
        f"{filters.fuzzy_threshold:g}",
        "--max-scrolls",
        str(filters.max_scrolls),
    ]
    if filters.time_mode == "days":
        arguments += ["--days", str(filters.days)]
    elif filters.time_mode == "range":
        if filters.start_date:
            arguments += ["--start-date", filters.start_date]
        if filters.end_date:
            arguments += ["--end-date", filters.end_date]
    if filters.headless:
        arguments.append("--headless")
    return arguments


@dataclass(frozen=True, slots=True)
class SpiderRunResult:
    """一次抓取的结果。"""

    success: bool
    message: str
    retained: tuple[dict, ...] = ()
    items: tuple[dict, ...] = ()
    excel_path: str = ""
    json_path: str = ""
    finished_at: str = ""

    @property
    def has_payload(self) -> bool:
        """是否有可复用的抓取内容（用于判断是否值得落盘/恢复）。"""
        return bool(self.retained or self.items)

    @property
    def finished_at_display(self) -> str:
        """完成时间的可读形式（落盘为 ISO，展示为「MM-DD HH:MM」）。"""
        if not self.finished_at:
            return ""
        try:
            moment = datetime.fromisoformat(self.finished_at)
        except ValueError:
            return self.finished_at
        return moment.strftime("%m-%d %H:%M")

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "message": self.message,
            "retained": list(self.retained),
            "items": list(self.items),
            "excelPath": self.excel_path,
            "jsonPath": self.json_path,
            "finishedAt": self.finished_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "SpiderRunResult":
        if not isinstance(payload, dict):
            return cls(success=False, message="结果格式无效。")
        return cls(
            success=bool(payload.get("success")),
            message=str(payload.get("message") or ""),
            retained=tuple(item for item in (payload.get("retained") or []) if isinstance(item, dict)),
            items=tuple(item for item in (payload.get("items") or []) if isinstance(item, dict)),
            excel_path=str(payload.get("excelPath") or payload.get("excel_path") or ""),
            json_path=str(payload.get("jsonPath") or payload.get("json_path") or ""),
            finished_at=str(payload.get("finishedAt") or payload.get("finished_at") or ""),
        )

    @property
    def video_urls(self) -> tuple[str, ...]:
        """从结果中提取去重后的视频链接（保序）。

        顺序：**保留商品优先**（那是用户真正要下载的）→ 其余带货记录；
        同一层级内保持原始先后。这与放入下载队列的意图一致。
        """
        seen: set[str] = set()
        urls: list[str] = []
        for entry in (*self.retained, *self.items):
            for url in _urls_in(entry):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        return tuple(urls)

    @property
    def effective_entries(self) -> tuple[tuple[bool, dict], ...]:
        """结果表要展示的条目：``(是否为保留商品, 条目)``。

        有保留商品时优先展示它们（那是用户真正要下载的）；否则回落到全部带货
        记录，避免出现「抓到了东西但表格是空的」。
        """
        if self.retained:
            return tuple((True, entry) for entry in self.retained)
        return tuple((False, entry) for entry in self.items)

    def urls_for_entries(self, entries: Sequence[dict]) -> tuple[str, ...]:
        """按给定条目提取去重后的下载链接（保序）。

        供「只把勾选的商品送入下载」使用；结果表里选中的行会映射回原始条目。
        """
        seen: set[str] = set()
        urls: list[str] = []
        for entry in entries:
            for url in _urls_in(entry):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        return tuple(urls)

    @property
    def product_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for entry in self.retained:
            name = str(entry.get("name") or entry.get("product_name") or entry.get("cleanedName") or "").strip()
            if name:
                names.append(name)
        return tuple(names)


def _urls_in(entry: object) -> list[str]:
    """从一个条目里取出视频链接。

    顺序是**嵌套 items 在前、条目自身链接在后**——这是既有契约
    （``ui/spider_page.extract_video_urls`` 的历史行为，调用方依赖它），
    因此不要"顺手"改成父先子后。
    """
    urls: list[str] = []

    def _read(candidate: object) -> str:
        if isinstance(candidate, dict):
            return str(candidate.get("video_url") or candidate.get("videoUrl") or "").strip()
        return str(getattr(candidate, "video_url", "") or "").strip()

    nested = None
    if isinstance(entry, dict):
        nested = entry.get("items")
    else:
        nested = getattr(entry, "items", None)
    if isinstance(nested, (list, tuple)):
        for child in nested:
            child_url = _read(child)
            if child_url:
                urls.append(child_url)

    direct = _read(entry)
    if direct:
        urls.append(direct)
    return urls


def parse_result_payload(payload: dict) -> SpiderRunResult:
    """解析爬虫 ``--json-out`` 的内容。"""
    if not isinstance(payload, dict):
        return SpiderRunResult(success=False, message="结果格式无效。")

    retained_raw = payload.get("retained_products") or payload.get("retainedProducts") or []
    items_raw = payload.get("all_items") or payload.get("allItems") or []
    retained = tuple(item for item in retained_raw if isinstance(item, dict))
    items = tuple(item for item in items_raw if isinstance(item, dict))
    return SpiderRunResult(
        success=True,
        message=f"抓取完成：保留 {len(retained)} 款商品，共 {len(items)} 条带货记录。",
        retained=retained,
        items=items,
        excel_path=str(payload.get("excel_path") or payload.get("excelPath") or ""),
    )


# 失败摘要里要跳过的"噪声行"：版本横幅、网址、纯分隔线等。
_NOISE_MARKERS = ("版本:", "版本：", "version", "http://", "https://", "===", "---")
_ERROR_MARKERS = (
    "traceback",
    "error",
    "exception",
    "failed",
    "failure",
    "错误",
    "失败",
    "异常",
    "无法",
    "拒绝",
    "超时",
)


def summarise_failure(lines: Sequence[str], *, exit_code: int | None = None) -> str:
    """从输出尾部挑出最有信息量的一行作为失败原因。

    直接取最后一行会把爬虫的版本横幅（如 ``版本: 4.1.1.4``）当成错误原因，
    实测误导性很强。这里优先返回含错误关键字的行，其次返回最后一行非噪声内容。
    """
    cleaned = [line.strip() for line in lines if line and line.strip()]
    if not cleaned:
        return f"退出码 {exit_code}" if exit_code is not None else "无输出"

    for line in reversed(cleaned):
        lowered = line.lower()
        if any(marker in lowered for marker in _ERROR_MARKERS):
            return line

    for line in reversed(cleaned):
        if not any(marker in line for marker in _NOISE_MARKERS):
            return line
    return cleaned[-1]


class SpiderRunner:
    """以子进程执行一次抓取；支持取消。"""

    def __init__(self, *, timeout: float | None = DEFAULT_RUN_TIMEOUT_SECONDS) -> None:
        # 真实抓取要逐个打开账号主页翻页，几分钟很正常；这里只作为兜底，
        # 避免异常挂死时无限等待（None 表示不限制，仅供测试使用）。
        self._timeout = timeout

    def run(
        self,
        config: SpiderConfig,
        *,
        on_log=None,  # noqa: ANN001 - Callable[[str], None] | None
        cancel_event=None,  # noqa: ANN001 - threading.Event | None
    ) -> SpiderRunResult:
        environment = check_environment()
        if not environment.available or environment.directory is None:
            return SpiderRunResult(success=False, message=environment.message)

        if not config.enabled_accounts:
            return SpiderRunResult(success=False, message="请先添加并启用至少一个对标账号。")

        # 日期范围提前校验：界面是自由文本输入，写错格式只会在抓取中途失败。
        date_issue = validate_date_filters(config.filters)
        if date_issue:
            return SpiderRunResult(success=False, message=date_issue)

        directory = environment.directory
        workdir = Path(tempfile.mkdtemp(prefix="jingxu-spider-"))
        json_out = workdir / "result.json"
        config_file = workdir / "config.json"
        profile_dir = profile_directory()
        export_dir = exports_directory()
        profile_dir.mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(parents=True, exist_ok=True)

        config_file.write_text(
            json.dumps(_cli_config_document(config), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        arguments = build_arguments(
            config,
            cli_path=directory / "cli.py",
            profile_dir=profile_dir,
            export_dir=export_dir,
            json_out=json_out,
            config_file=config_file,
        )

        environment_variables = dict(os.environ)
        environment_variables.update(
            {
                "PYTHONUNBUFFERED": "1",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                # 禁止写 __pycache__：安装到 Program Files 后爬虫源码目录是只读的
                # （或不该被污染），而写字节码失败会在部分 Python 版本上产生告警；
                # 更重要的是避免安装目录里混入运行期生成物。
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        try:
            process = subprocess.Popen(
                [environment.python, *arguments],
                cwd=str(directory),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment_variables,
            )
        except OSError as error:
            return SpiderRunResult(success=False, message=f"无法启动爬虫：{error}")

        tail: list[str] = []
        deadline = None if self._timeout is None else time.monotonic() + self._timeout
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    return SpiderRunResult(success=False, message="抓取已取消。")
                # 超时必须在这里判断：把 timeout 只交给 wait() 是无效的，
                # 因为只要子进程还在输出，这个 for 循环就永远不返回
                # （实测 timeout=30 仍跑了 84 秒）。
                if deadline is not None and time.monotonic() > deadline:
                    process.kill()
                    return SpiderRunResult(
                        success=False,
                        message=f"抓取超时（超过 {self._timeout:.0f} 秒），已终止。",
                    )
                text = line.rstrip()
                if text:
                    tail.append(text)
                    del tail[:-40]
                    if on_log is not None:
                        on_log(text)
            code = process.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            return SpiderRunResult(success=False, message="抓取超时，已终止。")
        finally:
            if process.poll() is None:
                process.kill()

        if code != 0:
            return SpiderRunResult(
                success=False,
                message=f"抓取失败：{summarise_failure(tail, exit_code=code)}",
            )

        if not json_out.is_file():
            return SpiderRunResult(success=False, message="爬虫未生成结果文件，请查看日志。")

        try:
            payload = json.loads(json_out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return SpiderRunResult(success=False, message=f"结果无法解析：{error}")

        result = parse_result_payload(payload)
        return replace(
            result,
            json_path=str(json_out),
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )


def _cli_config_document(config: SpiderConfig) -> dict:
    """生成爬虫 CLI 读取的配置文档（字段名对齐爬虫 core/models.py）。"""
    filters = config.filters
    return {
        "accounts": [
            {
                "platform": account.platform,
                "name": account.name,
                "url_or_id": account.url_or_id,
                "enabled": account.enabled,
                "sec_uid": "",
                "user_id": "",
            }
            for account in config.accounts
        ],
        "time_config": {
            "mode": filters.time_mode,
            "days": filters.days,
            "start_date": filters.start_date,
            "end_date": filters.end_date,
        },
        "filter_config": {
            "min_account_count": filters.min_accounts,
            "min_total_occurrences": filters.min_occurrences,
            "filter_by": filters.filter_by,
            "enable_fuzzy_cluster": filters.enable_fuzzy,
            "fuzzy_threshold": filters.fuzzy_threshold,
        },
        "headless": filters.headless,
        "max_scrolls_per_account": filters.max_scrolls,
        "export_dir": str(data_directory() / "Spider" / "exports"),
    }


def parse_accounts_text(text: str, *, platform: str = "") -> list[SpiderAccount]:
    """批量导入账号：每行一个链接或 ID，可用 ``名称=链接`` 指定备注名。

    ``platform`` 仅在显式传入 ``douyin``/``kuaishou`` 时生效；默认空表示
    按每条内容的特征自动识别平台（此前用形参默认值 ``"douyin"`` 覆盖了识别，
    导致快手链接被当成抖音账号）。
    """
    forced = platform.strip().lower() if platform.strip().lower() in PLATFORMS else ""
    accounts: list[SpiderAccount] = []
    for raw_line in (text or "").splitlines():
        for item in (segment.strip() for segment in raw_line.split(";")):
            if not item:
                continue

            name = ""
            target = item
            for separator in ("=", "\t", "|"):
                if separator in item:
                    head, _, tail = item.partition(separator)
                    if tail.strip():
                        name, target = head.strip(), tail.strip()
                        break
            if not target:
                continue

            accounts.append(
                SpiderAccount(
                    platform=forced or detect_platform(target),
                    url_or_id=target,
                    name=name,
                )
            )
    return accounts
