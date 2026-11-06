"""生成 30 秒版宣传片：6 个镜头（片头 → 5 个功能 → 闲鱼落版）。

流程：
  1. edge-tts 逐句配音（zh-CN-XiaoxiaoNeural），ffprobe 量每句时长
  2. 按配音时长分配镜头时长，并把总时长精确压到 30.000s
  3. zoompan 微推 + xfade 交叉转场 + 配音/BGM 侧链闪避 + ASS 字幕烧录

产物：
  清影快速混剪-宣传片-30s.mp4   正片（1920×1080 / 30fps / H.264 + AAC）
  字幕-30s.srt                  可直接上传平台的字幕
  out/scenes30/*.mp4            中间镜头片段
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parent.parent  # 宣传视频/
FFMPEG = REPO / "runtime" / "ffmpeg" / "ffmpeg.exe"
FFPROBE = REPO / "runtime" / "ffmpeg" / "ffprobe.exe"

SCENES = ROOT / "scenes"
VOICE = ROOT / "voice30"
OUT = ROOT / "out"
CLIPS = OUT / "scenes30"

FPS = 30
XFADE = 0.4
TOTAL = 30.0
VOICE_RATE = 44100
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_RATE = "+12%"

# 镜头顺序即时间轴顺序；voice 为配音稿，text 为烧录字幕（可与配音不同，落版要把账号写清楚）。
BEATS = [
    {
        "id": "intro",
        "image": "00_intro.png",
        "voice": "清影快速混剪，完全离线的 Windows 批量视频工具。",
        "text": "清影快速混剪 · 完全离线的批量视频工具",
        "caption": False,
        "zoom": 0.04,
    },
    {
        "id": "composition",
        "image": "01_composition.png",
        "voice": "素材导入，随机拼接，批次和随机种子可控，几十条成片各不相同。",
        "text": "素材拖入即用 · 随机/自定义编排 · 批次差异化",
        "zoom": 0.06,
    },
    {
        "id": "spider",
        "image": "02_spider.png",
        "voice": "对标账号一键抓取，多维筛选爆品，直接导出 Excel 报表。",
        "text": "对标账号抓取 · 多维筛选 · 导出 Excel",
        "zoom": 0.06,
    },
    {
        "id": "subtitles",
        "image": "03_subtitles.png",
        "voice": "Whisper 离线识别，OCR 定位，字幕一键烧进成片。",
        "text": "Whisper 离线识别 · OCR 定位 · 一键烧录",
        "zoom": 0.06,
    },
    {
        "id": "queue",
        "image": "05_queue.png",
        "voice": "蒙版、贴纸、渲染队列，批量出片又快又稳。",
        "text": "蒙版贴纸 · 渲染队列 · 硬件加速",
        "zoom": 0.06,
    },
    {
        "id": "outro",
        "image": "06_outro.png",
        "voice": "闲鱼扫码找我，清影快速混剪，开箱即用。",
        "text": "闲鱼 · 2222015802752 · 扫码带走",
        "caption": False,
        "zoom": 0.04,
    },
]


def run(args: list[str]) -> None:
    result = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{' '.join(args)}\n{result.stderr}")


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


# ────────────────────────────── 配音 ──────────────────────────────


def synth_voice(beat: dict) -> Path:
    """逐句合成配音；已有文件直接复用（重跑不重复消耗网络）。"""
    target = VOICE / "beats" / f"{beat['id']}.mp3"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1024:
        return target

    import edge_tts

    async def _go() -> None:
        communicate = edge_tts.Communicate(beat["voice"], TTS_VOICE, rate=TTS_RATE)
        await communicate.save(str(target))

    asyncio.run(_go())
    print(f"OK 配音 {beat['id']}: {target.stat().st_size / 1024:.0f} KB")
    return target


def plan_durations(voice_durations: list[float]) -> list[float]:
    """片头/落版固定时长（落版要留时间读账号、扫码），功能镜头按配音长度分配剩余时间。

    总时长（含转场重叠）精确等于 TOTAL；若配音本身超预算，优先保证配音不被截断。
    """
    count = len(voice_durations)
    overlap = XFADE * (count - 1)
    budget = TOTAL + overlap

    intro = max(4.2, voice_durations[0] + 0.8)
    outro = max(4.8, voice_durations[-1] + 0.9)
    feature_voices = voice_durations[1:-1]
    floors = [max(3.6, duration + 0.6) for duration in feature_voices]

    remaining = budget - intro - outro
    if remaining > sum(floors):
        spare = remaining - sum(floors)
        weights = [duration for duration in feature_voices]
        total_weight = sum(weights) or 1.0
        features = [
            floor + spare * weight / total_weight for floor, weight in zip(floors, weights)
        ]
    else:
        features = floors

    durations = [intro, *features, outro]
    # 浮点误差归零：差值补到最长的功能镜头上，避免落版时间被吃掉。
    drift = budget - sum(durations)
    if features:
        longest = 1 + max(range(len(features)), key=lambda index: features[index])
        durations[longest] += drift
    else:
        durations[0] += drift
    return [round(max(duration, 3.0), 3) for duration in durations]


# ────────────────────────────── 画面 ──────────────────────────────


def render_clip(beat: dict, duration: float, *, fade_in: bool, fade_out: bool) -> Path:
    target = CLIPS / f"{beat['id']}.mp4"
    frames = max(int(duration * FPS), 2)
    filters = [
        f"zoompan=z='1+{beat['zoom']}*on/{frames}'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:fps={FPS}:s=1920x1080",
    ]
    if fade_in:
        filters.append("fade=t=in:st=0:d=0.5")
    if fade_out:
        filters.append(f"fade=t=out:st={max(duration - 0.6, 0):.3f}:d=0.6")
    filters.append("format=yuv420p")
    run([
        "-loop", "1", "-framerate", str(FPS), "-t", f"{duration:.3f}",
        "-i", str(SCENES / beat["image"]),
        "-vf", ",".join(filters),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        str(target),
    ])
    print(f"OK 镜头 {beat['id']}: {duration:.2f}s")
    return target


# ────────────────────────────── 声音 ──────────────────────────────


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels == 2:
        data = data.reshape(-1, 2)
    else:
        data = np.stack([data, data], axis=1)
    return data, rate


def write_wav(path: Path, data: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def build_voice_track(timeline: list[dict]) -> Path:
    master = np.zeros((int((TOTAL + 0.5) * VOICE_RATE), 2), dtype=np.float32)
    for entry in timeline:
        wav_tmp = OUT / "beats30" / f"{entry['id']}.wav"
        wav_tmp.parent.mkdir(parents=True, exist_ok=True)
        run(["-i", str(entry["voice_path"]), "-ar", str(VOICE_RATE), "-ac", "2", str(wav_tmp)])
        data, rate = read_wav(wav_tmp)
        assert rate == VOICE_RATE
        at = int(entry["start"] * VOICE_RATE)
        end = min(at + data.shape[0], master.shape[0])
        master[at:end] += data[: end - at]
    target = OUT / "voice30.wav"
    write_wav(target, master, VOICE_RATE)
    print("OK 配音轨", f"{master.shape[0] / VOICE_RATE:.1f}s")
    return target


def build_bgm_track() -> Path:
    bgm, rate = read_wav(ROOT / "music" / "bgm.wav")
    target_len = int(TOTAL * rate)
    if bgm.shape[0] < target_len:
        bgm = np.tile(bgm, (int(np.ceil(target_len / bgm.shape[0])), 1))
    bgm = bgm[:target_len].copy()
    ramp_in = int(1.2 * rate)
    ramp_out = int(2.6 * rate)
    bgm[:ramp_in] *= np.linspace(0.0, 1.0, ramp_in)[:, None]
    bgm[-ramp_out:] *= np.linspace(1.0, 0.0, ramp_out)[:, None]
    target = OUT / "bgm30.wav"
    write_wav(target, bgm * 0.26, rate)
    print("OK BGM 轨", f"{bgm.shape[0] / rate:.1f}s")
    return target


# ────────────────────────────── 字幕 ──────────────────────────────

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Promo,Microsoft YaHei UI,54,&H00FFFFFF,&H00FFFFFF,&H00141014,&H8C000000,1,0,0,0,100,100,0,0,1,2.8,1.2,2,120,120,46,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}:{minutes:02d}:{seconds % 60:05.2f}"


def srt_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def build_subtitles(timeline: list[dict]) -> tuple[Path, Path]:
    ass_lines = [ASS_HEADER]
    srt_blocks: list[str] = []
    for index, entry in enumerate(timeline, start=1):
        if not entry.get("caption", True):
            continue  # 片头/落版是纯文字画面，不再叠烧录字幕
        begin = max(entry["start"] + 0.15, 0.0)
        end = min(entry["start"] + entry["duration"] - XFADE / 2, TOTAL)
        ass_lines.append(
            f"Dialogue: 0,{ass_time(begin)},{ass_time(end)},Promo,,0,0,0,,{entry['text']}\n"
        )
        srt_blocks.append(
            f"{len(srt_blocks) + 1}\n{srt_time(begin)} --> {srt_time(end)}\n{entry['text']}\n"
        )
    ass_path = OUT / "promo30.ass"
    ass_path.write_text("".join(ass_lines), encoding="utf-8")
    srt_path = ROOT / "字幕-30s.srt"
    srt_path.write_text("\n".join(srt_blocks), encoding="utf-8-sig")
    shown = sum(1 for entry in timeline if entry.get("caption", True))
    print("OK 字幕", ass_path.name, f"{shown} 条（片头/落版不烧）")
    return ass_path, srt_path


# ────────────────────────────── 组装 ──────────────────────────────


def main() -> int:
    for directory in (OUT, CLIPS, VOICE / "beats"):
        directory.mkdir(parents=True, exist_ok=True)

    voice_paths = [synth_voice(beat) for beat in BEATS]
    voice_durations = [probe_duration(path) for path in voice_paths]
    durations = plan_durations(voice_durations)

    timeline: list[dict] = []
    cursor = 0.0
    for beat, path, duration in zip(BEATS, voice_paths, durations):
        timeline.append({**beat, "voice_path": path, "duration": duration, "start": round(cursor, 3)})
        cursor += duration - XFADE
    total = round(sum(durations) - XFADE * (len(durations) - 1), 3)
    print(f"成片总时长：{total:.2f}s（{len(timeline)} 个镜头）")
    for entry in timeline:
        print(f"  {entry['id']:<12} {entry['start']:6.2f}s +{entry['duration']:.2f}s")

    clips = [
        render_clip(
            entry,
            entry["duration"],
            fade_in=index == 0,
            fade_out=index == len(timeline) - 1,
        )
        for index, entry in enumerate(timeline)
    ]

    voice_track = build_voice_track(timeline)
    bgm_track = build_bgm_track()
    ass_path, srt_path = build_subtitles(timeline)

    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip.relative_to(ROOT))]
    inputs += ["-i", str(voice_track.relative_to(ROOT)), "-i", str(bgm_track.relative_to(ROOT))]

    filters: list[str] = []
    last = "[0:v]"
    offset = timeline[0]["duration"] - XFADE
    for index in range(1, len(clips)):
        label = f"[v{index}]"
        filters.append(
            f"{last}[{index}:v]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}{label}"
        )
        last = label
        if index < len(clips) - 1:
            offset += timeline[index]["duration"] - XFADE

    voice_idx = len(clips)
    bgm_idx = len(clips) + 1
    filters.append(f"[{voice_idx}:a]asplit=2[voice_main][voice_sc]")
    filters.append(
        f"[{bgm_idx}:a][voice_sc]sidechaincompress=threshold=0.05:ratio=7:attack=20:release=350[ducked]"
    )
    filters.append("[voice_main][ducked]amix=inputs=2:duration=first:normalize=0:weights=1.0 1.0[amixed]")
    filters.append(f"[amixed]volume=2dB,alimiter=limit=0.94,afade=t=out:st={TOTAL - 1.4:.3f}:d=1.4[aout]")
    filters.append(f"{last}subtitles=out/promo30.ass[vout]")

    final = ROOT / "清影快速混剪-宣传片-30s.mp4"
    run([
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "-t", f"{TOTAL:.3f}",
        str(final.relative_to(ROOT)),
    ])
    print("OK 成片", final.name, f"{probe_duration(final):.2f}s",
          f"{final.stat().st_size / 1024 / 1024:.1f} MB")
    print("OK 字幕", srt_path.name)
    (OUT / "timeline30.json").write_text(
        json.dumps(
            [
                {k: v for k, v in entry.items() if k != "voice_path"}
                for entry in timeline
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
