"""字幕文件处理：SRT 解析/导出、ASS 生成与 ffmpeg 滤镜路径转义。"""

from __future__ import annotations

import re
from pathlib import Path

from jingxu.domain.subtitles import SubtitleCue, SubtitleStyle

_TIME_PATTERN = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})"
)


def parse_srt(text: str) -> list[SubtitleCue]:
    """解析 SRT 文本为字幕列表（宽容处理缺失编号与空行）。"""
    cues: list[SubtitleCue] = []
    blocks = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").replace("\r", "\n"))

    for block in blocks:
        lines = [line.strip("\ufeff").rstrip() for line in block.split("\n")]
        lines = [line for line in lines if line.strip()]
        if not lines:
            continue

        index = 0
        if lines[0].strip().isdigit():
            index = 1
        if index >= len(lines) or "-->" not in lines[index]:
            continue

        start_text, _, end_text = lines[index].partition("-->")
        start = _parse_time(start_text)
        end = _parse_time(end_text)
        if start is None or end is None:
            continue

        content = "\n".join(lines[index + 1 :]).strip()
        if not content:
            continue
        cues.append(SubtitleCue(start=start, end=max(end, start + 0.01), text=content))

    cues.sort(key=lambda cue: cue.start)
    return cues


def _parse_time(text: str) -> float | None:
    match = _TIME_PATTERN.search(text or "")
    if match is None:
        return None
    hours = int(match.group("h"))
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    milliseconds_text = match.group("ms")
    milliseconds = int(milliseconds_text.ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def format_srt(cues: list[SubtitleCue]) -> str:
    """导出为 SRT 文本。"""
    chunks: list[str] = []
    for order, cue in enumerate(cues, 1):
        chunks.append(f"{order}\n{cue.start_text} --> {cue.end_text}\n{cue.text.strip()}\n")
    return "\n".join(chunks)


_ASS_TIME_PATTERN = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.:](?P<cs>\d{1,2})"
)


def parse_ass(text: str) -> list[SubtitleCue]:
    """解析 ASS/SSA 文本为字幕列表（对齐 .NET ``AssSubtitleCodec.Read``）。

    - 依据 ``Format:`` 行列顺序映射字段；
    - ``Text`` 为最后一列，允许包含逗号；
    - ``\\N`` 还原为换行。
    """
    cues: list[SubtitleCue] = []
    format_order: list[str] = []

    for raw_line in (text or "").lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("format:"):
            fields = [field.strip().lower() for field in line.split(":", 1)[1].split(",")]
            if "start" in fields and "end" in fields:
                format_order = fields
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        if not format_order:
            continue

        payload = line.split(":", 1)[1]
        parts = payload.split(",")
        if len(parts) > len(format_order):
            head = parts[: len(format_order) - 1]
            head.append(",".join(parts[len(format_order) - 1 :]))
            parts = head
        if len(parts) < len(format_order):
            continue

        values = {name: parts[index].strip() for index, name in enumerate(format_order) if index < len(parts)}
        start = _parse_ass_time(values.get("start", ""))
        end = _parse_ass_time(values.get("end", ""))
        if start is None or end is None:
            continue
        content = values.get("text", "").replace(r"\N", "\n").replace(r"\n", "\n").strip()
        if not content:
            continue
        cues.append(SubtitleCue(start=start, end=max(end, start + 0.01), text=content))

    cues.sort(key=lambda cue: cue.start)
    return cues


def _parse_ass_time(text: str) -> float | None:
    match = _ASS_TIME_PATTERN.search(text or "")
    if match is None:
        return None
    hours = int(match.group("h"))
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    centiseconds = int(match.group("cs").ljust(2, "0")[:2])
    return hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0


def load_subtitle_file(path: Path) -> list[SubtitleCue]:
    """按扩展名读取字幕文件（.ass/.ssa 走 ASS 解析，其余按 SRT）。"""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    if Path(path).suffix.lower() in {".ass", ".ssa"}:
        return parse_ass(text)
    return parse_srt(text)


def format_ass_time(value: float) -> str:
    """ASS 时间格式 H:MM:SS.cc。"""
    total_centiseconds = max(0, int(round(value * 100)))
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _ass_color(hex_color: str) -> str:
    """把 #RRGGBB 转为 ASS 的 &HAABBGGRR（不透明）。"""
    value = (hex_color or "#FFFFFF").lstrip("#")
    if len(value) != 6:
        value = "FFFFFF"
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H00{blue}{green}{red}"


def build_ass(cues: list[SubtitleCue], style: SubtitleStyle, width: int, height: int) -> str:
    """生成带样式的 ASS 字幕文本（PlayRes 与成片画幅一致）。"""
    alignment = style.alignment
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_name},{style.font_size},{_ass_color(style.color)},&H000000FF,{_ass_color(style.outline_color)},&H64000000,-1,0,0,0,100,100,0,0,1,{style.outline},{style.shadow},{alignment},40,40,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip("\n")]
    for cue in cues:
        text = cue.text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N")
        lines.append(
            f"Dialogue: 0,{format_ass_time(cue.start)},{format_ass_time(cue.end)},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def write_ass(path: Path, cues: list[SubtitleCue], style: SubtitleStyle, width: int, height: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_ass(cues, style, width, height), encoding="utf-8-sig")
    return path


def escape_filter_path(path: Path | str) -> str:
    """ffmpeg 滤镜内的文件路径转义（盘符冒号、反斜杠与单引号）。"""
    text = str(path).replace("\\", "/")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    return text
