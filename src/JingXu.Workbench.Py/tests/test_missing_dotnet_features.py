"""本轮补齐的「.NET 有 / Python 无」条目回归。

逐条：

1. **选品结果表的链接可点开**（.NET ``OpenSelectedSampleVideo`` /
   ``OpenSelectedVideo``）：列已显示链接，但此前点不动。
2. **选品「清空日志」**（.NET ``ClearLogCommand``）：日志很长时无法清掉。
3. **蒙版「统一应用到全部层」**（.NET ``ApplyCurrentVisualSettingsToAllLayersCommand``）：
   这类批量按钮此前只有「统一尺寸」与「统一起始片段」两个。
4. **字幕页「导入视频」**（.NET ``PickVideoCommand``）：字幕实验室此前只能用
   混剪页选中的素材，不能指定别的视频。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import LayerKind  # noqa: E402
from jingxu.infrastructure.layer_store import LayerStore  # noqa: E402
from jingxu.infrastructure.spider import SpiderConfigStore, SpiderRunResult  # noqa: E402
from jingxu.infrastructure.subtitle_store import SubtitleStore  # noqa: E402
from jingxu.ui.layer_page import VISUAL_SETTING_FIELDS, LayerPage  # noqa: E402
from jingxu.ui.spider_page import (  # noqa: E402
    RESULT_SAMPLE_VIDEO_COLUMN,
    SpiderPage,
    _is_openable_url,
)
from jingxu.ui.subtitle_page import SubtitlePage  # noqa: E402
from jingxu.ui.theme import apply_application_theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _spider_page(tmp: Path) -> SpiderPage:
    return SpiderPage(store=SpiderConfigStore(tmp / "config.json"))


def _result_with_links() -> SpiderRunResult:
    return SpiderRunResult(
        success=True,
        message="ok",
        retained=(
            {
                "商品名称": "耳机",
                "清洗名称": "耳机",
                "涉及平台": "douyin",
                "带货账号数": 3,
                "带货视频数": 7,
                "对标账号明细": "小A、小B",
                "参考价格": "¥29.9",
                "示例视频链接": "https://www.douyin.com/video/123",
            },
            {"商品名称": "无链接商品", "示例视频链接": "—"},
        ),
    )


# ── 1. 结果表链接可点开 ─────────────────────────────────────────────────────


def test_openable_url_detection() -> None:
    assert _is_openable_url("https://www.douyin.com/video/1") is True
    assert _is_openable_url("http://x.cn/a") is True
    # 缺失占位与半截 URL 都不算可打开
    for value in ("—", "", "   ", "not-a-url", "https://", "ftp://x"):
        assert _is_openable_url(value) is False, value


def test_link_cells_are_marked_openable(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _spider_page(tmp_path)
    page._fill_results(_result_with_links())

    table = page._results_table
    assert table.rowCount() == 2

    link_item = table.item(0, RESULT_SAMPLE_VIDEO_COLUMN)
    assert link_item.font().underline() is True, "可打开的链接没有下划线提示"
    assert (0, RESULT_SAMPLE_VIDEO_COLUMN) in page._openable_cells

    placeholder = table.item(1, RESULT_SAMPLE_VIDEO_COLUMN)
    assert placeholder.font().underline() is False, "「—」占位不该显得可点"
    assert (1, RESULT_SAMPLE_VIDEO_COLUMN) not in page._openable_cells


def test_cell_url_only_for_link_columns(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _spider_page(tmp_path)
    page._fill_results(_result_with_links())

    assert page._cell_url(0, RESULT_SAMPLE_VIDEO_COLUMN) == "https://www.douyin.com/video/123"
    assert page._cell_url(0, 1) == "", "非链接列不该被当成链接"
    assert page._cell_url(1, RESULT_SAMPLE_VIDEO_COLUMN) == "", "占位符不该返回 URL"


def test_open_result_link_opens_in_browser(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """打开链接走 QDesktopServices，且传的是 http(s) 而不是本地文件路径。"""
    apply_application_theme(qapp)
    page = _spider_page(tmp_path)
    page._fill_results(_result_with_links())

    opened: list[str] = []

    from jingxu.ui import spider_page as module  # noqa: PLC0415

    monkeypatch.setattr(
        module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()),
    )
    page._open_result_link(0, RESULT_SAMPLE_VIDEO_COLUMN)

    assert opened == ["https://www.douyin.com/video/123"]


def test_open_result_link_reports_when_missing(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _spider_page(tmp_path)
    page._fill_results(_result_with_links())

    page._open_result_link(1, RESULT_SAMPLE_VIDEO_COLUMN)

    assert "没有可打开的链接" in page._result_caption.text()


def test_openable_cells_reset_between_results(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """重新填结果时要清掉旧的可点标记，否则行号会指向错的单元格。"""
    apply_application_theme(qapp)
    page = _spider_page(tmp_path)
    page._fill_results(_result_with_links())
    assert page._openable_cells

    page._fill_results(SpiderRunResult(success=True, message="ok", retained=()))

    assert page._openable_cells == set()


# ── 2. 清空日志 ─────────────────────────────────────────────────────────────


def test_clear_log_button_lifecycle(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _spider_page(tmp_path)

    assert page._log_clear.isEnabled() is False, "没有日志时「清空日志」不该可用"

    page._append_log("第一行")
    page._append_log("第二行")
    qapp.processEvents()
    assert page._log_clear.isEnabled() is True
    assert "第一行" in page._log.toPlainText()

    page._clear_log()
    qapp.processEvents()
    assert page._log.toPlainText() == ""
    assert page._log_clear.isEnabled() is False


def test_log_has_block_cap(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """日志有行数上限（对齐 .NET AppendLog 的容量保护），避免长跑吃内存。"""
    apply_application_theme(qapp)
    page = _spider_page(tmp_path)

    assert page._log.maximumBlockCount() > 0


# ── 3. 蒙版「统一应用到全部层」 ─────────────────────────────────────────────


def _mask_page(tmp_path: Path, count: int = 3) -> LayerPage:
    for index in range(count):
        (tmp_path / f"mask{index}.png").write_bytes(b"stub")
    store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "tracks.json")
    for index in range(count):
        store.add(tmp_path / f"mask{index}.png")
    return LayerPage(
        store,
        title="蒙版模板",
        file_filter="*",
        hint="测试",
        ffmpeg=Path("ffmpeg"),
    )


def test_visual_setting_fields_exist_on_layer_spec() -> None:
    """字段集必须都是 LayerSpec 的真实字段名（拼错会静默不生效）。"""
    import dataclasses  # noqa: PLC0415

    from jingxu.domain.layers import LayerSpec  # noqa: PLC0415

    names = {field.name for field in dataclasses.fields(LayerSpec)}
    missing = [name for name in VISUAL_SETTING_FIELDS if name not in names]
    assert missing == [], f"VISUAL_SETTING_FIELDS 含不存在的字段：{missing}"


def test_apply_visual_settings_unifies_and_keeps_sources(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """统一参数：画法一致，**素材来源必须各不相同**。"""
    apply_application_theme(qapp)
    page = _mask_page(tmp_path)
    first = page._layers[0]
    page._store.replace(
        first.with_changes(
            x_percent=11.0,
            y_percent=22.0,
            width_percent=33.0,
            opacity=0.5,
            rotation_degrees=15.0,
            start_clip_index=2,
        )
    )
    page._reload()
    page._list.setCurrentRow(0)
    qapp.processEvents()

    page._apply_visual_settings_to_all()

    layers = page._layers
    assert len({(layer.x_percent, layer.width_percent, layer.opacity) for layer in layers}) == 1
    assert {layer.start_clip_index for layer in layers} == {2}, "起始片段应一并同步"
    assert len({Path(layer.source).name for layer in layers}) == 3, "素材来源被覆盖了"
    assert "统一到其余 2 个图层" in page._status.text()


def test_apply_visual_settings_requires_selection(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _mask_page(tmp_path)
    page._list.setCurrentRow(-1)

    page._apply_visual_settings_to_all()

    assert "请先选择" in page._status.text()


def test_apply_visual_settings_requires_two_layers(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _mask_page(tmp_path, count=1)
    page._list.setCurrentRow(0)

    page._apply_visual_settings_to_all()

    assert "至少需要 2 个图层" in page._status.text()


# ── 4. 字幕页「导入视频」 ───────────────────────────────────────────────────


def _subtitle_page(tmp_path: Path) -> SubtitlePage:
    return SubtitlePage(SubtitleStore(tmp_path / "subtitles.json"), Path("ffmpeg"))


def test_subtitle_page_has_import_video_button(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _subtitle_page(tmp_path)

    from jingxu.ui.widgets import SecondaryButton  # noqa: PLC0415

    labels = {button.text() for button in page.findChildren(SecondaryButton)}
    assert "导入视频…" in labels
    assert "恢复跟随混剪" in labels


def test_subtitle_manual_source_wins_over_composition(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    """手动导入后，混剪页再推素材不得覆盖它（.NET 的独立当前视频）。"""
    apply_application_theme(qapp)
    page = _subtitle_page(tmp_path)
    composition_video = tmp_path / "混剪素材.mp4"
    manual_video = tmp_path / "手动导入.mp4"
    for path in (composition_video, manual_video):
        path.write_bytes(b"stub")

    page.set_source_material(composition_video)
    assert page._source == composition_video
    assert "跟随混剪" in page._source_label.text()

    page._manual_source = manual_video
    page._adopt_source(manual_video)
    page._refresh_source_controls()
    assert "手动导入" in page._source_label.text()
    assert page._resume_follow.isEnabled() is True

    # 混剪页再推 → 不应覆盖
    page.set_source_material(composition_video)
    assert page._source == manual_video


def test_subtitle_resume_restores_following(qapp, tmp_path: Path) -> None:  # noqa: ANN001
    apply_application_theme(qapp)
    page = _subtitle_page(tmp_path)
    video = tmp_path / "手动导入.mp4"
    video.write_bytes(b"stub")

    page._manual_source = video
    page._adopt_source(video)
    page._refresh_source_controls()

    received: list[int] = []
    page.source_resume_requested.connect(lambda: received.append(1))
    page._resume_following_composition()

    assert received == [1], "没有请求壳层重新推素材"
    assert page._manual_source is None
    assert page._source is None, "恢复跟随时应先清空，避免显示过期的手动视频"
    assert page._resume_follow.isEnabled() is False
    assert "已恢复跟随" in page._status.text()
