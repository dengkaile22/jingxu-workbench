"""效果计划：上下双屏、2×2 四屏与拼接主素材增强。

所有随机素材与倍率都在入队时物化，保证渲染过程可复现。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from jingxu.domain.composition import CompositionPlan, normalize_assets
from jingxu.domain.deterministic import DeterministicRandom, select_index_with_reshuffled_cycles
from jingxu.domain.media import MediaAsset

DEFAULT_FEATHER_PIXELS = 48
MAX_FEATHER_PIXELS = 256

_AUX_BRANCH = 1501


class EffectPlanError(ValueError):
    """效果计划参数不合法。"""


def _same_asset(left: MediaAsset, right: MediaAsset) -> bool:
    if left.asset_id and right.asset_id:
        return left.asset_id == right.asset_id
    return str(left.path).casefold() == str(right.path).casefold()


def _same_file(left: MediaAsset, right: MediaAsset) -> bool:
    try:
        return Path(left.path).resolve() == Path(right.path).resolve()
    except OSError:
        return str(left.path).casefold() == str(right.path).casefold()


class DoubleScreenSourceMode(str, Enum):
    """双屏辅助素材来源。"""

    CURRENT_CLIP = "current_clip"
    RANDOM_CURRENT_FOLDER = "random_current_folder"


class DoubleScreenPlacement(str, Enum):
    """双屏覆盖位置。"""

    TOP = "top"
    BOTTOM = "bottom"


class DoubleScreenPlacementMode(str, Enum):
    """双屏覆盖位置模式。"""

    TOP = "top"
    BOTTOM = "bottom"
    RANDOM = "random"


@dataclass(frozen=True, slots=True)
class DoubleScreenClipSelection:
    """单个片段的双屏辅助素材与覆盖位置。"""

    clip_index: int
    source_asset: MediaAsset
    placement: DoubleScreenPlacement


@dataclass(frozen=True, slots=True)
class DoubleScreenEffectPlan:
    """上下双屏：从指定片段开始应用到结尾，随机素材在入队时固定。"""

    start_clip_index: int = 1
    source_mode: DoubleScreenSourceMode = DoubleScreenSourceMode.CURRENT_CLIP
    placement_mode: DoubleScreenPlacementMode = DoubleScreenPlacementMode.RANDOM
    feather_enabled: bool = True
    feather_pixels: int = DEFAULT_FEATHER_PIXELS
    clip_selections: tuple[DoubleScreenClipSelection, ...] = ()

    def __post_init__(self) -> None:
        if self.start_clip_index < 1:
            raise EffectPlanError("双屏起始视频必须从 1 开始。")
        if self.feather_pixels < 0 or self.feather_pixels > MAX_FEATHER_PIXELS:
            raise EffectPlanError(f"双屏羽化宽度必须在 0 到 {MAX_FEATHER_PIXELS} 像素之间。")

    def applies_to(self, zero_based_clip_index: int) -> bool:
        return zero_based_clip_index >= 0 and zero_based_clip_index + 1 >= self.start_clip_index

    def selection_for(self, zero_based_clip_index: int) -> DoubleScreenClipSelection | None:
        for selection in self.clip_selections:
            if selection.clip_index == zero_based_clip_index:
                return selection
        return None

    def materialize_for_plan(
        self,
        plan: CompositionPlan,
        current_folder_assets: list[MediaAsset] | tuple[MediaAsset, ...],
        plan_index: int,
    ) -> DoubleScreenEffectPlan:
        """按素材文件夹与成片序号生成确定性的随机辅助素材快照。"""
        if self.source_mode is not DoubleScreenSourceMode.RANDOM_CURRENT_FOLDER:
            return replace(self, clip_selections=())

        if not current_folder_assets:
            raise EffectPlanError("双屏随机素材需要当前文件夹中至少有一个视频素材。")

        normalized = normalize_assets(current_folder_assets)
        seed = plan.seed if plan.seed is not None else 0
        placement_random = DeterministicRandom(
            ((seed & 0xFFFFFFFF) * 0x9E3779B97F4A7C15)
            ^ ((plan_index * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1))
            ^ 0xD15EA5E5
        )
        selections: list[DoubleScreenClipSelection] = []

        for clip_index, asset in enumerate(plan.assets):
            if not self.applies_to(clip_index):
                continue

            candidates = [item for item in normalized if not _same_asset(item, asset)]
            if not candidates:
                candidates = normalized

            selection_ordinal = max(plan_index, 0) * max(len(plan.assets), 1) + clip_index
            source_index = select_index_with_reshuffled_cycles(
                len(candidates), seed, selection_ordinal, branch_index=_AUX_BRANCH
            )
            if self.placement_mode is DoubleScreenPlacementMode.TOP:
                placement = DoubleScreenPlacement.TOP
            elif self.placement_mode is DoubleScreenPlacementMode.BOTTOM:
                placement = DoubleScreenPlacement.BOTTOM
            else:
                placement = DoubleScreenPlacement.TOP if placement_random.next_int(2) == 0 else DoubleScreenPlacement.BOTTOM

            selections.append(
                DoubleScreenClipSelection(clip_index=clip_index, source_asset=candidates[source_index], placement=placement)
            )

        return replace(self, clip_selections=tuple(selections))


class FourScreenSourceMode(str, Enum):
    """四屏辅助素材来源。"""

    CURRENT_CLIP = "current_clip"
    RANDOM_CURRENT_FOLDER = "random_current_folder"


class FourScreenPosition(int, Enum):
    """四屏格位：左上、右上、左下、右下。"""

    TOP_LEFT = 0
    TOP_RIGHT = 1
    BOTTOM_LEFT = 2
    BOTTOM_RIGHT = 3


@dataclass(frozen=True, slots=True)
class FourScreenCellSelection:
    """四屏单格素材。"""

    position: FourScreenPosition
    source_asset: MediaAsset
    is_main: bool


@dataclass(frozen=True, slots=True)
class FourScreenClipSelection:
    """一个片段的四格素材快照。"""

    clip_index: int
    cells: tuple[FourScreenCellSelection, ...]


@dataclass(frozen=True, slots=True)
class FourScreenEffectPlan:
    """2×2 四屏：从指定片段至结尾，素材与位置在入队时固定。"""

    start_clip_index: int = 1
    source_mode: FourScreenSourceMode = FourScreenSourceMode.CURRENT_CLIP
    feather_enabled: bool = True
    feather_pixels: int = DEFAULT_FEATHER_PIXELS
    clip_selections: tuple[FourScreenClipSelection, ...] = ()

    def __post_init__(self) -> None:
        if self.start_clip_index < 1:
            raise EffectPlanError("四屏起始视频必须从 1 开始。")
        if self.feather_pixels < 0 or self.feather_pixels > MAX_FEATHER_PIXELS:
            raise EffectPlanError(f"四屏羽化宽度必须在 0 到 {MAX_FEATHER_PIXELS} 像素之间。")

    def applies_to(self, zero_based_clip_index: int) -> bool:
        return zero_based_clip_index >= 0 and zero_based_clip_index + 1 >= self.start_clip_index

    def selection_for(self, zero_based_clip_index: int) -> FourScreenClipSelection | None:
        for selection in self.clip_selections:
            if selection.clip_index == zero_based_clip_index:
                return selection
        return None

    def materialize_for_plan(
        self,
        plan: CompositionPlan,
        source_assets: list[MediaAsset] | tuple[MediaAsset, ...],
        plan_index: int,
    ) -> FourScreenEffectPlan:
        """固定每格素材与位置；随机模式下先按文件夹洗牌，再依次取用。"""
        if self.start_clip_index > len(plan.assets):
            raise EffectPlanError(f"四屏起始视频必须在 1 到 {len(plan.assets)} 之间。")
        if self.source_mode is FourScreenSourceMode.RANDOM_CURRENT_FOLDER and not source_assets:
            raise EffectPlanError("四屏随机素材需要已导入的素材池。")

        normalized = normalize_assets(source_assets)
        seen_paths: set[str] = set()
        unique: list[MediaAsset] = []
        for asset in normalized:
            key = str(Path(asset.path).resolve()).casefold()
            if key in seen_paths:
                continue
            seen_paths.add(key)
            unique.append(asset)

        seed = plan.seed if plan.seed is not None else 0
        selections: list[FourScreenClipSelection] = []

        for clip_index, main in enumerate(plan.assets):
            if not self.applies_to(clip_index):
                continue

            random = DeterministicRandom(
                ((seed & 0xFFFFFFFF) * 0x9E3779B97F4A7C15)
                ^ ((plan_index * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1))
                ^ ((clip_index * 0x1F123BB5) & ((1 << 64) - 1))
                ^ 0x4F555253
            )
            random_mode = self.source_mode is FourScreenSourceMode.RANDOM_CURRENT_FOLDER
            main_position = random.next_int(4) if random_mode else 0
            folder = str(Path(main.path).resolve().parent).casefold()
            candidates: list[MediaAsset] = []
            if random_mode:
                candidates = [
                    asset
                    for asset in unique
                    if not _same_asset(asset, main)
                    and str(Path(asset.path).resolve().parent).casefold() == folder
                ]

            for index in range(len(candidates) - 1, 0, -1):
                other = random.next_int(index + 1)
                candidates[index], candidates[other] = candidates[other], candidates[index]

            cells: list[FourScreenCellSelection] = []
            auxiliary_index = 0
            for position in range(4):
                is_main = position == main_position
                if is_main or not candidates:
                    source = main
                else:
                    source = candidates[auxiliary_index % len(candidates)]
                    auxiliary_index += 1
                cells.append(
                    FourScreenCellSelection(
                        position=FourScreenPosition(position),
                        source_asset=source,
                        is_main=is_main,
                    )
                )

            selections.append(FourScreenClipSelection(clip_index=clip_index, cells=tuple(cells)))

        return replace(self, clip_selections=tuple(selections))

    def validate_for_plan(self, plan: CompositionPlan) -> None:
        """校验快照完整；不合法时抛出 :class:`EffectPlanError`。"""
        error = "四屏素材快照不完整或无效，请重新入队后再开始渲染。"
        expected = len(plan.assets) - self.start_clip_index + 1
        if self.start_clip_index > len(plan.assets) or len(self.clip_selections) != expected:
            raise EffectPlanError(error)

        if len({selection.clip_index for selection in self.clip_selections}) != len(self.clip_selections):
            raise EffectPlanError(error)

        for selection in self.clip_selections:
            if not self.applies_to(selection.clip_index) or len(selection.cells) != 4:
                raise EffectPlanError(error)
            if len({cell.position for cell in selection.cells}) != 4:
                raise EffectPlanError(error)
            main_cells = [cell for cell in selection.cells if cell.is_main]
            if len(main_cells) != 1:
                raise EffectPlanError(error)

            main = plan.assets[selection.clip_index]
            if not _same_file(main_cells[0].source_asset, main):
                raise EffectPlanError(error)
            if self.source_mode is FourScreenSourceMode.CURRENT_CLIP and any(
                not _same_file(cell.source_asset, main) for cell in selection.cells
            ):
                raise EffectPlanError(error)


class MainMaterialBoostMode(str, Enum):
    """主素材增强模式：固定值或区间内随机。"""

    FIXED = "fixed"
    RANDOM = "random"


MIN_BOOST_PERCENT = 100.0
MAX_BOOST_PERCENT = 110.0


@dataclass(frozen=True, slots=True)
class MainMaterialBoostPlan:
    """拼接主素材的音量调大与缩放（100%–110%），仅作用于主轨。"""

    enable_volume: bool = False
    volume_mode: MainMaterialBoostMode = MainMaterialBoostMode.FIXED
    volume_min_percent: float = 105.0
    volume_max_percent: float = 105.0
    enable_scale: bool = False
    scale_mode: MainMaterialBoostMode = MainMaterialBoostMode.FIXED
    scale_min_percent: float = 105.0
    scale_max_percent: float = 105.0

    def __post_init__(self) -> None:
        if not self.enable_volume and not self.enable_scale:
            raise EffectPlanError("请至少启用音量或缩放之一。")
        _validate_boost_range(self.enable_volume, self.volume_mode, self.volume_min_percent, self.volume_max_percent, "音量")
        _validate_boost_range(self.enable_scale, self.scale_mode, self.scale_min_percent, self.scale_max_percent, "缩放")

    @property
    def is_active(self) -> bool:
        return self.enable_volume or self.enable_scale

    def materialize(self, seed: int, clip_count: int) -> MaterializedMainMaterialBoost:
        """按种子为每个主轨片段物化音量/缩放倍率（1.0–1.1）。"""
        if clip_count < 0:
            raise EffectPlanError("片段数量不能为负数。")

        volume_factors: list[float] = []
        scale_factors: list[float] = []
        for index in range(clip_count):
            volume_factors.append(
                _sample_factor(seed, 100, index, self.volume_mode, self.volume_min_percent, self.volume_max_percent)
                if self.enable_volume
                else 1.0
            )
            scale_factors.append(
                _sample_factor(seed, 200, index, self.scale_mode, self.scale_min_percent, self.scale_max_percent)
                if self.enable_scale
                else 1.0
            )

        return MaterializedMainMaterialBoost(
            enable_volume=self.enable_volume,
            enable_scale=self.enable_scale,
            volume_factors=tuple(volume_factors),
            scale_factors=tuple(scale_factors),
        )


@dataclass(frozen=True, slots=True)
class MaterializedMainMaterialBoost:
    """已按种子物化的主轨各片段倍率。"""

    enable_volume: bool
    enable_scale: bool
    volume_factors: tuple[float, ...]
    scale_factors: tuple[float, ...]

    @property
    def is_active(self) -> bool:
        return self.enable_volume or self.enable_scale

    @property
    def normalize_loudness(self) -> bool:
        return self.enable_volume


def _sample_factor(
    seed: int,
    branch_base: int,
    clip_index: int,
    mode: MainMaterialBoostMode,
    min_percent: float,
    max_percent: float,
) -> float:
    if mode is MainMaterialBoostMode.FIXED or abs(max_percent - min_percent) < 0.000001:
        return round(min_percent / 100.0, 6)

    generator = DeterministicRandom.from_branch(seed, branch_base + clip_index)
    percent = min_percent + (max_percent - min_percent) * generator.next_double()
    return round(percent / 100.0, 6)


def _validate_boost_range(
    enabled: bool,
    mode: MainMaterialBoostMode,
    min_percent: float,
    max_percent: float,
    label: str,
) -> None:
    if not enabled:
        return

    if mode is MainMaterialBoostMode.FIXED:
        if not (MIN_BOOST_PERCENT <= min_percent <= MAX_BOOST_PERCENT):
            raise EffectPlanError(
                f"拼接主素材{label}固定值必须在 {MIN_BOOST_PERCENT:g}%–{MAX_BOOST_PERCENT:g}% 之间。"
            )
        return

    if not (MIN_BOOST_PERCENT <= min_percent <= MAX_BOOST_PERCENT) or not (
        MIN_BOOST_PERCENT <= max_percent <= MAX_BOOST_PERCENT
    ):
        raise EffectPlanError(
            f"拼接主素材{label}随机区间必须在 {MIN_BOOST_PERCENT:g}%–{MAX_BOOST_PERCENT:g}% 之间。"
        )
    if min_percent > max_percent:
        raise EffectPlanError(f"拼接主素材{label}随机下限不能大于上限。")
