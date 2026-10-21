#!/usr/bin/env python3
"""Standalone CHGNet relaxation runner.

This script is executed by the separate CHGNet Python environment
(`chgnet_env`) — not by the GUI interpreter. It reads a POSCAR, runs CHGNet
with a fixed cell (the ``relax`` mode from the reference chgnet-opt tool),
and writes CONTCAR / relaxed.cif / result.json.

Reference behavior:
- StructOptimizer, CUDA when available, CPU fallback
- fixed cell for relax mode
- configurable max steps and fmax
"""

from __future__ import annotations

import argparse
import json
import traceback
import warnings
from pathlib import Path


def _write_result(path: Path, payload: dict) -> None:
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="CHGNet structure relaxation")
    parser.add_argument("--input", required=True, help="input POSCAR")
    parser.add_argument("--outdir", required=True, help="output directory")
    parser.add_argument("--max-steps", type=int, default=300)
    parser.add_argument("--fmax", type=float, default=0.05)
    parser.add_argument("--relax-cell", action="store_true",
                        help="also relax the lattice (bulk mode); default fixed cell")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    result_path = outdir / "result.json"
    contcar = outdir / "CONTCAR"
    cif_path = outdir / "relaxed.cif"

    try:
        import torch
        from chgnet.model import StructOptimizer
        from pymatgen.io.cif import CifWriter
        from pymatgen.io.vasp import Poscar

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[CHGNet] torch={torch.__version__} device={device}", flush=True)
        if device == "cuda":
            print(f"[CHGNet] gpu={torch.cuda.get_device_name(0)}", flush=True)

        poscar = Poscar.from_file(args.input)
        structure = poscar.structure
        print(
            f"[CHGNet] formula={structure.composition.reduced_formula} "
            f"atoms={len(structure)} volume={structure.lattice.volume:.3f}",
            flush=True,
        )
        print(
            f"[CHGNet] relax_cell={bool(args.relax_cell)} max_steps={args.max_steps} "
            f"fmax={args.fmax}",
            flush=True,
        )

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            relaxer = StructOptimizer(use_device=device)
            result = relaxer.relax(
                atoms=structure,
                fmax=float(args.fmax),
                steps=int(args.max_steps),
                relax_cell=bool(args.relax_cell),
                save_path=str(outdir / "relax.pkl"),
            )

        final_structure = result["final_structure"]
        energies = list(result["trajectory"].energies)
        Poscar(final_structure).write_file(str(contcar))
        CifWriter(final_structure).write_file(str(cif_path))

        final_energy = float(energies[-1]) if energies else None
        payload = {
            "ok": True,
            "device": device,
            "torch": torch.__version__,
            "chgnet": getattr(__import__("chgnet"), "__version__", "unknown"),
            "formula": final_structure.composition.reduced_formula,
            "atoms": len(final_structure),
            "steps": len(energies),
            "initial_energy": float(energies[0]) if energies else None,
            "final_energy": final_energy,
            "energy_change": (float(energies[-1] - energies[0]) if len(energies) > 1 else 0.0),
            "contcar": str(contcar),
            "cif": str(cif_path),
        }
        _write_result(result_path, payload)
        print(
            f"[CHGNet] done steps={payload['steps']} final_energy={payload['final_energy']}",
            flush=True,
        )
        print("[CHGNet] CONTCAR = " + str(contcar), flush=True)
        print("[CHGNet] CIF = " + str(cif_path), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _write_result(result_path, {"ok": False, "error": detail})
        print(f"[CHGNet] ERROR: {detail}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
