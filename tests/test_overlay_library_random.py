"""蒙版素材库随机替换：对齐 .NET ``BuildLayersForPlan`` / ``OverlaySourceSelector``。

用户反馈混剪页「每条成片随机替换 1 个素材库蒙版」勾选后毫无效果——查证属实：
``CompositionPage.overlay_random_replace()`` 全仓无调用者，``CompositionDraft`` 也没有
对应字段，是一条完整的死链。本文件守住补齐后的行为。

对齐要点（都能在 .NET 侧找到同名实现）：

* 库内选择用 **固定种子 + 全局累加序号**（``_randomLibrarySelectionSeed`` +
  ``_nextRandomMaskSelectionOrdinal``），**不是**逐条递增的 ``plan.seed``。
  用后者会让洗牌轮次每片都从头开始：既破坏"一轮内每条素材只出现一次"，
  又可能让相邻成片拿到同一条。
* 随机模式是"替换"而不是"追加叠加"：每条成片只保留 **1 条**外部蒙版。
* 只替换素材，画法（位置/尺寸/透明度/羽化/起始片段）全部沿用模板。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import make_asset  # noqa: E402

from jingxu.application.composition_service import (  # noqa: E402
    CompositionDraft,
    build_requests,
    materialize_overlay_library,
    select_overlay_replacement,
)
from jingxu.domain.composition import OrderMode  # noqa: E402
from jingxu.domain.layers import LayerKind, LayerSpec  # noqa: E402
from jingxu.infrastructure.layer_store import (  # noqa: E402
    OVERLAY_LIBRARY_FILE_NAME,
    LayerStore,
    overlay_library_path,
)


def _library(tmp_path: Path, count: int = 3) -> tuple[Path, ...]:
    paths: list[Path] = []
    for index in range(count):
        path = tmp_path / f"mask{index}.png"
        path.write_bytes(b"stub")
        paths.append(path)
    return tuple(paths)


def _template() -> LayerSpec:
    return LayerSpec(
        kind=LayerKind.OVERLAY,
        source=Path("current.png"),
        x_percent=40.0,
        y_percent=26.0,
        width_percent=80.0,
        height_percent=40.0,
        opacity=0.3,
        feather=0.25,
        start_clip_index=2,
    )


def _draft(tmp_path: Path, *, enabled: bool = True, count: int = 3, batch: int = 9) -> CompositionDraft:
    return CompositionDraft(
        mode=OrderMode.RANDOM,
        seed=2026,
        batch_count=batch,
        layers=(_template(),),
        randomize_overlay_library=enabled,
        overlay_library=_library(tmp_path, count),
    )


def _selected(tmp_path: Path, *, ordinal: int, seed: int, count: int = 3) -> tuple[LayerSpec, ...]:
    return materialize_overlay_library(
        _draft(tmp_path, count=count),
        plan_index=ordinal,
        seed=seed,
    )


# ── 选择器本身 ──────────────────────────────────────────────────────────────


def test_select_returns_none_for_empty_library() -> None:
    assert select_overlay_replacement([], seed=1, plan_ordinal=0) is None


def test_select_returns_sole_entry(tmp_path: Path) -> None:
    library = _library(tmp_path, 1)
    assert select_overlay_replacement(library, seed=7, plan_ordinal=5) == library[0]


def test_select_is_reproducible(tmp_path: Path) -> None:
    library = _library(tmp_path, 4)
    first = [select_overlay_replacement(library, seed=99, plan_ordinal=i) for i in range(8)]
    second = [select_overlay_replacement(library, seed=99, plan_ordinal=i) for i in range(8)]
    assert first == second


def test_select_covers_every_entry_within_a_round(tmp_path: Path) -> None:
    """一轮（序号 0..N-1）必须覆盖库内全部素材，各出现一次。

    这正是"固定种子"的前提：若用逐条递增的 seed，每片都从新一轮开始，
    这个保证就不成立。
    """
    library = _library(tmp_path, 4)
    round_one = [select_overlay_replacement(library, seed=12345, plan_ordinal=i) for i in range(4)]
    assert sorted(round_one) == sorted(library)


def test_select_avoids_adjacent_repeats(tmp_path: Path) -> None:
    """相邻成片不得拿到同一条素材（洗牌轮次交界处做了防碰撞）。"""
    library = _library(tmp_path, 3)
    picks = [select_overlay_replacement(library, seed=555, plan_ordinal=i) for i in range(12)]
    repeats = [i for i in range(len(picks) - 1) if picks[i] == picks[i + 1]]
    assert repeats == [], f"相邻重复出现在 {repeats}"


def test_select_crosses_batches_without_reset(tmp_path: Path) -> None:
    """序号跨批次累加：一次 6 条与分两次各 3 条得到同一序列（.NET 同语义）。"""
    library = _library(tmp_path, 3)
    one_go = [select_overlay_replacement(library, seed=8, plan_ordinal=i) for i in range(6)]
    split = [select_overlay_replacement(library, seed=8, plan_ordinal=i) for i in range(3)]
    split += [select_overlay_replacement(library, seed=8, plan_ordinal=i) for i in range(3, 6)]
    assert one_go == split


# ── 图层物化 ────────────────────────────────────────────────────────────────


def test_disabled_keeps_layers_untouched(tmp_path: Path) -> None:
    """未开启随机替换时原样返回，素材不变。"""
    draft = _draft(tmp_path, enabled=False)
    layers = materialize_overlay_library(draft, plan_index=0, seed=1)
    assert layers == draft.layers


def test_empty_library_keeps_layers_untouched(tmp_path: Path) -> None:
    """开启但库为空：不静默清空用户的轨道。"""
    draft = CompositionDraft(
        mode=OrderMode.RANDOM,
        seed=1,
        layers=(_template(),),
        randomize_overlay_library=True,
        overlay_library=(),
    )
    assert materialize_overlay_library(draft, plan_index=0, seed=1) == draft.layers


def test_random_replacement_swaps_source_only(tmp_path: Path) -> None:
    """只换素材：位置/尺寸/透明度/羽化/起始片段全部沿用模板。"""
    template = _template()
    layers = _selected(tmp_path, ordinal=1, seed=42)

    assert len(layers) == 1
    produced = layers[0]
    assert produced.source != template.source
    assert produced.x_percent == pytest.approx(template.x_percent)
    assert produced.y_percent == pytest.approx(template.y_percent)
    assert produced.width_percent == pytest.approx(template.width_percent)
    assert produced.height_percent == pytest.approx(template.height_percent)
    assert produced.opacity == pytest.approx(template.opacity)
    assert produced.feather == pytest.approx(template.feather)
    assert produced.start_clip_index == template.start_clip_index


def test_random_replacement_keeps_single_layer(tmp_path: Path) -> None:
    """随机模式是"替换"而非"追加叠加"：多条轨道也只保留 1 条。"""
    draft = CompositionDraft(
        mode=OrderMode.RANDOM,
        seed=1,
        layers=(
            _template(),
            _template().with_changes(id="second", source=Path("other.png")),
            LayerSpec(kind=LayerKind.STICKER, source=Path("s.png"), id="sticker"),
        ),
        randomize_overlay_library=True,
        overlay_library=_library(tmp_path, 3),
    )

    layers = materialize_overlay_library(draft, plan_index=0, seed=1)

    assert len(layers) == 1
    assert layers[0].kind is LayerKind.OVERLAY


def test_self_ghost_layer_is_not_used_as_template(tmp_path: Path) -> None:
    """自叠影没有独立素材文件，不能当作替换模板（.NET 同样只挑非自叠影）。"""
    from jingxu.domain.layers import SELF_SOURCE  # noqa: PLC0415

    draft = CompositionDraft(
        mode=OrderMode.RANDOM,
        seed=1,
        layers=(LayerSpec(kind=LayerKind.OVERLAY, source=Path(SELF_SOURCE), id="ghost"),),
        randomize_overlay_library=True,
        overlay_library=_library(tmp_path, 2),
    )

    layers = materialize_overlay_library(draft, plan_index=0, seed=1)

    assert len(layers) == 1
    assert str(layers[0].source) != SELF_SOURCE
    # 没有外部模板时按 .NET 走导入默认值新建（上半红框区 + 28% 透明）
    assert layers[0].y_percent == pytest.approx(26.0)
    assert layers[0].opacity == pytest.approx(0.28)


# ── 入队链路 ────────────────────────────────────────────────────────────────


def test_build_requests_uses_global_ordinal(tmp_path: Path) -> None:
    """入队时把**全局序号**传给库选择，因此一批 9 条分成 3 轮、每轮覆盖全部素材。"""
    draft = _draft(tmp_path, batch=9)
    requests = build_requests(
        assets=[make_asset("a.mp4")],
        draft=draft,
        output_directory=tmp_path,
        library_selection_seed=12345,
    )

    names = [request.layers[0].source for request in requests]
    assert len(names) == 9
    library = list(draft.overlay_library)
    for round_index in range(3):
        chunk = names[round_index * 3 : (round_index + 1) * 3]
        assert sorted(chunk) == sorted(library), f"第 {round_index + 1} 轮没有覆盖全部素材"
    assert all(left != right for left, right in zip(names, names[1:])), "出现相邻重复"


def test_build_requests_ordinal_continues_across_batches(tmp_path: Path) -> None:
    """两次各入队 3 条（序号 0..2 与 3..5）等价于一次入队 6 条。"""
    draft = _draft(tmp_path, batch=3)
    assets = [make_asset("a.mp4")]

    single = build_requests(
        assets=assets, draft=draft, output_directory=tmp_path, library_selection_seed=99
    )
    single += build_requests(
        assets=assets,
        draft=draft,
        output_directory=tmp_path,
        library_ordinal=3,
        library_selection_seed=99,
    )
    combined = build_requests(
        assets=assets,
        draft=_draft(tmp_path, batch=6),
        output_directory=tmp_path,
        library_selection_seed=99,
    )

    assert [r.layers[0].source for r in single] == [r.layers[0].source for r in combined]


def test_build_requests_defaults_to_draft_seed_when_not_given(tmp_path: Path) -> None:
    """未显式给库种子时退回草稿种子，保证测试与脚本可复现。"""
    draft = _draft(tmp_path, batch=3)
    assets = [make_asset("a.mp4")]

    first = build_requests(assets=assets, draft=draft, output_directory=tmp_path)
    second = build_requests(assets=assets, draft=draft, output_directory=tmp_path)

    assert [r.layers[0].source for r in first] == [r.layers[0].source for r in second]


def test_shell_consumes_the_random_overlay_toggle() -> None:
    """壳层必须真的读 ``overlay_random_replace()``（回归：勾了完全没反应）。"""
    import inspect  # noqa: PLC0415

    from jingxu.ui import shell_window  # noqa: PLC0415

    source = inspect.getsource(shell_window.ShellWindow._enqueue)
    assert "overlay_random_replace()" in source
    assert "randomize_overlay_library" in source
    assert "overlay_library" in source


def test_overlay_library_uses_its_own_file() -> None:
    """蒙版库与贴纸库、蒙版轨道三者落盘位置互不相同。"""
    from jingxu.infrastructure.layer_store import (  # noqa: PLC0415
        OVERLAY_FILE_NAME,
        STICKER_FILE_NAME,
    )

    assert len({OVERLAY_LIBRARY_FILE_NAME, OVERLAY_FILE_NAME, STICKER_FILE_NAME}) == 3
    assert overlay_library_path().name == OVERLAY_LIBRARY_FILE_NAME


def test_overlay_library_persists_entries(tmp_path: Path) -> None:
    """蒙版库条目能落盘并读回（与贴纸库共用实现、独立文件）。"""
    from jingxu.infrastructure.sticker_library import StickerLibrary  # noqa: PLC0415

    path = tmp_path / OVERLAY_LIBRARY_FILE_NAME
    library = StickerLibrary(store_path=path)
    sources = _library(tmp_path, 3)
    assert library.add(list(sources)) == 3

    reopened = StickerLibrary(store_path=path)
    assert len(reopened.entries) == 3
    assert {entry.path for entry in reopened.entries} == set(sources)


def test_overlay_store_and_library_stay_separate(tmp_path: Path) -> None:
    """轨道与素材库是两份数据：往库里加素材不会凭空生成轨道。"""
    from jingxu.infrastructure.sticker_library import StickerLibrary  # noqa: PLC0415

    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "tracks.json")
    library = StickerLibrary(store_path=tmp_path / OVERLAY_LIBRARY_FILE_NAME)
    library.add(list(_library(tmp_path, 2)))

    assert store.layers == []
    assert len(library.entries) == 2


# ── 两处开关必须同步（.NET 两处绑同一属性） ─────────────────────────────────


def test_overlay_random_toggles_stay_in_sync(qapp) -> None:  # noqa: ANN001
    """混剪页与蒙版页各有一个「随机替换 1 个素材库蒙版」开关，改动必须双向同步。

    回归：``set_overlay_random`` 用 ``blockSignals`` 抑制了 stateChanged，
    却不主动广播，于是从混剪页取消后蒙版页仍显示勾选，两处自相矛盾。
    """
    import os  # noqa: PLC0415

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    from jingxu.infrastructure.queue import RenderQueue  # noqa: PLC0415
    from jingxu.infrastructure.runtime import require_tool  # noqa: PLC0415
    from jingxu.ui.shell_window import ShellWindow  # noqa: PLC0415
    from jingxu.ui.theme import apply_application_theme  # noqa: PLC0415

    apply_application_theme(QApplication.instance())
    ffmpeg = require_tool("ffmpeg")
    window = ShellWindow(ffmpeg, require_tool("ffprobe"), RenderQueue(ffmpeg))
    try:
        composition = window._composition_page
        overlay = window._overlay_page

        def state() -> tuple[bool, bool]:
            return (composition._overlay_random.isChecked(), overlay._random_library.isChecked())

        assert state() == (False, False)

        overlay._random_library.setChecked(True)
        qapp.processEvents()
        assert state() == (True, True), "蒙版页勾选没有同步到混剪页"

        composition.set_overlay_random(False)
        qapp.processEvents()
        assert state() == (False, False), "混剪页取消没有同步回蒙版页"

        composition._overlay_random.setChecked(True)
        qapp.processEvents()
        assert state() == (True, True)

        overlay._random_library.setChecked(False)
        qapp.processEvents()
        assert state() == (False, False)
    finally:
        window.close()


def test_mask_page_has_its_own_library_bar(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """蒙版页要有 .NET 那套库工具条：随机替换开关 + 导入 + 清理失效 + 清空库。"""
    from jingxu.infrastructure.sticker_library import StickerLibrary  # noqa: PLC0415
    from jingxu.ui.layer_page import LayerPage  # noqa: PLC0415

    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "t.json")
    source = tmp_path / "m.png"
    source.write_bytes(b"stub")
    store.add(source)
    library = StickerLibrary(store_path=tmp_path / OVERLAY_LIBRARY_FILE_NAME)
    page = LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
        sticker_library=library,
    )

    assert page._random_library is not None
    assert "随机替换" in page._random_library.text()
    # 蒙版页没有「添加到轨道」（.NET 亦然），该属性为 None 但必须存在
    assert page._add_from_library is None
    assert "蒙版素材库" in page._library_caption.text()


def test_prune_library_removes_missing_entries(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """「清理失效」只移除文件已丢失的条目，不动磁盘文件。"""
    from jingxu.infrastructure.sticker_library import StickerLibrary  # noqa: PLC0415
    from jingxu.ui.layer_page import LayerPage  # noqa: PLC0415

    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "t2.json")
    source = tmp_path / "m.png"
    source.write_bytes(b"stub")
    store.add(source)

    library = StickerLibrary(store_path=tmp_path / OVERLAY_LIBRARY_FILE_NAME)
    kept = _library(tmp_path, 2)
    library.add(list(kept))
    missing = tmp_path / "gone.png"
    missing.write_bytes(b"stub")
    library.add([missing])
    missing.unlink()

    page = LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
        sticker_library=library,
    )
    page._prune_library()

    assert len(library.entries) == 2
    assert {entry.path for entry in library.entries} == set(kept)
    assert all(path.exists() for path in kept)
