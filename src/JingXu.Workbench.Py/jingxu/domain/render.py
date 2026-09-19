"""渲染设置、画幅策略、质量档与转码决策模型。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from jingxu.domain.composition import CompositionPlan
from jingxu.domain.effects import (
    DoubleScreenEffectPlan,
    FourScreenEffectPlan,
    MainMaterialBoostPlan,
)
from jingxu.domain.layers import LayerSpec
from jingxu.domain.splitscreen import SplitScreenSpec
from jingxu.domain.subtitles import SubtitleBurnSpec, SubtitleRemovalSpec

CANVAS_PRESETS: tuple[tuple[str, int, int], ...] = (
    ("竖屏 1080x1920", 1080, 1920),
    ("横屏 1920x1080", 1920, 1080),
    ("方形 1080x1080", 1080, 1080),
    ("竖屏 720x1280", 720, 1280),
)

CRF_PRESETS: tuple[tuple[str, int], ...] = (
    ("高质量 (CRF 20)", 20),
    ("标准 (CRF 23)", 23),
    ("体积优先 (CRF 26)", 26),
)


class ProcessingMode(str, Enum):
    """渲染处理器选择。"""

    AUTO = "auto"
    CPU = "cpu"
    GPU = "gpu"

    @property
    def display_text(self) -> str:
        return {"auto": "自动（推荐）", "cpu": "CPU（兼容稳定）", "gpu": "GPU（硬件加速）"}[self.value]


class FitMode(str, Enum):
    """拼接素材适配方式。"""

    PAD = "pad"
    CROP = "crop"
    STRETCH = "stretch"
    BLUR = "blur"

    @property
    def display_text(self) -> str:
        return {
            "pad": "黑边",
            "crop": "居中裁切",
            "stretch": "拉伸",
            "blur": "模糊背景",
        }[self.value]


class OverlayFitMode(str, Enum):
    """蒙版素材适配方式。"""

    FILL_CROP = "fill_crop"
    CONTAIN = "contain"
    STRETCH = "stretch"
    MATCH_CANVAS_CROP = "match_canvas_crop"

    @property
    def display_text(self) -> str:
        return {
            "fill_crop": "填满裁切",
            "contain": "完整适配",
            "stretch": "拉伸",
            "match_canvas_crop": "裁成画幅再覆盖",
        }[self.value]


class OutputCanvasPreset(str, Enum):
    """输出画幅预设。"""

    INHERIT_FIRST = "inherit_first"
    VERTICAL_9X16 = "vertical_9x16"
    HORIZONTAL_16X9 = "horizontal_16x9"
    SQUARE_1X1 = "square_1x1"
    PORTRAIT_3X4 = "portrait_3x4"
    CUSTOM = "custom"

    @property
    def display_text(self) -> str:
        return {
            "inherit_first": "继承首段",
            "vertical_9x16": "9:16 竖屏",
            "horizontal_16x9": "16:9 横屏",
            "square_1x1": "1:1 方形",
            "portrait_3x4": "3:4 竖屏",
            "custom": "自定义",
        }[self.value]

    @property
    def canvas_size(self) -> tuple[int, int] | None:
        return {
            OutputCanvasPreset.VERTICAL_9X16: (1080, 1920),
            OutputCanvasPreset.HORIZONTAL_16X9: (1920, 1080),
            OutputCanvasPreset.SQUARE_1X1: (1080, 1080),
            OutputCanvasPreset.PORTRAIT_3X4: (1080, 1440),
        }.get(self)


@dataclass(frozen=True, slots=True)
class OutputAspect:
    """输出画幅策略（继承首段或指定目标分辨率 + 适配方式）。"""

    inherit_from_first: bool
    target_width: int | None
    target_height: int | None
    fit_mode: FitMode = FitMode.CROP

    @staticmethod
    def inherit_first(fit_mode: FitMode = FitMode.CROP) -> OutputAspect:
        return OutputAspect(True, None, None, fit_mode)

    @staticmethod
    def custom(width: int, height: int, fit_mode: FitMode = FitMode.CROP) -> OutputAspect:
        return OutputAspect(False, width, height, fit_mode)


@dataclass(frozen=True, slots=True)
class UnifiedAspectPolicy:
    """混剪「统一比例」策略：成片画幅与素材/蒙版各自的适配方式。"""

    is_enabled: bool = False
    preset: OutputCanvasPreset = OutputCanvasPreset.VERTICAL_9X16
    custom_width: int | None = None
    custom_height: int | None = None
    clip_fit_mode: FitMode = FitMode.CROP
    overlay_fit_mode: OverlayFitMode = OverlayFitMode.FILL_CROP

    def to_output_aspect(self) -> OutputAspect:
        if not self.is_enabled:
            return OutputAspect.inherit_first()
        if self.preset is OutputCanvasPreset.INHERIT_FIRST:
            return OutputAspect.inherit_first(self.clip_fit_mode)
        if self.preset is OutputCanvasPreset.CUSTOM:
            if self.custom_width and self.custom_height and self.custom_width > 0 and self.custom_height > 0:
                return OutputAspect.custom(self.custom_width, self.custom_height, self.clip_fit_mode)
            raise ValueError("自定义画幅的宽度与高度必须大于零。")
        size = self.preset.canvas_size
        if size is None:
            raise ValueError("未知的画幅预设。")
        return OutputAspect.custom(size[0], size[1], self.clip_fit_mode)

    def apply_overlay_fit(self, layers: tuple[LayerSpec, ...]) -> tuple[LayerSpec, ...]:
        """启用统一比例时，将蒙版适配方式应用到各层。"""
        if not self.is_enabled or not layers:
            return layers
        return tuple(replace(layer, fit=self.overlay_fit_mode.value) for layer in layers)

    def build_preview_description(self, first_clip_width: int | None = None, first_clip_height: int | None = None) -> str:
        if not self.is_enabled:
            return "未启用统一比例：成片继承第一条素材画幅；异比例片段将按默认居中裁切拼接。"
        return (
            f"已启用统一比例：成片画幅 {self._describe_canvas(first_clip_width, first_clip_height)}；"
            f"拼接素材 {_describe_clip_fit(self.clip_fit_mode)}；蒙版素材 {self.overlay_fit_mode.display_text}。"
            "渲染前主时间线与蒙版均缩放至同一画幅再叠加。"
        )

    def _describe_canvas(self, first_clip_width: int | None, first_clip_height: int | None) -> str:
        if self.preset is OutputCanvasPreset.INHERIT_FIRST:
            if first_clip_width and first_clip_height:
                return f"继承首段 {first_clip_width}×{first_clip_height}"
            return "继承首段素材分辨率"
        if self.preset is OutputCanvasPreset.CUSTOM:
            if self.custom_width and self.custom_height:
                return f"{self.custom_width}×{self.custom_height}（自定义）"
            return "自定义（请填写有效宽高）"
        labels = {
            OutputCanvasPreset.VERTICAL_9X16: "1080×1920（9:16 竖屏）",
            OutputCanvasPreset.HORIZONTAL_16X9: "1920×1080（16:9 横屏）",
            OutputCanvasPreset.SQUARE_1X1: "1080×1080（1:1 方形）",
            OutputCanvasPreset.PORTRAIT_3X4: "1080×1440（3:4 竖屏）",
        }
        return labels.get(self.preset, "未知")

    @staticmethod
    def recommended_overlay_fit(preset: OutputCanvasPreset) -> OverlayFitMode:
        """3:4 竖屏时推荐「先裁成画幅再覆盖」。"""
        if preset is OutputCanvasPreset.PORTRAIT_3X4:
            return OverlayFitMode.MATCH_CANVAS_CROP
        return OverlayFitMode.FILL_CROP


def _describe_clip_fit(fit: FitMode) -> str:
    return {
        FitMode.CROP: "Cover 居中裁切",
        FitMode.PAD: "Contain 完整适配（黑边）",
        FitMode.STRETCH: "Stretch 拉伸填满",
        FitMode.BLUR: "模糊背景填充",
    }[fit]


class OutputResolutionPreset(str, Enum):
    """导出画面分辨率预设（按短边缩放）。"""

    ORIGINAL = "original"
    P480 = "p480"
    P720 = "p720"
    P1080 = "p1080"

    @property
    def display_text(self) -> str:
        return {"original": "原画", "p480": "480P", "p720": "720P", "p1080": "1080P"}[self.value]

    @property
    def short_edge(self) -> int | None:
        return {"p480": 480, "p720": 720, "p1080": 1080}.get(self.value)


class OutputFrameRatePreset(str, Enum):
    """导出帧率预设。"""

    ORIGINAL = "original"
    FPS24 = "24"
    FPS25 = "25"
    FPS30 = "30"
    FPS50 = "50"
    FPS60 = "60"

    @property
    def display_text(self) -> str:
        return {
            "original": "原帧率",
            "24": "24 fps",
            "25": "25 fps",
            "30": "30 fps",
            "50": "50 fps",
            "60": "60 fps",
        }[self.value]

    @property
    def value_fps(self) -> float | None:
        return None if self is OutputFrameRatePreset.ORIGINAL else float(self.value)


@dataclass(frozen=True, slots=True)
class OutputVideoSettings:
    """入队时冻结的导出分辨率与帧率策略。"""

    resolution: OutputResolutionPreset = OutputResolutionPreset.ORIGINAL
    frame_rate: OutputFrameRatePreset = OutputFrameRatePreset.ORIGINAL

    @property
    def is_original_resolution(self) -> bool:
        return self.resolution is OutputResolutionPreset.ORIGINAL

    @property
    def is_original_frame_rate(self) -> bool:
        return self.frame_rate is OutputFrameRatePreset.ORIGINAL

    @property
    def requires_transcode(self) -> bool:
        return not self.is_original_resolution or not self.is_original_frame_rate

    def resolve_target_size(self, canvas_width: int, canvas_height: int) -> tuple[int, int]:
        """以当前画幅为基准按短边缩放，输出偶数尺寸。"""
        if canvas_width <= 0 or canvas_height <= 0:
            raise ValueError("画布尺寸必须为正整数。")
        if self.is_original_resolution:
            return canvas_width, canvas_height

        short_edge = self.resolution.short_edge
        if short_edge is None:
            raise ValueError("未知的导出分辨率预设。")

        if canvas_width <= canvas_height:
            return short_edge, _scale_even(canvas_height, short_edge, canvas_width)
        return _scale_even(canvas_width, short_edge, canvas_height), short_edge

    def resolve_frame_rate(self, first_clip_frame_rate: float) -> float:
        if first_clip_frame_rate <= 0:
            raise ValueError("素材帧率必须为正数。")
        preset = self.frame_rate.value_fps
        return first_clip_frame_rate if preset is None else preset


def _scale_even(long_edge: int, target_short_edge: int, current_short_edge: int) -> int:
    scaled = long_edge * (target_short_edge / float(current_short_edge))
    rounded_to_even = int(round(scaled / 2.0)) * 2
    return max(2, rounded_to_even)


class QualityPreset(str, Enum):
    """输出质量档位。"""

    LOSSLESS = "lossless"
    HIGH = "high"
    BALANCED = "balanced"
    SMALL = "small"
    FAST = "fast"

    @property
    def display_text(self) -> str:
        return {
            "lossless": "无损直拷",
            "high": "高质量",
            "balanced": "平衡",
            "small": "小体积",
            "fast": "快速",
        }[self.value]


@dataclass(frozen=True, slots=True)
class RenderProfile:
    """不可变的渲染质量配置。"""

    quality: QualityPreset
    video_crf: int | None
    audio_bitrate_kbps: int
    x264_preset: str = "faster"

    @property
    def crf(self) -> int | None:
        return self.video_crf

    @property
    def audio_kbps(self) -> int:
        return self.audio_bitrate_kbps

    @property
    def encode_preset(self) -> str:
        return self.x264_preset.strip() or "faster"

    @staticmethod
    def for_preset(preset: QualityPreset) -> RenderProfile:
        return {
            QualityPreset.LOSSLESS: RenderProfile(QualityPreset.LOSSLESS, None, 0, "faster"),
            QualityPreset.HIGH: RenderProfile(QualityPreset.HIGH, 18, 192, "fast"),
            QualityPreset.BALANCED: RenderProfile(QualityPreset.BALANCED, 22, 160, "faster"),
            QualityPreset.SMALL: RenderProfile(QualityPreset.SMALL, 27, 128, "veryfast"),
            QualityPreset.FAST: RenderProfile(QualityPreset.FAST, 26, 128, "ultrafast"),
        }[preset]


class TranscodeReason(str, Enum):
    """必须重新编码的原因。"""

    OVERLAY = "overlay"
    EFFECTS = "effects"
    ASPECT_CHANGE = "aspect_change"
    SUBTITLE = "subtitle"
    BGM = "bgm"
    STREAM_MISMATCH = "stream_mismatch"
    TRANSITION = "transition"
    QUALITY_PRESET = "quality_preset"
    MAIN_MATERIAL_BOOST = "main_material_boost"
    OUTPUT_RESOLUTION = "output_resolution"
    OUTPUT_FRAME_RATE = "output_frame_rate"

    @property
    def display_text(self) -> str:
        return {
            "overlay": "存在视频蒙版覆盖层",
            "effects": "存在差异化/滤镜效果",
            "aspect_change": "画幅与源素材不一致",
            "subtitle": "存在字幕处理或烧录",
            "bgm": "存在 BGM 或音频混合",
            "stream_mismatch": "输入流编码或结构不兼容",
            "transition": "存在非零转场重叠",
            "quality_preset": "质量档需要重新编码",
            "main_material_boost": "主轨素材启用了音量/缩放增强",
            "output_resolution": "选择了显式导出分辨率",
            "output_frame_rate": "选择了显式导出帧率",
        }[self.value]


@dataclass(frozen=True, slots=True)
class VariationSettings:
    """差异化滤镜：逐条成片对片段做可复现的小幅变化。"""

    mirror: bool = True
    light_crop: bool = True
    color: bool = True
    denoise: bool = False
    rotate: bool = True
    rotation_max_degrees: float = 15.0
    intensity: int = 100

    @property
    def enabled(self) -> bool:
        return self.mirror or self.light_crop or self.color or self.denoise or self.rotate


class CoverMode(str, Enum):
    """封面取帧方式。"""

    FIRST_SOURCE_FRAME = "first_source_frame"
    FINAL_OUTPUT_FRAME = "final_output_frame"
    TIMESTAMP = "timestamp"

    @property
    def display_text(self) -> str:
        return {
            "first_source_frame": "首段素材首帧",
            "final_output_frame": "成片结尾帧",
            "timestamp": "指定时间点",
        }[self.value]


@dataclass(frozen=True, slots=True)
class CoverRequest:
    """封面导出：从成片中取一帧。"""

    output_path: Path
    at_seconds: float = 1.0
    mode: CoverMode = CoverMode.TIMESTAMP


@dataclass(frozen=True, slots=True)
class BgmSource:
    """背景音乐来源：单文件或从音频库随机抽取。"""

    kind: str = "file"  # "file" | "library"
    path: Path | None = None
    volume_mode: str = "fixed"  # "fixed" | "random"
    volume_percent: int = 30
    volume_min: int = 15
    volume_max: int = 45
    fade_out_seconds: float = 1.5
    loop: bool = True

    def resolved_volume(self, offset: int = 0) -> int:
        if self.volume_mode != "random":
            return max(0, min(self.volume_percent, 200))
        low, high = sorted((max(0, self.volume_min), max(0, self.volume_max)))
        if high <= low:
            return low
        return low + (offset * 7) % (high - low + 1)


@dataclass(frozen=True, slots=True)
class BgmSettings:
    """背景音乐混入设置。"""

    path: Path
    volume_percent: int = 30
    fade_out_seconds: float = 1.5
    loop: bool = True


@dataclass(frozen=True, slots=True)
class TransitionSettings:
    """交叉转场：相邻片段重叠，成片时长相应缩短。"""

    enabled: bool = False
    duration_seconds: float = 0.5


@dataclass(frozen=True, slots=True)
class RenderSettings:
    """画幅、帧率与编码参数。

    ``stream_copy``：请求「无损直拷」；仅当没有任何需要转码的处理
    （分屏/图层/字幕/BGM/差异化/统一比例/音量）且素材流参数一致时生效，
    否则自动回退普通转码。
    """

    width: int = 1080
    height: int = 1920
    fps: float = 30.0
    crf: int = 23
    preset: str = "veryfast"
    audio_bitrate_k: int = 192
    processing: ProcessingMode = ProcessingMode.AUTO
    fit_mode: FitMode = FitMode.PAD
    output_video: OutputVideoSettings = OutputVideoSettings()
    quality: QualityPreset = QualityPreset.BALANCED
    main_volume_percent: int = 100
    variation: VariationSettings | None = None
    stream_copy: bool = False
    transition: TransitionSettings | None = None
    boost: MainMaterialBoostPlan | None = None
    clear_metadata: bool = False


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """一次入队渲染的完整请求（不可变）。"""

    name: str
    plan: CompositionPlan
    settings: RenderSettings
    output_path: Path
    cover: CoverRequest | None = None
    bgm: BgmSettings | None = None
    split: SplitScreenSpec | None = None
    layers: tuple[LayerSpec, ...] = ()
    subtitles: SubtitleBurnSpec | None = None
    removal: SubtitleRemovalSpec | None = None
    aspect: OutputAspect | None = None
    double_screen: DoubleScreenEffectPlan | None = None
    four_screen: FourScreenEffectPlan | None = None

    @property
    def total_duration(self) -> float:
        if self.plan.transition_seconds > 0:
            return self.plan.total_duration
        transition = self.settings.transition
        plan = self.plan
        if transition is not None and transition.enabled and len(plan.assets) > 1:
            return max(0.0, plan.total_duration - transition.duration_seconds * (len(plan.assets) - 1))
        return plan.total_duration


@dataclass(frozen=True, slots=True)
class RenderDecision:
    """根据请求快照给出的直拷/转码判断。"""

    can_stream_copy: bool
    reasons: tuple[TranscodeReason, ...]


def has_stream_mismatch(plan: CompositionPlan) -> bool:
    """相邻片段之间编码/尺寸/帧率/音轨结构是否不一致。"""
    if not plan.assets:
        return True

    first = plan.assets[0]
    for asset in plan.assets[1:]:
        if asset.video_codec.strip().lower() != first.video_codec.strip().lower():
            return True
        if asset.width != first.width or asset.height != first.height:
            return True
        if asset.fps != first.fps:
            return True
        if asset.has_audio != first.has_audio:
            return True
        if asset.has_audio and asset.audio_codec.strip().lower() != first.audio_codec.strip().lower():
            return True
    return False


def render_decision(request: RenderRequest) -> RenderDecision:
    """分析请求并给出转码决策（对齐 .NET RenderDecision.For）。"""
    reasons: list[TranscodeReason] = []
    plan = request.plan
    settings = request.settings

    if any(layer.enabled for layer in request.layers):
        reasons.append(TranscodeReason.OVERLAY)

    has_effects = (
        (settings.variation is not None and settings.variation.enabled)
        or request.split is not None
        or request.double_screen is not None
        or request.four_screen is not None
    )
    if has_effects:
        reasons.append(TranscodeReason.EFFECTS)

    has_subtitles = (request.subtitles is not None and not request.subtitles.is_empty) or (
        request.removal is not None and request.removal.enabled
    )
    if has_subtitles:
        reasons.append(TranscodeReason.SUBTITLE)

    if request.bgm is not None:
        reasons.append(TranscodeReason.BGM)

    if (settings.boost is not None and settings.boost.is_active) or settings.main_volume_percent != 100:
        reasons.append(TranscodeReason.MAIN_MATERIAL_BOOST)

    if request.aspect is not None and not request.aspect.inherit_from_first:
        reasons.append(TranscodeReason.ASPECT_CHANGE)
    elif request.aspect is None and plan.assets:
        first = plan.assets[0]
        if settings.width != first.width or settings.height != first.height:
            reasons.append(TranscodeReason.ASPECT_CHANGE)

    if not settings.output_video.is_original_resolution:
        reasons.append(TranscodeReason.OUTPUT_RESOLUTION)
    if not settings.output_video.is_original_frame_rate:
        reasons.append(TranscodeReason.OUTPUT_FRAME_RATE)
    elif plan.assets and float(settings.fps) != float(plan.assets[0].fps):
        # 原帧率策略要求画布帧率跟随首段；显式不同的画布帧率必须重编码。
        reasons.append(TranscodeReason.OUTPUT_FRAME_RATE)

    if settings.transition is not None and settings.transition.enabled and len(plan.assets) > 1:
        reasons.append(TranscodeReason.TRANSITION)

    if not settings.stream_copy:
        reasons.append(TranscodeReason.QUALITY_PRESET)

    if has_stream_mismatch(plan):
        reasons.append(TranscodeReason.STREAM_MISMATCH)

    return RenderDecision(len(reasons) == 0, tuple(reasons))


def validate_transition(plan: CompositionPlan, transition: TransitionSettings | None) -> str | None:
    """校验交叉转场；合法返回 ``None``，否则返回中文错误文案。"""
    if transition is None or not transition.enabled or len(plan.assets) < 2:
        return None

    duration = transition.duration_seconds
    if duration <= 0:
        return "转场时长必须大于 0 秒。"

    for index in range(len(plan.assets) - 1):
        first = plan.assets[index]
        second = plan.assets[index + 1]
        if min(first.duration, second.duration) <= duration:
            return (
                f"转场时长 {duration:g} 秒超过了相邻片段"
                f"（{first.display_name}、{second.display_name}）的较短时长。"
            )
    return None
