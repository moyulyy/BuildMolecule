"""POSCAR 解析、居中与导出的离线单元测试。"""

from __future__ import annotations

import pytest

from mk_mole.services.poscar import (
    PoscarError,
    StructureData,
    center_poscar_in_cell,
    extract_poscar,
    parse_formula,
    parse_poscar,
)

BENZENE = """benzene
1.0
30.0 0.0 0.0
0.0 30.0 0.0
0.0 0.0 30.0
C H
6 6
Direct
0.46000000 0.50000000 0.50000000
0.54000000 0.50000000 0.50000000
0.48000000 0.55300000 0.50000000
0.52000000 0.55300000 0.50000000
0.48000000 0.44700000 0.50000000
0.52000000 0.44700000 0.50000000
0.43700000 0.50000000 0.50000000
0.56300000 0.50000000 0.50000000
0.47000000 0.58500000 0.50000000
0.53000000 0.58500000 0.50000000
0.47000000 0.41500000 0.50000000
0.53000000 0.41500000 0.50000000
"""


def test_extract_last_complete_block() -> None:
    reply = (
        "先给一个草稿：\n```poscar\n" + BENZENE.replace("benzene", "draft") + "```\n"
        "最终版本：\n```poscar\n" + BENZENE.replace("benzene", "final") + "```\n"
        "以上。"
    )
    extracted = extract_poscar(reply)
    assert extracted.startswith("final")
    assert "C H" in extracted


def test_parse_and_center() -> None:
    parsed = parse_poscar(BENZENE)
    assert parsed.formula() == "C6H6"
    assert parsed.atom_count == 12
    assert parsed.cell_lengths() == (30.0, 30.0, 30.0)

    shifted = BENZENE.replace("0.46000000", "0.61000000")
    centered = center_poscar_in_cell(shifted)
    coords = parse_poscar(centered).fractional
    for axis in range(3):
        low = min(c[axis] for c in coords)
        high = max(c[axis] for c in coords)
        assert abs((low + high) / 2 - 0.5) < 1e-6


def test_structure_and_exports() -> None:
    structure = StructureData.from_poscar(BENZENE, expected_formula="C₆H₆")
    assert structure.formula == "C6H6"
    assert structure.atom_count == 12
    assert structure.warnings == []
    assert round(structure.molecular_weight or 0, 1) == 78.1
    assert len(structure.bonds) >= 12

    xyz = structure.export_text("xyz")
    assert xyz.splitlines()[0] == "12"
    cif = structure.export_text("cif")
    assert "_cell_length_a   30.000000" in cif
    assert "C6" in cif
    sdf = structure.export_text("sdf")
    assert "V2000" in sdf
    pdb = structure.export_text("pdb")
    assert "CONECT" in pdb and pdb.rstrip().endswith("END")
    assert structure.export_text("poscar") == BENZENE


def test_formula_mismatch_warns() -> None:
    structure = StructureData.from_poscar(BENZENE, expected_formula="C2H6")
    assert structure.warnings
    assert "C2H6" in structure.warnings[0]


def test_truncated_poscar_is_rejected() -> None:
    with pytest.raises(PoscarError):
        parse_poscar("\n".join(BENZENE.splitlines()[:10]))


def test_formula_normalization() -> None:
    assert parse_formula("C₆H₆") == {"C": 6, "H": 6}
    assert parse_formula("CH3OH") == {"C": 1, "H": 4, "O": 1}
    assert parse_formula("C6H6+") == {}
