"""滤镜图编译：画幅适配、双屏/四屏、图层叠加、音频混合与 concat。

对齐 .NET 版 ``FfmpegCommandCompiler`` / ``OverlayFilterCompiler`` /
``FourScreenFilterCompiler`` 的滤镜语义；随机素材与倍率已在入队时物化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jingxu.domain.composition import CompositionPlan
from jingxu.domain.effects import (
    DoubleScreenClipSelection,
    DoubleScreenEffectPlan,
    DoubleScreenPlacement,
    FourScreenEffectPlan,
    FourScreenPosition,
    MaterializedMainMaterialBoost,
)
from jingxu.domain.layers import LayerSpec
from jingxu.domain.render import (
    BgmSettings,
    FitMode,
    RenderSettings,
    VariationSettings,
    validate_transition,
)
from jingxu.domain.splitscreen import SplitMode, SplitScreenSpec
from jingxu.domain.subtitles import RemovalMode, SubtitleRemovalSpec
from jingxu.infrastructure.subtitles import escape_filter_path

SAMPLE_RATE = 48000
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
SELF_SOURCE = ":self:"


@dataclass(frozen=True, slots=True)
class ExtraInput:
    """滤镜图需要的额外输入（按引用顺序追加在素材输入之后）。"""

    path: Path
    loop: bool
    purpose: str


@dataclass(frozen=True, slots=True)
class FilterGraph:
    script: str
    has_audio: bool
    extra_inputs: tuple[ExtraInput, ...] = field(default_factory=tuple)
    video_label: str = "vout"
    audio_label: str = "aout"


def _even(value: float) -> int:
    number = int(round(value))
    return number if number % 2 == 0 else number - 1


def _decimal(value: float) -> str:
    """格式化小数：最多 6 位并去掉多余零（对齐 .NET FormatDecimal）。"""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _seconds(value: float) -> str:
    return f"{max(value, 0.0):.3f}"


def _source_crop_filters(layer: LayerSpec, settings: RenderSettings) -> str:
    """源素材取景裁剪：人工框选优先，否则按成片画幅比例中心裁切。"""
    if layer.source_crop_bounds is not None:
        x, y, width, height = (max(0.0, min(value, 1.0)) for value in layer.source_crop_bounds)
        return (
            f"crop=w='max(2\\,trunc(iw*{_decimal(width)}/2)*2)'"
            f":h='max(2\\,trunc(ih*{_decimal(height)}/2)*2)'"
            f":x='trunc(min(iw-ow\\,iw*{_decimal(x)})/2)*2'"
            f":y='trunc(min(ih-oh\\,ih*{_decimal(y)})/2)*2'"
        )
    if layer.source_crop_canvas:
        bias = max(-1.0, min(layer.source_crop_y, 1.0))
        return (
            f"crop=w='min(iw\\,ih*{settings.width}/{settings.height})'"
            f":h='min(ih\\,iw*{settings.height}/{settings.width})'"
            f":x='(iw-ow)/2'"
            f":y='(ih-oh)/2*(1+{_decimal(bias)})'"
        )
    return ""


def _layer_fit_filters(layer: LayerSpec, settings: RenderSettings, width: int, height_limit: int) -> str:
    """按蒙版适配方式生成缩放链；高度上限始终生效（对齐 .NET 的 Bounds 派生）。"""
    fit = (layer.fit or "fill_crop").lower()
    if fit == "contain":
        width = width - (width % 2)
        chain = (
            f"scale={width}:-2:force_original_aspect_ratio=decrease,"
            f"pad={width}:{max(2, height_limit) if height_limit else 'ih'}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
        )
    elif fit == "stretch":
        chain = f"scale={width}:-2"
    elif fit == "match_canvas_crop":
        width = width - (width % 2)
        chain = (
            f"crop=w='min(iw\\,ih*{settings.width}/{settings.height})'"
            f":h='min(ih\\,iw*{settings.height}/{settings.width})'"
            f":x='(iw-ow)/2':y='(ih-oh)/2*(1+{_decimal(max(-1.0, min(layer.source_crop_y, 1.0)))})',"
            f"scale={width}:-2"
        )
    else:  # fill_crop（默认）
        chain = f"scale={width}:-2"

    if height_limit > 0:
        chain += f",crop=iw:'min(ih,{height_limit})':0:'(ih-oh)/2'"
    return chain


def _feather_sigma(feather: float, width: int) -> int:
    """羽化高斯半径：按图层宽度线性缩放并限制 1..8。

    .NET 使用 min(宽,高)，但图层高度在编译期未知（``scale=-2`` 保持比例），
    因此以宽度为准；高度上限开启时用其近似。
    """
    if feather <= 0.0 or width <= 0:
        return 0
    scaled = int(round(max(0.0, min(feather, 1.0)) * width * 0.015))
    return max(1, min(scaled, 8))


def _alpha_envelope(
    input_label: str,
    output_label: str,
    layer: LayerSpec,
    width: int,
) -> str:
    """在 alpha 平面应用顶部渐变、底边线性羽化与边缘柔化（对齐 .NET）。"""
    factors: list[str] = []
    if layer.top_fade > 0.0:
        fade = max(0.0, min(layer.top_fade, 1.0))
        factors.append(f"min(1,Y/(H*{_decimal(fade)}))")
    if layer.feather > 0.0:
        band = max(0.0, min(layer.feather, 1.0))
        factors.append(f"min(1,max(0,(H-Y)/(H*{_decimal(band)}+0.000001)))")
    multiplier = "*".join(factors) if factors else "1"
    sigma = _feather_sigma(layer.feather, width)
    blur = f",gblur=sigma={sigma}" if sigma > 0 else ""
    rgb_label = f"{output_label}rgb"
    alpha_in = f"{output_label}ain"
    alpha_out = f"{output_label}aout"
    return (
        f"[{input_label}]split=2[{rgb_label}][{alpha_in}];"
        f"[{alpha_in}]alphaextract,geq=lum='lum(X,Y)*{multiplier}'{blur}[{alpha_out}];"
        f"[{rgb_label}][{alpha_out}]alphamerge[{output_label}]"
    )


def _cell_grid(mode: SplitMode) -> tuple[int, int]:
    if mode is SplitMode.FOUR:
        return 2, 2
    if mode is SplitMode.DOUBLE_H:
        return 2, 1
    return 1, 2


def _base_chain(label: str, settings: RenderSettings, token: str) -> str:
    width, height = settings.width, settings.height
    tail = f"setsar=1,fps={_decimal(settings.fps)},format=yuv420p,setpts=PTS-STARTPTS"
    if settings.fit_mode is FitMode.CROP:
        core = (
            f"{label}scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},{tail}"
        )
    elif settings.fit_mode is FitMode.STRETCH:
        core = f"{label}scale={width}:{height},{tail}"
    elif settings.fit_mode is FitMode.BLUR:
        core = (
            f"{label}split[{token}bg][{token}fg];"
            f"[{token}bg]scale={width}:{height},boxblur=20:1[{token}blur];"
            f"[{token}fg]scale={width}:{height}:force_original_aspect_ratio=decrease[{token}fit];"
            f"[{token}blur][{token}fit]overlay=(W-w)/2:(H-h)/2,{tail}"
        )
    else:
        core = (
            f"{label}scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,{tail}"
        )
    return core


def _variation_chain(index: int, seed: int | None, variation: VariationSettings | None) -> str | None:
    """差异化滤镜：按请求种子与片段序号做可复现的小幅变化（对齐 .NET 滤镜集合）。"""
    if variation is None or not variation.enabled:
        return None

    level = max(0.0, min(float(variation.intensity), 200.0)) / 100.0
    generator = _variation_random(seed, index)
    steps: list[str] = []

    if variation.mirror:
        steps.append("hflip" if generator.random() < 0.5 else "vflip")
    if variation.rotate and abs(variation.rotation_max_degrees) > 0.0:
        degrees = generator.uniform(-variation.rotation_max_degrees, variation.rotation_max_degrees) * level
        if abs(degrees) >= 0.05:
            import math

            radians = degrees * math.pi / 180.0
            steps.append(f"rotate={radians:.6f}:ow=iw:oh=ih:c=black")
    if variation.light_crop:
        keep = 1.0 - (0.02 + 0.03 * level)
        steps.append(f"crop=iw*{keep:.4f}:ih*{keep:.4f}:(iw-ow)/2:(ih-oh)/2")
    if variation.color:
        brightness = round(generator.uniform(-0.02, 0.02) * level, 3)
        contrast = round(1.0 + generator.uniform(-0.04, 0.04) * level, 3)
        saturation = round(1.0 + generator.uniform(0.0, 0.08) * level, 3)
        steps.append(f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation}")
    if variation.denoise:
        strength = round(1.0 + 2.0 * level, 3)
        steps.append(f"hqdn3d={strength}:{strength}:{strength}")

    return ",".join(steps) if steps else None


def _variation_random(seed: int | None, index: int):
    from jingxu.domain.deterministic import DeterministicRandom

    return DeterministicRandom.from_branch(seed if seed is not None else 0, 5000 + index)


def _cell_chain(label: str, width: int, height: int, fps: float, *, duration: float | None) -> str:
    trim = f"trim=duration={_seconds(duration)}," if duration is not None else ""
    return (
        f"{label}{trim}scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={_decimal(fps)},format=yuv420p,setpts=PTS-STARTPTS"
    )


def _audio_chain(
    index: int,
    asset,
    duration: float,
    *,
    volume_factor: float = 1.0,
    normalize_loudness: bool = False,
) -> str:
    steps = [
        f"aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo",
        f"aresample={SAMPLE_RATE}",
    ]
    if normalize_loudness:
        steps.append(LOUDNORM)
    if abs(volume_factor - 1.0) > 1e-6:
        steps.append(f"volume={volume_factor:.6f}")
    steps.append(f"atrim=duration={_seconds(duration)}")
    steps.append("asetpts=PTS-STARTPTS")
    return f"[{index}:a]{','.join(steps)}[a{index}]"


def _silence_chain(index: int, duration: float) -> str:
    return (
        f"anullsrc=channel_layout=stereo:sample_rate={SAMPLE_RATE},"
        f"atrim=duration={_seconds(duration)},asetpts=PTS-STARTPTS[a{index}]"
    )


def _feather_pixels(first: int, second: int, requested: int) -> int:
    return max(0, min(requested, min(first, second) // 3))


def _append_feather_mask(
    lines: list[str],
    source_label: str,
    output_label: str,
    mask_width: int,
    mask_height: int,
    axis: str,
    end: int,
    feather_width: int,
    fps: float,
) -> None:
    """生成与时间无关的灰度渐变蒙版；alphamerge 复用末帧，由主视频决定时长。"""
    lines.append(
        f"nullsrc=size={mask_width}x{mask_height}:rate={_decimal(fps)},format=gray,trim=end_frame=1,"
        f"geq=lum='255*clip(({end}-{axis})/{feather_width},0,1)'[{output_label}mask]"
    )
    lines.append(f"[{source_label}]format=rgba[{output_label}rgba]")
    lines.append(
        f"[{output_label}rgba][{output_label}mask]"
        f"alphamerge=eof_action=repeat:repeatlast=1[{output_label}]"
    )


def _double_screen_chain(
    index: int,
    settings: RenderSettings,
    effect: DoubleScreenEffectPlan,
    selection: DoubleScreenClipSelection | None,
    aux_label: str | None,
    duration: float,
    fps: float,
) -> list[str]:
    """上下双屏：主素材占一半画幅，辅助素材或同源画面占另一半，中缝可羽化。

    两块画面先各自补齐到整幅画布，再做叠加；羽化时把「上方那一块」按
    中缝位置做 alpha 渐变后叠在下方块之上（对齐 .NET 的互补渐变）。
    """
    width, height = settings.width, settings.height
    top_height = height // 2
    bottom_height = height - top_height
    lines: list[str] = []
    prefix = f"d{index}"

    aux_on_top = selection is not None and selection.placement is DoubleScreenPlacement.TOP
    main_height = bottom_height if aux_on_top else top_height
    main_y = top_height if aux_on_top else 0

    # 主素材：先适配整幅画布，再裁剪到所属半屏。
    lines.append(
        f"[v{index}fit]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{main_height}:0:{main_y},setsar=1[{prefix}main]"
    )

    # 辅助素材：外部输入适配半屏；同源模式下复用当前片段。
    if aux_label is not None:
        aux_height = top_height if aux_on_top else bottom_height
        aux_y = 0 if aux_on_top else top_height
        lines.append(
            f"[{aux_label}]fps={_decimal(fps)},trim=duration={_seconds(duration)},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{aux_height}:0:{aux_y},setsar=1[{prefix}aux]"
        )
    else:
        aux_height = top_height if aux_on_top else bottom_height
        source_y = 0 if aux_on_top else top_height
        lines.append(
            f"[v{index}fit]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{aux_height}:0:{source_y},setsar=1[{prefix}aux]"
        )

    if aux_on_top:
        top_piece, top_y = f"{prefix}aux", 0
        bottom_piece, bottom_y = f"{prefix}main", main_y
    else:
        top_piece, top_y = f"{prefix}main", main_y
        bottom_piece, bottom_y = f"{prefix}aux", top_height

    lines.append(f"[{bottom_piece}]pad={width}:{height}:0:{bottom_y}:color=black[{prefix}base]")
    lines.append(f"[{top_piece}]pad={width}:{height}:0:{top_y}:color=black[{prefix}top]")

    blend = _feather_pixels(top_height, bottom_height, effect.feather_pixels) if effect.feather_enabled else 0
    if blend <= 0:
        lines.append(
            f"[{prefix}base][{prefix}top]overlay=0:0:format=rgb,setpts=PTS-STARTPTS[v{index}]"
        )
        return lines

    _append_feather_mask(
        lines,
        f"{prefix}top",
        f"{prefix}fade",
        width,
        height,
        "Y",
        top_height + blend,
        blend * 2,
        fps,
    )
    lines.append(f"[{prefix}base][{prefix}fade]overlay=0:0:format=rgb,setpts=PTS-STARTPTS[v{index}]")
    return lines


def _four_screen_chain(
    lines: list[str],
    index: int,
    settings: RenderSettings,
    effect: FourScreenEffectPlan,
    aux_labels: dict[FourScreenPosition, str],
    duration: float,
    fps: float,
) -> str:
    """2×2 四屏：同源同尺寸先缩放一次再分流，中缝灰度渐变互补混合（对齐 .NET）。"""
    selection = effect.selection_for(index)
    if selection is None:
        return f"[v{index}fit]null[v{index}]"

    prefix = f"fs{index}"
    target_width, target_height = settings.width, settings.height
    left_width = target_width // 2
    right_width = target_width - left_width
    top_height = target_height // 2
    bottom_height = target_height - top_height
    blend_x = _feather_pixels(left_width, right_width, effect.feather_pixels) if effect.feather_enabled else 0
    blend_y = _feather_pixels(top_height, bottom_height, effect.feather_pixels) if effect.feather_enabled else 0

    cells = sorted(selection.cells, key=lambda cell: int(cell.position))
    duration_text = _seconds(duration)

    # 相同来源（外部素材路径或主素材）合并分组，避免重复变换。
    groups: dict[str, list] = {}
    for cell in cells:
        label = aux_labels.get(cell.position)
        key = str(cell.source_asset.path).casefold() if label else ""
        groups.setdefault(key, []).append(cell)

    for key, source_cells in groups.items():
        first_label = aux_labels.get(source_cells[0].position)
        source_label = f"{prefix}source{int(source_cells[0].position)}" if first_label else f"v{index}fit"
        if first_label is not None:
            lines.append(
                f"[{first_label}]fps={_decimal(fps)},trim=duration={duration_text},setpts=PTS-STARTPTS,"
                f"setsar=1[{source_label}]"
            )

        sizes: dict[tuple[int, int], list] = {}
        for cell in source_cells:
            cell_width = (left_width if int(cell.position) % 2 == 0 else right_width) + blend_x
            cell_height = (top_height if int(cell.position) < 2 else bottom_height) + blend_y
            sizes.setdefault((cell_width, cell_height), []).append(cell)

        if len(sizes) > 1:
            labels = "".join(f"[{prefix}size{int(size[0].position)}]" for size in sizes.values())
            lines.append(f"[{source_label}]split={len(sizes)}{labels}")

        for (cell_width, cell_height), resized in sizes.items():
            source = source_label if len(sizes) == 1 else f"{prefix}size{int(resized[0].position)}"
            chain = (
                f"[{source}]format=rgba,"
                f"scale={cell_width}:{cell_height}:force_original_aspect_ratio=increase,"
                f"format=rgba,crop={cell_width}:{cell_height}:(iw-ow)/2:(ih-oh)/2,setsar=1"
            )
            if len(resized) > 1:
                chain += f",split={len(resized)}"
            for cell in resized:
                chain += f"[{prefix}cell{int(cell.position)}]"
            lines.append(chain)

    if blend_x == 0 and blend_y == 0:
        return (
            f"[{prefix}cell0][{prefix}cell1][{prefix}cell2][{prefix}cell3]"
            f"xstack=inputs=4:layout=0_0|{left_width}_0|0_{top_height}|{left_width}_{top_height}:shortest=1,"
            f"format=yuv420p,setpts=PTS-STARTPTS[v{index}]"
        )

    for row in range(2):
        if blend_x == 0:
            lines.append(
                f"[{prefix}cell{row * 2}][{prefix}cell{row * 2 + 1}]"
                f"hstack=inputs=2:shortest=1[{prefix}row{row}]"
            )
            continue

        row_height = (top_height if row == 0 else bottom_height) + blend_y
        lines.append(
            f"[{prefix}cell{row * 2 + 1}]pad={target_width}:{row_height}:"
            f"{left_width - blend_x}:0:color=black[{prefix}row{row}base]"
        )
        _append_feather_mask(
            lines,
            f"{prefix}cell{row * 2}",
            f"{prefix}row{row}fade",
            left_width + blend_x,
            row_height,
            "X",
            left_width + blend_x,
            blend_x * 2,
            fps,
        )
        lines.append(
            f"[{prefix}row{row}base][{prefix}row{row}fade]overlay=0:0:format=rgb:shortest=1[{prefix}row{row}]"
        )

    if blend_y == 0:
        return (
            f"[{prefix}row0][{prefix}row1]vstack=inputs=2:shortest=1,format=yuv420p,"
            f"setpts=PTS-STARTPTS[v{index}]"
        )

    lines.append(
        f"[{prefix}row1]format=rgba,pad={target_width}:{target_height}:0:{top_height - blend_y}:"
        f"color=black[{prefix}base]"
    )
    _append_feather_mask(
        lines,
        f"{prefix}row0",
        f"{prefix}topfade",
        target_width,
        top_height + blend_y,
        "Y",
        top_height + blend_y,
        blend_y * 2,
        fps,
    )
    return (
        f"[{prefix}base][{prefix}topfade]overlay=0:0:format=rgb:shortest=1,format=yuv420p,"
        f"setpts=PTS-STARTPTS[v{index}]"
    )


def _clip_start_seconds(plan: CompositionPlan, one_based_index: int) -> float:
    """返回第 N 个片段在成片时间轴上的起点（1 基，对齐 .NET StartClipIndex）。"""
    if one_based_index <= 1 or not plan.assets:
        return 0.0
    total = 0.0
    for index, asset in enumerate(plan.assets):
        if index + 1 >= one_based_index:
            break
        total += asset.duration
    return max(0.0, total)


def build_filter_graph(
    plan: CompositionPlan,
    settings: RenderSettings,
    *,
    split: SplitScreenSpec | None = None,
    layers: tuple[LayerSpec, ...] = (),
    bgm: BgmSettings | None = None,
    gradient_path: Path | None = None,
    removal: SubtitleRemovalSpec | None = None,
    subtitle_path: Path | None = None,
    boost: MaterializedMainMaterialBoost | None = None,
    double_screen: DoubleScreenEffectPlan | None = None,
    four_screen: FourScreenEffectPlan | None = None,
) -> FilterGraph:
    """把编排计划编译为 ``-filter_complex_script`` 脚本文本。"""
    if not plan.assets:
        raise ValueError("编排计划为空，无法编译滤镜图。")

    lines: list[str] = []
    extra_inputs: list[ExtraInput] = []
    base_index = len(plan.assets)

    active_layers = sorted(
        (layer for layer in layers if layer.enabled),
        key=lambda layer: (layer.z_index, layer.display_name),
    )
    split_active = (
        split is not None
        and split.mode.cell_count > 1
        and split.start_index < len(plan.assets)
        and (split.same_source or bool(split.aux_paths))
    )

    # ── 额外输入登记：图层 → 四屏辅助素材 → 双屏辅助素材 → 分屏辅助 → 梯度 ──
    layer_inputs: list[tuple[LayerSpec, int | None]] = []
    for layer in active_layers:
        if str(layer.source) == SELF_SOURCE:
            layer_inputs.append((layer, None))
            continue
        layer_inputs.append((layer, base_index + len(extra_inputs)))
        extra_inputs.append(ExtraInput(path=layer.source, loop=True, purpose="layer"))

    four_aux_inputs: dict[tuple[int, int], int] = {}
    if four_screen is not None:
        for selection in sorted(four_screen.clip_selections, key=lambda item: item.clip_index):
            main = plan.assets[selection.clip_index] if 0 <= selection.clip_index < len(plan.assets) else None
            for cell in sorted(selection.cells, key=lambda item: int(item.position)):
                if main is not None and str(cell.source_asset.path).casefold() == str(main.path).casefold():
                    continue
                key = (selection.clip_index, int(cell.position))
                four_aux_inputs[key] = base_index + len(extra_inputs)
                extra_inputs.append(ExtraInput(path=cell.source_asset.path, loop=True, purpose="four-screen"))

    double_aux_inputs: dict[int, int] = {}
    if double_screen is not None and double_screen.clip_selections:
        for selection in sorted(double_screen.clip_selections, key=lambda item: item.clip_index):
            double_aux_inputs[selection.clip_index] = base_index + len(extra_inputs)
            extra_inputs.append(ExtraInput(path=selection.source_asset.path, loop=True, purpose="double-screen"))

    aux_input_index: dict[int, int] = {}
    if split_active and split is not None and not split.same_source:
        for aux_index in range(len(split.aux_paths)):
            aux_input_index[aux_index] = base_index + len(extra_inputs)
            extra_inputs.append(ExtraInput(path=split.aux_paths[aux_index], loop=True, purpose="aux"))

    gradient_index: int | None = None
    if split_active and split is not None and split.feather and gradient_path is not None:
        gradient_index = base_index + len(extra_inputs)
        extra_inputs.append(ExtraInput(path=gradient_path, loop=True, purpose="gradient"))

    # ── 使用次数统计（决定 split 复制数量）──────────────────────────────
    split_segments = [
        index
        for index in range(len(plan.assets))
        if split_active and split is not None and index >= split.start_index
    ] if split_active else []

    aux_usage: dict[int, int] = {}
    if split_active and split is not None and not split.same_source:
        for index in split_segments:
            for cell in range(1, split.cell_count):
                aux_index = (cell - 1) % len(split.aux_paths)
                aux_usage[aux_index] = aux_usage.get(aux_index, 0) + 1

    for aux_index, uses in aux_usage.items():
        labels = "".join(f"[aux{aux_index}_{use}]" for use in range(uses))
        lines.append(f"[{aux_input_index[aux_index]}:v]split={uses}{labels}")

    if split_active and split is not None and split.feather and gradient_index is not None:
        labels = "".join(f"[grad{use}]" for use in range(len(split_segments)))
        lines.append(f"[{gradient_index}:v]split={len(split_segments)}{labels}")

    # ── 逐片段视频链 ────────────────────────────────────────────────────
    aux_cursor: dict[int, int] = {}
    feather_cursor = 0
    has_original_audio = plan.has_audio

    for index, asset in enumerate(plan.assets):
        source_label = f"[{index}:v]"
        variation = _variation_chain(index, plan.seed, settings.variation)
        if variation:
            lines.append(f"{source_label}{variation}[v{index}_pre]")
            source_label = f"[v{index}_pre]"

        lines.append(_base_chain(source_label, settings, f"b{index}") + f"[v{index}_src]")

        scale_factor = 1.0
        volume_factor = 1.0
        normalize_loudness = False
        if boost is not None and boost.is_active:
            if index < len(boost.scale_factors):
                scale_factor = boost.scale_factors[index]
            if index < len(boost.volume_factors):
                volume_factor = boost.volume_factors[index]
            normalize_loudness = boost.normalize_loudness

        if abs(scale_factor - 1.0) > 1e-6:
            lines.append(
                f"[v{index}_src]scale=iw*{scale_factor:.6f}:ih*{scale_factor:.6f},"
                f"crop={settings.width}:{settings.height}:(iw-ow)/2:(ih-oh)/2,setsar=1[v{index}_boost]"
            )
            fitted_label = f"[v{index}_boost]"
        else:
            fitted_label = f"[v{index}_src]"

        double_applies = double_screen is not None and double_screen.applies_to(index)
        four_applies = four_screen is not None and four_screen.applies_to(index)

        if double_applies or four_applies:
            lines.append(f"{fitted_label}null[v{index}fit]")
        else:
            lines.append(f"{fitted_label}null[v{index}]")

        if double_applies and double_screen is not None:
            selection = double_screen.selection_for(index)
            aux_label = None
            if index in double_aux_inputs:
                aux_label = f"{double_aux_inputs[index]}:v"
            lines.extend(
                _double_screen_chain(index, settings, double_screen, selection, aux_label, asset.duration, settings.fps)
            )

        if four_applies and four_screen is not None:
            aux_labels = {
                position: f"{input_index}:v"
                for (clip_index, position_code), input_index in four_aux_inputs.items()
                if clip_index == index
                for position in (FourScreenPosition(position_code),)
            }
            lines.append(
                _four_screen_chain(
                    lines, index, settings, four_screen, aux_labels, asset.duration, settings.fps
                )
            )

        if split_active and split is not None and index >= split.start_index:
            columns, rows = _cell_grid(split.mode)
            cell_width = _even(settings.width / columns)
            cell_height = _even(settings.height / rows)
            cells = split.cell_count
            cell_labels: list[str] = []

            if split.same_source or not split.aux_paths:
                labels = "".join(f"[same{index}_{cell}]" for cell in range(cells))
                lines.append(f"[v{index}]split={cells}{labels}")
                for cell in range(cells):
                    lines.append(
                        _cell_chain(f"[same{index}_{cell}]", cell_width, cell_height, settings.fps, duration=None)
                        + f"[sc{index}_{cell}]"
                    )
                    cell_labels.append(f"[sc{index}_{cell}]")
            else:
                lines.append(
                    _cell_chain(f"[v{index}]", cell_width, cell_height, settings.fps, duration=None)
                    + f"[sc{index}_0]"
                )
                cell_labels.append(f"[sc{index}_0]")
                for cell in range(1, cells):
                    aux_index = (cell - 1) % len(split.aux_paths)
                    use = aux_cursor.get(aux_index, 0)
                    aux_cursor[aux_index] = use + 1
                    lines.append(
                        _cell_chain(
                            f"[aux{aux_index}_{use}]", cell_width, cell_height, settings.fps, duration=asset.duration
                        )
                        + f"[sc{index}_{cell}]"
                    )
                    cell_labels.append(f"[sc{index}_{cell}]")

            if split.mode is SplitMode.FOUR:
                layout = "xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0"
            elif split.mode is SplitMode.DOUBLE_H:
                layout = "hstack=inputs=2"
            else:
                layout = "vstack=inputs=2"
            lines.append("".join(cell_labels) + layout + f"[v{index}_comp]")

            if split.feather and gradient_index is not None:
                lines.append(f"[v{index}_comp][grad{feather_cursor}]overlay=0:0:shortest=1[v{index}]")
                feather_cursor += 1
            else:
                lines.append(f"[v{index}_comp]null[v{index}]")

        if has_original_audio or bgm is not None:
            if asset.has_audio:
                lines.append(
                    _audio_chain(
                        index,
                        asset,
                        asset.duration,
                        volume_factor=volume_factor,
                        normalize_loudness=normalize_loudness,
                    )
                )
            else:
                lines.append(_silence_chain(index, asset.duration))

    # ── 拼接：交叉转场（xfade/acrossfade）或硬切 concat ───────────────────
    has_audio = has_original_audio or bgm is not None
    transition = settings.transition
    transition_active = (
        transition is not None
        and transition.enabled
        and len(plan.assets) > 1
        and validate_transition(plan, transition) is None
        and min(asset.duration for asset in plan.assets) >= 0.04
    )

    if transition_active and transition is not None:
        duration = transition.duration_seconds
        video_accumulated = "v0"
        audio_accumulated = "a0"
        elapsed = plan.assets[0].duration
        for index in range(1, len(plan.assets)):
            offset = elapsed - duration
            video_target = f"vx{index}"
            lines.append(
                f"[{video_accumulated}][v{index}]xfade=transition=fade:"
                f"duration={duration:.3f}:offset={offset:.3f}[{video_target}]"
            )
            video_accumulated = video_target
            if has_audio:
                audio_target = f"ax{index}"
                lines.append(
                    f"[{audio_accumulated}][a{index}]acrossfade=d={duration:.3f}:c1=tri:c2=tri[{audio_target}]"
                )
                audio_accumulated = audio_target
            elapsed += plan.assets[index].duration - duration
        video_tail = video_accumulated
        audio_tail = audio_accumulated
    else:
        if has_audio:
            reference = "".join(f"[v{i}][a{i}]" for i in range(len(plan.assets)))
            lines.append(f"{reference}concat=n={len(plan.assets)}:v=1:a=1[vcat][acat]")
        else:
            reference = "".join(f"[v{i}]" for i in range(len(plan.assets)))
            lines.append(f"{reference}concat=n={len(plan.assets)}:v=1:a=0[vcat]")
        video_tail = "vcat"
        audio_tail = "acat" if has_audio else ""

    # ── 图层叠加 ────────────────────────────────────────────────────────
    mix_overlay = False
    if layer_inputs:
        previous = video_tail
        for order, (layer, input_index) in enumerate(layer_inputs):
            window_end = layer.end_seconds if layer.end_seconds > 0 else plan.total_duration
            # 起始片段（1 基）换算为绝对时间，与手动起点取较晚者。
            clip_start = _clip_start_seconds(plan, int(layer.start_clip_index))
            window_start = max(0.0, min(max(layer.start_seconds, clip_start), max(window_end - 0.04, 0.0)))
            duration = max(window_end - window_start, 0.04)
            width = max(2, int(round(settings.width * max(layer.width_percent, 1) / 100)))
            height_limit = (
                _even(settings.height * max(0.0, min(layer.height_percent, 100.0)) / 100)
                if layer.height_percent > 0.0
                else 0
            )

            crop = _source_crop_filters(layer, settings)
            fit_chain = _layer_fit_filters(layer, settings, width, height_limit)

            def _build_source(label: str) -> str:
                chain = f"{label}trim=duration={_seconds(duration)},setpts=PTS-STARTPTS+{window_start:.3f}/TB"
                if layer.remove_black:
                    chain += ",colorkey=black:0.10:0.06"
                if crop:
                    chain += f",{crop}"
                chain += f",{fit_chain},format=rgba,colorchannelmixer=aa={max(0.0, min(layer.opacity, 1.0)):.3f}"
                return chain

            rotate = ""
            if abs(layer.rotation_degrees) >= 0.1:
                import math

                radians = layer.rotation_degrees * math.pi / 180.0
                rotate = f"rotate={radians:.6f}:ow=rotw(iw):oh=roth(ih):c=none"

            source = f"lay{order}"
            if input_index is not None:
                chain = _build_source(f"[{input_index}:v]")
            else:
                # 自叠影：从当前主画面分流一条作为图层来源。
                ghost_label = f"lay{order}ghost"
                lines.append(f"[{previous}]split[lay{order}keep][{ghost_label}]")
                previous = f"lay{order}keep"
                chain = _build_source(f"[{ghost_label}]")

            if layer.feather > 0.0 or layer.top_fade > 0.0:
                base_label = f"lay{order}base"
                envelope_label = f"lay{order}env"
                lines.append(chain + f"[{base_label}]")
                lines.append(_alpha_envelope(base_label, envelope_label, layer, width))
                if rotate:
                    lines.append(f"[{envelope_label}]{rotate}[{source}]")
                else:
                    source = envelope_label
            elif rotate:
                lines.append(chain + f",{rotate}[{source}]")
            else:
                lines.append(chain + f"[{source}]")

            x = f"main_w*{max(layer.x_percent, 0) / 100:.4f}-overlay_w/2"
            y = f"main_h*{max(layer.y_percent, 0) / 100:.4f}-overlay_h/2"
            target = f"vlay{order}"
            lines.append(f"[{previous}][{source}]overlay=x={x}:y={y}:eof_action=pass[{target}]")
            previous = target

            if (layer.audio_mode or "discard").lower() == "mix":
                mix_overlay = True

        video_tail = previous

    # ── 硬字幕去除 ──────────────────────────────────────────────────────
    if removal is not None and removal.enabled:
        x, y, width, height = removal.normalized_box(settings.width, settings.height)
        if removal.mode is RemovalMode.BLUR:
            lines.append(f"[{video_tail}]split=2[rbase][rcrop]")
            lines.append(f"[rcrop]crop={width}:{height}:{x}:{y},gblur=sigma=12[rblur]")
            lines.append(f"[rbase][rblur]overlay={x}:{y}[vrm]")
        elif removal.mode is RemovalMode.COVER:
            lines.append(f"[{video_tail}]drawbox=x={x}:y={y}:w={width}:h={height}:color=black@1.0:t=fill[vrm]")
        elif removal.mode is RemovalMode.CROP_AND_REFRAME:
            if y <= 1:
                lines.append(
                    f"[{video_tail}]crop={settings.width}:{settings.height - (y + height)}:0:{y + height},"
                    f"scale={settings.width}:{settings.height}[vrm]"
                )
            elif y + height >= settings.height - 1:
                lines.append(
                    f"[{video_tail}]crop={settings.width}:{settings.height - height}:0:0,"
                    f"scale={settings.width}:{settings.height}[vrm]"
                )
            else:
                raise ValueError("裁切重构仅适用于贴顶或贴底的字幕带。")
        else:
            lines.append(f"[{video_tail}]delogo=x={x}:y={y}:w={width}:h={height}[vrm]")
        video_tail = "vrm"

    # ── 字幕烧录 / 输出分辨率 ───────────────────────────────────────────
    tail_label = video_tail
    if subtitle_path is not None:
        escaped = escape_filter_path(subtitle_path)
        if str(subtitle_path).lower().endswith(".ass"):
            lines.append(f"[{tail_label}]ass='{escaped}'[vsub]")
        else:
            lines.append(f"[{tail_label}]subtitles=filename='{escaped}'[vsub]")
        tail_label = "vsub"

    target_width, target_height = settings.output_video.resolve_target_size(settings.width, settings.height)
    if (target_width, target_height) != (settings.width, settings.height):
        lines.append(f"[{tail_label}]scale={target_width}:{target_height}[vout]")
    else:
        lines.append(f"[{tail_label}]null[vout]")

    # ── 音频输出（原声音量 + 图层音轨 + BGM 混音）───────────────────────
    if has_audio:
        main_label = audio_tail
        main_volume = max(0, int(settings.main_volume_percent))
        if main_volume != 100:
            lines.append(f"[{audio_tail}]volume={main_volume / 100:.3f}[acatv]")
            main_label = "acatv"

        mix_inputs = 1
        if mix_overlay:
            overlay_audio_labels = [
                f"{input_index}:a"
                for layer, input_index in layer_inputs
                if input_index is not None and (layer.audio_mode or "discard").lower() == "mix"
            ]
            if overlay_audio_labels:
                for position, label in enumerate(overlay_audio_labels):
                    lines.append(f"[{label}]aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo[ovla{position}]")
                references = "".join(f"[ovla{position}]" for position in range(len(overlay_audio_labels)))
                inputs = len(overlay_audio_labels) + 1
                lines.append(
                    f"[{main_label}]{references}amix=inputs={inputs}:duration=first:dropout_transition=0[amix]"
                )
                main_label = "amix"
                mix_inputs += len(overlay_audio_labels)

        if bgm is None:
            lines.append(f"[{main_label}]anull[aout]")
        else:
            bgm_index = base_index + len(extra_inputs)
            extra_inputs.append(ExtraInput(path=bgm.path, loop=bgm.loop, purpose="bgm"))
            volume = bgm.resolved_gain
            total = max(plan.total_duration, 0.05)
            fade = max(0.0, min(bgm.fade_out_seconds, total))
            chain = (
                f"[{bgm_index}:a]aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
                f"aloop=loop=-1:size=2e9,atrim=duration={total:.3f},asetpts=PTS-STARTPTS,volume={volume:.3f}"
            )
            chain += f",afade=t=out:st={max(total - fade, 0):.3f}:d={max(fade, 0.001):.3f}"
            if has_original_audio or mix_overlay:
                lines.append(chain + "[bgm]")
                lines.append(f"[{main_label}][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]")
            else:
                lines.append(chain + ",anull[aout]")

    return FilterGraph(
        script=";\n".join(lines) + "\n",
        has_audio=has_audio,
        extra_inputs=tuple(extra_inputs),
    )
