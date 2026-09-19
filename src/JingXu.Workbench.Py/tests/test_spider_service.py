"""选品爬虫服务：平台识别、账号解析、配置持久化、CLI 参数与结果解析。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jingxu.infrastructure import spider as spider_service
from jingxu.infrastructure.spider import (
    SpiderAccount,
    SpiderConfig,
    SpiderConfigStore,
    SpiderFilters,
    SpiderRunResult,
    build_arguments,
    detect_platform,
    parse_accounts_text,
    parse_result_payload,
)


# ── 平台识别 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.douyin.com/user/MS4wLjABAAAAxyz", "douyin"),
        ("https://v.douyin.com/abcdEF/", "douyin"),
        ("MS4wLjABAAAAxyz", "douyin"),
        ("https://www.kuaishou.com/profile/3x6df89v345", "kuaishou"),
        ("https://v.kuaishou.com/abcdEF/", "kuaishou"),
        ("https://www.kwai.com/profile/abc", "kuaishou"),
        ("3x6df89v345", "douyin"),  # 无法判断时回落抖音
    ],
)
def test_detect_platform(raw: str, expected: str) -> None:
    assert detect_platform(raw) == expected


def test_detect_platform_does_not_misclassify_kuaishou() -> None:
    """快手链接曾被抖音兜底分支误判，这里作为回归防线。"""
    assert detect_platform("https://www.kuaishou.com/profile/xyz") == "kuaishou"


# ── 账号批量解析 ────────────────────────────────────────────────────────────


def test_parse_accounts_text_reads_named_and_plain_lines() -> None:
    accounts = parse_accounts_text(
        "达人A=https://www.douyin.com/user/abc\nhttps://www.kuaishou.com/profile/xyz"
    )
    assert len(accounts) == 2
    assert accounts[0].name == "达人A"
    assert accounts[0].platform == "douyin"
    assert accounts[1].name == ""
    assert accounts[1].platform == "kuaishou"


def test_parse_accounts_text_supports_semicolon_and_tab() -> None:
    accounts = parse_accounts_text("达人A=abc;达人B=def")
    assert [account.name for account in accounts] == ["达人A", "达人B"]

    tabbed = parse_accounts_text("达人C\thttps://www.douyin.com/user/ghi")
    assert tabbed[0].name == "达人C"
    assert tabbed[0].url_or_id == "https://www.douyin.com/user/ghi"


def test_parse_accounts_text_keeps_numeric_ids_intact() -> None:
    """纯数字 ID 不得被当成序号表达式拆开。"""
    accounts = parse_accounts_text("123456789")
    assert len(accounts) == 1
    assert accounts[0].url_or_id == "123456789"


def test_parse_accounts_text_ignores_blank_lines() -> None:
    assert parse_accounts_text("\n\n  \n") == []


# ── 配置模型与持久化 ────────────────────────────────────────────────────────


def test_config_from_empty_payload_uses_defaults() -> None:
    config = SpiderConfig.from_dict({})
    assert config.accounts == ()
    assert config.filters.time_mode == "days"
    assert config.filters.days == 7
    assert config.filters.min_accounts == 2
    assert config.filters.filter_by == "accounts"


def test_config_from_dict_tolerates_bad_values() -> None:
    config = SpiderConfig.from_dict(
        {
            "accounts": [{"url_or_id": "abc"}, {"platform": "kuaishou"}, "not-a-dict"],
            "filters": {
                "timeMode": "bogus",
                "days": -5,
                "minAccounts": "x",
                "fuzzyThreshold": 9.9,
                "filterBy": "nope",
            },
        }
    )
    # 缺 url_or_id 的账号被丢弃，非字典条目被忽略。
    assert len(config.accounts) == 1
    # 非法枚举回落默认；数值越界钳到允许下界（-5 天 → 1 天），非数字才回落默认。
    assert config.filters.time_mode == "days"
    assert config.filters.days == 1
    assert config.filters.min_accounts == 2
    assert config.filters.fuzzy_threshold == 1.0
    assert config.filters.filter_by == "accounts"


def test_config_enabled_accounts_filters_disabled_and_empty() -> None:
    config = SpiderConfig(
        accounts=(
            SpiderAccount(platform="douyin", url_or_id="a", enabled=True),
            SpiderAccount(platform="douyin", url_or_id="b", enabled=False),
            SpiderAccount(platform="douyin", url_or_id="", enabled=True),
        )
    )
    assert [account.url_or_id for account in config.enabled_accounts] == ["a"]


def test_config_store_roundtrip(tmp_path: Path) -> None:
    store = SpiderConfigStore(tmp_path / "Spider" / "config.json")
    config = SpiderConfig(
        accounts=(SpiderAccount(platform="kuaishou", url_or_id="xyz", name="老铁"),),
        filters=SpiderFilters(time_mode="range", start_date="2026-01-01", end_date="2026-02-01"),
    )
    store.save(config)
    restored = store.load()

    assert restored.accounts == config.accounts
    assert restored.filters.time_mode == "range"
    assert restored.filters.start_date == "2026-01-01"


def test_config_store_returns_defaults_for_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert SpiderConfigStore(path).load().accounts == ()


def test_config_store_returns_defaults_when_missing(tmp_path: Path) -> None:
    assert SpiderConfigStore(tmp_path / "absent.json").load().accounts == ()


# ── CLI 参数 ────────────────────────────────────────────────────────────────


def _arguments(filters: SpiderFilters) -> list[str]:
    return build_arguments(
        SpiderConfig(filters=filters),
        cli_path=Path("cli.py"),
        profile_dir=Path("profile"),
        export_dir=Path("exports"),
        json_out=Path("result.json"),
    )


def test_build_arguments_includes_core_flags() -> None:
    args = _arguments(SpiderFilters())
    assert args[0] == "cli.py"
    for flag in ("--json-out", "--profile-dir", "--export-dir", "--time-mode", "--min-accounts",
                 "--min-occurrences", "--filter-by", "--fuzzy-threshold", "--max-scrolls"):
        assert flag in args


def test_build_arguments_days_mode() -> None:
    args = _arguments(SpiderFilters(time_mode="days", days=3))
    assert args[args.index("--days") + 1] == "3"
    assert "--start-date" not in args


def test_build_arguments_range_mode_uses_dates() -> None:
    args = _arguments(
        SpiderFilters(time_mode="range", start_date="2026-01-01", end_date="2026-02-01")
    )
    assert args[args.index("--start-date") + 1] == "2026-01-01"
    assert args[args.index("--end-date") + 1] == "2026-02-01"
    assert "--days" not in args


def test_build_arguments_all_mode_has_no_range_flags() -> None:
    args = _arguments(SpiderFilters(time_mode="all"))
    assert "--days" not in args
    assert "--start-date" not in args


def test_build_arguments_headless_flag_only_when_enabled() -> None:
    assert "--headless" not in _arguments(SpiderFilters(headless=False))
    assert "--headless" in _arguments(SpiderFilters(headless=True))


def test_build_arguments_includes_config_when_given() -> None:
    args = build_arguments(
        SpiderConfig(),
        cli_path=Path("cli.py"),
        profile_dir=Path("p"),
        export_dir=Path("e"),
        json_out=Path("r.json"),
        config_file=Path("cfg.json"),
    )
    assert args[args.index("--config") + 1] == "cfg.json"


# ── 结果解析 ────────────────────────────────────────────────────────────────


def test_parse_result_payload_reads_counts_and_urls() -> None:
    payload = {
        "retained_products": [
            {"name": "生姜洗发水", "account_count": 3, "items": [{"video_url": "https://v/1"}]}
        ],
        "all_items": [
            {"video_url": "https://v/2"},
            {"videoUrl": "https://v/3"},
            {"video_url": "https://v/1"},
        ],
        "excel_path": "out.xlsx",
    }
    result = parse_result_payload(payload)

    assert result.success is True
    assert len(result.retained) == 1
    assert len(result.items) == 3
    assert result.excel_path == "out.xlsx"
    # 去重且保序：保留商品优先；条目内部是「嵌套 items 在前、自身链接在后」。
    assert result.video_urls == ("https://v/1", "https://v/2", "https://v/3")
    assert result.product_names == ("生姜洗发水",)


def test_parse_result_payload_handles_camel_case_keys() -> None:
    result = parse_result_payload(
        {"retainedProducts": [{"name": "A"}], "allItems": [{"videoUrl": "https://v/9"}]}
    )
    assert len(result.retained) == 1
    assert result.video_urls == ("https://v/9",)


def test_parse_result_payload_rejects_non_dict() -> None:
    assert parse_result_payload([]).success is False  # type: ignore[arg-type]


def test_run_result_without_urls_has_empty_tuple() -> None:
    result = SpiderRunResult(success=True, message="ok", retained=({"name": "A"},))
    assert result.video_urls == ()


# ── 环境检测 ────────────────────────────────────────────────────────────────


def test_check_environment_reports_missing_directory(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("JINGXU_SPIDER_DIR", "/definitely/not/here")
    monkeypatch.setattr(spider_service, "search_roots", lambda: [])
    environment = spider_service.check_environment()
    assert environment.available is False
    assert "未找到选品爬虫" in environment.message


def test_spider_directory_prefers_env_override(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "spider"
    directory.mkdir()
    (directory / "cli.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("JINGXU_SPIDER_DIR", str(directory))
    monkeypatch.setattr(spider_service, "search_roots", lambda: [])
    assert spider_service.spider_directory() == directory


def test_spider_python_prefers_bundled_runtime(tmp_path: Path, monkeypatch) -> None:
    bundled = tmp_path / "runtime" / "python" / "python.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"stub")
    monkeypatch.delenv("JINGXU_SPIDER_PYTHON", raising=False)
    monkeypatch.setattr(spider_service, "search_roots", lambda: [tmp_path])
    assert Path(str(spider_service.spider_python())) == bundled


def test_spider_python_respects_env_override(tmp_path: Path, monkeypatch) -> None:
    custom = tmp_path / "custom.exe"
    custom.write_bytes(b"stub")
    monkeypatch.setenv("JINGXU_SPIDER_PYTHON", str(custom))
    assert Path(str(spider_service.spider_python())) == custom


# ── 运行器 ──────────────────────────────────────────────────────────────────


class _FakeProcess:
    """假爬虫进程：输出若干行后写出结果 JSON。"""

    def __init__(self, lines: list[str], payload: dict | None, *, code: int = 0) -> None:
        self._lines = lines
        self._payload = payload
        self._code = code
        self.stdout = iter([f"{line}\n" for line in lines])
        self._json_out = Path()

    def bind(self, json_out: Path) -> None:
        self._json_out = json_out

    def wait(self, timeout: float | None = None) -> int:
        if self._payload is not None:
            self._json_out.write_text(json.dumps(self._payload), encoding="utf-8")
        return self._code

    def poll(self) -> int:
        return self._code

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


def _patch_run(monkeypatch, process: _FakeProcess) -> None:  # noqa: ANN001
    """让 SpiderRunner 使用假进程，并跳过环境检测。"""
    monkeypatch.setattr(
        spider_service,
        "check_environment",
        lambda **_: spider_service.SpiderEnvironment(
            available=True, message="ok", directory=Path.cwd(), python="python"
        ),
    )

    def fake_popen(arguments, **kwargs):  # noqa: ANN001
        json_index = arguments.index("--json-out")
        process.bind(Path(arguments[json_index + 1]))
        return process

    monkeypatch.setattr(spider_service.subprocess, "Popen", fake_popen)


def test_runner_returns_failure_without_accounts(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        spider_service,
        "check_environment",
        lambda **_: spider_service.SpiderEnvironment(
            available=True, message="ok", directory=Path.cwd(), python="python"
        ),
    )
    result = spider_service.SpiderRunner().run(SpiderConfig())
    assert result.success is False
    assert "至少一个对标账号" in result.message


def test_runner_parses_successful_result(monkeypatch) -> None:  # noqa: ANN001
    process = _FakeProcess(["[*] 开始"], {"retained_products": [{"name": "A"}], "all_items": []})
    _patch_run(monkeypatch, process)
    logs: list[str] = []

    result = spider_service.SpiderRunner().run(
        SpiderConfig(accounts=(SpiderAccount(platform="douyin", url_or_id="a"),)),
        on_log=logs.append,
    )

    assert result.success is True
    assert result.retained[0]["name"] == "A"
    assert logs == ["[*] 开始"]


def test_runner_reports_nonzero_exit(monkeypatch) -> None:  # noqa: ANN001
    process = _FakeProcess(["Traceback", "ImportError: DrissionPage"], None, code=1)
    _patch_run(monkeypatch, process)

    result = spider_service.SpiderRunner().run(
        SpiderConfig(accounts=(SpiderAccount(platform="douyin", url_or_id="a"),))
    )

    assert result.success is False
    assert "ImportError" in result.message


def test_runner_reports_missing_result_file(monkeypatch) -> None:  # noqa: ANN001
    process = _FakeProcess(["[*] done"], None, code=0)
    _patch_run(monkeypatch, process)

    result = spider_service.SpiderRunner().run(
        SpiderConfig(accounts=(SpiderAccount(platform="douyin", url_or_id="a"),))
    )

    assert result.success is False
    assert "未生成结果文件" in result.message


def test_runner_honours_cancel_event(monkeypatch) -> None:  # noqa: ANN001
    import threading

    process = _FakeProcess(["line1", "line2"], None, code=0)
    _patch_run(monkeypatch, process)
    cancel = threading.Event()

    def on_log(line: str) -> None:
        cancel.set()  # 收到第一行就取消

    result = spider_service.SpiderRunner().run(
        SpiderConfig(accounts=(SpiderAccount(platform="douyin", url_or_id="a"),)),
        on_log=on_log,
        cancel_event=cancel,
    )

    assert result.success is False
    assert "取消" in result.message
