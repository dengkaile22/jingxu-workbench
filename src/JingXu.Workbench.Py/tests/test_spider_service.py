"""选品爬虫服务：平台识别、账号解析、配置持久化、CLI 参数与结果解析。"""

from __future__ import annotations

import json
import time
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
    summarise_failure,
    validate_date_filters,
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


# ── 分享文案解析（用户实际粘贴的就是这种整段文字）────────────────────────────


def test_parse_accounts_text_extracts_link_from_douyin_share_text() -> None:
    """此前会把整段分享文案当成账号链接存进账号表，爬虫无法处理。"""
    share = (
        "0- 长按复制此条消息，打开抖音搜索，查看TA的更多作品。 "
        "https://v.douyin.com/iTXqs_ymHlg/ 8@0.com :2pm"
    )
    accounts = parse_accounts_text(share)

    assert len(accounts) == 1
    assert accounts[0].url_or_id == "https://v.douyin.com/iTXqs_ymHlg/"
    assert accounts[0].platform == "douyin"
    # 抖音话术里没有昵称，展示名回落到链接尾段而不是整段文案
    assert accounts[0].display_name == "iTXqs_ymHlg"


def test_parse_accounts_text_reads_nickname_from_kuaishou_share_text() -> None:
    share = (
        "https://v.kuaishou.com/KoL53UgI 看了这么多快手，还是「牛奶巧巧」最好玩了！ "
        "复制此消息，打开【快手】直接观看！"
    )
    accounts = parse_accounts_text(share)

    assert len(accounts) == 1
    assert accounts[0].url_or_id == "https://v.kuaishou.com/KoL53UgI"
    assert accounts[0].platform == "kuaishou"
    assert accounts[0].name == "牛奶巧巧"


def test_parse_accounts_text_extracts_nickname_from_square_brackets() -> None:
    accounts = parse_accounts_text("https://v.kuaishou.com/abc 【老铁严选】最好玩！")
    assert accounts[0].name == "老铁严选"


def test_share_nickname_never_returns_a_link() -> None:
    """「」里若是链接片段不能当昵称（抖音文案的括号里含网址）。"""
    from jingxu.infrastructure.spider import extract_share_nickname

    assert extract_share_nickname("看「https://v.douyin.com/abc/」") == ""
    assert extract_share_nickname("看「牛奶巧巧」") == "牛奶巧巧"


def test_share_link_strips_leading_index() -> None:
    from jingxu.infrastructure.spider import extract_share_link

    assert extract_share_link("2- https://v.douyin.com/x/ 5@4.com :1pm") == "https://v.douyin.com/x/"


def test_share_link_returns_bare_id_when_no_url() -> None:
    from jingxu.infrastructure.spider import extract_share_link

    assert extract_share_link("3- MS4wLjABAAAAxyz") == "MS4wLjABAAAAxyz"


def test_display_name_truncates_long_ids() -> None:
    account = SpiderAccount(platform="douyin", url_or_id="M" * 40)
    assert account.display_name.endswith("…")
    assert len(account.display_name) <= 17


def test_display_name_prefers_explicit_name() -> None:
    account = SpiderAccount(platform="douyin", url_or_id="https://v.douyin.com/x/", name="达人A")
    assert account.display_name == "达人A"


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


# ── 结果落盘（抓取耗时以分钟计，关掉应用不该丢）────────────────────────────


def _sample_result(**overrides) -> SpiderRunResult:  # noqa: ANN003
    payload = {
        "success": True,
        "message": "抓取完成：保留 1 款商品",
        "retained": ({"name": "生姜洗发水", "account_count": 3, "video_url": "https://v/a"},),
        "items": ({"video_url": "https://v/b"},),
        "excel_path": "C:/exports/report.xlsx",
        "finished_at": "2026-09-19T22:50:00",
    }
    payload.update(overrides)
    return SpiderRunResult(**payload)


def test_result_store_roundtrip(tmp_path: Path) -> None:
    store = SpiderConfigStore(tmp_path / "config.json")
    store.save_result(_sample_result())

    restored = store.load_result()
    assert restored is not None
    assert restored.retained[0]["name"] == "生姜洗发水"
    assert restored.excel_path == "C:/exports/report.xlsx"
    assert restored.finished_at == "2026-09-19T22:50:00"


def test_result_store_writes_next_to_config(tmp_path: Path) -> None:
    """结果文件与配置同目录，便于一起备份/清理。"""
    store = SpiderConfigStore(tmp_path / "Spider" / "config.json")
    assert store.results_path == tmp_path / "Spider" / "last_result.json"


def test_result_store_skips_empty_failures(tmp_path: Path) -> None:
    """无内容的失败不应覆盖已有结果（否则一次网络抖动就清空上次成果）。"""
    store = SpiderConfigStore(tmp_path / "config.json")
    store.save_result(_sample_result())
    store.save_result(SpiderRunResult(success=False, message="抓取失败：超时"))

    restored = store.load_result()
    assert restored is not None
    assert restored.retained[0]["name"] == "生姜洗发水"


def test_result_store_returns_none_when_missing(tmp_path: Path) -> None:
    assert SpiderConfigStore(tmp_path / "config.json").load_result() is None


def test_result_store_returns_none_for_broken_json(tmp_path: Path) -> None:
    store = SpiderConfigStore(tmp_path / "config.json")
    store.results_path.write_text("{not json", encoding="utf-8")
    assert store.load_result() is None


def test_result_display_time_is_compact() -> None:
    assert _sample_result().finished_at_display == "09-19 22:50"


def test_result_display_time_tolerates_garbage() -> None:
    assert _sample_result(finished_at="不是时间").finished_at_display == "不是时间"
    assert _sample_result(finished_at="").finished_at_display == ""


# ── 可下载条目与选中提取 ────────────────────────────────────────────────────


def test_effective_entries_prefers_retained() -> None:
    """有保留商品时只展示它们（那才是用户要下载的）。"""
    result = _sample_result()
    entries = result.effective_entries
    assert len(entries) == 1
    assert entries[0][0] is True
    assert entries[0][1]["name"] == "生姜洗发水"


def test_effective_entries_falls_back_to_items() -> None:
    """没有保留商品时回落到全部带货记录，避免「抓到了但表格是空的」。"""
    result = _sample_result(retained=())
    entries = result.effective_entries
    assert len(entries) == 1
    assert entries[0][0] is False
    assert entries[0][1]["video_url"] == "https://v/b"


def test_urls_for_entries_only_returns_selected() -> None:
    """只送勾选商品——此前是强制全发。"""
    result = SpiderRunResult(
        success=True,
        message="ok",
        retained=(
            {"name": "A", "video_url": "https://v/a"},
            {"name": "B", "video_url": "https://v/b"},
            {"name": "C", "video_url": "https://v/c"},
        ),
    )
    assert result.urls_for_entries([result.retained[1]]) == ("https://v/b",)
    assert result.urls_for_entries(list(result.retained)) == (
        "https://v/a",
        "https://v/b",
        "https://v/c",
    )
    assert result.urls_for_entries([]) == ()


def test_urls_for_entries_dedupes_across_entries() -> None:
    result = SpiderRunResult(
        success=True,
        message="ok",
        retained=({"video_url": "https://same"}, {"video_url": "https://same"}),
    )
    assert result.urls_for_entries(list(result.retained)) == ("https://same",)


# ── 失败留档与预检诊断透出 ──────────────────────────────────────────────────


def test_archive_failure_output_writes_log(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """失败信息会被翻译成中文，但原始输出必须留档，否则无法排查。"""
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
    lines = [f"line {index}" for index in range(500)]

    path = spider_service.archive_failure_output(lines, exit_code=1)

    assert path is not None and path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "退出码：1" in text
    assert "输出行数：500" in text
    # 只保留尾部，避免日志文件过大
    assert "line 499" in text
    assert "\nline 0\n" not in text


def test_archive_failure_output_returns_none_for_empty() -> None:
    assert spider_service.archive_failure_output([], exit_code=1) is None


def test_read_diagnostics_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert spider_service._read_diagnostics(tmp_path / "absent.json") is None


def test_read_diagnostics_returns_none_for_broken_json(tmp_path: Path) -> None:
    target = tmp_path / "broken.json"
    target.write_text("{not json", encoding="utf-8")
    assert spider_service._read_diagnostics(target) is None


def test_read_diagnostics_parses_preflight_payload(tmp_path: Path) -> None:
    """爬虫预检失败时（退出码 2）诊断只存在于结果文件里。"""
    target = tmp_path / "result.json"
    target.write_text(
        json.dumps(
            {
                "retained_products": [],
                "all_items": [],
                "diagnostics": {
                    "blocked": True,
                    "issues": [
                        {
                            "level": "blocker",
                            "code": "profile_locked",
                            "message": "浏览器档案正被另一个浏览器占用",
                            "suggestion": "请先关闭登录窗口",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    view = spider_service._read_diagnostics(target)

    assert view is not None
    assert view.blocked is True
    assert "浏览器档案" in view.blocking_message


def test_failed_run_still_surfaces_diagnostics(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """非零退出也要读诊断：否则界面只能看到一句「抓取失败」。"""
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
    payload = {
        "retained_products": [],
        "all_items": [],
        "diagnostics": {
            "blocked": True,
            "issues": [
                {
                    "level": "blocker",
                    "code": "no_browser",
                    "message": "未找到 Chromium 内核浏览器（Chrome/Edge）",
                    "suggestion": "安装 Chrome 或 Edge",
                }
            ],
        },
    }

    class _FailingProcess:
        def __init__(self, json_out: Path) -> None:
            self._json_out = json_out
            self.stdout = iter(["[*] 运行前自检\n", "✗ [no_browser] 未找到浏览器\n"])
            self.returncode = 2
            self.args = ["python", "cli.py"]

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *exc):  # noqa: ANN002, ANN204
            return False

        def wait(self, timeout=None):  # noqa: ANN001
            self._json_out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return 2

        def poll(self):  # noqa: ANN201
            return 2

        def kill(self) -> None:
            pass

        def terminate(self) -> None:
            pass

    monkeypatch.setattr(
        spider_service,
        "check_environment",
        lambda **_: spider_service.SpiderEnvironment(
            available=True, message="ok", directory=Path.cwd(), python="python"
        ),
    )

    def fake_popen(arguments, **kwargs):  # noqa: ANN001
        index = arguments.index("--json-out")
        return _FailingProcess(Path(arguments[index + 1]))

    monkeypatch.setattr(spider_service.subprocess, "Popen", fake_popen)

    result = spider_service.SpiderRunner().run(
        SpiderConfig(accounts=(SpiderAccount(platform="douyin", url_or_id="a"),))
    )

    assert result.success is False
    assert result.diagnostics is not None
    assert result.diagnostics.blocked is True
    assert "未找到 Chromium" in result.diagnostics.blocking_message
    # 原始输出也要留档并告知用户
    assert "完整输出已留档" in result.message


# ── 不得往安装目录写字节码 ──────────────────────────────────────────────────


def test_every_bundled_python_launch_disables_bytecode() -> None:
    """扫描 spider 模块内所有启动随包解释器的地方，必须带 -B。

    实测教训：先只给 SpiderRunner 加了 -B，但 check_environment 的启动探测同样会
    调用随包解释器，于是**应用一启动**就在安装目录写出 __pycache__，导致文件数
    与 MSI 清单不一致（且卸载不清理这类「安装后新增」文件）。
    这类遗漏用静态扫描守住，比逐个记着更可靠。
    """
    import ast

    source = Path(spider_service.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            continue
        if func.value.id != "subprocess" or func.attr not in {"run", "Popen"}:
            continue
        # 只关心启动随包 python 的调用：命令列表里以 python 解释器变量开头
        if not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List) or not first.elts:
            continue
        head = first.elts[0]
        launches_python = (
            isinstance(head, ast.Attribute) and head.attr == "python"
        ) or (isinstance(head, ast.Name) and "python" in head.id)
        if not launches_python:
            continue
        literals = [
            element.value
            for element in first.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if "-B" not in literals:
            offenders.append(node.lineno)

    assert offenders == [], f"以下调用未加 -B，会往安装目录写字节码：行 {offenders}"


def test_spider_python_launch_sets_dont_write_bytecode_env(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """环境变量也要设：-B 是命令行保险，两者互为补充（用户 shell 可能覆盖环境变量）。"""
    captured: dict[str, str] = {}

    class _Process:
        stdout = iter([])

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *exc):  # noqa: ANN002, ANN204
            return False

        def wait(self, timeout=None):  # noqa: ANN001
            return 1

        def poll(self):  # noqa: ANN201
            return 1

        def kill(self) -> None:
            pass

        def terminate(self) -> None:
            pass

    monkeypatch.setattr(
        spider_service,
        "check_environment",
        lambda **_: spider_service.SpiderEnvironment(
            available=True, message="ok", directory=Path.cwd(), python="python"
        ),
    )

    def fake_popen(arguments, **kwargs):  # noqa: ANN001
        captured.update(kwargs.get("env") or {})
        return _Process()

    monkeypatch.setattr(spider_service.subprocess, "Popen", fake_popen)

    spider_service.SpiderRunner().run(
        SpiderConfig(accounts=(SpiderAccount(platform="douyin", url_or_id="a"),))
    )

    assert captured.get("PYTHONDONTWRITEBYTECODE") == "1"


# ── 日期范围校验 ────────────────────────────────────────────────────────────


def test_validate_date_filters_ignores_non_range_modes() -> None:
    assert validate_date_filters(SpiderFilters(time_mode="days", start_date="乱写")) == ""
    assert validate_date_filters(SpiderFilters(time_mode="all", end_date="乱写")) == ""


def test_validate_date_filters_allows_empty_range() -> None:
    assert validate_date_filters(SpiderFilters(time_mode="range")) == ""


def test_validate_date_filters_rejects_bad_format() -> None:
    message = validate_date_filters(SpiderFilters(time_mode="range", start_date="2026/01/01"))
    assert "YYYY-MM-DD" in message
    assert "2026/01/01" in message


def test_validate_date_filters_rejects_reversed_range() -> None:
    message = validate_date_filters(
        SpiderFilters(time_mode="range", start_date="2026-05-01", end_date="2026-01-01")
    )
    assert "不能晚于" in message


def test_validate_date_filters_accepts_valid_range() -> None:
    assert (
        validate_date_filters(
            SpiderFilters(time_mode="range", start_date="2026-01-01", end_date="2026-05-01")
        )
        == ""
    )


def test_runner_rejects_bad_date_before_launching(monkeypatch) -> None:  # noqa: ANN001
    """格式错误应在启动浏览器之前拦下，而不是抓取中途才报晦涩错误。"""
    launched: list[object] = []
    monkeypatch.setattr(
        spider_service,
        "check_environment",
        lambda **_: spider_service.SpiderEnvironment(
            available=True, message="ok", directory=Path.cwd(), python="python"
        ),
    )
    monkeypatch.setattr(spider_service.subprocess, "Popen", lambda *a, **k: launched.append(a))

    result = spider_service.SpiderRunner().run(
        SpiderConfig(
            accounts=(SpiderAccount(platform="douyin", url_or_id="a"),),
            filters=SpiderFilters(time_mode="range", start_date="01-01-2026"),
        )
    )

    assert result.success is False
    assert "YYYY-MM-DD" in result.message
    assert launched == []


# ── 目录约定 ────────────────────────────────────────────────────────────────


def test_exports_and_profile_directories_are_under_data_dir(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
    assert spider_service.exports_directory() == tmp_path / "Spider" / "exports"
    assert spider_service.profile_directory() == tmp_path / "Spider" / "browser_profile"
    assert spider_service.results_path() == tmp_path / "Spider" / "last_result.json"


# ── 失败摘要（曾把版本横幅当成错误原因）────────────────────────────────────


def test_summarise_failure_skips_version_banner() -> None:
    """实测踩过：最后一行是「版本: 4.1.1.4」，被当成失败原因展示给用户。"""
    lines = ["版本: 4.1.1.4", "正在启动浏览器...", "浏览器启动失败：未找到可用的 Chromium 内核"]
    assert summarise_failure(lines, exit_code=1) == "浏览器启动失败：未找到可用的 Chromium 内核"


def test_summarise_failure_prefers_error_keyword_line() -> None:
    lines = ["版本: 1.0", "Traceback (most recent call last):", "ImportError: no module named x"]
    assert summarise_failure(lines, exit_code=1) == "ImportError: no module named x"


def test_summarise_failure_falls_back_to_exit_code_when_empty() -> None:
    assert summarise_failure([], exit_code=2) == "退出码 2"
    assert summarise_failure(["", "   "], exit_code=3) == "退出码 3"


def test_summarise_failure_handles_only_noise() -> None:
    # 全是噪声时回退到最后一行，而不是抛异常或返回空
    assert summarise_failure(["版本: 1.0", "==="], exit_code=1) == "==="


def test_runner_uses_bounded_default_timeout() -> None:
    """默认必须有兜底超时，否则子进程挂死会无限等待。"""
    assert spider_service.DEFAULT_RUN_TIMEOUT_SECONDS > 0


class _SlowProcess:
    """持续输出但不结束的假进程，用于验证超时真的生效。"""

    def __init__(self) -> None:
        self.stdout = self
        self.killed = False
        self._count = 0

    def __iter__(self):  # noqa: ANN204
        return self

    def __next__(self):  # noqa: ANN204
        self._count += 1
        if self._count > 2000:
            raise StopIteration
        time.sleep(0.02)
        return "still working\n"

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        self.killed = True


def test_runner_timeout_applies_while_streaming(monkeypatch) -> None:  # noqa: ANN001
    """超时必须对读取循环生效——只交给 wait() 无效（实测 30s 限制仍跑了 84s）。"""
    process = _SlowProcess()
    monkeypatch.setattr(
        spider_service,
        "check_environment",
        lambda **_: spider_service.SpiderEnvironment(
            available=True, message="ok", directory=Path.cwd(), python="python"
        ),
    )
    monkeypatch.setattr(spider_service.subprocess, "Popen", lambda *a, **k: process)

    started = time.monotonic()
    result = spider_service.SpiderRunner(timeout=0.3).run(
        SpiderConfig(accounts=(SpiderAccount(platform="douyin", url_or_id="a"),))
    )
    elapsed = time.monotonic() - started

    assert result.success is False
    assert "超时" in result.message
    assert elapsed < 5.0, f"超时未生效，耗时 {elapsed:.1f}s"
    assert process.killed is True


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
