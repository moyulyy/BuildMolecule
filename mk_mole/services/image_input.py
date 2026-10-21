"""结构图片输入：读取、缩放并编码为 DeepSeek 可接受的 data URL。"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader


class ImageInputError(ValueError):
    pass


def load_structure_image(
    path: str | Path,
    *,
    max_dim: int = 1280,
    max_bytes: int = 6_000_000,
) -> tuple[str, QImage]:
    """返回 (data:image/png;base64,..., 缩放后的 QImage)，供预览与请求复用。"""
    file = Path(path)
    try:
        if file.stat().st_size > 12 * 1024 * 1024:
            raise ImageInputError("结构图片不能超过 12 MB")
    except OSError as exc:
        raise ImageInputError(f"读取图片失败：{exc}") from exc

    reader = QImageReader(str(file))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ImageInputError(f"无法读取图片：{reader.errorString()}")

    if max(image.width(), image.height()) > max_dim:
        image = image.scaled(
            max_dim,
            max_dim,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ImageInputError("无法创建图片缓冲区")
    try:
        ok = image.save(buffer, "PNG")
    finally:
        buffer.close()
    data = bytes(buffer.data())
    if not ok or not data:
        raise ImageInputError("图片编码失败，请换一张图片")
    if len(data) > max_bytes:
        raise ImageInputError("图片压缩后仍然过大，请换一张更小的图片")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}", image
