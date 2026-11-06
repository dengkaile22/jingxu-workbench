"""用 Qt 预渲染宣传片的每一幕（1920×1080 PNG）。

设计语言与软件主题一致：暖灰背景 + 品牌粉强调色 + 深墨正文。
标注体系：编号徽章（粉色圆）+ 紧贴的标签胶囊（深墨底白字），直接钉在 UI 目标上，
不依赖空白区域、不画长连接线，缩放时不会错位。

产物： scenes/*.png
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT.parent  # 仓库根：脚本随仓库移动，不再写死 Desktop 绝对路径
SHOTS = ROOT / "界面截图" if (ROOT / "界面截图").exists() else ROOT / "shots"
SCENES_DIR = ROOT / "scenes"
QR_IMAGE = SCENES_DIR / "goofish_qr.png"
LOGO = APP / "core" / "jingxu" / "ui" / "assets" / "AppLogo.png"
GOOFISH_URL = "https://www.goofish.com/personal?userId=2222015802752"
GOOFISH_ID = "2222015802752"

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication

W, H = 1920, 1080
BG_TOP = QColor("#F8F6F1")
BG_BOTTOM = QColor("#EAE4D8")
INK = QColor("#17231F")
MUTED = QColor("#68736E")
PINK = QColor("#E86F8A")
PINK_DEEP = QColor("#C34A68")
CARD_BORDER = QColor("#D2D0C8")

FONT_FAMILY = "Microsoft YaHei UI"


def font(size: int, *, bold: bool = True) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    return f


def box_blur(image: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return image
    window = radius * 2 + 1
    padded = np.pad(image, ((radius, radius), (radius, radius)), mode="edge")
    cum = np.cumsum(padded, axis=0)
    blurred = (cum[window - 1:, :] - np.vstack([np.zeros((1, cum.shape[1])), cum[:-window, :]])) / window
    cum = np.cumsum(blurred, axis=1)
    blurred = (cum[:, window - 1:] - np.hstack([np.zeros((cum.shape[0], 1)), cum[:, :-window]])) / window
    return blurred


def rounded_mask(width: int, height: int, radius: int) -> np.ndarray:
    ys = np.arange(height)[:, None]
    xs = np.arange(width)[None, :]
    dx = np.clip(np.maximum(radius - xs, xs - (width - 1 - radius)), 0, None)
    dy = np.clip(np.maximum(radius - ys, ys - (height - 1 - radius)), 0, None)
    dist = np.sqrt(dx.astype(float) ** 2 + dy.astype(float) ** 2)
    alpha = np.clip(radius + 0.5 - dist, 0.0, 1.0)
    return (alpha * 255).astype(np.uint8)


# ─────────────────────────── 背景与品牌层 ───────────────────────────


def draw_background(painter: QPainter) -> None:
    gradient = QLinearGradient(0, 0, 0, H)
    gradient.setColorAt(0.0, BG_TOP)
    gradient.setColorAt(1.0, BG_BOTTOM)
    painter.fillRect(0, 0, W, H, gradient)

    bloom = QRadialGradient(QPointF(W - 260, -120), 780)
    bloom.setColorAt(0.0, QColor(232, 111, 138, 44))
    bloom.setColorAt(1.0, QColor(232, 111, 138, 0))
    painter.fillRect(0, 0, W, H, bloom)

    bloom2 = QRadialGradient(QPointF(120, H + 160), 640)
    bloom2.setColorAt(0.0, QColor(122, 150, 220, 28))
    bloom2.setColorAt(1.0, QColor(122, 150, 220, 0))
    painter.fillRect(0, 0, W, H, bloom2)

    painter.setPen(QPen(QColor(23, 35, 31, 16), 2))
    for x in range(80, W, 64):
        for y in range(80, H, 64):
            painter.drawPoint(x, y)


def draw_brand(painter: QPainter) -> None:
    logo = QPixmap(str(LOGO)).scaled(
        46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    painter.drawPixmap(88, 58, logo)
    painter.setFont(font(27))
    painter.setPen(INK)
    painter.drawText(146, 92, "清影快速混剪")


def draw_progress(painter: QPainter, index: int, total: int) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(23, 35, 31, 24))
    painter.drawRect(0, 0, W, 6)
    painter.setBrush(PINK)
    painter.drawRect(0, 0, int(W * index / total), 6)
    painter.setFont(font(22, bold=False))
    painter.setPen(MUTED)
    painter.drawText(
        QRectF(W - 240, 60, 152, 36),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        f"{index:02d} / {total:02d}",
    )


def draw_heading(painter: QPainter, title: str, subtitle: str) -> None:
    painter.setFont(font(58))
    painter.setPen(INK)
    painter.drawText(88, 176, title)
    width = painter.fontMetrics().horizontalAdvance(title)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(PINK)
    painter.drawRoundedRect(QRectF(88, 190, width + 6, 9), 4, 4)
    painter.setFont(font(26, bold=False))
    painter.setPen(MUTED)
    painter.drawText(88 + width + 36, 178, subtitle)


# ─────────────────────────── 卡片 ───────────────────────────


def card_shadow(canvas: QImage, x: int, y: int, width: int, height: int, radius: int, *, strength: int = 110) -> None:
    mask = rounded_mask(width, height, radius)
    padded = np.pad(mask.astype(np.float64) / 255.0, 20, mode="constant")
    blur = box_blur(padded, 20)
    shadow = np.zeros((height + 40, width + 40, 4), dtype=np.uint8)
    shadow[:, :, 3] = np.clip(blur * strength, 0, 255).astype(np.uint8)
    shadow[:, :, 0:3] = 24
    image = QImage(shadow.data, width + 40, height + 40, (width + 40) * 4, QImage.Format.Format_ARGB32)
    painter = QPainter(canvas)
    painter.drawImage(x - 20, y + 9, image)
    painter.end()


def draw_screenshot_card(
    canvas: QImage,
    shot_path: Path,
    x: int,
    y: int,
    width: int,
    radius: int = 20,
    *,
    rotation: float = 0.0,
) -> QRectF:
    shot = QPixmap(str(shot_path))
    height = round(width * shot.height() / shot.width())
    scaled = shot.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)

    card = QPixmap(scaled.size())
    card.fill(Qt.GlobalColor.transparent)
    painter = QPainter(card)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    rect = QRectF(0, 0, width, height)
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.setClipping(False)
    painter.setPen(QPen(CARD_BORDER, 3))
    painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), radius, radius)
    painter.end()

    if rotation:
        rotated = QPixmap(card.size())
        rotated.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rotated)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(card.width() / 2, card.height() / 2)
        painter.rotate(rotation)
        painter.translate(-card.width() / 2, -card.height() / 2)
        painter.drawPixmap(0, 0, card)
        painter.end()
        card = rotated

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(x, y, card)
    painter.end()
    return QRectF(x, y, width, height)


# ─────────────────────────── 标注 ───────────────────────────


def map_rect(card: QRectF, app_rect: list[int]) -> QRectF:
    scale = card.width() / 1920.0
    x, y, w, h = app_rect
    return QRectF(card.x() + x * scale, card.y() + y * scale, w * scale, h * scale)


def draw_badge(painter: QPainter, center: QPointF, number: int) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 46))
    painter.drawEllipse(center + QPointF(2, 4), 23, 23)
    painter.setBrush(PINK)
    painter.drawEllipse(center, 23, 23)
    painter.setPen(QPen(QColor(255, 255, 255, 220), 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, 21, 21)
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(font(28))
    painter.drawText(
        QRectF(center.x() - 23, center.y() - 23, 46, 46),
        Qt.AlignmentFlag.AlignCenter,
        str(number),
    )


def draw_label(painter: QPainter, anchor: QPointF, text: str, *, side: str = "right") -> QRectF:
    """标签胶囊：锚点贴在徽章边上，向 side 方向延伸。"""
    text_font = font(26)
    painter.setFont(text_font)
    text_w = painter.fontMetrics().horizontalAdvance(text)
    pill_h = 46
    pill_w = text_w + 40
    gap = 12
    if side == "right":
        rect = QRectF(anchor.x() + gap, anchor.y() - pill_h / 2, pill_w, pill_h)
    else:
        rect = QRectF(anchor.x() - gap - pill_w, anchor.y() - pill_h / 2, pill_w, pill_h)

    painter.setPen(QPen(QColor(255, 255, 255, 70), 2))
    painter.setBrush(QColor(23, 35, 31, 236))
    painter.drawRoundedRect(rect, pill_h / 2, pill_h / 2)

    painter.setPen(QColor("#F6F4EE"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    return rect


CORNER = {
    "tl": lambda r: QPointF(r.left(), r.top()),
    "tr": lambda r: QPointF(r.right(), r.top()),
    "bl": lambda r: QPointF(r.left(), r.bottom()),
    "br": lambda r: QPointF(r.right(), r.bottom()),
}


def draw_callouts(painter: QPainter, card: QRectF, callouts: list[dict]) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for item in callouts:
        rect = map_rect(card, item["rect"])
        edge = rect.adjusted(-7, -7, 7, 7)
        painter.setPen(QPen(QColor(232, 111, 138, 70), 14))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(edge, 14, 14)
        painter.setPen(QPen(PINK, 4))
        painter.drawRoundedRect(edge, 14, 14)

        corner = item.get("badge", "tl")
        point = CORNER[corner](rect)
        badge_center = QPointF(
            point.x() + item.get("dx", 0),
            point.y() + item.get("dy", 0),
        )
        draw_badge(painter, badge_center, item["num"])
        side = item.get("side", "right")
        # 胶囊挂在徽章外侧
        anchor = QPointF(
            badge_center.x() + (25 if side == "right" else -25),
            badge_center.y() + item.get("py", 0),
        )
        draw_label(painter, anchor, item["text"], side=side)


def draw_inset_caption(painter: QPainter, card: QRectF, text: str) -> None:
    """给副卡片加一条标题胶囊（贴在卡片上缘外侧）。"""
    text_font = font(28)
    painter.setFont(text_font)
    text_w = painter.fontMetrics().horizontalAdvance(text)
    pill_h = 52
    pill_w = text_w + 64
    rect = QRectF(card.left() + card.width() / 2 - pill_w / 2, card.top() - pill_h - 14, pill_w, pill_h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(232, 111, 138, 244))
    painter.drawRoundedRect(rect, pill_h / 2, pill_h / 2)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


# ─────────────────────────── 页面装配 ───────────────────────────


def new_canvas() -> QImage:
    canvas = QImage(W, H, QImage.Format.Format_ARGB32)
    canvas.fill(BG_TOP)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    draw_background(painter)
    painter.end()
    return canvas


FULL_W = 1440
FULL_X = (W - FULL_W) // 2
FULL_Y = 224


def render_full_scene(
    path: Path,
    *,
    index: int,
    title: str,
    subtitle: str,
    page: str,
    callouts: list[dict],
) -> None:
    canvas = new_canvas()
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw_brand(painter)
    draw_progress(painter, index, 7)
    draw_heading(painter, title, subtitle)
    painter.end()

    height = round(FULL_W * 1080 / 1920)
    card_shadow(canvas, FULL_X, FULL_Y, FULL_W, height, 20)
    card = draw_screenshot_card(canvas, SHOTS / f"{page}.png", FULL_X, FULL_Y, FULL_W)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    draw_callouts(painter, card, callouts)
    painter.end()
    canvas.save(str(path))
    print("OK", path.name)


def render_dual_scene(
    path: Path,
    *,
    index: int,
    title: str,
    subtitle: str,
    main_page: str,
    inset_page: str,
    main_callouts: list[dict],
    inset_caption: str,
) -> None:
    canvas = new_canvas()
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw_brand(painter)
    draw_progress(painter, index, 7)
    draw_heading(painter, title, subtitle)
    painter.end()

    main_w = 1080
    main_x, main_y = 88, 268
    inset_w = 610
    inset_x, inset_y = 1214, 556

    main_h = round(main_w * 1080 / 1920)
    card_shadow(canvas, main_x, main_y, main_w, main_h, 18)
    main_card = draw_screenshot_card(canvas, SHOTS / f"{main_page}.png", main_x, main_y, main_w, 18, rotation=-0.8)

    inset_h = round(inset_w * 1080 / 1920)
    card_shadow(canvas, inset_x, inset_y, inset_w, inset_h, 15, strength=90)
    inset_card = draw_screenshot_card(canvas, SHOTS / f"{inset_page}.png", inset_x, inset_y, inset_w, 15, rotation=1.3)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    draw_callouts(painter, main_card, main_callouts)
    draw_inset_caption(painter, inset_card, inset_caption)
    painter.end()
    canvas.save(str(path))
    print("OK", path.name)


def draw_goofish_qr(
    painter: QPainter,
    x: float,
    y: float,
    size: int,
    *,
    caption: str = "扫码进闲鱼主页",
    caption_size: int = 20,
) -> None:
    """右下角闲鱼二维码：白底圆角卡片 + 二维码 + 一行说明。二维码缺失时静默跳过。"""
    if not QR_IMAGE.exists():
        return
    qr = QPixmap(str(QR_IMAGE)).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawRoundedRect(QRectF(x - 16, y - 16, qr.width() + 32, qr.height() + 32), 18, 18)
    painter.drawPixmap(int(x), int(y), qr)
    if caption:
        painter.setFont(font(caption_size, bold=False))
        painter.setPen(MUTED)
        painter.drawText(
            QRectF(x - 40, y + qr.height() + 12, qr.width() + 80, 30),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            caption,
        )


def make_goofish_qr() -> None:
    """用 qrcode 生成闲鱼主页二维码；依赖缺失时跳过，成片仍保留账号文字。"""
    try:
        import qrcode
    except Exception as exc:  # noqa: BLE001 - 依赖可选，缺了不影响出片
        print("SKIP 二维码（qrcode 不可用）:", exc)
        return
    qr = qrcode.QRCode(version=None, box_size=10, border=1)
    qr.add_data(GOOFISH_URL)
    qr.make(fit=True)
    QR_IMAGE.parent.mkdir(parents=True, exist_ok=True)
    qr.make_image(fill_color="#17231F", back_color="white").save(str(QR_IMAGE))
    print("OK", QR_IMAGE.name)


def render_logo_intro(path: Path) -> None:
    canvas = new_canvas()
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    logo = QPixmap(str(LOGO)).scaled(230, 230, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter.drawPixmap((W - logo.width()) // 2, 158, logo)

    painter.setFont(font(148))
    painter.setPen(INK)
    title = "清影快速混剪"
    painter.drawText(int((W - painter.fontMetrics().horizontalAdvance(title)) / 2), 566, title)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(PINK)
    painter.drawRoundedRect(QRectF((W - 296) / 2, 604, 296, 12), 6, 6)

    painter.setFont(font(42, bold=False))
    painter.setPen(MUTED)
    subtitle = "完全离线的 Windows 批量混剪工作台"
    painter.drawText(int((W - painter.fontMetrics().horizontalAdvance(subtitle)) / 2), 700, subtitle)

    chips = ["批量混剪", "爆品选品", "字幕实验室", "定时抓取"]
    chip_font = font(31)
    painter.setFont(chip_font)
    widths = [painter.fontMetrics().horizontalAdvance(c) + 74 for c in chips]
    total = sum(widths) + 24 * (len(chips) - 1)
    x = (W - total) / 2
    for chip, chip_w in zip(chips, widths):
        rect = QRectF(x, 794, chip_w, 64)
        painter.setPen(QPen(PINK, 3))
        painter.setBrush(QColor(255, 255, 255, 200))
        painter.drawRoundedRect(rect, 32, 32)
        painter.setPen(INK)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, chip)
        x += chip_w + 24

    painter.setFont(font(27, bold=False))
    painter.setPen(MUTED)
    footer = "本地处理 · 数据不出本机 · 开箱即用"
    painter.drawText(int((W - painter.fontMetrics().horizontalAdvance(footer)) / 2), 958, footer)
    painter.end()
    canvas.save(str(path))
    print("OK", path.name)


def render_logo_outro(path: Path) -> None:
    canvas = new_canvas()
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    logo = QPixmap(str(LOGO)).scaled(190, 190, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter.drawPixmap((W - logo.width()) // 2, 146, logo)

    painter.setFont(font(96))
    painter.setPen(INK)
    title = "完全离线 · 数据不出本机"
    painter.drawText(int((W - painter.fontMetrics().horizontalAdvance(title)) / 2), 500, title)

    painter.setFont(font(38, bold=False))
    painter.setPen(MUTED)
    slogan = "把重复劳动交给批量，把时间留给创意。"
    painter.drawText(int((W - painter.fontMetrics().horizontalAdvance(slogan)) / 2), 586, slogan)

    chips = ["本地运行", "无需联网账号", "Windows 10 / 11", "一键安装"]
    chip_font = font(29)
    painter.setFont(chip_font)
    widths = [painter.fontMetrics().horizontalAdvance(c) + 62 for c in chips]
    total = sum(widths) + 22 * (len(chips) - 1)
    x = (W - total) / 2
    for chip, chip_w in zip(chips, widths):
        rect = QRectF(x, 676, chip_w, 60)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(23, 35, 31, 238))
        painter.drawRoundedRect(rect, 30, 30)
        painter.setPen(QColor("#F6F4EE"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, chip)
        x += chip_w + 22

    painter.setFont(font(33))
    painter.setPen(PINK_DEEP)
    brand = "清影快速混剪"
    painter.drawText(int((W - painter.fontMetrics().horizontalAdvance(brand)) / 2), 856, brand)

    # 闲鱼账号：成片落版必须能看清账号，同时给二维码方便扫码进主页。
    painter.setFont(font(30))
    painter.setPen(MUTED)
    shop = f"闲鱼 · {GOOFISH_ID}"
    painter.drawText(int((W - painter.fontMetrics().horizontalAdvance(shop)) / 2), 916, shop)

    draw_goofish_qr(painter, W - 168 - 132, H - 168 - 132, 168)
    painter.end()
    canvas.save(str(path))
    print("OK", path.name)


def render_cover(path: Path) -> None:
    canvas = new_canvas()
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    logo = QPixmap(str(LOGO)).scaled(92, 92, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter.drawPixmap(108, 84, logo)
    painter.setFont(font(50))
    painter.setPen(INK)
    painter.drawText(218, 150, "清影快速混剪")

    draw_goofish_qr(painter, W - 214, 96, 132, caption="扫码进闲鱼主页", caption_size=19)

    painter.setFont(font(78))
    painter.drawText(108, 306, "批量成片，离线搞定")
    painter.setFont(font(32, bold=False))
    painter.setPen(MUTED)
    painter.drawText(112, 374, "完全离线的 Windows 批量视频工作台")
    painter.end()

    card_x, card_y, card_w = 806, 452, 1020
    card_h = round(card_w * 1080 / 1920)
    card_shadow(canvas, card_x, card_y, card_w, card_h, 18)
    draw_screenshot_card(canvas, SHOTS / "composition.png", card_x, card_y, card_w, 18)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    chips = ["批量混剪", "爆品选品", "字幕实验室"]
    chip_font = font(30)
    painter.setFont(chip_font)
    y = 520
    for chip in chips:
        chip_w = painter.fontMetrics().horizontalAdvance(chip) + 62
        rect = QRectF(108, y, chip_w, 58)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(23, 35, 31, 238))
        painter.drawRoundedRect(rect, 29, 29)
        painter.setPen(QColor("#F6F4EE"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, chip)
        y += 76

    painter.setFont(font(27, bold=False))
    painter.setPen(MUTED)
    painter.drawText(108, 918, "本地处理 · 数据不出本机 · 开箱即用")

    painter.setFont(font(29))
    painter.setPen(PINK_DEEP)
    painter.drawText(108, 980, f"闲鱼 · {GOOFISH_ID}")
    painter.end()
    canvas.save(str(path))
    print("OK", path.name)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyhbd.ttc")
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    make_goofish_qr()

    render_logo_intro(SCENES_DIR / "00_intro.png")

    render_dual_scene(
        SCENES_DIR / "01_composition.png",
        index=2,
        title="批量混剪",
        subtitle="素材导入 · 随机/自定义编排 · 批次差异化",
        main_page="composition",
        inset_page="composition_settings",
        inset_caption="编排 · 批次与随机种子",
        main_callouts=[
            {"num": 1, "text": "素材拖入即用", "rect": [56, 91, 260, 845], "badge": "bl", "side": "right", "dy": -8},
            {"num": 2, "text": "首帧预览", "rect": [820, 92, 320, 460], "badge": "tl", "side": "left", "dx": 6, "dy": 6},
            {"num": 3, "text": "导入 / 清理素材", "rect": [1416, 546, 184, 53], "badge": "bl", "side": "left", "dy": 6},
        ],
    )

    render_full_scene(
        SCENES_DIR / "02_spider.png",
        index=3,
        title="爆品选品爬虫",
        subtitle="对标账号抓取 · 多维筛选 · Excel 报表",
        page="spider",
        callouts=[
            {"num": 1, "text": "对标账号（抖音 / 快手）", "rect": [336, 142, 1484, 150], "badge": "tl", "side": "right", "dx": 8, "dy": 10},
            {"num": 2, "text": "多维筛选爆品", "rect": [336, 538, 1484, 146], "badge": "br", "side": "right", "dy": -10},
            {"num": 3, "text": "抓取 · 定时 · 送入下载", "rect": [336, 700, 366, 48], "badge": "bl", "side": "left", "dy": -14},
        ],
    )

    render_full_scene(
        SCENES_DIR / "03_subtitles.png",
        index=4,
        title="字幕实验室",
        subtitle="离线识别 · OCR 定位 · 一键烧录",
        page="subtitles",
        callouts=[
            {"num": 1, "text": "框选 / 检测字幕区域", "rect": [560, 190, 500, 300], "badge": "tr", "side": "right", "dx": 6, "dy": 6},
            {"num": 2, "text": "Whisper 离线识别 · OCR", "rect": [336, 575, 400, 100], "badge": "bl", "side": "left", "dy": 10},
            {"num": 3, "text": "字幕列表可编辑导出", "rect": [336, 864, 1254, 130], "badge": "br", "side": "left", "dy": -8},
        ],
    )

    render_dual_scene(
        SCENES_DIR / "04_overlays.png",
        index=5,
        title="蒙版 · 贴纸",
        subtitle="三类蒙版多层叠加 · 贴纸库随机抽取",
        main_page="overlays",
        inset_page="stickers",
        inset_caption="贴纸素材库 · 随机抽取",
        main_callouts=[
            {"num": 1, "text": "蒙版素材库", "rect": [336, 166, 1254, 150], "badge": "tl", "side": "right", "dx": 8, "dy": 8},
            {"num": 2, "text": "蒙版轨道 · 多层叠加", "rect": [336, 350, 1254, 192], "badge": "bl", "side": "right", "dy": -6},
        ],
    )

    render_dual_scene(
        SCENES_DIR / "05_queue.png",
        index=6,
        title="渲染队列 · 硬件加速",
        subtitle="可暂停调度 · 失败隔离重试",
        main_page="queue",
        inset_page="settings",
        inset_caption="硬件编码器自动检测",
        main_callouts=[
            {"num": 1, "text": "实时进度 · 可暂停", "rect": [336, 176, 1256, 130], "badge": "bl", "side": "right", "dy": -8},
            {"num": 2, "text": "失败隔离 · 一键重试", "rect": [336, 486, 1256, 84], "badge": "bl", "side": "right", "dy": 14},
        ],
    )

    render_logo_outro(SCENES_DIR / "06_outro.png")
    render_cover(SCENES_DIR / "cover.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
