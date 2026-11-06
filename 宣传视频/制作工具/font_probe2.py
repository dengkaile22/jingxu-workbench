"""验证：真实平台 + WA_DontShowOnScreen 能否正常渲染中文并截图。"""

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

app = QApplication(["font-test2"])
print("字体总数:", len(QFontDatabase.families()))
print("含 YaHei 的族:", [f for f in QFontDatabase.families() if "YaHei" in f][:8])

window = QWidget()
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
layout = QVBoxLayout(window)
label = QLabel("测试中文渲染：清影快速混剪 · 批量混剪与选品爬虫 2026")
label.setStyleSheet("font-size: 28px; color: #17231F;")
layout.addWidget(label)
window.resize(900, 200)
window.show()
app.processEvents()
image = window.grab()
out = r"C:\Users\DENGKA~1\AppData\Local\Temp\commandcode\C--Users-dengkaile-Desktop-------\11257bbf-07af-4710-9166-e307c03495ba\scratchpad\promo\tools\font-probe2.png"
image.save(out)
print("saved", out, image.width(), image.height())
