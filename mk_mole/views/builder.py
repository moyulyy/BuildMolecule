"""构建分子主页面：DeepSeek 生成 POSCAR + 本地 3D 预览。"""

from __future__ import annotations

import base64
import re
import threading
from pathlib import Path

from PySide6.QtCore import QByteArray, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap, QShortcut, QKeySequence, QTextCursor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT, AppConfig
from ..elements import element_color
from ..services.chgnet import ChgnetEnvironment, ChgnetProbeWorker, ChgnetRelaxWorker
from ..services.deepseek import (
    DeepSeekError,
    GenerationCancelled,
    GenerationResult,
    generate_poscar,
)
from ..services.image_input import ImageInputError, load_structure_image
from ..services.molfile import molfile_summary
from ..services.poscar import StructureData, normalize_formula, parse_formula
from ..services.pubchem import CompoundInfo, PubChemError, lookup_cas
from ..theme import Color, app_font
from ..widgets.controls import (
    ElementDot,
    EmptyMoleculeArt,
    IconButton,
    IOSLineEdit,
    PillButton,
    ProgressTrack,
    SegmentedControl,
    Spinner,
    StatusPill,
    Switch,
    card,
    hline,
    make_label,
)
from ..widgets.icons import icon
from ..widgets.viewer import MoleculeViewer
from .dialogs import CASSheet, DownloadSheet, SettingsSheet
from .structure_editor import StructureEditorDialog

VIEWS = [
    ("前视", (0.0, 0.0, 0.0, 1.0)),
    ("后视", (0.0, 1.0, 0.0, 0.0)),
    ("左视", (0.0, 0.70710678, 0.0, 0.70710678)),
    ("右视", (0.0, -0.70710678, 0.0, 0.70710678)),
    ("俯视", (0.70710678, 0.0, 0.0, 0.70710678)),
    ("仰视", (-0.70710678, 0.0, 0.0, 0.70710678)),
]


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _svg_pixmap(svg: str, size: int = 52) -> QPixmap | None:
    """把 Ketcher 返回的 SVG 渲染成带白底的高分屏缩略图。"""
    if not svg.strip():
        return None
    try:
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            return None
        image = QImage(size * 2, size * 2, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(2.0)
        return pixmap
    except Exception:  # noqa: BLE001
        return None


class CasWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, cas: str):
        super().__init__()
        self.cas = cas

    def run(self) -> None:  # noqa: D401
        try:
            self.done.emit(lookup_cas(self.cas))
        except PubChemError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"CAS 检索失败：{exc}")


class GenerateWorker(QThread):
    progress = Signal(int, str)
    event = Signal(str, str)
    succeeded = Signal(object, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, config: AppConfig, payload: dict):
        super().__init__()
        self.config = config
        self.payload = payload
        self._cancel = threading.Event()
        self._chars = 0
        self._next_threshold = 1500

    def cancel(self) -> None:
        self._cancel.set()

    def _on_event(self, kind: str, text: str) -> None:
        if self._cancel.is_set():
            return
        self.event.emit(kind, text)
        if kind in ("thinking", "content"):
            self._chars += len(text)
            if self._chars >= self._next_threshold:
                self._next_threshold = self._chars + 1500
                percent = min(82, 28 + self._chars // 400)
                message = "DeepSeek 正在推理…" if kind == "thinking" else "正在生成 POSCAR…"
                self.progress.emit(percent, message)

    def run(self) -> None:  # noqa: D401
        try:
            effort = self.config.reasoning_effort or DEFAULT_REASONING_EFFORT
            self.progress.emit(8, f"正在连接 DeepSeek（{self.config.model} · {effort}）…")
            result = generate_poscar(
                self.config,
                self.payload,
                on_event=self._on_event,
                is_cancelled=self._cancel.is_set,
            )
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            self.progress.emit(90, "正在解析 POSCAR…")
            structure = StructureData.from_poscar(
                result.poscar,
                source=f"DeepSeek · {result.model} · {effort}",
                expected_formula=self.payload.get("formula", ""),
            )
            self.progress.emit(97, "正在准备 3D 渲染…")
            self.succeeded.emit(result, structure)
        except GenerationCancelled:
            self.cancelled.emit()
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"生成失败：{exc}")


class BuilderPage(QWidget):
    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self._cas_worker: CasWorker | None = None
        self._gen_worker: GenerateWorker | None = None
        self._compound: CompoundInfo | None = None
        self._molfile: str = ""
        self._molfile_name: str = ""
        self._image_b64: str = ""
        self._image_name: str = ""
        self._structure_source: str = ""
        self._structure: StructureData | None = None
        self._initial_structure: StructureData | None = None
        self._result: GenerationResult | None = None
        self._chgnet_env: ChgnetEnvironment | None = None
        self._chgnet_probe: ChgnetProbeWorker | None = None
        self._chgnet_probe_started = False
        self._relax_worker: ChgnetRelaxWorker | None = None
        self._relax_log_count = 0
        self._log_kind = ""
        self._render_token = 0
        self._immersive_connected = False
        self._current_view = 0

        self._build_ui()
        self._restore_form()
        self._apply_config_state()

    # ================================================================== UI
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar, 0)

        self.right = self._build_right()
        root.addWidget(self.right, 1)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(404)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)

        # 大标题固定在顶部，表单与进度在下方滚动，避免滚动时标题被裁切
        header_host = QWidget()
        header_layout = QVBoxLayout(header_host)
        header_layout.setContentsMargins(4, 2, 7, 0)
        header_layout.setSpacing(2)
        title = make_label("构建分子", "LargeTitle")
        subtitle = make_label("DeepSeek × 3D 结构预览 · 本地桌面版", color=Color.secondary)
        subtitle.setFont(app_font(12))
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header_host, 0)

        content = QWidget()
        content.setObjectName("ScrollBody")
        self.scroll_layout = QVBoxLayout(content)
        self.scroll_layout.setContentsMargins(2, 6, 7, 4)
        self.scroll_layout.setSpacing(12)

        # 未配置 DeepSeek 的提示卡片
        self.callout = QFrame()
        self.callout.setObjectName("Callout")
        self.callout.setStyleSheet(
            "QFrame#Callout { background: rgba(0, 122, 255, 8%);"
            " border: 1px solid rgba(0, 122, 255, 18%); border-radius: 14px; }"
        )
        callout_layout = QHBoxLayout(self.callout)
        callout_layout.setContentsMargins(13, 11, 11, 11)
        callout_layout.setSpacing(10)
        callout_icon = QLabel()
        callout_icon.setFixedSize(30, 30)
        callout_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        callout_icon.setStyleSheet(
            "background: rgba(0, 122, 255, 14%); border-radius: 15px;"
        )
        callout_icon.setPixmap(icon("atom", Color.blue, 18, 1.7).pixmap(18, 18))
        callout_layout.addWidget(callout_icon)
        callout_text = QVBoxLayout()
        callout_text.setSpacing(1)
        callout_title = make_label("尚未连接 DeepSeek", size=12.5, weight=app_font(12.5).weight())
        callout_sub = make_label("填写 API Key 后即可开始生成", color=Color.secondary)
        callout_sub.setFont(app_font(11))
        callout_text.addWidget(callout_title)
        callout_text.addWidget(callout_sub)
        callout_layout.addLayout(callout_text, 1)
        callout_btn = PillButton("配置", variant="tinted", height=30)
        callout_btn.setFont(app_font(11.5, app_font(11.5).weight()))
        callout_btn.clicked.connect(self.open_settings)
        callout_layout.addWidget(callout_btn)
        self.scroll_layout.addWidget(self.callout)

        self.form_card = self._build_form_card()
        self.scroll_layout.addWidget(self.form_card)

        self.confirmed_card = self._build_confirmed_card()
        self.scroll_layout.addWidget(self.confirmed_card)

        self.progress_card = self._build_progress_card()
        self.scroll_layout.addWidget(self.progress_card)
        self.scroll_layout.addStretch(1)

        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)

        bottom = QWidget()
        bottom_v = QVBoxLayout(bottom)
        bottom_v.setContentsMargins(4, 2, 7, 2)
        bottom_v.setSpacing(7)

        options = QHBoxLayout()
        options.setSpacing(8)
        self.relax_switch = Switch(self.config.auto_relax)
        self.relax_switch.toggled.connect(self._on_relax_toggled)
        options.addWidget(self.relax_switch)
        relax_label = make_label(
            "生成后 CHGNet 弛豫", size=12, weight=app_font(12).weight())
        options.addWidget(relax_label)
        options.addStretch(1)
        self.chgnet_status = make_label("检测中…", color=Color.tertiary)
        self.chgnet_status.setFont(app_font(10.5))
        options.addWidget(self.chgnet_status)
        self.chgnet_retry = PillButton("检测", variant="tinted", height=28)
        self.chgnet_retry.setFont(app_font(10.5, app_font(10.5).weight()))
        self.chgnet_retry.setFixedSize(60, 28)
        self.chgnet_retry.clicked.connect(lambda: self._start_chgnet_probe(force=True))
        self.chgnet_retry.hide()
        options.addWidget(self.chgnet_retry)
        bottom_v.addLayout(options)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        self.generate_btn = PillButton(
            "开始生成结构", variant="primary", icon_name="sparkles",
            icon_color="#FFFFFF", height=46,
        )
        self.generate_btn.setFont(app_font(14, app_font(14).weight()))
        self.generate_btn.clicked.connect(self._start_or_cancel)
        buttons.addWidget(self.generate_btn, 1)
        self.clear_btn = IconButton("trash", "清空并新建", color=Color.secondary, size=46)
        self.clear_btn.clicked.connect(self.reset_all)
        buttons.addWidget(self.clear_btn)
        bottom_v.addLayout(buttons)
        layout.addWidget(bottom)
        return sidebar

    def _build_form_card(self) -> QFrame:
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(make_label("分子信息", "CardTitle"))
        header.addStretch(1)
        self.model_badge = QLabel(f"{DEFAULT_MODEL} · {DEFAULT_REASONING_EFFORT}")
        self.model_badge.setFont(app_font(10.5, app_font(10.5).weight()))
        self.model_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.model_badge.setStyleSheet(
            f"background: rgba(0,122,255,9%); color: {Color.blue};"
            " border-radius: 9px; padding: 3px 8px;"
        )
        header.addWidget(self.model_badge)
        layout.addLayout(header)

        self.formula_edit = IOSLineEdit("如 CO₂、C₆H₆、CH₃OH")
        self.formula_edit.textChanged.connect(self._on_formula_changed)
        layout.addWidget(self._field("分子式", self.formula_edit, required=True))

        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        self.name_edit = IOSLineEdit("如 苯")
        self.english_edit = IOSLineEdit("如 Benzene")
        name_row.addWidget(self._field("中文名称", self.name_edit), 1)
        name_row.addWidget(self._field("英文名称", self.english_edit), 1)
        layout.addLayout(name_row)

        cas_host = QWidget()
        cas_layout = QVBoxLayout(cas_host)
        cas_layout.setContentsMargins(0, 0, 0, 0)
        cas_layout.setSpacing(5)
        cas_label_row = QHBoxLayout()
        cas_label_row.setSpacing(5)
        cas_label_row.addWidget(make_label("CAS 号", "FieldLabel"))
        cas_label_row.addStretch(1)
        cas_layout.addLayout(cas_label_row)
        cas_row = QHBoxLayout()
        cas_row.setSpacing(8)
        self.cas_edit = IOSLineEdit("如 71-43-2")
        cas_row.addWidget(self.cas_edit, 1)
        self.cas_btn = PillButton("检索", variant="tinted", icon_name="search",
                                  icon_color=Color.blue, height=38)
        self.cas_btn.setFixedWidth(82)
        self.cas_btn.clicked.connect(self._lookup_cas)
        cas_row.addWidget(self.cas_btn)
        cas_layout.addLayout(cas_row)
        layout.addWidget(cas_host)

        self.smiles_edit = IOSLineEdit("可选，如 C1=CC=CC=C1")
        self.smiles_edit.setFont(app_font(12, app_font(12).weight(), mono=True))
        smiles_host = QWidget()
        smiles_layout = QVBoxLayout(smiles_host)
        smiles_layout.setContentsMargins(0, 0, 0, 0)
        smiles_layout.setSpacing(5)
        smiles_top = QHBoxLayout()
        smiles_top.setSpacing(6)
        smiles_top.addWidget(make_label("SMILES", "FieldLabel"))
        smiles_top.addStretch(1)
        self.edit_structure_btn = PillButton(
            "结构编辑", variant="tinted", icon_name="molecule",
            icon_color=Color.blue, height=30,
        )
        self.edit_structure_btn.setFont(app_font(11, app_font(11).weight()))
        self.edit_structure_btn.clicked.connect(self._open_structure_editor)
        smiles_top.addWidget(self.edit_structure_btn)
        smiles_layout.addLayout(smiles_top)
        smiles_layout.addWidget(self.smiles_edit)
        layout.addWidget(smiles_host)
        smiles_hint = make_label(
            "可直接输入 SMILES，或用「结构编辑」在 Ketcher 中绘制。",
            color=Color.tertiary,
        )
        smiles_hint.setFont(app_font(10.5))
        layout.addWidget(smiles_hint)

        self.description_edit = IOSLineEdit("可选，如 顺式构型、带 +1 电荷")
        layout.addWidget(self._field("补充说明", self.description_edit))

        layout.addWidget(hline())

        ref_header = QHBoxLayout()
        ref_header.setSpacing(7)
        ref_header.addWidget(make_label("结构参考", "FieldLabel"))
        ref_hint = make_label("SDF / MOL / XYZ / PDB", color=Color.tertiary)
        ref_hint.setFont(app_font(10.5))
        ref_header.addWidget(ref_hint)
        ref_header.addStretch(1)
        layout.addLayout(ref_header)

        ref_row = QHBoxLayout()
        ref_row.setSpacing(8)
        self.import_btn = PillButton(
            "导入结构文件", variant="tinted", icon_name="doc",
            icon_color=Color.blue, height=32,
        )
        self.import_btn.setFont(app_font(11.5, app_font(11.5).weight()))
        self.import_btn.clicked.connect(self._import_structure)
        ref_row.addWidget(self.import_btn)
        self.image_btn = PillButton(
            "选择结构图片", variant="tinted", icon_name="image",
            icon_color=Color.blue, height=32,
        )
        self.image_btn.setFont(app_font(11.5, app_font(11.5).weight()))
        self.image_btn.clicked.connect(self._pick_image)
        ref_row.addWidget(self.image_btn)
        ref_row.addStretch(1)
        layout.addLayout(ref_row)

        self.chips_host = QWidget()
        chips_layout = QHBoxLayout(self.chips_host)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(8)

        self.file_chip = QFrame()
        self.file_chip.setObjectName("InsetCard")
        chip_layout = QHBoxLayout(self.file_chip)
        chip_layout.setContentsMargins(8, 3, 4, 3)
        chip_layout.setSpacing(5)
        chip_icon = QLabel()
        chip_icon.setPixmap(icon("doc", Color.secondary, 13, 1.6).pixmap(13, 13))
        chip_layout.addWidget(chip_icon)
        self.file_chip_label = make_label("", color=Color.secondary)
        self.file_chip_label.setFont(app_font(10.5))
        self.file_chip_label.setMaximumWidth(110)
        chip_layout.addWidget(self.file_chip_label)
        chip_clear = IconButton("close", "移除结构文件", color=Color.tertiary, size=20)
        chip_clear.setIcon(icon("close", Color.tertiary, 11, 1.6))
        chip_clear.clicked.connect(self._clear_structure_file)
        chip_layout.addWidget(chip_clear)
        self.file_chip.hide()
        chips_layout.addWidget(self.file_chip)

        self.image_chip = QFrame()
        self.image_chip.setObjectName("InsetCard")
        image_chip_layout = QHBoxLayout(self.image_chip)
        image_chip_layout.setContentsMargins(6, 4, 4, 4)
        image_chip_layout.setSpacing(6)
        self.image_thumb = QLabel()
        self.image_thumb.setFixedSize(40, 40)
        self.image_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_thumb.setStyleSheet(
            "background: white; border: 1px solid rgba(60,60,67,10%); border-radius: 8px;"
        )
        image_chip_layout.addWidget(self.image_thumb)
        self.image_chip_label = make_label("", color=Color.secondary)
        self.image_chip_label.setFont(app_font(10.5))
        self.image_chip_label.setMaximumWidth(80)
        image_chip_layout.addWidget(self.image_chip_label)
        image_clear = IconButton("close", "移除结构图片", color=Color.tertiary, size=20)
        image_clear.setIcon(icon("close", Color.tertiary, 11, 1.6))
        image_clear.clicked.connect(self._clear_image)
        image_chip_layout.addWidget(image_clear)
        self.image_chip.hide()
        chips_layout.addWidget(self.image_chip)
        chips_layout.addStretch(1)
        self.chips_host.hide()
        layout.addWidget(self.chips_host)

        self.image_hint = make_label(
            "图片会作为 DeepSeek 视觉输入（支持图文）",
            color=Color.tertiary,
        )
        self.image_hint.setFont(app_font(10.5))
        self.image_hint.setWordWrap(True)
        layout.addWidget(self.image_hint)
        return frame

    def _field(self, label: str, edit: QLineEdit, *, required: bool = False) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(5)
        top.addWidget(make_label(label, "FieldLabel"))
        if required:
            req = QLabel("必填")
            req.setObjectName("Required")
            req.setFont(app_font(10.5, app_font(10.5).weight()))
            top.addWidget(req)
        top.addStretch(1)
        layout.addLayout(top)
        layout.addWidget(edit)
        return host

    def _build_confirmed_card(self) -> QFrame:
        frame = card(inset=True)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(11)
        self.confirmed_image = QLabel()
        self.confirmed_image.setFixedSize(58, 58)
        self.confirmed_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.confirmed_image.setStyleSheet(
            "background: white; border: 1px solid rgba(60,60,67,10%); border-radius: 11px;"
        )
        layout.addWidget(self.confirmed_image)
        info = QVBoxLayout()
        info.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.confirmed_title = make_label("已确认结构", size=12.5,
                                           weight=app_font(12.5).weight())
        title_row.addWidget(self.confirmed_title)
        self.confirmed_badge = QLabel("CAS 检索")
        self.confirmed_badge.setFont(app_font(10))
        self.confirmed_badge.setStyleSheet(
            "background: rgba(0,122,255,10%); color: #007AFF;"
            "border-radius: 7px; padding: 1px 6px;"
        )
        title_row.addWidget(self.confirmed_badge)
        title_row.addStretch(1)
        info.addLayout(title_row)
        self.confirmed_meta = make_label("", color=Color.secondary)
        self.confirmed_meta.setFont(app_font(11))
        self.confirmed_meta.setWordWrap(True)
        info.addWidget(self.confirmed_meta)
        self.confirmed_smiles = make_label("", color=Color.tertiary)
        self.confirmed_smiles.setFont(app_font(10, app_font(10).weight(), mono=True))
        self.confirmed_smiles.setWordWrap(False)
        self.confirmed_smiles.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info.addWidget(self.confirmed_smiles)
        layout.addLayout(info, 1)
        self.confirmed_remove = IconButton("close", "移除已确认结构", color=Color.tertiary, size=24)
        self.confirmed_remove.setIcon(icon("close", Color.tertiary, 12, 1.6))
        self.confirmed_remove.clicked.connect(self._clear_confirmed)
        layout.addWidget(self.confirmed_remove, 0, Qt.AlignmentFlag.AlignTop)
        frame.hide()
        return frame

    def _build_progress_card(self) -> QFrame:
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(make_label("生成进度", size=13, weight=app_font(13).weight()))
        header.addStretch(1)
        self.progress_spinner = Spinner(15, Color.blue, frame)
        header.addWidget(self.progress_spinner)
        self.progress_status = StatusPill("等待", "idle", frame)
        header.addWidget(self.progress_status)
        layout.addLayout(header)

        self.progress_track = ProgressTrack(height=8)
        layout.addWidget(self.progress_track)

        self.progress_text = make_label("准备就绪", color=Color.secondary)
        self.progress_text.setFont(app_font(11.5))
        self.progress_text.setWordWrap(True)
        layout.addWidget(self.progress_text)

        self.notice = QLabel("")
        self.notice.setFont(app_font(11.5))
        self.notice.setWordWrap(True)
        self.notice.hide()
        layout.addWidget(self.notice)

        self.log_toggle = PillButton("查看日志", variant="ghost",
                                     icon_name="chevron-down", icon_color=Color.blue, height=26)
        self.log_toggle.setFont(app_font(11.5, app_font(11.5).weight()))
        self.log_toggle.clicked.connect(self._toggle_log)
        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self.log_toggle)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(150)
        self.log_view.setMinimumHeight(110)
        self.log_view.setFont(app_font(10.5, app_font(10.5).weight(), mono=True))
        self.log_view.document().setMaximumBlockCount(2000)
        self.log_view.hide()
        layout.addWidget(self.log_view)

        frame.hide()
        return frame

    def _build_right(self) -> QWidget:
        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.addWidget(make_label("结构预览", "PageTitle"))
        hint = make_label("拖拽旋转 · 滚轮缩放 · 双击复位", color=Color.secondary)
        hint.setFont(app_font(11.5))
        title_col.addWidget(hint)
        header.addLayout(title_col)
        header.addStretch(1)
        self.meta_label = make_label("", color=Color.secondary)
        self.meta_label.setFont(app_font(11.5))
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.meta_label)
        self.header_status = StatusPill("等待生成", "idle", right)
        header.addWidget(self.header_status)
        layout.addLayout(header)

        self.viewer_card = card()
        card_layout = QVBoxLayout(self.viewer_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(7)
        self.view_seg = SegmentedControl([label for label, _ in VIEWS],
                                         height=32, min_segment=42)
        self.view_seg.changed.connect(self._apply_view)
        self.view_seg.setEnabled(False)
        toolbar_layout.addWidget(self.view_seg)
        toolbar_layout.addStretch(1)
        self.reset_btn = IconButton("reset", "重置视角", color=Color.secondary, size=34)
        self.reset_btn.clicked.connect(self._reset_view)
        toolbar_layout.addWidget(self.reset_btn)
        self.download_btn = PillButton("下载结构", variant="tinted",
                                       icon_name="download", icon_color=Color.blue, height=32)
        self.download_btn.setFont(app_font(11.5, app_font(11.5).weight()))
        self.download_btn.clicked.connect(self._open_download)
        toolbar_layout.addWidget(self.download_btn)
        self.camera_btn = IconButton("camera", "保存当前视角图片", color=Color.secondary, size=34)
        self.camera_btn.clicked.connect(self._save_view_image)
        toolbar_layout.addWidget(self.camera_btn)
        self.fullscreen_btn = IconButton("expand", "沉浸模式（F11）", color=Color.secondary, size=34)
        self.fullscreen_btn.clicked.connect(self._toggle_immersive)
        toolbar_layout.addWidget(self.fullscreen_btn)
        card_layout.addWidget(toolbar)
        card_layout.addWidget(hline())

        self.stack = QStackedWidget()
        self.empty_page = self._build_empty_page()
        self.loading_page = self._build_loading_page()
        self.viewer = MoleculeViewer()
        self.viewer.ready.connect(self._on_viewer_ready)
        self.viewer.failed.connect(self._on_viewer_failed)
        self.stack.addWidget(self.empty_page)
        self.stack.addWidget(self.loading_page)
        self.stack.addWidget(self.viewer)
        card_layout.addWidget(self.stack, 1)

        self.footer = QWidget()
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(14, 8, 14, 8)
        footer_layout.setSpacing(10)
        self.legend_widget = QWidget()
        self.legend_layout = QHBoxLayout(self.legend_widget)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(10)
        footer_layout.addWidget(self.legend_widget)
        footer_layout.addStretch(1)
        self.cell_label = make_label("", color=Color.tertiary)
        self.cell_label.setFont(app_font(10.5))
        footer_layout.addWidget(self.cell_label)
        self.source_label = make_label("", color=Color.tertiary)
        self.source_label.setFont(app_font(10.5))
        footer_layout.addWidget(self.source_label)
        self.footer.hide()
        card_layout.addWidget(hline())
        card_layout.addWidget(self.footer)

        layout.addWidget(self.viewer_card, 1)
        self._set_actions_enabled(False)
        return right

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 26)
        layout.setSpacing(0)
        layout.addStretch(1)
        art = EmptyMoleculeArt()
        layout.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)
        title = make_label("等待构建结构", size=17, weight=app_font(17).weight())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        sub = make_label("输入分子式，DeepSeek 会生成可继续计算的 POSCAR", color=Color.secondary)
        sub.setFont(app_font(12))
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)
        layout.addSpacing(18)

        samples = QHBoxLayout()
        samples.setSpacing(6)
        samples.addStretch(1)
        sample_label = make_label("试试", color=Color.tertiary)
        sample_label.setFont(app_font(11))
        samples.addWidget(sample_label, 0, Qt.AlignmentFlag.AlignVCenter)
        for text, formula, name in (
            ("H₂O", "H2O", "水"),
            ("C₆H₆", "C6H6", "苯"),
            ("CH₃OH", "CH3OH", "甲醇"),
            ("CO₂", "CO2", "二氧化碳"),
        ):
            btn = PillButton(text, variant="tinted", height=29)
            btn.setFont(app_font(11.5, app_font(11.5).weight()))
            btn.clicked.connect(lambda _=False, f=formula, n=name: self._fill_sample(f, n))
            samples.addWidget(btn)
        samples.addStretch(1)
        layout.addLayout(samples)
        layout.addSpacing(12)
        shortcut = make_label("按 Ctrl + Enter 开始生成", color=Color.tertiary)
        shortcut.setFont(app_font(10.5))
        shortcut.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(shortcut)
        layout.addStretch(1)
        return page

    def _build_loading_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        self.loading_spinner = Spinner(24, Color.blue, page)
        layout.addWidget(self.loading_spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        self.loading_label = make_label("DeepSeek 正在构建结构…", color=Color.secondary)
        self.loading_label.setFont(app_font(12))
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.loading_label)
        layout.addStretch(1)
        return page

    # ============================================================ 配置/表单
    def _restore_form(self) -> None:
        cfg = self.config
        self.formula_edit.setText(cfg.last_formula)
        self.name_edit.setText(cfg.last_name)
        self.english_edit.setText(cfg.last_english_name)
        self.cas_edit.setText(cfg.last_cas)
        self.description_edit.setText(cfg.last_description)
        self.smiles_edit.setText(cfg.last_smiles)
        self._on_formula_changed()

    def _apply_config_state(self) -> None:
        self.callout.setVisible(not self.config.configured)
        model = self.config.model or DEFAULT_MODEL
        effort = self.config.reasoning_effort or DEFAULT_REASONING_EFFORT
        self.model_badge.setText(f"{model} · {effort}")
        self.progress_text.setText(
            f"使用 {model}（思考强度 {effort}）生成初始结构" if self.config.configured
            else "请先在设置中填写 DeepSeek API Key"
        )
        if not self.config.auto_relax and hasattr(self, "chgnet_status"):
            self._set_chgnet_status("已关闭", Color.secondary, "本次生成不会自动弛豫")

    def open_settings(self) -> None:
        sheet = SettingsSheet(self.config, self.window())
        sheet.saved.connect(self._on_settings_saved)
        sheet.exec()

    def _on_settings_saved(self, config: AppConfig) -> None:
        self.config = config
        self._apply_config_state()
        self._toast("DeepSeek 设置已保存", "success")

    def persist(self) -> None:
        self.config.snapshot_form(
            self.formula_edit.text(), self.name_edit.text(), self.english_edit.text(),
            self.cas_edit.text(), self.description_edit.text(), self.smiles_edit.text(),
        )
        try:
            self.config.save()
        except OSError:
            pass

    def _on_formula_changed(self) -> None:
        self.formula_edit.setProperty("error", "false")
        _repolish(self.formula_edit)

    def _fill_sample(self, formula: str, name: str) -> None:
        self.formula_edit.setText(formula)
        if not self.name_edit.text().strip():
            self.name_edit.setText(name)
        self.formula_edit.setFocus()

    # ============================================================== CAS 检索
    def _lookup_cas(self) -> None:
        cas = self.cas_edit.text().strip()
        if not cas:
            self._toast("请先填写 CAS 号", "warning")
            self.cas_edit.setFocus()
            return
        if self._cas_worker and self._cas_worker.isRunning():
            return
        self.cas_btn.setEnabled(False)
        self.cas_btn.setText("检索中…")
        self.cas_btn.setIcon(icon("search", Color.tertiary, 16, 1.8))
        self._cas_worker = CasWorker(cas)
        self._cas_worker.done.connect(self._on_cas_done)
        self._cas_worker.failed.connect(self._on_cas_failed)
        self._cas_worker.finished.connect(self._on_cas_finished)
        self._cas_worker.start()

    def _on_cas_done(self, compound: CompoundInfo) -> None:
        sheet = CASSheet(compound, self.window())
        if sheet.exec() == QDialog.DialogCode.Accepted:
            self._apply_compound(compound)

    def _on_cas_failed(self, message: str) -> None:
        self._toast(message, "error", 3600)

    def _on_cas_finished(self) -> None:
        self.cas_btn.setEnabled(True)
        self.cas_btn.setText("检索")
        self.cas_btn.setIcon(icon("search", Color.blue, 16, 1.8))
        if self._cas_worker:
            self._cas_worker.deleteLater()
            self._cas_worker = None

    def _apply_compound(self, compound: CompoundInfo) -> None:
        self._compound = compound
        self._molfile = compound.sdf
        self._molfile_name = f"CID {compound.cid}.sdf" if compound.sdf else ""
        self._structure_source = "CAS 检索"
        if compound.formula:
            self.formula_edit.setText(compound.formula)
        if compound.smiles:
            self.smiles_edit.setText(compound.smiles)
        if compound.display_name:
            self.english_edit.setText(compound.display_name)
        self.cas_edit.setText(compound.cas)
        self.file_chip.hide()
        self._refresh_chips()

        self.confirmed_image.clear()
        pixmap = QPixmap()
        if compound.png and pixmap.loadFromData(compound.png):
            self.confirmed_image.setPixmap(pixmap.scaled(
                52, 52, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        elif compound.sdf:
            self.confirmed_image.setPixmap(icon("doc", Color.secondary, 24, 1.6).pixmap(24, 24))
        self.confirmed_badge.setText("CAS 检索")
        self.confirmed_meta.setText(
            f"{compound.formula or '未知分子式'} · "
            f"{compound.atom_count or '?'} 原子 · CID {compound.cid}"
        )
        self.confirmed_smiles.setText(self._shorten(compound.smiles) or "—")
        self.confirmed_card.show()
        self._toast("已确认结构，将作为 DeepSeek 的建模参考", "success")

    @staticmethod
    def _shorten(text: str, limit: int = 42) -> str:
        text = (text or "").strip().replace("\n", " ")
        return text if len(text) <= limit else text[:limit] + "…"

    def _clear_confirmed(self) -> None:
        self._compound = None
        self._molfile = ""
        self._molfile_name = ""
        self._structure_source = ""
        self.confirmed_card.hide()
        self.file_chip.hide()
        self._refresh_chips()
        self._toast("已移除结构参考", "info")

    # ============================================================ 结构文件
    def _import_structure(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.window(), "导入结构文件", "",
            "结构文件 (*.sdf *.mol *.xyz *.pdb);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._toast(f"读取失败：{exc}", "error")
            return
        if len(text) > 2_000_000:
            self._toast("结构文件过大（上限 2 MB）", "warning")
            return
        self._molfile = text
        self._molfile_name = self._shorten(Path(path).name, 24)
        self._structure_source = "结构文件"
        self.file_chip_label.setText(self._molfile_name)
        self.file_chip.show()
        self._refresh_chips()
        self._compound = None

        self.confirmed_image.clear()
        self.confirmed_image.setPixmap(icon("doc", Color.secondary, 24, 1.6).pixmap(24, 24))
        self.confirmed_badge.setText("结构文件")
        self.confirmed_meta.setText(f"{self._molfile_name} · 将作为连接表参考")
        self.confirmed_smiles.setText(self._shorten(text.splitlines()[0]) if text else "")
        self.confirmed_card.show()
        self._toast(f"已导入 {self._molfile_name}", "success")

    def _clear_structure_file(self) -> None:
        self._molfile = ""
        self._molfile_name = ""
        if self._structure_source == "结构文件":
            self._structure_source = ""
        self.file_chip.hide()
        self._refresh_chips()
        if not self._compound:
            self.confirmed_card.hide()
        self._toast("已移除结构文件", "info")

    # ============================================================ 结构图片
    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.window(), "选择结构图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            data_url, image = load_structure_image(path)
        except ImageInputError as exc:
            kind = "warning" if ("过大" in str(exc) or "12 MB" in str(exc)) else "error"
            self._toast(str(exc), kind)
            return
        self._image_b64 = data_url
        self._image_name = Path(path).name
        self.image_chip_label.setText(self._shorten(self._image_name, 18))
        self.image_thumb.setPixmap(QPixmap.fromImage(image).scaled(
            38, 38,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self.image_chip.show()
        self._refresh_chips()
        self._toast(f"已添加结构图片 {self._image_name}", "success")

    def _clear_image(self) -> None:
        self._image_b64 = ""
        self._image_name = ""
        self.image_chip.hide()
        self.image_thumb.clear()
        self._refresh_chips()
        self._toast("已移除结构图片", "info")

    def _refresh_chips(self) -> None:
        self.chips_host.setVisible(
            not self.file_chip.isHidden() or not self.image_chip.isHidden()
        )

    # ============================================================ 结构编辑
    def _open_structure_editor(self) -> None:
        smiles = self.smiles_edit.text().strip()
        if not smiles and self._compound:
            smiles = self._compound.smiles
        dialog = StructureEditorDialog(
            self.window(),
            smiles=smiles,
            molfile=self._molfile,
        )
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            data = dialog.result_data if accepted else None
        finally:
            dialog.deleteLater()
        if data:
            self._apply_editor_structure(data)

    def _apply_editor_structure(self, data: dict) -> None:
        smiles = str(data.get("smiles") or "").strip()
        if not smiles:
            return
        molfile = str(data.get("molfile") or "")
        self.smiles_edit.setText(smiles)
        self._molfile = molfile
        self._molfile_name = "Ketcher 结构" if molfile else ""
        self._structure_source = "Ketcher 结构编辑"
        self._compound = None
        # 编辑器结构是新的权威来源，清掉旧的图片/文件参考，避免冲突
        self._image_b64 = ""
        self._image_name = ""
        self.image_chip.hide()
        self.image_thumb.clear()
        self.file_chip.hide()
        self._refresh_chips()

        formula, atom_count = molfile_summary(molfile)
        if formula:
            self.formula_edit.setText(formula)

        self.confirmed_image.clear()
        pixmap = _svg_pixmap(str(data.get("svg") or ""))
        if pixmap is not None:
            self.confirmed_image.setPixmap(pixmap)
        else:
            self.confirmed_image.setPixmap(
                icon("doc", Color.secondary, 24, 1.6).pixmap(24, 24))
        self.confirmed_badge.setText("结构编辑")
        meta = formula or "自定义结构"
        if atom_count:
            meta += f" · {atom_count} 原子"
        meta += " · Ketcher"
        self.confirmed_meta.setText(meta)
        self.confirmed_smiles.setText(self._shorten(smiles))
        self.confirmed_card.show()
        self._toast("已从结构编辑器回填 SMILES / molfile", "success")

    # ============================================================== 生成流程
    def _start_or_cancel(self) -> None:
        if self._relax_worker and self._relax_worker.isRunning():
            self._cancel_relax()
            return
        if self._gen_worker and self._gen_worker.isRunning():
            self._cancel_generation()
            return
        self._start_generation()

    def _start_generation(self) -> None:
        if self._relax_worker and self._relax_worker.isRunning():
            return
        formula = self.formula_edit.text().strip()
        if not parse_formula(formula):
            self.formula_edit.setProperty("error", "true")
            _repolish(self.formula_edit)
            self.formula_edit.setFocus()
            self._toast("请填写有效的分子式，例如 C6H6", "warning")
            return
        if not self.config.configured:
            self._toast("请先配置 DeepSeek API Key", "warning")
            self.open_settings()
            return

        payload = {
            "formula": normalize_formula(formula),
            "name": self.name_edit.text().strip(),
            "english_name": self.english_edit.text().strip(),
            "cas": self.cas_edit.text().strip(),
            "description": self.description_edit.text().strip(),
            "smiles": self.smiles_edit.text().strip(),
            "molfile": self._molfile,
            "image_b64": self._image_b64,
            "structure_source": (
                self._structure_source
                or ("结构图片" if self._image_b64 else "")
                or ("SMILES（手填）" if self.smiles_edit.text().strip() else "")
            ),
        }
        self._previous_structure = self._structure
        self.progress_card.show()
        self.notice.hide()
        self.log_view.clear()
        self.log_view.hide()
        self.log_toggle.setText("查看日志")
        self.log_toggle.setIcon(icon("chevron-down", Color.blue, 14, 1.8))
        self._log_kind = ""
        self.progress_track.set_target(0.03, animate=False)
        self.progress_spinner.start()
        self.progress_status.set_status("生成中", "running")
        self.header_status.set_status("DeepSeek 生成中", "running")
        self.progress_text.setText(
            f"正在连接 {self.config.model}（{self.config.reasoning_effort}）…")
        self._set_generating(True)
        self._switch_loading("DeepSeek 正在构建结构…")
        self._scroll_to_progress()
        self._append_status(
            f"开始生成：{normalize_formula(formula)} · 模型 {self.config.model} · "
            f"思考强度 {self.config.reasoning_effort}")

        self._gen_worker = GenerateWorker(self.config, payload)
        self._gen_worker.progress.connect(self._on_generation_progress)
        self._gen_worker.event.connect(self._on_generation_event)
        self._gen_worker.succeeded.connect(self._on_generation_done)
        self._gen_worker.failed.connect(self._on_generation_failed)
        self._gen_worker.cancelled.connect(self._on_generation_cancelled)
        self._gen_worker.finished.connect(self._on_generation_finished)
        self._gen_worker.start()

    def _cancel_generation(self) -> None:
        if not self._gen_worker or not self._gen_worker.isRunning():
            return
        self._gen_worker.cancel()
        self.progress_status.set_status("取消中", "warning")
        self.progress_text.setText("正在取消请求…")
        self.header_status.set_status("取消中", "warning")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("正在取消…")

    def _on_generation_progress(self, percent: int, text: str) -> None:
        self.progress_track.set_target(max(0.03, percent / 100.0))
        if text:
            self.progress_text.setText(text)

    def _on_generation_event(self, kind: str, text: str) -> None:
        if kind == "status":
            self._append_status(text)
            if text:
                self.progress_text.setText(text)
            return
        if kind == "thinking":
            if self._log_kind != "thinking":
                self._append_log("\n[思考] ")
            self._append_log(text)
            self.progress_text.setText("DeepSeek 正在推理…")
        elif kind == "content":
            if self._log_kind != "content":
                self._append_log("\n[生成] ")
            self._append_log(text)
            self.progress_text.setText("正在生成 POSCAR…")
        self._log_kind = kind

    def _on_generation_done(self, result: GenerationResult, structure: StructureData) -> None:
        self._result = result
        self._structure = structure
        self._initial_structure = structure
        self.progress_track.set_target(1.0)
        self.progress_status.set_status("已完成", "success")
        self.progress_spinner.stop()
        self.header_status.set_status("已生成", "success")
        self.progress_text.setText(
            f"{result.model} · {self.config.reasoning_effort} · "
            f"{result.elapsed:.1f} 秒 · {structure.atom_count} 个原子"
        )
        self._append_status(
            f"生成完成：{structure.formula}，{structure.atom_count} 个原子，"
            f"用时 {result.elapsed:.1f} 秒"
        )
        if structure.warnings:
            self._show_notice("warning", "；".join(structure.warnings))
            self._toast(structure.warnings[0], "warning", 4200)
        self._set_generating(False)
        self._render_structure(structure)
        if self.config.auto_relax:
            if self._chgnet_env is not None:
                self._toast("初始结构已生成，开始 CHGNet 弛豫", "info")
                self._start_relax(structure)
            else:
                message = (
                    "未检测到可用的 CHGNet 环境，已跳过弛豫。"
                    "请运行 install_chgnet.bat，然后点击「检测」。"
                )
                self._show_notice("warning", message)
                self.progress_text.setText("已生成结构 · CHGNet 未安装，未执行弛豫")
                self._toast("已生成结构；CHGNet 未安装，已跳过弛豫", "warning", 4200)
        else:
            self._toast(f"已生成 {structure.formula} 的 3D 结构", "success")

    def _on_generation_failed(self, message: str) -> None:
        self.progress_spinner.stop()
        self.progress_track.set_target(0.0, animate=False)
        self.progress_status.set_status("失败", "error")
        self.header_status.set_status("生成失败", "error")
        self.progress_text.setText("生成失败，请检查 DeepSeek 设置或网络后重试")
        self._append_status(f"失败：{message}")
        self._show_notice("error", message)
        self._set_generating(False)
        self._restore_previous_structure()
        self.header_status.set_status("生成失败", "error")
        self._toast(message, "error", 4200)

    def _on_generation_cancelled(self) -> None:
        self.progress_spinner.stop()
        self.progress_track.set_target(0.0, animate=False)
        self.progress_status.set_status("已取消", "cancelled")
        self.header_status.set_status("已取消", "cancelled")
        self.progress_text.setText("本次生成已取消")
        self._append_status("用户取消了本次生成")
        self._show_notice("warning", "生成已取消，没有产生新的结构。")
        self._set_generating(False)
        self._restore_previous_structure()
        self.header_status.set_status("已取消", "cancelled")
        self._toast("已取消生成", "info")

    def _on_generation_finished(self) -> None:
        worker = self._gen_worker
        self._gen_worker = None
        if worker:
            worker.deleteLater()

    # ============================================================ CHGNet
    def _set_chgnet_status(self, text: str, color: str, tooltip: str = "") -> None:
        self.chgnet_status.setText(text)
        self.chgnet_status.setStyleSheet(f"color: {color};")
        self.chgnet_status.setToolTip(tooltip or text)

    def _apply_chgnet_env_status(self) -> None:
        env = self._chgnet_env
        if env is None:
            return
        text = "CUDA" if env.device == "cuda" else "CPU"
        color = Color.green if env.device == "cuda" else Color.secondary
        tooltip = (
            f"{env.label}\ntorch {env.torch} · chgnet {env.chgnet}\n"
            f"{env.python}"
        )
        self._set_chgnet_status(text, color, tooltip)
        self.chgnet_retry.hide()

    def _on_relax_toggled(self, checked: bool) -> None:
        self.config.auto_relax = bool(checked)
        if not checked:
            self._set_chgnet_status("已关闭", Color.secondary, "本次生成不会自动弛豫")
            self.chgnet_retry.hide()
            return
        if self._chgnet_env is not None:
            self._apply_chgnet_env_status()
        else:
            self._set_chgnet_status(
                "未安装", Color.orange,
                "运行 install_chgnet.bat，然后点击「检测」",
            )
            self.chgnet_retry.show()

    def _start_chgnet_probe(self, force: bool = False) -> None:
        if self._chgnet_probe is not None and self._chgnet_probe.isRunning():
            return
        if self._chgnet_env is not None and not force:
            self._apply_chgnet_env_status()
            return
        if force:
            self._chgnet_env = None
        self._set_chgnet_status("检测中…", Color.tertiary, "正在检测 CHGNet/torch 环境…")
        self.chgnet_retry.hide()
        self._chgnet_probe_started = True
        self._chgnet_probe = ChgnetProbeWorker(self.config, self)
        self._chgnet_probe.detected.connect(self._on_chgnet_detected)
        self._chgnet_probe.unavailable.connect(self._on_chgnet_unavailable)
        self._chgnet_probe.finished.connect(self._on_chgnet_probe_finished)
        self._chgnet_probe.start()

    def _on_chgnet_detected(self, env: ChgnetEnvironment) -> None:
        self._chgnet_env = env
        if self.config.auto_relax:
            self._apply_chgnet_env_status()
        else:
            self._set_chgnet_status("已关闭", Color.secondary, "本次生成不会自动弛豫")

    def _on_chgnet_unavailable(self, message: str) -> None:
        self._chgnet_env = None
        if self.config.auto_relax:
            self._set_chgnet_status(
                "未安装", Color.orange,
                message + "\n\n运行 install_chgnet.bat，然后点击「检测」",
            )
            self.chgnet_retry.show()

    def _on_chgnet_probe_finished(self) -> None:
        worker = self._chgnet_probe
        self._chgnet_probe = None
        if worker:
            worker.deleteLater()

    def _start_relax(self, structure: StructureData) -> None:
        env = self._chgnet_env
        if env is None:
            return
        self._initial_structure = structure
        self._relax_log_count = 0
        self.progress_card.show()
        self.notice.hide()
        self.progress_track.set_target(0.12, animate=True)
        self.progress_spinner.start()
        self.progress_status.set_status("弛豫中", "running")
        self.header_status.set_status("CHGNet 弛豫中", "running")
        self.progress_text.setText(
            f"CHGNet 弛豫中 · {env.label} · 最多 {self.config.chgnet_max_steps} 步"
        )
        self._append_status(
            f"CHGNet 弛豫开始：{structure.formula} · {env.label} · "
            f"max_steps={self.config.chgnet_max_steps} · fmax={self.config.chgnet_fmax} eV/Å"
        )
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("取消弛豫")
        self.generate_btn.setProperty("variant", "destructive")
        self.generate_btn.setIcon(icon("close", Color.red, 16, 2.0))
        _repolish(self.generate_btn)
        self.clear_btn.setEnabled(False)
        self.relax_switch.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.camera_btn.setEnabled(False)

        self._relax_worker = ChgnetRelaxWorker(
            structure,
            env,
            max_steps=self.config.chgnet_max_steps,
            fmax=self.config.chgnet_fmax,
            parent=self,
        )
        self._relax_worker.log.connect(self._on_relax_log)
        self._relax_worker.succeeded.connect(self._on_relax_succeeded)
        self._relax_worker.failed.connect(self._on_relax_failed)
        self._relax_worker.cancelled.connect(self._on_relax_cancelled)
        self._relax_worker.finished.connect(self._on_relax_finished)
        self._relax_worker.start()
        self._scroll_to_progress()

    def _on_relax_log(self, line: str) -> None:
        line = (line or "").rstrip()
        if not line:
            return
        self._append_log(f"[CHGNet] {line}\n")
        self._relax_log_count += 1
        self.progress_track.set_target(min(0.9, 0.12 + self._relax_log_count * 0.012))
        if any(key in line for key in ("CHGNet", "formula=", "device=", "done", "ERROR", "Error")):
            self.progress_text.setText(line[:160])

    def _on_relax_succeeded(self, structure: StructureData, info: dict) -> None:
        self._structure = structure
        self._render_structure(structure)
        self.progress_track.set_target(1.0)
        self.progress_status.set_status("已完成", "success")
        self.progress_spinner.stop()
        self.header_status.set_status("弛豫完成", "success")
        energy = info.get("final_energy")
        try:
            energy_text = f"{float(energy):.4f} eV"
        except (TypeError, ValueError):
            energy_text = ""
        steps = info.get("steps", "?")
        device = str(info.get("device") or (
            self._chgnet_env.short_label if self._chgnet_env else ""
        ))
        text = f"CHGNet {device} · {steps} 步" + (f" · 最终能量 {energy_text}" if energy_text else "")
        self.progress_text.setText(text)
        self._append_status("CHGNet 弛豫完成：" + text)
        self._set_generating(False)
        self.relax_switch.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.camera_btn.setEnabled(True)
        if structure.warnings:
            self._show_notice("warning", "；".join(structure.warnings))
        else:
            self.notice.hide()
        self._toast("CHGNet 弛豫完成", "success")

    def _on_relax_failed(self, message: str) -> None:
        self.progress_spinner.stop()
        self.progress_track.set_target(0.0, animate=False)
        self.progress_status.set_status("失败", "error")
        self.header_status.set_status("弛豫失败", "warning")
        self.progress_text.setText("CHGNet 弛豫失败，已保留初始结构")
        self._append_status(f"CHGNet 弛豫失败：{message}")
        self._show_notice("error", message)
        self._set_generating(False)
        self.relax_switch.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.camera_btn.setEnabled(True)
        self._toast("CHGNet 弛豫失败，已保留初始结构", "error", 4200)

    def _on_relax_cancelled(self) -> None:
        self.progress_spinner.stop()
        self.progress_track.set_target(0.0, animate=False)
        self.progress_status.set_status("已取消", "cancelled")
        self.header_status.set_status("已取消", "cancelled")
        self.progress_text.setText("CHGNet 弛豫已取消，保留初始结构")
        self._append_status("用户取消了 CHGNet 弛豫")
        self._show_notice("warning", "CHGNet 弛豫已取消，显示的是初始结构。")
        self._set_generating(False)
        self.relax_switch.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.camera_btn.setEnabled(True)
        self._toast("已取消 CHGNet 弛豫", "info")

    def _on_relax_finished(self) -> None:
        worker = self._relax_worker
        self._relax_worker = None
        if worker:
            worker.deleteLater()
        self.progress_spinner.stop()
        self.relax_switch.setEnabled(True)
        if self._structure is not None:
            self._set_generating(False)

    def _cancel_relax(self) -> None:
        worker = self._relax_worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        self.progress_status.set_status("取消中", "warning")
        self.progress_text.setText("正在停止 CHGNet 弛豫…")
        self.header_status.set_status("取消中", "warning")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("正在取消…")

    def _set_generating(self, running: bool) -> None:
        self.generate_btn.setEnabled(True)
        if running:
            self.generate_btn.setText("取消生成")
            self.generate_btn.setProperty("variant", "destructive")
            self.generate_btn.setIcon(icon("close", Color.red, 16, 2.0))
            self.clear_btn.setEnabled(False)
        else:
            self.generate_btn.setText("重新生成" if self._structure else "开始生成结构")
            self.generate_btn.setProperty("variant", "primary")
            color = "#FFFFFF"
            self.generate_btn.setIcon(icon("sparkles", color, 17, 1.9))
            self.clear_btn.setEnabled(True)
        _repolish(self.generate_btn)

    def _restore_previous_structure(self) -> None:
        previous = getattr(self, "_previous_structure", None)
        if previous:
            self._render_structure(previous)
        else:
            self._structure = None
            self.stack.setCurrentWidget(self.empty_page)
            self.footer.hide()
            self.meta_label.setText("")
            self._set_actions_enabled(False)

    # ============================================================== 渲染/工具
    def _render_structure(self, structure: StructureData) -> None:
        self._structure = structure
        self.viewer.load_structure(structure.sdf)
        self._switch_loading("正在渲染 3D 结构…")
        self._render_token += 1
        token = self._render_token

        def show_viewer() -> None:
            if token == self._render_token and self._structure is structure:
                self.stack.setCurrentWidget(self.viewer)

        QTimer.singleShot(800, show_viewer)

        self.meta_label.setText(
            f"{structure.formula} · {structure.atom_count} 原子"
            + (f" · {structure.molecular_weight:.1f} g/mol" if structure.molecular_weight else "")
        )
        self.header_status.set_status("已生成", "success")
        self._update_legend(structure.elements)
        a, b, c = structure.cell
        self.cell_label.setText(f"{a:.1f} × {b:.1f} × {c:.1f} Å")
        self.source_label.setText(structure.source)
        self.footer.show()
        self._set_actions_enabled(True)
        self.view_seg.set_current_index(0, animate=False)
        self._current_view = 0

    def _switch_loading(self, text: str) -> None:
        self.loading_label.setText(text)
        self.loading_spinner.start()
        self.stack.setCurrentWidget(self.loading_page)

    def _on_viewer_ready(self) -> None:
        if self._structure and self.stack.currentWidget() is self.loading_page:
            QTimer.singleShot(260, lambda: self.stack.setCurrentWidget(self.viewer)
                              if self._structure else None)

    def _on_viewer_failed(self, message: str) -> None:
        self.loading_spinner.stop()
        self._toast(message, "error")
        self.stack.setCurrentWidget(self.empty_page)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self.view_seg.setEnabled(enabled)
        for button in (self.reset_btn, self.download_btn, self.camera_btn):
            button.setEnabled(enabled)
        self.fullscreen_btn.setEnabled(True)

    def _apply_view(self, index: int) -> None:
        if not self._structure:
            return
        index = max(0, min(index, len(VIEWS) - 1))
        self._current_view = index
        self.viewer.set_view(VIEWS[index][1])

    def _reset_view(self) -> None:
        self.viewer.reset_view()
        self.view_seg.set_current_index(0, animate=True, emit=False)
        self._current_view = 0

    def _toggle_immersive(self) -> None:
        window = self.window()
        if hasattr(window, "toggle_immersive"):
            window.toggle_immersive()

    def _on_immersive_changed(self, enabled: bool) -> None:
        self.sidebar.setVisible(not enabled)
        self.fullscreen_btn.setIcon(icon("shrink" if enabled else "expand",
                                         Color.secondary, 18, 1.8))
        self.fullscreen_btn.setToolTip("退出沉浸模式（Esc）" if enabled else "沉浸模式（F11）")

    def _open_download(self) -> None:
        if not self._structure:
            self._toast("请先生成结构", "warning")
            return
        sheet = DownloadSheet(self._structure, self.window())
        sheet.exec()

    def _save_view_image(self) -> None:
        if not self._structure:
            self._toast("请先生成结构", "warning")
            return
        name = re.sub(r"[^A-Za-z0-9_.-]+", "", self._structure.formula) or "structure"
        path, _ = QFileDialog.getSaveFileName(
            self.window(), "保存当前视角", f"{name}_{VIEWS[self._current_view][0]}.png",
            "PNG 图片 (*.png)",
        )
        if not path:
            return

        def done(data_url) -> None:
            if not data_url or not str(data_url).startswith("data:image"):
                self._toast("截图失败", "error")
                return
            try:
                payload = str(data_url).split(",", 1)[1]
                Path(path).write_bytes(base64.b64decode(payload))
            except (IndexError, ValueError, OSError) as exc:
                self._toast(f"保存失败：{exc}", "error")
                return
            self._toast(f"已保存到 {path}", "success")

        self.viewer.grab_png(done)

    # ------------------------------------------------------------- 日志/提示
    def _append_log(self, text: str) -> None:
        if not text:
            return
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_view.insertPlainText(text)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_view.ensureCursorVisible()

    def _append_status(self, text: str) -> None:
        self._append_log(f"\n[状态] {text}\n")
        self._log_kind = ""

    def _toggle_log(self) -> None:
        visible = self.log_view.isVisible()
        self.log_view.setVisible(not visible)
        self.log_toggle.setText("收起日志" if not visible else "查看日志")
        self.log_toggle.setIcon(icon(
            "chevron-up" if not visible else "chevron-down", Color.blue, 14, 1.8))
        if not visible:
            self.log_view.ensureCursorVisible()
            QTimer.singleShot(
                40, lambda: self.scroll.ensureWidgetVisible(self.log_view, 0, 12))

    def _show_notice(self, kind: str, text: str) -> None:
        if kind == "error":
            style = (
                "background: rgba(255,59,48,8%); color: #B42318;"
                " border: 1px solid rgba(255,59,48,14%);"
                " border-radius: 10px; padding: 8px 10px;"
            )
        else:
            style = (
                "background: rgba(255,149,0,9%); color: #8A4B00;"
                " border: 1px solid rgba(255,149,0,16%);"
                " border-radius: 10px; padding: 8px 10px;"
            )
        self.notice.setStyleSheet(style)
        self.notice.setText(text)
        self.notice.show()

    def _update_legend(self, elements: list[str]) -> None:
        _clear_layout(self.legend_layout)
        if not elements:
            return
        for element in elements[:7]:
            item = QWidget()
            row = QHBoxLayout(item)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(ElementDot(element_color(element), 9, item))
            label = make_label(element, color=Color.secondary)
            label.setFont(app_font(10.5, app_font(10.5).weight()))
            row.addWidget(label)
            self.legend_layout.addWidget(item)
        if len(elements) > 7:
            more = make_label(f"+{len(elements) - 7}", color=Color.tertiary)
            more.setFont(app_font(10.5))
            self.legend_layout.addWidget(more)

    def _scroll_to_progress(self) -> None:
        QTimer.singleShot(
            60, lambda: self.scroll.ensureWidgetVisible(self.progress_card, 0, 14))

    def _toast(self, text: str, kind: str = "info", duration: int = 2800) -> None:
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast(text, kind, duration)

    def reset_all(self) -> None:
        if self._gen_worker and self._gen_worker.isRunning():
            return
        if self._relax_worker and self._relax_worker.isRunning():
            return
        self.formula_edit.clear()
        self.name_edit.clear()
        self.english_edit.clear()
        self.cas_edit.clear()
        self.description_edit.clear()
        self.smiles_edit.clear()
        self._compound = None
        self._molfile = ""
        self._molfile_name = ""
        self._image_b64 = ""
        self._image_name = ""
        self._structure_source = ""
        self._initial_structure = None
        self._relax_log_count = 0
        self.relax_switch.setEnabled(True)
        self.confirmed_card.hide()
        self.file_chip.hide()
        self.image_chip.hide()
        self._refresh_chips()
        self.image_thumb.clear()
        self.progress_card.hide()
        self.progress_spinner.stop()
        self.progress_track.set_target(0, animate=False)
        self.progress_text.setText("准备就绪")
        self.progress_status.set_status("等待", "idle")
        self.header_status.set_status("等待生成", "idle")
        self.meta_label.setText("")
        self.footer.hide()
        self._structure = None
        self._result = None
        self._previous_structure = None
        self.formula_edit.setProperty("error", "false")
        _repolish(self.formula_edit)
        self.viewer.clear()
        self.stack.setCurrentWidget(self.empty_page)
        self._set_actions_enabled(False)
        self.generate_btn.setText("开始生成结构")
        self.generate_btn.setProperty("variant", "primary")
        self.generate_btn.setIcon(icon("sparkles", "#FFFFFF", 17, 1.9))
        _repolish(self.generate_btn)
        self.formula_edit.setFocus()
        self._toast("已清空", "info")

    def shutdown(self) -> None:
        self.persist()
        relax = self._relax_worker
        if relax and relax.isRunning():
            relax.cancel()
            if not relax.wait(3000):
                relax.terminate()
                relax.wait(500)
        worker = self._gen_worker
        if worker and worker.isRunning():
            worker.cancel()
            if not worker.wait(2500):
                worker.terminate()
                worker.wait(500)
        cas = self._cas_worker
        if cas and cas.isRunning():
            cas.wait(1000)
        probe = self._chgnet_probe
        if probe and probe.isRunning():
            if not probe.wait(1500):
                probe.terminate()
                probe.wait(300)

    # -------------------------------------------------------------- 事件
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._immersive_connected:
            window = self.window()
            if hasattr(window, "immersiveChanged"):
                window.immersiveChanged.connect(self._on_immersive_changed)
                self._immersive_connected = True
        if not self._chgnet_probe_started:
            self._start_chgnet_probe()
        if not hasattr(self, "_shortcuts"):
            self._shortcuts = []
            for seq in ("Ctrl+Return", "Ctrl+Enter", "Meta+Return"):
                shortcut = QShortcut(QKeySequence(seq), self)
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut.activated.connect(self._start_or_cancel)
                self._shortcuts.append(shortcut)
