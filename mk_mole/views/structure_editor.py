"""Ketcher 结构编辑器弹层（本地 HTTP 服务 + QWebEngine）。

Ketcher 是 Web_Probe 页面使用的自托管结构编辑器；这里把同一份预构建资源
放在 `mk_mole/assets/ketcher`，通过临时 localhost 服务加载，避免 file://
下的 SharedArrayBuffer / 跨源隔离限制。确认后返回 SMILES、molfile 和 SVG。
"""

from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme import Color, app_font
from ..widgets.controls import IconButton, PillButton, Spinner, hline, make_label


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


class _KetcherHandler(SimpleHTTPRequestHandler):
    """为 Ketcher 提供静态文件，并开启 WASM SharedArrayBuffer 所需的跨源隔离。"""

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, *args):  # noqa: D401
        return

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class StructureEditorDialog(QDialog):
    """模态 Ketcher 编辑器；exec() 后读取 result_data。"""

    def __init__(self, parent: QWidget, *, smiles: str = "", molfile: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setWindowTitle("MK-MOLE 结构编辑器")

        self._initial_smiles = smiles or ""
        self._initial_molfile = molfile or ""
        self._ready = False
        self._poll_tries = 0
        self._confirm_tries = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setSingleShot(True)
        self._poll_timer.timeout.connect(self._poll_ready)
        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.timeout.connect(self._poll_confirm)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._reset_status_style)
        self.result_data: dict | None = None

        self._build_ui()
        self._start_server()
        self._load_ketcher()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 26, 34, 26)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("SheetCard")
        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("结构编辑器", size=20, weight=app_font(20).weight()))
        subtitle = make_label(
            "在 Ketcher 中绘制或修改结构；确认后回填 SMILES 与 molfile，作为 DeepSeek 的准确参考。",
            color=Color.secondary,
        )
        subtitle.setFont(app_font(12))
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        close = IconButton("close", "关闭", color=Color.secondary, size=30)
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(header)
        body.addWidget(hline())

        self.stack = QStackedWidget()
        self.loading_page = self._build_loading_page()
        self.web = QWebEngineView()
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web.setStyleSheet("background: white;")
        settings = self.web.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        try:
            self.web.page().setBackgroundColor(QColor("#FFFFFF"))
        except AttributeError:
            pass
        self.web.loadFinished.connect(self._on_load_finished)
        self.stack.addWidget(self.loading_page)
        self.stack.addWidget(self.web)

        box = QFrame()
        box.setObjectName("KetcherBox")
        box.setStyleSheet(
            "QFrame#KetcherBox { background: white;"
            " border: 1px solid rgba(60,60,67,12%); border-radius: 12px; }"
        )
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(8, 8, 8, 8)
        box_layout.addWidget(self.stack)
        body.addWidget(box, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.status_label = make_label("正在启动本地结构编辑器…", color=Color.secondary)
        self.status_label.setFont(app_font(11.5))
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.cancel_btn = PillButton("取消", variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = PillButton(
            "使用该结构", variant="primary", icon_name="check",
            icon_color="#FFFFFF", height=38,
        )
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.confirm_btn)
        body.addLayout(footer)

    def _build_loading_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        self.loading_spinner = Spinner(24, Color.blue, page)
        layout.addWidget(self.loading_spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        self.loading_label = make_label(
            "Ketcher 编辑器加载中…\n首次加载约需数秒",
            color=Color.secondary,
        )
        self.loading_label.setFont(app_font(12))
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.loading_label)
        layout.addStretch(1)
        return page

    def showEvent(self, event) -> None:  # noqa: N802
        parent = self.parentWidget()
        if parent:
            top_left = parent.mapToGlobal(parent.rect().topLeft())
            self.setGeometry(top_left.x(), top_left.y(), parent.width(), parent.height())
            available_w = max(760, parent.width() - 80)
            available_h = max(600, parent.height() - 80)
            self.card.setFixedSize(min(1160, available_w), min(860, available_h))
        super().showEvent(event)
        if self.stack.currentWidget() is self.loading_page:
            self.loading_spinner.start()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            local = self.card.mapFrom(self, event.position().toPoint())
            if not self.card.rect().contains(local):
                self.reject()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 32, 100))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 24, 24)
        p.end()

    # ------------------------------------------------------------ Ketcher
    def _start_server(self) -> None:
        directory = _assets_dir() / "ketcher"
        if not (directory / "index.html").exists():
            self._set_error("未找到 Ketcher 编辑器资源，请重新安装/打包。")
            return
        try:
            self._httpd = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                lambda *args, **kwargs: _KetcherHandler(
                    *args, directory=str(directory), **kwargs),
            )
            self._httpd.daemon_threads = True
            self._http_thread = threading.Thread(
                target=self._httpd.serve_forever, daemon=True)
            self._http_thread.start()
            self._ketcher_url = (
                f"http://127.0.0.1:{self._httpd.server_address[1]}/index.html"
            )
        except OSError as exc:
            self._set_error(f"无法启动本地结构编辑器：{exc}")

    def _load_ketcher(self) -> None:
        if self._httpd is None:
            return
        self.web.load(QUrl(self._ketcher_url))

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            self._set_error("结构编辑器加载失败，请重试")
            return
        self._poll_tries = 0
        self._poll_ready()

    def _poll_ready(self) -> None:
        if self._poll_tries > 260:
            self._set_error("结构编辑器初始化超时，请重试")
            return
        self._poll_tries += 1
        self.web.page().runJavaScript(
            "!!(window.ketcher && window.ketcher.editor && window.ketcher.editor.render)",
            0,
            self._on_ready_result,
        )

    def _on_ready_result(self, ready) -> None:
        if ready:
            self._ready = True
            self.loading_spinner.stop()
            self.stack.setCurrentWidget(self.web)
            self.status_label.setText("已就绪 · 可绘制/修改结构")
            self.confirm_btn.setEnabled(True)
            self._apply_initial()
            self.web.setFocus()
            return
        self._poll_timer.start(120)

    def _apply_initial(self) -> None:
        if not self._ready:
            return
        initial = self._initial_smiles.strip() or self._initial_molfile.strip()
        if not initial:
            script = "window.ketcher.clear();"
        else:
            script = (
                f"window.ketcher.setMolecule({json.dumps(initial)})"
                ".catch(e => console.error('MK-MOLE initial structure:', e));"
            )
        self.web.page().runJavaScript(script)

    # -------------------------------------------------------------- 确认
    def _confirm(self) -> None:
        if not self._ready:
            self.status_label.setText("编辑器尚未就绪，请稍候")
            return
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setText("读取结构…")
        self.status_label.setText("正在读取 SMILES / molfile…")
        self._confirm_tries = 0
        self.web.page().runJavaScript(
            "window.__mkKetcherResult = null;"
            "(async () => {"
            "  try {"
            "    const smiles = await window.ketcher.getSmiles();"
            "    let molfile = '';"
            "    try { molfile = await window.ketcher.getMolfile(); } catch (e) {}"
            "    let svg = '';"
            "    try { svg = await window.ketcher.getSvg(); } catch (e) {}"
            "    window.__mkKetcherResult = {ok: true, smiles, molfile, svg};"
            "  } catch (e) {"
            "    window.__mkKetcherResult = {ok: false, error: String(e)};"
            "  }"
            "})();"
        )
        self._poll_confirm()

    def _poll_confirm(self) -> None:
        if self._confirm_tries > 100:
            self._confirm_failed("读取结构超时，请重试")
            return
        self._confirm_tries += 1
        self.web.page().runJavaScript(
            "window.__mkKetcherResult ? JSON.stringify(window.__mkKetcherResult) : ''",
            0,
            self._on_confirm_result,
        )

    def _on_confirm_result(self, payload) -> None:
        if not payload:
            self._result_timer.start(100)
            return
        try:
            data = json.loads(str(payload))
        except ValueError:
            self._confirm_failed("结构读取失败，请重试")
            return
        if not data.get("ok"):
            self._confirm_failed(data.get("error") or "结构读取失败，请重试")
            return
        smiles = str(data.get("smiles") or "").strip()
        if not smiles:
            self._confirm_failed("画布为空，请先绘制分子结构")
            return
        self.result_data = {
            "smiles": smiles,
            "molfile": str(data.get("molfile") or ""),
            "svg": str(data.get("svg") or ""),
        }
        self.status_label.setText("结构已读取")
        self.accept()

    def _confirm_failed(self, message: str) -> None:
        self.confirm_btn.setEnabled(True)
        self.confirm_btn.setText("使用该结构")
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {Color.red};")
        self._status_timer.start(1800)

    def _reset_status_style(self) -> None:
        self.status_label.setStyleSheet(f"color: {Color.secondary};")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_error(self, text: str) -> None:
        self.loading_spinner.stop()
        self.loading_label.setText(text)
        self.status_label.setText(text)
        self.confirm_btn.setEnabled(False)

    # ------------------------------------------------------------- 清理
    def _cleanup(self) -> None:
        self._poll_timer.stop()
        self._result_timer.stop()
        self._status_timer.stop()
        self.loading_spinner.stop()
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:  # noqa: BLE001
                pass
        thread = self._http_thread
        self._http_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def done(self, result: int) -> None:  # noqa: D401
        self._cleanup()
        super().done(result)
