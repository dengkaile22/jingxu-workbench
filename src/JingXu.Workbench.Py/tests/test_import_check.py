"""运行期依赖导入检查（``--import-check``）的回归测试。

为什么需要
----------
扫码登录由应用**进程内**执行 ``from core.browser_manager import BrowserManager``，
而它 ``import DrissionPage``。这类运行期动态导入 PyInstaller 静态分析看不到，
缺收集时只在用户点「抖音登录」那一刻才以 ``No module named 'DrissionPage'``
暴露——而源码运行完全正常，所以问题只在装机版出现。

``--import-check`` 把这条链路变成一条构建期可执行的命令；
本文件保证它自己的判定逻辑不会退化（例如异常被吞掉、结论恒为成功）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jingxu.__main__ import _import_check_report  # noqa: E402
from jingxu.infrastructure import spider as spider_service  # noqa: E402


def test_report_covers_every_login_prerequisite() -> None:
    """报告必须逐项覆盖登录链路：爬虫目录、依赖、浏览器、爬虫组件。"""
    report, code = _import_check_report()

    names = {check["name"] for check in report["checks"]}
    assert any("爬虫源码目录" in name for name in names)
    assert any("DrissionPage" in name for name in names)
    assert any("浏览器" in name for name in names)
    assert any("爬虫浏览器组件" in name for name in names)
    assert code in (0, 1)


def test_report_is_json_serialisable() -> None:
    report, _ = _import_check_report()
    payload = json.dumps(report, ensure_ascii=False)
    assert "schemaVersion" in payload
    assert json.loads(payload)["schemaVersion"] == 1


def test_success_matches_all_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """``success`` 必须等于「所有检查项都可用」，不能恒真。"""
    report, code = _import_check_report()
    expected = all(bool(item["available"]) for item in report["checks"])
    assert report["success"] is expected
    assert code == (0 if expected else 1)


def test_missing_dependency_makes_report_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺 DrissionPage 时必须如实报失败并给出缺哪个——这正是装机版的真实故障。"""
    monkeypatch.setattr(spider_service, "_missing_login_modules", lambda: ("DrissionPage",))

    report, code = _import_check_report()

    assert report["success"] is False
    assert code == 1
    entry = next(item for item in report["checks"] if "DrissionPage" in str(item["name"]))
    assert entry["available"] is False
    assert "DrissionPage" in str(entry["detail"])


def test_missing_spider_directory_makes_report_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spider_service, "spider_directory", lambda: None)

    report, code = _import_check_report()

    assert report["success"] is False
    assert code == 1


def test_missing_browser_makes_report_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spider_service, "find_browser", lambda: None)

    report, code = _import_check_report()

    assert report["success"] is False
    assert code == 1


def test_broken_component_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """组件导入失败要变成报告里的一项，而不是让命令崩掉。"""
    monkeypatch.setattr(
        spider_service, "_missing_login_modules", lambda: ()
    )
    import importlib

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "core.browser_manager":
            raise ImportError("No module named 'DrissionPage'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    report, code = _import_check_report()

    assert code == 1
    entry = next(item for item in report["checks"] if "爬虫浏览器组件" in str(item["name"]))
    assert entry["available"] is False
    assert "DrissionPage" in str(entry["detail"])


def test_argparse_accepts_import_check() -> None:
    """命令行必须真的认得这个开关（构建脚本按它调用）。"""
    from jingxu.__main__ import _parse_args

    args = _parse_args(["--import-check", "--report-file", "out.json"])
    assert args.import_check is True
    assert args.report_file == "out.json"
