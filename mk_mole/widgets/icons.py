"""用 QPainter 绘制的线性图标，避免依赖额外的图标字体。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from ..theme import Color


def _pixmap(name: str, color: str, size: int, width: float) -> QPixmap:
    scale = 3
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(scale, scale)
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)
    _draw(p, name, s, color, width)
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def _draw(p: QPainter, name: str, s: float, color: str, width: float) -> None:
    if name == "search":
        r = s * 0.28
        c = QPointF(s * 0.44, s * 0.44)
        p.drawEllipse(c, r, r)
        p.drawLine(QPointF(s * 0.64, s * 0.64), QPointF(s * 0.82, s * 0.82))

    elif name == "image":
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.20, s * 0.72, s * 0.60), s * 0.10, s * 0.10)
        p.drawEllipse(QPointF(s * 0.36, s * 0.38), s * 0.055, s * 0.055)
        path = QPainterPath(QPointF(s * 0.20, s * 0.72))
        path.lineTo(s * 0.40, s * 0.50)
        path.lineTo(s * 0.54, s * 0.64)
        path.lineTo(s * 0.64, s * 0.55)
        path.lineTo(s * 0.80, s * 0.72)
        p.drawPath(path)

    elif name == "download":
        p.drawLine(QPointF(s * 0.50, s * 0.16), QPointF(s * 0.50, s * 0.62))
        p.drawLine(QPointF(s * 0.31, s * 0.44), QPointF(s * 0.50, s * 0.63))
        p.drawLine(QPointF(s * 0.69, s * 0.44), QPointF(s * 0.50, s * 0.63))
        p.drawLine(QPointF(s * 0.22, s * 0.80), QPointF(s * 0.78, s * 0.80))

    elif name == "camera":
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.27, s * 0.76, s * 0.54), s * 0.11, s * 0.11)
        path = QPainterPath(QPointF(s * 0.31, s * 0.27))
        path.lineTo(s * 0.37, s * 0.17)
        path.lineTo(s * 0.63, s * 0.17)
        path.lineTo(s * 0.69, s * 0.27)
        p.drawPath(path)
        p.drawEllipse(QPointF(s * 0.50, s * 0.54), s * 0.15, s * 0.15)

    elif name == "expand":
        for x, y, dx, dy in (
            (0.18, 0.18, 0.16, 0.16),
            (0.82, 0.18, -0.16, 0.16),
            (0.18, 0.82, 0.16, -0.16),
            (0.82, 0.82, -0.16, -0.16),
        ):
            p.drawLine(QPointF(s * x, s * y), QPointF(s * (x + dx), s * y))
            p.drawLine(QPointF(s * x, s * y), QPointF(s * x, s * (y + dy)))

    elif name == "shrink":
        for x, y, dx, dy in (
            (0.34, 0.34, -0.16, -0.16),
            (0.66, 0.34, 0.16, -0.16),
            (0.34, 0.66, -0.16, 0.16),
            (0.66, 0.66, 0.16, 0.16),
        ):
            p.drawLine(QPointF(s * x, s * y), QPointF(s * (x + dx), s * y))
            p.drawLine(QPointF(s * x, s * y), QPointF(s * x, s * (y + dy)))

    elif name == "reset":
        rect = QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.60)
        p.drawArc(rect, 40 * 16, 285 * 16)
        p.drawLine(QPointF(s * 0.70, s * 0.13), QPointF(s * 0.79, s * 0.26))
        p.drawLine(QPointF(s * 0.79, s * 0.26), QPointF(s * 0.64, s * 0.28))

    elif name == "close":
        p.drawLine(QPointF(s * 0.26, s * 0.26), QPointF(s * 0.74, s * 0.74))
        p.drawLine(QPointF(s * 0.74, s * 0.26), QPointF(s * 0.26, s * 0.74))

    elif name == "check":
        path = QPainterPath(QPointF(s * 0.20, s * 0.53))
        path.lineTo(s * 0.42, s * 0.74)
        path.lineTo(s * 0.81, s * 0.27)
        p.drawPath(path)

    elif name == "trash":
        p.drawLine(QPointF(s * 0.22, s * 0.28), QPointF(s * 0.78, s * 0.28))
        p.drawLine(QPointF(s * 0.40, s * 0.28), QPointF(s * 0.43, s * 0.17))
        p.drawLine(QPointF(s * 0.60, s * 0.28), QPointF(s * 0.57, s * 0.17))
        p.drawLine(QPointF(s * 0.40, s * 0.17), QPointF(s * 0.60, s * 0.17))
        path = QPainterPath(QPointF(s * 0.29, s * 0.36))
        path.lineTo(s * 0.33, s * 0.82)
        path.lineTo(s * 0.67, s * 0.82)
        path.lineTo(s * 0.71, s * 0.36)
        p.drawPath(path)

    elif name == "doc":
        path = QPainterPath(QPointF(s * 0.27, s * 0.14))
        path.lineTo(s * 0.60, s * 0.14)
        path.lineTo(s * 0.75, s * 0.29)
        path.lineTo(s * 0.75, s * 0.86)
        path.lineTo(s * 0.27, s * 0.86)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.60, s * 0.14), QPointF(s * 0.60, s * 0.29))
        p.drawLine(QPointF(s * 0.60, s * 0.29), QPointF(s * 0.75, s * 0.29))
        p.drawLine(QPointF(s * 0.37, s * 0.51), QPointF(s * 0.65, s * 0.51))
        p.drawLine(QPointF(s * 0.37, s * 0.65), QPointF(s * 0.65, s * 0.65))

    elif name == "sparkles":
        def star(cx: float, cy: float, rr: float) -> None:
            path = QPainterPath(QPointF(cx, cy - rr))
            path.quadTo(cx + rr * 0.16, cy - rr * 0.16, cx + rr, cy)
            path.quadTo(cx + rr * 0.16, cy + rr * 0.16, cx, cy + rr)
            path.quadTo(cx - rr * 0.16, cy + rr * 0.16, cx - rr, cy)
            path.quadTo(cx - rr * 0.16, cy - rr * 0.16, cx, cy - rr)
            p.drawPath(path)

        star(s * 0.46, s * 0.50, s * 0.30)
        star(s * 0.77, s * 0.25, s * 0.13)

    elif name == "chevron-down":
        path = QPainterPath(QPointF(s * 0.26, s * 0.40))
        path.lineTo(s * 0.50, s * 0.63)
        path.lineTo(s * 0.74, s * 0.40)
        p.drawPath(path)

    elif name == "chevron-up":
        path = QPainterPath(QPointF(s * 0.26, s * 0.61))
        path.lineTo(s * 0.50, s * 0.38)
        path.lineTo(s * 0.74, s * 0.61)
        p.drawPath(path)

    elif name == "info":
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.35, s * 0.35)
        p.drawLine(QPointF(s * 0.50, s * 0.45), QPointF(s * 0.50, s * 0.70))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(s * 0.50, s * 0.33), s * 0.035, s * 0.035)

    elif name == "molecule":
        p.drawEllipse(QPointF(s * 0.50, s * 0.28), s * 0.115, s * 0.115)
        p.drawEllipse(QPointF(s * 0.29, s * 0.70), s * 0.105, s * 0.105)
        p.drawEllipse(QPointF(s * 0.72, s * 0.68), s * 0.105, s * 0.105)
        p.drawLine(QPointF(s * 0.46, s * 0.37), QPointF(s * 0.33, s * 0.61))
        p.drawLine(QPointF(s * 0.56, s * 0.37), QPointF(s * 0.68, s * 0.60))
        p.drawLine(QPointF(s * 0.39, s * 0.71), QPointF(s * 0.62, s * 0.69))

    elif name == "folder":
        path = QPainterPath(QPointF(s * 0.16, s * 0.30))
        path.lineTo(s * 0.40, s * 0.30)
        path.lineTo(s * 0.47, s * 0.39)
        path.lineTo(s * 0.84, s * 0.39)
        path.lineTo(s * 0.84, s * 0.78)
        path.lineTo(s * 0.16, s * 0.78)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "eye":
        path = QPainterPath(QPointF(s * 0.14, s * 0.50))
        path.cubicTo(s * 0.30, s * 0.24, s * 0.70, s * 0.24, s * 0.86, s * 0.50)
        path.cubicTo(s * 0.70, s * 0.76, s * 0.30, s * 0.76, s * 0.14, s * 0.50)
        p.drawPath(path)
        p.drawEllipse(QPointF(s * 0.50, s * 0.50), s * 0.125, s * 0.125)

    elif name == "alert":
        path = QPainterPath(QPointF(s * 0.50, s * 0.14))
        path.lineTo(s * 0.90, s * 0.82)
        path.lineTo(s * 0.10, s * 0.82)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.50, s * 0.38), QPointF(s * 0.50, s * 0.60))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(s * 0.50, s * 0.70), s * 0.033, s * 0.033)

    elif name == "atom":
        p.drawEllipse(QPointF(s * 0.50, s * 0.50), s * 0.08, s * 0.08)
        for angle in (0, 60, 120):
            p.save()
            p.translate(s * 0.50, s * 0.50)
            p.rotate(angle)
            p.drawEllipse(QRectF(-s * 0.34, -s * 0.15, s * 0.68, s * 0.30))
            p.restore()

    elif name == "copy":
        p.drawRoundedRect(QRectF(s * 0.30, s * 0.18, s * 0.50, s * 0.56), s * 0.09, s * 0.09)
        p.drawRoundedRect(QRectF(s * 0.18, s * 0.30, s * 0.50, s * 0.52), s * 0.09, s * 0.09)


def icon(name: str, color: str = Color.label, size: int = 18, width: float = 1.8) -> QIcon:
    return QIcon(_pixmap(name, color, size, width))


def app_icon() -> QIcon:
    """优先使用打包好的多尺寸 ICO；缺失时用 QPainter 生成蓝紫渐变图标。"""
    ico = Path(__file__).resolve().parent.parent / "assets" / "mk_mole.ico"
    if ico.exists():
        return QIcon(str(ico))

    pm = QPixmap(256, 256)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    from PySide6.QtGui import QLinearGradient

    g = QLinearGradient(0, 0, 256, 256)
    g.setColorAt(0, QColor("#4FACFE"))
    g.setColorAt(1, QColor("#5856D6"))
    p.setBrush(g)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)

    pen = QPen(QColor(255, 255, 255, 238), 11)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    nodes = [QPointF(128, 84), QPointF(78, 168), QPointF(180, 160)]
    for i in range(3):
        p.drawLine(nodes[i], nodes[(i + 1) % 3])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 245))
    for n, r in zip(nodes, (28, 24, 24)):
        p.drawEllipse(n, r, r)
    p.end()
    return QIcon(pm)
