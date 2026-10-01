"""设置页与 .NET 的结构对齐 + 一个真实缺陷的回归。

缺陷：``_data_label`` 被赋值两次（「应用」区块与「维护」区块各一次），
后者覆盖前者，而 ``_apply_runtime_info`` 只刷新后者——于是「应用」区块的
「数据目录」永远停在初始值，看起来像"读不到数据目录"。
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.infrastructure.encoders import EncoderRegistry  # noqa: E402
from jingxu.infrastructure.paths import data_directory  # noqa: E402
from jingxu.infrastructure.queue import RenderQueue  # noqa: E402
from jingxu.ui.settings_page import SettingsPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


def _page() -> SettingsPage:
    ffmpeg = Path("ffmpeg")
    return SettingsPage(ffmpeg, Path("ffprobe"), EncoderRegistry(ffmpeg), RenderQueue(ffmpeg))


class _FakeInfo:
    """替代 collect_runtime_info 的返回值（避免真起编码器探针）。"""

    ffmpeg_path = "ffmpeg"
    ffprobe_path = "ffprobe"
    ffmpeg_version = "test"
    ffprobe_version = "test"
    available_encoders: list[str] = []
    resolved_encoders: dict[str, str] = {}
    gpu_processing_status = ""
    python_version = "3.14"
    platform_text = "Windows"

    @property
    def data_directory(self) -> str:
        return str(data_directory())


# ── 数据目录标签（真实缺陷回归） ────────────────────────────────────────────


def test_both_data_directory_labels_exist(qapp) -> None:  # noqa: ANN001
    """「应用」与「维护」两个区块各有自己的数据目录标签，不能共用一个属性。"""
    page = _page()

    assert page._data_label is not page._maintenance_data_label
    assert "JingXu" in page._data_label.text() or page._data_label.text() != ""


def test_runtime_info_refreshes_both_labels(qapp) -> None:  # noqa: ANN001
    """运行期信息刷新后，两处数据目录都要跟着更新。

    回归：此前 ``_apply_runtime_info`` 只刷新被覆盖后的那一个，
    「应用」区块的标签永远停在初始值。
    """
    page = _page()
    page._data_label.setText("")
    page._maintenance_data_label.setText("")

    page._apply_runtime_info(_FakeInfo())

    expected = str(data_directory())
    assert page._data_label.text() == expected
    assert page._maintenance_data_label.text() == expected


# ── 分区名（对齐 .NET SettingsView.xaml） ───────────────────────────────────


def _section_titles(page: SettingsPage) -> list[str]:
    """取各折叠区的标题（``SectionExpander`` 内部用 ``SectionHeader`` 显示）。"""
    from jingxu.ui.widgets import SectionExpander, SectionHeader  # noqa: PLC0415

    titles: list[str] = []
    for expander in page.findChildren(SectionExpander):
        header = expander.findChild(SectionHeader)
        if header is not None:
            titles.append(header.text())
    return titles


def test_settings_sections_present(qapp) -> None:  # noqa: ANN001
    """分区与 .NET 对上：应用 / 渲染并发 / 运行时诊断 / 硬件编码 / 维护。"""
    titles = _section_titles(_page())

    for name in ("应用", "渲染并发", "运行时诊断", "硬件编码", "维护"):
        assert name in titles, f"缺少分区「{name}」（当前：{titles}）"


def test_settings_page_has_about_section_as_superset(qapp) -> None:  # noqa: ANN001
    """「关于」是 Python 版增强（.NET 设置页没有该分区），刻意保留。"""
    assert "关于" in _section_titles(_page())


def test_runtime_order_hint_matches_dotnet(qapp) -> None:  # noqa: ANN001
    """解析顺序提示要与 .NET 的一行说明一致（三段 + 可选组件说明）。"""
    from PySide6.QtWidgets import QLabel  # noqa: PLC0415

    page = _page()
    texts = [label.text() for label in page.findChildren(QLabel)]
    joined = "\n".join(texts)

    assert "外部运行时解析顺序" in joined
    assert "应用目录 runtime/" in joined
    assert "系统 PATH" in joined
    assert "可选组件" in joined
