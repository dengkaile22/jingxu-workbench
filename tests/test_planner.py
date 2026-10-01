"""序号提取、表达式解析与批量随机计划测试。"""

from __future__ import annotations

import pytest
from conftest import make_asset

from jingxu.domain.composition import (
    SequenceError,
    has_duplicate_sequence_indices,
    normalize_assets,
    parse_expression,
    plan_custom,
    plan_random_batch,
    split_expressions,
)
from jingxu.domain.media import extract_sequence_index


class TestExtractSequenceIndex:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("商品_片段_12.mp4", 12),
            ("01.mp4", 1),
            ("a1b22c333.mov", 333),
            ("no_number.mp4", None),
            ("", None),
            ("deadbeefdeadbeefdeadbeefdeadbeef.mp4", None),
            ("0.mp4", None),
        ],
    )
    def test_extraction(self, name: str, expected: int | None) -> None:
        assert extract_sequence_index(name) == expected


class TestSplitExpressions:
    def test_newline_and_semicolon(self) -> None:
        assert split_expressions("264513\n351246; 123") == ["264513", "351246", "123"]

    def test_empty(self) -> None:
        assert split_expressions("   ") == []


class TestParseExpression:
    def test_compact_requires_single_digits(self) -> None:
        assert parse_expression("264513") == [2, 6, 4, 5, 1, 3]

    def test_comma_allows_multi_digit_and_repeats(self) -> None:
        assert parse_expression("2,6,14,5,1,3") == [2, 6, 14, 5, 1, 3]
        assert parse_expression("2,2,3") == [2, 2, 3]

    def test_full_width_comma(self) -> None:
        assert parse_expression("2，6，4") == [2, 6, 4]

    @pytest.mark.parametrize("text", ["", "  ", "a1", "2,0", "2,,3", "1,2,x"])
    def test_invalid(self, text: str) -> None:
        with pytest.raises(SequenceError):
            parse_expression(text)


class TestPlanCustom:
    def test_maps_by_sequence_index(self) -> None:
        assets = [
            make_asset("clip_1.mp4"),
            make_asset("clip_2.mp4"),
            make_asset("clip_3.mp4"),
        ]
        indexed = [
            assets[0].__class__(**{**_as_dict(asset), "sequence_index": index})
            for index, asset in enumerate(assets, start=1)
        ]
        plan = plan_custom(indexed, [3, 1, 3])
        assert [asset.display_name for asset in plan.assets] == ["clip_3.mp4", "clip_1.mp4", "clip_3.mp4"]

    def test_missing_index_raises(self) -> None:
        assets = [make_asset("a.mp4"), make_asset("b.mp4")]
        with pytest.raises(SequenceError, match="不存在"):
            plan_custom(assets, [1, 5])


class TestPlanRandomBatch:
    def test_batch_is_deterministic_and_differentiated(self) -> None:
        assets = [make_asset(f"{i}.mp4") for i in range(6)]
        first = plan_random_batch(assets, 4, 2026)
        second = plan_random_batch(assets, 4, 2026)
        orders = [tuple(asset.display_name for asset in plan.assets) for plan in first]
        assert orders == [tuple(asset.display_name for asset in plan.assets) for plan in second]
        assert len(set(orders)) == 4

    def test_clips_per_plan(self) -> None:
        assets = [make_asset(f"{i}.mp4") for i in range(5)]
        plans = plan_random_batch(assets, 3, 7, clips_per_plan=3)
        assert all(len(plan.assets) == 3 for plan in plans)

    def test_repeats_when_permutation_space_exhausted(self) -> None:
        assets = [make_asset(f"{i}.mp4", duration=1.0) for i in range(2)]
        plans = plan_random_batch(assets, 5, 3)
        assert len(plans) == 5

    def test_empty_assets(self) -> None:
        with pytest.raises(SequenceError, match="素材列表不能为空"):
            plan_random_batch([], 1, 1)


class TestHelpers:
    def test_duplicate_detection(self) -> None:
        first = make_asset("a1.mp4", duration=1.0)
        second = make_asset("b1.mp4", duration=1.0)
        third = make_asset("c2.mp4", duration=1.0)
        plain = [make_asset("x.mp4"), make_asset("y.mp4")]
        assert not has_duplicate_sequence_indices(plain)
        assert has_duplicate_sequence_indices([first, second, third])

    def test_normalize_sorts_by_index_then_path(self) -> None:
        assets = [
            make_asset("b.mp4"),
            make_asset("a.mp4"),
        ]
        normalized = normalize_assets(assets)
        assert [asset.display_name for asset in normalized] == ["a.mp4", "b.mp4"]


def _as_dict(asset) -> dict:
    return {
        "path": asset.path,
        "duration": asset.duration,
        "width": asset.width,
        "height": asset.height,
        "fps": asset.fps,
        "has_audio": asset.has_audio,
        "video_codec": asset.video_codec,
        "audio_codec": asset.audio_codec,
    }
