"""混剪编排页迁移回归：差异化旋转 / 无损直拷 / 上下双屏与中缝强度 / 模板往返。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_asset

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.splitscreen import SplitMode  # noqa: E402
from jingxu.ui.composition_page import QUALITY_SETTINGS, CompositionPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CompositionPage:
    """隔离数据目录后再构造页面（EffectTemplateStore 会写入该目录）。"""
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
    page = CompositionPage()
    page.set_materials([make_asset("a.mp4"), make_asset("b.mp4")])
    return page


def test_quality_lossless_sets_stream_copy(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)

    assert page._quality.value() == "balanced"
    assert page.draft().settings.stream_copy is False

    page._quality.set_value("lossless")
    page._refresh_quality_hint()  # set_value 不触发 changed，模板应用路径也是显式刷新
    draft = page.draft()
    assert draft.settings.stream_copy is True
    crf, preset, hint = QUALITY_SETTINGS["lossless"]
    assert draft.settings.crf == crf
    assert draft.settings.preset == preset
    assert page._quality_hint.text() == hint


def test_variation_rotation_written_to_draft(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)

    page._variation_enable.setChecked(True)
    assert page._variation_rotate.isChecked() is True  # 旋转默认开启（对齐 .NET）
    assert page._variation_rotation_max.isEnabled() is True

    page._variation_rotate.setChecked(False)
    assert page._variation_rotation_max.isEnabled() is False
    page._variation_rotate.setChecked(True)
    page._variation_rotation_max.setValue(6.5)

    variation = page.draft().settings.variation
    assert variation is not None
    assert variation.rotate is True
    assert variation.rotation_max_degrees == 6.5
    assert page._variation_intensity.minimum() == 1
    assert page._variation_intensity.maximum() == 200
    assert page._variation_intensity.value() == 100


def test_split_modes_are_mutually_exclusive(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)

    page._double_v_enable.setChecked(True)
    assert page._double_enable.isChecked() is False
    assert page._four_enable.isChecked() is False
    draft = page.draft()
    assert draft.double_screen is not None and draft.split is None

    page._double_enable.setChecked(True)
    assert page._double_v_enable.isChecked() is False
    assert page._four_enable.isChecked() is False
    draft = page.draft()
    assert draft.split is not None and draft.split.mode is SplitMode.DOUBLE_H
    assert draft.double_screen is None

    page._four_enable.setChecked(True)
    assert page._double_enable.isChecked() is False
    assert page._double_v_enable.isChecked() is False
    draft = page.draft()
    assert draft.four_screen is not None
    assert draft.split is None and draft.double_screen is None

    page._four_enable.setChecked(False)
    draft = page.draft()
    assert draft.split is None and draft.double_screen is None and draft.four_screen is None


def test_split_feather_defaults_and_range(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)

    assert page._split_feather_px.minimum() == 0
    assert page._split_feather_px.maximum() == 256
    assert page._split_feather_px.singleStep() == 8
    assert page._split_feather_px.value() == 48

    page._double_v_enable.setChecked(True)
    page._split_feather_px.setValue(96)
    plan = page.draft().double_screen
    assert plan is not None
    assert plan.feather_pixels == 96
    assert page._split_feather_label.text() == "96 像素"


def test_template_roundtrip_rotation_split_and_feather(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)

    page._variation_enable.setChecked(True)
    page._variation_rotate.setChecked(True)
    page._variation_rotation_max.setValue(9.0)
    page._double_v_enable.setChecked(True)
    page._split_feather_px.setValue(120)
    payload = page._template_payload()
    assert payload["variation"]["rotate"] is True
    assert payload["variation"]["rotation_max_degrees"] == 9.0
    assert payload["split_mode"] == "double_v"
    assert payload["split_four"] is False
    assert payload["split_feather_px"] == 120

    page._variation_enable.setChecked(False)
    page._double_v_enable.setChecked(False)
    page._split_feather_px.setValue(8)
    page._apply_template_payload(payload)

    variation = page.draft().settings.variation
    assert variation is not None
    assert variation.rotate is True
    assert variation.rotation_max_degrees == 9.0
    plan = page.draft().double_screen
    assert plan is not None
    assert page._split_feather_px.value() == 120
    assert plan.feather_pixels == 120


def test_template_legacy_payload_falls_back_to_four(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)

    legacy = {"split_enabled": True, "split_four": True, "split_feather_px": 64}
    page._apply_template_payload(legacy)
    assert page.draft().four_screen is not None
    assert page._split_feather_px.value() == 64

    legacy_double = {"split_enabled": True, "split_four": False}
    page._apply_template_payload(legacy_double)
    spec = page.draft().split
    assert spec is not None and spec.mode is SplitMode.DOUBLE_H

    page._apply_template_payload({})
    draft = page.draft()
    assert draft.split is None and draft.double_screen is None and draft.four_screen is None


def test_bgm_enable_gate_controls_draft(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"stub")
    page._bgm_file = bgm

    # 默认未启用：不生成 BGM。
    assert page.draft().bgm_source is None

    page._bgm_enable.setChecked(True)
    page._bgm_volume.setValue(25)
    source = page.draft().bgm_source
    assert source is not None and source.kind == "file"
    assert source.volume_percent == 25


def test_audio_library_random_volume_takes_priority(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)
    track = tmp_path / "track.mp3"
    track.write_bytes(b"stub")
    page.set_audio_library([track])

    page._library_enable.setChecked(True)
    page._library_fixed_enable.setChecked(True)
    page._library_volume.setValue(40)
    page._library_random_enable.setChecked(True)
    page._library_min.setValue(12)
    page._library_max.setValue(24)

    source = page.draft().bgm_source
    assert source is not None and source.kind == "library"
    assert source.volume_mode == "random"  # 随机优先
    assert "随机优先" in page._library_hint.text()


def test_boost_section_flows_into_draft_and_template(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    page = _page(monkeypatch, tmp_path)

    assert page.draft().settings.boost is None
    page._boost_volume_enable.setChecked(True)
    page._boost_scale_enable.setChecked(True)
    page._boost_volume_fixed.setValue(105.5)
    plan = page.draft().settings.boost
    assert plan is not None
    assert plan.enable_volume and plan.enable_scale
    assert plan.volume_min_percent == pytest.approx(105.5)

    payload = page._template_payload()
    assert payload["boost"]["volume_enabled"] is True
    assert payload["aspect_enabled"] is True

    page._boost_volume_enable.setChecked(False)
    page._boost_scale_enable.setChecked(False)
    page._aspect_enable.setChecked(False)
    page._apply_template_payload(payload)

    restored = page.draft().settings.boost
    assert restored is not None and restored.enable_volume
    assert page._aspect_enable.isChecked() is True
