"""VASP POSCAR 解析、居中与结构格式转换。

LLM 的输出是不可信的：这里只接受元素行、数目行与坐标行完全自洽的 POSCAR，
并把分子整体平移到晶胞中央。渲染用距离法推断化学键后转成 SDF，下载时再按需
导出 POSCAR / CIF / XYZ / SDF / PDB。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

# 常见元素的共价半径（Å），用于距离法推断成键
COVALENT_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84, "C": 0.76,
    "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58, "Na": 1.66, "Mg": 1.41,
    "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39,
    "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Kr": 1.16,
    "Rb": 2.20, "Sr": 1.95, "Y": 1.90, "Zr": 1.75, "Nb": 1.64, "Mo": 1.54,
    "Tc": 1.47, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39, "Ag": 1.45, "Cd": 1.44,
    "In": 1.42, "Sn": 1.39, "Sb": 1.39, "Te": 1.38, "I": 1.39, "Xe": 1.40,
    "Cs": 2.44, "Ba": 2.15, "La": 2.07, "Ce": 2.04, "W": 1.62, "Pt": 1.36,
    "Au": 1.36, "Hg": 1.32, "Pb": 1.46, "Bi": 1.48,
}

ATOMIC_WEIGHTS = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81, "C": 12.011,
    "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180, "Na": 22.990,
    "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06,
    "Cl": 35.45, "Ar": 39.948, "K": 39.098, "Ca": 40.078, "Sc": 44.956,
    "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938, "Fe": 55.845,
    "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38, "Ga": 69.723,
    "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904, "Kr": 83.798,
    "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224, "Nb": 92.906,
    "Mo": 95.95, "Ru": 101.07, "Rh": 102.91, "Pd": 106.42, "Ag": 107.87,
    "Cd": 112.41, "In": 114.82, "Sn": 118.71, "Sb": 121.76, "Te": 127.60,
    "I": 126.90, "Xe": 131.29, "Cs": 132.91, "Ba": 137.33, "La": 138.91,
    "Ce": 140.12, "W": 183.84, "Pt": 195.08, "Au": 196.97, "Hg": 200.59,
    "Pb": 207.2, "Bi": 208.98,
}

ELEMENT_SYMBOL_RE = re.compile(r"^[A-Z][a-z]?$")
SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
FORMULA_TOKEN_RE = re.compile(r"([A-Z][a-z]?)(\d*\.?\d*)")


class PoscarError(ValueError):
    pass


@dataclass
class Atom:
    index: int
    element: str
    x: float
    y: float
    z: float


@dataclass
class ParsedPoscar:
    comment: str
    scale: float
    lattice: list[list[float]]
    symbols: list[str]
    counts: list[int]
    mode: str
    cartesian: list[list[float]]
    fractional: list[list[float]]
    selective: bool = False
    flags: list[list[str]] = field(default_factory=list)

    @property
    def elements(self) -> list[str]:
        out: list[str] = []
        for symbol, count in zip(self.symbols, self.counts):
            out.extend([symbol] * count)
        return out

    def atoms(self) -> list[Atom]:
        return [
            Atom(i + 1, el, x, y, z)
            for i, (el, (x, y, z)) in enumerate(zip(self.elements, self.cartesian))
        ]

    @property
    def atom_count(self) -> int:
        return len(self.cartesian)

    def cell_lengths(self) -> tuple[float, float, float]:
        return tuple(
            math.sqrt(sum(v * v for v in row)) for row in self.lattice  # type: ignore[return-value]
        )

    def formula(self) -> str:
        return formula_from_counts(self.symbols, self.counts)

    def molecular_weight(self) -> float | None:
        if not all(sym in ATOMIC_WEIGHTS for sym in self.symbols):
            return None
        return sum(ATOMIC_WEIGHTS[sym] * n for sym, n in zip(self.symbols, self.counts))


def normalize_formula(text: str) -> str:
    return (text or "").translate(SUBSCRIPT_MAP).replace(" ", "").strip()


def parse_formula(formula: str) -> dict[str, int]:
    """解析简单分子式（支持 Unicode 下标与小数，如 C6H6、CO₂、C6H12O6）。"""
    text = normalize_formula(formula)
    if not text:
        return {}
    counts: dict[str, int] = {}
    pos = 0
    for match in FORMULA_TOKEN_RE.finditer(text):
        if match.start() != pos:
            return {}
        symbol, number = match.group(1), match.group(2)
        try:
            count = int(float(number)) if number else 1
        except ValueError:
            return {}
        if count <= 0:
            return {}
        counts[symbol] = counts.get(symbol, 0) + count
        pos = match.end()
    if pos != len(text):
        return {}
    return counts


def formula_from_counts(symbols: list[str], counts: list[int]) -> str:
    parts = []
    for sym, n in zip(symbols, counts):
        parts.append(sym if n == 1 else f"{sym}{n}")
    return "".join(parts)


def _locate(lines: list[str], start: int = 0) -> dict | None:
    if len(lines) - start < 8:
        return None
    try:
        scale = float(lines[start + 1].split()[0])
        lattice = [[float(x) for x in lines[start + k].split()[:3]] for k in (2, 3, 4)]
    except (ValueError, IndexError):
        return None
    if any(len(row) < 3 for row in lattice):
        return None
    symbols = lines[start + 5].split()
    if not symbols or not all(ELEMENT_SYMBOL_RE.match(s) for s in symbols):
        return None
    try:
        counts = [int(float(x)) for x in lines[start + 6].split()]
    except (ValueError, IndexError):
        return None
    if len(counts) != len(symbols) or any(c <= 0 for c in counts):
        return None
    i = start + 7
    selective = False
    if i < len(lines) and lines[i].lower().startswith("s"):
        selective = True
        i += 1
    if i >= len(lines):
        return None
    mode = lines[i].lower()
    if not (mode.startswith("d") or mode.startswith("c")):
        return None
    first = i + 1
    total = sum(counts)
    j = first
    flags: list[list[str]] = []
    while j < len(lines) and j - first < total:
        parts = lines[j].split()
        if len(parts) < 3:
            break
        try:
            for value in parts[:3]:
                float(value)
        except ValueError:
            break
        flags.append(parts[3:])
        j += 1
    if j - first != total:
        return None
    return {
        "start": start,
        "end": j,
        "scale": scale,
        "lattice": lattice,
        "symbols": symbols,
        "counts": counts,
        "mode": mode,
        "first": first,
        "total": total,
        "selective": selective,
        "flags": flags,
    }


def _parse_at(lines: list[str], start: int) -> str:
    loc = _locate(lines, start)
    if not loc:
        return ""
    return "\n".join(lines[start:loc["end"]]) + "\n"


def _extract_block(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    found = ""
    for start in range(len(lines)):
        block = _parse_at(lines, start)
        if block:
            found = block
    return found


def extract_poscar(reply: str) -> str:
    """从 LLM 回复中提取最后一个完整 POSCAR（终稿通常在草稿之后）。"""
    if not reply:
        return ""
    fences = [
        (m.group(1) or "", m.group(2) or "")
        for m in re.finditer(r"```([^\n`]*)\n([\s\S]*?)```", reply)
    ]
    for tagged_only in (True, False):
        for tag, body in reversed(fences):
            if tagged_only and not ("poscar" in tag.lower() or "vasp" in tag.lower()):
                continue
            block = _extract_block(body)
            if block:
                return block.strip()
    return _extract_block(reply).strip()


def _invert3(m: list[list[float]]) -> list[list[float]] | None:
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-10:
        return None
    inv = 1.0 / det
    return [
        [(e * i - f * h) * inv, (c * h - b * i) * inv, (b * f - c * e) * inv],
        [(f * g - d * i) * inv, (a * i - c * g) * inv, (c * d - a * f) * inv],
        [(d * h - e * g) * inv, (b * g - a * h) * inv, (a * e - b * d) * inv],
    ]


def _mat_vec(m: list[list[float]], v: list[float]) -> list[float]:
    return [sum(m[r][k] * v[k] for k in range(3)) for r in range(3)]


def parse_poscar(text: str) -> ParsedPoscar:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    loc = _locate(lines, 0)
    if not loc:
        raise PoscarError("POSCAR 格式不完整：元素行、原子数行与坐标行无法对应")
    comment = lines[0]
    scale = loc["scale"]
    lattice = [[value * scale for value in row] for row in loc["lattice"]]
    first = loc["first"]
    coords: list[list[float]] = []
    for ln in lines[first:first + loc["total"]]:
        parts = ln.split()
        coords.append([float(parts[0]), float(parts[1]), float(parts[2])])
    if loc["mode"].startswith("d"):
        fractional = coords
        cartesian = [_mat_vec(lattice, p) for p in coords]
    else:
        cartesian = [[value * scale for value in p] for p in coords]
        inv = _invert3(lattice)
        if not inv:
            raise PoscarError("晶格矩阵不可逆，无法解析 Cartesian 坐标")
        fractional = [_mat_vec(inv, p) for p in cartesian]
    return ParsedPoscar(
        comment=comment,
        scale=scale,
        lattice=lattice,
        symbols=list(loc["symbols"]),
        counts=list(loc["counts"]),
        mode="direct" if loc["mode"].startswith("d") else "cartesian",
        cartesian=cartesian,
        fractional=fractional,
        selective=loc["selective"],
        flags=loc["flags"],
    )


def center_poscar_in_cell(poscar_text: str) -> str:
    """把结构整体平移到晶胞中央，避免分子贴着盒底。"""
    lines = [ln.strip() for ln in (poscar_text or "").splitlines() if ln.strip()]
    loc = _locate(lines, 0)
    if not loc:
        return poscar_text
    first = loc["first"]
    try:
        parsed = parse_poscar(poscar_text)
    except PoscarError:
        return poscar_text

    lo = [min(p[k] for p in parsed.fractional) for k in range(3)]
    hi = [max(p[k] for p in parsed.fractional) for k in range(3)]
    shift = [0.5 - (lo[k] + hi[k]) / 2.0 for k in range(3)]
    wrap = max(hi[k] - lo[k] for k in range(3)) <= 0.5
    for idx, frac in enumerate(parsed.fractional):
        values = [frac[k] + shift[k] for k in range(3)]
        if wrap:
            values = [v % 1.0 for v in values]
        tail = ("  " + "  ".join(parsed.flags[idx])) if parsed.selective and idx < len(parsed.flags) else ""
        lines[first + idx] = "  ".join(f"{v:.8f}" for v in values) + tail
    return "\n".join(lines) + "\n"


def infer_bonds(atoms: list[Atom]) -> list[tuple[int, int, int]]:
    bonds: list[tuple[int, int, int]] = []
    n = len(atoms)
    for i in range(n):
        ai = atoms[i]
        ri = COVALENT_RADII.get(ai.element, 0.77)
        for j in range(i + 1, n):
            aj = atoms[j]
            rj = COVALENT_RADII.get(aj.element, 0.77)
            dx = ai.x - aj.x
            dy = ai.y - aj.y
            dz = ai.z - aj.z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if 0.35 < dist < 1.25 * (ri + rj):
                bonds.append((i + 1, j + 1, 1))
    return bonds


def atoms_to_sdf(atoms: list[Atom], bonds: list[tuple[int, int, int]], title: str) -> str:
    lines = [title or "MK-MOLE", "  MK-MOLE  3D", ""]
    lines.append(f"{len(atoms):3d}{len(bonds):3d}  0  0  0  0            999 V2000")
    for atom in atoms:
        lines.append(
            f"{atom.x:10.4f}{atom.y:10.4f}{atom.z:10.4f} {atom.element:<3s}"
            " 0  0  0  0  0  0  0  0  0  0  0  0"
        )
    for a, b, order in bonds:
        lines.append(f"{a:3d}{b:3d}{order:3d}  0  0  0  0")
    lines.append("M  END")
    return "\n".join(lines) + "\n"


def atoms_to_xyz(atoms: list[Atom], title: str) -> str:
    lines = [str(len(atoms)), title or "MK-MOLE"]
    for atom in atoms:
        lines.append(f"{atom.element:<2s} {atom.x:14.8f} {atom.y:14.8f} {atom.z:14.8f}")
    return "\n".join(lines) + "\n"


def atoms_to_pdb(atoms: list[Atom], bonds: list[tuple[int, int, int]], title: str) -> str:
    lines = [f"COMPND    {title or 'MK-MOLE'}"]
    for atom in atoms:
        name = f"{atom.element:<2s}"
        lines.append(
            f"ATOM  {atom.index:5d} {name:>2s}   MOL A   1    "
            f"{atom.x:8.3f}{atom.y:8.3f}{atom.z:8.3f}  1.00  0.00          {atom.element:>2s}"
        )
    for a, b, _order in bonds:
        lines.append(f"CONECT{a:5d}{b:5d}")
    lines.append("END")
    return "\n".join(lines) + "\n"


def poscar_to_cif(parsed: ParsedPoscar, title: str) -> str:
    a, b, c = parsed.cell_lengths()
    lines = [
        f"data_{re.sub(r'[^A-Za-z0-9_]+', '_', title or 'MKMOLE')}",
        f"_chemical_formula_sum   '{parsed.formula()}'",
        f"_cell_length_a   {a:.6f}",
        f"_cell_length_b   {b:.6f}",
        f"_cell_length_c   {c:.6f}",
        "_cell_angle_alpha   90.000000",
        "_cell_angle_beta    90.000000",
        "_cell_angle_gamma   90.000000",
        "_symmetry_space_group_name_H-M   'P 1'",
        "_symmetry_Int_Tables_number   1",
        "loop_",
        "_symmetry_equiv_pos_as_xyz",
        "  'x, y, z'",
        "loop_",
        "_atom_site_label",
        "_atom_site_type_symbol",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_occupancy",
    ]
    for idx, (element, frac) in enumerate(zip(parsed.elements, parsed.fractional), start=1):
        lines.append(
            f"{element}{idx}  {element}  {frac[0]:.8f}  {frac[1]:.8f}  {frac[2]:.8f}  1.0000"
        )
    return "\n".join(lines) + "\n"


@dataclass
class StructureData:
    poscar: str
    sdf: str
    atoms: list[Atom]
    bonds: list[tuple[int, int, int]]
    elements: list[str]
    formula: str
    atom_count: int
    cell: tuple[float, float, float]
    molecular_weight: float | None = None
    source: str = "DeepSeek"
    warnings: list[str] = field(default_factory=list)
    parsed: ParsedPoscar | None = None

    @classmethod
    def from_poscar(cls, poscar_text: str, *, source: str = "DeepSeek",
                    expected_formula: str = "") -> "StructureData":
        parsed = parse_poscar(poscar_text)
        atoms = parsed.atoms()
        bonds = infer_bonds(atoms)
        elements = list(dict.fromkeys(parsed.elements))
        warnings: list[str] = []
        if expected_formula:
            expected = parse_formula(expected_formula)
            actual = parse_formula(parsed.formula())
            if expected and expected != actual:
                warnings.append(
                    f"LLM 生成组成 {parsed.formula()} 与输入分子式 {normalize_formula(expected_formula)} 不一致"
                )
        return cls(
            poscar=poscar_text,
            sdf=atoms_to_sdf(atoms, bonds, parsed.comment),
            atoms=atoms,
            bonds=bonds,
            elements=elements,
            formula=parsed.formula(),
            atom_count=parsed.atom_count,
            cell=parsed.cell_lengths(),
            molecular_weight=parsed.molecular_weight(),
            source=source,
            warnings=warnings,
            parsed=parsed,
        )

    def export_text(self, fmt: str, *, title: str = "") -> str:
        fmt = fmt.lower()
        if fmt in ("poscar", "vasp"):
            return self.poscar
        if fmt in ("sdf", "mol"):
            return self.sdf
        if fmt == "xyz":
            return atoms_to_xyz(self.atoms, title or self.formula)
        if fmt == "pdb":
            return atoms_to_pdb(self.atoms, self.bonds, title or self.formula)
        if fmt == "cif":
            if not self.parsed:
                raise PoscarError("缺少晶格数据，无法导出 CIF")
            return poscar_to_cif(self.parsed, title or self.formula)
        raise ValueError(f"不支持的格式：{fmt}")

    def save(self, path: str | Path, fmt: str) -> None:
        Path(path).write_text(self.export_text(fmt), encoding="utf-8", newline="\n")


POSCAR_RETRY_HINT = (
    "上一轮没有输出完整、可解析的 POSCAR（可能思考过长或被截断）。"
    "现在立即直接给出最终结果，只输出一个 ```poscar 代码块，块内为完整 VASP5 POSCAR："
    "注释行 / 1.0 / 三行 30 Å 晶格 / 元素行 / 数目行 / Direct / 逐行分数坐标。"
    "必须保持与用户提供的 molfile/SMILES/图片一致的原子种类与连接；"
    "每个元素的原子数要精确；所有坐标在 0~1 且分子居中；"
    "不要解释、不要自问自答、不要再演算坐标、不要输出第二个代码块或 CIF/XYZ。"
    "如果信息不足，输出一个完整的最接近结构，绝不能输出半截 POSCAR。"
)
