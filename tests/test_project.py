"""项目保存 / 打开：store 纯函数往返 + 主壳（ShellWindow）集成。"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import make_asset

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from jingxu.domain.subtitles import SubtitleCue  # noqa: E402
from jingxu.infrastructure.project_store import (  # noqa: E402
    CURRENT_SCHEMA_VERSION,
    PROJECT_SUFFIX,
    ProjectDocument,
    ProjectError,
    document_from_payload,
    load_project,
    project_snapshot,
    save_project,
)
from jingxu.infrastructure.queue import RenderQueue  # noqa: E402
from jingxu.ui.shell_window import ShellWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _sample_document() -> ProjectDocument:
    """含中文项目名与全部字段的样例文档。"""
    return ProjectDocument(
        name="中文项目·甲",
        groups=(("C:/素材/a.mp4", "C:/素材/b.mp4"), ("C:/素材/c.mp4",)),
        output_directory="C:/输出/分镜输出",
        composition={"output_prefix": "混剪", "seed": 42},
        overlays=({"source": "C:/素材/overlay.mp4", "start_seconds": 1.0},),
        stickers=({"source": "C:/素材/sticker.png"},),
        subtitles={"cues": [{"start": 0.0, "end": 1.0, "text": "你好"}]},
        recent_jobs=(
            {
                "name": "混剪_001",
                "state": "completed",
                "output_path": "C:/输出/a.mp4",
                "message": "完成",
            },
        ),
        created_at="2026-07-10T10:00:00+08:00",
    )


# ────────────────────────────── store 纯函数 ──────────────────────────────


def test_save_load_roundtrip_utf8_json_without_temp(tmp_path: Path) -> None:
    path = tmp_path / "项目.jxproj"
    document = _sample_document()

    saved = save_project(path, document)

    assert saved.created_at == document.created_at
    assert saved.modified_at
    assert saved.read_only is False
    assert path.is_file()
    assert list(tmp_path.glob("*.tmp")) == []

    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["schemaVersion"] == CURRENT_SCHEMA_VERSION
    assert payload["name"] == "中文项目·甲"
    assert "read_only" not in payload
    assert payload["groups"] == [["C:/素材/a.mp4", "C:/素材/b.mp4"], ["C:/素材/c.mp4"]]

    loaded = load_project(path)
    assert loaded == saved
    assert loaded.read_only is False


def test_project_snapshot_roundtrips_document() -> None:
    document = _sample_document()
    assert document_from_payload(project_snapshot(document)) == document


def test_newer_schema_version_loads_read_only(tmp_path: Path) -> None:
    path = tmp_path / "future.jxproj"
    path.write_text(
        json.dumps({"schemaVersion": 999, "name": "未来项目"}, ensure_ascii=False),
        encoding="utf-8",
    )

    document = load_project(path)
    assert document.read_only is True
    assert document.schema_version == 999
    assert document.name == "未来项目"
    assert document.groups == ((), ())

    with pytest.raises(ProjectError, match="仅可另存为新文件"):
        save_project(path, document, source_path=path)
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 999

    copy_path = tmp_path / "副本.jxproj"
    saved = save_project(copy_path, document, source_path=path)
    assert saved.read_only is False
    assert saved.schema_version == CURRENT_SCHEMA_VERSION
    assert load_project(copy_path).read_only is False


def test_load_rejects_missing_corrupt_and_non_object(tmp_path: Path) -> None:
    with pytest.raises(ProjectError):
        load_project(tmp_path / "不存在.jxproj")

    broken = tmp_path / "broken.jxproj"
    broken.write_text("{不是 JSON", encoding="utf-8")
    with pytest.raises(ProjectError):
        load_project(broken)

    array = tmp_path / "array.jxproj"
    array.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProjectError):
        load_project(array)


def test_document_from_payload_tolerates_missing_fields() -> None:
    document = document_from_payload(
        {"schemaVersion": 1, "groups": [["a.mp4"], ["b.mp4", 7]], "recentJobs": "bad"}
    )

    assert document.name == "未命名项目"
    assert document.groups == (("a.mp4",), ("b.mp4",))
    assert document.output_directory == ""
    assert document.overlays == ()
    assert document.stickers == ()
    assert document.recent_jobs == ()
    assert document.read_only is False


def test_failed_save_cleans_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "占位目录"
    target.mkdir()

    with pytest.raises(ProjectError):
        save_project(target, ProjectDocument())

    assert list(tmp_path.glob("*.tmp")) == []


# ────────────────────────────── 主壳集成 ──────────────────────────────

def _stub_probe(path, probe):  # noqa: ANN001, ANN202
    """stub 探测：保留真实路径（与生产 probe_media 一致）。"""
    return replace(
        make_asset(Path(path).name, duration=2.0, width=1080, height=1920),
        path=Path(path),
    )


@contextmanager
def _shell_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # noqa: ANN201
    monkeypatch.setenv("JINGXU_DATA_DIRECTORY", str(tmp_path / "data"))
    monkeypatch.setattr("jingxu.ui.shell_window.probe_media", _stub_probe)
    queue = RenderQueue(Path("ffmpeg"))
    window = ShellWindow(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"), queue=queue)
    window._suppress_close_prompt = True
    try:
        yield window
    finally:
        window._suppress_close_prompt = True
        window.close()
        queue.stop()


def _stub_files(tmp_path: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"stub")
        paths.append(path)
    return paths


def test_shell_save_then_open_restores_materials(
    qapp,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _shell_window(monkeypatch, tmp_path) as window:
        a, b = _stub_files(tmp_path, "a.mp4", "b.mp4")
        window._add_materials([str(a), str(b)])

        assert len(window._assets) == 2
        assert window._dirty is True
        assert "未保存" in window._save_state_label.text()

        project_path = tmp_path / "我的项目.jxproj"
        assert window.save_project(project_path) is True
        assert project_path.is_file()
        assert window._dirty is False
        assert window._save_state_label.text() == "已保存"
        assert window._project_label.text() == "未命名项目"
        assert "未命名项目" in window.windowTitle()

        window._clear_materials()
        assert window._assets == []
        assert window._dirty is True

        assert window.open_project(project_path) is True
        assert len(window._assets) == 2
        assert [asset.path for asset in window._assets] == [a, b]
        assert window._dirty is False
        assert window._save_state_label.text() == "已保存"
        assert load_project(project_path).groups[0] == (str(a), str(b))


def test_shell_project_roundtrip_layers_and_subtitles(
    qapp,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _shell_window(monkeypatch, tmp_path) as window:
        mask = tmp_path / "mask.mp4"
        mask.write_bytes(b"stub")
        window._overlay_store.add(mask)
        window._overlay_page.refresh_from_store()
        window._subtitle_store.document.cues.append(SubtitleCue(start=0.0, end=1.0, text="字幕一"))
        window._subtitle_page.refresh_from_store()

        project_path = tmp_path / "图层.jxproj"
        assert window.save_project(project_path) is True

        window._overlay_store.clear()
        window._overlay_page.refresh_from_store()
        window._subtitle_store.import_document({})
        window._subtitle_page.refresh_from_store()
        assert len(window._overlay_page._layers) == 0
        assert len(window._subtitle_page._cues) == 0

        assert window.open_project(project_path) is True
        assert len(window._overlay_page._layers) == 1
        assert len(window._overlay_store.layers) == 1
        assert len(window._subtitle_page._cues) == 1
        assert window._subtitle_page._cues[0].text == "字幕一"


def test_shell_read_only_project_rejected_on_overwrite(
    qapp,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _shell_window(monkeypatch, tmp_path) as window:
        read_only_path = tmp_path / "future.jxproj"
        read_only_path.write_text(
            json.dumps({"schemaVersion": 999, "name": "未来项目"}, ensure_ascii=False),
            encoding="utf-8",
        )

        assert window.open_project(read_only_path) is True
        assert "只读" in window._save_state_label.text()
        assert "只读" in window._inspector_save_label.text()

        assert window.save_project(read_only_path) is False
        assert "只读" in window._save_state_label.text()
        assert json.loads(read_only_path.read_text(encoding="utf-8"))["schemaVersion"] == 999

        copy_path = tmp_path / "另存.jxproj"
        assert window.save_project(copy_path) is True
        assert window._save_state_label.text() == "已保存"
        assert load_project(copy_path).schema_version == CURRENT_SCHEMA_VERSION


def test_shell_new_project_resets_content(
    qapp,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _shell_window(monkeypatch, tmp_path) as window:
        a = _stub_files(tmp_path, "a.mp4")[0]
        window._add_materials([str(a)])
        mask = tmp_path / "mask.png"
        mask.write_bytes(b"stub")
        window._overlay_store.add(mask)
        window._overlay_page.refresh_from_store()
        assert window._dirty is True

        window.new_project()

        assert window._assets == []
        assert len(window._overlay_page._layers) == 0
        assert window._project_label.text() == "未命名项目"
        assert window._save_state_label.text() == "已保存"
        assert window._dirty is False


def test_shell_close_prompt_discard_does_not_block(
    qapp,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _shell_window(monkeypatch, tmp_path) as window:
        monkeypatch.setattr(
            "jingxu.ui.shell_window.QMessageBox.question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
        )
        window._suppress_close_prompt = False
        window._mark_dirty()

        assert window.close() is True


def test_shell_save_appends_project_suffix(
    qapp,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _shell_window(monkeypatch, tmp_path) as window:
        assert window.save_project(tmp_path / "无后缀") is True
        assert (tmp_path / ("无后缀" + PROJECT_SUFFIX)).is_file()
