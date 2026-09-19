"""素材模型与文件名序号解析。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEX_HASH_NAME = re.compile(r"^[0-9a-fA-F]{16,}$")
_LAST_NUMERIC_TOKEN = re.compile(r"\d+")


def extract_sequence_index(file_name: str) -> int | None:
    """提取文件名中最后一个连续数字片段作为序号。

    例如 ``商品_片段_12.mp4`` → 12。纯十六进制哈希名（如微信导出的
    32 位哈希文件名）不含业务序号，返回 ``None``；序号必须为正整数。
    """
    if not file_name or not file_name.strip():
        return None

    name_without_extension = Path(file_name).stem
    if _HEX_HASH_NAME.match(name_without_extension):
        return None

    matches = _LAST_NUMERIC_TOKEN.findall(name_without_extension)
    if not matches:
        return None

    try:
        index = int(matches[-1])
    except ValueError:
        return None

    return index if index > 0 else None


@dataclass(frozen=True, slots=True)
class MediaAsset:
    """已探测的本地视频素材。"""

    path: Path
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str = ""
    audio_codec: str = ""
    sequence_index: int | None = None
    asset_id: str = ""

    @property
    def display_name(self) -> str:
        return self.path.name

    @property
    def duration_text(self) -> str:
        total = max(0, int(round(self.duration)))
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def resolution_text(self) -> str:
        return f"{self.width}x{self.height}"
