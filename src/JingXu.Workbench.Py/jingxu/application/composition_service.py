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
from jingxu.domain.layers import LayerKind, LayerSpec, imported_mask_layer
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
from jingxu.infrastructure.sticker_library import select_random_sticker


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
    # 「随机贴纸库」：开启后每条成片的贴纸轨道从素材库按种子确定性替换素材
    # （对齐 .NET StickerEditorViewModel.TryBuildEnabledTracksForPlan）。
    randomize_sticker_library: bool = False
    sticker_library: tuple[Path, ...] = ()
    # 「蒙版随机替换」：开启后每条成片只用 1 个库蒙版，套用当前蒙版轨道的画法
    # （对齐 .NET OverlayEditorViewModel.BuildLayersForPlan）。
    randomize_overlay_library: bool = False
    overlay_library: tuple[Path, ...] = ()


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
    library_ordinal: int = 0,
    library_selection_seed: int | None = None,
    reserved_paths: Sequence[Path] = (),
) -> list[RenderRequest]:
    """生成一批可入队的渲染请求。

    - 自定义序号：每条表达式产出一条成片，支持换行/分号分隔的多任务；
    - 随机批量：产出 ``batch_count`` 条，同一种子可复现且尽可能差异化；
    - ``clips_per_plan`` 为随机模式下的每片素材数，留空表示使用全部素材；
    - 双屏/四屏的随机辅助素材与主素材增强倍率在此物化，保证渲染可复现；
    - ``library_ordinal`` / ``library_selection_seed``：素材库随机替换的**全局**序号与
      固定种子（对齐 .NET ``_nextRandomMaskSelectionOrdinal`` + ``_randomLibrarySelectionSeed``）。
      序号跨多次入队累加，因此一轮内每条库素材只出现一次、相邻成片不重复。
      **不能**用逐条递增的 ``plan.seed``：那会让洗牌轮次从头开始，既破坏"一轮覆盖全部素材"，
      又可能让相邻成片拿到同一条。``library_selection_seed`` 省略时退回草稿种子（便于测试复现）。
    - ``reserved_paths``：**别处已占用**的输出路径（例如队列里尚未落盘的在前任务）。
      必须传进来一起比对，否则跨批次的同名请求会算到同一个文件名而互相覆盖。
    """
    if not assets:
        raise ValueError("没有可编排的素材。")

    plans = _build_plans(list(assets), draft)
    count = len(plans)
    prefix = draft.output_prefix.strip() or "混剪"
    directory = Path(output_directory)
    material_pool = list(pool) if pool else list(assets)
    selection_seed = (
        library_selection_seed
        if library_selection_seed is not None
        else (draft.seed if draft.seed is not None else 0)
    )

    requests: list[RenderRequest] = []
    # 本批次已分配的路径 + 调用方告知的在途路径，一起参与去重。
    # ``unique_output_path`` 默认只看磁盘上已存在的文件，而同一批次里的任务在入队时
    # 都还没落盘，于是「顺序拼接」与「随机批量」两次调用会各自算出同名文件，
    # 后渲染的任务把先渲染的**直接覆盖**（实测 5 条请求只产出 3 个文件）。
    allocated: list[Path] = [Path(path) for path in reserved_paths]
    for offset, plan in enumerate(plans):
        transition_error = validate_transition(plan, draft.settings.transition)
        if transition_error is not None:
            raise ValueError(transition_error)

        # 素材库选择序号是**全局**的：本次批次内递增，且承接上一批次的进度。
        selection_ordinal = library_ordinal + offset
        suffix = "" if count == 1 else f"_{offset + 1:03d}"
        output = unique_output_path(directory, f"{prefix}{suffix}", reserved_paths=allocated)
        allocated.append(output)
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
                layers=_materialize_overlay_library(
                    draft,
                    plan_index=selection_ordinal,
                    seed=selection_seed,
                ),
                subtitles=draft.subtitles,
                removal=draft.removal,
            )
        )

    return requests


def select_overlay_replacement(
    sources: Sequence[Path],
    *,
    seed: int,
    plan_ordinal: int,
) -> Path | None:
    """从蒙版素材库按任务种子确定性选取一条素材。

    逐行对齐 .NET ``OverlaySourceSelector.SelectReplacement``：先把库洗牌，
    再按**全局成片序号**逐项取用（``DeterministicShuffleCycle.SelectIndex``），
    因此一轮内每条素材只出现一次、相邻成片不会拿到同一条。
    库为空时返回 ``None``，由调用方决定是报错还是保持原样。
    """
    candidates = [Path(path) for path in sources if str(path)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    index = select_index_with_reshuffled_cycles(
        len(candidates),
        seed,
        max(0, plan_ordinal),
        branch_index=0,
    )
    return candidates[index % len(candidates)]


def materialize_overlay_library(
    draft: CompositionDraft,
    *,
    plan_index: int,
    seed: int,
) -> tuple[LayerSpec, ...]:
    """「蒙版随机替换」：每条成片只用 1 个库蒙版，沿用模板的画法。

    对齐 .NET ``OverlayEditorViewModel.BuildLayersForPlan``：

    * 未开启 → 原样返回全部图层；
    * 开启但库为空 → 原样返回（不静默清空用户的轨道）；
    * 开启 → 从库中选 1 条，套到**当前选中的外部蒙版轨道**上（没有则退回第一条
      非自叠影轨道）；若一条外部轨道都没有，就按 .NET 的导入默认值新建一条。

    **只替换素材，不动画法**（位置/尺寸/透明度/羽化/起始片段都沿用模板）。
    """
    layers = draft.layers
    if not draft.randomize_overlay_library:
        return layers

    chosen = select_overlay_replacement(draft.overlay_library, seed=seed, plan_ordinal=plan_index)
    if chosen is None:
        return layers

    external = [layer for layer in layers if layer.kind is LayerKind.OVERLAY and not layer.is_self_source]
    if external:
        template = external[0]
        replaced = [
            replace(layer, source=chosen) if layer.id == template.id else layer
            for layer in layers
        ]
        # .NET 在随机模式下只保留这一条蒙版，避免把库内蒙版继续叠加上去。
        return tuple(layer for layer in replaced if layer.id == template.id)

    return (imported_mask_layer(chosen),)


def _materialize_overlay_library(
    draft: CompositionDraft,
    *,
    plan_index: int,
    seed: int,
) -> tuple[LayerSpec, ...]:
    """蒙版图层入口：先按「随机替换」换素材，再按「随机贴纸库」换贴纸。

    两条链互相独立：蒙版随机替换只作用于蒙版轨道，贴纸随机库只作用于贴纸轨道，
    因此可以同时开启。``plan_index`` 是**全局**选择序号（见 ``build_requests``）。
    """
    layers = materialize_overlay_library(
        draft,
        plan_index=plan_index,
        seed=seed,
    )
    sticker_draft = replace(draft, layers=layers)
    return _materialize_sticker_library(sticker_draft, plan_index)


def _materialize_sticker_library(draft: CompositionDraft, plan_index: int) -> tuple[LayerSpec, ...]:
    """按「随机贴纸库」开关替换贴纸轨道的素材。

    只替换素材、不动画法（位置/尺寸/透明度/旋转沿用轨道设置），与 .NET
    「随机替换：每条成片从素材库选择 1 个，沿用当前轨道的画法」一致。

    选择走确定性洗牌：同一成片序号结果固定可复现，一个成片内多条轨道不重复。
    """
    layers = draft.layers
    if not draft.randomize_sticker_library:
        return layers
    sources = [Path(path) for path in draft.sticker_library if str(path)]
    if not sources:
        # 开启随机但库为空：不静默改变画法，交由界面提示用户（见 layer_page）。
        return layers

    sticker_indexes = [
        index for index, layer in enumerate(layers) if layer.kind is LayerKind.STICKER
    ]
    if not sticker_indexes:
        return layers

    seed = draft.seed if draft.seed is not None else 0
    replaced = list(layers)
    for position, layer_index in enumerate(sticker_indexes):
        chosen = select_random_sticker(
            sources,
            seed=seed,
            plan_ordinal=max(0, plan_index),
            track_index=position,
            track_count=len(sticker_indexes),
        )
        if chosen is not None:
            replaced[layer_index] = replace(layers[layer_index], source=chosen)
    return tuple(replaced)


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
