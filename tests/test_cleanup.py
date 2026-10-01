"""临时缓存与输出半成品清理测试（对齐 .NET 的已知范围清理）。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from jingxu.infrastructure.diagnostics import cleanup_temp_files, cleanup_workspace


def test_cleanup_temp_files_removes_known_items(tmp_path: Path) -> None:
    """顶层 jingxu-py-* 与 jingxu-feather-*.png 被删，无关文件保留。"""
    old = tmp_path / "jingxu-py-old"
    old.mkdir()
    (old / "concat.filter").write_text("x" * 1024, encoding="utf-8")
    feather = tmp_path / "jingxu-feather-abc.png"
    feather.write_bytes(b"png" * 4)
    (tmp_path / "unrelated").mkdir()
    (tmp_path / "unrelated" / "keep.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "other-feather.png").write_bytes(b"keep")

    deleted, freed = cleanup_temp_files(tmp_path)

    assert deleted == 2
    assert freed >= 1024 + 12
    assert not old.exists()
    assert not feather.exists()
    assert (tmp_path / "unrelated" / "keep.txt").exists()
    assert (tmp_path / "other-feather.png").exists()


def test_cleanup_temp_files_removes_known_session_directories(tmp_path: Path) -> None:
    """固定会话目录整体删除，内部 GUID/会话子目录随父目录一并清理。"""
    session = tmp_path / "jingxu-whisper" / "session1"
    session.mkdir(parents=True)
    (session / "audio.wav").write_bytes(b"wav")
    ocr = tmp_path / "jingxu-ocr" / "g1"
    ocr.mkdir(parents=True)
    (ocr / "frame.png").write_bytes(b"ocr")

    deleted, freed = cleanup_temp_files(tmp_path)

    assert deleted == 2
    assert freed >= 6
    assert not (tmp_path / "jingxu-whisper").exists()
    assert not (tmp_path / "jingxu-ocr").exists()


def test_cleanup_temp_files_removes_orphan_ocr_sessions(tmp_path: Path) -> None:
    """异常中断遗留的 jingxu-ocr-* 会话目录也被回收。"""
    orphan = tmp_path / "jingxu-ocr-ab12cd34-xyz"
    orphan.mkdir()
    (orphan / "frame_0001.png").write_bytes(b"png")

    deleted, freed = cleanup_temp_files(tmp_path)

    assert deleted == 1
    assert freed >= 3
    assert not orphan.exists()


def test_cleanup_temp_files_respects_protected_paths(tmp_path: Path) -> None:
    """保护集内的 jingxu-py-live 不删、不计数，其他候选照删。"""
    live = tmp_path / "jingxu-py-live"
    live.mkdir()
    (live / "work.filter").write_text("live", encoding="utf-8")
    (tmp_path / "jingxu-py-old").mkdir()

    deleted, freed = cleanup_temp_files(tmp_path, protected_paths=[live])

    assert deleted == 1
    assert freed == 0
    assert live.exists()
    assert not (tmp_path / "jingxu-py-old").exists()


def test_cleanup_workspace_removes_only_stale_parts(tmp_path: Path) -> None:
    """输出目录只删过期半成品；新半成品与保护半成品保留且计入 skipped。"""
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    stale_seconds = 2 * 3600
    old_part = output / "old.part.mp4"
    old_part.write_bytes(b"x" * 2048)
    fresh_part = output / "fresh.part.mp4"
    fresh_part.write_bytes(b"y" * 1024)
    protected_part = output / "protected.part.mp4"
    protected_part.write_bytes(b"z" * 512)
    finished = output / "final.mp4"
    finished.write_bytes(b"final")

    old_time = time.time() - stale_seconds
    os.utime(old_part, (old_time, old_time))
    os.utime(protected_part, (old_time, old_time))

    report = cleanup_workspace(
        temp_directory=temp_root,
        protected_paths=[protected_part],
        output_directories=[output],
        stale_part_seconds=3600.0,
    )

    assert report.deleted == 1
    assert report.freed_bytes >= 2048
    assert report.skipped >= 1
    assert not old_part.exists()
    assert fresh_part.exists()
    assert protected_part.exists()
    assert finished.exists()


def test_cleanup_workspace_is_idempotent(tmp_path: Path) -> None:
    """二次清理没有新候选，deleted 归零。"""
    temp_root = tmp_path / "temp"
    (temp_root / "jingxu-py-old").mkdir(parents=True)
    output = tmp_path / "output"
    output.mkdir()
    old_part = output / "old.part.mp4"
    old_part.write_bytes(b"x" * 128)
    old_time = time.time() - 2 * 3600
    os.utime(old_part, (old_time, old_time))

    first = cleanup_workspace(temp_directory=temp_root, output_directories=[output])
    second = cleanup_workspace(temp_directory=temp_root, output_directories=[output])

    assert first.deleted == 2
    assert second.deleted == 0
    assert second.freed_bytes == 0
