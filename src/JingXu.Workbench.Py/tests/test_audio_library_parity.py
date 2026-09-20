"""音频库对齐、下载错误映射与爬虫结果提取测试。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jingxu.infrastructure.audio_library import (
    CURRENT_SCHEMA_VERSION,
    AudioLibrary,
    AudioProbeError,
    AudioTrack,
    parse_audio_payload,
)
from jingxu.infrastructure.downloader import describe_http_error, log_download_error
from jingxu.ui.spider_page import extract_video_urls


def _track(path: Path, duration: float = 12.0) -> AudioTrack:
    return AudioTrack(path=path, duration=duration, sample_rate=44100, channels=2, codec="mp3")


class TestAudioLibrarySchema:
    def test_save_writes_schema_and_entry_fields(self, tmp_path: Path) -> None:
        audio = tmp_path / "bgm.mp3"
        audio.write_bytes(b"stub")
        library = AudioLibrary(tmp_path / "audio-library.json")

        assert library.add([_track(audio)]) == 1
        payload = json.loads((tmp_path / "audio-library.json").read_text(encoding="utf-8"))

        assert payload["schemaVersion"] == CURRENT_SCHEMA_VERSION
        entry = payload["entries"][0]
        assert entry["filePath"] == str(audio)
        assert entry["displayName"] == "bgm.mp3"
        assert entry["duration"] == pytest.approx(12.0)
        assert entry["lastUsedAt"] > 0
        assert len(entry["id"]) >= 8

    def test_duplicate_refreshes_and_keeps_id(self, tmp_path: Path) -> None:
        audio = tmp_path / "bgm.mp3"
        audio.write_bytes(b"stub")
        library = AudioLibrary(tmp_path / "audio-library.json")

        library.add([_track(audio, duration=5.0)])
        first = library.tracks[0]
        added = library.add([_track(audio, duration=9.0)])

        assert added == 0
        updated = library.tracks[0]
        assert updated.id == first.id
        assert updated.duration == pytest.approx(9.0)
        assert updated.last_used_at >= first.last_used_at

    def test_case_insensitive_path_dedupe(self, tmp_path: Path) -> None:
        audio = tmp_path / "BGM.MP3"
        audio.write_bytes(b"stub")
        library = AudioLibrary(tmp_path / "audio-library.json")
        library.add([_track(audio)])
        library.add([_track(Path(str(audio).upper()))])
        assert len(library.tracks) == 1

    def test_legacy_document_migrates(self, tmp_path: Path) -> None:
        audio = tmp_path / "old.mp3"
        audio.write_bytes(b"stub")
        store = tmp_path / "audio-library.json"
        store.write_text(
            json.dumps({"tracks": [{"path": str(audio), "duration": 3.0, "sample_rate": 48000, "channels": 1, "codec": "aac"}]}),
            encoding="utf-8",
        )

        library = AudioLibrary(store)
        assert len(library.tracks) == 1
        track = library.tracks[0]
        assert track.path == audio
        assert track.sample_rate == 48000
        assert track.id  # 自动补 ID

    def test_clear_returns_count_and_prune_missing(self, tmp_path: Path) -> None:
        audio = tmp_path / "bgm.mp3"
        audio.write_bytes(b"stub")
        library = AudioLibrary(tmp_path / "audio-library.json")
        library.add([_track(audio)])

        audio.unlink()
        assert library.prune_missing() == 1

        audio.write_bytes(b"stub")
        library.add([_track(audio)])
        assert library.clear() == 1
        assert library.tracks == []

    def test_recent_tracks_sorted_by_last_used(self, tmp_path: Path) -> None:
        first = tmp_path / "a.mp3"
        second = tmp_path / "b.mp3"
        first.write_bytes(b"x")
        second.write_bytes(b"x")
        library = AudioLibrary(tmp_path / "audio-library.json")
        library.add([_track(first)])
        time.sleep(0.01)
        library.add([_track(second)])
        library.touch(first)

        assert library.recent_tracks[0].path == first


class TestAudioProbeValidation:
    def test_zero_duration_rejected(self, tmp_path: Path) -> None:
        payload = {
            "streams": [{"codec_type": "audio", "sample_rate": "44100", "channels": 2, "codec_name": "mp3"}],
            "format": {"duration": "0"},
        }
        with pytest.raises(AudioProbeError, match="时长无效"):
            parse_audio_payload(payload, tmp_path / "a.mp3")

    def test_valid_payload(self, tmp_path: Path) -> None:
        payload = {
            "streams": [{"codec_type": "audio", "sample_rate": "48000", "channels": 2, "codec_name": "aac"}],
            "format": {"duration": "42.5"},
        }
        track = parse_audio_payload(payload, tmp_path / "a.m4a")
        assert track.duration == pytest.approx(42.5)
        assert track.sample_rate == 48000
        assert track.display_name == "a.m4a"


class TestDownloadErrorMapping:
    @pytest.mark.parametrize(
        ("status", "fragment"),
        [
            (401, "需要登录"),
            (403, "拒绝访问"),
            (404, "已失效"),
            (429, "过于频繁"),
            (503, "暂时不可用"),
            (500, "HTTP 500"),
        ],
    )
    def test_describe_http_error(self, status: int, fragment: str) -> None:
        assert fragment in describe_http_error(status)

    def test_log_download_error_writes_file(self, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path))
        log_download_error("https://example.com/video", "下载失败：测试")

        logs = list((tmp_path / "logs").glob("download-*.log"))
        assert logs
        content = logs[0].read_text(encoding="utf-8")
        assert "example.com/video" in content and "测试" in content


class TestSpiderUrlExtraction:
    class _Item:
        def __init__(self, url: str) -> None:
            self.video_url = url

    def test_extracts_and_dedupes(self) -> None:
        items = [self._Item("https://a/1"), self._Item("https://a/1"), self._Item("https://a/2")]
        assert extract_video_urls(items) == ["https://a/1", "https://a/2"]

    def test_handles_dicts_and_nested(self) -> None:
        retained = type("R", (), {"items": [self._Item("https://n/1")], "video_url": "https://n/0"})()
        assert extract_video_urls([{"video_url": "https://d/1"}, retained]) == [
            "https://d/1",
            "https://n/1",
            "https://n/0",
        ]

    def test_empty_input(self) -> None:
        assert extract_video_urls([]) == []
        assert extract_video_urls([object()]) == []


class TestUnsupportedDownloadUrl:
    """主页链接应给出可照做的说明，而不是抛 yt-dlp 原文。

    实测：用户从对标账号复制分享文案得到的是主页链接，粘到下载页后看到的是一大串
    ``Unsupported URL: https://live.kuaishou.com/profile/...``，因而误判为
    「下载功能失效」。
    """

    def test_detects_profile_urls(self) -> None:
        from jingxu.infrastructure.downloader import looks_like_profile_url

        assert looks_like_profile_url("https://www.douyin.com/user/MS4wLjABAAAAx") is True
        assert looks_like_profile_url("https://live.kuaishou.com/profile/abc?cc=x") is True
        assert looks_like_profile_url("https://www.douyin.com/video/712345") is False
        assert looks_like_profile_url("https://v.kuaishou.com/KoL53UgI") is False

    def test_profile_url_message_tells_user_what_to_do(self) -> None:
        from jingxu.infrastructure.downloader import describe_unsupported_url

        message = describe_unsupported_url("https://www.douyin.com/user/MS4wLjABAAAAx")
        assert "主页链接" in message
        assert "分享" in message  # 告诉用户怎么拿到正确的链接

    def test_other_unsupported_url_gets_generic_guidance(self) -> None:
        from jingxu.infrastructure.downloader import describe_unsupported_url

        message = describe_unsupported_url("https://example.com/weird-page")
        assert "支持" in message
        assert "分享链接" in message
        assert "主页链接" not in message
