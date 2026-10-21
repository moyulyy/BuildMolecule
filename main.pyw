"""MK-MOLE 无控制台启动入口（Windows 可双击 / 用 pythonw 运行）。

使用 pythonw.exe 启动时不会出现黑色终端窗口；如果启动失败，会把完整的
traceback 写入便携数据目录下的 error.log，并弹出一个 Windows 错误对话框。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _data_dir() -> Path:
    override = os.environ.get("MK_MOLE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / "data"


def _report_startup_error(detail: str) -> None:
    try:
        base = _data_dir()
        base.mkdir(parents=True, exist_ok=True)
        (base / "error.log").write_text(detail, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                detail[-1800:],
                "MK-MOLE 启动失败",
                0x00000010,  # MB_ICONERROR
            )
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    try:
        from mk_mole.app import main

        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        _report_startup_error(traceback.format_exc())
        raise
