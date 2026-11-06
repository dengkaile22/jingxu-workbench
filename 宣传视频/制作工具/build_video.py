"""合成宣传片：场景微缩放 + 交叉转场 + 配音 + BGM（侧链闪避）+ 字幕烧录。

输入：scenes/*.png、voice/beats/*.mp3、voice/timings.json、music/bgm.wav
输出：out/清影快速混剪-宣传片.mp4（以及中间产物 out/scenes/*.mp4）
"""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

FFMPEG = Path(__file__).resolve().parent.parent.parent / "runtime" / "ffmpeg" / "ffmpeg.exe"
FFPROBE = Path(__file__).resolve().parent.parent.parent / "runtime" / "ffmpeg" / "ffprobe.exe"

ROOT = Path(__file__).resolve().parent.parent
SCENES = ROOT / "scenes"
VOICE = ROOT / "voice"
OUT = ROOT / "out"
SCENE_CLIPS = OUT / "scenes"
FPS = 30
XFADE = 0.5
FADE = 0.45

SCENE_IMG = {
    "intro": "00_intro.png",
    "composition": "01_composition.png",
    "spider": "02_spider.png",
    "subtitles": "03_subtitles.png",
    "overlays": "04_overlays.png",
    "queue": "05_queue.png",
    "outro": "06_outro.png",
}
ZOOM = {
    "intro": 0.05,
    "composition": 0.07,
    "spider": 0.07,
    "subtitles": 0.07,
    "overlays": 0.07,
    "queue": 0.07,
    "outro": 0.05,
}


def run(args: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or ROOT),
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


def render_scene_clip(scene_id: str, duration: float, fade_in: bool, fade_out: bool) -> Path:
    target = SCENE_CLIPS / f"{scene_id}.mp4"
    if target.exists() and abs(probe_duration(target) - duration) < 0.1:
        print(f"复用场景片段 {scene_id}")
        return target
    zoom = ZOOM[scene_id]
    frames = max(int(duration * FPS), 2)
    filters = [
        f"zoompan=z='1+{zoom}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps={FPS}:s=1920x1080",
    ]
    if fade_in:
        filters.append(f"fade=t=in:st=0:d={FADE}")
    if fade_out:
        filters.append(f"fade=t=out:st={max(duration - FADE, 0):.3f}:d={FADE}")
    filters.append("format=yuv420p")
    run([
        "-loop", "1", "-framerate", str(FPS), "-t", f"{duration:.3f}",
        "-i", f"scenes/{SCENE_IMG[scene_id]}",
        "-vf", ",".join(filters),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        str(target),
    ])
    print(f"OK 场景片段 {scene_id}: {duration:.2f}s")
    return target


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Promo,Microsoft YaHei UI,50,&H00FFFFFF,&H00FFFFFF,&H00141014,&H8C000000,1,0,0,0,100,100,0,0,1,2.6,1.2,2,120,120,44,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def build_subtitles(timeline: list[dict]) -> Path:
    lines = [ASS_HEADER]
    for entry in timeline:
        scene_start = entry["start"]
        for beat in entry["beats"]:
            begin = scene_start + beat["start"] - 0.12
            end = scene_start + beat["start"] + beat["duration"] + 0.35
            text = beat["text"].strip()
            lines.append(
                f"Dialogue: 0,{ass_time(begin)},{ass_time(end)},Promo,,0,0,0,,{text}\n"
            )
    target = OUT / "promo.ass"
    target.write_text("".join(lines), encoding="utf-8")
    print("OK 字幕", target.name, f"{len(lines) - 1} 条")
    return target


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SCENE_CLIPS.mkdir(parents=True, exist_ok=True)

    timings = json.loads((VOICE / "timings.json").read_text(encoding="utf-8"))

    # ── 时间轴：每幕的起始时间（含转场重叠）
    timeline: list[dict] = []
    cursor = 0.0
    for index, entry in enumerate(timings):
        entry = dict(entry)
        entry["start"] = round(cursor, 3)
        entry["index"] = index
        timeline.append(entry)
        cursor += entry["duration"] - XFADE
    total = cursor + XFADE
    print(f"成片总时长：{total:.2f}s")

    # ── 场景片段
    clips = []
    for entry in timeline:
        clip = render_scene_clip(
            entry["id"],
            entry["duration"],
            fade_in=entry["index"] == 0,
            fade_out=entry["index"] == len(timeline) - 1,
        )
        clips.append(clip)

    # ── 配音轨（按时间轴放置到主音轨）
    voice_rate = 44100
    master = np.zeros((int((total + 1.0) * voice_rate), 2), dtype=np.float32)
    for entry in timeline:
        for beat in entry["beats"]:
            mp3 = VOICE / "beats" / beat["file"]
            wav_tmp = OUT / "beats" / f"{beat['file']}.wav"
            wav_tmp.parent.mkdir(parents=True, exist_ok=True)
            if not wav_tmp.exists():
                run(["-i", str(mp3), "-ar", str(voice_rate), "-ac", "2", str(wav_tmp)])
            data, rate = read_wav(wav_tmp)
            assert rate == voice_rate
            at = int((entry["start"] + beat["start"]) * voice_rate)
            end = min(at + data.shape[0], master.shape[0])
            master[at:end] += data[: end - at]
    voice_path = OUT / "voice.wav"
    write_wav(voice_path, master, voice_rate)
    print("OK 配音轨", f"{master.shape[0] / voice_rate:.1f}s")

    # ── BGM：裁到成片长度 + 首尾淡入淡出
    bgm, bgm_rate = read_wav(ROOT / "music" / "bgm.wav")
    target_len = int(total * bgm_rate)
    if bgm.shape[0] < target_len:
        repeats = int(np.ceil(target_len / bgm.shape[0]))
        bgm = np.tile(bgm, (repeats, 1))
    bgm = bgm[:target_len].copy()
    ramp_in = int(1.6 * bgm_rate)
    ramp_out = int(3.2 * bgm_rate)
    bgm[:ramp_in] *= np.linspace(0.0, 1.0, ramp_in)[:, None]
    bgm[-ramp_out:] *= np.linspace(1.0, 0.0, ramp_out)[:, None]
    bgm_path = OUT / "bgm-trim.wav"
    write_wav(bgm_path, bgm * 0.30, bgm_rate)
    print("OK BGM 轨", f"{bgm.shape[0] / bgm_rate:.1f}s")

    # ── 字幕
    ass_path = build_subtitles(timeline)

    # ── 组装：xfade 链 + 音频混合 + 字幕烧录
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip.relative_to(ROOT))]
    inputs += ["-i", str(voice_path.relative_to(ROOT)), "-i", str(bgm_path.relative_to(ROOT))]

    filters = []
    last = "[0:v]"
    offset = timeline[0]["duration"] - XFADE
    for index in range(1, len(clips)):
        out_label = f"[v{index}]"
        filters.append(
            f"{last}[{index}:v]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}{out_label}"
        )
        last = out_label
        if index < len(clips) - 1:
            offset += timeline[index]["duration"] - XFADE

    voice_idx = len(clips)
    bgm_idx = len(clips) + 1
    filters.append(f"[{voice_idx}:a]asplit=2[voice_main][voice_sc]")
    filters.append(f"[{bgm_idx}:a][voice_sc]sidechaincompress=threshold=0.045:ratio=6:attack=25:release=380[ducked]")
    filters.append(f"[voice_main][ducked]amix=inputs=2:duration=first:normalize=0:weights=1.0 1.05[amixed]")
    filters.append("[amixed]volume=3dB,alimiter=limit=0.94,afade=t=out:st=%.3f:d=2.0[aout]" % (total - 2.0))
    filters.append(f"{last}subtitles=out/promo.ass[vout]")

    run([
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "-t", f"{total:.3f}",
        "out/清影快速混剪-宣传片.mp4",
    ])
    final = OUT / "清影快速混剪-宣传片.mp4"
    print("OK 成片", final, f"{probe_duration(final):.2f}s", f"{final.stat().st_size / 1024 / 1024:.1f} MB")
    import shutil
    root_final = ROOT / "清影快速混剪-宣传片.mp4"
    shutil.copy2(final, root_final)
    print("OK 已同步至", root_final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
