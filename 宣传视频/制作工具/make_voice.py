"""生成宣传片旁白：每个「节拍」（一句旁白）一条 edge-tts 音频，并记录时长。

产物：
  voice/beats/<scene>_<index>.mp3
  voice/timings.json   —— 每场景的节拍文本与时长（秒），供合成脚本计算时间轴
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FFPROBE = Path(__file__).resolve().parents[2] / "runtime" / "ffmpeg" / "ffprobe.exe"

ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "voice"
BEATS_DIR = VOICE / "beats"

VOICE_NAME = "zh-CN-XiaoxiaoNeural"
RATE = "+8%"
GAP_AFTER_BEAT = 0.42      # 句间停顿（秒）
SCENE_HEAD_PAD = 0.55      # 场景开始留白
SCENE_TAIL_PAD = 0.75      # 场景结束留白

SCENES: list[dict] = [
    {
        "id": "intro",
        "beats": [
            "清影快速混剪，一款完全离线的 Windows 桌面视频工具。",
            "批量混剪、爆品选品、字幕处理，一个软件全部搞定。",
        ],
    },
    {
        "id": "composition",
        "beats": [
            "导入带货素材，",
            "随机拼接、自定义序号，两种编排随你选。",
            "设置批次数量和随机种子，一次生成几十条差异化成片，每条都不同、还能复现。",
            "交叉转场、画幅适配、滤镜贴纸、背景音乐，一次编排，全部生效。",
        ],
    },
    {
        "id": "spider",
        "beats": [
            "不知道卖什么？让对标账号替你选。",
            "抖音、快手公开页面自动抓取，",
            "按点赞量、出现频次、跨账号共性，筛出真正的爆品，一键导出 Excel 报表。",
            "还能设置定时抓取，每天自动跑，醒来就能看结果。",
        ],
    },
    {
        "id": "subtitles",
        "beats": [
            "自带字幕实验室：",
            "Whisper 离线识别、OCR 自动定位硬字幕，也可以手动框选。",
            "识别结果可编辑、可导出，字幕样式直接烧录进成片。",
            "全部本地完成，不联网。",
        ],
    },
    {
        "id": "overlays",
        "beats": [
            "蒙版和贴纸，两个包装利器。",
            "三种蒙版、多层叠加、形状遮罩、羽化淡入；",
            "贴纸库随机抽取，让每条成片的封面都不重样。",
        ],
    },
    {
        "id": "queue",
        "beats": [
            "渲染交给任务队列：",
            "可暂停、可取消，失败自动隔离重试。",
            "自动检测并启用硬件加速，批量出片又快又稳。",
        ],
    },
    {
        "id": "outro",
        "beats": [
            "所有功能本地运行，素材不出本机。",
            "清影快速混剪，把重复劳动交给批量，把时间留给创意。",
        ],
    },
]


def synth(text: str, target: Path) -> None:
    result = subprocess.run(
        [
            sys.executable, "-m", "edge_tts",
            "--voice", VOICE_NAME,
            "--rate", RATE,
            "--text", text,
            "--write-media", str(target),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not target.exists():
        raise RuntimeError(f"edge-tts 失败：{text}\n{result.stderr}")


def duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def main() -> int:
    BEATS_DIR.mkdir(parents=True, exist_ok=True)
    timings: list[dict] = []
    for scene in SCENES:
        scene_entry = {"id": scene["id"], "beats": [], "duration": 0.0}
        cursor = SCENE_HEAD_PAD
        for index, text in enumerate(scene["beats"], start=1):
            target = BEATS_DIR / f"{scene['id']}_{index:02d}.mp3"
            if not target.exists():
                synth(text, target)
                print("OK", target.name)
            seconds = duration(target)
            scene_entry["beats"].append(
                {
                    "text": text,
                    "file": target.name,
                    "start": round(cursor, 3),
                    "duration": round(seconds, 3),
                }
            )
            cursor += seconds + GAP_AFTER_BEAT
        cursor = cursor - GAP_AFTER_BEAT + SCENE_TAIL_PAD
        scene_entry["duration"] = round(cursor, 3)
        timings.append(scene_entry)
        print(f"场景 {scene['id']}: {scene_entry['duration']}s")
    (VOICE / "timings.json").write_text(
        json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(item["duration"] for item in timings)
    print(f"旁白总时长（含停顿）：{total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
