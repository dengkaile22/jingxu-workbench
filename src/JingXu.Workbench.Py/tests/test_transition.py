"""交叉转场：域校验、时长扣减、xfade/acrossfade 滤镜链与界面预览。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_asset

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.application.composition_service import CompositionDraft, build_requests  # noqa: E402
from jingxu.application.stream_copy import stream_copy_blockers  # noqa: E402
from jingxu.domain.composition import CompositionPlan, OrderMode  # noqa: E402
from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.domain.render import (  # noqa: E402
    RenderRequest,
    RenderSettings,
    TransitionSettings,
    validate_transition,
)
from jingxu.infrastructure.filter_graph import build_filter_graph  # noqa: E402
from jingxu.ui.composition_page import CompositionPage  # noqa: E402


def _plan(*durations: float, has_audio: bool = True) -> CompositionPlan:
    return CompositionPlan(
        assets=tuple(
            make_asset(f"clip{index}.mp4", duration=duration, has_audio=has_audio)
            for index, duration in enumerate(durations)
        ),
        mode=OrderMode.SEQUENTIAL,
    )


def _settings(**kwargs) -> RenderSettings:
    return RenderSettings(width=640, height=360, fps=30, **kwargs)


def _request(plan: CompositionPlan, transition: TransitionSettings | None) -> RenderRequest:
    return RenderRequest(
        name="转场",
        plan=plan,
        settings=_settings(transition=transition),
        output_path=Path("out") / "转场.mp4",
    )


# ────────────────────────────── 域校验 ──────────────────────────────


def test_validate_transition_none_or_disabled_or_single_clip() -> None:
    plan = _plan(10.0, 10.0)

    assert validate_transition(plan, None) is None
    assert validate_transition(plan, TransitionSettings(enabled=False, duration_seconds=1.0)) is None
    assert validate_transition(_plan(10.0), TransitionSettings(enabled=True, duration_seconds=0.5)) is None


def test_validate_transition_requires_positive_duration() -> None:
    message = validate_transition(_plan(10.0, 10.0), TransitionSettings(enabled=True, duration_seconds=0.0))

    assert message == "转场时长必须大于 0 秒。"


def test_validate_transition_rejects_duration_not_shorter_than_clips() -> None:
    transition = TransitionSettings(enabled=True, duration_seconds=2.0)
    message = validate_transition(_plan(10.0, 2.0), transition)

    assert message is not None
    assert "超过了相邻片段" in message
    assert "clip0.mp4" in message and "clip1.mp4" in message

    shorter = TransitionSettings(enabled=True, duration_seconds=1.9)
    assert validate_transition(_plan(10.0, 2.0), shorter) is None


def test_total_duration_subtracts_transition_overlap() -> None:
    second = TransitionSettings(enabled=True, duration_seconds=1.0)

    assert _request(_plan(10.0, 10.0), second).total_duration == pytest.approx(19.0)
    assert _request(_plan(10.0, 10.0, 10.0), second).total_duration == pytest.approx(28.0)
    assert _request(_plan(10.0, 10.0), None).total_duration == pytest.approx(20.0)
    assert _request(_plan(10.0, 10.0), TransitionSettings(enabled=False)).total_duration == pytest.approx(20.0)
    assert _request(_plan(10.0), second).total_duration == pytest.approx(10.0)


# ────────────────────────────── 滤镜链 ──────────────────────────────


def test_xfade_and_acrossfade_replace_concat_for_two_clips() -> None:
    settings = _settings(transition=TransitionSettings(enabled=True, duration_seconds=1.0))
    graph = build_filter_graph(_plan(10.0, 10.0), settings)

    assert "[v0][v1]xfade=transition=fade:duration=1.000:offset=9.000[vx1]" in graph.script
    assert "[a0][a1]acrossfade=d=1.000:c1=tri:c2=tri[ax1]" in graph.script
    assert "concat=" not in graph.script
    assert "[vx1]null[vout]" in graph.script
    assert "[ax1]anull[aout]" in graph.script


def test_xfade_offsets_accumulate_for_three_clips() -> None:
    settings = _settings(transition=TransitionSettings(enabled=True, duration_seconds=1.0))
    graph = build_filter_graph(_plan(10.0, 10.0, 10.0), settings)

    assert "[v0][v1]xfade=transition=fade:duration=1.000:offset=9.000[vx1]" in graph.script
    assert "[vx1][v2]xfade=transition=fade:duration=1.000:offset=18.000[vx2]" in graph.script
    assert "[a0][a1]acrossfade=d=1.000:c1=tri:c2=tri[ax1]" in graph.script
    assert "[ax1][a2]acrossfade=d=1.000:c1=tri:c2=tri[ax2]" in graph.script
    assert "[vx2]null[vout]" in graph.script
    assert "[ax2]anull[aout]" in graph.script


def test_xfade_without_audio_skips_acrossfade() -> None:
    settings = _settings(transition=TransitionSettings(enabled=True, duration_seconds=1.0))
    graph = build_filter_graph(_plan(10.0, 10.0, has_audio=False), settings)

    assert graph.has_audio is False
    assert "xfade=transition=fade" in graph.script
    assert "acrossfade" not in graph.script
    assert "concat=" not in graph.script


def test_disabled_transition_keeps_hard_cut_concat() -> None:
    script = build_filter_graph(_plan(10.0, 10.0), _settings()).script

    assert "xfade=" not in script
    assert "concat=n=2:v=1:a=1[vcat][acat]" in script


def test_single_clip_keeps_concat_even_when_transition_enabled() -> None:
    settings = _settings(transition=TransitionSettings(enabled=True, duration_seconds=0.5))
    script = build_filter_graph(_plan(10.0), settings).script

    assert "xfade=" not in script
    assert "concat=n=1" in script


def test_invalid_transition_falls_back_to_concat() -> None:
    settings = _settings(transition=TransitionSettings(enabled=True, duration_seconds=0.5))
    script = build_filter_graph(_plan(0.4, 10.0), settings).script

    assert "xfade=" not in script
    assert "concat=n=2:v=1:a=1[vcat][acat]" in script


def test_tiny_clip_falls_back_to_concat_defensively() -> None:
    settings = _settings(transition=TransitionSettings(enabled=True, duration_seconds=0.01))
    script = build_filter_graph(_plan(0.03, 10.0), settings).script

    assert "xfade=" not in script
    assert "concat=n=2:v=1:a=1[vcat][acat]" in script


def test_transition_tail_feeds_layer_overlay() -> None:
    settings = _settings(transition=TransitionSettings(enabled=True, duration_seconds=0.5))
    layer = LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"))
    script = build_filter_graph(_plan(2.0, 2.0), settings, layers=(layer,)).script

    assert "[vx1][lay0]overlay=" in script
    assert "[ax1]anull[aout]" in script


# ────────────────────────────── 无损直拷 ──────────────────────────────


def test_stream_copy_blocker_for_enabled_transition() -> None:
    request = _request(_plan(2.0, 2.0), TransitionSettings(enabled=True, duration_seconds=0.5))
    blockers = stream_copy_blockers(request)

    assert len(blockers) == 1
    assert "交叉转场" in blockers[0]


def test_stream_copy_without_transition_has_no_transition_blocker() -> None:
    request = _request(_plan(2.0, 2.0), None)

    assert stream_copy_blockers(request) == ()
    assert stream_copy_blockers(_request(_plan(2.0, 2.0), TransitionSettings(enabled=False))) == ()


# ────────────────────────────── 入队校验 ──────────────────────────────


def test_build_requests_rejects_transition_longer_than_shortest_clip(tmp_path: Path) -> None:
    assets = [make_asset("a.mp4", duration=2.0), make_asset("b.mp4", duration=2.0)]
    draft = CompositionDraft(
        mode=OrderMode.SEQUENTIAL,
        settings=RenderSettings(transition=TransitionSettings(enabled=True, duration_seconds=3.0)),
    )

    with pytest.raises(ValueError, match="超过了相邻片段"):
        build_requests(assets=assets, draft=draft, output_directory=tmp_path)


def test_build_requests_keeps_total_duration_for_valid_transition(tmp_path: Path) -> None:
    assets = [make_asset("a.mp4", duration=2.0), make_asset("b.mp4", duration=2.0)]
    draft = CompositionDraft(
        mode=OrderMode.SEQUENTIAL,
        settings=RenderSettings(transition=TransitionSettings(enabled=True, duration_seconds=0.5)),
    )

    requests = build_requests(assets=assets, draft=draft, output_directory=tmp_path)

    assert len(requests) == 1
    assert requests[0].total_duration == pytest.approx(3.5)


# ────────────────────────────── 界面 ──────────────────────────────


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, assets: list) -> CompositionPage:
    """隔离数据目录后构造页面（EffectTemplateStore 会写入该目录）。"""
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
    page = CompositionPage()
    page.set_materials(assets)
    return page


def test_transition_controls_write_draft_and_live_summary(
    qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # noqa: ANN001
    assets = [make_asset(f"c{index}.mp4", duration=2.0) for index in range(3)]
    page = _page(monkeypatch, tmp_path, assets)

    assert page.draft().settings.transition is None
    assert page._transition_seconds.isEnabled() is False
    assert page._plan_summary.text() == "共 3 段 · 成片时长 00:06"

    page._transition_enable.setChecked(True)

    assert page._transition_seconds.isEnabled() is True
    assert page._plan_summary.text() == "共 3 段 · 成片时长 00:05"
    transition = page.draft().settings.transition
    assert transition is not None
    assert transition.enabled is True
    assert transition.duration_seconds == pytest.approx(0.5)

    page._transition_seconds.setValue(1.0)
    assert page._plan_summary.text() == "共 3 段 · 成片时长 00:04"


def test_preview_reports_invalid_transition(
    qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # noqa: ANN001
    assets = [make_asset("a.mp4", duration=2.0), make_asset("b.mp4", duration=2.0)]
    page = _page(monkeypatch, tmp_path, assets)

    page._transition_enable.setChecked(True)
    page._transition_seconds.setValue(2.0)

    assert "超过了相邻片段" in page._plan_summary.text()


def test_transition_template_roundtrip(
    qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # noqa: ANN001
    assets = [make_asset("a.mp4", duration=2.0), make_asset("b.mp4", duration=2.0)]
    page = _page(monkeypatch, tmp_path, assets)

    page._transition_enable.setChecked(True)
    page._transition_seconds.setValue(1.2)
    payload = page._template_payload()

    assert payload["transition_enabled"] is True
    assert payload["transition_seconds"] == pytest.approx(1.2)

    page._transition_enable.setChecked(False)
    page._apply_template_payload(payload)

    transition = page.draft().settings.transition
    assert transition is not None and transition.enabled is True
    assert transition.duration_seconds == pytest.approx(1.2)


def test_legacy_template_without_transition_keys_falls_back(
    qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # noqa: ANN001
    assets = [make_asset("a.mp4", duration=2.0), make_asset("b.mp4", duration=2.0)]
    page = _page(monkeypatch, tmp_path, assets)

    page._transition_enable.setChecked(True)
    page._apply_template_payload({"mode": "sequential"})

    assert page._transition_enable.isChecked() is False
    assert page._transition_seconds.isEnabled() is False
    assert page._transition_seconds.value() == pytest.approx(0.5)
    assert page.draft().settings.transition is None
