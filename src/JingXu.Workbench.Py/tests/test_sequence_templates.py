"""序号模板存储与图层页参数语义测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_asset

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.domain.layers import LayerKind  # noqa: E402
from jingxu.infrastructure.layer_store import LayerStore  # noqa: E402
from jingxu.infrastructure.sequence_templates import SequenceTemplateStore  # noqa: E402
from jingxu.ui.layer_page import LayerPage  # noqa: E402


class TestSequenceTemplates:
    def test_save_apply_rename_delete(self, tmp_path: Path) -> None:
        store = SequenceTemplateStore(tmp_path / "sequence-templates.json")

        saved = store.save("爆款顺序", "264513")
        assert saved.expression == "264513"
        assert store.get("爆款顺序").id == saved.id

        # 同名覆盖保留 id
        updated = store.save("爆款顺序", "123456")
        assert updated.id == saved.id
        assert store.get("爆款顺序").expression == "123456"

        assert store.rename("爆款顺序", "竖屏顺序") is True
        assert store.names == ["竖屏顺序"]
        assert store.delete("竖屏顺序") is True
        assert store.names == []

    def test_multi_expression_allowed(self, tmp_path: Path) -> None:
        store = SequenceTemplateStore(tmp_path / "sequence-templates.json")
        store.save("多任务", "264513\n351246; 123")
        assert store.get("多任务").expression.startswith("264513")

    def test_validation_rejects_empty_and_bad(self, tmp_path: Path) -> None:
        store = SequenceTemplateStore(tmp_path / "sequence-templates.json")
        with pytest.raises(ValueError, match="模板名称不能为空"):
            store.save("   ", "123")
        with pytest.raises(ValueError, match="不能为空"):
            store.save("空表达", "   ")
        with pytest.raises(ValueError, match="无效"):
            store.save("坏表达", "12a")

    def test_duplicate_name_rename_rejected(self, tmp_path: Path) -> None:
        store = SequenceTemplateStore(tmp_path / "sequence-templates.json")
        store.save("A", "123")
        store.save("B", "321")
        with pytest.raises(ValueError, match="同名"):
            store.rename("B", "A")

    def test_persisted_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "sequence-templates.json"
        SequenceTemplateStore(path).save("持久", "111")
        assert SequenceTemplateStore(path).names == ["持久"]


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


class TestLayerPageSemantics:
    def _page(self, tmp_path: Path) -> LayerPage:
        store = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "overlay.json")
        page = LayerPage(store, title="蒙版模板", file_filter="蒙版视频 (*.mp4)", hint="测试")
        mask = tmp_path / "mask.mp4"
        mask.write_bytes(b"stub")
        page._store.add(mask)
        page.refresh_from_store()
        return page

    def test_opacity_semantics_match_dotnet(self, qapp, tmp_path: Path) -> None:  # noqa: ANN001
        page = self._page(tmp_path)

        page._opacity.setValue(28)  # 28% 透明 → 72% 不透明
        layer = page._selected()
        assert layer is not None
        assert layer.opacity == pytest.approx(0.72)

        page._opacity.setValue(0)
        assert page._selected().opacity == pytest.approx(1.0)
        page._opacity.setValue(100)
        assert page._selected().opacity == pytest.approx(0.0)

    def test_new_fields_roundtrip(self, qapp, tmp_path: Path) -> None:  # noqa: ANN001
        page = self._page(tmp_path)

        page._top_fade.setValue(1.0)
        page._feather.setValue(0.3)
        page._fit.setCurrentIndex(page._fit.findData("match_canvas_crop"))
        page._start_clip.setValue(3)
        page._mix_audio.setChecked(True)
        page._source_crop_canvas.setChecked(True)
        page._source_crop_y.setValue(0.5)

        layer = page._selected()
        assert layer is not None
        assert layer.top_fade == pytest.approx(1.0)
        assert layer.feather == pytest.approx(0.3)
        assert layer.fit == "match_canvas_crop"
        assert layer.start_clip_index == 3
        assert layer.audio_mode == "mix"
        assert layer.source_crop_canvas is True
        assert layer.source_crop_y == pytest.approx(0.5)

        reloaded = LayerStore(LayerKind.OVERLAY, store_path=tmp_path / "overlay.json")
        stored = reloaded.layers[0]
        assert stored.top_fade == pytest.approx(1.0)
        assert stored.fit == "match_canvas_crop"
        assert stored.start_clip_index == 3
        assert stored.audio_mode == "mix"

    def test_pip_preset_applies_bounds(self, qapp, tmp_path: Path) -> None:  # noqa: ANN001
        page = self._page(tmp_path)

        page._apply_pip_preset()

        layer = page._selected()
        assert layer is not None
        assert layer.x_percent == pytest.approx(73.0)
        assert layer.fit == "contain"

    def test_unified_size_applies_to_all_layers(self, qapp, tmp_path: Path) -> None:  # noqa: ANN001
        page = self._page(tmp_path)
        second = tmp_path / "mask2.mp4"
        second.write_bytes(b"stub")
        page._store.add(second)
        page.refresh_from_store()
        page._list.setCurrentRow(0)
        page._width.setValue(66)
        page._height.setValue(40)

        page._apply_unified_size()

        widths = {layer.width_percent for layer in page._store.layers}
        heights = {layer.height_percent for layer in page._store.layers}
        assert widths == {66.0}
        assert heights == {40.0}
