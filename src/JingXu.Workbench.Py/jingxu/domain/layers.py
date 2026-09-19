"""图层模型：蒙版覆盖与贴纸（共用一套叠加参数）。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from uuid import uuid4

SELF_SOURCE = ":self:"

# 形状遮罩常量（对齐 .NET OverlayLayer 的硬编码取值）
DEFAULT_MASK_CORNER_RADIUS_PX = 8.0
MIN_MASK_CORNER_RADIUS_PX = 1.0
MAX_MASK_CORNER_RADIUS_PX = 200.0
MASK_PNG_MODES = ("luma", "alpha", "luma_alpha")
# 只接受 ffmpeg 能作为单帧图片循环读取的格式（.gif 走 -stream_loop，不在此列）。
MASK_PNG_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


class LayerKind(str, Enum):
    OVERLAY = "overlay"
    STICKER = "sticker"


class LayerShapeMask(str, Enum):
    """图层 alpha 形状。

    ``NONE`` 保留素材自带 alpha（默认，行为与迁移前一致）；
    ``RECTANGLE`` 等价于不裁剪（矩形即整个边界框）；
    ``ROUNDED_RECTANGLE``/``ELLIPSE`` 用逐像素表达式重写 alpha 通道；
    ``IMPORTED_PNG`` 用外部灰度/透明 PNG 作为 alpha 遮罩。
    """

    NONE = "none"
    RECTANGLE = "rectangle"
    ROUNDED_RECTANGLE = "rounded_rectangle"
    ELLIPSE = "ellipse"
    IMPORTED_PNG = "imported_png"


@dataclass(frozen=True, slots=True)
class LayerSpec:
    """一条叠加图层：素材 + 时间窗口 + 位置 / 尺寸 / 透明度 / 边缘处理。"""

    kind: LayerKind
    source: Path
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    x_percent: float = 50.0
    y_percent: float = 50.0
    width_percent: float = 30.0
    height_percent: float = 0.0
    opacity: float = 1.0
    remove_black: bool = False
    rotation_degrees: float = 0.0
    feather: float = 0.0
    top_fade: float = 0.0
    source_crop_canvas: bool = False
    source_crop_y: float = 0.0
    source_crop_bounds: tuple[float, float, float, float] | None = None
    fit: str = "fill_crop"
    scale_percent: float = 100.0
    start_clip_index: int = 1
    audio_mode: str = "discard"
    z_index: int = 0
    enabled: bool = True
    id: str = ""
    # ── 形状遮罩（对齐 .NET OverlayLayer.Shape / AlphaPngPath）──────────────
    shape_mask: str = LayerShapeMask.NONE.value
    mask_corner_radius_px: float = DEFAULT_MASK_CORNER_RADIUS_PX
    mask_png: Path | None = None
    mask_png_mode: str = "luma"
    mask_png_invert: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", uuid4().hex[:10])

    @property
    def display_name(self) -> str:
        return self.source.name

    @property
    def is_image(self) -> bool:
        return self.source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

    @property
    def is_self_source(self) -> bool:
        """是否为主片自叠影（无外部输入）。"""
        return str(self.source) == SELF_SOURCE

    @property
    def shape_mask_kind(self) -> LayerShapeMask:
        """容错解析形状字符串；未知值回落 ``NONE``。"""
        try:
            return LayerShapeMask(str(self.shape_mask or "").strip().lower())
        except ValueError:
            return LayerShapeMask.NONE

    @property
    def needs_explicit_height(self) -> bool:
        """PNG 遮罩必须显式高度，否则两路尺寸无法保证逐像素相等。"""
        return self.shape_mask_kind is LayerShapeMask.IMPORTED_PNG

    @property
    def window_text(self) -> str:
        end = f"{self.end_seconds:.1f}s" if self.end_seconds > 0 else "片尾"
        return f"{self.start_seconds:.1f}s → {end}"

    def with_changes(self, **changes: object) -> "LayerSpec":
        return replace(self, **changes)

    def validate_shape_mask(self) -> str | None:
        """校验形状遮罩参数；合法返回 ``None``，否则返回中文错误文案。

        规则（对齐 .NET ``OverlayLayer.Validate`` 的形状分支并补上高度约束）：

        * 形状为 ``NONE``/``RECTANGLE``：恒通过（矩形即边界框，无额外参数）；
        * ``IMPORTED_PNG``：必须指定遮罩文件、后缀可被 ffmpeg 单帧读取，
          且**必须显式高度**（``height_percent > 0``）；
        * 圆角半径必须落在 1–200 像素。
        """
        kind = self.shape_mask_kind
        if kind in (LayerShapeMask.NONE, LayerShapeMask.RECTANGLE):
            return None

        if kind is LayerShapeMask.ROUNDED_RECTANGLE:
            radius = float(self.mask_corner_radius_px)
            if not (MIN_MASK_CORNER_RADIUS_PX <= radius <= MAX_MASK_CORNER_RADIUS_PX):
                return (
                    f"圆角半径必须在 {MIN_MASK_CORNER_RADIUS_PX:g} 到 "
                    f"{MAX_MASK_CORNER_RADIUS_PX:g} 像素之间。"
                )
            return None

        if kind is LayerShapeMask.ELLIPSE:
            return None

        # IMPORTED_PNG
        if self.mask_png is None:
            return "PNG 遮罩缺少遮罩文件。"
        mask_path = Path(self.mask_png)
        if mask_path.suffix.lower() not in MASK_PNG_SUFFIXES:
            return "PNG 遮罩仅支持 png/jpg/jpeg/webp/bmp 格式。"
        if str(self.mask_png_mode or "").strip().lower() not in MASK_PNG_MODES:
            return "PNG 遮罩模式必须是 luma、alpha 或 luma_alpha。"
        if float(self.height_percent) <= 0:
            return "PNG 遮罩需要显式高度（当前高度为 0，将无法与图层画面逐像素对齐）。"
        return None
