"""MDL molfile 摘要：读取原子数并按 Hill 顺序生成分子式。"""

from __future__ import annotations

import re
from collections import Counter

_ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$")


def molfile_summary(molfile: str) -> tuple[str, int]:
    """返回 (Hill 顺序分子式, 原子数)；解析失败返回 ("", 0)。"""
    lines = (molfile or "").splitlines()
    if len(lines) < 4:
        return "", 0
    try:
        atom_count = int(lines[3][0:3])
    except (ValueError, IndexError):
        return "", 0
    if atom_count <= 0:
        return "", 0

    elements: list[str] = []
    for line in lines[4:4 + atom_count]:
        symbol = line[31:34].strip() if len(line) >= 34 else ""
        if _ELEMENT_RE.match(symbol):
            elements.append(symbol)
    if len(elements) != atom_count:
        return "", 0

    counts = Counter(elements)
    order: list[str] = []
    if "C" in counts:
        order.append("C")
        if "H" in counts:
            order.append("H")
        order.extend(sorted(e for e in counts if e not in ("C", "H")))
    else:
        order.extend(sorted(counts))
    formula = "".join(
        element + (str(counts[element]) if counts[element] > 1 else "")
        for element in order
    )
    return formula, atom_count
