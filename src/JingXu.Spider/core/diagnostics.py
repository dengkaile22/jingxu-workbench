"""运行前环境自检与运行后诊断：把「跑不起来 / 抓不到」变成可读结论。

为什么需要
----------
用户实测遇到的失败几乎都缺乏可读解释：

* 同时抓两个平台直接崩溃（两个 Chromium 实例抢同一个 profile 目录）；
* 登录态过期后仍然跑，结果是 0 件而不是「请重新登录」；
* 商品提取不到，日志只说「累计发现带货商品 0 件」；
* 浏览器/解释器/依赖缺失时抛的是底层异常。

本模块把这些检查集中起来：运行前产出 ``preflight``（环境异常清单 + 修复建议），
运行后产出 ``diagnosis``（0 件的可能原因）。两者都会写进日志与 ``--json-out``。

Cookie / 登录态
---------------
Chromium 不支持「读取 cookie 判断是否登录」这种廉价做法，因此这里改为**行为证据**
记录：把每次抓取观察到的「是否需要登录」写入 ``data/login_state.json``，
据此判断登录态是否有效、是否需要重新扫码。这是可靠且不需要额外依赖的方式。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

# 各平台的登录页地址
LOGIN_URLS = {
    "douyin": "https://www.douyin.com/",
    "kuaishou": "https://www.kuaishou.com/",
}

# 运行前检查的依赖模块（与 requirements.txt 对应）
REQUIRED_MODULES = ("DrissionPage", "requests", "openpyxl")

# 页面里出现这些标记，说明站点把访客当未登录处理
LOGIN_WALL_MARKERS = (
    "登录后查看",
    "请先登录",
    "扫码登录",
    "登录即",
    "登录/注册",
    "立即登录",
    "请登录",
)

# 出现这些标记说明触发风控/验证码，继续跑只会更糟
RISK_MARKERS = (
    "验证码",
    "滑动验证",
    "安全验证",
    "操作过于频繁",
    "访问频繁",
)


@dataclass
class Issue:
    """一条环境或运行问题。"""

    level: str          # "blocker" 阻断 / "warning" 提醒
    code: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
        }

    def line(self) -> str:
        head = "✗" if self.level == "blocker" else "!"
        text = f"{head} [{self.code}] {self.message}"
        return f"{text} → {self.suggestion}" if self.suggestion else text


@dataclass
class PreflightReport:
    """运行前环境自检结果。"""

    ok: bool = True
    issues: list[Issue] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    def add(self, level: str, code: str, message: str, suggestion: str = "") -> None:
        self.issues.append(Issue(level, code, message, suggestion))
        if level == "blocker":
            self.ok = False

    @property
    def blockers(self) -> list[Issue]:
        return [item for item in self.issues if item.level == "blocker"]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [item.to_dict() for item in self.issues],
            "info": self.info,
        }


# ── 登录态记录 ──────────────────────────────────────────────────────────────


def login_state_path(profile_dir: Optional[str] = None) -> str:
    """登录态记录文件路径（默认放在 profile 目录旁边）。"""
    if profile_dir:
        base = os.path.dirname(os.path.abspath(profile_dir)) or "."
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "login_state.json")


def load_login_state(profile_dir: Optional[str] = None) -> dict:
    path = login_state_path(profile_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_login_state(
    platform: str,
    status: str,
    *,
    profile_dir: Optional[str] = None,
    detail: str = "",
) -> dict:
    """记录一次登录态观测。

    ``status``：``ok`` 正常 / ``required`` 需要登录 / ``risk`` 触发风控。
    """
    path = login_state_path(profile_dir)
    data = load_login_state(profile_dir)
    entry = {
        "status": status,
        "detail": detail[:200],
        "observedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if status == "ok":
        entry["lastOkAt"] = entry["observedAt"]
    data[platform] = entry
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return entry


def describe_login_state(platform: str, profile_dir: Optional[str] = None) -> str:
    """把登录态记录翻译成一句中文说明。"""
    entry = load_login_state(profile_dir).get(platform) or {}
    if not entry:
        return "尚无登录记录（首次抓取会要求扫码登录）"
    status = entry.get("status")
    observed = entry.get("observedAt") or ""
    if status == "ok":
        last_ok = entry.get("lastOkAt") or observed
        return f"登录态正常（最近确认 {last_ok}）"
    if status == "required":
        return f"上次抓取要求登录（{observed}），登录态可能已失效，请重新扫码"
    if status == "risk":
        return f"上次抓取触发风控（{observed}）：{entry.get('detail') or '需人工验证'}，请稍后再试"
    return f"登录态未知（{observed}）"


def detect_login_state_in_text(text: str) -> str:
    """从页面文本里判断登录态。返回 ``ok`` / ``required`` / ``risk``。"""
    if not text:
        return "ok"
    for marker in RISK_MARKERS:
        if marker in text:
            return "risk"
    for marker in LOGIN_WALL_MARKERS:
        if marker in text:
            return "required"
    return "ok"


# ── 运行前自检 ──────────────────────────────────────────────────────────────


def run_preflight(
    *,
    headless: bool,
    profile_dir: Optional[str],
    browser_path: Optional[str] = None,
    requires_browser: bool = True,
) -> PreflightReport:
    """运行前自检：浏览器、profile 占用、依赖、登录态记录。

    每一项都给出「问题 + 建议」，避免用户面对底层异常。
    """
    report = PreflightReport()

    # 1. 依赖
    missing = _missing_modules()
    if missing:
        report.add(
            "blocker",
            "missing_dependency",
            f"缺少爬虫依赖：{', '.join(missing)}",
            "在爬虫目录执行 pip install -r requirements.txt",
        )
    report.info["missingModules"] = missing

    # 2. 浏览器
    if requires_browser:
        from core.browser_manager import find_browser_path

        resolved = find_browser_path(browser_path)
        report.info["browserPath"] = resolved or ""
        if not resolved:
            report.add(
                "blocker",
                "no_browser",
                "未找到 Chromium 内核浏览器（Chrome/Edge）",
                "安装 Chrome 或 Edge，或设置环境变量 JINGXU_BROWSER_PATH 指向浏览器可执行文件",
            )

    # 3. profile 独占锁：两个实例抢同一目录会直接崩（实测 0xc0000142）
    if profile_dir:
        report.info["profileDir"] = os.path.abspath(profile_dir)
        locked = _profile_locked(profile_dir)
        report.info["profileLocked"] = locked
        if locked:
            report.add(
                "blocker",
                "profile_locked",
                "浏览器档案正被另一个浏览器占用",
                "请先关闭登录窗口或另一个正在抓取的窗口后再试（同一档案不能同时被两个实例使用）",
            )

    # 4. 无头模式与登录态的矛盾
    if headless:
        report.add(
            "warning",
            "headless_login",
            "无头模式无法扫码登录",
            "首次使用请先关闭无头模式完成扫码；登录态保存后再用无头模式",
        )

    # 5. 登录态记录
    for platform in LOGIN_URLS:
        report.info[f"loginState.{platform}"] = describe_login_state(platform, profile_dir)

    return report


def _missing_modules() -> list[str]:
    import importlib.util

    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def _profile_locked(profile_dir: str) -> bool:
    """档案目录是否已被占用（Chromium 的独占锁）。"""
    if not os.path.isdir(profile_dir):
        return False
    for name in ("SingletonLock", "lockfile"):
        if os.path.exists(os.path.join(profile_dir, name)):
            return True
    lock = os.path.join(profile_dir, "Default", "LOCK")
    if not os.path.isfile(lock):
        return False
    try:
        with open(lock, "a+b"):
            return False
    except OSError:
        return True


# ── 运行后诊断 ──────────────────────────────────────────────────────────────


def run_diagnosis(
    *,
    videos_scanned: int,
    items_found: int,
    retained: int,
    diagnostics: Optional[dict] = None,
    login_states: Optional[Iterable[str]] = None,
    stopped_by_user: bool = False,
) -> list[Issue]:
    """运行后诊断：把结果翻译成「为什么没抓到」。"""
    issues: list[Issue] = []
    diagnostics = diagnostics or {}

    if stopped_by_user:
        issues.append(
            Issue("warning", "stopped", "抓取被用户取消", "可重新运行，已获取的部分结果仍然有效")
        )

    login_list = [state for state in (login_states or []) if state]
    if "risk" in login_list:
        issues.append(
            Issue(
                "warning",
                "risk_control",
                "抓取过程中出现验证码/风控提示",
                "请在弹出的浏览器里手动完成验证，并降低抓取频率（减少账号数或调小翻页上限）",
            )
        )
    elif "required" in login_list:
        issues.append(
            Issue(
                "blocker",
                "login_required",
                "抓取过程中站点要求登录，登录态可能已失效",
                "请重新扫码登录后再试（登录态已记录，可在界面看到状态）",
            )
        )

    if videos_scanned == 0:
        issues.append(
            Issue(
                "blocker",
                "no_videos",
                "没有读取到任何视频",
                "确认账号链接可用、时间范围内确有视频；若一直如此，可能是平台改版或需要登录",
            )
        )
        return issues

    if items_found == 0:
        scanned = int(diagnostics.get("scannedNodes", 0) or 0)
        candidates = int(diagnostics.get("scanCandidates", 0) or 0)
        note = (
            f"已扫描 {videos_scanned} 个视频，但一个带货商品都没提取到"
            f"（扫描 {scanned} 个数据节点、{candidates} 个候选）"
        )
        if candidates == 0:
            suggestion = (
                "这些视频很可能确实没有挂商品（小黄车）。"
                "建议换有带货的账号，或把时间范围放宽后重试"
            )
        else:
            suggestion = (
                "存在候选节点但取不出有效商品名，平台字段结构可能已变化；"
                "请把运行日志中的 [未提取到商品] 行提供给开发者"
            )
        issues.append(Issue("blocker", "no_products", note, suggestion))
        return issues

    if retained == 0:
        issues.append(
            Issue(
                "warning",
                "no_retained",
                f"提取到 {items_found} 条商品记录，但没有任何商品满足「保留相同项」门槛",
                "同一商品需要在多个对标账号出现才会保留；"
                "可增加对标账号数量，或把「跨账号数」门槛调到 1 先验证链路",
            )
        )

    return issues


def build_diagnostics_payload(
    *,
    preflight: Optional[PreflightReport],
    login_states: dict,
    extraction_summary: dict,
    issues: list[Issue],
) -> dict:
    """汇总成写入 ``--json-out`` 的 diagnostics 段。"""
    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "preflight": preflight.to_dict() if preflight else {},
        "loginState": login_states,
        "extraction": extraction_summary,
        "issues": [item.to_dict() for item in issues],
        "blocked": any(item.level == "blocker" for item in issues),
    }


def format_issues(issues: list[Issue]) -> str:
    """把问题列表格式化成多行文本，供控制台输出。"""
    if not issues:
        return ""
    return "\n".join(item.line() for item in issues)


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
