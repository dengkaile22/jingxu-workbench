"""贴纸素材库与「随机贴纸库」选择：库的持久化、确定性洗牌与边界。

对齐 .NET ``StickerEditorViewModel`` 的语义：

* 素材库是导入贴纸的落点，与轨道分离；轨道由用户在库里点「添加」生成；
* 「随机贴纸库」在渲染时把轨道素材替换为库中随机一款，但随机必须是**确定性**
  的——同一成片序号必得同一结果，一个成片内多条轨道不重复。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jingxu.infrastructure.sticker_library import (
    LIBRARY_FILE_NAME,
    STICKER_SUFFIXES,
    StickerEntry,
    StickerLibrary,
    filter_sticker_paths,
    select_random_sticker,
)


def _make_files(tmp_path: Path, *names: str) -> list[Path]:
    created: list[Path] = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"stub")
        created.append(path)
    return created


# ── 素材库：登记 / 去重 / 持久化 ────────────────────────────────────────────


def test_library_starts_empty(tmp_path: Path) -> None:
    assert StickerLibrary(tmp_path / LIBRARY_FILE_NAME).entries == []


def test_library_add_and_count(tmp_path: Path) -> None:
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    files = _make_files(tmp_path, "a.png", "b.webp", "c.gif")

    assert library.add(files) == 3
    assert len(library.entries) == 3


def test_library_rejects_unsupported_suffix(tmp_path: Path) -> None:
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    files = _make_files(tmp_path, "a.png", "note.txt", "video.avi")

    assert library.add(files) == 1
    assert [entry.path.name for entry in library.entries] == ["a.png"]


def test_filter_keeps_only_sticker_formats(tmp_path: Path) -> None:
    files = _make_files(tmp_path, "a.png", "b.mp4", "c.txt", "d.psd")
    kept = filter_sticker_paths(files)
    assert [path.name for path in kept] == ["a.png", "b.mp4"]


def test_filter_deduplicates_case_insensitively(tmp_path: Path) -> None:
    """Windows 路径不区分大小写，同一文件的两种写法只应登记一次。"""
    path = _make_files(tmp_path, "a.png")[0]
    kept = filter_sticker_paths([path, Path(str(path).upper())])
    assert len(kept) == 1


def test_library_reimport_does_not_duplicate(tmp_path: Path) -> None:
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    files = _make_files(tmp_path, "a.png")

    assert library.add(files) == 1
    assert library.add(files) == 0
    assert len(library.entries) == 1


def test_library_newest_first(tmp_path: Path) -> None:
    """最新导入的排最前，便于「刚导入就能加轨道」。"""
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    library.add(_make_files(tmp_path, "first.png"))
    library.add(_make_files(tmp_path, "second.png"))

    assert [entry.path.name for entry in library.entries] == ["second.png", "first.png"]


def test_library_persists_and_reloads(tmp_path: Path) -> None:
    store = tmp_path / LIBRARY_FILE_NAME
    files = _make_files(tmp_path, "a.png", "b.png")
    StickerLibrary(store).add(files)

    restored = StickerLibrary(store)
    assert len(restored.entries) == 2
    assert {entry.path.name for entry in restored.entries} == {"a.png", "b.png"}


def test_library_survives_broken_json(tmp_path: Path) -> None:
    store = tmp_path / LIBRARY_FILE_NAME
    store.write_text("{not json", encoding="utf-8")
    assert StickerLibrary(store).entries == []


def test_library_remove_by_id(tmp_path: Path) -> None:
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    library.add(_make_files(tmp_path, "a.png", "b.png"))
    target = library.entries[0]

    assert library.remove(target.id) is True
    assert len(library.entries) == 1
    assert library.remove("不存在") is False


def test_library_clear_keeps_files_on_disk(tmp_path: Path) -> None:
    """清空素材库不应删除用户的贴纸文件。"""
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    files = _make_files(tmp_path, "a.png", "b.png")
    library.add(files)

    assert library.clear() == 2
    assert library.entries == []
    assert all(path.is_file() for path in files)


def test_library_prune_removes_missing_files(tmp_path: Path) -> None:
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    files = _make_files(tmp_path, "a.png", "b.png")
    library.add(files)
    files[0].unlink()

    assert library.prune_missing() == 1
    assert len(library.entries) == 1


def test_entry_reports_kind(tmp_path: Path) -> None:
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    library.add(_make_files(tmp_path, "still.png", "clip.mp4"))
    kinds = {entry.path.name: entry.kind_text for entry in library.entries}
    assert kinds == {"still.png": "图片", "clip.mp4": "视频"}


def test_entry_id_is_stable_across_reload(tmp_path: Path) -> None:
    """ID 稳定，界面才能按 ID 定位条目。"""
    store = tmp_path / LIBRARY_FILE_NAME
    library = StickerLibrary(store)
    library.add(_make_files(tmp_path, "a.png"))
    original = library.entries[0].id

    assert StickerLibrary(store).entries[0].id == original


def test_sources_are_unique_paths(tmp_path: Path) -> None:
    library = StickerLibrary(tmp_path / LIBRARY_FILE_NAME)
    library.add(_make_files(tmp_path, "a.png", "b.png"))
    assert len(library.sources) == len(set(library.sources)) == 2


def test_schema_is_versioned(tmp_path: Path) -> None:
    store = tmp_path / LIBRARY_FILE_NAME
    StickerLibrary(store).add(_make_files(tmp_path, "a.png"))
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert "filePath" in payload["entries"][0]


def test_sticker_suffixes_include_images_and_video() -> None:
    assert ".png" in STICKER_SUFFIXES and ".webp" in STICKER_SUFFIXES
    assert ".mp4" in STICKER_SUFFIXES and ".mov" in STICKER_SUFFIXES


# ── 随机贴纸库：确定性选择 ──────────────────────────────────────────────────


def _sources(tmp_path: Path, count: int) -> list[Path]:
    return _make_files(tmp_path, *[f"sticker{index}.png" for index in range(count)])


def test_random_selection_is_reproducible(tmp_path: Path) -> None:
    """同一成片序号 + 同一轨道必须稳定：批量出片要可复现。"""
    sources = _sources(tmp_path, 5)
    first = select_random_sticker(sources, seed=2026, plan_ordinal=3, track_index=1, track_count=3)
    second = select_random_sticker(sources, seed=2026, plan_ordinal=3, track_index=1, track_count=3)
    assert first == second


def test_random_selection_spreads_tracks_within_a_plan(tmp_path: Path) -> None:
    """一个成片内的多条轨道应取到不同素材，否则随机没意义。"""
    sources = _sources(tmp_path, 5)
    picks = {
        select_random_sticker(sources, seed=7, plan_ordinal=0, track_index=index, track_count=4)
        for index in range(4)
    }
    assert len(picks) == 4


def test_random_selection_varies_across_plans(tmp_path: Path) -> None:
    """不同成片序号应产生不同组合（重洗牌）。"""
    sources = _sources(tmp_path, 4)
    plan0 = [
        select_random_sticker(sources, seed=11, plan_ordinal=0, track_index=index, track_count=4)
        for index in range(4)
    ]
    plan1 = [
        select_random_sticker(sources, seed=11, plan_ordinal=1, track_index=index, track_count=4)
        for index in range(4)
    ]
    assert plan0 != plan1


def test_random_selection_differs_by_seed(tmp_path: Path) -> None:
    sources = _sources(tmp_path, 5)
    a = select_random_sticker(sources, seed=1, plan_ordinal=0, track_index=0, track_count=3)
    b = select_random_sticker(sources, seed=2, plan_ordinal=0, track_index=0, track_count=3)
    assert a != b


def test_random_selection_returns_none_for_empty_library(tmp_path: Path) -> None:
    """库为空时由调用方给出可读错误，这里只返回 None。"""
    assert select_random_sticker([], seed=1, plan_ordinal=0, track_index=0, track_count=1) is None


def test_random_selection_rejects_negative_ordinal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        select_random_sticker(_sources(tmp_path, 3), seed=1, plan_ordinal=-1, track_index=0, track_count=1)


def test_random_selection_handles_single_source(tmp_path: Path) -> None:
    sources = _sources(tmp_path, 1)
    for ordinal in range(3):
        picked = select_random_sticker(
            sources, seed=5, plan_ordinal=ordinal, track_index=0, track_count=1
        )
        assert picked == sources[0]


def test_random_selection_covers_every_source_over_a_cycle(tmp_path: Path) -> None:
    """一轮洗牌应覆盖全部素材，避免某些贴纸永远用不到。"""
    sources = _sources(tmp_path, 4)
    picked = {
        select_random_sticker(sources, seed=99, plan_ordinal=ordinal, track_index=0, track_count=1)
        for ordinal in range(4)
    }
    assert picked == set(sources)


def test_entry_defaults_display_name_to_stem(tmp_path: Path) -> None:
    entry = StickerEntry(path=Path("素材/我的贴纸.png"))
    assert entry.display_name == "我的贴纸"
    assert entry.id
