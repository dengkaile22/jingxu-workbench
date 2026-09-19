"""效果计划测试：双屏/四屏物化、主素材增强、画幅与导出策略、命名策略。"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.domain.composition import CompositionPlan, OrderMode
from jingxu.domain.effects import (
    DoubleScreenEffectPlan,
    DoubleScreenPlacement,
    DoubleScreenPlacementMode,
    DoubleScreenSourceMode,
    EffectPlanError,
    FourScreenEffectPlan,
    FourScreenSourceMode,
    MainMaterialBoostMode,
    MainMaterialBoostPlan,
)
from jingxu.domain.render import (
    FitMode,
    OutputCanvasPreset,
    OutputFrameRatePreset,
    OutputResolutionPreset,
    OutputVideoSettings,
    QualityPreset,
    RenderProfile,
    UnifiedAspectPolicy,
)
from jingxu.infrastructure.paths import (
    allocate_unique_path,
    sanitize_file_name_prefix,
    unique_output_path,
)

MATERIALS = Path("materials")


def _plan(*names: str, seed: int = 42) -> CompositionPlan:
    return CompositionPlan(assets=tuple(make_asset(name) for name in names), mode=OrderMode.RANDOM, seed=seed)


class TestDoubleScreenPlan:
    def test_validation(self) -> None:
        with pytest.raises(EffectPlanError, match="起始视频必须从 1 开始"):
            DoubleScreenEffectPlan(start_clip_index=0)
        with pytest.raises(EffectPlanError, match="羽化宽度"):
            DoubleScreenEffectPlan(feather_pixels=257)
        DoubleScreenEffectPlan()

    def test_applies_from_start_clip(self) -> None:
        plan = DoubleScreenEffectPlan(start_clip_index=2)
        assert plan.applies_to(1) is True
        assert plan.applies_to(0) is False

    def test_materialize_random_folder_is_deterministic(self) -> None:
        plan = _plan("a1.mp4", "a2.mp4", "a3.mp4")
        folder = [make_asset("a1.mp4"), make_asset("a2.mp4"), make_asset("a3.mp4"), make_asset("a4.mp4")]
        effect = DoubleScreenEffectPlan(
            start_clip_index=1,
            source_mode=DoubleScreenSourceMode.RANDOM_CURRENT_FOLDER,
            placement_mode=DoubleScreenPlacementMode.RANDOM,
        )

        first = effect.materialize_for_plan(plan, folder, 0)
        second = effect.materialize_for_plan(plan, folder, 0)

        assert [item.source_asset.display_name for item in first.clip_selections] == [
            item.source_asset.display_name for item in second.clip_selections
        ]
        assert len(first.clip_selections) == 3
        for clip_index, selection in enumerate(first.clip_selections):
            assert selection.clip_index == clip_index
            assert selection.source_asset.display_name != plan.assets[clip_index].display_name
            assert selection.placement in (DoubleScreenPlacement.TOP, DoubleScreenPlacement.BOTTOM)

    def test_materialize_without_candidates_raises(self) -> None:
        effect = DoubleScreenEffectPlan(source_mode=DoubleScreenSourceMode.RANDOM_CURRENT_FOLDER)
        with pytest.raises(EffectPlanError, match="至少有一个视频素材"):
            effect.materialize_for_plan(_plan("a1.mp4"), [], 0)


class TestFourScreenPlan:
    def test_materialize_places_main_once(self) -> None:
        plan = _plan("a1.mp4", "a2.mp4")
        assets = [make_asset("a1.mp4"), make_asset("a2.mp4"), make_asset("a3.mp4")]
        effect = FourScreenEffectPlan(
            start_clip_index=1,
            source_mode=FourScreenSourceMode.RANDOM_CURRENT_FOLDER,
        )

        materialized = effect.materialize_for_plan(plan, assets, 1)
        assert len(materialized.clip_selections) == 2
        for selection in materialized.clip_selections:
            assert len(selection.cells) == 4
            main_cells = [cell for cell in selection.cells if cell.is_main]
            assert len(main_cells) == 1
            assert main_cells[0].source_asset.display_name == plan.assets[selection.clip_index].display_name

        materialized.validate_for_plan(plan)

    def test_same_source_mode_uses_main_for_all_cells(self) -> None:
        plan = _plan("a1.mp4", "a2.mp4")
        effect = FourScreenEffectPlan()
        materialized = effect.materialize_for_plan(plan, [], 0)
        for selection in materialized.clip_selections:
            names = {cell.source_asset.display_name for cell in selection.cells}
            assert names == {plan.assets[selection.clip_index].display_name}

    def test_validate_rejects_incomplete_snapshot(self) -> None:
        plan = _plan("a1.mp4", "a2.mp4")
        effect = FourScreenEffectPlan(start_clip_index=1)
        with pytest.raises(EffectPlanError, match="快照不完整"):
            effect.validate_for_plan(plan)

    def test_start_beyond_plan_raises(self) -> None:
        plan = _plan("a1.mp4")
        effect = FourScreenEffectPlan(start_clip_index=3)
        with pytest.raises(EffectPlanError, match="起始视频必须在 1 到 1 之间"):
            effect.materialize_for_plan(plan, [], 0)


class TestMainMaterialBoost:
    def test_requires_at_least_one_switch(self) -> None:
        with pytest.raises(EffectPlanError, match="至少启用音量或缩放之一"):
            MainMaterialBoostPlan()

    def test_range_validation(self) -> None:
        with pytest.raises(EffectPlanError, match="固定值必须在 100%–110%"):
            MainMaterialBoostPlan(enable_volume=True, volume_min_percent=120, volume_max_percent=120)
        with pytest.raises(EffectPlanError, match="随机下限不能大于上限"):
            MainMaterialBoostPlan(
                enable_volume=True,
                volume_mode=MainMaterialBoostMode.RANDOM,
                volume_min_percent=108,
                volume_max_percent=102,
            )

    def test_fixed_mode_uses_fixed_factor(self) -> None:
        plan = MainMaterialBoostPlan(enable_volume=True, volume_min_percent=105, volume_max_percent=105)
        materialized = plan.materialize(seed=7, clip_count=3)
        assert materialized.volume_factors == (1.05, 1.05, 1.05)
        assert materialized.normalize_loudness is True

    def test_random_mode_is_deterministic_and_in_range(self) -> None:
        plan = MainMaterialBoostPlan(
            enable_volume=True,
            volume_mode=MainMaterialBoostMode.RANDOM,
            volume_min_percent=101,
            volume_max_percent=109,
            enable_scale=True,
            scale_mode=MainMaterialBoostMode.RANDOM,
            scale_min_percent=100,
            scale_max_percent=110,
        )
        first = plan.materialize(seed=99, clip_count=4)
        second = plan.materialize(seed=99, clip_count=4)
        assert first.volume_factors == second.volume_factors
        assert all(1.01 <= factor <= 1.09 for factor in first.volume_factors)
        assert all(1.0 <= factor <= 1.1 for factor in first.scale_factors)
        assert len({first.volume_factors[i] for i in range(4)}) > 1


class TestOutputVideoSettings:
    def test_original_keeps_canvas(self) -> None:
        settings = OutputVideoSettings()
        assert settings.resolve_target_size(1080, 1920) == (1080, 1920)
        assert settings.requires_transcode is False

    @pytest.mark.parametrize(
        ("canvas", "preset", "expected"),
        [
            ((1080, 1920), OutputResolutionPreset.P720, (720, 1280)),
            ((1920, 1080), OutputResolutionPreset.P480, (854, 480)),
            ((1080, 1080), OutputResolutionPreset.P1080, (1080, 1080)),
            ((1080, 1440), OutputResolutionPreset.P480, (480, 640)),
        ],
    )
    def test_short_edge_scaling(self, canvas, preset, expected) -> None:
        settings = OutputVideoSettings(resolution=preset)
        assert settings.resolve_target_size(*canvas) == expected

    def test_frame_rate_resolution(self) -> None:
        assert OutputVideoSettings().resolve_frame_rate(29.97) == pytest.approx(29.97)
        assert OutputVideoSettings(frame_rate=OutputFrameRatePreset.FPS50).resolve_frame_rate(30) == 50
        assert OutputVideoSettings(frame_rate=OutputFrameRatePreset.FPS24).requires_transcode is True


class TestUnifiedAspectPolicy:
    def test_disabled_inherits_first(self) -> None:
        policy = UnifiedAspectPolicy()
        aspect = policy.to_output_aspect()
        assert aspect.inherit_from_first is True
        assert "未启用统一比例" in policy.build_preview_description()

    def test_presets_and_custom(self) -> None:
        policy = UnifiedAspectPolicy(is_enabled=True, preset=OutputCanvasPreset.PORTRAIT_3X4)
        aspect = policy.to_output_aspect()
        assert (aspect.target_width, aspect.target_height) == (1080, 1440)
        assert UnifiedAspectPolicy.recommended_overlay_fit(OutputCanvasPreset.PORTRAIT_3X4).value == "match_canvas_crop"
        assert UnifiedAspectPolicy.recommended_overlay_fit(OutputCanvasPreset.SQUARE_1X1).value == "fill_crop"

    def test_custom_requires_size(self) -> None:
        policy = UnifiedAspectPolicy(is_enabled=True, preset=OutputCanvasPreset.CUSTOM)
        with pytest.raises(ValueError, match="宽度与高度必须大于零"):
            policy.to_output_aspect()

    def test_apply_overlay_fit_updates_layers(self) -> None:
        from jingxu.domain.layers import LayerKind, LayerSpec

        layer = LayerSpec(kind=LayerKind.OVERLAY, source=Path("mask.mp4"))
        preset = OutputCanvasPreset.PORTRAIT_3X4
        policy = UnifiedAspectPolicy(
            is_enabled=True,
            preset=preset,
            overlay_fit_mode=UnifiedAspectPolicy.recommended_overlay_fit(preset),
        )
        updated = policy.apply_overlay_fit((layer,))
        assert updated[0].fit == "match_canvas_crop"
        assert layer.fit == "fill_crop"


class TestRenderProfile:
    def test_quality_presets(self) -> None:
        assert RenderProfile.for_preset(QualityPreset.HIGH).crf == 18
        assert RenderProfile.for_preset(QualityPreset.HIGH).audio_kbps == 192
        assert RenderProfile.for_preset(QualityPreset.HIGH).encode_preset == "fast"
        assert RenderProfile.for_preset(QualityPreset.BALANCED).crf == 22
        assert RenderProfile.for_preset(QualityPreset.BALANCED).audio_kbps == 160
        assert RenderProfile.for_preset(QualityPreset.SMALL).crf == 27
        assert RenderProfile.for_preset(QualityPreset.SMALL).audio_kbps == 128
        assert RenderProfile.for_preset(QualityPreset.FAST).crf == 26
        assert RenderProfile.for_preset(QualityPreset.FAST).encode_preset == "ultrafast"
        assert RenderProfile.for_preset(QualityPreset.LOSSLESS).crf is None


class TestOutputNaming:
    def test_sanitize(self) -> None:
        assert sanitize_file_name_prefix("a<b>:c/d") == "a_b__c_d"
        assert sanitize_file_name_prefix("  .. ") == "混剪成片"
        assert sanitize_file_name_prefix("混剪") == "混剪"

    def test_allocate_avoids_existing(self, tmp_path: Path) -> None:
        (tmp_path / "成片.mp4").write_text("x", encoding="utf-8")
        (tmp_path / "成片_001.mp4").write_text("x", encoding="utf-8")
        assert allocate_unique_path(tmp_path, "成片.mp4").name == "成片_002.mp4"

    def test_allocate_respects_reserved_paths(self, tmp_path: Path) -> None:
        reserved = tmp_path / "成片.mp4"
        assert allocate_unique_path(tmp_path, "成片.mp4", reserved_paths=[reserved]).name == "成片_001.mp4"

    def test_batch_suffix_not_doubled(self, tmp_path: Path) -> None:
        (tmp_path / "分镜_001.mp4").write_text("x", encoding="utf-8")
        allocated = unique_output_path(tmp_path, "分镜_001")
        assert allocated.name == "分镜_002.mp4"

    def test_cap_raises(self, tmp_path: Path) -> None:
        for index in range(1, 4):
            (tmp_path / f"成片_{index:03d}.mp4").write_text("x", encoding="utf-8")
        (tmp_path / "成片.mp4").write_text("x", encoding="utf-8")
        # 未超过上限时正常分配
        allocated = unique_output_path(tmp_path, "成片")
        assert allocated.name == "成片_004.mp4"
