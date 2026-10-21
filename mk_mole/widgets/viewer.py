"""基于 QWebEngine + 3Dmol.js 的本地 3D 分子查看器。"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget


def assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


class MoleculeViewer(QWidget):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._ready = False
        self._pending_sdf: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.web = QWebEngineView(self)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web.setStyleSheet("background: #ffffff;")
        self.web.setMinimumHeight(220)
        settings = self.web.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        try:
            self.web.page().setBackgroundColor(QColor("#FFFFFF"))
        except AttributeError:
            pass
        self.web.loadFinished.connect(self._load_finished)
        self.web.load(QUrl.fromLocalFile(str(assets_dir() / "viewer.html")))
        layout.addWidget(self.web)

    def _load_finished(self, ok: bool) -> None:
        if not ok:
            self.failed.emit("3D 视图加载失败")
            return
        self.web.page().runJavaScript("window.mkViewerReady === true", 0, self._check_ready)

    def _check_ready(self, result) -> None:
        if result:
            self._become_ready()
        else:
            # 3Dmol 可能比 loadFinished 稍晚初始化完成
            self._poll_ready(0)

    def _poll_ready(self, attempts: int) -> None:
        if attempts > 40:
            self.failed.emit("3D 引擎初始化超时")
            return
        self.web.page().runJavaScript("window.mkViewerReady === true", 0, self._poll_result)

    def _poll_result(self, result) -> None:
        if result:
            self._become_ready()
        else:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(120, lambda: self._poll_ready(0))

    def _become_ready(self) -> None:
        if self._ready:
            return
        self._ready = True
        if self._pending_sdf:
            sdf, self._pending_sdf = self._pending_sdf, None
            self.load_structure(sdf)
        self.ready.emit()

    def is_ready(self) -> bool:
        return self._ready

    def load_structure(self, sdf: str) -> None:
        if not self._ready:
            self._pending_sdf = sdf
            return
        script = f"window.setStructure({json.dumps(sdf)});"
        self.web.page().runJavaScript(script, 0, lambda ok: None if ok else self.failed.emit("结构渲染失败"))

    def set_view(self, quaternion: tuple[float, float, float, float]) -> None:
        if not self._ready:
            return
        qx, qy, qz, qw = quaternion
        self.web.page().runJavaScript(f"window.setView({qx},{qy},{qz},{qw});")

    def reset_view(self) -> None:
        if self._ready:
            self.web.page().runJavaScript("window.resetView();")

    def clear(self) -> None:
        if self._ready:
            self.web.page().runJavaScript("window.clearStructure();")

    def grab_png(self, callback) -> None:
        """异步取当前视角 PNG；callback(data_url: str)。"""
        if not self._ready:
            callback("")
            return
        self.web.page().runJavaScript("window.pngURI()", 0, callback)
