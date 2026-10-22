"""无边框圆角主窗口：自绘阴影、标题栏、窗口控制与缩放热区。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from .controls import IconButton, Toast, TrafficLights, make_label
from .icons import app_icon, icon
from ..theme import Color, app_font


class ShadowCanvas(QWidget):
    """负责在圆角卡片外绘制柔和阴影。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._margin = 18
        self._root: QWidget | None = None

    def set_root(self, root: QWidget) -> None:
        self._root = root

    def set_margin(self, margin: int) -> None:
        self._margin = margin
        self.update()

    def margin(self) -> int:
        return self._margin

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._root or self._margin <= 0:
            return
        m = self._margin
        rect = QRectF(m, m + 5, self.width() - 2 * m, self.height() - 2 * m - 5)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        layers = 13
        for i in range(layers, 0, -1):
            spread = i * 1.1
            alpha = int(2 + (layers - i) * 1.4)
            p.setBrush(QColor(24, 24, 40, alpha))
            p.drawRoundedRect(rect.adjusted(-spread, -spread * 0.55, spread, spread),
                              24 + spread, 24 + spread)
        p.end()


class TitleBar(QWidget):
    """自绘标题栏：左侧交通灯，中间品牌，右侧设置。"""

    settingsClicked = Signal()

    def __init__(self, window: "FramelessWindow"):
        super().__init__(window)
        self._window = window
        self.setFixedHeight(50)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 14, 0)
        layout.setSpacing(0)

        self.lights = TrafficLights(self)
        self.lights.closeClicked.connect(window.close)
        self.lights.minimizeClicked.connect(window.showMinimized)
        self.lights.zoomClicked.connect(window.toggle_maximize)
        layout.addWidget(self.lights, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        center = QHBoxLayout()
        center.setSpacing(7)
        brand_icon = QLabel()
        brand_icon.setPixmap(icon("molecule", Color.secondary, 15, 1.7).pixmap(15, 15))
        brand_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        brand = make_label("MK-MOLE", size=12, weight=app_font(12).weight())
        brand.setStyleSheet(f"color: {Color.secondary}; font-weight: 600; letter-spacing: 0.4px;")
        brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        dot = make_label("·", color=Color.tertiary)
        dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        page = make_label("构建分子", color=Color.tertiary)
        page.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        for w in (brand_icon, brand, dot, page):
            center.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(center)
        layout.addStretch(1)

        self.settings = IconButton("chevron-down", "设置", color=Color.secondary, size=32)
        self.settings.setIcon(icon("atom", Color.secondary, 18, 1.7))
        self.settings.clicked.connect(self.settingsClicked)
        layout.addWidget(self.settings, 0, Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _EdgeHandle(QWidget):
    """透明缩放热区，按下后交给系统完成缩放。"""

    def __init__(self, window: "FramelessWindow", edges: Qt.Edge):
        super().__init__(window)
        self._window = window
        self._edges = edges
        if edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edges == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge) or edges == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle:
                handle.startSystemResize(self._edges)
        super().mousePressEvent(event)


class FramelessWindow(QMainWindow):
    """带圆角卡片外观的无边框窗口。"""

    immersiveChanged = Signal(bool)

    def __init__(self, title: str = "MK-MOLE"):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(1100, 660)
        screen = QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = min(1280, max(1100, available.width() - 80))
            height = min(950, max(660, available.height() - 80))
            self.resize(width, height)
        else:
            self.resize(1240, 840)

        self._immersive = False
        self._normal_margin = 18

        self.canvas = ShadowCanvas(self)
        self.setCentralWidget(self.canvas)
        self._canvas_layout = QVBoxLayout(self.canvas)
        self._canvas_layout.setContentsMargins(18, 18, 18, 18)
        self._canvas_layout.setSpacing(0)

        self.root = QFrame()
        self.root.setObjectName("Root")
        self._canvas_layout.addWidget(self.root)
        self.canvas.set_root(self.root)

        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)

        self.content = QWidget()
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(22, 0, 22, 22)
        self._content_layout.setSpacing(0)
        root_layout.addWidget(self.content, 1)

        self.toast = Toast(self.root)

        self._handles: list[_EdgeHandle] = []
        for edges in (
            Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        ):
            handle = _EdgeHandle(self, edges)
            handle.show()
            handle.raise_()
            self._handles.append(handle)

    # ---------- 内容 ----------
    def set_content(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget, 1)

    def show_toast(self, text: str, kind: str = "info", duration: int = 2800) -> None:
        self.toast.show_message(text, kind, duration)

    # ---------- 窗口状态 ----------
    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._update_layout_state()

    def set_immersive(self, enabled: bool) -> None:
        if enabled == self._immersive:
            return
        self._immersive = enabled
        self.title_bar.setVisible(not enabled)
        if enabled:
            self._normal_margin = self.canvas.margin()
            self.canvas.set_margin(0)
            self._canvas_layout.setContentsMargins(0, 0, 0, 0)
            self.root.setProperty("fullscreen", "true")
            self.showFullScreen()
        else:
            self.canvas.set_margin(self._normal_margin)
            self._canvas_layout.setContentsMargins(
                self._normal_margin, self._normal_margin,
                self._normal_margin, self._normal_margin)
            self.root.setProperty("fullscreen", "false")
            self.showNormal()
        self._repolish(self.root)
        self._update_layout_state()
        self.immersiveChanged.emit(enabled)

    def toggle_immersive(self) -> None:
        self.set_immersive(not self._immersive)

    def is_immersive(self) -> bool:
        return self._immersive

    def _repolish(self, widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _update_layout_state(self) -> None:
        maximized = self.isMaximized()
        margin = 0 if (maximized or self._immersive) else self._normal_margin
        if not self._immersive:
            self.canvas.set_margin(margin)
            self._canvas_layout.setContentsMargins(margin, margin, margin, margin)
        self._position_handles()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self._update_layout_state()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_handles()
        if self.toast.isVisible():
            self.toast.adjustSize()
            self.toast.move(
                (self.width() - self.toast.width()) // 2,
                max(12, self.height() - self.toast.height() - 96),
            )

    def _position_handles(self) -> None:
        if not self._handles:
            return
        w, h = self.width(), self.height()
        if self._immersive or self.isMaximized():
            for handle in self._handles:
                handle.hide()
            return
        m = self.canvas.margin()
        t = 8
        c = 14
        x0, y0 = m, m
        x1, y1 = w - m, h - m
        for handle in self._handles:
            handle.show()
            edges = handle._edges
            if edges == Qt.Edge.LeftEdge:
                handle.setGeometry(x0 - t // 2, y0 + c, t, max(0, y1 - y0 - 2 * c))
            elif edges == Qt.Edge.RightEdge:
                handle.setGeometry(x1 - t // 2, y0 + c, t, max(0, y1 - y0 - 2 * c))
            elif edges == Qt.Edge.TopEdge:
                handle.setGeometry(x0 + c, y0 - t // 2, max(0, x1 - x0 - 2 * c), t)
            elif edges == Qt.Edge.BottomEdge:
                handle.setGeometry(x0 + c, y1 - t // 2, max(0, x1 - x0 - 2 * c), t)
            elif edges == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge):
                handle.setGeometry(x0 - t // 2, y0 - t // 2, c, c)
            elif edges == (Qt.Edge.TopEdge | Qt.Edge.RightEdge):
                handle.setGeometry(x1 - c + t // 2, y0 - t // 2, c, c)
            elif edges == (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
                handle.setGeometry(x0 - t // 2, y1 - c + t // 2, c, c)
            else:
                handle.setGeometry(x1 - c + t // 2, y1 - c + t // 2, c, c)
            handle.raise_()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._immersive:
            self.set_immersive(False)
            return
        if event.key() == Qt.Key.Key_F11:
            self.toggle_immersive()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # 由具体页面在关闭前保存表单状态
        super().closeEvent(event)
