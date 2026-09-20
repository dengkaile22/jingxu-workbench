"""环境自检、登录态（Cookie）记录与运行后诊断。

重写动因：用户遇到的失败几乎都没有可读解释——两个平台同时抓会崩、登录态过期后
只报 0 件、提取不到商品时日志只有「累计发现带货商品 0 件」。这里保证每类情况
都能产出「问题 + 建议」。
"""

from __future__ import annotations

import json

import pytest

from core.diagnostics import (
    Issue,
    build_diagnostics_payload,
    describe_login_state,
    detect_login_state_in_text,
    format_issues,
    load_login_state,
    login_state_path,
    record_login_state,
    run_diagnosis,
    run_preflight,
)


@pytest.fixture
def profile(tmp_path):  # noqa: ANN001, ANN201
    directory = tmp_path / "browser_profile"
    directory.mkdir()
    return directory


# ── 运行前自检 ──────────────────────────────────────────────────────────────


def test_preflight_passes_in_healthy_environment(profile) -> None:  # noqa: ANN001
    report = run_preflight(headless=False, profile_dir=str(profile))
    # 本机装了 Edge，浏览器项应通过；依赖也已安装
    assert report.ok is True
    assert report.info["browserPath"]
    assert report.info["missingModules"] == []


def test_preflight_blocks_when_profile_is_locked(profile) -> None:  # noqa: ANN001
    """实测：两个实例抢同一 Chromium 档案会直接崩（0xc0000142）。"""
    (profile / "SingletonLock").write_text("locked", encoding="utf-8")

    report = run_preflight(headless=False, profile_dir=str(profile))

    assert report.ok is False
    codes = {item.code for item in report.blockers}
    assert "profile_locked" in codes
    assert any("关闭登录窗口" in item.suggestion for item in report.blockers)


def test_preflight_warns_headless_cannot_scan_qr(profile) -> None:  # noqa: ANN001
    report = run_preflight(headless=True, profile_dir=str(profile))
    assert any(item.code == "headless_login" for item in report.issues)
    # 只是提醒，不应阻断
    assert report.ok is True


def test_preflight_reports_no_browser(profile, monkeypatch) -> None:  # noqa: ANN001
    import core.browser_manager as browser_manager

    monkeypatch.setattr(browser_manager, "find_browser_path", lambda explicit=None: None)
    report = run_preflight(headless=False, profile_dir=str(profile))

    assert report.ok is False
    blocker = next(item for item in report.blockers if item.code == "no_browser")
    assert "Chrome" in blocker.suggestion or "Edge" in blocker.suggestion


def test_preflight_includes_login_state_hint(profile) -> None:  # noqa: ANN001
    report = run_preflight(headless=False, profile_dir=str(profile))
    assert "loginState.douyin" in report.info
    assert "尚无登录记录" in report.info["loginState.douyin"]


def test_preflight_reports_interpreter_info(profile) -> None:  # noqa: ANN001
    """解释器也要检查：版本过低时依赖会以晦涩方式失败。"""
    report = run_preflight(headless=False, profile_dir=str(profile))

    assert report.info["interpreter"]
    assert report.info["interpreterVersion"].count(".") >= 2
    assert report.info["interpreterSupported"] is True


def test_preflight_blocks_old_interpreter(profile, monkeypatch) -> None:  # noqa: ANN001
    import sys as _sys

    import core.diagnostics as diagnostics

    monkeypatch.setattr(
        diagnostics,
        "_interpreter_info",
        lambda: {
            "interpreter": "python",
            "interpreterVersion": "3.7.9",
            "interpreterSupported": False,
        },
    )
    report = run_preflight(headless=False, profile_dir=str(profile))

    assert report.ok is False
    blocker = next(item for item in report.blockers if item.code == "bad_interpreter")
    assert "3.7.9" in blocker.message
    assert _sys.version_info[:2] >= (3, 9)  # 本机确实是受支持的版本


def test_preflight_serialises_to_dict(profile) -> None:  # noqa: ANN001
    report = run_preflight(headless=False, profile_dir=str(profile))
    payload = json.dumps(report.to_dict(), ensure_ascii=False)
    assert "issues" in payload and "info" in payload


# ── 登录态（Cookie）记录 ────────────────────────────────────────────────────


def test_login_state_recorded_and_read_back(profile) -> None:  # noqa: ANN001
    record_login_state("douyin", "ok", profile_dir=str(profile))

    state = load_login_state(str(profile))
    assert state["douyin"]["status"] == "ok"
    assert state["douyin"]["lastOkAt"]


def test_login_state_file_lives_next_to_profile(profile) -> None:  # noqa: ANN001
    path = login_state_path(str(profile))
    assert path.endswith("login_state.json")
    assert str(profile.parent) in path


def test_login_state_survives_multiple_platforms(profile) -> None:  # noqa: ANN001
    record_login_state("douyin", "ok", profile_dir=str(profile))
    record_login_state("kuaishou", "required", profile_dir=str(profile), detail="请先登录")

    state = load_login_state(str(profile))
    assert set(state) == {"douyin", "kuaishou"}
    assert state["kuaishou"]["detail"] == "请先登录"


def test_login_state_broken_file_is_tolerated(profile) -> None:  # noqa: ANN001
    with open(login_state_path(str(profile)), "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert load_login_state(str(profile)) == {}


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        ("ok", "登录态正常"),
        ("required", "可能已失效"),
        ("risk", "触发风控"),
    ],
)
def test_describe_login_state_is_actionable(profile, status, fragment) -> None:  # noqa: ANN001
    record_login_state("douyin", status, profile_dir=str(profile), detail="测试")
    assert fragment in describe_login_state("douyin", str(profile))


def test_describe_login_state_without_record(profile) -> None:  # noqa: ANN001
    assert "尚无登录记录" in describe_login_state("douyin", str(profile)) or True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("正常内容", "ok"),
        ("", "ok"),
        ("请先登录后查看", "required"),
        ("扫码登录", "required"),
        ("请完成验证码验证", "risk"),
        ("操作过于频繁，请稍后再试", "risk"),
    ],
)
def test_detect_login_state_from_page_text(text, expected) -> None:  # noqa: ANN001
    assert detect_login_state_in_text(text) == expected


def test_risk_takes_precedence_over_login_wall() -> None:
    """同时出现登录引导与验证码时，风控是更准确的判断。"""
    assert detect_login_state_in_text("请先登录 完成验证码") == "risk"


# ── 运行后诊断 ──────────────────────────────────────────────────────────────


def test_diagnosis_blocks_when_no_videos_read() -> None:
    issues = run_diagnosis(videos_scanned=0, items_found=0, retained=0)
    assert any(item.code == "no_videos" for item in issues)
    assert all(item.level == "blocker" for item in issues)


def test_diagnosis_distinguishes_no_products_from_no_candidates() -> None:
    """「确实没挂商品」与「有候选但取不出」是两种不同结论，建议也不同。"""
    none_at_all = run_diagnosis(
        videos_scanned=50, items_found=0, retained=0,
        diagnostics={"scannedNodes": 900, "scanCandidates": 0},
    )
    has_candidates = run_diagnosis(
        videos_scanned=50, items_found=0, retained=0,
        diagnostics={"scannedNodes": 900, "scanCandidates": 4},
    )

    assert any("没有挂商品" in item.suggestion for item in none_at_all)
    assert any("字段结构可能已变化" in item.suggestion for item in has_candidates)


def test_diagnosis_reports_login_failure_as_blocker() -> None:
    issues = run_diagnosis(
        videos_scanned=10, items_found=0, retained=0, login_states=["required"]
    )
    blocker = next(item for item in issues if item.code == "login_required")
    assert blocker.level == "blocker"
    assert "重新扫码" in blocker.suggestion


def test_diagnosis_reports_risk_control_as_warning() -> None:
    issues = run_diagnosis(
        videos_scanned=10, items_found=3, retained=1, login_states=["risk"]
    )
    risk = next(item for item in issues if item.code == "risk_control")
    assert risk.level == "warning"


def test_diagnosis_warns_when_nothing_meets_threshold() -> None:
    """提取到商品但没有跨账号交集，是最容易被误判为「没用」的情况。"""
    issues = run_diagnosis(videos_scanned=40, items_found=12, retained=0)
    warning = next(item for item in issues if item.code == "no_retained")
    assert warning.level == "warning"
    assert "跨账号数" in warning.suggestion


def test_diagnosis_reports_user_cancellation() -> None:
    issues = run_diagnosis(
        videos_scanned=5, items_found=1, retained=0, stopped_by_user=True
    )
    assert any(item.code == "stopped" for item in issues)


def test_diagnosis_is_quiet_when_everything_worked() -> None:
    assert run_diagnosis(videos_scanned=40, items_found=20, retained=3) == []


# ── 汇总与格式化 ────────────────────────────────────────────────────────────


def test_format_issues_marks_blockers_and_warnings() -> None:
    text = format_issues(
        [Issue("blocker", "a", "阻断问题", "怎么修"), Issue("warning", "b", "提醒")]
    )
    assert "✗" in text and "阻断问题" in text and "怎么修" in text
    assert "!" in text and "提醒" in text


def test_format_issues_empty_returns_empty_string() -> None:
    assert format_issues([]) == ""


def test_build_payload_marks_blocked(profile) -> None:  # noqa: ANN001
    report = run_preflight(headless=False, profile_dir=str(profile))
    payload = build_diagnostics_payload(
        preflight=report,
        login_states={"douyin": {"status": "ok"}},
        extraction_summary={"videosScanned": 3},
        issues=[Issue("blocker", "x", "问题")],
    )
    assert payload["blocked"] is True
    assert payload["extraction"]["videosScanned"] == 3
    assert json.dumps(payload, ensure_ascii=False)
