"""应用启动与窗口装配。"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .config import AppConfig
from .theme import GLOBAL_QSS, apply_palette, app_font
from .views.builder import BuilderPage
from .widgets.icons import app_icon
from .widgets.window import FramelessWindow


def _set_windows_app_id() -> None:
    """让 Windows 任务栏把窗口归到 MK-MOLE，而不是 python.exe。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "MK-MOLE.MoleculeBuilder.1"
        )
    except Exception:  # noqa: BLE001
        pass


def create_app(argv: list[str] | None = None) -> tuple[QApplication, FramelessWindow, BuilderPage]:
    _set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("MK-MOLE")
    app.setApplicationDisplayName("MK-MOLE · 构建分子")
    app.setOrganizationName("MK-MOLE")
    app.setDesktopFileName("mk-mole")
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(True)
    apply_palette(app)
    app.setFont(app_font(13, QFont.Weight.Normal))
    app.setStyleSheet(GLOBAL_QSS)

    config = AppConfig.load()
    window = FramelessWindow("MK-MOLE · 构建分子")
    page = BuilderPage(config)
    window.set_content(page)
    window.title_bar.settingsClicked.connect(page.open_settings)
    app.aboutToQuit.connect(page.shutdown)

    if config.configured:
        effort = config.reasoning_effort or "high"
        QTimer.singleShot(900, lambda: window.show_toast(
            f"已连接 DeepSeek · {config.model} · {effort}", "info", 2200))
    return app, window, page


def main() -> int:
    app, window, _page = create_app()
    window.show()
    return app.exec()
