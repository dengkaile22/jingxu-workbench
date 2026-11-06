"""排查 offscreen 模式下中文字体渲染。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(["font-test"])

families = QFontDatabase.families()
print("字体总数:", len(families))
print("含 YaHei 的族:", [f for f in families if "YaHei" in f or "雅黑" in f][:10])
print("含 SimSun 的族:", [f for f in families if "SimSun" in f][:5])
print("前 20 个族:", families[:20])

image = QImage(900, 300, QImage.Format.Format_ARGB32)
image.fill(0xFFFFFFFF)
painter = QPainter(image)
font = QFont()
font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "SimSun"])
font.setPixelSize(40)
painter.setFont(font)
painter.drawText(20, 60, "测试中文渲染：清影快速混剪 2026")
painter.drawText(20, 120, "批量混剪 · 选品爬虫 · 字幕实验室")
font2 = QFont("Microsoft YaHei")
font2.setPixelSize(40)
painter.setFont(font2)
painter.drawText(20, 200, "直接指定族名：抖音快手对标账号抓取")
painter.end()
out = os.path.join(os.path.dirname(__file__), "font-probe.png")
image.save(out)
print("saved", out)
