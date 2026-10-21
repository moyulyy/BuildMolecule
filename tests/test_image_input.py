"""结构图片编码测试（离屏 Qt）。"""

from __future__ import annotations

import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mk_mole.services.image_input import ImageInputError, load_structure_image  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_png_roundtrip(tmp_path) -> None:
    _app()
    image = QImage(64, 32, QImage.Format.Format_RGB32)
    image.fill(QColor("#3366ff"))
    path = tmp_path / "structure.png"
    assert image.save(str(path), "PNG")

    data_url, loaded = load_structure_image(path)
    assert data_url.startswith("data:image/png;base64,")
    assert loaded.width() == 64 and loaded.height() == 32
    payload = base64.b64decode(data_url.split(",", 1)[1])
    assert payload.startswith(b"\x89PNG")


def test_large_image_is_scaled(tmp_path) -> None:
    _app()
    image = QImage(2000, 1000, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    path = tmp_path / "large.png"
    assert image.save(str(path), "PNG")

    _data_url, loaded = load_structure_image(path, max_dim=640)
    assert max(loaded.width(), loaded.height()) == 640
    assert loaded.width() == 640 and loaded.height() == 320


def test_invalid_image_is_rejected(tmp_path) -> None:
    _app()
    path = tmp_path / "not-an-image.png"
    path.write_text("not an image", encoding="utf-8")
    try:
        load_structure_image(path)
    except ImageInputError as exc:
        assert "无法读取图片" in str(exc)
    else:
        raise AssertionError("应当抛出 ImageInputError")
