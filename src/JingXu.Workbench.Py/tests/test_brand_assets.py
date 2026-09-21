"""品牌资源（logo 与窗口图标）：加载、降级与打包路径解析。

背景：.NET 版把 ``Assets/AppLogo.png`` 与 ``Assets/AppIcon.ico`` 作为 WPF Resource
使用（壳层标题栏与启动画面显示 logo，窗口图标用 ico）。Python 迁移版此前
**完全没有图片资源**，标题栏用画成色块的「炳」字代替 logo，exe 也没设置图标，
资源管理器与任务栏显示的是 PyInstaller 默认图标。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from jingxu.ui import assets_loader  # noqa: E402
from jingxu.ui.brand import app_icon, build_logo_widget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():  # noqa: ANN201
    return QApplication.instance() or QApplication(["jingxu-tests"])


@pytest.fixture(autouse=True)
def _clear_asset_cache():  # noqa: ANN202
    """资源路径有 lru_cache，用例之间必须清理，否则互相污染。"""
    assets_loader.logo_path.cache_clear()
    assets_loader.icon_path.cache_clear()
    yield
    assets_loader.logo_path.cache_clear()
    assets_loader.icon_path.cache_clear()


# ── 资源随包存在 ────────────────────────────────────────────────────────────


def test_logo_asset_is_packaged() -> None:
    """logo 必须随包存在，否则界面只能退回文字标记。"""
    path = assets_loader.logo_path()
    assert path is not None and path.is_file()
    assert path.name == "AppLogo.png"
    assert path.stat().st_size > 1000


def test_icon_asset_is_packaged() -> None:
    path = assets_loader.icon_path()
    assert path is not None and path.is_file()
    assert path.suffix.lower() == ".ico"


def test_has_logo_matches_loader() -> None:
    assert assets_loader.has_logo() is (assets_loader.logo_path() is not None)


# ── 界面接入 ────────────────────────────────────────────────────────────────


def test_logo_widget_shows_image_when_available(qapp) -> None:  # noqa: ANN001
    widget = build_logo_widget(size=28)

    assert widget.width() == 28 and widget.height() == 28
    assert not widget.pixmap().isNull(), "有资源时必须用图片而不是文字"
    assert widget.text() == ""


def test_logo_widget_scales_to_requested_size(qapp) -> None:  # noqa: ANN001
    """logo 是正方形，缩放到指定边长后不得变形。"""
    widget = build_logo_widget(size=64)
    pixmap = widget.pixmap()

    assert not pixmap.isNull()
    assert pixmap.width() == 64
    assert pixmap.height() == 64


def test_app_icon_has_multiple_sizes(qapp) -> None:  # noqa: ANN001
    """ico 应含多档尺寸，任务栏与资源管理器才清晰。"""
    icon = app_icon()

    assert icon is not None and not icon.isNull()
    sizes = {size.width() for size in icon.availableSizes()}
    assert {16, 32} <= sizes, f"缺少小尺寸图标：{sorted(sizes)}"


# ── 资源缺失时降级（不得崩、不得留空白）──────────────────────────────────────


def test_logo_widget_falls_back_to_text(qapp, monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setattr(assets_loader, "_candidate_directories", lambda: [tmp_path])
    assets_loader.logo_path.cache_clear()

    widget = build_logo_widget(size=28)

    assert widget.pixmap().isNull()
    assert widget.text() == "炳"
    assert "background" in widget.styleSheet()


def test_app_icon_returns_none_when_missing(qapp, monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setattr(assets_loader, "_candidate_directories", lambda: [tmp_path])
    assets_loader.icon_path.cache_clear()

    assert app_icon() is None


def test_empty_file_is_not_treated_as_asset(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """0 字节占位文件不得被当作可用资源（Tesseract 占位文件就是这种坑）。"""
    (tmp_path / "AppLogo.png").write_bytes(b"")
    monkeypatch.setattr(assets_loader, "_candidate_directories", lambda: [tmp_path])

    assert assets_loader.asset_path("AppLogo.png") is None


# ── 解析顺序 ────────────────────────────────────────────────────────────────


def test_frozen_bundle_directory_is_searched(monkeypatch, tmp_path: Path) -> None:
    """PyInstaller 打包后资源在 _MEIPASS 下，必须能找到。"""
    bundle = tmp_path / "bundle"
    target = bundle / "jingxu" / "ui" / "assets"
    target.mkdir(parents=True)
    (target / "AppLogo.png").write_bytes(b"x" * 2048)

    monkeypatch.setattr(assets_loader.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(
        assets_loader, "_ASSET_DIRECTORY", tmp_path / "不存在的开发目录"
    )

    assert assets_loader.asset_path("AppLogo.png") == target / "AppLogo.png"


def test_asset_directory_is_searched_first(monkeypatch, tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "AppLogo.png").write_bytes(b"y" * 2048)
    monkeypatch.setattr(assets_loader, "_ASSET_DIRECTORY", package_dir)

    assert assets_loader.asset_path("AppLogo.png") == package_dir / "AppLogo.png"


def test_missing_asset_returns_none(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setattr(assets_loader, "_candidate_directories", lambda: [tmp_path])
    assert assets_loader.asset_path("不存在的文件.png") is None
