"""ffprobe 扩展元数据：像素格式与显示旋转（硬件解码白名单的前置条件）。"""

from __future__ import annotations

from pathlib import Path

from conftest import make_asset

from jingxu.infrastructure.ffprobe import parse_probe_payload


def _payload(**video_overrides: object) -> dict:
    """构造最小 ffprobe JSON：format + 一个视频流（可覆盖字段）。"""
    video: dict = {
        "codec_type": "video",
        "codec_name": "h264",
        "pix_fmt": "yuv420p",
        "width": 1080,
        "height": 1920,
        "avg_frame_rate": "30/1",
        "r_frame_rate": "30/1",
    }
    video.update(video_overrides)
    return {
        "streams": [video],
        "format": {"duration": "12.5"},
    }


def test_parse_probe_payload_reads_pixel_format() -> None:
    asset = parse_probe_payload(_payload(), Path("素材.mp4"))
    assert asset.pixel_format == "yuv420p"


def test_parse_probe_payload_defaults_missing_pixel_format_to_empty() -> None:
    """缺 pix_fmt 时留空（空值在硬件白名单里会被拒绝，而不是被当作 yuv420p）。"""
    video = _payload()
    video["streams"][0].pop("pix_fmt")
    asset = parse_probe_payload(video, Path("素材.mp4"))
    assert asset.pixel_format == ""


def test_parse_probe_payload_reads_rotation_from_side_data() -> None:
    payload = _payload(
        side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90}]
    )
    asset = parse_probe_payload(payload, Path("竖屏.mp4"))
    assert asset.rotation_degrees == 90


def test_parse_probe_payload_falls_back_to_rotate_tag() -> None:
    payload = _payload(tags={"rotate": "270"})
    asset = parse_probe_payload(payload, Path("竖屏.mp4"))
    assert asset.rotation_degrees == 270


def test_parse_probe_payload_side_data_wins_over_tag() -> None:
    payload = _payload(
        side_data_list=[{"rotation": "180"}],
        tags={"rotate": "90"},
    )
    asset = parse_probe_payload(payload, Path("竖屏.mp4"))
    assert asset.rotation_degrees == 180


def test_parse_probe_payload_normalizes_rotation() -> None:
    """旋转统一为 0–359 的整数，便于白名单做「是否为零」的严格判断。"""
    payload = _payload(side_data_list=[{"rotation": "450"}])
    assert parse_probe_payload(payload, Path("a.mp4")).rotation_degrees == 90

    payload = _payload(side_data_list=[{"rotation": 360}])
    assert parse_probe_payload(payload, Path("a.mp4")).rotation_degrees == 0


def test_parse_probe_payload_tolerates_broken_rotation_values() -> None:
    payload = _payload(side_data_list=[{"rotation": "N/A"}, {"rotation": None}])
    assert parse_probe_payload(payload, Path("a.mp4")).rotation_degrees == 0

    payload = _payload(tags={"rotate": "not-a-number"})
    assert parse_probe_payload(payload, Path("a.mp4")).rotation_degrees == 0


def test_parse_probe_payload_without_rotation_is_zero() -> None:
    payload = _payload()
    assert parse_probe_payload(payload, Path("a.mp4")).rotation_degrees == 0


def test_make_asset_defaults_pass_hardware_whitelist_shape() -> None:
    """测试夹具默认值必须落在白名单内，避免硬件解码用例静默不生效。"""
    asset = make_asset()
    assert asset.video_codec == "h264"
    assert asset.pixel_format == "yuv420p"
    assert asset.rotation_degrees == 0
    assert asset.width % 2 == 0 and asset.height % 2 == 0


def test_make_asset_accepts_explicit_codec_and_audio_codec() -> None:
    asset = make_asset("b.mp4", video_codec="hevc", has_audio=False, audio_codec="")
    assert asset.video_codec == "hevc"
    assert asset.audio_codec == ""
    assert asset.has_audio is False
