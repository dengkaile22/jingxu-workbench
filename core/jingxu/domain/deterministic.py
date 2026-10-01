"""确定性伪随机数：SplitMix64 与随机袋抽取。

与 .NET 版 ``DeterministicRandom`` / ``DeterministicShuffleCycle`` 算法一致，
保证同一批参数在任何运行环境下都能复现相同的素材顺序。
"""

from __future__ import annotations

_MASK64 = (1 << 64) - 1
_UINT64_MAX = _MASK64
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15
_MIX1 = 0xBF58476D1CE4E5B9
_MIX2 = 0x94D049BB133111EB


class DeterministicRandom:
    """基于 SplitMix64 的确定性伪随机数发生器。"""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK64

    @classmethod
    def from_branch(cls, base_seed: int, branch_index: int) -> DeterministicRandom:
        """从种子和命名分支派生一个独立的随机源。"""
        mixer = cls(base_seed)
        for _ in range(branch_index + 1):
            mixer.next_uint64()
        return cls(mixer.next_uint64())

    def next_uint64(self) -> int:
        """返回下一个 64 位伪随机值（SplitMix64）。"""
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * _MIX1) & _MASK64
        z = ((z ^ (z >> 27)) * _MIX2) & _MASK64
        return z ^ (z >> 31)

    def next_double(self) -> float:
        """返回 [0.0, 1.0) 范围内的均匀分布浮点数。"""
        return self.next_uint64() / _UINT64_MAX

    def random(self) -> float:
        """``random.Random`` 风格别名：返回 [0.0, 1.0) 浮点数。"""
        return self.next_double()

    def uniform(self, low: float, high: float) -> float:
        """返回 [low, high) 范围内的均匀分布浮点数。"""
        return low + (high - low) * self.next_double()

    def next_int(self, exclusive_max: int) -> int:
        """返回 [0, exclusive_max) 范围内的均匀分布整数。"""
        if exclusive_max <= 0:
            raise ValueError("上界必须为正整数。")
        threshold = (-exclusive_max) % exclusive_max
        while True:
            value = self.next_uint64()
            if value >= threshold:
                return value % exclusive_max


def select_index(item_count: int, seed: int, selection_ordinal: int, branch_index: int = 0) -> int:
    """按随机袋中的全局抽取序号返回素材索引。

    先随机确定首项，再只洗牌剩余项，保证一轮内每个索引只出现一次。
    """
    if item_count <= 0:
        raise ValueError("素材数量必须大于零。")
    if selection_ordinal < 0:
        raise ValueError("抽取序号不能为负数。")
    if item_count == 1:
        return 0

    order = list(range(item_count))
    generator = DeterministicRandom.from_branch(seed, branch_index)

    first_index = generator.next_int(item_count)
    order[0], order[first_index] = order[first_index], order[0]
    for index in range(item_count - 1, 1, -1):
        target = 1 + generator.next_int(index)
        order[index], order[target] = order[target], order[index]

    return order[selection_ordinal % item_count]


def select_index_with_reshuffled_cycles(
    item_count: int,
    seed: int,
    selection_ordinal: int,
    branch_index: int = 0,
) -> int:
    """按逐轮重洗牌的随机袋返回素材索引。

    每轮完整覆盖全部素材，下一轮派生新顺序，并避免轮次交界连续命中同一素材。
    """
    if item_count <= 0:
        raise ValueError("素材数量必须大于零。")
    if selection_ordinal < 0:
        raise ValueError("抽取序号不能为负数。")
    if item_count <= 2:
        return select_index(item_count, seed, selection_ordinal, branch_index)

    cycle_ordinal = selection_ordinal // item_count
    offset = selection_ordinal % item_count
    order = _build_cycle_order(item_count, seed, cycle_ordinal, branch_index)
    if cycle_ordinal > 0:
        previous = _build_cycle_order(item_count, seed, cycle_ordinal - 1, branch_index)
        if order == previous:
            order[0], order[1] = order[1], order[0]
        if order[0] == previous[-1]:
            order[0], order[1] = order[1], order[0]

    return order[offset]


def _build_cycle_order(item_count: int, seed: int, cycle_ordinal: int, branch_index: int) -> list[int]:
    cycle_bits = (cycle_ordinal * _GOLDEN_GAMMA) & _MASK64
    mixed_seed = ((seed << 32) ^ cycle_bits ^ (branch_index & 0xFFFFFFFF)) & _MASK64
    generator = DeterministicRandom(mixed_seed)
    order = list(range(item_count))
    for index in range(item_count - 1, 0, -1):
        target = generator.next_int(index + 1)
        order[index], order[target] = order[target], order[index]
    return order
