"""失败任务诊断归档、磁盘预算与进程树守卫测试。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from jingxu.infrastructure.disk_space import (
    DiskSpaceError,
    Reservation,
    cleanup_stale_reservations,
    ensure_space,
    estimate_output_bytes,
    release,
    reserve,
)
from jingxu.infrastructure.diagnostic_store import (
    LOG_FOLDER,
    archive_failure,
    latest_diagnostics,
    trim_old_diagnostics,
)


class TestDiagnosticArchive:
    def test_archive_writes_logs(self, tmp_path: Path) -> None:
        archive = archive_failure(
            tmp_path,
            "job-123",
            log_text="渲染失败：编码器不可用",
            filter_text="[0:v]null[vout]",
            concat_text="file 'a.mp4'",
            stderr_text="ffmpeg stderr",
        )

        assert archive.directory == tmp_path / LOG_FOLDER / "job-123"
        assert (archive.directory / "render.log").read_text(encoding="utf-8").startswith("渲染失败")
        assert (archive.directory / "filter.filter").read_text(encoding="utf-8") == "[0:v]null[vout]"
        assert (archive.directory / "concat.txt").is_file()
        assert (archive.directory / "ffmpeg-stderr.log").read_text(encoding="utf-8") == "ffmpeg stderr"

    def test_trim_removes_age_expired_but_keeps_current(self, tmp_path: Path) -> None:
        old = archive_failure(tmp_path, "old-job", log_text="old")
        current = archive_failure(tmp_path, "current-job", log_text="current")
        stale_time = time.time() - 8 * 24 * 3600
        os.utime(old.directory, (stale_time, stale_time))

        removed = trim_old_diagnostics(tmp_path, current_job_id="current-job")

        assert removed == 1
        assert not old.directory.exists()
        assert current.directory.exists()

    def test_trim_by_total_size_keeps_newest(self, tmp_path: Path) -> None:
        small = archive_failure(tmp_path, "small", log_text="x")
        big = archive_failure(tmp_path, "big", log_text="y")
        big_file = big.directory / "filter.filter"
        big_file.write_text("z" * (70 * 1024 * 1024), encoding="utf-8")
        now = time.time()
        os.utime(small.directory, (now - 100, now - 100))
        os.utime(big.directory, (now, now))

        removed = trim_old_diagnostics(tmp_path)

        assert removed == 1
        assert big.directory.exists()

    def test_latest_diagnostics_sorted(self, tmp_path: Path) -> None:
        first = archive_failure(tmp_path, "first", log_text="1")
        second = archive_failure(tmp_path, "second", log_text="2")
        now = time.time()
        os.utime(first.directory, (now - 50, now - 50))
        os.utime(second.directory, (now, now))

        assert [path.name for path in latest_diagnostics(tmp_path)] == ["second", "first"]


class TestDiskSpace:
    def test_estimate_has_floor(self) -> None:
        assert estimate_output_bytes(0.0) == 64 * 1024 * 1024
        assert estimate_output_bytes(100.0) > 64 * 1024 * 1024

    def test_ensure_space_passes_for_small_request(self, tmp_path: Path) -> None:
        ensure_space(tmp_path / "out.mp4", 1024)

    def test_ensure_space_raises_for_absurd_request(self, tmp_path: Path) -> None:
        with pytest.raises(DiskSpaceError, match="磁盘空间不足"):
            ensure_space(tmp_path / "out.mp4", 1 << 62)

    def test_reservation_roundtrip_and_stale_cleanup(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path / "data"))
        reservation = reserve(tmp_path / "out.mp4", 1024)
        assert reservation.path.exists()
        payload = json.loads(reservation.path.read_text(encoding="utf-8"))
        assert payload["bytes"] == 1024 and payload["pid"] == os.getpid()

        release(reservation)
        assert not reservation.path.exists()

        stale = reserve(tmp_path / "out.mp4", 2048)
        payload = json.loads(stale.path.read_text(encoding="utf-8"))
        payload["created"] = time.time() - 48 * 3600
        payload["pid"] = 0
        stale.path.write_text(json.dumps(payload), encoding="utf-8")

        assert cleanup_stale_reservations() == 1
        assert not stale.path.exists()

    def test_release_is_idempotent(self, tmp_path: Path) -> None:
        release(Reservation(token="missing", path=tmp_path / "missing.json"))
