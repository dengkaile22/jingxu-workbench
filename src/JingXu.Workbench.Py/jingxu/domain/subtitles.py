"""字幕模型：字幕条目、烧录样式与硬字幕去除区域。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SubtitlePosition(str, Enum):
    BOTTOM = "bottom"
    MIDDLE = "middle"
    TOP = "top"

    @property
    def display_text(self) -> str:
        return {"bottom": "底部", "middle": "居中", "top": "顶部"}[self.value]

    @property
    def ass_alignment(self) -> int:
        return {"bottom": 2, "middle": 5, "top": 8}[self.value]


class RemovalMode(str, Enum):
    BLUR = "blur"
    COVER = "cover"
    DELOGO = "delogo"
    CROP_AND_REFRAME = "crop_and_reframe"

    @property
    def display_text(self) -> str:
        return {
            "blur": "模糊",
            "cover": "遮盖",
            "delogo": "去标（插值）",
            "crop_and_reframe": "裁切重构",
        }[self.value]


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """一条字幕。"""

    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def format_time(self, value: float) -> str:
        total_ms = max(0, int(round(value * 1000)))
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    @property
    def start_text(self) -> str:
        return self.format_time(self.start)

    @property
    def end_text(self) -> str:
        return self.format_time(self.end)


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    """烧录样式（ASS 输出）。"""

    font_name: str = "Microsoft YaHei"
    font_size: int = 22
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline: int = 2
    shadow: int = 0
    margin_v: int = 40
    position: SubtitlePosition = SubtitlePosition.BOTTOM

    @property
    def alignment(self) -> int:
        return self.position.ass_alignment


@dataclass(frozen=True, slots=True)
class SubtitleBurnSpec:
    """烧录请求：条目 + 样式。"""

    cues: tuple[SubtitleCue, ...] = field(default_factory=tuple)
    style: SubtitleStyle = SubtitleStyle()

    @property
    def is_empty(self) -> bool:
        return not self.cues


@dataclass(frozen=True, slots=True)
class DetectedSubtitleSegment:
    """OCR 检测出的硬字幕段：归一化百分比区域 + 时间范围 + 置信度。"""

    x_percent: float
    y_percent: float
    width_percent: float
    height_percent: float
    start_seconds: float
    end_seconds: float
    confidence: float
    requires_review: bool = False
    review_state: str = "pending"

    @property
    def confirmed(self) -> bool:
        return self.review_state == "confirmed"

    @property
    def rejected(self) -> bool:
        return self.review_state == "rejected"


def validate_timeline(cues: tuple[SubtitleCue, ...] | list[SubtitleCue]) -> list[str]:
    """校验字幕时间轴：返回问题列表（空表示可用）。

    对齐 .NET ``SubtitleTimeline.Validate``：结束时间须晚于开始、文本不能为空、
    相邻条目不得重叠；只报告问题，绝不删除条目。
    """
    issues: list[str] = []
    items = list(cues)
    for index, cue in enumerate(items):
        if cue.end <= cue.start:
            issues.append(f"第 {index + 1} 条：结束时间必须晚于开始时间。")
        if not cue.text.strip():
            issues.append(f"第 {index + 1} 条：字幕文本不能为空。")

    for index in range(1, len(items)):
        previous = items[index - 1]
        current = items[index]
        if (
            previous.end > current.start
            and previous.end > previous.start
            and current.end > current.start
        ):
            issues.append(f"第 {index + 1} 条与第 {index} 条字幕时间重叠。")
    return issues


def resolve_overlaps(cues: tuple[SubtitleCue, ...] | list[SubtitleCue]) -> list[SubtitleCue]:
    """把重叠的前一条结束时间裁到后一条开始时间（不删除任何条目）。"""
    resolved: list[SubtitleCue] = []
    for cue in cues:
        if resolved:
            previous = resolved[-1]
            if previous.end > cue.start and cue.start > previous.start:
                resolved[-1] = SubtitleCue(start=previous.start, end=cue.start, text=previous.text)
        resolved.append(cue)
    return resolved


def has_pending_reviews(segments: tuple[DetectedSubtitleSegment, ...] | list[DetectedSubtitleSegment]) -> bool:
    """是否存在需要复核但尚未确认的 OCR 区域。"""
    return any(segment.requires_review and segment.review_state == "pending" for segment in segments)


@dataclass(frozen=True, slots=True)
class SubtitleRemovalSpec:
    """硬字幕去除区域（相对成片宽高的百分比）。"""

    mode: RemovalMode = RemovalMode.BLUR
    x_percent: float = 8.0
    y_percent: float = 76.0
    width_percent: float = 84.0
    height_percent: float = 18.0
    blur_power: int = 12
    enabled: bool = True

    def normalized_box(self, canvas_width: int, canvas_height: int) -> tuple[int, int, int, int]:
        """换算为像素区域（x, y, w, h），保证偶数且不越界。"""
        x = int(round(canvas_width * max(0.0, min(self.x_percent, 100.0)) / 100))
        y = int(round(canvas_height * max(0.0, min(self.y_percent, 100.0)) / 100))
        width = int(round(canvas_width * max(1.0, min(self.width_percent, 100.0)) / 100))
        height = int(round(canvas_height * max(1.0, min(self.height_percent, 100.0)) / 100))

        width = min(width, canvas_width - x)
        height = min(height, canvas_height - y)
        width = width if width % 2 == 0 else max(2, width - 1)
        height = height if height % 2 == 0 else max(2, height - 1)
        return max(0, x), max(0, y), width, height
