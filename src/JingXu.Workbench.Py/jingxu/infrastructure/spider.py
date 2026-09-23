"""选品爬虫服务：账号配置持久化、环境检测与 CLI 调用。

爬虫引擎随主程序源码树维护（``src/JingXu.Workbench.Py/JingXu.Spider``，
便携包内为 ``runtime/spider``），通过其 CLI 以子进程方式驱动，结果经
``--json-out`` 交换。这样做的原因：

* 爬虫依赖 DrissionPage + Chromium，与主程序的可选依赖解耦；
* CLI 是爬虫的稳定契约（``--days``/``--min-accounts``/``--json-out`` 等），
  不需要把爬虫的 GUI 组件塞进主界面——这正是风格不统一的历史成因；
* 子进程可独立取消，不会拖住渲染队列。
"""

from __future__ import annotations

import json
import os
import re
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
from jingxu.infrastructure.process_control import no_window_kwargs
from jingxu.infrastructure.profile_lock import (
    lock_files_present,
    probe_holder_pids,
    remove_stale_locks,
)

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
        """表格展示用名称：优先备注名，其次可读的账号标识。

        直接显示完整链接会占满整列且难以分辨，因此短链/Sec-UID 只显示尾部
        片段；抓取拿到真实昵称后会替换为昵称。
        """
        if self.name:
            return self.name
        value = self.url_or_id
        if value.startswith("http"):
            tail = value.rstrip("/").rsplit("/", 1)[-1]
            return tail or value
        return value[:16] + ("…" if len(value) > 16 else "")

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
        candidates.append(parent / "src" / "JingXu.Workbench.Py" / "JingXu.Spider")  # 仓库源码布局
        candidates.append(parent / "JingXu.Spider")           # 主程序项目根内的源码布局

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
            message="未找到选品爬虫源码（runtime/spider 或 src/JingXu.Workbench.Py/JingXu.Spider）。",
        )

    python = str(spider_python())
    probe = (
        "import importlib.util as u,json;"
        f"mods={list(REQUIRED_MODULES)!r};"
        "print(json.dumps([m for m in mods if u.find_spec(m) is None]))"
    )
    try:
        # -B：禁止写 __pycache__。这个探测在应用启动时就会跑，随包运行时位于
        # 安装目录，写字节码会污染安装目录（且卸载不清理这类"安装后新增"文件）。
        completed = subprocess.run(
            [python, "-B", "-c", probe],
            **no_window_kwargs(),
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
class ProfileLockState:
    """浏览器档案占用状态。

    ``busy`` 与 ``stale`` 必须分开：前者要拦住用户（真的会崩），后者要自动清理
    （崩溃残留，不清理会永久挡住用户）。旧实现把两者混为一谈——见
    ``profile_lock`` 模块开头的说明。
    """

    busy: bool
    holder_pids: tuple[int, ...] = ()
    stale_locks: tuple[str, ...] = ()
    cleared_locks: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.busy:
            pids = "、".join(str(pid) for pid in self.holder_pids)
            return (
                f"浏览器档案正被占用（进程 {pids}）。"
                "请先关闭登录窗口或另一个正在抓取的窗口，再重试。"
            )
        if self.cleared_locks:
            return f"已清理上次异常退出残留的锁文件（{'、'.join(self.cleared_locks)}）。"
        return ""


def profile_lock_state(
    *,
    probe=None,
    cleanup: bool = True,
    directory: Path | None = None,
) -> ProfileLockState:
    """检测档案占用，并（默认）清理确认无主的残留锁。

    ``probe`` 供测试注入；``directory`` 也供测试指定（默认取真实的登录态档案
    目录）。实现见 :mod:`jingxu.infrastructure.profile_lock`。
    """
    target = Path(directory) if directory is not None else profile_directory()
    if not target.is_dir():
        return ProfileLockState(busy=False)

    try:
        pids = probe_holder_pids(target, probe=probe)
    except Exception:  # noqa: BLE001 - 探测失败不得阻断流程
        return ProfileLockState(busy=False)

    if pids:
        return ProfileLockState(busy=True, holder_pids=tuple(pids))

    locks = lock_files_present(target)
    if not locks:
        return ProfileLockState(busy=False)

    cleared: tuple[str, ...] = ()
    if cleanup:
        try:
            cleared = remove_stale_locks(target)
        except Exception:  # noqa: BLE001 - 清理失败只降级为提示
            cleared = ()
    return ProfileLockState(busy=False, stale_locks=locks, cleared_locks=cleared)


def profile_in_use() -> bool:
    """profile 目录是否正被浏览器进程占用。

    Chromium 对 ``user_data_dir`` 加独占锁；登录浏览器还没关就又点「开始抓取」
    时，两个实例抢同一 profile 会启动失败（实测表现为 python.exe 应用程序错误
    0xc0000142，进程直接崩掉）。抓取前检查可给出可读提示，而不是让用户面对
    系统级崩溃弹窗。

    **判定依据是活着的浏览器进程**，不是锁文件是否存在：Windows 上
    ``Default/LOCK`` 是 0 字节普通文件，靠它判断恒为 False（旧实现的缺陷）；
    而崩溃残留的 ``SingletonLock`` 又会让判定恒为 True，把用户永久挡住。
    """
    return profile_lock_state().busy


def probe_time_filter(filters: "SpiderFilters") -> str:
    """把时间配置翻译成一句可读说明，便于用户核对设置是否生效。"""
    if filters.time_mode == "days":
        return f"近 {filters.days} 天"
    if filters.time_mode == "range":
        return f"{filters.start_date or '最早'} ~ {filters.end_date or '现在'}"
    return "全部历史"


@dataclass(slots=True)
class SpiderLoginSession:
    """一次扫码登录会话。

    由**应用进程自己**托管浏览器，不走爬虫 CLI 的 ``--login``：后者的
    ``run_login`` 在打开窗口后调用 ``input()`` 等待回车，一旦 stdin 不是
    交互终端就立刻抛 ``EOFError``，随后 ``finally`` 关闭浏览器——登录根本
    走不完，Cookie 也来不及落盘（已实测确认）。

    这里直接复用爬虫的 ``BrowserManager``，由界面按钮控制生命周期：
    用户扫码完成并点「我已登录」后 ``close()``，Cookie 正常持久化。
    """

    _manager: object
    platform_label: str
    profile: Path

    def is_running(self) -> bool:
        return self._manager is not None

    def close(self) -> None:
        """关闭浏览器并落盘 Cookie（幂等）。"""
        manager, self._manager = self._manager, None
        if manager is None:
            return
        try:
            manager.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 关闭失败不应影响退出流程
            pass


def _missing_login_modules() -> tuple[str, ...]:
    """扫码登录需要在**本进程**里真实可导入的模块。

    为什么不能只查 ``find_spec``：那只看包在不在，不看它能不能导入。打包版曾出现
    「``find_spec('DrissionPage')`` 有结果、但真正 ``import`` 时它的子依赖不在包里」
    的情况，报错被上层拼成一句无法定位的「组件加载失败」。这里实际导入一次，
    把缺的模块名如实列出来。
    """
    import importlib

    missing: list[str] = []
    for name in ("DrissionPage",):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - 缺依赖/库损坏都算不可用
            missing.append(name)
    return tuple(missing)


def open_login_window(platform: str) -> SpiderLoginSession:
    """打开浏览器让用户扫码登录指定平台。

    登录态写入 :func:`profile_directory`，后续抓取直接复用；首次使用绕不开
    这一步，必须在界面上给出入口，否则用户撞到登录墙后无从下手。
    """
    if platform not in PLATFORMS:
        raise SpiderError(f"不支持的平台：{platform}")

    directory = spider_directory()
    if directory is None:
        raise SpiderError("未找到选品爬虫源码（runtime/spider 或 src/JingXu.Workbench.Py/JingXu.Spider）。")

    browser = find_browser()
    if browser is None:
        raise SpiderError(
            "未找到 Chromium 内核浏览器。请安装 Chrome 或 Edge，"
            f"或设置环境变量 {BROWSER_ENV} 指向浏览器可执行文件。"
        )

    # 档案被占用时先拦住：两个实例抢同一 profile 会让新进程直接崩（0xc0000142），
    # 崩溃前不会给出任何可读原因。顺带清掉上次异常退出的残留锁。
    state = profile_lock_state()
    if state.busy:
        raise SpiderError(state.message)

    # 依赖缺失要在这里明确说清楚，而不是等 from core... 抛出
    # ModuleNotFoundError 再拼一句含义模糊的「组件加载失败」——
    # 实测该写法把「打包时没收集 DrissionPage」误报成「请安装爬虫依赖」。
    missing = _missing_login_modules()
    if missing:
        raise SpiderError(
            "扫码登录需要以下组件，当前运行环境中缺失："
            + "、".join(missing)
            + "。源码运行时请执行 pip install -e \".[spider]\"；"
            "安装包版本请改用随包运行时或反馈构建问题。"
        )

    # 让爬虫内部模块（core.* / ecommerce_spider.*）可被导入。应用侧没有同名
    # 顶层模块，因此不存在覆盖风险。
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

    profile = profile_directory()
    profile.mkdir(parents=True, exist_ok=True)
    try:
        from core.browser_manager import BrowserManager  # type: ignore[import-not-found]
    except Exception as error:  # noqa: BLE001 - 依赖缺失时给出可操作提示
        raise SpiderError(
            f"爬虫组件加载失败：{type(error).__name__}: {error}。"
            f"爬虫目录：{directory}。请确认该目录下的 core/ 组件完整。"
        ) from error

    try:
        manager = BrowserManager(
            headless=False,
            user_data_dir=str(profile),
            browser_path=str(browser),
        )
        manager.open_login_window(platform)
    except Exception as error:  # noqa: BLE001 - 浏览器启动失败原因很多，统一转可读提示
        raise SpiderError(
            f"无法打开登录页面：{type(error).__name__}: {error}。"
            f"浏览器：{browser}；档案：{profile}。"
            "若提示档案被占用，请关闭其它浏览器窗口或另一个选品登录窗口后重试。"
        ) from error

    return SpiderLoginSession(
        _manager=manager,
        platform_label=PLATFORM_LABELS.get(platform, platform),
        profile=profile,
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
class SpiderDiagnosticsView:
    """爬虫诊断摘要（环境 / 登录态 / 提取），供界面直接展示。

    原始结构由爬虫写入 ``--json-out`` 的 ``diagnostics`` 段；这里只提取界面需要
    的部分，避免把整棵结构耦合进 UI。
    """

    issues: tuple[dict, ...] = ()
    videos_scanned: int = 0
    videos_with_products: int = 0
    login_states: tuple[tuple[str, str], ...] = ()

    @property
    def blocked(self) -> bool:
        return any(str(item.get("level")) == "blocker" for item in self.issues)

    @property
    def blocking_message(self) -> str:
        """第一条阻断级问题的「说明 + 建议」，用于界面主提示。"""
        for item in self.issues:
            if str(item.get("level")) != "blocker":
                continue
            message = str(item.get("message") or "").strip()
            suggestion = str(item.get("suggestion") or "").strip()
            return f"{message}。{suggestion}" if suggestion else message
        return ""

    def lines(self) -> list[str]:
        """全部问题的可读行（阻断项标 ✗，提醒项标 !）。"""
        rendered: list[str] = []
        for item in self.issues:
            mark = "✗" if str(item.get("level")) == "blocker" else "!"
            message = str(item.get("message") or "").strip()
            suggestion = str(item.get("suggestion") or "").strip()
            rendered.append(f"{mark} {message}" + (f" → {suggestion}" if suggestion else ""))
        return rendered

    @classmethod
    def from_payload(cls, payload: object) -> "SpiderDiagnosticsView | None":
        if not isinstance(payload, dict) or not payload:
            return None
        extraction = payload.get("extraction") or {}
        raw_issues = payload.get("issues") or []
        login = payload.get("loginState") or {}
        return cls(
            issues=tuple(item for item in raw_issues if isinstance(item, dict)),
            videos_scanned=int(extraction.get("videosScanned") or 0),
            videos_with_products=int(extraction.get("videosWithProducts") or 0),
            login_states=tuple(
                (str(platform), str((entry or {}).get("status") or ""))
                for platform, entry in login.items()
                if isinstance(entry, dict)
            ),
        )


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
    diagnostics: SpiderDiagnosticsView | None = None

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
            "issues": [dict(item) for item in (self.diagnostics.issues if self.diagnostics else ())],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "SpiderRunResult":
        if not isinstance(payload, dict):
            return cls(success=False, message="结果格式无效。")
        raw_issues = payload.get("issues") or []
        issues = tuple(item for item in raw_issues if isinstance(item, dict))
        diagnostics = (
            SpiderDiagnosticsView(issues=issues) if issues else None
        )
        return cls(
            success=bool(payload.get("success")),
            message=str(payload.get("message") or ""),
            retained=tuple(item for item in (payload.get("retained") or []) if isinstance(item, dict)),
            items=tuple(item for item in (payload.get("items") or []) if isinstance(item, dict)),
            excel_path=str(payload.get("excelPath") or payload.get("excel_path") or ""),
            json_path=str(payload.get("jsonPath") or payload.get("json_path") or ""),
            finished_at=str(payload.get("finishedAt") or payload.get("finished_at") or ""),
            diagnostics=diagnostics,
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
        diagnostics=SpiderDiagnosticsView.from_payload(payload.get("diagnostics")),
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


def archive_failure_output(lines: Sequence[str], *, exit_code: int | None) -> Path | None:
    """把爬虫子进程的完整输出留档，返回文件路径。

    失败信息会被翻译成可读中文，但**原始输出不能丢**：没有它就无法排查
    「为什么失败」。因此这里把完整输出（含回溯）写入
    ``<数据目录>/logs/spider-YYYYMMDD-HHMMSS.log``，失败信息里会指向该文件。
    """
    if not lines:
        return None
    from jingxu.infrastructure.diagnostics import logs_directory

    try:
        directory = logs_directory()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = directory / f"spider-{stamp}.log"
        header = [
            "# 选品爬虫运行输出留档",
            f"# 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# 退出码：{exit_code if exit_code is not None else '未知'}",
            f"# 输出行数：{len(lines)}",
            "",
        ]
        # 全量写入会很大（翻页日志很多），保留尾部即可定位问题
        body = list(lines)[-400:]
        target.write_text("\n".join(header + body), encoding="utf-8")
        return target
    except OSError:
        return None


def _read_diagnostics(json_out: Path) -> SpiderDiagnosticsView | None:
    """从结果文件里取出 diagnostics 段；缺失或损坏时返回 ``None``。

    失败路径也要调用：爬虫的预检失败会以退出码 2 结束，此时诊断**只**存在于
    结果文件里。
    """
    if not json_out.is_file():
        return None
    try:
        payload = json.loads(json_out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return SpiderDiagnosticsView.from_payload(payload.get("diagnostics"))


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
                # -B 抑制字节码写入：随包运行时位于安装目录（可能只读），
                # 写 .pyc 会污染安装目录并与 MSI 清单文件数不一致。
                # 环境变量 PYTHONDONTWRITEBYTECODE 已设，这里再加一道保险，
                # 因为环境变量可能被用户的 shell 配置覆盖。
                [environment.python, "-B", *arguments],
                **no_window_kwargs(),
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
                    # 保留足够行数：失败时要留档完整上下文（留档函数再截取尾部 400 行）
                    del tail[:-400]
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
            # 非零退出也要读结果文件：爬虫在运行前自检失败时（退出码 2）会把
            # 环境诊断写进 --json-out。不读的话，界面只能看到一句「抓取失败」，
            # 而真正的阻断原因（缺浏览器/profile 被占用/未登录）永远到不了界面。
            diagnostics = _read_diagnostics(json_out)
            archive = archive_failure_output(tail, exit_code=code)
            message = f"抓取失败：{summarise_failure(tail, exit_code=code)}"
            if archive is not None:
                message += f"\n完整输出已留档：{archive}"
            return SpiderRunResult(success=False, message=message, diagnostics=diagnostics)

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


# 分享文案里的链接（抖音/快手短链、主页链接，以及 http(s) 通用形式）
_SHARE_LINK_RE = re.compile(r"https?://[^\s\u4e00-\u9fff，。！？、；：「」【】（）]+")
# 行首序号：分享文案常带「0- 」「2- 」前缀
_LEADING_INDEX_RE = re.compile(r"^\s*\d+\s*[-—.、]\s*")
# 昵称：快手用「」包裹；抖音话术为「查看TA的更多作品」不带昵称
_SHARE_NICKNAME_PATTERNS = (
    re.compile(r"[「【]([^」】]{1,32})[」】]"),
    re.compile(r"名为\s*([^\s，。！]{1,32})"),
)


def extract_share_link(text: str) -> str:
    """从分享文案/混合文本中抽出第一个链接；没有链接时返回空串。"""
    if not text:
        return ""
    candidate = _LEADING_INDEX_RE.sub("", text.strip())
    match = _SHARE_LINK_RE.search(candidate)
    if not match:
        # 没有链接：可能是纯 ID（数字或 Sec-UID），去掉序号前缀后原样返回
        stripped = candidate.strip()
        return stripped if stripped and " " not in stripped[:64] else ""
    return match.group(0).rstrip(".,;，。；、)]）】")


def extract_share_nickname(text: str) -> str:
    """从分享文案里取账号昵称；取不到返回空串。

    抖音的分享话术只写「查看TA的更多作品」，其中没有昵称，因此返回空是正常的，
    抓取完成后会用真实昵称补上。
    """
    if not text:
        return ""
    for pattern in _SHARE_NICKNAME_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            if not name or _looks_like_link(name):
                continue
            return name
    return ""


def _looks_like_link(value: str) -> bool:
    """判断一段文本是否更像链接/标识，而不是昵称。"""
    lowered = value.lower()
    if "http" in lowered or "/" in value or "@" in value:
        return True
    # 含 .com / .cn 等域名特征
    if re.search(r"\.(com|cn|net|org)\b", lowered):
        return True
    return False


def parse_accounts_text(text: str, *, platform: str = "") -> list[SpiderAccount]:
    """批量导入账号：每行一个账号，可用 ``名称=链接`` 指定备注名。

    直接粘贴 App 的**分享文案**也要能用——用户实际粘的就是这种整段文字：

    * ``0- 长按复制此条消息，打开抖音搜索，查看TA的更多作品。 https://v.douyin.com/xxx/ 8@0.com :2pm``
    * ``https://v.kuaishou.com/xxx 看了这么多快手，还是「牛奶巧巧」最好玩了！ 复制此消息，打开【快手】直接观看！``

    因此需要从中抽出真正的链接与昵称；此前会把整段文案当成账号链接存进
    账号表，爬虫自然无法处理。

    ``platform`` 仅在显式传入 ``douyin``/``kuaishou`` 时生效；默认空表示
    按每条内容的特征自动识别平台。
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

            # 分享文案：抽出链接，并从固定话术里取昵称
            link = extract_share_link(target)
            if link:
                target = link
                if not name:
                    name = extract_share_nickname(item)

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
