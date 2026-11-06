"""合成 4 首演示 BGM（用于「音频库」截图），numpy 简易合成。

风格：轻快电子 / 温暖叙事 / 动感节拍 / 舒缓氛围。
输出 WAV 后转 MP3（192k），与真实素材库文件形态一致。
"""

from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

FFMPEG = Path(__file__).resolve().parents[2] / "runtime" / "ffmpeg" / "ffmpeg.exe"

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
AUDIO = DEMO / "audio"
SR = 44100


def midi(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12.0)


def envelope(length: int, attack: float, decay: float, sr: int = SR) -> np.ndarray:
    a = max(int(attack * sr), 1)
    d = max(length - a, 1)
    env = np.concatenate(
        [np.linspace(0.0, 1.0, a), np.exp(-np.linspace(0.0, decay, d))]
    )
    return env[:length]


def tone(freq: float, dur: float, *, decay: float = 4.0, harmonics: tuple[float, ...] = (1.0, 0.4, 0.15)) -> np.ndarray:
    length = int(dur * SR)
    t = np.arange(length) / SR
    signal = np.zeros(length)
    for index, amp in enumerate(harmonics, start=1):
        signal += amp * np.sin(2 * np.pi * freq * index * t)
    signal *= envelope(length, 0.005, decay)
    return signal


def pluck(freq: float, dur: float = 0.45) -> np.ndarray:
    return tone(freq, dur, decay=9.0, harmonics=(1.0, 0.5, 0.28, 0.12))


def pad(freqs: tuple[float, ...], dur: float) -> np.ndarray:
    length = int(dur * SR)
    t = np.arange(length) / SR
    signal = np.zeros(length)
    for freq in freqs:
        signal += np.sin(2 * np.pi * freq * t) * (1.0 + 0.06 * np.sin(2 * np.pi * 0.7 * t))
    signal *= envelope(length, 0.6, 1.2)
    return signal / max(len(freqs), 1)


def kick() -> np.ndarray:
    length = int(0.32 * SR)
    t = np.arange(length) / SR
    freq = 150 * np.exp(-t * 22) + 44
    signal = np.sin(2 * np.pi * np.cumsum(freq) / SR)
    return signal * np.exp(-t * 13)


def snare() -> np.ndarray:
    rng = np.random.default_rng(7)
    length = int(0.22 * SR)
    t = np.arange(length) / SR
    noise = rng.uniform(-1, 1, length) * np.exp(-t * 26)
    body = 0.4 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
    return noise * 0.6 + body


def hat() -> np.ndarray:
    rng = np.random.default_rng(11)
    length = int(0.07 * SR)
    t = np.arange(length) / SR
    noise = rng.uniform(-1, 1, length) * np.exp(-t * 90)
    return np.diff(noise, prepend=0.0) * 0.5


def place(track: np.ndarray, sound: np.ndarray, at: float, gain: float = 1.0) -> None:
    start = int(at * SR)
    end = start + sound.shape[0]
    if start >= track.shape[0]:
        return
    end = min(end, track.shape[0])
    track[start:end] += sound[: end - start] * gain


def normalize(signal: np.ndarray, peak: float = 0.9) -> np.ndarray:
    top = np.max(np.abs(signal)) or 1.0
    return signal / top * peak


def write_wav(path: Path, stereo: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(stereo, -1.0, 1.0)
    pcm = (data * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())


def to_stereo(mono: np.ndarray, width: float = 0.012) -> np.ndarray:
    delay = int(width * SR)
    left = mono.copy()
    right = np.concatenate([np.zeros(delay), mono[:-delay]]) if delay else mono.copy()
    return np.stack([left, right], axis=1)


def track_upbeat(bars: int = 8) -> np.ndarray:
    bpm = 124.0
    beat = 60.0 / bpm
    total = bars * 4 * beat + 1.0
    out = np.zeros(int(total * SR))
    progression = [(60, 64, 67), (55, 59, 62), (57, 60, 64), (53, 57, 60)]
    for bar in range(bars):
        chord_notes = progression[bar % len(progression)]
        start = bar * 4 * beat
        place(out, pad(tuple(midi(n - 12) for n in chord_notes), 4 * beat), start, 0.30)
        place(out, kick(), start, 0.9)
        place(out, kick(), start + 2 * beat, 0.9)
        for step in range(8):
            at = start + step * beat / 2
            place(out, hat(), at, 0.35 if step % 2 else 0.5)
        for step in range(8):
            at = start + step * beat / 2
            note = chord_notes[step % 3] + (12 if step % 4 == 3 else 0)
            place(out, pluck(midi(note), 0.35), at, 0.32)
        bass = chord_notes[0] - 24
        for step in range(4):
            place(out, tone(midi(bass + (0 if step < 3 else 2)), beat * 0.9, decay=6, harmonics=(1.0, 0.3)), start + step * beat, 0.42)
    return normalize(out)


def track_warm(bars: int = 6) -> np.ndarray:
    bpm = 88.0
    beat = 60.0 / bpm
    total = bars * 4 * beat + 2.0
    out = np.zeros(int(total * SR))
    progression = [(53, 57, 60, 64), (48, 52, 55, 59), (55, 59, 62, 65), (50, 53, 57, 60)]
    for bar in range(bars):
        notes = progression[bar % len(progression)]
        start = bar * 4 * beat
        place(out, pad(tuple(midi(n) for n in notes), 4 * beat), start, 0.42)
        for step in range(3):
            at = start + step * beat * 1.2
            note = notes[(step + bar) % len(notes)] + 12
            place(out, pluck(midi(note), 1.2), at, 0.30)
    return normalize(out, 0.85)


def track_beat(bars: int = 8) -> np.ndarray:
    bpm = 112.0
    beat = 60.0 / bpm
    total = bars * 4 * beat + 1.0
    out = np.zeros(int(total * SR))
    progression = [(57, 60, 64), (55, 59, 62), (53, 57, 60), (55, 58, 62)]
    rng = np.random.default_rng(3)
    for bar in range(bars):
        chord_notes = progression[bar % len(progression)]
        start = bar * 4 * beat
        place(out, pad(tuple(midi(n - 12) for n in chord_notes), 4 * beat), start, 0.26)
        for step in range(4):
            place(out, kick(), start + step * beat, 1.0 if step % 2 == 0 else 0.75)
            if step in (1, 3):
                place(out, snare(), start + step * beat, 0.55)
            place(out, hat(), start + step * beat + beat / 2, 0.35)
        bass = chord_notes[0] - 24
        for step in range(8):
            at = start + step * beat / 2
            note = bass + (0, 0, 3, 5)[step % 4]
            place(out, tone(midi(note), 0.4, decay=7, harmonics=(1.0, 0.5)), at, 0.4)
        lead = chord_notes[2] + 12
        for step in range(4):
            if rng.random() < 0.6:
                place(out, pluck(midi(lead + (0, 4, 7, 12)[step % 4]), 0.5), start + step * beat, 0.2)
    return normalize(out)


def track_calm(bars: int = 5) -> np.ndarray:
    bpm = 76.0
    beat = 60.0 / bpm
    total = bars * 4 * beat + 3.0
    out = np.zeros(int(total * SR))
    progression = [(48, 55, 59, 64), (45, 52, 57, 60), (41, 48, 52, 57), (43, 50, 55, 59)]
    for bar in range(bars):
        notes = progression[bar % len(progression)]
        start = bar * 4 * beat
        place(out, pad(tuple(midi(n) for n in notes), 4 * beat), start, 0.5)
        place(out, pluck(midi(notes[2] + 12), 2.0), start + beat, 0.18)
        place(out, pluck(midi(notes[1] + 24), 2.0), start + 3 * beat, 0.12)
    return normalize(out, 0.8)


def wav_to_mp3(wav_path: Path, mp3_path: Path, *, bitrate: str = "192k") -> None:
    result = subprocess.run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(wav_path),
            "-codec:a", "libmp3lame", "-b:a", bitrate,
            "-metadata", "title=" + mp3_path.stem,
            str(mp3_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def main() -> int:
    specs = [
        ("热门BGM_轻快电子", track_upbeat),
        ("热门BGM_温暖叙事", track_warm),
        ("热门BGM_动感节拍", track_beat),
        ("热门BGM_舒缓氛围", track_calm),
    ]
    AUDIO.mkdir(parents=True, exist_ok=True)
    for name, builder in specs:
        mono = builder()
        wav_path = AUDIO / f"{name}.wav"
        mp3_path = AUDIO / f"{name}.mp3"
        write_wav(wav_path, to_stereo(mono))
        wav_to_mp3(wav_path, mp3_path)
        print("OK", mp3_path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
