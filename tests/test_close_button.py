"""窗口控制按钮测试：确认红点点击不会被父级标题栏吞掉。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget  # noqa: E402

from mk_mole.widgets.controls import TrafficLights  # noqa: E402


class _FakeTitleBar(QWidget):
    def __init__(self):
        super().__init__()
        self.pressed = 0
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.lights = TrafficLights(self)
        self.layout.addWidget(self.lights)
        self.resize(100, 45)

    def mousePressEvent(self, event):  # noqa: N802
        self.pressed += 1
        super().mousePressEvent(event)


def test_red_traffic_light_emits_close_and_does_not_bubble() -> None:
    app = QApplication.instance() or QApplication([])
    bar = _FakeTitleBar()
    bar.show()
    fired: list[bool] = []
    bar.lights.closeClicked.connect(lambda: fired.append(True))
    QTest.mouseClick(bar.lights, Qt.MouseButton.LeftButton, pos=QPoint(9, 11))
    app.processEvents()
    assert fired == [True]
    assert bar.pressed == 0
    bar.close()
