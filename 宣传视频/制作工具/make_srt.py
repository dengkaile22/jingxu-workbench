"""从 timings.json 生成平台可用的 SRT 字幕（与正片时间轴一致）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XFADE = 0.5


def srt_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def main() -> int:
    timings = json.loads((ROOT / "voice" / "timings.json").read_text(encoding="utf-8"))
    cursor = 0.0
    blocks: list[str] = []
    index = 1
    for entry in timings:
        for beat in entry["beats"]:
            begin = cursor + beat["start"] - 0.12
            end = cursor + beat["start"] + beat["duration"] + 0.35
            blocks.append(
                f"{index}\n{srt_time(begin)} --> {srt_time(end)}\n{beat['text']}\n"
            )
            index += 1
        cursor += entry["duration"] - XFADE
    target = ROOT / "out" / "字幕.srt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(blocks), encoding="utf-8-sig")
    (ROOT / "字幕.srt").write_text("\n".join(blocks), encoding="utf-8-sig")
    print("OK", target, f"{len(blocks)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
