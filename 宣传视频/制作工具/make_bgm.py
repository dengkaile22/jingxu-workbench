"""合成宣传片背景音乐：112 BPM 的轻快企业风电子，128 秒。

结构（与分镜对应）：
  0-13s      片头：氛围铺底 + 稀疏点音
  13-107s    主体：鼓组 + 贝斯 + 琶音，每 8 小节做一个呼吸
  64-71s     中段留白（字幕场景，鼓组撤下）
  107-128s   结尾：铺底渐弱
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "music" / "bgm.wav"
SR = 44100
BPM = 112.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT


def midi(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12.0)


def envelope(length: int, attack: float, decay: float, sr: int = SR) -> np.ndarray:
    a = max(int(attack * sr), 1)
    d = max(length - a, 1)
    env = np.concatenate([np.linspace(0.0, 1.0, a), np.exp(-np.linspace(0.0, decay, d))])
    return env[:length]


def tone(freq: float, dur: float, *, decay: float = 4.0, harmonics=(1.0, 0.4, 0.15)) -> np.ndarray:
    length = int(dur * SR)
    t = np.arange(length) / SR
    signal = np.zeros(length)
    for index, amp in enumerate(harmonics, start=1):
        signal += amp * np.sin(2 * np.pi * freq * index * t)
    return signal * envelope(length, 0.004, decay)


def pluck(freq: float, dur: float = 0.4) -> np.ndarray:
    return tone(freq, dur, decay=8.0, harmonics=(1.0, 0.5, 0.26, 0.1))


def pad(freqs, dur: float, *, detune: float = 0.004) -> np.ndarray:
    length = int(dur * SR)
    t = np.arange(length) / SR
    signal = np.zeros(length)
    for freq in freqs:
        signal += np.sin(2 * np.pi * freq * (1 - detune) * t)
        signal += np.sin(2 * np.pi * freq * (1 + detune) * t)
        signal += 0.3 * np.sin(2 * np.pi * freq * 2 * t)
    signal *= envelope(length, 0.9, 1.4)
    return signal / (len(freqs) * 2)


def kick() -> np.ndarray:
    length = int(0.3 * SR)
    t = np.arange(length) / SR
    freq = 148 * np.exp(-t * 24) + 46
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 12)


def snare() -> np.ndarray:
    rng = np.random.default_rng(7)
    length = int(0.2 * SR)
    t = np.arange(length) / SR
    return rng.uniform(-1, 1, length) * np.exp(-t * 28) * 0.7 + 0.35 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)


def hat(open_: bool = False) -> np.ndarray:
    rng = np.random.default_rng(11 if not open_ else 13)
    length = int((0.16 if open_ else 0.06) * SR)
    t = np.arange(length) / SR
    noise = rng.uniform(-1, 1, length) * np.exp(-t * (26 if open_ else 90))
    return np.diff(noise, prepend=0.0) * 0.5


def riser(dur: float) -> np.ndarray:
    rng = np.random.default_rng(23)
    length = int(dur * SR)
    t = np.arange(length) / SR
    noise = rng.uniform(-1, 1, length)
    env = (t / dur) ** 2.2
    return np.diff(noise * env, prepend=0.0) * 0.35


def place(track: np.ndarray, sound: np.ndarray, at: float, gain: float = 1.0) -> None:
    start = int(at * SR)
    if start >= track.shape[0] or start < 0:
        return
    end = min(start + sound.shape[0], track.shape[0])
    track[start:end] += sound[: end - start] * gain


PROGRESSION = [
    (48, 55, 60, 64),   # C
    (43, 50, 55, 59),   # G
    (45, 52, 57, 60),   # Am
    (41, 48, 53, 57),   # F
]


def compose(total_seconds: float = 128.0) -> np.ndarray:
    total = np.zeros(int(total_seconds * SR))
    bars = int(total_seconds / BAR) + 1
    main_start_bar, main_end_bar = 6, 50
    break_start_bar, break_end_bar = 30, 33
    outro_start_bar = 51

    for bar in range(bars):
        start = bar * BAR
        if start >= total_seconds:
            break
        notes = PROGRESSION[bar % len(PROGRESSION)]
        pad_gain = 0.30 if bar < main_start_bar or bar >= outro_start_bar else 0.24
        place(total, pad(tuple(midi(n) for n in notes), BAR * 1.02), start, pad_gain)

        if bar < main_start_bar:
            if bar % 2 == 0:
                place(total, pluck(midi(notes[2] + 24), 1.4), start + BEAT * (1 + (bar % 3)), 0.16)
            if bar == main_start_bar - 1:
                place(total, riser(BAR * 0.96), start + 0.1, 0.55)
            continue

        if bar >= outro_start_bar:
            if bar == outro_start_bar:
                place(total, hat(open_=True), start, 0.25)
            place(total, pluck(midi(notes[3] + 12), 1.6), start + BEAT * 2, 0.14)
            continue

        in_break = break_start_bar <= bar < break_end_bar
        phrase = (bar - main_start_bar) % 8

        if not in_break:
            place(total, kick(), start, 0.95)
            place(total, kick(), start + 2 * BEAT, 0.9)
            place(total, kick(), start + 3.5 * BEAT, 0.5 if phrase == 7 else 0.0)
            place(total, snare(), start + BEAT, 0.5)
            place(total, snare(), start + 3 * BEAT, 0.52)
            for step in range(8):
                if step % 2 == 1:
                    place(total, hat(), start + step * BEAT / 2, 0.32)
            if phrase in (3, 7):
                place(total, hat(open_=True), start + 3.5 * BEAT, 0.4)
        else:
            if bar == break_start_bar:
                place(total, hat(open_=True), start, 0.3)
            place(total, pluck(midi(notes[1] + 24), 2.0), start + BEAT * 2, 0.2)

        bass_note = notes[0] - 24
        for step in range(8 if not in_break else 4):
            at = start + step * BEAT / 2
            offset = (0, 0, 7, 0, 5, 0, 3, 7)[step % 8]
            place(total, tone(midi(bass_note + offset), 0.36, decay=6.5, harmonics=(1.0, 0.5)), at, 0.34)

        arp_gain = 0.16 if in_break else 0.22
        for step in range(8):
            at = start + step * BEAT / 2
            note = notes[step % len(notes)] + (12 if step % 4 < 2 else 24)
            place(total, pluck(midi(note), 0.34), at, arp_gain)

    # 结尾总渐弱
    tail = np.ones_like(total)
    fade_len = int(8.0 * SR)
    tail[-fade_len:] = np.linspace(1.0, 0.0, fade_len)
    return total * tail


def main() -> int:
    mono = compose()
    peak = np.max(np.abs(mono)) or 1.0
    mono = mono / peak * 0.86
    delay = int(0.011 * SR)
    right = np.concatenate([np.zeros(delay), mono[:-delay]])
    stereo = np.stack([mono, right], axis=1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(OUT), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())
    print("OK", OUT, f"{mono.shape[0] / SR:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
