"""应用层：用例编排（素材 → 渲染请求，含批量差异化）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from jingxu.domain.composition import (
    CompositionPlan,
    CompositionPreviewPlan,
    CompositionPreviewResult,
    OrderMode,
    SequenceError,
    has_duplicate_sequence_indices,
    parse_expression,
    plan_custom,
    plan_order,
    plan_random_batch,
    split_expressions,
    to_preview,
    validate_transitions,
)
from jingxu.domain.deterministic import select_index_with_reshuffled_cycles
from jingxu.domain.effects import (
    DoubleScreenEffectPlan,
    FourScreenEffectPlan,
    MainMaterialBoostPlan,
)
from jingxu.domain.layers import LayerSpec
from jingxu.domain.media import MediaAsset
from jingxu.domain.render import (
    BgmSettings,
    BgmSource,
    CoverRequest,
    RenderRequest,
    RenderSettings,
    validate_transition,
)
from jingxu.domain.splitscreen import SplitScreenSpec
from jingxu.domain.subtitles import SubtitleBurnSpec, SubtitleRemovalSpec
from jingxu.infrastructure.paths import unique_output_path


@dataclass(frozen=True, slots=True)
class CompositionDraft:
    """界面上尚未入队的编排选择。"""

    mode: OrderMode = OrderMode.RANDOM
    seed: int | None = 2026
    sequence_text: str = ""
    settings: RenderSettings = RenderSettings()
    output_prefix: str = "混剪"
    batch_count: int = 1
    clips_per_plan: int | None = None
    bgm: BgmSettings | None = None
    bgm_source: BgmSource | None = None
    bgm_tracks: tuple[Path, ...] = ()
    cover_enabled: bool = False
    cover_at_seconds: float = 1.0
    split: SplitScreenSpec | None = None
    double_screen: DoubleScreenEffectPlan | None = None
    four_screen: FourScreenEffectPlan | None = None
    boost: MainMaterialBoostPlan | None = None
    layers: tuple[LayerSpec, ...] = ()
    subtitles: SubtitleBurnSpec | None = None
    removal: SubtitleRemovalSpec | None = None


def build_preview(
    assets: Sequence[MediaAsset],
    draft: CompositionDraft,
) -> CompositionPreviewResult:
    """生成编排预览与入队前校验（对齐 .NET CompositionOrchestrator.BuildPreview）。"""
    asset_list = list(assets)
    if not asset_list:
        return CompositionPreviewResult(False, "请先导入至少一个视频素材。", (), ())

    if has_duplicate_sequence_indices(asset_list):
        return CompositionPreviewResult(False, "存在重复序号，自定义序号拼接前请先处理重复项。", (), ())

    if draft.mode is OrderMode.RANDOM:
        if draft.batch_count <= 0:
            return CompositionPreviewResult(False, "批量数量必须为正整数。", (), ())
        if draft.clips_per_plan is not None and draft.clips_per_plan < 1:
            return CompositionPreviewResult(False, "每片素材数必须为正整数。", (), ())
        try:
            plans = plan_random_batch(
                asset_list,
                draft.batch_count,
                draft.seed if draft.seed is not None else 0,
                clips_per_plan=draft.clips_per_plan,
            )
        except SequenceError as error:
            return CompositionPreviewResult(False, str(error), (), ())
        previews = tuple(to_preview(index + 1, plan) for index, plan in enumerate(plans))
        return CompositionPreviewResult(True, "", previews, tuple(plans))

    if draft.mode is OrderMode.CUSTOM:
        expressions = split_expressions(draft.sequence_text)
        if not expressions:
            return CompositionPreviewResult(False, "序号表达式不能为空。", (), ())

        previews: list[CompositionPreviewPlan] = []
        plans: list[CompositionPlan] = []
        for expression in expressions:
            try:
                indices = parse_expression(expression)
                plan = plan_custom(asset_list, indices)
            except SequenceError as error:
                return CompositionPreviewResult(False, f"表达式「{expression}」：{error}", (), ())
            plans.append(plan)
            previews.append(to_preview(len(previews) + 1, plan))
        return CompositionPreviewResult(True, "", tuple(previews), tuple(plans))

    return CompositionPreviewResult(False, "未知编排模式。", (), ())


def build_plan(assets: Sequence[MediaAsset], draft: CompositionDraft, *, seed: int | None = None) -> CompositionPlan:
    """按草稿生成单条编排计划（含自定义序号校验）。"""
    ordered = plan_order(
        list(assets),
        draft.mode,
        seed=draft.seed if seed is None else seed,
        sequence_text=draft.sequence_text,
    )
    return CompositionPlan(assets=ordered, mode=draft.mode, seed=seed if seed is not None else draft.seed)


def build_requests(
    *,
    assets: Sequence[MediaAsset],
    draft: CompositionDraft,
    output_directory: Path,
    start_index: int = 1,
    pool: Sequence[MediaAsset] | None = None,
) -> list[RenderRequest]:
    """生成一批可入队的渲染请求。

    - 自定义序号：每条表达式产出一条成片，支持换行/分号分隔的多任务；
    - 随机批量：产出 ``batch_count`` 条，同一种子可复现且尽可能差异化；
    - ``clips_per_plan`` 为随机模式下的每片素材数，留空表示使用全部素材；
    - 双屏/四屏的随机辅助素材与主素材增强倍率在此物化，保证渲染可复现。
    """
    if not assets:
        raise ValueError("没有可编排的素材。")

    plans = _build_plans(list(assets), draft)
    count = len(plans)
    prefix = draft.output_prefix.strip() or "混剪"
    directory = Path(output_directory)
    material_pool = list(pool) if pool else list(assets)

    requests: list[RenderRequest] = []
    for offset, plan in enumerate(plans):
        transition_error = validate_transition(plan, draft.settings.transition)
        if transition_error is not None:
            raise ValueError(transition_error)

        suffix = "" if count == 1 else f"_{offset + 1:03d}"
        output = unique_output_path(directory, f"{prefix}{suffix}")
        cover = (
            CoverRequest(output_path=output.with_suffix(".jpg"), at_seconds=draft.cover_at_seconds)
            if draft.cover_enabled
            else None
        )
        requests.append(
            RenderRequest(
                name=f"{prefix} #{start_index + offset}",
                plan=plan,
                settings=replace(draft.settings),
                output_path=output,
                cover=cover,
                bgm=_resolve_bgm(draft, offset, plan.seed),
                split=draft.split,
                double_screen=_materialize_double(draft, plan, material_pool, offset),
                four_screen=_materialize_four(draft, plan, material_pool, offset),
                layers=draft.layers,
                subtitles=draft.subtitles,
                removal=draft.removal,
            )
        )

    return requests


def _materialize_double(
    draft: CompositionDraft,
    plan: CompositionPlan,
    pool: list[MediaAsset],
    plan_index: int,
) -> DoubleScreenEffectPlan | None:
    if draft.double_screen is None:
        return None
    try:
        return draft.double_screen.materialize_for_plan(plan, pool, plan_index)
    except Exception as error:  # noqa: BLE001 - 领域错误转为入队校验错误
        raise ValueError(str(error)) from error


def _materialize_four(
    draft: CompositionDraft,
    plan: CompositionPlan,
    pool: list[MediaAsset],
    plan_index: int,
) -> FourScreenEffectPlan | None:
    if draft.four_screen is None:
        return None
    try:
        return draft.four_screen.materialize_for_plan(plan, pool, plan_index)
    except Exception as error:  # noqa: BLE001 - 领域错误转为入队校验错误
        raise ValueError(str(error)) from error


def _build_plans(assets: list[MediaAsset], draft: CompositionDraft) -> list[CompositionPlan]:
    if draft.mode is OrderMode.CUSTOM:
        expressions = split_expressions(draft.sequence_text)
        if not expressions and draft.sequence_text.strip():
            expressions = [draft.sequence_text.strip()]
        if not expressions:
            raise ValueError("序号表达式不能为空。")

        plans: list[CompositionPlan] = []
        for expression in expressions:
            try:
                indices = parse_expression(expression)
                plans.append(plan_custom(assets, indices))
            except SequenceError as error:
                raise ValueError(f"表达式「{expression}」：{error}") from error
        return plans

    if draft.mode is OrderMode.RANDOM:
        count = max(1, draft.batch_count)
        base_seed = draft.seed if draft.seed is not None else 0
        plans = plan_random_batch(
            assets,
            count,
            base_seed,
            clips_per_plan=draft.clips_per_plan,
        )
        # 每条成片使用递增种子，保证差异化滤镜与音乐抽取互不相同。
        return [replace(plan, seed=base_seed + offset) for offset, plan in enumerate(plans)]

    return [CompositionPlan(assets=tuple(assets), mode=OrderMode.SEQUENTIAL, seed=draft.seed)]


def _resolve_bgm(draft: CompositionDraft, offset: int, seed: int | None) -> BgmSettings | None:
    """按草稿决定本条成片的 BGM（单文件直用；音频库按种子随机抽取）。"""
    if draft.bgm is not None:
        return draft.bgm
    source = draft.bgm_source
    if source is None:
        return None

    path: Path | None = source.path
    if source.kind == "library":
        if not draft.bgm_tracks:
            return None
        path = _pick_library_track(draft.bgm_tracks, seed, offset)
        if path is None:
            return None

    if path is None or not Path(path).is_file():
        return None

    return BgmSettings(
        path=Path(path),
        volume_gain=source.resolved_gain(offset),
        fade_out_seconds=source.fade_out_seconds,
        loop=source.loop,
    )


def _pick_library_track(tracks: Sequence[Path], seed: int | None, ordinal: int, attempts: int = 5) -> Path | None:
    """按确定性随机袋抽取音频库曲目，跳过已被删除的文件（最多尝试 5 次）。"""
    candidates = list(tracks)
    if not candidates:
        return None

    base_seed = seed if seed is not None else 0
    for attempt in range(min(attempts, len(candidates))):
        position = select_index_with_reshuffled_cycles(
            len(candidates),
            base_seed,
            ordinal + attempt,
            branch_index=3,
        )
        path = candidates[position]
        if Path(path).is_file():
            return path
    return None
