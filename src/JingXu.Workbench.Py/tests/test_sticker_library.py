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


# ── 随机贴纸库接进渲染（入队请求层的素材替换）──────────────────────────────


def _media_assets(tmp_path: Path, count: int = 3):  # noqa: ANN202
    from jingxu.domain.media import MediaAsset

    assets = []
    for index in range(1, count + 1):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x" * 4096)
        assets.append(
            MediaAsset(
                path=path, duration=3.0, width=1080, height=1920, fps=30.0, has_audio=True
            )
        )
    return assets


def _sticker_layers(tmp_path: Path, count: int = 2):  # noqa: ANN202
    from jingxu.domain.layers import LayerKind, LayerSpec

    layers = []
    for index in range(count):
        path = tmp_path / f"track{index}.png"
        path.write_bytes(b"y" * 2048)
        layers.append(
            LayerSpec(kind=LayerKind.STICKER, source=path, x_percent=10.0 + index * 10)
        )
    return tuple(layers)


def _build(tmp_path: Path, *, randomize: bool, batch: int = 3):  # noqa: ANN202
    from jingxu.application.composition_service import CompositionDraft, build_requests

    tmp_path.mkdir(parents=True, exist_ok=True)
    assets = _media_assets(tmp_path)
    stickers = _make_files(tmp_path, "lib1.png", "lib2.png", "lib3.png")
    draft = CompositionDraft(
        batch_count=batch,
        layers=_sticker_layers(tmp_path),
        randomize_sticker_library=randomize,
        sticker_library=tuple(stickers),
    )
    return build_requests(
        assets=assets, draft=draft, output_directory=tmp_path / "out", pool=assets
    )


def test_disabled_random_library_keeps_track_sources(tmp_path: Path) -> None:
    """开关关闭时必须原样使用轨道绑定的素材（不得偷偷替换）。"""
    requests = _build(tmp_path, randomize=False)

    for request in requests:
        assert [layer.source.name for layer in request.layers] == ["track0.png", "track1.png"]


def test_enabled_random_library_replaces_sources(tmp_path: Path) -> None:
    """开启后每条成片的贴纸素材应来自素材库。"""
    requests = _build(tmp_path, randomize=True)
    library_names = {"lib1.png", "lib2.png", "lib3.png"}

    for request in requests:
        picked = {layer.source.name for layer in request.layers}
        assert picked <= library_names, f"出现了库外素材：{picked}"


def test_random_library_keeps_track_geometry(tmp_path: Path) -> None:
    """只换素材、不动画法（位置/尺寸/透明度/旋转沿用轨道）。"""
    requests = _build(tmp_path, randomize=True)

    for request in requests:
        assert [layer.x_percent for layer in request.layers] == [10.0, 20.0]


def test_random_library_does_not_repeat_within_a_plan(tmp_path: Path) -> None:
    """一个成片内的多条轨道应取到不同素材，否则随机没意义。"""
    requests = _build(tmp_path, randomize=True)

    for request in requests:
        sources = [layer.source for layer in request.layers]
        assert len(set(sources)) == len(sources)


def test_random_library_varies_across_plans(tmp_path: Path) -> None:
    """不同成片应产生不同组合（确定性洗牌重新洗牌）。"""
    requests = _build(tmp_path, randomize=True, batch=3)
    combos = {tuple(layer.source.name for layer in request.layers) for request in requests}
    assert len(combos) > 1


def test_random_library_is_reproducible(tmp_path: Path) -> None:
    """同一输入两次构建结果必须一致（批量出片可复现）。"""
    first = _build(tmp_path / "run", randomize=True)
    second = _build(tmp_path / "run", randomize=True)

    assert [tuple(l.source.name for l in r.layers) for r in first] == [
        tuple(l.source.name for l in r.layers) for r in second
    ]


def test_random_library_with_empty_library_keeps_sources(tmp_path: Path) -> None:
    """开启随机但库为空：不得清空素材，交由界面提示（否则成片会丢贴纸）。"""
    from jingxu.application.composition_service import CompositionDraft, build_requests

    assets = _media_assets(tmp_path)
    draft = CompositionDraft(
        batch_count=2,
        layers=_sticker_layers(tmp_path),
        randomize_sticker_library=True,
        sticker_library=(),
    )
    requests = build_requests(
        assets=assets, draft=draft, output_directory=tmp_path / "out", pool=assets
    )

    for request in requests:
        assert [layer.source.name for layer in request.layers] == ["track0.png", "track1.png"]


def test_random_library_ignores_non_sticker_layers(tmp_path: Path) -> None:
    """蒙版图层不受贴纸随机替换影响。"""
    from jingxu.application.composition_service import CompositionDraft, build_requests
    from jingxu.domain.layers import LayerKind, LayerSpec

    assets = _media_assets(tmp_path)
    stickers = _make_files(tmp_path, "lib1.png", "lib2.png")
    mask = tmp_path / "mask.png"
    mask.write_bytes(b"z" * 2048)
    draft = CompositionDraft(
        batch_count=2,
        layers=(
            LayerSpec(kind=LayerKind.OVERLAY, source=mask, x_percent=50.0),
            LayerSpec(kind=LayerKind.STICKER, source=stickers[0], x_percent=10.0),
        ),
        randomize_sticker_library=True,
        sticker_library=tuple(stickers),
    )
    requests = build_requests(
        assets=assets, draft=draft, output_directory=tmp_path / "out", pool=assets
    )

    for request in requests:
        overlay = next(l for l in request.layers if l.kind is LayerKind.OVERLAY)
        assert overlay.source.name == "mask.png", "蒙版素材不得被贴纸随机替换改动"
