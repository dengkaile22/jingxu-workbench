"""音频库、下载链接提取与清理工具测试。"""

from __future__ import annotations

from pathlib import Path

from jingxu.infrastructure.audio_library import AudioLibrary, AudioTrack, parse_audio_payload
from jingxu.infrastructure.diagnostics import cleanup_temp_files
from jingxu.ui.download_page import extract_urls


def _track(audio_dir: Path, name: str) -> AudioTrack:
    return AudioTrack(path=audio_dir / name, duration=95.0, sample_rate=44100, channels=2, codec="mp3")


def test_audio_library_persists_and_deduplicates(tmp_path: Path) -> None:
    store = tmp_path / "audio-library.json"
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    for name in ("a.mp3", "b.mp3"):
        (audio_dir / name).write_bytes(b"stub")

    library = AudioLibrary(store)
    assert library.add([_track(audio_dir, "a.mp3"), _track(audio_dir, "a.mp3"), _track(audio_dir, "b.mp3")]) == 2
    assert library.add([_track(audio_dir, "a.mp3")]) == 0
    assert [track.display_name for track in library.tracks] == ["a.mp3", "b.mp3"]
    assert _track(audio_dir, "a.mp3").duration_text == "01:35"

    reloaded = AudioLibrary(store)
    assert [track.display_name for track in reloaded.tracks] == ["a.mp3", "b.mp3"]

    assert reloaded.remove(audio_dir / "a.mp3") is True
    assert [track.display_name for track in AudioLibrary(store).tracks] == ["b.mp3"]

    reloaded.clear()
    assert AudioLibrary(store).tracks == []


def test_audio_library_drops_missing_files_on_reload(tmp_path: Path) -> None:
    store = tmp_path / "audio-library.json"
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "gone.mp3").write_bytes(b"stub")

    library = AudioLibrary(store)
    library.add([_track(audio_dir, "gone.mp3")])
    (audio_dir / "gone.mp3").unlink()

    assert AudioLibrary(store).tracks == []


def test_parse_audio_payload_reads_stream_metadata() -> None:
    payload = {
        "streams": [{"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2}],
        "format": {"duration": "12.5"},
    }
    track = parse_audio_payload(payload, Path("bgm.m4a"))
    assert track.sample_rate == 48000
    assert track.channels == 2
    assert track.duration == 12.5


def test_extract_urls_deduplicates_and_trims_punctuation() -> None:
    text = """
    复制打开抖音，看看【某人的作品】 https://v.douyin.com/ABC123/ ，
    另一个 https://www.kuaishou.com/short-video/xyz。
    https://v.douyin.com/ABC123/
    """
    urls = extract_urls(text)
    assert urls == ["https://v.douyin.com/ABC123/", "https://www.kuaishou.com/short-video/xyz"]


def test_cleanup_temp_files_only_removes_known_prefix(tmp_path: Path) -> None:
    (tmp_path / "jingxu-py-old").mkdir()
    (tmp_path / "jingxu-py-old" / "concat.filter").write_text("x" * 1024, encoding="utf-8")
    (tmp_path / "unrelated").mkdir()
    (tmp_path / "unrelated" / "keep.txt").write_text("keep", encoding="utf-8")

    deleted, freed = cleanup_temp_files(tmp_path)

    assert deleted == 1
    assert freed >= 1024
    assert not (tmp_path / "jingxu-py-old").exists()
    assert (tmp_path / "unrelated" / "keep.txt").exists()
