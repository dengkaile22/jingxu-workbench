"""确定性随机与随机袋抽取测试。"""

from __future__ import annotations

import pytest

from jingxu.domain.deterministic import (
    DeterministicRandom,
    select_index,
    select_index_with_reshuffled_cycles,
)


class TestSplitMix64:
    def test_reference_vectors_seed_zero(self) -> None:
        generator = DeterministicRandom(0)
        assert generator.next_uint64() == 0xE220A8397B1DCDAF
        assert generator.next_uint64() == 0x6E789E6AA1B965F4
        assert generator.next_uint64() == 0x06C45D188009454F

    def test_seed_is_reproducible(self) -> None:
        first = [DeterministicRandom(42).next_uint64() for _ in range(1)]
        second = [DeterministicRandom(42).next_uint64() for _ in range(1)]
        assert first == second
        assert DeterministicRandom(42).next_uint64() != DeterministicRandom(43).next_uint64()

    def test_from_branch_is_stable_and_divergent(self) -> None:
        branch_a = DeterministicRandom.from_branch(2026, 3)
        branch_a_again = DeterministicRandom.from_branch(2026, 3)
        branch_b = DeterministicRandom.from_branch(2026, 4)
        assert branch_a.next_uint64() == branch_a_again.next_uint64()
        assert branch_a.next_uint64() != branch_b.next_uint64()

    def test_next_double_range(self) -> None:
        generator = DeterministicRandom(7)
        for _ in range(100):
            value = generator.next_double()
            assert 0.0 <= value <= 1.0

    def test_next_int_range_and_errors(self) -> None:
        generator = DeterministicRandom(11)
        for _ in range(200):
            value = generator.next_int(5)
            assert 0 <= value < 5
        with pytest.raises(ValueError, match="上界必须为正整数"):
            generator.next_int(0)


class TestShuffleCycle:
    def test_cycle_covers_every_index_once(self) -> None:
        item_count = 7
        picks = [select_index_with_reshuffled_cycles(item_count, 99, ordinal) for ordinal in range(item_count)]
        assert sorted(picks) == list(range(item_count))

    def test_cycle_boundary_avoids_immediate_repeat(self) -> None:
        item_count = 5
        picks = [select_index_with_reshuffled_cycles(item_count, 1234, ordinal) for ordinal in range(item_count * 4)]
        for first, second in zip(picks, picks[1:]):
            assert first != second

    def test_cycle_is_deterministic(self) -> None:
        first = [select_index_with_reshuffled_cycles(6, 5, ordinal) for ordinal in range(12)]
        second = [select_index_with_reshuffled_cycles(6, 5, ordinal) for ordinal in range(12)]
        assert first == second

    def test_two_items_alternate(self) -> None:
        picks = [select_index(2, 8, ordinal) for ordinal in range(6)]
        assert sorted(picks[:2]) == [0, 1]
        assert picks[0] != picks[1]

    def test_small_counts(self) -> None:
        assert select_index(1, 3, 10) == 0
        with pytest.raises(ValueError, match="素材数量必须大于零"):
            select_index(0, 3, 0)
        with pytest.raises(ValueError, match="抽取序号不能为负数"):
            select_index(3, 3, -1)
