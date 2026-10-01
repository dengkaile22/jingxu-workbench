"""Regression coverage for the September 29 issue screenshots."""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import make_asset, wait_until
from jingxu.application.composition_service import CompositionDraft, build_requests
from jingxu.domain.composition import OrderMode
from jingxu.domain.effects import FourScreenEffectPlan
from jingxu.domain.render import ProcessingMode, RenderSettings
from jingxu.domain.splitscreen import SplitMode, SplitScreenSpec
from jingxu.infrastructure.queue import JobState, RenderQueue
from jingxu.infrastructure.spider import SpiderRunResult


@pytest.mark.parametrize("four_flags", [(True, False), (False, True), (True, True)])
def test_queued_four_screen_batch_resumes_without_deadlock(tmp_path, four_flags):
    requests = build_requests(
        assets=[make_asset()],
        draft=CompositionDraft(batch_count=2),
        output_directory=tmp_path,
    )
    calls = []

    def runner(ffmpeg, request, **kwargs):
        calls.append(request.name)
        return request.output_path

    queue = RenderQueue(Path("unused"), runner=runner, max_concurrency=2)
    queue.pause()
    try:
        for request, is_four in zip(requests, four_flags):
            queue.enqueue(replace(request, four_screen=FourScreenEffectPlan() if is_four else None))
        queue.resume()
        wait_until(lambda: queue.active_count == 0, timeout=1.0)
        assert len(calls) == 2
        assert all(job.state is JobState.COMPLETED for job in queue.jobs)
    finally:
        queue.stop()


def test_four_screen_keeps_exclusive_access_with_waiting_followup(tmp_path):
    requests = build_requests(
        assets=[make_asset()], draft=CompositionDraft(batch_count=2), output_directory=tmp_path,
    )
    started = threading.Event()
    release = threading.Event()
    calls = []

    def runner(ffmpeg, request, **kwargs):
        calls.append(request.name)
        started.set()
        release.wait(timeout=3)
        return request.output_path

    queue = RenderQueue(Path("unused"), runner=runner, max_concurrency=2)
    queue.pause()
    try:
        first = queue.enqueue(replace(requests[0], four_screen=FourScreenEffectPlan()))
        second = queue.enqueue(requests[1])
        queue.resume()
        assert started.wait(timeout=1)
        states = {job.id: job.state for job in queue.jobs}
        assert states[first.id] is JobState.RUNNING
        assert states[second.id] is JobState.QUEUED
        release.set()
        wait_until(lambda: queue.active_count == 0)
        assert calls == [requests[0].name, requests[1].name]
    finally:
        release.set()
        queue.stop()


def _folder_assets(tmp_path):
    assets = []
    for index in range(1, 4):
        path = tmp_path / f"{index}.mp4"
        path.touch()
        assets.append(replace(make_asset(path.name), path=path))
    return assets


def test_double_screen_random_survives_importing_whole_folder(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jingxu.ui.composition_page import CompositionPage
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path / "data"))
    page = CompositionPage()
    try:
        page.set_materials(_folder_assets(tmp_path))
        page._double_enable.setChecked(True)
        page._split_random.setChecked(True)
        draft = page.draft()
        assert draft.split is not None and not draft.split.same_source
        requests = build_requests(assets=page._assets, draft=draft, output_directory=tmp_path / "out")
        assert requests[0].split.uses_aux()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


def test_random_split_picks_other_imported_video_for_each_clip(tmp_path):
    assets = _folder_assets(tmp_path)
    draft = CompositionDraft(
        mode=OrderMode.SEQUENTIAL,
        split=SplitScreenSpec(mode=SplitMode.DOUBLE_H, random_from_source_folder=True),
    )
    request = build_requests(assets=assets, draft=draft, output_directory=tmp_path / "out")[0]
    again = build_requests(assets=assets, draft=draft, output_directory=tmp_path / "out")[0]
    assert request.split == again.split
    for index, asset in enumerate(request.plan.assets):
        path = request.split.aux_paths[request.split.aux_index_for(index, 1)]
        assert path != asset.path
        assert path in {a.path for a in assets}


def test_random_split_uses_each_sources_folder_and_handles_single_video(tmp_path):
    folders = [tmp_path / name for name in ("first", "second", "single")]
    for folder in folders:
        folder.mkdir()
    groups = [_folder_assets(folder) for folder in folders[:2]]
    only = folders[2] / "only.mp4"
    only.touch()
    assets = [groups[0][0], groups[1][0], replace(make_asset("only.mp4"), path=only)]
    draft = CompositionDraft(
        mode=OrderMode.SEQUENTIAL,
        split=SplitScreenSpec(mode=SplitMode.DOUBLE_H, random_from_source_folder=True, start_index=1),
    )
    request = build_requests(assets=assets, draft=draft, output_directory=tmp_path / "out")[0]
    assert request.split.aux_indices_by_clip[0] == ()
    for index in (1, 2):
        chosen = request.split.aux_paths[request.split.aux_index_for(index, 1)]
        assert chosen.parent == assets[index].path.parent
    assert request.split.aux_paths[request.split.aux_index_for(1, 1)] != assets[1].path
    assert request.split.aux_paths[request.split.aux_index_for(2, 1)] == only


def test_random_split_varies_across_batch_and_is_repeatable(tmp_path):
    assets = _folder_assets(tmp_path)
    draft = CompositionDraft(
        mode=OrderMode.CUSTOM, sequence_text="1;1;1",
        split=SplitScreenSpec(mode=SplitMode.DOUBLE_H, random_from_source_folder=True),
    )
    def choices():
        requests = build_requests(assets=assets, draft=draft, output_directory=tmp_path / "out")
        return [r.split.aux_paths[r.split.aux_index_for(0, 1)] for r in requests]
    picked = choices()
    assert picked == choices()
    assert picked[0] != picked[1]
    assert all(path != assets[0].path for path in picked)


@pytest.mark.integration
@pytest.mark.parametrize("start_index", [0, 1])
def test_random_double_screen_renders_other_video_on_right(tmp_path, start_index):
    from jingxu.infrastructure.ffmpeg_runner import run_render
    from jingxu.infrastructure.ffprobe import probe_media
    from jingxu.infrastructure.runtime import find_tool

    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are required")
    assets = []
    for color in ("red", "blue"):
        path = tmp_path / f"{color}.mp4"
        subprocess.run([
            str(ffmpeg), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            f"color={color}:s=160x160:r=8:d=1", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(path),
        ], check=True, capture_output=True)
        assets.append(probe_media(path, ffprobe))
    draft = CompositionDraft(
        mode=OrderMode.SEQUENTIAL,
        settings=RenderSettings(width=320, height=160, fps=8, processing=ProcessingMode.CPU, preset="ultrafast"),
        split=SplitScreenSpec(
            mode=SplitMode.DOUBLE_H, random_from_source_folder=True,
            feather=False, start_index=start_index,
        ),
    )
    request = build_requests(assets=assets, draft=draft, output_directory=tmp_path / "out")[0]
    output = run_render(ffmpeg, request)
    info = probe_media(output, ffprobe)
    assert (info.width, info.height) == (320, 160)
    assert info.duration == pytest.approx(2.0, abs=0.2)
    for clip_index in (0, 1):
        frame = subprocess.run([
            str(ffmpeg), "-loglevel", "error", "-ss", str(clip_index + 0.5), "-i", str(output),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ], check=True, capture_output=True).stdout
        colors = []
        for x in (120, 200):
            offset = (80 * 320 + x) * 3
            red, _green, blue = frame[offset:offset + 3]
            assert max(red, blue) > 180
            colors.append("red" if red > blue else "blue")
        expected = ["red", "blue"] if clip_index == 0 else ["blue", "red"]
        if clip_index < start_index:
            expected[1] = expected[0]
        assert colors == expected


@pytest.mark.parametrize("fuzzy", [False, True])
@pytest.mark.parametrize("mode", ["accounts", "total", "likes"])
def test_retention_thresholds_do_not_mix_platforms(fuzzy, mode):
    from core.analyzer import ProductAnalyzer
    from core.models import OccurrenceFilterConfig, VideoProductItem

    def item(platform, likes):
        return VideoProductItem(
            platform=platform, account_name=platform, account_id=platform,
            video_id=platform, video_title="洗发水", video_url=f"https://example.com/{platform}",
            publish_time=0, publish_time_str="2026-09-29 10:00:00",
            product_id="p1", product_name="生姜洗发水500ml", like_count=likes,
        )

    analyzer = ProductAnalyzer(OccurrenceFilterConfig(
        min_account_count=2, min_total_occurrences=2, min_like_count=100,
        filter_by=mode, enable_fuzzy_cluster=fuzzy,
    ))
    retained, aggregated = analyzer.aggregate_and_filter([item("douyin", 10), item("kuaishou", 200)])
    assert len(aggregated) == 2
    assert {p.platform for p in aggregated} == {"douyin", "kuaishou"}
    if mode == "likes":
        assert [p.platform for p in retained] == ["kuaishou"]
        assert retained[0].sample_video_url == "https://example.com/kuaishou"
    else:
        assert retained == []


def test_no_retained_products_means_no_visible_or_downloadable_rows():
    result = SpiderRunResult(
        success=True, message="无达标商品", retained=(),
        items=({"video_url": "https://example.com/below-threshold"},),
    )
    assert result.effective_entries == ()
    assert result.video_urls == ()
    restored = SpiderRunResult.from_dict(result.to_dict())
    assert restored.effective_entries == ()
    assert restored.video_urls == ()


def test_download_urls_exclude_rejected_raw_records():
    result = SpiderRunResult(
        success=True, message="ok",
        retained=({"sample_video_url": "https://example.com/retained"},),
        items=({"video_url": "https://example.com/rejected"},),
    )
    assert result.video_urls == ("https://example.com/retained",)
