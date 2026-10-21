"""MK-MOLE 视觉主题：iOS 风格配色、字体与全局样式表。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette


class Color:
    # 背景 / 卡片
    background = "#F2F2F7"
    background_top = "#F7F7FB"
    card = "#FFFFFF"
    card_alt = "#FBFBFD"

    # 文本
    label = "#1C1C1E"
    secondary = "#6E6E73"
    tertiary = "#A1A1A6"
    placeholder = "#C7C7CC"

    # iOS 系统色
    blue = "#007AFF"
    blue_dark = "#0066D6"
    blue_light = "#5AC8FA"
    indigo = "#5856D6"
    green = "#34C759"
    orange = "#FF9500"
    red = "#FF3B30"
    pink = "#FF375F"
    purple = "#AF52DE"
    teal = "#30B0C7"
    gray_fill = "#F2F2F7"
    separator = "rgba(60, 60, 67, 0.10)"

    # 交通灯
    traffic_close = "#FF6B60"
    traffic_min = "#FFCC00"
    traffic_max = "#34C759"


FONT_FAMILIES = [
    "SF Pro Display",
    "Segoe UI Variable Display",
    "Segoe UI",
    "Microsoft YaHei UI",
    "PingFang SC",
    "Noto Sans CJK SC",
]

MONO_FAMILIES = ["SF Mono", "Cascadia Mono", "Consolas", "Microsoft YaHei UI"]


def app_font(size: int = 13, weight: QFont.Weight = QFont.Weight.Normal,
             *, mono: bool = False, spacing: float | None = None) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES if mono else FONT_FAMILIES)
    f.setPixelSize(size)
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if spacing is not None:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def apply_palette(app) -> None:
    """让原生控件（滚动条、输入框选中态等）也使用浅色主题。"""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(Color.background))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(Color.label))
    pal.setColor(QPalette.ColorRole.Base, QColor(Color.card))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(Color.card_alt))
    pal.setColor(QPalette.ColorRole.Text, QColor(Color.label))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(Color.label))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(Color.blue))
    pal.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(Color.placeholder))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(Color.card))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(Color.label))
    app.setPalette(pal)


GLOBAL_QSS = f"""
* {{
    outline: none;
}}
QWidget {{
    color: {Color.label};
    font-family: "SF Pro Display", "Segoe UI Variable Display", "Segoe UI",
                 "Microsoft YaHei UI", "PingFang SC";
    font-size: 13px;
}}
QLabel, QCheckBox {{
    background: transparent;
}}
QToolTip {{
    background: rgba(28, 28, 30, 92%);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ---------- 窗口与卡片 ---------- */
QFrame#Root {{
    background: {Color.background};
    border: 1px solid rgba(60, 60, 67, 9%);
    border-radius: 24px;
}}
QFrame#Root[fullscreen="true"] {{
    border-radius: 0px;
    border: none;
}}
QFrame#Card {{
    background: {Color.card};
    border: 1px solid rgba(60, 60, 67, 8%);
    border-radius: 18px;
}}
QFrame#InsetCard {{
    background: {Color.card_alt};
    border: 1px solid rgba(60, 60, 67, 7%);
    border-radius: 14px;
}}
QFrame#SheetCard {{
    background: {Color.card};
    border: 1px solid rgba(60, 60, 67, 10%);
    border-radius: 22px;
}}
QFrame#Hairline {{
    background: rgba(60, 60, 67, 9%);
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ---------- 文本 ---------- */
QLabel#LargeTitle {{
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -0.6px;
}}
QLabel#PageTitle {{
    font-size: 21px;
    font-weight: 700;
    letter-spacing: -0.3px;
}}
QLabel#CardTitle {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel#FieldLabel {{
    font-size: 12px;
    font-weight: 500;
    color: {Color.secondary};
}}
QLabel#Subtle {{
    font-size: 12px;
    color: {Color.secondary};
}}
QLabel#Tiny {{
    font-size: 11px;
    color: {Color.tertiary};
}}
QLabel#Mono {{
    font-family: "SF Mono", "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 11px;
    color: {Color.secondary};
}}
QLabel#Required {{
    color: {Color.blue};
    font-size: 11px;
    font-weight: 600;
}}

/* ---------- 输入框 ---------- */
QLineEdit {{
    background: {Color.gray_fill};
    border: 1.5px solid transparent;
    border-radius: 11px;
    padding: 0 12px;
    min-height: 38px;
    font-size: 13.5px;
    color: {Color.label};
    selection-background-color: {Color.blue};
    selection-color: white;
}}
QLineEdit:hover {{
    background: #EDEDF3;
}}
QLineEdit:focus {{
    background: {Color.card};
    border: 1.5px solid {Color.blue};
}}
QLineEdit:disabled {{
    color: {Color.tertiary};
    background: #F7F7FA;
}}
QLineEdit[error="true"] {{
    background: {Color.card};
    border: 1.5px solid {Color.red};
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    border: none;
    border-radius: 11px;
    padding: 0 16px;
    min-height: 38px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton[variant="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2B95FF, stop:0.55 {Color.blue}, stop:1 #0069E0);
    color: white;
}}
QPushButton[variant="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #48A5FF, stop:0.6 #1684FF, stop:1 #0072EC);
}}
QPushButton[variant="primary"]:pressed {{
    background: #0062CC;
}}
QPushButton[variant="tinted"] {{
    background: rgba(0, 122, 255, 9%);
    color: {Color.blue};
}}
QPushButton[variant="tinted"]:hover {{
    background: rgba(0, 122, 255, 15%);
}}
QPushButton[variant="tinted"]:pressed {{
    background: rgba(0, 122, 255, 22%);
}}
QPushButton[variant="secondary"] {{
    background: rgba(120, 120, 128, 10%);
    color: {Color.label};
}}
QPushButton[variant="secondary"]:hover {{
    background: rgba(120, 120, 128, 16%);
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    color: {Color.blue};
}}
QPushButton[variant="ghost"]:hover {{
    background: rgba(0, 122, 255, 9%);
}}
QPushButton[variant="destructive"] {{
    background: rgba(255, 59, 48, 9%);
    color: {Color.red};
}}
QPushButton[variant="destructive"]:hover {{
    background: rgba(255, 59, 48, 15%);
}}
QPushButton[variant="icon"] {{
    background: transparent;
    border-radius: 10px;
    padding: 0;
}}
QPushButton[variant="icon"]:hover {{
    background: rgba(120, 120, 128, 12%);
}}
QPushButton[variant="icon"]:pressed {{
    background: rgba(120, 120, 128, 20%);
}}
QPushButton:disabled {{
    color: rgba(60, 60, 67, 28%);
    background: rgba(120, 120, 128, 7%);
}}
QPushButton[variant="primary"]:disabled {{
    color: rgba(255, 255, 255, 80%);
    background: #9CCBFF;
}}

/* ---------- 滚动区 ---------- */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QWidget#ScrollBody {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 6px 1px;
}}
QScrollBar::handle:vertical {{
    background: rgba(60, 60, 67, 16%);
    border-radius: 4px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(60, 60, 67, 28%);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0px;
    border: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 0px;
}}

/* ---------- 只读日志 ---------- */
QPlainTextEdit#LogView {{
    background: {Color.gray_fill};
    border: none;
    border-radius: 11px;
    padding: 10px;
    color: {Color.secondary};
    font-family: "SF Mono", "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 11px;
    selection-background-color: {Color.blue};
}}

/* ---------- 菜单 ---------- */
QMenu {{
    background: {Color.card};
    border: 1px solid rgba(60, 60, 67, 12%);
    border-radius: 12px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 18px 8px 14px;
    border-radius: 8px;
    font-size: 13px;
}}
QMenu::item:selected {{
    background: rgba(0, 122, 255, 10%);
    color: {Color.blue};
}}
"""
