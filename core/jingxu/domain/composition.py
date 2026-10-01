"""编排模型、序号解析与可复现的批量计划。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum

from jingxu.domain.deterministic import DeterministicRandom
from jingxu.domain.media import MediaAsset

_EXPRESSION_SEPARATOR = re.compile(r"[\r\n;]+")
_ALL_DIGITS = re.compile(r"^\d+$")


class OrderMode(str, Enum):
    """拼接顺序模式。"""

    SEQUENTIAL = "sequential"
    RANDOM = "random"
    CUSTOM = "custom"


class SequenceError(ValueError):
    """自定义序号不合法。"""


def split_expressions(text: str) -> list[str]:
    """将多任务输入拆分为多条序号表达式（换行或分号分隔，忽略空行）。"""
    if not text or not text.strip():
        return []
    return [segment.strip() for segment in _EXPRESSION_SEPARATOR.split(text.strip()) if segment.strip()]


def parse_expression(expression: str) -> list[int]:
    """解析序号表达式并返回 1 基序号列表（允许重复）。

    支持紧凑单位数字（如 ``264513``）与逗号分隔任意位数（如 ``2,6,14,5,1,3``）。
    """
    if not expression or not expression.strip():
        raise SequenceError("序号表达式不能为空。")

    trimmed = expression.strip().replace("，", ",")
    if "," in trimmed:
        return _parse_comma_expression(trimmed)
    if _ALL_DIGITS.match(trimmed.replace(" ", "")):
        return _parse_compact_expression(trimmed.replace(" ", ""))

    raise SequenceError(f"序号表达式 \"{expression}\" 格式无效，仅支持紧凑数字或逗号分隔格式。")


def _parse_compact_expression(expression: str) -> list[int]:
    indices: list[int] = []
    for position, char in enumerate(expression):
        digit = ord(char) - ord("0")
        if digit < 1 or digit > 9:
            raise SequenceError(f"序号表达式第 {position + 1} 项 \"{char}\" 不是有效的正整数（1-9）。")
        indices.append(digit)
    if not indices:
        raise SequenceError("序号表达式不能为空。")
    return indices


def _parse_comma_expression(expression: str) -> list[int]:
    tokens = expression.split(",")
    indices: list[int] = []
    for position, token in enumerate(tokens):
        trimmed = token.strip()
        if not trimmed:
            raise SequenceError(f"序号表达式第 {position + 1} 项为空。")
        if not trimmed.isdigit() or int(trimmed) <= 0:
            raise SequenceError(f"序号表达式第 {position + 1} 项 \"{trimmed}\" 不是有效的正整数。")
        indices.append(int(trimmed))
    if not indices:
        raise SequenceError("序号表达式不能为空。")
    return indices


def parse_sequence(text: str, count: int) -> list[int]:
    """解析自定义序号并返回 0 基下标列表。

    支持紧凑输入 ``264513`` 与逗号输入 ``2,6,4,5,1,3``；
    必须是 1..count 的一个完整排列（不重不漏）。
    """
    if count <= 0:
        raise SequenceError("没有可编排的素材。")

    normalized = text.replace("，", ",").replace(" ", "").strip()
    if not normalized:
        raise SequenceError("请输入自定义序号，例如 264513 或 2,6,4,5,1,3。")

    if "," in normalized:
        tokens = [token for token in normalized.split(",") if token]
        if any(not token.isdigit() for token in tokens):
            raise SequenceError("序号只能包含数字，例如 2,6,4,5,1,3。")
        numbers = [int(token) for token in tokens]
    else:
        if not normalized.isdigit():
            raise SequenceError("序号只能包含数字，例如 264513。")
        numbers = [int(ch) for ch in normalized]

    if len(numbers) != count:
        raise SequenceError(f"序号数量必须与素材数量一致：需要 {count} 个，当前 {len(numbers)} 个。")

    expected = set(range(1, count + 1))
    if set(numbers) != expected:
        raise SequenceError(f"序号必须是 1..{count} 的不重复排列（不重不漏）。")

    return [number - 1 for number in numbers]


@dataclass(frozen=True, slots=True)
class CompositionPlan:
    """按最终顺序排列好的编排计划。"""

    assets: tuple[MediaAsset, ...]
    mode: OrderMode
    seed: int | None = None
    transition_seconds: float = 0.0

    @property
    def total_duration(self) -> float:
        duration = sum(asset.duration for asset in self.assets)
        if len(self.assets) > 1 and self.transition_seconds > 0:
            duration -= self.transition_seconds * (len(self.assets) - 1)
        return max(0.0, duration)

    @property
    def raw_duration(self) -> float:
        return sum(asset.duration for asset in self.assets)

    @property
    def has_audio(self) -> bool:
        return any(asset.has_audio for asset in self.assets)

    @property
    def sequence(self) -> tuple[int, ...]:
        return tuple(asset.sequence_index if asset.sequence_index is not None else 0 for asset in self.assets)


def normalize_assets(assets: list[MediaAsset] | tuple[MediaAsset, ...]) -> list[MediaAsset]:
    """按序号 → 路径（忽略大小写）→ ID 排序，规范化输入顺序。"""
    return sorted(
        assets,
        key=lambda asset: (
            asset.sequence_index if asset.sequence_index is not None else math.inf,
            str(asset.path).casefold(),
            asset.asset_id,
        ),
    )


def has_duplicate_sequence_indices(assets: list[MediaAsset] | tuple[MediaAsset, ...]) -> bool:
    """判断素材之间是否存在重复序号。"""
    seen: set[int] = set()
    for asset in assets:
        index = asset.sequence_index
        if index is None:
            continue
        if index in seen:
            return True
        seen.add(index)
    return False


def duplicate_sequence_indices(assets: list[MediaAsset] | tuple[MediaAsset, ...]) -> set[int]:
    """返回出现次数超过一次的序号集合。"""
    counts: dict[int, int] = {}
    for asset in assets:
        index = asset.sequence_index
        if index is None:
            continue
        counts[index] = counts.get(index, 0) + 1
    return {index for index, count in counts.items() if count > 1}


def shuffle_with_seed(assets: list[MediaAsset] | tuple[MediaAsset, ...], seed: int, attempt: int = 0) -> list[MediaAsset]:
    """以种子派生的独立随机源做 Fisher–Yates 洗牌。"""
    generator = DeterministicRandom.from_branch(seed, attempt)
    shuffled = list(assets)
    for index in range(len(shuffled) - 1, 0, -1):
        target = generator.next_int(index + 1)
        shuffled[index], shuffled[target] = shuffled[target], shuffled[index]
    return shuffled


def _factorial_space(count: int) -> int:
    if count > 20:
        return (1 << 63) - 1
    return math.factorial(count)


def plan_custom(
    assets: list[MediaAsset] | tuple[MediaAsset, ...],
    indices: list[int] | tuple[int, ...],
    transition_seconds: float = 0.0,
) -> CompositionPlan:
    """按 1 基序号列表生成自定义计划（允许重复序号）。

    序号通过素材的文件名序号匹配；匹配不到的序号会抛出 ``SequenceError``。
    """
    if not assets:
        raise SequenceError("素材列表不能为空。")
    if not indices:
        raise SequenceError("序号列表不能为空。")

    index_map: dict[int, MediaAsset] = {}
    for asset in assets:
        if asset.sequence_index is not None:
            index_map.setdefault(asset.sequence_index, asset)

    position_map = {position + 1: asset for position, asset in enumerate(assets)}

    selected: list[MediaAsset] = []
    for position, index in enumerate(indices):
        asset = index_map.get(index)
        if asset is None and not index_map:
            asset = position_map.get(index)
        if asset is None:
            raise SequenceError(f"序号 {index}（第 {position + 1} 项）在素材列表中不存在。")
        selected.append(asset)

    error = validate_transitions(selected, transition_seconds)
    if error is not None:
        raise SequenceError(error)

    return CompositionPlan(
        assets=tuple(selected),
        mode=OrderMode.CUSTOM,
        seed=None,
        transition_seconds=transition_seconds,
    )


def plan_random_batch(
    assets: list[MediaAsset] | tuple[MediaAsset, ...],
    count: int,
    seed: int,
    *,
    transition_seconds: float = 0.0,
    clips_per_plan: int | None = None,
) -> list[CompositionPlan]:
    """生成批量随机计划：同一种子可复现，排列空间未耗尽前避免重复顺序。"""
    if not assets:
        raise SequenceError("素材列表不能为空。")
    if count <= 0:
        raise SequenceError("成片数量必须为正整数。")

    take_count = len(assets) if clips_per_plan is None else max(1, min(clips_per_plan, len(assets)))
    normalized = normalize_assets(assets)
    position_of = {id(asset): position for position, asset in enumerate(normalized)}
    factorial_space = _factorial_space(take_count)

    emitted_keys: set[str] = set()
    plans: list[CompositionPlan] = []
    attempt = 0

    while len(plans) < count:
        shuffled = shuffle_with_seed(normalized, seed, attempt)
        selected = shuffled[:take_count]
        key = ",".join(
            str(asset.sequence_index) if asset.sequence_index is not None else f"#{position_of[id(asset)]}"
            for asset in selected
        )

        if len(emitted_keys) < factorial_space and key in emitted_keys:
            attempt += 1
            if attempt > count * 100 + 10000:
                break
            continue

        emitted_keys.add(key)
        plans.append(
            CompositionPlan(
                assets=tuple(selected),
                mode=OrderMode.RANDOM,
                seed=seed,
                transition_seconds=transition_seconds,
            )
        )
        attempt += 1
        if attempt > count * 100 + 10000:
            break

    return plans


def validate_transitions(assets: list[MediaAsset] | tuple[MediaAsset, ...], transition_seconds: float) -> str | None:
    """校验转场时长不超过相邻片段较短时长；返回错误文本或 None。"""
    if transition_seconds <= 0 or len(assets) < 2:
        return None

    for index in range(len(assets) - 1):
        shorter = min(assets[index].duration, assets[index + 1].duration)
        if transition_seconds >= shorter:
            return (
                f"转场时长 {transition_seconds:.1f} 秒超过了相邻片段 "
                f"{assets[index].sequence_index} 和 {assets[index + 1].sequence_index} 的较短时长。"
            )
    return None


def plan_order(
    assets: list[MediaAsset],
    mode: OrderMode,
    *,
    seed: int | None = None,
    sequence_text: str = "",
) -> tuple[MediaAsset, ...]:
    """按模式生成最终素材顺序。随机模式在给定种子下可复现。"""
    if not assets:
        return ()

    if mode is OrderMode.SEQUENTIAL:
        return tuple(assets)

    if mode is OrderMode.RANDOM:
        plans = plan_random_batch(assets, 1, seed if seed is not None else 0)
        return plans[0].assets

    indices = parse_sequence(sequence_text, len(assets))
    return tuple(assets[index] for index in indices)


@dataclass(frozen=True, slots=True)
class CompositionPreviewPlan:
    """单条编排预览：序号链与预计时长。"""

    plan_number: int
    sequence: tuple[int, ...]
    duration: float


@dataclass(frozen=True, slots=True)
class CompositionPreviewResult:
    """编排校验与预览结果。"""

    can_enqueue: bool
    validation_message: str
    plans: tuple[CompositionPreviewPlan, ...]
    executable_plans: tuple[CompositionPlan, ...]


def to_preview(plan_number: int, plan: CompositionPlan) -> CompositionPreviewPlan:
    return CompositionPreviewPlan(plan_number=plan_number, sequence=plan.sequence, duration=plan.total_duration)
