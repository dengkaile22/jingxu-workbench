"""编排规则测试。"""

from __future__ import annotations

import pytest
from conftest import make_asset

from jingxu.domain.composition import (
    CompositionPlan,
    OrderMode,
    SequenceError,
    parse_sequence,
    plan_order,
)


class TestParseSequence:
    def test_compact_input(self) -> None:
        assert parse_sequence("264513", 6) == [1, 5, 3, 4, 0, 2]

    def test_comma_input(self) -> None:
        assert parse_sequence("2,6,4,5,1,3", 6) == [1, 5, 3, 4, 0, 2]

    def test_full_width_comma_and_spaces(self) -> None:
        assert parse_sequence(" 2，6，4，5，1，3 ", 6) == [1, 5, 3, 4, 0, 2]

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "请输入自定义序号"),
            ("2645", "数量必须与素材数量一致"),
            ("2645133", "数量必须与素材数量一致"),
            ("2645a3", "只能包含数字"),
            ("264533", "不重复排列"),
            ("274513", "不重复排列"),
        ],
    )
    def test_rejects_invalid_input(self, text: str, message: str) -> None:
        with pytest.raises(SequenceError, match=message):
            parse_sequence(text, 6)


class TestPlanOrder:
    def test_sequential_keeps_order(self) -> None:
        assets = [make_asset(f"{i}.mp4") for i in range(3)]
        ordered = plan_order(assets, OrderMode.SEQUENTIAL)
        assert [asset.display_name for asset in ordered] == ["0.mp4", "1.mp4", "2.mp4"]

    def test_random_is_reproducible_with_seed(self) -> None:
        assets = [make_asset(f"{i}.mp4") for i in range(8)]
        first = plan_order(assets, OrderMode.RANDOM, seed=2026)
        second = plan_order(assets, OrderMode.RANDOM, seed=2026)
        third = plan_order(assets, OrderMode.RANDOM, seed=7)

        assert [a.display_name for a in first] == [a.display_name for a in second]
        assert sorted(a.display_name for a in first) == sorted(a.display_name for a in assets)
        assert [a.display_name for a in first] != [a.display_name for a in third]

    def test_custom_uses_sequence(self) -> None:
        assets = [make_asset(f"{i}.mp4") for i in range(3)]
        ordered = plan_order(assets, OrderMode.CUSTOM, sequence_text="312")
        assert [a.display_name for a in ordered] == ["2.mp4", "0.mp4", "1.mp4"]

    def test_empty_assets_returns_empty(self) -> None:
        assert plan_order([], OrderMode.RANDOM, seed=1) == ()


class TestCompositionPlan:
    def test_totals_and_audio_flag(self) -> None:
        plan = CompositionPlan(
            assets=(make_asset("a.mp4", duration=1.5), make_asset("b.mp4", duration=2.5, has_audio=False)),
            mode=OrderMode.SEQUENTIAL,
        )
        assert plan.total_duration == pytest.approx(4.0)
        assert plan.has_audio is True
