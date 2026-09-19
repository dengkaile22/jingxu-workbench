"""测试共用辅助。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from jingxu.domain.media import MediaAsset, extract_sequence_index


def make_asset(
    name: str = "a.mp4",
    *,
    duration: float = 2.0,
    width: int = 640,
    height: int = 360,
    fps: float = 30.0,
    has_audio: bool = True,
) -> MediaAsset:
    return MediaAsset(
        path=Path("materials") / name,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio,
        video_codec="h264",
        audio_codec="aac" if has_audio else "",
        sequence_index=extract_sequence_index(name),
        asset_id=name,
    )


def wait_until(predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时。")
