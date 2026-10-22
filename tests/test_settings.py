"""设置弹层测试：CAS Key 字段、回显与保存快照。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget  # noqa: E402

from mk_mole.config import AppConfig  # noqa: E402
from mk_mole.views.dialogs import SettingsSheet  # noqa: E402
from mk_mole.widgets.controls import StatusPill  # noqa: E402


def test_status_pill_resizes_with_final_font() -> None:
    app = QApplication.instance() or QApplication([])
    pill = StatusPill("CAS Common Chemistry")
    pill.show()
    app.processEvents()

    needed = QFontMetrics(pill.font()).horizontalAdvance("CAS Common Chemistry") + 38
    assert pill.width() == needed
    pill.close()


def test_settings_has_cas_key_field() -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1240, 840)
    sheet = SettingsSheet(
        AppConfig(api_key="sk-test", cas_api_key="cas-test"),
        parent,
    )
    sheet.show()
    app.processEvents()

    assert sheet.cas_key_edit.text() == "cas-test"
    assert sheet.cas_key_edit.echoMode() == QLineEdit.EchoMode.Password
    assert sheet._snapshot().cas_api_key == "cas-test"
    # 新增一行 CAS 字段后，设置页仍不应被横向裁切。
    assert sheet._form_scroll.horizontalScrollBar().maximum() == 0
    sheet.close()
