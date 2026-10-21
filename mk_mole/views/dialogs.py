"""iOS 风格弹层：DeepSeek 设置、CAS 检索结果、结构下载。"""

from __future__ import annotations

import re
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QPropertyAnimation, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QImage,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    DEFAULT_BASE_URL,
    DEFAULT_REASONING_EFFORT,
    MODEL_CHOICES,
    REASONING_EFFORT_CHOICES,
    AppConfig,
)
from ..services.deepseek import DeepSeekError, test_connection
from ..services.poscar import StructureData
from ..services.pubchem import CompoundInfo
from ..theme import Color, app_font
from ..widgets.controls import (
    IconButton,
    IOSLineEdit,
    PillButton,
    SegmentedControl,
    Spinner,
    StatusPill,
    card,
    hline,
    make_label,
)
from ..widgets.icons import icon


class OverlayDialog(QDialog):
    """半透明遮罩 + 居中白色卡片的模态弹层。"""

    def __init__(self, parent: QWidget, *, width: int = 640):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._card_width = width
        self._fade: QPropertyAnimation | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 32)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.sheet = QFrame()
        self.sheet.setObjectName("SheetCard")
        self.sheet.setFixedWidth(width)
        shadow = QGraphicsDropShadowEffect(self.sheet)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(20, 20, 40, 70))
        self.sheet.setGraphicsEffect(shadow)
        row.addWidget(self.sheet)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self.body = QVBoxLayout(self.sheet)
        self.body.setContentsMargins(26, 22, 26, 22)
        self.body.setSpacing(14)

    def showEvent(self, event) -> None:  # noqa: N802
        parent = self.parentWidget()
        if parent:
            top_left = parent.mapToGlobal(QPoint(0, 0))
            self.setGeometry(top_left.x(), top_left.y(), parent.width(), parent.height())
        super().showEvent(event)
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 32, 80))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 24, 24)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            local = self.sheet.mapFrom(self, event.position().toPoint())
            if not self.sheet.rect().contains(local):
                self.reject()
                return
        super().mousePressEvent(event)

    def header(self, title: str, subtitle: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(3)
        column.addWidget(make_label(title, size=20, weight=app_font(20).weight()))
        if subtitle:
            sub = make_label(subtitle, color=Color.secondary)
            sub.setFont(app_font(12))
            sub.setWordWrap(True)
            column.addWidget(sub)
        row.addLayout(column, 1)
        close = IconButton("close", "关闭", color=Color.secondary, size=30)
        close.clicked.connect(self.reject)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        return row


class SettingsSheet(OverlayDialog):
    saved = Signal(object)
    test_finished = Signal(str, str)

    def __init__(self, config: AppConfig, parent: QWidget):
        super().__init__(parent, width=620)
        self._config = config
        self._test_thread: threading.Thread | None = None
        self._show_key = False
        self.test_finished.connect(self._on_test_finished)

        self.body.addLayout(self.header(
            "DeepSeek 设置",
            "构建分子的结构由 DeepSeek 生成。密钥只保存在本机，不会上传到其他服务。",
        ))
        self.body.addWidget(hline())

        # API Key
        key_label_row = QHBoxLayout()
        key_label_row.setSpacing(8)
        key_label_row.addWidget(make_label("API Key", object_name="FieldLabel"))
        key_label_row.addStretch(1)
        get_key = PillButton("获取 API Key", variant="ghost", height=26)
        get_key.setFont(app_font(11, app_font(11).weight()))
        get_key.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://platform.deepseek.com/api_keys")))
        key_label_row.addWidget(get_key)
        self.body.addLayout(key_label_row)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.key_edit = IOSLineEdit("sk-…")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setText(config.api_key)
        self.key_edit.setFont(app_font(13, app_font(13).weight(), mono=True))
        key_row.addWidget(self.key_edit, 1)
        self.eye_btn = IconButton("eye", "显示 / 隐藏", color=Color.secondary, size=38)
        self.eye_btn.clicked.connect(self._toggle_key)
        key_row.addWidget(self.eye_btn)
        self.body.addLayout(key_row)

        # Base URL
        self.body.addWidget(make_label("API 地址", object_name="FieldLabel"))
        self.base_edit = IOSLineEdit(DEFAULT_BASE_URL)
        self.base_edit.setText(config.base_url or DEFAULT_BASE_URL)
        self.base_edit.setFont(app_font(12.5, app_font(12.5).weight(), mono=True))
        self.body.addWidget(self.base_edit)

        # 模型与思考强度
        model_row = QHBoxLayout()
        model_row.setSpacing(14)
        model_col = QVBoxLayout()
        model_col.setSpacing(6)
        model_col.addWidget(make_label("模型", object_name="FieldLabel"))
        self.model_seg = SegmentedControl(list(MODEL_CHOICES), min_segment=132)
        try:
            self.model_seg.set_current_index(MODEL_CHOICES.index(config.model), animate=False)
        except ValueError:
            self.model_seg.set_current_index(0, animate=False)
        model_col.addWidget(self.model_seg)
        model_row.addLayout(model_col)

        effort_col = QVBoxLayout()
        effort_col.setSpacing(6)
        effort_col.addWidget(make_label("思考强度", object_name="FieldLabel"))
        self.effort_seg = SegmentedControl(list(REASONING_EFFORT_CHOICES), min_segment=54)
        try:
            self.effort_seg.set_current_index(
                REASONING_EFFORT_CHOICES.index(config.reasoning_effort), animate=False)
        except ValueError:
            self.effort_seg.set_current_index(
                REASONING_EFFORT_CHOICES.index(DEFAULT_REASONING_EFFORT), animate=False)
        effort_col.addWidget(self.effort_seg)
        model_row.addLayout(effort_col)
        model_row.addStretch(1)
        self.body.addLayout(model_row)
        self.model_hint = make_label(
            "deepseek-flash 更快（默认）；deepseek-v4-pro 更强但更慢。"
            "思考强度 high 为默认，none 关闭思考。",
            color=Color.tertiary,
        )
        self.model_hint.setFont(app_font(11))
        self.model_hint.setWordWrap(True)
        self.body.addWidget(self.model_hint)

        # 测试连接
        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self.test_btn = PillButton("测试连接", variant="secondary", icon_name="check",
                                   icon_color=Color.blue, height=34)
        self.test_btn.clicked.connect(self._run_test)
        test_row.addWidget(self.test_btn)
        self.test_spinner = Spinner(15, Color.blue, self)
        test_row.addWidget(self.test_spinner)
        self.test_label = make_label("", color=Color.secondary)
        self.test_label.setFont(app_font(11.5))
        self.test_label.setWordWrap(True)
        test_row.addWidget(self.test_label, 1)
        self.body.addLayout(test_row)

        note = card(inset=True)
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(14, 11, 14, 11)
        note_layout.setSpacing(3)
        note_text = make_label("配置保存位置", size=11, weight=app_font(11).weight(),
                               color=Color.secondary)
        path_text = make_label(str(Path.home() / ".mk_mole"), object_name="Tiny")
        from ..config import config_path

        path_text.setText(str(config_path()))
        path_text.setFont(app_font(10.5, app_font(10.5).weight(), mono=True))
        path_text.setWordWrap(True)
        path_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        note_layout.addWidget(note_text)
        note_layout.addWidget(path_text)
        self.body.addWidget(note)

        footer = self.footer()
        cancel = PillButton("取消", variant="ghost")
        cancel.clicked.connect(self.reject)
        save = PillButton("保存", variant="primary", icon_name="check",
                          icon_color="#FFFFFF")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        self.body.addLayout(footer)

    def _toggle_key(self) -> None:
        self._show_key = not self._show_key
        self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if self._show_key else QLineEdit.EchoMode.Password
        )
        self.eye_btn.setIcon(icon("eye", Color.blue if self._show_key else Color.secondary, 18))

    def _current_model(self) -> str:
        index = max(0, min(self.model_seg.current_index(), len(MODEL_CHOICES) - 1))
        return MODEL_CHOICES[index]

    def _current_effort(self) -> str:
        index = max(0, min(self.effort_seg.current_index(), len(REASONING_EFFORT_CHOICES) - 1))
        return REASONING_EFFORT_CHOICES[index]

    def _snapshot(self) -> AppConfig:
        base = self.base_edit.text().strip() or DEFAULT_BASE_URL
        if not base.startswith(("http://", "https://")):
            base = "https://" + base
        return replace(
            self._config,
            api_key=self.key_edit.text().strip(),
            base_url=base,
            model=self._current_model(),
            reasoning_effort=self._current_effort(),
        )

    def _save(self) -> None:
        cfg = self._snapshot()
        if not cfg.api_key:
            self._set_test("请填写 API Key。", "error")
            return
        try:
            cfg.save()
        except OSError as exc:
            self._set_test(f"保存失败：{exc}", "error")
            return
        self._config = cfg
        self.saved.emit(cfg)
        self.accept()

    def _set_test(self, text: str, kind: str = "info") -> None:
        color = {"success": Color.green, "error": Color.red,
                 "info": Color.secondary, "warning": Color.orange}.get(kind, Color.secondary)
        self.test_label.setStyleSheet(f"color: {color};")
        self.test_label.setText(text)

    def _on_test_finished(self, text: str, kind: str) -> None:
        self.test_spinner.stop()
        self.test_btn.setEnabled(True)
        self._set_test(text, kind)

    def _run_test(self) -> None:
        cfg = self._snapshot()
        if not cfg.api_key:
            self._set_test("请先填写 API Key。", "error")
            return
        if self._test_thread and self._test_thread.is_alive():
            return
        self.test_btn.setEnabled(False)
        self.test_spinner.start()
        self._set_test("正在连接 DeepSeek…", "info")

        def work() -> None:
            try:
                models = test_connection(cfg)
                if models and cfg.model not in models:
                    payload = (f"连接成功，但模型列表中未发现 {cfg.model}", "warning")
                else:
                    payload = (f"连接成功 · {len(models)} 个可用模型" if models else "连接成功", "success")
            except DeepSeekError as exc:
                payload = (str(exc), "error")
            except Exception as exc:  # noqa: BLE001
                payload = (f"连接失败：{exc}", "error")
            try:
                self.test_finished.emit(*payload)
            except RuntimeError:
                pass

        self._test_thread = threading.Thread(target=work, daemon=True)
        self._test_thread.start()


def _crop_whitespace(pixmap: QPixmap, margin: int = 10) -> QPixmap:
    """裁掉 PubChem 二维图四周的浅灰/白色留白，让结构在预览框里更大。"""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    if width <= 0 or height <= 0:
        return pixmap
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            color = image.pixelColor(x, y)
            if color.alpha() > 12 and not (color.red() > 238 and color.green() > 238 and color.blue() > 238):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return pixmap
    rect = QRect(
        max(0, min_x - margin), max(0, min_y - margin),
        min(width, max_x - min_x + margin * 2),
        min(height, max_y - min_y + margin * 2),
    )
    cropped = image.copy(rect)
    # PubChem 的背景是 #F5F5F5，统一改成白色以融入白色预览卡片
    for y in range(cropped.height()):
        for x in range(cropped.width()):
            color = cropped.pixelColor(x, y)
            if color.red() > 238 and color.green() > 238 and color.blue() > 238:
                cropped.setPixelColor(x, y, QColor(255, 255, 255, color.alpha()))
    return QPixmap.fromImage(cropped)


class CASSheet(OverlayDialog):
    def __init__(self, compound: CompoundInfo, parent: QWidget):
        super().__init__(parent, width=660)
        self.compound = compound
        self.body.addLayout(self.header(
            "CAS 检索结果",
            "核对结构信息后确认，DeepSeek 将把它作为建模参考。",
        ))
        self.body.addWidget(hline())

        content = QHBoxLayout()
        content.setSpacing(18)

        image_frame = QFrame()
        image_frame.setObjectName("CASImage")
        image_frame.setFixedSize(218, 218)
        image_frame.setStyleSheet(
            "QFrame#CASImage { background: white; border: 1px solid rgba(60,60,67,10%);"
            " border-radius: 14px; }"
        )
        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(8, 8, 8, 8)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap()
        if compound.png and pixmap.loadFromData(compound.png):
            pixmap = _crop_whitespace(pixmap)
            image.setPixmap(pixmap.scaled(
                196, 196,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            image.setText("无二维结构图")
            image.setStyleSheet(f"color: {Color.tertiary};")
        image_layout.addWidget(image)
        content.addWidget(image_frame, 0, Qt.AlignmentFlag.AlignTop)

        meta = QVBoxLayout()
        meta.setSpacing(7)
        title = make_label(compound.display_name, size=17, weight=app_font(17).weight())
        title.setWordWrap(True)
        meta.addWidget(title)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(StatusPill(f"CAS {compound.cas}", "running"))
        if compound.cid:
            chips.addWidget(StatusPill(f"CID {compound.cid}", "idle"))
        chips.addStretch(1)
        meta.addLayout(chips)

        def row(label: str, value: str) -> None:
            line = QHBoxLayout()
            key = make_label(label, color=Color.secondary)
            key.setFont(app_font(11.5))
            key.setFixedWidth(62)
            val = make_label(value, size=12.5, weight=app_font(12.5).weight())
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            line.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(val, 1)
            meta.addLayout(line)

        if compound.formula:
            row("分子式", compound.formula)
        if compound.molecular_weight:
            row("分子量", f"{compound.molecular_weight:.2f}")
        if compound.atom_count:
            row("原子数", str(compound.atom_count))
        if compound.iupac_name and compound.iupac_name != compound.title:
            row("IUPAC", compound.iupac_name)

        if compound.smiles:
            meta.addWidget(make_label("SMILES", object_name="FieldLabel"))
            smiles = QLineEdit(compound.smiles)
            smiles.setReadOnly(True)
            smiles.setFont(app_font(11.5, app_font(11.5).weight(), mono=True))
            smiles.setCursorPosition(0)
            meta.addWidget(smiles)

        if compound.synonyms:
            alias_text = " · ".join(compound.synonyms[:8])
            alias = make_label(alias_text, color=Color.tertiary)
            alias.setFont(app_font(11))
            alias.setWordWrap(True)
            meta.addWidget(alias)
        meta.addStretch(1)
        content.addLayout(meta, 1)
        self.body.addLayout(content)

        footer = self.footer()
        cancel = PillButton("取消", variant="ghost")
        cancel.clicked.connect(self.reject)
        use = PillButton("使用该结构", variant="primary", icon_name="check",
                         icon_color="#FFFFFF")
        use.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(use)
        self.body.addLayout(footer)


class DownloadSheet(OverlayDialog):
    FORMATS = [
        ("POSCAR", "poscar"),
        ("CIF", "cif"),
        ("SDF", "sdf"),
        ("XYZ", "xyz"),
        ("PDB", "pdb"),
    ]

    def __init__(self, structure: StructureData, parent: QWidget):
        super().__init__(parent, width=600)
        self.structure = structure
        self.body.addLayout(self.header(
            "下载结构",
            "选择导出格式，保存到本机。POSCAR 保留 DeepSeek 生成的原始晶胞。",
        ))
        self.body.addWidget(hline())

        name_row = QHBoxLayout()
        name_col = QVBoxLayout()
        name_col.setSpacing(6)
        name_col.addWidget(make_label("文件名", object_name="FieldLabel"))
        self.name_edit = IOSLineEdit("structure")
        default_name = re.sub(r"[^A-Za-z0-9_.-]+", "", structure.formula) or "structure"
        self.name_edit.setText(default_name)
        name_col.addWidget(self.name_edit)
        name_row.addLayout(name_col, 1)
        self.body.addLayout(name_row)

        fmt_col = QVBoxLayout()
        fmt_col.setSpacing(6)
        fmt_col.addWidget(make_label("格式", object_name="FieldLabel"))
        self.seg = SegmentedControl([label for label, _ in self.FORMATS], min_segment=62)
        fmt_col.addWidget(self.seg)
        self.body.addLayout(fmt_col)

        info = make_label(
            "POSCAR / CIF 适合继续做 DFT 计算；SDF / XYZ / PDB 适合在分子软件中查看。",
            color=Color.tertiary,
        )
        info.setFont(app_font(11))
        info.setWordWrap(True)
        self.body.addWidget(info)

        footer = self.footer()
        cancel = PillButton("取消", variant="ghost")
        cancel.clicked.connect(self.reject)
        save = PillButton("保存…", variant="primary", icon_name="download",
                          icon_color="#FFFFFF")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        self.body.addLayout(footer)

    def _save(self) -> None:
        index = self.seg.current_index()
        label, fmt = self.FORMATS[max(0, min(index, len(self.FORMATS) - 1))]
        name = self.name_edit.text().strip() or "structure"
        if name.endswith("." + fmt):
            name = name[:-len(fmt) - 1]
        filters = f"{label} (*.{fmt});;所有文件 (*.*)"
        path, _ = QFileDialog.getSaveFileName(self, "保存结构", f"{name}.{fmt}", filters)
        if not path:
            return
        try:
            self.structure.save(path, fmt)
        except Exception as exc:  # noqa: BLE001
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.accept()
        parent = self.parentWidget()
        if parent and hasattr(parent, "window"):
            window = parent.window()
            if hasattr(window, "show_toast"):
                window.show_toast(f"已保存到 {path}", "success")
