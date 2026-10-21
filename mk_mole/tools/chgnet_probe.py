#!/usr/bin/env python3
"""Probe a Python interpreter for a working CHGNet/PyTorch installation.

Runs inside the candidate interpreter and prints one JSON line prefixed with
``MKMOLE_CHGNET=``. The GUI process never imports torch/chgnet directly.
"""

from __future__ import annotations

import json


def main() -> int:
    info: dict = {"ok": True}
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda"] = bool(torch.cuda.is_available())
        info["device"] = "cuda" if info["cuda"] else "cpu"
        if info["cuda"]:
            info["gpu"] = torch.cuda.get_device_name(0)
    except Exception as exc:  # noqa: BLE001
        info = {"ok": False, "error": f"torch: {type(exc).__name__}: {exc}"}
        print("MKMOLE_CHGNET=" + json.dumps(info, ensure_ascii=False), flush=True)
        return 0
    try:
        import chgnet
        import pymatgen
        import ase

        info["chgnet"] = getattr(chgnet, "__version__", "unknown")
        info["pymatgen"] = getattr(pymatgen, "__version__", "unknown")
        info["ase"] = getattr(ase, "__version__", "unknown")
    except Exception as exc:  # noqa: BLE001
        info = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print("MKMOLE_CHGNET=" + json.dumps(info, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
