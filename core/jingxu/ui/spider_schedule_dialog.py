"""Daily selection time, with an explicit enable/disable control."""
from dataclasses import replace

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QTimeEdit, QVBoxLayout

from jingxu.infrastructure.spider_schedule import DailySchedule
from jingxu.ui.widgets import Caption, SectionHeader
from jingxu.ui import theme


class SpiderScheduleDialog(QDialog):
    def __init__(self, schedule: DailySchedule, parent=None):
        super().__init__(parent)
        self._original = schedule
        self.setObjectName("SpiderScheduleDialog")
        self.setStyleSheet(f"QDialog#SpiderScheduleDialog {{ background: {theme.SURFACE_PANEL}; }} QTimeEdit {{ background: {theme.SURFACE_PANEL}; border: 1px solid {theme.LINE_DEFAULT}; border-radius: 4px; padding: 6px; min-height: 24px; }}")
        self.setWindowTitle("定时抓取设置")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(SectionHeader("每天自动抓取"))
        self._enabled = QCheckBox("启用每日定时抓取")
        self._enabled.setChecked(schedule.enabled)
        layout.addWidget(self._enabled)
        row = QHBoxLayout()
        row.addWidget(Caption("每天开始时间"))
        self._time = QTimeEdit(QTime.fromString(schedule.time, "HH:mm"))
        self._time.setDisplayFormat("HH:mm")
        self._time.setMinimumWidth(120)
        self._time.setEnabled(schedule.enabled)
        self._enabled.toggled.connect(self._time.setEnabled)
        row.addWidget(self._time)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(Caption("按已保存的启用账号和下方筛选报表抓取，完成后自动保存 Excel 报表。已有抓取任务运行时跳过本次启动。"))
        layout.addWidget(Caption("由 Windows 自动启动，关闭软件后也可执行。电脑需开机、保持当前 Windows 账号登录并联网；请先扫码保存 Cookie。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存定时设置")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def schedule(self):
        return replace(self._original, enabled=self._enabled.isChecked(), time=self._time.time().toString("HH:mm"))
