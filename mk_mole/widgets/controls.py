"""iOS 风格的自绘控件：分段控件、状态胶囊、进度条、交通灯、吐司等。"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .icons import icon
from ..theme import Color, app_font


def vspace(height: int) -> QWidget:
    w = QWidget()
    w.setFixedHeight(height)
    return w


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("Hairline")
    line.setFixedHeight(1)
    return line


def card(*, inset: bool = False) -> QFrame:
    frame = QFrame()
    frame.setObjectName("InsetCard" if inset else "Card")
    return frame


def make_label(text: str, object_name: str = "", size: int | None = None,
               weight: QFont.Weight = QFont.Weight.Normal,
               color: str | None = None) -> QLabel:
    lab = QLabel(text)
    if object_name:
        lab.setObjectName(object_name)
    if size is not None:
        lab.setFont(app_font(size, weight))
    if color:
        lab.setStyleSheet(f"color: {color};")
    return lab


class IOSLineEdit(QLineEdit):
    def __init__(self, placeholder: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFont(app_font(13))
        self.setClearButtonEnabled(False)
        self.setMinimumHeight(38)


class PillButton(QPushButton):
    """variant: primary / tinted / secondary / ghost / destructive / icon。"""

    def __init__(self, text: str = "", *, variant: str = "secondary",
                 icon_name: str | None = None, icon_color: str | None = None,
                 parent: QWidget | None = None, height: int = 38):
        super().__init__(text, parent)
        self.setProperty("variant", variant)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(app_font(13, QFont.Weight.DemiBold))
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        if icon_name:
            color = icon_color or ("#FFFFFF" if variant == "primary" else Color.blue)
            self.setIcon(icon(icon_name, color, 17, 1.9))
            self.setIconSize(QSize(17, 17))
        if variant == "icon":
            self.setFixedSize(height, height)
            self.setStyleSheet("padding: 0px;")


class IconButton(PillButton):
    def __init__(self, icon_name: str, tooltip: str = "", *,
                 color: str = Color.secondary, size: int = 34,
                 parent: QWidget | None = None):
        super().__init__("", variant="icon", parent=parent, height=size)
        self.setIcon(icon(icon_name, color, 18, 1.8))
        self.setIconSize(QSize(18, 18))
        self.setToolTip(tooltip)
        self.setFixedSize(size, size)


class SegmentedControl(QWidget):
    """带滑动白色指示块的 iOS 分段控件。"""

    changed = Signal(int)

    def __init__(self, items: list[str], parent: QWidget | None = None,
                 *, height: int = 34, min_segment: int = 44):
        super().__init__(parent)
        self._items = list(items)
        self._index = 0
        self._pos = 0.0
        self._hover = -1
        self._height = height
        self._min_segment = min_segment
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._update_width()

    def _update_width(self) -> None:
        fm = QFontMetrics(app_font(12, QFont.Weight.DemiBold))
        widest = max((fm.horizontalAdvance(t) for t in self._items), default=0)
        seg = max(self._min_segment, widest + 18)
        self.setFixedWidth(seg * len(self._items) + 8)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self._height)

    def set_items(self, items: list[str]) -> None:
        self._items = list(items)
        self._index = min(self._index, max(0, len(items) - 1))
        self._update_width()
        self.update()

    def current_index(self) -> int:
        return self._index

    def set_current_index(self, index: int, *, animate: bool = True, emit: bool = False) -> None:
        if not self._items:
            return
        index = max(0, min(index, len(self._items) - 1))
        old = self._index
        self._index = index
        if animate and old != index:
            self._anim.stop()
            self._anim.setStartValue(float(old))
            self._anim.setEndValue(float(index))
            self._anim.start()
        else:
            self._pos = float(index)
            self.update()
        if emit and old != index:
            self.changed.emit(index)

    def _on_anim(self, value) -> None:
        self._pos = float(value)
        self.update()

    def _segment_rect(self, index: float) -> QRectF:
        n = max(1, len(self._items))
        seg = (self.width() - 8) / n
        return QRectF(4 + seg * index, 4, seg, self.height() - 8)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._items:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(0.45)
        # 背景
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(118, 118, 128, 28))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        # 选中块
        rect = self._segment_rect(self._pos)
        p.setBrush(QColor(255, 255, 255, 245))
        p.setPen(QPen(QColor(60, 60, 67, 18), 1))
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 14))
        p.drawRoundedRect(rect.translated(0, 1).adjusted(1, 1, -1, -1), 8, 8)
        p.setBrush(QColor(255, 255, 255, 245))
        p.setPen(QPen(QColor(60, 60, 67, 16), 1))
        p.drawRoundedRect(rect, 8, 8)

        # 文本
        for i, text in enumerate(self._items):
            r = self._segment_rect(i)
            if i == self._index:
                p.setPen(QColor(Color.label))
                p.setFont(app_font(12, QFont.Weight.DemiBold))
            elif i == self._hover:
                p.setPen(QColor(Color.label))
                p.setFont(app_font(12, QFont.Weight.Medium))
            else:
                p.setPen(QColor(60, 60, 67, 165))
                p.setFont(app_font(12, QFont.Weight.Medium))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._items:
            n = len(self._items)
            seg = (self.width() - 8) / n
            idx = int((event.position().x() - 4) // max(seg, 1))
            idx = max(0, min(n - 1, idx))
            if idx != self._index:
                self.set_current_index(idx, emit=True)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        n = max(1, len(self._items))
        seg = (self.width() - 8) / n
        idx = int((event.position().x() - 4) // max(seg, 1))
        idx = max(0, min(n - 1, idx))
        if idx != self._hover:
            self._hover = idx
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)


class Switch(QWidget):
    """iOS 风格开关，默认 46×26，带平滑滑动动画。"""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._pos = 1.0 if checked else 0.0
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("开启 / 关闭")
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, *, animate: bool = True, emit: bool = False) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        if animate:
            self._anim.stop()
            self._anim.setStartValue(float(self._pos))
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()
        else:
            self._pos = 1.0 if checked else 0.0
            self.update()
        if emit:
            self.toggled.emit(checked)

    def _on_anim(self, value) -> None:
        self._pos = float(value)
        self.update()

    def toggle(self) -> None:
        self.setChecked(not self._checked, emit=True)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            if self.rect().contains(event.position().toPoint()):
                self.toggle()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(0.45)
        track = QRectF(0, 2, self.width(), self.height() - 4)
        off = QColor(120, 120, 128, 55)
        on = QColor(Color.green)
        col = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
            int(off.alpha() + (on.alpha() - off.alpha()) * self._pos),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob_r = self.height() - 8
        x = 4 + self._pos * (self.width() - knob_r - 8)
        knob = QRectF(x, 4, knob_r, knob_r)
        p.setBrush(QColor(0, 0, 0, 28))
        p.drawEllipse(knob.translated(0, 1.2))
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(60, 60, 67, 22), 1))
        p.drawEllipse(knob)
        p.end()


class StatusPill(QWidget):
    """带小圆点的状态胶囊：idle/running/success/warning/error/cancelled。"""

    _COLORS = {
        "idle": ("rgba(120,120,128,20%)", Color.secondary, Color.tertiary),
        "running": ("rgba(0,122,255,14%)", Color.blue, Color.blue),
        "success": ("rgba(52,199,89,16%)", "#1C8C3B", Color.green),
        "warning": ("rgba(255,149,0,16%)", "#A45B00", Color.orange),
        "error": ("rgba(255,59,48,14%)", "#C7241C", Color.red),
        "cancelled": ("rgba(120,120,128,20%)", Color.secondary, Color.secondary),
    }

    def __init__(self, text: str = "", kind: str = "idle", parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self._kind = kind
        self.setFont(app_font(11, QFont.Weight.DemiBold))
        self.setMinimumHeight(24)
        self.setMaximumHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._resize()

    def _resize(self) -> None:
        fm = QFontMetrics(self.font())
        self.setFixedWidth(fm.horizontalAdvance(self._text) + 38)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        # 构造时全局样式/字体尚未最终生效，按最终字体重新测量，避免文字被裁切。
        self._resize()
        super().showEvent(event)

    def set_status(self, text: str, kind: str) -> None:
        self._text = text
        self._kind = kind
        self._resize()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg, fg, dot = self._COLORS.get(self._kind, self._COLORS["idle"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg) if not bg.startswith("rgba") else _rgba(bg))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 12, 12)
        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(13, self.height() / 2), 3.0, 3.0)
        p.setPen(QColor(fg))
        p.setFont(self.font())
        p.drawText(QRectF(22, 0, self.width() - 26, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        p.end()


def _rgba(value: str) -> QColor:
    """解析 rgba(r,g,b,a%) 形式的颜色。"""
    try:
        inner = value[value.index("(") + 1:value.index(")")]
        parts = [p.strip() for p in inner.split(",")]
        r, g, b = (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
        a_raw = parts[3]
        a = int(float(a_raw[:-1]) / 100 * 255) if a_raw.endswith("%") else int(float(a_raw))
        return QColor(r, g, b, max(0, min(255, a)))
    except (ValueError, IndexError):
        return QColor(120, 120, 128, 30)


class Spinner(QWidget):
    """iOS 风格的 12 刻度活动指示器。"""

    def __init__(self, size: int = 16, color: str = Color.blue, parent: QWidget | None = None):
        super().__init__(parent)
        self._angle = 0
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self) -> None:
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 1) % 12
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self._angle * 30)
        for i in range(12):
            alpha = int(28 + (i / 11) * 212)
            col = QColor(self._color)
            col.setAlpha(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.save()
            p.rotate(i * 30)
            p.drawRoundedRect(QRectF(-1.0, -self.height() * 0.42, 2.0, self.height() * 0.24), 1, 1)
            p.restore()
        p.end()


class ProgressTrack(QWidget):
    """圆角渐变进度条，值变化时平滑过渡。"""

    valueChanged = Signal(float)

    def __init__(self, parent: QWidget | None = None, height: int = 8):
        super().__init__(parent)
        self._value = 0.0
        self._target = 0.0
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.update())

    def get_value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    value = Property(float, get_value, set_value)

    def set_target(self, value: float, *, animate: bool = True) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._target = value
        if animate and abs(value - self._value) > 0.001:
            self._anim.stop()
            self._anim.setStartValue(self._value)
            self._anim.setEndValue(value)
            self._anim.start()
        else:
            self.set_value(value)
        self.valueChanged.emit(value)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(120, 120, 128, 30))
        p.drawRoundedRect(r, self.height() / 2, self.height() / 2)
        if self._value > 0.001:
            fill_w = max(self.height(), r.width() * self._value)
            fill = QRectF(0, 0, min(fill_w, r.width()), r.height())
            grad = QLinearGradient(0, 0, r.width(), 0)
            grad.setColorAt(0.0, QColor("#0A84FF"))
            grad.setColorAt(1.0, QColor("#64D2FF"))
            p.setBrush(grad)
            p.drawRoundedRect(fill, self.height() / 2, self.height() / 2)
            # 顶部高光
            p.setBrush(QColor(255, 255, 255, 55))
            p.drawRoundedRect(fill.adjusted(2, 1.4, -2, -fill.height() / 2), 3, 3)
        p.end()


class TrafficLights(QWidget):
    closeClicked = Signal()
    minimizeClicked = Signal()
    zoomClicked = Signal()

    _COLORS = ("#FF6B60", "#FFCC00", "#34C759")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._hover = -1
        self._pressed = -1
        self.setFixedSize(70, 22)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("关闭  ·  最小化  ·  缩放")

    def _dot_rect(self, index: int) -> QRectF:
        return QRectF(index * 22 + 2, 4, 14, 14)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, color in enumerate(self._COLORS):
            r = self._dot_rect(i)
            p.setPen(QPen(QColor(0, 0, 0, 22), 1))
            p.setBrush(QColor(color))
            p.drawEllipse(r)
            if self._hover == i:
                p.setPen(QPen(QColor(60, 60, 67, 170), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                cx, cy = r.center().x(), r.center().y()
                if i == 0:
                    p.drawLine(QPointF(cx - 2.2, cy - 2.2), QPointF(cx + 2.2, cy + 2.2))
                    p.drawLine(QPointF(cx + 2.2, cy - 2.2), QPointF(cx - 2.2, cy + 2.2))
                elif i == 1:
                    p.drawLine(QPointF(cx - 2.8, cy), QPointF(cx + 2.8, cy))
                else:
                    p.drawLine(QPointF(cx - 2.6, cy), QPointF(cx + 2.6, cy))
                    p.drawLine(QPointF(cx, cy - 2.6), QPointF(cx, cy + 2.6))
        p.end()

    def _index_at(self, pos: QPoint) -> int:
        for i in range(3):
            if self._dot_rect(i).adjusted(-2, -2, 2, 2).contains(QPointF(pos)):
                return i
        return -1

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        idx = self._index_at(event.position().toPoint())
        if idx != self._hover:
            self._hover = idx
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self._pressed = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index_at(event.position().toPoint())
            if index >= 0:
                self._pressed = index
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index_at(event.position().toPoint())
            if index >= 0:
                if index == self._pressed:
                    if index == 0:
                        self.closeClicked.emit()
                    elif index == 1:
                        self.minimizeClicked.emit()
                    else:
                        self.zoomClicked.emit()
                self._pressed = -1
                event.accept()
                return
            self._pressed = -1
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._index_at(event.position().toPoint()) >= 0:
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class Toast(QWidget):
    """窗口底部居中的深色提示条，带淡入淡出。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 20, 10)
        layout.setSpacing(9)
        self._dot = QWidget()
        self._dot.setFixedSize(8, 8)
        layout.addWidget(self._dot)
        self._label = QLabel("")
        self._label.setFont(app_font(12.5, QFont.Weight.Medium))
        self._label.setStyleSheet("color: white; background: transparent;")
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(520)
        layout.addWidget(self._label)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(180)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(28, 28, 30, 235))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), self.height() / 2, self.height() / 2)
        p.end()

    def _dot_style(self, kind: str) -> None:
        color = {
            "success": Color.green,
            "error": Color.red,
            "warning": Color.orange,
            "info": Color.blue_light,
        }.get(kind, Color.blue_light)
        self._dot.setStyleSheet(
            f"background: {color}; border-radius: 4px;"
        )

    def show_message(self, text: str, kind: str = "info", duration: int = 2800) -> None:
        self._label.setText(text)
        self._dot_style(kind)
        self.adjustSize()
        parent = self.parentWidget()
        if parent:
            x = (parent.width() - self.width()) // 2
            y = max(12, parent.height() - self.height() - 96)
            self.move(max(12, x), y)
        self.raise_()
        self.show()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(duration)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._hide_once)
        self._fade.start()

    def _hide_once(self) -> None:
        try:
            self._fade.finished.disconnect(self._hide_once)
        except (RuntimeError, TypeError):
            pass
        self.hide()


class ElementDot(QWidget):
    def __init__(self, color: str, size: int = 10, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        grad = QRadialGradient(r.center() - QPointF(r.width() * 0.2, r.height() * 0.25),
                               r.width() * 0.9)
        base = QColor(self._color)
        grad.setColorAt(0.0, base.lighter(145))
        grad.setColorAt(1.0, base.darker(118))
        p.setPen(QPen(QColor(0, 0, 0, 35), 0.8))
        p.setBrush(grad)
        p.drawEllipse(r)
        p.end()


class EmptyMoleculeArt(QWidget):
    """空状态的分子插画（柔和渐变球 + 键）。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(230, 170)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # 背景光晕
        glow = QRadialGradient(QPointF(cx, cy), w * 0.48)
        glow.setColorAt(0.0, QColor(0, 122, 255, 26))
        glow.setColorAt(0.65, QColor(88, 86, 214, 10))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(cx - w * 0.48, cy - w * 0.48, w * 0.96, w * 0.96))

        nodes = [
            (QPointF(cx - 2, cy - 42), 30, "#4FACFE", "#0A84FF"),
            (QPointF(cx - 60, cy + 38), 22, "#AF7CFF", "#7A5AF8"),
            (QPointF(cx + 62, cy + 30), 24, "#5CE1E6", "#12A8C7"),
        ]
        # 键
        pen = QPen(QColor(160, 170, 195, 120), 9)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for i in range(3):
            p.drawLine(nodes[i][0], nodes[(i + 1) % 3][0])

        for center, radius, light, dark in nodes:
            draw_orb(p, center, radius, QColor(light), QColor(dark))

        # 高光点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawEllipse(nodes[0][0] + QPointF(-9, -10), 9, 7)
        p.end()


def draw_orb(p: QPainter, center: QPointF, radius: float,
             light: QColor, dark: QColor) -> None:
    grad = QRadialGradient(center - QPointF(radius * 0.35, radius * 0.4), radius * 1.7)
    grad.setColorAt(0.0, light.lighter(125))
    grad.setColorAt(0.55, light)
    grad.setColorAt(1.0, dark)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawEllipse(center, radius, radius)
    p.setBrush(QColor(255, 255, 255, 48))
    p.drawEllipse(center - QPointF(radius * 0.28, radius * 0.34), radius * 0.38, radius * 0.26)
